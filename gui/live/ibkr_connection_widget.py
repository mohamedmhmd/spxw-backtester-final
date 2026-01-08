"""
IBKR Connection Widget - UI for managing IBKR connection.

Provides controls for:
- Connecting/disconnecting to TWS or IB Gateway
- Selecting paper vs live trading mode
- Displaying connection status
- Showing account information

Usage:
    from gui.live.ibkr_connection_widget import IBKRConnectionWidget
    
    widget = IBKRConnectionWidget()
    widget.connection_established.connect(on_connected)
    widget.connection_lost.connect(on_disconnected)
"""

import logging
import asyncio
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QComboBox,
    QGroupBox, QFrame, QMessageBox, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QFont

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.ibkr_config import IBKRConfig, IBKRConnectionMode
from execution.ibkr_connection import IBKRConnection, ConnectionState
from guardrails.kill_switch import KillSwitch

logger = logging.getLogger(__name__)


class ConnectionWorker(QThread):
    """Worker thread for async connection operations"""
    
    finished = pyqtSignal(bool, str)  # success, message
    account_info = pyqtSignal(dict)   # account information
    
    def __init__(self, connection: IBKRConnection, action: str):
        super().__init__()
        self.connection = connection
        self.action = action  # 'connect' or 'disconnect'
    
    def run(self):
        """Run the connection operation"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            if self.action == 'connect':
                success = loop.run_until_complete(self.connection.connect())
                if success:
                    # Get account info
                    account_summary = self.connection.get_account_summary()
                    self.account_info.emit(account_summary)
                    self.finished.emit(True, "Connected successfully")
                else:
                    self.finished.emit(False, "Connection failed")
            else:
                self.connection.disconnect()
                self.finished.emit(True, "Disconnected")
        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            loop.close()


class IBKRConnectionWidget(QWidget):
    """
    Widget for managing IBKR connection.
    
    Signals:
        connection_established: Emitted when connected to IBKR
        connection_lost: Emitted when disconnected from IBKR
        connection_changed: Emitted with IBKRConnection instance on any change
    """
    
    # Signals
    connection_established = pyqtSignal(object)  # IBKRConnection
    connection_lost = pyqtSignal()
    connection_changed = pyqtSignal(object, bool)  # IBKRConnection, is_connected
    
    def __init__(self, kill_switch: KillSwitch, parent=None):
        super().__init__(parent)
        self.kill_switch = kill_switch
        self.connection: Optional[IBKRConnection] = None
        self.worker: Optional[ConnectionWorker] = None
        
        # Status update timer
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Connection Settings Group
        settings_group = QGroupBox("IBKR Connection Settings")
        settings_layout = QFormLayout()
        
        # Host input
        self.host_input = QLineEdit("127.0.0.1")
        self.host_input.setPlaceholderText("127.0.0.1")
        settings_layout.addRow("Host:", self.host_input)
        
        # Port selection with preset buttons
        port_layout = QHBoxLayout()
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(7497)
        port_layout.addWidget(self.port_input)
        
        # Quick port buttons
        tws_paper_btn = QPushButton("TWS Paper (7497)")
        tws_paper_btn.setFixedWidth(120)
        tws_paper_btn.clicked.connect(lambda: self.port_input.setValue(7497))
        port_layout.addWidget(tws_paper_btn)
        
        tws_live_btn = QPushButton("TWS Live (7496)")
        tws_live_btn.setFixedWidth(120)
        tws_live_btn.clicked.connect(lambda: self.port_input.setValue(7496))
        tws_live_btn.setStyleSheet("color: red;")
        port_layout.addWidget(tws_live_btn)
        
        settings_layout.addRow("Port:", port_layout)
        
        # Client ID
        self.client_id_input = QSpinBox()
        self.client_id_input.setRange(0, 999)
        self.client_id_input.setValue(1)
        self.client_id_input.setToolTip("Use different IDs for different applications")
        settings_layout.addRow("Client ID:", self.client_id_input)
        
        # Trading mode selection
        mode_layout = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("📋 Paper Trading", IBKRConnectionMode.PAPER)
        self.mode_combo.addItem("🔴 LIVE Trading", IBKRConnectionMode.LIVE)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        
        # Readonly checkbox
        self.readonly_check = QCheckBox("Read-only (no orders)")
        self.readonly_check.setToolTip("If checked, cannot place orders - useful for monitoring")
        mode_layout.addWidget(self.readonly_check)
        
        settings_layout.addRow("Mode:", mode_layout)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Connection buttons
        button_layout = QHBoxLayout()
        
        self.connect_btn = QPushButton("🔌 Connect")
        self.connect_btn.setMinimumHeight(40)
        self.connect_btn.setFont(QFont('Arial', 11, QFont.Weight.Bold))
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        button_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("⛔ Disconnect")
        self.disconnect_btn.setMinimumHeight(40)
        self.disconnect_btn.setFont(QFont('Arial', 11, QFont.Weight.Bold))
        self.disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #e53935;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        button_layout.addWidget(self.disconnect_btn)
        
        layout.addLayout(button_layout)
        
        # Status display
        status_group = QGroupBox("Connection Status")
        status_layout = QVBoxLayout()
        
        # Status indicator
        status_row = QHBoxLayout()
        self.status_indicator = QLabel("●")
        self.status_indicator.setFont(QFont('Arial', 24))
        self.status_indicator.setStyleSheet("color: gray;")
        status_row.addWidget(self.status_indicator)
        
        self.status_label = QLabel("Disconnected")
        self.status_label.setFont(QFont('Arial', 12, QFont.Weight.Bold))
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_layout.addLayout(status_row)
        
        # Account info labels
        self.account_label = QLabel("Account: -")
        status_layout.addWidget(self.account_label)
        
        self.nlv_label = QLabel("Net Liquidation: -")
        status_layout.addWidget(self.nlv_label)
        
        self.bp_label = QLabel("Buying Power: -")
        status_layout.addWidget(self.bp_label)
        
        self.pnl_label = QLabel("Today's P&L: -")
        status_layout.addWidget(self.pnl_label)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Warning label for live trading
        self.live_warning = QLabel(
            "⚠️ WARNING: Live trading mode will use real money!\n"
            "Make sure you understand the risks."
        )
        self.live_warning.setStyleSheet("""
            QLabel {
                color: red;
                background-color: #ffebee;
                padding: 10px;
                border: 2px solid red;
                border-radius: 5px;
            }
        """)
        self.live_warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.live_warning.setVisible(False)
        layout.addWidget(self.live_warning)
        
        layout.addStretch()
    
    def _on_mode_changed(self, index):
        """Handle trading mode change"""
        mode = self.mode_combo.currentData()
        
        if mode == IBKRConnectionMode.LIVE:
            self.live_warning.setVisible(True)
            self.port_input.setValue(7496)  # Switch to live port
            
            # Show extra warning
            QMessageBox.warning(
                self,
                "⚠️ Live Trading Warning",
                "You have selected LIVE trading mode.\n\n"
                "• Real money will be at risk\n"
                "• Orders will execute in live markets\n"
                "• Make sure you have tested in paper mode first\n\n"
                "Proceed with extreme caution!"
            )
        else:
            self.live_warning.setVisible(False)
            self.port_input.setValue(7497)  # Switch to paper port
    
    def _on_connect_clicked(self):
        """Handle connect button click"""
        # Validate settings
        host = self.host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Error", "Please enter a host address")
            return
        
        # Build config
        mode = self.mode_combo.currentData()
        config = IBKRConfig(
            host=host,
            port=self.port_input.value(),
            client_id=self.client_id_input.value(),
            readonly=self.readonly_check.isChecked(),
            mode=mode
        )
        
        # Validate config
        is_valid, error = config.validate()
        if not is_valid:
            QMessageBox.warning(self, "Configuration Error", error)
            return
        
        # Extra confirmation for live mode
        if mode == IBKRConnectionMode.LIVE:
            result = QMessageBox.question(
                self,
                "⚠️ Confirm Live Trading",
                "You are about to connect to LIVE trading.\n\n"
                "Are you absolutely sure you want to proceed?\n\n"
                "This will allow REAL orders to be placed!",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        
        # Create connection
        self.connection = IBKRConnection(config, self.kill_switch)
        
        # Update UI
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Connecting...")
        self._update_status_display(ConnectionState.CONNECTING)
        
        # Start connection in worker thread
        self.worker = ConnectionWorker(self.connection, 'connect')
        self.worker.finished.connect(self._on_connect_finished)
        self.worker.account_info.connect(self._on_account_info)
        self.worker.start()
    
    def _on_connect_finished(self, success: bool, message: str):
        """Handle connection attempt result"""
        if success:
            self.connect_btn.setText("🔌 Connect")
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            
            self._update_status_display(ConnectionState.CONNECTED)
            
            # Start status timer
            self._status_timer.start(5000)  # Update every 5 seconds
            
            # Emit signal
            self.connection_established.emit(self.connection)
            self.connection_changed.emit(self.connection, True)
            
            logger.info("IBKR connection established via UI")
        else:
            self.connect_btn.setText("🔌 Connect")
            self.connect_btn.setEnabled(True)
            
            self._update_status_display(ConnectionState.ERROR)
            
            QMessageBox.critical(
                self,
                "Connection Failed",
                f"Failed to connect to IBKR:\n\n{message}\n\n"
                "Make sure TWS or IB Gateway is running and API is enabled."
            )
    
    def _on_account_info(self, info: dict):
        """Handle account information"""
        self.account_label.setText(f"Account: {info.get('account', '-')}")
        
        nlv = info.get('net_liquidation', 0)
        self.nlv_label.setText(f"Net Liquidation: ${nlv:,.2f}")
        
        bp = info.get('buying_power', 0)
        self.bp_label.setText(f"Buying Power: ${bp:,.2f}")
        
        pnl = info.get('unrealized_pnl', 0) + info.get('realized_pnl', 0)
        color = "green" if pnl >= 0 else "red"
        self.pnl_label.setText(f"Today's P&L: <span style='color:{color}'>${pnl:,.2f}</span>")
    
    def _on_disconnect_clicked(self):
        """Handle disconnect button click"""
        if self.connection:
            self.connection.disconnect()
            
            self._status_timer.stop()
            
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            
            self._update_status_display(ConnectionState.DISCONNECTED)
            
            # Clear account info
            self.account_label.setText("Account: -")
            self.nlv_label.setText("Net Liquidation: -")
            self.bp_label.setText("Buying Power: -")
            self.pnl_label.setText("Today's P&L: -")
            
            # Emit signals
            self.connection_lost.emit()
            self.connection_changed.emit(self.connection, False)
            
            logger.info("IBKR disconnected via UI")
    
    def _update_status(self):
        """Update status from connection"""
        if self.connection and self.connection.is_connected():
            try:
                account_summary = self.connection.get_account_summary()
                self._on_account_info(account_summary)
            except Exception as e:
                logger.warning(f"Error updating account info: {e}")
    
    def _update_status_display(self, state: ConnectionState):
        """Update the status display based on connection state"""
        if state == ConnectionState.CONNECTED:
            self.status_indicator.setStyleSheet("color: #4caf50;")  # Green
            mode = self.connection.config.get_display_mode() if self.connection else ""
            self.status_label.setText(f"Connected ({mode})")
        elif state == ConnectionState.CONNECTING:
            self.status_indicator.setStyleSheet("color: #ff9800;")  # Orange
            self.status_label.setText("Connecting...")
        elif state == ConnectionState.RECONNECTING:
            self.status_indicator.setStyleSheet("color: #ff9800;")
            self.status_label.setText("Reconnecting...")
        elif state == ConnectionState.ERROR:
            self.status_indicator.setStyleSheet("color: #f44336;")  # Red
            self.status_label.setText("Connection Error")
        else:
            self.status_indicator.setStyleSheet("color: gray;")
            self.status_label.setText("Disconnected")
    
    def get_connection(self) -> Optional[IBKRConnection]:
        """Get the current IBKR connection"""
        return self.connection
    
    def is_connected(self) -> bool:
        """Check if connected to IBKR"""
        return self.connection is not None and self.connection.is_connected()
