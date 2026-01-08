"""
Kill Switch - Global emergency stop for all trading operations.

This is THE most critical safety mechanism in the live trading system.
When engaged, NO orders may be sent under ANY circumstances.

Usage:
    from guardrails.kill_switch import KillSwitch, KillSwitchReason
    
    # Get singleton instance
    kill_switch = KillSwitch.get_instance()
    
    # Check before ANY order operation
    if kill_switch.is_engaged():
        return  # Don't proceed
    
    # Engage in emergency
    kill_switch.engage(KillSwitchReason.MANUAL, "User pressed button")
    
    # Static check from anywhere
    if KillSwitch.check():
        return  # Blocked
"""

import logging
import threading
from datetime import datetime
from typing import Optional, Callable, List
from dataclasses import dataclass
from enum import Enum

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class KillSwitchReason(Enum):
    """Reasons why kill switch might be engaged"""
    MANUAL = "manual"           # User pressed the button
    MAX_LOSS = "max_loss"       # Daily loss limit hit
    ERROR = "error"             # System error
    DISCONNECT = "disconnect"   # Lost connection to broker
    TIME_CUTOFF = "time_cutoff" # Market close approaching
    EXTERNAL = "external"       # External signal (e.g., SMS, API)
    MAX_CONTRACTS = "max_contracts"  # Daily contract limit hit
    STARTUP = "startup"         # System starting up (safe default)


@dataclass
class KillSwitchEvent:
    """Record of a kill switch activation/deactivation"""
    timestamp: datetime
    reason: KillSwitchReason
    details: str
    engaged_by: str  # 'user', 'system', 'auto'
    action: str  # 'engaged' or 'disengaged'


class KillSwitchSignals(QObject):
    """Qt signals for the kill switch - separate class to avoid QObject singleton issues"""
    engaged = pyqtSignal(str)          # Emitted when kill switch is engaged (reason)
    disengaged = pyqtSignal()          # Emitted when kill switch is disengaged
    status_changed = pyqtSignal(bool)  # Emitted on any status change (True = engaged)


class KillSwitch:
    """
    GLOBAL KILL SWITCH - Singleton Pattern
    
    This is THE critical safety mechanism. When engaged:
    - No new orders can be placed
    - Existing orders can still be cancelled
    - Must be explicitly disengaged to resume trading
    
    This class is thread-safe and can emit Qt signals for UI updates.
    
    IMPORTANT: The kill switch starts ENGAGED by default for safety.
    It must be explicitly disengaged to allow trading.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern - only one kill switch can exist system-wide"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance
    
    def __init__(self):
        # Only initialize once (singleton)
        if self._initialized:
            return
        
        # Qt signals (separate object to avoid QObject inheritance issues)
        self.signals = KillSwitchSignals()
        
        # Convenience aliases
        self.engaged = self.signals.engaged
        self.disengaged = self.signals.disengaged
        self.status_changed = self.signals.status_changed
        
        # CRITICAL: Start ENGAGED for safety
        self._engaged = True
        self._engagement_time: Optional[datetime] = datetime.now()
        self._engagement_reason: KillSwitchReason = KillSwitchReason.STARTUP
        self._engagement_details: str = "System startup - disengage to enable trading"
        
        # History tracking
        self._history: List[KillSwitchEvent] = []
        self._history.append(KillSwitchEvent(
            timestamp=datetime.now(),
            reason=KillSwitchReason.STARTUP,
            details="System startup - kill switch engaged by default",
            engaged_by="system",
            action="engaged"
        ))
        
        # Callbacks for non-Qt integrations
        self._callbacks: List[Callable[[bool], None]] = []
        
        # Thread lock for state changes
        self._state_lock = threading.Lock()
        
        self._initialized = True
        
        logger.warning("=" * 60)
        logger.warning("KILL SWITCH INITIALIZED - ENGAGED BY DEFAULT")
        logger.warning("Trading is BLOCKED until manually disengaged")
        logger.warning("=" * 60)
    
    def is_engaged(self) -> bool:
        """
        Check if kill switch is engaged.
        
        THIS METHOD MUST BE CALLED BEFORE ANY ORDER OPERATION.
        
        Returns:
            True if engaged (trading blocked), False if disengaged (trading allowed)
        """
        with self._state_lock:
            return self._engaged
    
    def engage(self, 
               reason: KillSwitchReason = KillSwitchReason.MANUAL, 
               details: str = "", 
               engaged_by: str = "user") -> bool:
        """
        ENGAGE THE KILL SWITCH - STOPS ALL TRADING IMMEDIATELY
        
        This can be called from anywhere at any time. It's always safe to call.
        
        Args:
            reason: Why the kill switch was engaged
            details: Additional context
            engaged_by: Who/what engaged it ('user', 'system', 'auto')
        
        Returns:
            True if newly engaged, False if already engaged
        """
        with self._state_lock:
            if self._engaged:
                logger.warning(f"Kill switch already engaged since {self._engagement_time}")
                return False
            
            self._engaged = True
            self._engagement_time = datetime.now()
            self._engagement_reason = reason
            self._engagement_details = details
            
            event = KillSwitchEvent(
                timestamp=self._engagement_time,
                reason=reason,
                details=details,
                engaged_by=engaged_by,
                action="engaged"
            )
            self._history.append(event)
        
        # Log with HIGH visibility (outside lock)
        logger.critical("=" * 60)
        logger.critical("🛑 KILL SWITCH ENGAGED 🛑")
        logger.critical(f"Reason: {reason.value}")
        logger.critical(f"Details: {details}")
        logger.critical(f"Time: {self._engagement_time}")
        logger.critical(f"Engaged by: {engaged_by}")
        logger.critical("ALL TRADING HALTED - NO ORDERS WILL BE SENT")
        logger.critical("=" * 60)
        
        # Emit Qt signals (outside lock to prevent deadlock)
        try:
            self.signals.engaged.emit(f"{reason.value}: {details}")
            self.signals.status_changed.emit(True)
        except RuntimeError:
            # Qt signals might fail if no event loop
            pass
        
        # Call registered callbacks
        for callback in self._callbacks:
            try:
                callback(True)
            except Exception as e:
                logger.error(f"Error in kill switch callback: {e}")
        
        return True
    
    def disengage(self, confirmed_by: str = "user") -> bool:
        """
        DISENGAGE THE KILL SWITCH - ALLOWS TRADING TO RESUME
        
        This requires explicit action and should be logged for audit.
        
        Args:
            confirmed_by: Who is disengaging (for audit trail)
        
        Returns:
            True if newly disengaged, False if wasn't engaged
        """
        with self._state_lock:
            if not self._engaged:
                logger.info("Kill switch was not engaged")
                return False
            
            old_reason = self._engagement_reason
            old_time = self._engagement_time
            
            self._engaged = False
            self._engagement_time = None
            self._engagement_reason = None
            self._engagement_details = ""
            
            event = KillSwitchEvent(
                timestamp=datetime.now(),
                reason=old_reason,
                details=f"Disengaged by {confirmed_by}",
                engaged_by=confirmed_by,
                action="disengaged"
            )
            self._history.append(event)
        
        # Log with visibility (outside lock)
        logger.warning("=" * 60)
        logger.warning("✅ KILL SWITCH DISENGAGED ✅")
        logger.warning(f"Was engaged since: {old_time}")
        logger.warning(f"Was engaged for reason: {old_reason.value if old_reason else 'unknown'}")
        logger.warning(f"Disengaged by: {confirmed_by}")
        logger.warning("TRADING CAN NOW RESUME")
        logger.warning("=" * 60)
        
        # Emit Qt signals
        try:
            self.signals.disengaged.emit()
            self.signals.status_changed.emit(False)
        except RuntimeError:
            pass
        
        # Call callbacks
        for callback in self._callbacks:
            try:
                callback(False)
            except Exception as e:
                logger.error(f"Error in kill switch callback: {e}")
        
        return True
    
    def register_callback(self, callback: Callable[[bool], None]):
        """
        Register a callback to be called when status changes.
        
        Args:
            callback: Function that takes bool (True = engaged)
        """
        self._callbacks.append(callback)
    
    def unregister_callback(self, callback: Callable[[bool], None]):
        """Remove a previously registered callback"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def get_status(self) -> dict:
        """
        Get current status as a dictionary.
        
        Returns:
            Dict with engagement status and details
        """
        with self._state_lock:
            return {
                'engaged': self._engaged,
                'engagement_time': self._engagement_time,
                'engagement_reason': self._engagement_reason.value if self._engagement_reason else None,
                'engagement_details': self._engagement_details,
                'can_trade': not self._engaged,
            }
    
    def get_history(self) -> List[KillSwitchEvent]:
        """
        Get history of kill switch events.
        
        Returns:
            List of KillSwitchEvent objects
        """
        with self._state_lock:
            return list(self._history)
    
    def get_engagement_duration(self) -> Optional[float]:
        """
        Get how long the kill switch has been engaged (in seconds).
        
        Returns:
            Seconds engaged, or None if not engaged
        """
        with self._state_lock:
            if self._engaged and self._engagement_time:
                return (datetime.now() - self._engagement_time).total_seconds()
            return None
    
    @staticmethod
    def check() -> bool:
        """
        Static method to check kill switch from anywhere.
        
        Returns True if trading is BLOCKED (switch is engaged).
        
        This is a convenience method for quick checks throughout the codebase.
        
        Usage:
            if KillSwitch.check():
                logger.warning("Kill switch engaged - aborting order")
                return  # Don't proceed with order
        
        Returns:
            True if BLOCKED (engaged), False if ALLOWED (disengaged)
        """
        instance = KillSwitch._instance
        if instance is None:
            # No kill switch initialized = assume blocked for safety
            logger.error("Kill switch not initialized - blocking by default for safety")
            return True
        return instance.is_engaged()
    
    @staticmethod
    def get_instance() -> 'KillSwitch':
        """
        Get the singleton instance, creating it if necessary.
        
        Returns:
            The KillSwitch singleton instance
        """
        if KillSwitch._instance is None:
            KillSwitch()
        return KillSwitch._instance
    
    def __str__(self) -> str:
        status = "ENGAGED" if self._engaged else "DISENGAGED"
        return f"KillSwitch({status})"
    
    def __repr__(self) -> str:
        return self.__str__()
