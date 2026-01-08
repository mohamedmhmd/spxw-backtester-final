"""
Approval Gate - Human-in-the-loop approval system for trades.

Two modes:
1. MANUAL (Approve-to-send): Trade waits for explicit approval
2. AUTO_WITH_CANCEL: Trade auto-sends after delay, can be cancelled

This ensures a human portfolio manager is always in control.
"""

import logging
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, List, Any
from enum import Enum

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

logger = logging.getLogger(__name__)


class ApprovalMode(Enum):
    """Trade approval modes"""
    MANUAL = "manual"           # Must explicitly approve before sending
    AUTO_WITH_CANCEL = "auto"   # Auto-sends after delay but can cancel


class ApprovalStatus(Enum):
    """Status of a pending trade"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    AUTO_SENT = "auto_sent"


@dataclass
class PendingTrade:
    """A trade awaiting approval"""
    id: str
    created_at: datetime
    trade_type: str
    description: str
    quantity: int
    estimated_credit: float
    max_loss: float
    max_profit: float
    win_loss_ratio: float
    
    # The actual trade construction
    trade_data: Any = None
    
    # Status
    status: ApprovalStatus = ApprovalStatus.PENDING
    status_reason: str = ""
    
    # For auto mode
    auto_send_at: Optional[datetime] = None
    
    def time_until_auto_send(self) -> Optional[float]:
        """Seconds until auto-send (None if not in auto mode)"""
        if self.auto_send_at:
            delta = (self.auto_send_at - datetime.now()).total_seconds()
            return max(0, delta)
        return None
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'trade_type': self.trade_type,
            'description': self.description,
            'quantity': self.quantity,
            'credit': self.estimated_credit,
            'max_loss': self.max_loss,
            'max_profit': self.max_profit,
            'ratio': self.win_loss_ratio,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'auto_send_at': self.auto_send_at.isoformat() if self.auto_send_at else None,
            'time_remaining': self.time_until_auto_send(),
        }


class ApprovalGate(QObject):
    """
    Human-in-the-loop approval system for trades.
    
    Signals:
        trade_pending: New trade awaiting approval (trade_id, trade_info)
        trade_approved: Trade was approved (trade_id)
        trade_rejected: Trade was rejected (trade_id, reason)
        trade_cancelled: Trade was cancelled (trade_id)
        countdown_tick: Auto-send countdown (trade_id, seconds_remaining)
        trade_executing: Trade is being executed (trade_id)
    """
    
    # Signals
    trade_pending = pyqtSignal(str, dict)      # trade_id, trade_info dict
    trade_approved = pyqtSignal(str)           # trade_id
    trade_rejected = pyqtSignal(str, str)      # trade_id, reason
    trade_cancelled = pyqtSignal(str)          # trade_id
    countdown_tick = pyqtSignal(str, int)      # trade_id, seconds remaining
    trade_executing = pyqtSignal(str)          # trade_id
    
    def __init__(
        self,
        mode: ApprovalMode = ApprovalMode.MANUAL,
        auto_delay_seconds: int = 30,
        notification_callback: Optional[Callable[[str, str], None]] = None
    ):
        """
        Initialize approval gate.
        
        Args:
            mode: MANUAL or AUTO_WITH_CANCEL
            auto_delay_seconds: Seconds before auto-send in AUTO mode
            notification_callback: Function to call for notifications (title, message)
        """
        super().__init__()
        
        self.mode = mode
        self.auto_delay_seconds = auto_delay_seconds
        self.notification_callback = notification_callback
        
        # Pending trades
        self._pending_trades: Dict[str, PendingTrade] = {}
        
        # Execution callback (set by live engine)
        self._execution_callback: Optional[Callable] = None
        
        # Timer for auto-send countdown
        self._countdown_timer = QTimer()
        self._countdown_timer.timeout.connect(self._check_auto_sends)
        self._countdown_timer.start(1000)  # Check every second
        
        logger.info(f"Approval Gate initialized in {mode.value} mode")
        if mode == ApprovalMode.AUTO_WITH_CANCEL:
            logger.info(f"  Auto-send delay: {auto_delay_seconds} seconds")
    
    def set_execution_callback(self, callback: Callable):
        """
        Set the callback to execute approved trades.
        
        Args:
            callback: Function that takes the trade_data and executes it
        """
        self._execution_callback = callback
    
    def set_mode(self, mode: ApprovalMode, auto_delay: int = None):
        """Change approval mode"""
        self.mode = mode
        if auto_delay is not None:
            self.auto_delay_seconds = auto_delay
        logger.info(f"Approval mode changed to: {mode.value}")
    
    def submit_for_approval(self, trade_construction) -> str:
        """
        Submit a trade for approval.
        
        Args:
            trade_construction: IronCondorConstruction or similar object
        
        Returns:
            trade_id that can be used for approve/reject/cancel
        """
        trade_id = str(uuid.uuid4())[:8].upper()
        
        # Extract info from construction
        if hasattr(trade_construction, 'trade_type'):
            trade_type = trade_construction.trade_type.value if hasattr(trade_construction.trade_type, 'value') else str(trade_construction.trade_type)
        else:
            trade_type = "Unknown"
        
        description = getattr(trade_construction, 'representation', str(trade_construction))
        quantity = getattr(trade_construction, 'quantity', 1)
        credit = getattr(trade_construction, 'net_premium', 0)
        max_loss = getattr(trade_construction, 'max_loss', 0)
        max_profit = getattr(trade_construction, 'max_profit', 0)
        ratio = getattr(trade_construction, 'win_loss_ratio', 0)
        
        pending = PendingTrade(
            id=trade_id,
            created_at=datetime.now(),
            trade_type=trade_type,
            description=description,
            quantity=quantity,
            estimated_credit=credit,
            max_loss=max_loss,
            max_profit=max_profit,
            win_loss_ratio=ratio,
            trade_data=trade_construction,
        )
        
        # Set auto-send time if in auto mode
        if self.mode == ApprovalMode.AUTO_WITH_CANCEL:
            pending.auto_send_at = datetime.now() + timedelta(seconds=self.auto_delay_seconds)
        
        self._pending_trades[trade_id] = pending
        
        # Emit signal
        self.trade_pending.emit(trade_id, pending.to_dict())
        
        # Send notification
        self._notify_pending_trade(pending)
        
        logger.info(f"Trade {trade_id} submitted for approval: {trade_type}")
        logger.info(f"  Description: {description}")
        logger.info(f"  Quantity: {quantity}")
        logger.info(f"  Credit: ${credit:.2f}")
        logger.info(f"  Max Loss: ${max_loss:.2f}")
        
        if self.mode == ApprovalMode.AUTO_WITH_CANCEL:
            logger.info(f"  Auto-send in {self.auto_delay_seconds} seconds")
        
        return trade_id
    
    def approve(self, trade_id: str) -> bool:
        """
        Manually approve a trade for execution.
        
        Args:
            trade_id: The trade to approve
        
        Returns:
            True if approved, False if not found or already processed
        """
        pending = self._pending_trades.get(trade_id)
        if not pending:
            logger.warning(f"Trade {trade_id} not found")
            return False
        
        if pending.status != ApprovalStatus.PENDING:
            logger.warning(f"Trade {trade_id} already processed (status: {pending.status.value})")
            return False
        
        pending.status = ApprovalStatus.APPROVED
        pending.status_reason = "Manually approved"
        
        logger.info(f"Trade {trade_id} APPROVED")
        self.trade_approved.emit(trade_id)
        
        # Execute the trade
        self._execute_trade(pending)
        
        return True
    
    def reject(self, trade_id: str, reason: str = "") -> bool:
        """
        Reject a pending trade.
        
        Args:
            trade_id: The trade to reject
            reason: Why it was rejected
        
        Returns:
            True if rejected, False if not found or already processed
        """
        pending = self._pending_trades.get(trade_id)
        if not pending:
            logger.warning(f"Trade {trade_id} not found")
            return False
        
        if pending.status != ApprovalStatus.PENDING:
            logger.warning(f"Trade {trade_id} already processed")
            return False
        
        pending.status = ApprovalStatus.REJECTED
        pending.status_reason = reason
        
        logger.info(f"Trade {trade_id} REJECTED: {reason}")
        self.trade_rejected.emit(trade_id, reason)
        
        return True
    
    def cancel(self, trade_id: str) -> bool:
        """
        Cancel a pending trade (especially useful in auto mode).
        
        Args:
            trade_id: The trade to cancel
        
        Returns:
            True if cancelled, False if not found or already processed
        """
        pending = self._pending_trades.get(trade_id)
        if not pending:
            logger.warning(f"Trade {trade_id} not found")
            return False
        
        if pending.status != ApprovalStatus.PENDING:
            logger.warning(f"Trade {trade_id} already processed")
            return False
        
        pending.status = ApprovalStatus.CANCELLED
        pending.status_reason = "Cancelled by user"
        
        logger.info(f"Trade {trade_id} CANCELLED")
        self.trade_cancelled.emit(trade_id)
        
        return True
    
    def cancel_all(self) -> int:
        """
        Cancel all pending trades.
        
        Returns:
            Number of trades cancelled
        """
        cancelled = 0
        for trade_id, pending in list(self._pending_trades.items()):
            if pending.status == ApprovalStatus.PENDING:
                pending.status = ApprovalStatus.CANCELLED
                pending.status_reason = "Cancelled (cancel all)"
                cancelled += 1
                self.trade_cancelled.emit(trade_id)
        
        if cancelled > 0:
            logger.warning(f"Cancelled {cancelled} pending trades")
        
        return cancelled
    
    def _check_auto_sends(self):
        """Check for trades that should be auto-sent (timer callback)"""
        if self.mode != ApprovalMode.AUTO_WITH_CANCEL:
            return
        
        now = datetime.now()
        
        for trade_id, pending in list(self._pending_trades.items()):
            if pending.status != ApprovalStatus.PENDING:
                continue
            
            if pending.auto_send_at:
                seconds_remaining = (pending.auto_send_at - now).total_seconds()
                
                if seconds_remaining <= 0:
                    # Time to auto-send
                    logger.info(f"Trade {trade_id} AUTO-SENDING")
                    pending.status = ApprovalStatus.AUTO_SENT
                    pending.status_reason = "Auto-sent after countdown"
                    self.trade_executing.emit(trade_id)
                    self._execute_trade(pending)
                    
                elif seconds_remaining <= 10:
                    # Emit countdown in last 10 seconds
                    self.countdown_tick.emit(trade_id, int(seconds_remaining))
    
    def _execute_trade(self, pending: PendingTrade):
        """Execute an approved/auto-sent trade"""
        if self._execution_callback:
            try:
                self.trade_executing.emit(pending.id)
                self._execution_callback(pending.trade_data)
                logger.info(f"Trade {pending.id} sent for execution")
            except Exception as e:
                logger.error(f"Error executing trade {pending.id}: {e}")
                pending.status = ApprovalStatus.REJECTED
                pending.status_reason = f"Execution error: {str(e)}"
        else:
            logger.error(f"No execution callback set - trade {pending.id} not executed")
    
    def _notify_pending_trade(self, pending: PendingTrade):
        """Send notification about pending trade"""
        if not self.notification_callback:
            return
        
        title = f"🔔 Trade Awaiting Approval: {pending.id}"
        
        message = f"""
Trade Type: {pending.trade_type}
Strikes: {pending.description}
Quantity: {pending.quantity}
Est. Credit: ${pending.estimated_credit:.2f}
Max Loss: ${pending.max_loss:.2f}
Max Profit: ${pending.max_profit:.2f}
Ratio: {pending.win_loss_ratio:.2f}
"""
        
        if self.mode == ApprovalMode.AUTO_WITH_CANCEL and pending.auto_send_at:
            message += f"\n⏰ Auto-sends at {pending.auto_send_at.strftime('%H:%M:%S')}"
            message += f"\nCancel within {self.auto_delay_seconds}s to prevent execution"
        else:
            message += "\n👆 Approve or Reject in the trading panel"
        
        try:
            self.notification_callback(title, message)
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    def get_pending_trades(self) -> Dict[str, PendingTrade]:
        """Get all pending trades"""
        return {k: v for k, v in self._pending_trades.items() 
                if v.status == ApprovalStatus.PENDING}
    
    def get_trade(self, trade_id: str) -> Optional[PendingTrade]:
        """Get a specific trade by ID"""
        return self._pending_trades.get(trade_id)
    
    def get_all_trades(self) -> Dict[str, PendingTrade]:
        """Get all trades (including processed)"""
        return dict(self._pending_trades)
    
    def clear_processed(self):
        """Remove all non-pending trades from memory"""
        self._pending_trades = {
            k: v for k, v in self._pending_trades.items()
            if v.status == ApprovalStatus.PENDING
        }
