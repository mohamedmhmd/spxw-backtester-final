"""
Kill Switch Widget - Prominent emergency stop button for the UI.

This widget should be visible at ALL times when live trading is active.
It provides a big, obvious button to immediately halt all trading.

Usage:
    from gui.live.kill_switch_widget import KillSwitchWidget
    from guardrails.kill_switch import KillSwitch
    
    kill_switch = KillSwitch()
    widget = KillSwitchWidget(kill_switch)
    layout.addWidget(widget)
"""

import logging
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QMessageBox, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from guardrails.kill_switch import KillSwitch, KillSwitchReason

logger = logging.getLogger(__name__)


class KillSwitchWidget(QWidget):
    """
    Prominent kill switch button that should be visible at all times.
    
    Features:
    - Big red button when trading is enabled (click to engage/stop)
    - Green pulsing when engaged (click to disengage/resume)
    - Shows engagement duration
    - Requires confirmation to disengage
    - Cancel all orders button
    
    Signals:
        kill_switch_engaged: Emitted when kill switch is engaged
        kill_switch_disengaged: Emitted when kill switch is disengaged  
        cancel_all_requested: Emitted when cancel all orders is clicked
    """
    
    # Signals
    kill_switch_engaged = pyqtSignal()
    kill_switch_disengaged = pyqtSignal()
    cancel_all_requested = pyqtSignal()
    
    def __init__(self, kill_switch: KillSwitch, parent=None):
        super().__init__(parent)
        self.kill_switch = kill_switch
        
        # Timer for updating engagement duration
        self._duration_timer = QTimer()
        self._duration_timer.timeout.connect(self._update_duration)
        
        self._setup_ui()
        self._connect_signals()
        self._update_display()
    
    def _setup_ui(self):
        """Set up the UI components"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Main frame with border
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        frame.setLineWidth(2)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title = QLabel("⚡ LIVE TRADING CONTROLS")
        title.setFont(QFont('Arial', 12, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(title)
        
        # Main kill switch button
        self.kill_button = QPushButton("⚠️ KILL SWITCH")
        self.kill_button.setMinimumSize(220, 100)
        self.kill_button.setFont(QFont('Arial', 18, QFont.Weight.Bold))
        self.kill_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kill_button.clicked.connect(self._on_kill_switch_clicked)
        self.kill_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Prevent accidental keyboard activation
        frame_layout.addWidget(self.kill_button)
        
        # Status label
        self.status_label = QLabel("Status: CHECKING...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFont(QFont('Arial', 11, QFont.Weight.Bold))
        frame_layout.addWidget(self.status_label)
        
        # Duration label (shows how long kill switch has been engaged)
        self.duration_label = QLabel("")
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.duration_label.setFont(QFont('Arial', 9))
        self.duration_label.setStyleSheet("color: #666;")
        frame_layout.addWidget(self.duration_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        frame_layout.addWidget(separator)
        
        # Cancel all orders button (always available)
        self.cancel_all_btn = QPushButton("🚫 Cancel All Orders")
        self.cancel_all_btn.setMinimumHeight(50)
        self.cancel_all_btn.setFont(QFont('Arial', 12, QFont.Weight.Bold))
        self.cancel_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_all_btn.clicked.connect(self._on_cancel_all_clicked)
        self.cancel_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: 2px solid #e65100;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
            QPushButton:pressed {
                background-color: #e65100;
            }
        """)
        frame_layout.addWidget(self.cancel_all_btn)
        
        # Connection status indicator
        self.connection_label = QLabel("🔌 Connection: Unknown")
        self.connection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connection_label.setFont(QFont('Arial', 9))
        frame_layout.addWidget(self.connection_label)
        
        layout.addWidget(frame)
        
        # Set size policy
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    
    def _connect_signals(self):
        """Connect to kill switch signals"""
        self.kill_switch.engaged.connect(self._on_engaged)
        self.kill_switch.disengaged.connect(self._on_disengaged)
        self.kill_switch.status_changed.connect(self._on_status_changed)
    
    def _update_display(self):
        """Update button and labels based on kill switch state"""
        if self.kill_switch.is_engaged():
            # Kill switch is ENGAGED - trading is STOPPED
            self.kill_button.setText("🛑 TRADING STOPPED\n\nClick to Resume")
            self.kill_button.setStyleSheet("""
                QPushButton {
                    background-color: #d32f2f;
                    color: white;
                    border: 4px solid #b71c1c;
                    border-radius: 12px;
                }
                QPushButton:hover {
                    background-color: #c62828;
                    border-color: #8b0000;
                }
                QPushButton:pressed {
                    background-color: #b71c1c;
                }
            """)
            self.status_label.setText("🔴 ALL TRADING HALTED")
            self.status_label.setStyleSheet("color: #d32f2f; font-weight: bold;")
            
            # Start duration timer
            self._duration_timer.start(1000)
            self._update_duration()
            
        else:
            # Kill switch is DISENGAGED - trading is ALLOWED
            self.kill_button.setText("⚠️ KILL SWITCH\n\nClick to STOP ALL")
            self.kill_button.setStyleSheet("""
                QPushButton {
                    background-color: #4caf50;
                    color: white;
                    border: 4px solid #2e7d32;
                    border-radius: 12px;
                }
                QPushButton:hover {
                    background-color: #43a047;
                    border-color: #1b5e20;
                }
                QPushButton:pressed {
                    background-color: #388e3c;
                }
            """)
            self.status_label.setText("🟢 Trading Enabled")
            self.status_label.setStyleSheet("color: #2e7d32; font-weight: bold;")
            
            # Stop duration timer
            self._duration_timer.stop()
            self.duration_label.setText("")
    
    def _update_duration(self):
        """Update the engagement duration display"""
        duration = self.kill_switch.get_engagement_duration()
        if duration is not None:
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            self.duration_label.setText(f"Engaged for: {minutes}m {seconds}s")
    
    def _on_kill_switch_clicked(self):
        """Handle kill switch button click"""
        if self.kill_switch.is_engaged():
            # Currently engaged - user wants to disengage (resume trading)
            self._confirm_and_disengage()
        else:
            # Currently disengaged - user wants to engage (stop trading)
            self._engage_kill_switch()
    
    def _engage_kill_switch(self):
        """Engage the kill switch immediately (no confirmation needed for stopping)"""
        logger.info("User clicked to engage kill switch")
        
        self.kill_switch.engage(
            reason=KillSwitchReason.MANUAL,
            details="Manual UI button press",
            engaged_by="user"
        )
        
        self.kill_switch_engaged.emit()
        
        # Show brief confirmation
        self.status_label.setText("🔴 KILL SWITCH ENGAGED!")
    
    def _confirm_and_disengage(self):
        """Show confirmation dialog before disengaging"""
        # Create warning dialog
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("⚠️ Confirm Resume Trading")
        dialog.setText(
            "<b>Are you sure you want to resume trading?</b>"
        )
        dialog.setInformativeText(
            "This will allow new orders to be placed.\n\n"
            "Make sure:\n"
            "• IBKR is connected\n"
            "• Risk limits are properly configured\n"
            "• You are ready to monitor the system\n\n"
            "The kill switch was engaged for:\n"
            f"{self._get_engagement_reason()}"
        )
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        
        # Make "Yes" button red for extra caution
        yes_button = dialog.button(QMessageBox.StandardButton.Yes)
        yes_button.setText("Yes, Resume Trading")
        yes_button.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold;")
        
        no_button = dialog.button(QMessageBox.StandardButton.No)
        no_button.setText("No, Keep Stopped")
        
        result = dialog.exec()
        
        if result == QMessageBox.StandardButton.Yes:
            logger.info("User confirmed disengage of kill switch")
            self.kill_switch.disengage(confirmed_by="ui_button")
            self.kill_switch_disengaged.emit()
    
    def _get_engagement_reason(self) -> str:
        """Get the reason the kill switch was engaged"""
        status = self.kill_switch.get_status()
        reason = status.get('engagement_reason', 'Unknown')
        details = status.get('engagement_details', '')
        
        if details:
            return f"{reason}: {details}"
        return reason
    
    def _on_cancel_all_clicked(self):
        """Handle cancel all orders button click"""
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("🚫 Cancel All Orders")
        dialog.setText("<b>Cancel all open orders?</b>")
        dialog.setInformativeText(
            "This will immediately cancel all pending orders.\n\n"
            "This action cannot be undone."
        )
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        
        if dialog.exec() == QMessageBox.StandardButton.Yes:
            logger.warning("User requested to cancel all orders")
            self.cancel_all_requested.emit()
    
    def _on_engaged(self, reason: str):
        """Handle kill switch engaged signal"""
        self._update_display()
        logger.info(f"Kill switch widget updated: ENGAGED ({reason})")
    
    def _on_disengaged(self):
        """Handle kill switch disengaged signal"""
        self._update_display()
        logger.info("Kill switch widget updated: DISENGAGED")
    
    def _on_status_changed(self, is_engaged: bool):
        """Handle any status change"""
        self._update_display()
    
    def update_connection_status(self, connected: bool, mode: str = ""):
        """
        Update the connection status display.
        
        Args:
            connected: Whether connected to broker
            mode: Trading mode (e.g., "PAPER", "LIVE")
        """
        if connected:
            text = f"🟢 Connected ({mode})" if mode else "🟢 Connected"
            self.connection_label.setStyleSheet("color: #2e7d32;")
        else:
            text = "🔴 Disconnected"
            self.connection_label.setStyleSheet("color: #d32f2f;")
        
        self.connection_label.setText(f"🔌 {text}")
    
    def set_compact_mode(self, compact: bool):
        """
        Toggle compact mode for smaller displays.
        
        Args:
            compact: If True, use smaller buttons and fonts
        """
        if compact:
            self.kill_button.setMinimumSize(150, 60)
            self.kill_button.setFont(QFont('Arial', 12, QFont.Weight.Bold))
            self.cancel_all_btn.setMinimumHeight(35)
        else:
            self.kill_button.setMinimumSize(220, 100)
            self.kill_button.setFont(QFont('Arial', 18, QFont.Weight.Bold))
            self.cancel_all_btn.setMinimumHeight(50)


class KillSwitchToolbarWidget(QWidget):
    """
    Compact kill switch for embedding in toolbar.
    
    A smaller version that can be added to the main window toolbar.
    """
    
    clicked = pyqtSignal()
    
    def __init__(self, kill_switch: KillSwitch, parent=None):
        super().__init__(parent)
        self.kill_switch = kill_switch
        self._setup_ui()
        self._connect_signals()
        self._update_display()
    
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        
        # Status indicator
        self.indicator = QLabel("●")
        self.indicator.setFont(QFont('Arial', 16))
        layout.addWidget(self.indicator)
        
        # Button
        self.button = QPushButton("KILL")
        self.button.setFixedSize(60, 30)
        self.button.setFont(QFont('Arial', 10, QFont.Weight.Bold))
        self.button.clicked.connect(self._on_click)
        layout.addWidget(self.button)
    
    def _connect_signals(self):
        self.kill_switch.status_changed.connect(self._update_display)
    
    def _update_display(self):
        if self.kill_switch.is_engaged():
            self.indicator.setText("🔴")
            self.indicator.setToolTip("Kill switch ENGAGED - Trading stopped")
            self.button.setStyleSheet("""
                QPushButton {
                    background-color: #d32f2f;
                    color: white;
                    border-radius: 5px;
                }
            """)
        else:
            self.indicator.setText("🟢")
            self.indicator.setToolTip("Trading enabled")
            self.button.setStyleSheet("""
                QPushButton {
                    background-color: #4caf50;
                    color: white;
                    border-radius: 5px;
                }
            """)
    
    def _on_click(self):
        self.clicked.emit()
