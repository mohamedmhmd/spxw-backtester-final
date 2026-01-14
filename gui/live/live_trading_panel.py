"""
Live Trading Panel - Complete UI for live trading mode WITH IBKR integration.

This version includes ACTUAL IBKR connection functionality.
"""

import logging
import asyncio
from typing import Optional, Dict, List
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QSplitter,
    QGroupBox, QLabel, QPushButton, QFrame, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QTextEdit, QMessageBox,
    QSizePolicy, QGridLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, pyqtSlot
from PyQt6.QtGui import QFont, QColor

from guardrails.approval_gate import ApprovalGate

logger = logging.getLogger(__name__)

# Import IBKR components from Milestone 1
try:
    from execution.ibkr_connection import IBKRConnection, ConnectionState
    from config.ibkr_config import IBKRConfig, IBKRConnectionMode
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    logger.warning("IBKR components not available - connection disabled")


from engine.ibrkr_manager import IBKRConnectionManager

class LiveTradingPanel(QWidget):
    """
    Main panel for live trading - REPLACES backtest UI completely.
    Now with ACTUAL IBKR connection functionality.
    """
    
    # Signals
    connection_changed = pyqtSignal(bool)
    ready_to_trade = pyqtSignal(bool)
    trade_executed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Components
        self.kill_switch = None
        self.ibkr_connection: Optional['IBKRConnection'] = None
        self.risk_manager = None
        self.approval_gate = ApprovalGate()
        self.trade_constructor = None
        self._polygon_connected = False

        # Connection manager
        self._connection_manager: Optional[IBKRConnectionManager] = None

        # State
        self._is_connected = False
        self._account_info = {}
        self._executed_trades = []
        self._ic1_trade = None
        self._ic2_trade = None
        
        self._setup_ui()
        
        # Update timer
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._update_displays)
        self._update_timer.start(2000)
    
    def set_components(self, kill_switch, ibkr_connection=None, risk_manager=None, 
                       approval_gate=None, trade_constructor=None):
        """Set the live trading components."""
        self.kill_switch = kill_switch
        self.ibkr_connection = ibkr_connection
        self.risk_manager = risk_manager
        self.approval_gate = approval_gate
        self.trade_constructor = trade_constructor
        
        if self.kill_switch:
            self.kill_switch.status_changed.connect(self._on_kill_switch_changed)
            self._update_kill_switch_display()
        
        if self.approval_gate:
            self.approval_gate.trade_pending.connect(self._on_trade_pending)
            self.approval_gate.trade_approved.connect(self._on_trade_approved)
            self.approval_gate.trade_rejected.connect(self._on_trade_rejected)
            self.approval_gate.countdown_tick.connect(self._on_countdown_tick)
    
    def _setup_ui(self):
        """Set up the complete UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # TOP: KILL SWITCH
        self.kill_switch_frame = self._create_kill_switch_section()
        main_layout.addWidget(self.kill_switch_frame)
        
        # STATUS BAR
        self.status_bar_frame = self._create_status_bar()
        main_layout.addWidget(self.status_bar_frame)
        
        # MAIN CONTENT (Split left/right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)
        
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setSizes([400, 600])
        main_layout.addWidget(splitter, 1)
    
    def _create_kill_switch_section(self) -> QFrame:
        """Create the prominent kill switch section"""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        frame.setLineWidth(2)
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.kill_button = QPushButton("⚠️ KILL SWITCH")
        self.kill_button.setMinimumSize(200, 70)
        self.kill_button.setFont(QFont('Arial', 16, QFont.Weight.Bold))
        self.kill_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kill_button.clicked.connect(self._on_kill_switch_clicked)
        layout.addWidget(self.kill_button)
        
        status_layout = QVBoxLayout()
        self.kill_status_label = QLabel("Status: CHECKING...")
        self.kill_status_label.setFont(QFont('Arial', 12, QFont.Weight.Bold))
        status_layout.addWidget(self.kill_status_label)
        
        self.kill_detail_label = QLabel("")
        self.kill_detail_label.setFont(QFont('Arial', 9))
        status_layout.addWidget(self.kill_detail_label)
        
        layout.addLayout(status_layout)
        layout.addStretch()
        
        self.cancel_all_btn = QPushButton("🚫 Cancel All Orders")
        self.cancel_all_btn.setMinimumSize(150, 50)
        self.cancel_all_btn.setFont(QFont('Arial', 11, QFont.Weight.Bold))
        self.cancel_all_btn.clicked.connect(self._on_cancel_all)
        self.cancel_all_btn.setStyleSheet("""
            QPushButton { background-color: #ff9800; color: white; border-radius: 5px; }
            QPushButton:hover { background-color: #f57c00; }
        """)
        layout.addWidget(self.cancel_all_btn)
        
        return frame
    
    def _create_status_bar(self) -> QFrame:
        """Create the status bar"""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 5, 10, 5)
        
        self.mode_label = QLabel("📋 PAPER TRADING")
        self.mode_label.setFont(QFont('Arial', 11, QFont.Weight.Bold))
        layout.addWidget(self.mode_label)
        
        layout.addWidget(QLabel("|"))
        
        self.connection_status_label = QLabel("🔴 Disconnected")
        layout.addWidget(self.connection_status_label)
        
        layout.addWidget(QLabel("|"))
        
        self.account_label = QLabel("Account: -")
        layout.addWidget(self.account_label)
        
        layout.addWidget(QLabel("|"))
        
        self.nlv_label = QLabel("NLV: -")
        layout.addWidget(self.nlv_label)
        
        layout.addStretch()
        
        self.daily_pnl_label = QLabel("Daily P&L: $0.00")
        self.daily_pnl_label.setFont(QFont('Arial', 11, QFont.Weight.Bold))
        layout.addWidget(self.daily_pnl_label)

        # Add Polygon status indicator
        self.polygon_status_label = QLabel("Polygon: Disconnected")
        self.polygon_status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.polygon_status_label)
        
        return frame
    
    def _update_polygon_status(self, connected: bool):
        """Update Polygon connection status display"""
        self._polygon_connected = connected
        if connected:
            self.polygon_status_label.setText("Polygon: 🟢 Live")
            self.polygon_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.polygon_status_label.setText("Polygon: 🔴 Disconnected")
            self.polygon_status_label.setStyleSheet("color: red;")

    
    def _create_left_panel(self) -> QWidget:
        """Create the left configuration panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        scroll_layout.addWidget(self._create_connection_group())
        scroll_layout.addWidget(self._create_strategy_group())
        scroll_layout.addWidget(self._create_risk_limits_group())
        scroll_layout.addWidget(self._create_execute_group())
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        return panel
    
    def _create_connection_group(self) -> QGroupBox:
        """Create IBKR connection controls - NOW FUNCTIONAL"""
        group = QGroupBox("🔌 IBKR Connection")
        layout = QGridLayout()
        
        # Check if IBKR is available
        if not IBKR_AVAILABLE:
            warning = QLabel("⚠️ IBKR components not installed.\nRun: pip install ib_insync")
            warning.setStyleSheet("color: red;")
            layout.addWidget(warning, 0, 0, 1, 2)
            group.setLayout(layout)
            return group
        
        layout.addWidget(QLabel("Host:"), 0, 0)
        self.host_input = QComboBox()
        self.host_input.setEditable(True)
        self.host_input.addItem("127.0.0.1")
        layout.addWidget(self.host_input, 0, 1)
        
        layout.addWidget(QLabel("Port:"), 1, 0)
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(7497)
        layout.addWidget(self.port_input, 1, 1)
        
        # Quick port buttons
        port_btns = QHBoxLayout()
        paper_btn = QPushButton("Paper (7497)")
        paper_btn.clicked.connect(lambda: self._set_port(7497, "paper"))
        port_btns.addWidget(paper_btn)
        
        live_btn = QPushButton("Live (7496)")
        live_btn.clicked.connect(lambda: self._set_port(7496, "live"))
        live_btn.setStyleSheet("color: red; font-weight: bold;")
        port_btns.addWidget(live_btn)
        layout.addLayout(port_btns, 2, 0, 1, 2)
        
        layout.addWidget(QLabel("Client ID:"), 3, 0)
        self.client_id_input = QSpinBox()
        self.client_id_input.setRange(0, 999)
        self.client_id_input.setValue(1)
        layout.addWidget(self.client_id_input, 3, 1)
        
        # Read-only mode checkbox
        self.readonly_check = QCheckBox("Read-Only Mode (no orders)")
        self.readonly_check.setChecked(True)  # Default to read-only for safety
        layout.addWidget(self.readonly_check, 4, 0, 1, 2)
        
        # Connect/Disconnect buttons
        btn_layout = QHBoxLayout()
        
        self.connect_btn = QPushButton("🔌 Connect")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        self.connect_btn.setStyleSheet("""
            QPushButton { background-color: #4caf50; color: white; padding: 10px; font-weight: bold; }
            QPushButton:hover { background-color: #43a047; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        btn_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("⛔ Disconnect")
        self.disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setStyleSheet("""
            QPushButton { background-color: #f44336; color: white; padding: 10px; font-weight: bold; }
            QPushButton:hover { background-color: #d32f2f; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        btn_layout.addWidget(self.disconnect_btn)
        
        layout.addLayout(btn_layout, 5, 0, 1, 2)
        
        # Connection status
        self.conn_status_detail = QLabel("Not connected")
        self.conn_status_detail.setStyleSheet("color: gray;")
        layout.addWidget(self.conn_status_detail, 6, 0, 1, 2)
        
        group.setLayout(layout)
        return group
    
    def _set_port(self, port: int, mode: str):
        """Set port and update mode display"""
        self.port_input.setValue(port)
        if mode == "live":
            self.mode_label.setText("🔴 LIVE TRADING")
            self.mode_label.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.mode_label.setText("📋 PAPER TRADING")
            self.mode_label.setStyleSheet("color: blue;")
    
    def _create_strategy_group(self) -> QGroupBox:
        """Create Strategy 16 configuration"""
        group = QGroupBox("📊 Strategy 16 - Iron Condors")
        layout = QGridLayout()
        
        layout.addWidget(QLabel("Target W/L Ratio:"), 0, 0)
        self.target_ratio_input = QDoubleSpinBox()
        self.target_ratio_input.setRange(0.5, 5.0)
        self.target_ratio_input.setValue(1.5)
        self.target_ratio_input.setSingleStep(0.1)
        layout.addWidget(self.target_ratio_input, 0, 1)
        
        layout.addWidget(QLabel("Min Wing Width:"), 1, 0)
        self.min_wing_input = QSpinBox()
        self.min_wing_input.setRange(10, 100)
        self.min_wing_input.setValue(15)
        self.min_wing_input.setSingleStep(5)
        layout.addWidget(self.min_wing_input, 1, 1)
        
        layout.addWidget(QLabel("Max Wing Width:"), 2, 0)
        self.max_wing_input = QSpinBox()
        self.max_wing_input.setRange(20, 150)
        self.max_wing_input.setValue(70)
        self.max_wing_input.setSingleStep(5)
        layout.addWidget(self.max_wing_input, 2, 1)
        
        layout.addWidget(QLabel("Trade Size:"), 3, 0)
        self.trade_size_input = QSpinBox()
        self.trade_size_input.setRange(1, 100)
        self.trade_size_input.setValue(1)
        layout.addWidget(self.trade_size_input, 3, 1)
        
        self.optimize_wings_check = QCheckBox("Smart Wing Optimization")
        self.optimize_wings_check.setChecked(True)
        layout.addWidget(self.optimize_wings_check, 4, 0, 1, 2)
        
        group.setLayout(layout)
        return group
    
    def _create_risk_limits_group(self) -> QGroupBox:
        """Create risk limits display"""
        group = QGroupBox("🛡️ Risk Limits")
        layout = QGridLayout()
        
        layout.addWidget(QLabel("Max Contracts/Trade:"), 0, 0)
        self.max_contracts_trade = QSpinBox()
        self.max_contracts_trade.setRange(1, 100)
        self.max_contracts_trade.setValue(10)
        layout.addWidget(self.max_contracts_trade, 0, 1)
        
        layout.addWidget(QLabel("Max Contracts/Day:"), 1, 0)
        self.max_contracts_day = QSpinBox()
        self.max_contracts_day.setRange(1, 500)
        self.max_contracts_day.setValue(50)
        layout.addWidget(self.max_contracts_day, 1, 1)
        
        layout.addWidget(QLabel("Max Daily Loss ($):"), 2, 0)
        self.max_daily_loss = QSpinBox()
        self.max_daily_loss.setRange(100, 100000)
        self.max_daily_loss.setValue(10000)
        self.max_daily_loss.setSingleStep(1000)
        layout.addWidget(self.max_daily_loss, 2, 1)
        
        self.risk_status_label = QLabel("Contracts today: 0/50")
        self.risk_status_label.setStyleSheet("color: green;")
        layout.addWidget(self.risk_status_label, 3, 0, 1, 2)
        
        group.setLayout(layout)
        return group
    
    def _create_execute_group(self) -> QGroupBox:
        """Create trade execution controls with Engine Start/Stop"""
        group = QGroupBox("⚡ Trading Engine")
        layout = QVBoxLayout()
        
        # Approval mode
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Approval Mode:"))
        self.approval_mode_combo = QComboBox()
        self.approval_mode_combo.addItem("Manual (Approve-to-send)", "manual")
        self.approval_mode_combo.addItem("Auto-send (30s cancel window)", "auto")
        mode_layout.addWidget(self.approval_mode_combo)
        layout.addLayout(mode_layout)
        
        # Scan interval
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Scan Interval:"))
        self.scan_interval_input = QSpinBox()
        self.scan_interval_input.setRange(5, 300)
        self.scan_interval_input.setValue(5)
        self.scan_interval_input.setSuffix(" sec")
        interval_layout.addWidget(self.scan_interval_input)
        layout.addLayout(interval_layout)
        
        # SPX Price display
        self.spx_price_label = QLabel("SPX: ---.--")
        self.spx_price_label.setFont(QFont('Arial', 14, QFont.Weight.Bold))
        self.spx_price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.spx_price_label)
        
        # Engine status
        self.engine_status_label = QLabel("Engine: STOPPED")
        self.engine_status_label.setFont(QFont('Arial', 11, QFont.Weight.Bold))
        self.engine_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.engine_status_label.setStyleSheet("color: gray; padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
        layout.addWidget(self.engine_status_label)
        
        # START / STOP Engine buttons
        engine_btn_layout = QHBoxLayout()
        
        self.start_engine_btn = QPushButton("▶️ START ENGINE")
        self.start_engine_btn.setMinimumHeight(50)
        self.start_engine_btn.clicked.connect(self._on_start_engine)
        self.start_engine_btn.setEnabled(False)
        self.start_engine_btn.setStyleSheet("""
            QPushButton { background-color: #4caf50; color: white; font-weight: bold; font-size: 14px; border-radius: 5px; }
            QPushButton:hover { background-color: #43a047; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        engine_btn_layout.addWidget(self.start_engine_btn)
        
        self.stop_engine_btn = QPushButton("⏹️ STOP ENGINE")
        self.stop_engine_btn.setMinimumHeight(50)
        self.stop_engine_btn.clicked.connect(self._on_stop_engine)
        self.stop_engine_btn.setEnabled(False)
        self.stop_engine_btn.setStyleSheet("""
            QPushButton { background-color: #f44336; color: white; font-weight: bold; font-size: 14px; border-radius: 5px; }
            QPushButton:hover { background-color: #d32f2f; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        engine_btn_layout.addWidget(self.stop_engine_btn)
        
        layout.addLayout(engine_btn_layout)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)
        
        # IC Status display
        layout.addWidget(QLabel("Trade Sequence Status:"))
        
        self.ic1_status = QLabel("⬜ IC1: Waiting for signal...")
        self.ic1_status.setStyleSheet("padding: 3px;")
        layout.addWidget(self.ic1_status)
        
        self.ic2_status = QLabel("⬜ IC2: Requires IC1 first")
        self.ic2_status.setStyleSheet("padding: 3px; color: gray;")
        layout.addWidget(self.ic2_status)
        
        self.ic3_status = QLabel("⬜ IC3: Requires IC2 first")
        self.ic3_status.setStyleSheet("padding: 3px; color: gray;")
        layout.addWidget(self.ic3_status)
        
        # Manual scan buttons (for testing/override)
        layout.addWidget(QLabel("Manual Override:"))
        
        manual_btn_layout = QHBoxLayout()
        
        self.scan_ic1_btn = QPushButton("IC1")
        self.scan_ic1_btn.clicked.connect(self._on_scan_ic1)
        self.scan_ic1_btn.setEnabled(False)
        self.scan_ic1_btn.setToolTip("Manually scan for IC1 (bypasses signal check)")
        manual_btn_layout.addWidget(self.scan_ic1_btn)
        
        self.scan_ic2_btn = QPushButton("IC2")
        self.scan_ic2_btn.clicked.connect(self._on_scan_ic2)
        self.scan_ic2_btn.setEnabled(False)
        manual_btn_layout.addWidget(self.scan_ic2_btn)
        
        self.scan_ic3_btn = QPushButton("IC3")
        self.scan_ic3_btn.clicked.connect(self._on_scan_ic3)
        self.scan_ic3_btn.setEnabled(False)
        manual_btn_layout.addWidget(self.scan_ic3_btn)
        
        layout.addLayout(manual_btn_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_right_panel(self) -> QWidget:
        """Create the right panel with trading activity"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        
        tabs = QTabWidget()
        
        tabs.addTab(self._create_pending_trades_tab(), "⏳ Pending Approval")
        tabs.addTab(self._create_positions_tab(), "📈 Positions")
        tabs.addTab(self._create_log_tab(), "📝 Log")
        
        layout.addWidget(tabs)
        return panel
    
    def _create_pending_trades_tab(self) -> QWidget:
        """Create the pending trades tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.pending_table = QTableWidget()
        self.pending_table.setColumnCount(7)
        self.pending_table.setHorizontalHeaderLabels([
            "ID", "Type", "Strikes", "Qty", "Credit", "Countdown", "Actions"
        ])
        self.pending_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.pending_table)
        
        btn_layout = QHBoxLayout()
        self.approve_selected_btn = QPushButton("✅ Approve Selected")
        self.approve_selected_btn.clicked.connect(self._on_approve_selected)
        btn_layout.addWidget(self.approve_selected_btn)
        
        self.reject_selected_btn = QPushButton("❌ Reject Selected")
        self.reject_selected_btn.clicked.connect(self._on_reject_selected)
        btn_layout.addWidget(self.reject_selected_btn)
        
        layout.addLayout(btn_layout)
        return widget
    
    def _create_positions_tab(self) -> QWidget:
        """Create the positions tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.positions_table = QTableWidget()
        self.positions_table.setColumnCount(6)
        self.positions_table.setHorizontalHeaderLabels([
            "Type", "Strikes", "Qty", "Entry Credit", "Current P&L", "Status"
        ])
        self.positions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.positions_table)
        
        return widget
    
    def _create_log_tab(self) -> QWidget:
        """Create the trade log tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont('Courier', 9))
        layout.addWidget(self.log_text)
        
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(lambda: self.log_text.clear())
        layout.addWidget(clear_btn)
        
        return widget
    
    # =========================================================================
    # IBKR CONNECTION HANDLERS
    # =========================================================================
    
    def _on_connect_clicked(self):
        """Handle connect button click - ACTUALLY CONNECTS TO IBKR"""
        if not IBKR_AVAILABLE:
            QMessageBox.warning(
                self,
                "IBKR Not Available",
                "IBKR connection components not installed.\n\n"
                "Run: pip install ib_insync"
            )
            return
        
        # Confirm if connecting to live
        port = self.port_input.value()
        if port == 7496:  # Live port
            result = QMessageBox.warning(
                self,
                "⚠️ LIVE TRADING CONNECTION",
                "You are about to connect to LIVE TRADING!\n\n"
                "Port 7496 is for REAL MONEY trading.\n\n"
                "Are you sure you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        
        # Build config
        host = self.host_input.currentText()
        client_id = self.client_id_input.value()
        readonly = self.readonly_check.isChecked()
        
        mode = IBKRConnectionMode.LIVE if port in [7496, 4001] else IBKRConnectionMode.PAPER
        
        config = IBKRConfig(
            host=host,
            port=port,
            client_id=client_id,
            mode=mode,
            readonly=readonly
        )
        
        # Validate
        is_valid, error = config.validate()
        if not is_valid:
            QMessageBox.warning(self, "Invalid Configuration", error)
            return
        
        # Disable connect button, update status
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Connecting...")
        self.conn_status_detail.setText("Connecting to IBKR...")
        self._log(f"Connecting to {host}:{port} (Client ID: {client_id})...")
        
        # Start connection in background
        self._connection_manager = IBKRConnectionManager(config, self.kill_switch)
        self._connection_manager.connection_success.connect(self._on_connection_success)
        self._connection_manager.connection_failed.connect(self._on_connection_failed)
        self._connection_manager.account_update.connect(self._on_account_update)
        self._connection_manager.connect()  # Non-blocking!
    
    def _on_disconnect_clicked(self):
        """Handle disconnect button click"""
        if self.ibkr_connection:
            self.ibkr_connection.disconnect()
        
        self._is_connected = False
        self.ibkr_connection = None
        
        self._update_connection_ui(False)
        self._log("Disconnected from IBKR")
    
    @pyqtSlot(object)
    def _on_connection_success(self, connection: 'IBKRConnection'):
        """Handle successful connection"""
        self.ibkr_connection = connection
        self._is_connected = True
        
        self._update_connection_ui(True)
        self._log("✅ Connected to IBKR successfully!")
        
        # Enable trading controls if kill switch is disengaged
        self._update_trading_controls()
        
        self.connection_changed.emit(True)
    
    @pyqtSlot(str)
    def _on_connection_failed(self, error: str):
        """Handle failed connection"""
        self._is_connected = False
        
        self._update_connection_ui(False)
        self.conn_status_detail.setText(f"Error: {error}")
        self._log(f"❌ Connection failed: {error}")
        
        QMessageBox.warning(
            self,
            "Connection Failed",
            f"Could not connect to IBKR:\n\n{error}\n\n"
            "Please ensure:\n"
            "1. TWS or IB Gateway is running\n"
            "2. API is enabled in TWS settings\n"
            "3. Port number is correct (7497 for paper, 7496 for live)\n"
            "4. 'Enable ActiveX and Socket Clients' is checked"
        )
    
    @pyqtSlot(dict)
    def _on_account_update(self, info: dict):
        """Handle account info update"""
        self._account_info = info
        
        account = info.get('account', '-')
        nlv = info.get('net_liquidation', 0)
        daily_pnl = info.get('daily_pnl', 0)
        
        self.account_label.setText(f"Account: {account}")
        self.nlv_label.setText(f"NLV: ${nlv:,.0f}")
        
        pnl_color = "green" if daily_pnl >= 0 else "red"
        self.daily_pnl_label.setText(f"Daily P&L: <span style='color:{pnl_color}'>${daily_pnl:,.2f}</span>")
    
    def _update_connection_ui(self, connected: bool):
        """Update UI based on connection state"""
        if connected:
            self.connect_btn.setEnabled(False)
            self.connect_btn.setText("🔌 Connected")
            self.disconnect_btn.setEnabled(True)
            self.connection_status_label.setText("🟢 Connected")
            self.conn_status_detail.setText("Connected to IBKR")
            
            # Disable connection settings
            self.host_input.setEnabled(False)
            self.port_input.setEnabled(False)
            self.client_id_input.setEnabled(False)
            self.readonly_check.setEnabled(False)
        else:
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("🔌 Connect")
            self.disconnect_btn.setEnabled(False)
            self.connection_status_label.setText("🔴 Disconnected")
            
            # Enable connection settings
            self.host_input.setEnabled(True)
            self.port_input.setEnabled(True)
            self.client_id_input.setEnabled(True)
            self.readonly_check.setEnabled(True)
            
            # Disable trading controls
            self.scan_ic1_btn.setEnabled(False)
            self.scan_ic2_btn.setEnabled(False)
            self.scan_ic3_btn.setEnabled(False)
    
    def _update_trading_controls(self):
        """Update trading control buttons based on state"""
        can_trade = (
            self._is_connected and 
            self.kill_switch and 
            not self.kill_switch.is_engaged()
        )
        
        # Engine start button
        engine_running = hasattr(self, 'trading_engine') and self.trading_engine and self.trading_engine.state.value == "running"
        self.start_engine_btn.setEnabled(can_trade and not engine_running)
        self.stop_engine_btn.setEnabled(engine_running)
        
        # Manual override buttons
        self.scan_ic1_btn.setEnabled(can_trade and self._ic1_trade is None)
        self.scan_ic2_btn.setEnabled(can_trade and self._ic1_trade is not None and self._ic2_trade is None)
        self.scan_ic3_btn.setEnabled(can_trade and self._ic2_trade is not None)
        
        if can_trade:
            self.ic1_status.setText("⬜ IC1: Waiting for signal...")
        elif not self._is_connected:
            self.ic1_status.setText("⬜ IC1: Connect to IBKR first")
            self.ic1_status.setStyleSheet("padding: 3px; color: gray;")
        elif self.kill_switch and self.kill_switch.is_engaged():
            self.ic1_status.setText("⬜ IC1: Disengage kill switch first")
            self.ic1_status.setStyleSheet("padding: 3px; color: orange;")
    
    # =========================================================================
    # KILL SWITCH HANDLERS
    # =========================================================================
    
    def _on_kill_switch_clicked(self):
        """Handle kill switch button click"""
        if self.kill_switch is None:
            return
        
        if self.kill_switch.is_engaged():
            result = QMessageBox.question(
                self,
                "Disengage Kill Switch",
                "Are you sure you want to disengage the kill switch?\n\n"
                "This will allow trading to resume.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if result == QMessageBox.StandardButton.Yes:
                self.kill_switch.disengage("ui_button")
        else:
            self.kill_switch.engage()
        
        self._update_kill_switch_display()
        self._update_trading_controls()
    
    def _on_kill_switch_changed(self, engaged: bool):
        """Handle kill switch status change"""
        self._update_kill_switch_display()
        self._update_trading_controls()
    
    def _update_kill_switch_display(self):
        """Update kill switch UI"""
        if self.kill_switch is None:
            return
        
        if self.kill_switch.is_engaged():
            self.kill_button.setText("🛑 TRADING STOPPED\nClick to Resume")
            self.kill_button.setStyleSheet("""
                QPushButton { background-color: #d32f2f; color: white; border: 4px solid #b71c1c; border-radius: 12px; }
                QPushButton:hover { background-color: #c62828; }
            """)
            self.kill_status_label.setText("🔴 ALL TRADING HALTED")
            self.kill_status_label.setStyleSheet("color: #d32f2f;")
            self.kill_switch_frame.setStyleSheet("background-color: #ffebee;")
        else:
            self.kill_button.setText("⚠️ KILL SWITCH\nClick to STOP ALL")
            self.kill_button.setStyleSheet("""
                QPushButton { background-color: #4caf50; color: white; border: 4px solid #2e7d32; border-radius: 12px; }
                QPushButton:hover { background-color: #43a047; }
            """)
            self.kill_status_label.setText("🟢 Trading Enabled")
            self.kill_status_label.setStyleSheet("color: #2e7d32;")
            self.kill_switch_frame.setStyleSheet("background-color: #e8f5e9;")
    
    def _on_cancel_all(self):
        """Cancel all orders"""
        result = QMessageBox.question(
            self,
            "Cancel All Orders",
            "Cancel all open orders?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if result == QMessageBox.StandardButton.Yes:
            if self.ibkr_connection and self.ibkr_connection.is_connected():
                count = self.ibkr_connection.cancel_all_orders()
                self._log(f"Cancelled {count} orders")
            if self.approval_gate:
                count = self.approval_gate.cancel_all()
                self._log(f"Cancelled {count} pending approvals")
    
    # =========================================================================
    # ENGINE CONTROL
    # =========================================================================
    
    def _on_start_engine(self):
        """Start the continuous trading engine"""
        if not self._check_ready_to_trade():
            return
        
        # Confirm start
        result = QMessageBox.question(
            self,
            "Start Trading Engine",
            "Start the automated trading engine?\n\n"
            "The engine will:\n"
            f"• Scan for signals every {self.scan_interval_input.value()} seconds\n"
            "• Automatically submit trades when signals are detected\n"
            "• Follow the IC1 → IC2 → IC3 sequence\n\n"
            "Make sure you have reviewed your settings!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if result != QMessageBox.StandardButton.Yes:
            return
        
        # Create engine if not exists
        if not hasattr(self, 'trading_engine') or self.trading_engine is None:
            self._create_trading_engine()
        
        # Start engine
        if self.trading_engine:
            self.trading_engine.start()
            self._update_engine_ui(True)
            self._log("🚀 Trading engine STARTED")
    
    def _on_stop_engine(self):
        """Stop the trading engine"""
        if hasattr(self, 'trading_engine') and self.trading_engine:
            self.trading_engine.stop()
            self._update_engine_ui(False)
            self._log("🛑 Trading engine STOPPED")
    
    def _create_trading_engine(self):
        """Create the trading engine instance"""
        try:
            #from engine.live_trading_engine import LiveTradingEngine, LiveEngineConfig
            
            #config = LiveEngineConfig(
                #scan_interval_seconds=self.scan_interval_input.value(),
                #iron_1_target_win_loss_ratio=self.target_ratio_input.value(),
                #iron_1_trade_size=self.trade_size_input.value(),
                #min_wing_width=self.min_wing_input.value(),
                #max_wing_width=self.max_wing_input.value(),
                #optimize_wings=self.optimize_wings_check.isChecked(),
            #)
            #polygon_api_key = "VGG0V1GnGumf21Yw7mMDwg7_derXxQSP"
            #self.trading_engine = LiveTradingEngine(
                #config=config,
                #ibkr_connection=self.ibkr_connection,
                #kill_switch=self.kill_switch,
                #risk_manager=self.risk_manager,
                #approval_gate=self.approval_gate,
                #trade_constructor=self.trade_constructor,
                #polygon_api_key=polygon_api_key
            #)

            from engine.mock_live_trading_engine import MockLiveTradingEngine, MockEngineConfig

            config = MockEngineConfig(
    scan_interval_seconds=60,
    mock_spx_price=6000.0,
    wing_width=25,
    iron_1_trade_size=1,
)

            self.trading_engine = MockLiveTradingEngine(
    config=config,
    ibkr_connection=self.ibkr_connection,
    kill_switch=self.kill_switch,
    risk_manager=self.risk_manager,
    approval_gate=self.approval_gate,
    trade_constructor=self.trade_constructor,
    polygon_api_key=""
)
            
            # Connect signals
            self.trading_engine.state_changed.connect(self._on_engine_state_changed)
            self.trading_engine.signal_detected.connect(self._on_signal_detected)
            self.trading_engine.trade_submitted.connect(self._on_trade_submitted)
            self.trading_engine.log_message.connect(self._on_engine_log)
            self.trading_engine.price_update.connect(self._on_price_update)
            self.trading_engine.trade_executed.connect(self._on_trade_executed)
            
            self._log("Trading engine created")
            
        except ImportError as e:
            self._log(f"Could not import trading engine: {e}", "error")
            self.trading_engine = None
    
    def _update_engine_ui(self, running: bool):
        """Update UI based on engine state"""
        if running:
            self.start_engine_btn.setEnabled(False)
            self.stop_engine_btn.setEnabled(True)
            self.engine_status_label.setText("Engine: 🟢 RUNNING")
            self.engine_status_label.setStyleSheet(
                "color: white; padding: 5px; background-color: #4caf50; border-radius: 3px; font-weight: bold;"
            )
            # Disable settings while running
            self.scan_interval_input.setEnabled(False)
            self.target_ratio_input.setEnabled(False)
            self.trade_size_input.setEnabled(False)
            self.min_wing_input.setEnabled(False)
            self.max_wing_input.setEnabled(False)
        else:
            self.start_engine_btn.setEnabled(self._is_connected and 
                                             self.kill_switch and 
                                             not self.kill_switch.is_engaged())
            self.stop_engine_btn.setEnabled(False)
            self.engine_status_label.setText("Engine: STOPPED")
            self.engine_status_label.setStyleSheet(
                "color: gray; padding: 5px; background-color: #f0f0f0; border-radius: 3px;"
            )
            # Re-enable settings
            self.scan_interval_input.setEnabled(True)
            self.target_ratio_input.setEnabled(True)
            self.trade_size_input.setEnabled(True)
            self.min_wing_input.setEnabled(True)
            self.max_wing_input.setEnabled(True)
    
    @pyqtSlot(str)
    def _on_engine_state_changed(self, state: str):
        """Handle engine state change"""
        self._log(f"Engine state: {state}")
        self._update_engine_ui(state == "running")
    
    @pyqtSlot(str, dict)
    def _on_signal_detected(self, trade_type: str, details: dict):
        """Handle signal detection"""
        self._log(f"📊 Signal detected: {trade_type}")
        
        # Update IC status display
        if "IC1" in trade_type or "Iron Condor 1" in trade_type:
            self.ic1_status.setText(f"✅ IC1: Signal detected at {details.get('price', '?')}")
            self.ic1_status.setStyleSheet("padding: 3px; color: green; font-weight: bold;")


    def _update_pending_table(self):
        """Update the pending trades table with current approval queue"""
        if not self.approval_gate:
           return

        # Get pending trades from approval gate
        pending_trades = self.approval_gate.get_pending_trades()
        # Clear and rebuild table
        self.pending_table.setRowCount(len(pending_trades))
   
        for row, (trade_id, pending_trade) in enumerate(pending_trades.items()):
            # pending_trade is a PendingTrade object, not a dict!
        
            # ID
            self.pending_table.setItem(row, 0, QTableWidgetItem(str(trade_id)[:8]))
    
            # Type
            self.pending_table.setItem(row, 1, QTableWidgetItem(pending_trade.trade_type))
    
            # Strikes/Description
            self.pending_table.setItem(row, 2, QTableWidgetItem(pending_trade.description))
    
            # Quantity
            self.pending_table.setItem(row, 3, QTableWidgetItem(str(pending_trade.quantity)))
    
            # Credit
            self.pending_table.setItem(row, 4, QTableWidgetItem(f"${pending_trade.estimated_credit:.2f}"))
    
            # Countdown
            time_remaining = pending_trade.time_until_auto_send()
            countdown_text = f"{int(time_remaining)}s" if time_remaining else "Manual"
            self.pending_table.setItem(row, 5, QTableWidgetItem(countdown_text))
    
            # Actions - create approve/reject buttons
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)
    
            approve_btn = QPushButton("✅")
            approve_btn.setMaximumWidth(30)
            approve_btn.clicked.connect(lambda checked, tid=trade_id: self._approve_trade(tid))
            actions_layout.addWidget(approve_btn)
    
            reject_btn = QPushButton("❌")
            reject_btn.setMaximumWidth(30)
            reject_btn.clicked.connect(lambda checked, tid=trade_id: self._reject_trade(tid))
            actions_layout.addWidget(reject_btn)
    
            self.pending_table.setCellWidget(row, 6, actions_widget)

    def _approve_trade(self, trade_id: str):
        """Approve a specific trade"""
        if self.approval_gate:
           self.approval_gate.approve(trade_id)
           self._log(f"✅ Approved trade: {trade_id}")
           self._update_pending_table()

    def _reject_trade(self, trade_id: str):
        """Reject a specific trade"""
        if self.approval_gate:
           self.approval_gate.reject(trade_id, "Manual rejection")
           self._log(f"❌ Rejected trade: {trade_id}")
           self._update_pending_table()
    
    @pyqtSlot(str, dict)
    def _on_trade_submitted(self, trade_id: str, trade_info: dict):
        """Handle trade submitted to approval"""
        self._log(f"📤 Trade {trade_id} submitted for approval")
        self._update_pending_table()
    
    @pyqtSlot(str, str)
    def _on_engine_log(self, message: str, level: str):
        """Handle log message from engine"""
        self._log(message)

    @pyqtSlot(str, dict)
    def _on_trade_executed(self, trade_id: str, trade_info: dict):
        """Handle trade execution"""
        self._log(f"✅ Trade EXECUTED: {trade_id}")
    
        # Add to executed trades list
        self._executed_trades.append({
        'trade_id': trade_id,
        'trade_type': trade_info.get('trade_type', trade_info.get('strikes', 'Unknown')),
        'strikes': trade_info.get('strikes', trade_info.get('representation', 'N/A')),
        'quantity': trade_info.get('quantity', 1),
        'credit': trade_info.get('limit_price', trade_info.get('net_premium', 0)),
        'status': trade_info.get('status', 'Filled'),
        'timestamp': datetime.now(),
    })
    
        # Update the positions table
        self._update_positions_table()
    
        # Also update pending table (remove from pending)
        self._update_pending_table()

    def _update_positions_table(self):
        """Update the positions table with executed trades"""
        self.positions_table.setRowCount(len(self._executed_trades))
    
        for row, trade in enumerate(self._executed_trades):
            # Type
            self.positions_table.setItem(row, 0, QTableWidgetItem(str(trade.get('trade_type', 'Unknown'))))
        
            # Strikes
            strikes = trade.get('strikes', 'N/A')
            if isinstance(strikes, dict):
               strikes = f"{strikes.get('long_put', '')}/{strikes.get('short_put', '')} - {strikes.get('short_call', '')}/{strikes.get('long_call', '')}"
            self.positions_table.setItem(row, 1, QTableWidgetItem(str(strikes)))
        
            # Qty
            self.positions_table.setItem(row, 2, QTableWidgetItem(str(trade.get('quantity', 1))))
        
            # Entry Credit
            credit = trade.get('credit', 0)
            self.positions_table.setItem(row, 3, QTableWidgetItem(f"${credit:.2f}" if credit else "N/A"))
        
            # Current P&L (would need live updates from IBKR)
            self.positions_table.setItem(row, 4, QTableWidgetItem("--"))
        
            # Status
            self.positions_table.setItem(row, 5, QTableWidgetItem(trade.get('status', 'Open')))
    
    @pyqtSlot(float, float)
    def _on_price_update(self, spx_price: float, spy_price: float):
        """Handle price update from engine"""
        if spx_price > 0:
            self.spx_price_label.setText(f"SPX: {spx_price:,.2f}")
    
    # =========================================================================
    # TRADE SCANNING (Manual Override)
    # =========================================================================
    
    def _on_scan_ic1(self):
        """Scan for Iron Condor 1"""
        if not self._check_ready_to_trade():
            return
        
        self._log("🔍 Scanning for Iron Condor 1...")
        self._log(f"  Target ratio: {self.target_ratio_input.value()}")
        self._log(f"  Wing width: {self.min_wing_input.value()}-{self.max_wing_input.value()}")
        self._log(f"  Size: {self.trade_size_input.value()} contracts")
        
        # TODO: Integrate with trade_constructor when IBKR is connected
        QMessageBox.information(
            self,
            "Scan IC1",
            "Iron Condor 1 scanning will:\n\n"
            "1. Get current SPX price from IBKR\n"
            "2. Find optimal ATM strikes\n"
            "3. Calculate wing width for target ratio\n"
            "4. Submit to approval queue\n\n"
            "Full execution will be implemented in Milestone 3."
        )
    
    def _on_scan_ic2(self):
        """Scan for Iron Condor 2"""
        if not self._check_ready_to_trade():
            return
        self._log("🔍 Scanning for Iron Condor 2...")
    
    def _on_scan_ic3(self):
        """Scan for Iron Condor 3"""
        if not self._check_ready_to_trade():
            return
        self._log("🔍 Scanning for Iron Condor 3...")
    
    def _check_ready_to_trade(self) -> bool:
        """Check if system is ready to trade"""
        if not self._is_connected:
            QMessageBox.warning(self, "Not Connected", "Connect to IBKR first.")
            return False
        
        if self.kill_switch and self.kill_switch.is_engaged():
            QMessageBox.warning(self, "Kill Switch", "Kill switch is engaged. Cannot trade.")
            return False
        
        return True
    
    # =========================================================================
    # APPROVAL HANDLERS
    # =========================================================================
    
    def _on_trade_pending(self, trade_id: str, trade_info: dict):
        """Handle new pending trade"""
        self._log(f"Trade {trade_id} pending: {trade_info.get('trade_type', 'Unknown')}")
        self._update_pending_table()
    
    def _on_trade_approved(self, trade_id: str):
        """Handle trade approved"""
        self._log(f"Trade {trade_id} APPROVED")
    
    def _on_trade_rejected(self, trade_id: str, reason: str):
        """Handle trade rejected"""
        self._log(f"Trade {trade_id} REJECTED: {reason}")
    
    def _on_countdown_tick(self, trade_id: str, seconds: int):
        """Handle countdown tick"""
        pass
    
    def _on_approve_selected(self):
        """Approve selected trades"""
        self._log("Approve selected - implementation pending")
    
    def _on_reject_selected(self):
        """Reject selected trades"""
        self._log("Reject selected - implementation pending")
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def _update_displays(self):
        """Periodic update of displays"""
        self._update_risk_status()
        
        # Update SPX price if connected
        if self._is_connected and self.ibkr_connection:
            # TODO: Get live SPX price
            pass
    
    def _update_risk_status(self):
        """Update risk status display"""
        if self.risk_manager:
            status = self.risk_manager.get_status()
            contracts = status.get('daily_contracts', 0)
            max_contracts = self.max_contracts_day.value()
            self.risk_status_label.setText(f"Contracts today: {contracts}/{max_contracts}")
    
    def _log(self, message: str):
        """Add message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        logger.info(message)
    
    def reset_daily_state(self):
        """Reset state for new trading day"""
        self._ic1_trade = None
        self._ic2_trade = None
        self.ic1_status.setText("IC1: Ready to scan" if self._is_connected else "IC1: Connect first")
        self.ic2_status.setText("IC2: Requires IC1 first")
        self.ic3_status.setText("IC3: Requires IC2 first")
        self._update_trading_controls()
        
        if self.risk_manager:
            self.risk_manager.reset_daily_counters()
        
        self._log("Daily state reset")
