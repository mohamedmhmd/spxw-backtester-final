"""
Risk Limits Manager - Comprehensive risk management for live trading.

Handles:
- Max contracts per trade
- Max contracts per day
- Trade frequency limits
- Daily loss limits
- Time-based restrictions
- VIX/volatility conditions
- No-trade conditions

Every trade must pass ALL checks before execution.
"""

import logging
from datetime import datetime, date, time, timedelta
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from enum import Enum

from guardrails.kill_switch import KillSwitch, KillSwitchReason

logger = logging.getLogger(__name__)


@dataclass
class RiskLimitsConfig:
    """
    Configuration for all risk limits.
    
    These are the guardrails that protect you from excessive losses.
    """
    # =========================================================================
    # CONTRACT LIMITS
    # =========================================================================
    max_contracts_per_trade: int = 10       # Max contracts in a single trade
    max_contracts_per_day: int = 50         # Total contracts traded per day
    max_open_positions: int = 5             # Max number of open positions
    
    # =========================================================================
    # DOLLAR LIMITS
    # =========================================================================
    max_loss_per_trade: float = 5000.0      # Max loss per individual trade
    max_loss_per_day: float = 10000.0       # Daily loss limit (auto-engages kill switch)
    max_notional_exposure: float = 500000.0 # Max total notional exposure
    warning_loss_threshold: float = 5000.0  # Warn at this daily loss level
    
    # =========================================================================
    # TRADE FREQUENCY LIMITS
    # =========================================================================
    min_seconds_between_trades: int = 30    # Minimum time between trades
    max_trades_per_hour: int = 10           # Max trades in any 60-minute window
    max_trades_per_day: int = 20            # Max total trades per day
    
    # =========================================================================
    # TIME RESTRICTIONS
    # =========================================================================
    trading_start_time: time = field(default_factory=lambda: time(9, 35))   # 5 min after open
    trading_end_time: time = field(default_factory=lambda: time(15, 45))    # 15 min before close
    no_trade_last_minutes: int = 15         # No new trades in last N minutes
    
    # =========================================================================
    # MARKET CONDITION RESTRICTIONS
    # =========================================================================
    max_vix_level: float = 40.0             # Don't trade if VIX above this
    min_bid_ask_spread_ratio: float = 0.5   # Min bid/ask ratio for liquidity
    max_spread_percentage: float = 0.10     # Max spread as % of mid price
    
    # =========================================================================
    # STRATEGY-SPECIFIC LIMITS (Strategy 16 Iron Condors)
    # =========================================================================
    max_iron_condors_per_day: int = 3       # IC1, IC2, IC3 max
    require_ic1_before_ic2: bool = True     # Must have IC1 before IC2
    require_ic2_before_ic3: bool = True     # Must have IC2 before IC3
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            'max_contracts_per_trade': self.max_contracts_per_trade,
            'max_contracts_per_day': self.max_contracts_per_day,
            'max_open_positions': self.max_open_positions,
            'max_loss_per_trade': self.max_loss_per_trade,
            'max_loss_per_day': self.max_loss_per_day,
            'max_notional_exposure': self.max_notional_exposure,
            'min_seconds_between_trades': self.min_seconds_between_trades,
            'max_trades_per_hour': self.max_trades_per_hour,
            'max_trades_per_day': self.max_trades_per_day,
            'trading_start_time': self.trading_start_time.isoformat(),
            'trading_end_time': self.trading_end_time.isoformat(),
            'no_trade_last_minutes': self.no_trade_last_minutes,
            'max_vix_level': self.max_vix_level,
        }


class RiskCheckResult(Enum):
    """Result of a risk check"""
    PASSED = "passed"
    BLOCKED = "blocked"
    WARNING = "warning"


@dataclass
class RiskCheckResponse:
    """Detailed response from a risk check"""
    result: RiskCheckResult
    check_name: str
    message: str
    current_value: Optional[float] = None
    limit_value: Optional[float] = None
    
    def __str__(self):
        if self.result == RiskCheckResult.PASSED:
            return f"✅ {self.check_name}: {self.message}"
        elif self.result == RiskCheckResult.WARNING:
            return f"⚠️ {self.check_name}: {self.message}"
        else:
            return f"❌ {self.check_name}: {self.message}"


class RiskLimitsManager:
    """
    Manages all risk limit checks before trades are executed.
    
    Every trade must pass ALL checks before proceeding.
    Failed checks will block the trade and log the reason.
    
    Usage:
        manager = RiskLimitsManager(config, kill_switch)
        
        # Before any trade
        passed, checks = manager.check_all(contracts=10, estimated_risk=5000)
        if not passed:
            return  # Don't trade
    """
    
    def __init__(self, config: RiskLimitsConfig, kill_switch: KillSwitch):
        self.config = config
        self.kill_switch = kill_switch
        
        # Daily tracking (reset at start of each day)
        self._daily_contracts_traded: int = 0
        self._daily_trades_count: int = 0
        self._daily_pnl: float = 0.0
        self._daily_iron_condors: int = 0
        
        # Trade timing
        self._last_trade_time: Optional[datetime] = None
        self._hourly_trade_times: List[datetime] = []
        
        # Current date tracking
        self._current_date: date = date.today()
        
        # Position tracking
        self._open_positions: List[dict] = []
        
        # Iron Condor sequence tracking (for Strategy 16)
        self._ic1_executed: bool = False
        self._ic2_executed: bool = False
        self._ic3_executed: bool = False
        
        logger.info("Risk Limits Manager initialized")
        logger.info(f"  Max contracts/trade: {config.max_contracts_per_trade}")
        logger.info(f"  Max contracts/day: {config.max_contracts_per_day}")
        logger.info(f"  Max daily loss: ${config.max_loss_per_day:,.0f}")
        logger.info(f"  Trading hours: {config.trading_start_time} - {config.trading_end_time}")
    
    def reset_daily_counters(self):
        """Reset all daily counters - call at start of each trading day"""
        self._daily_contracts_traded = 0
        self._daily_trades_count = 0
        self._daily_pnl = 0.0
        self._daily_iron_condors = 0
        self._hourly_trade_times = []
        self._current_date = date.today()
        
        # Reset IC sequence
        self._ic1_executed = False
        self._ic2_executed = False
        self._ic3_executed = False
        
        logger.info("Daily risk counters reset")
    
    def _check_date_rollover(self):
        """Check if we've rolled to a new trading day"""
        if date.today() != self._current_date:
            logger.info(f"New trading day detected: {date.today()}")
            self.reset_daily_counters()
    
    def check_all(self, 
                  contracts: int, 
                  estimated_risk: float,
                  trade_type: str = "unknown",
                  current_vix: Optional[float] = None) -> Tuple[bool, List[RiskCheckResponse]]:
        """
        Run ALL risk checks for a proposed trade.
        
        Args:
            contracts: Number of contracts in the trade
            estimated_risk: Maximum potential loss for this trade
            trade_type: Type of trade (e.g., "Iron Condor 1", "Iron Condor 2")
            current_vix: Current VIX level (optional)
        
        Returns:
            Tuple of (all_passed: bool, list of check responses)
        """
        self._check_date_rollover()
        
        checks = []
        
        # 1. Kill switch (most critical - always first)
        checks.append(self._check_kill_switch())
        
        # 2. Time-based checks
        checks.append(self._check_trading_hours())
        checks.append(self._check_time_cutoff())
        
        # 3. Contract limits
        checks.append(self._check_contracts_per_trade(contracts))
        checks.append(self._check_daily_contracts(contracts))
        checks.append(self._check_open_positions())
        
        # 4. Trade frequency
        checks.append(self._check_trade_frequency())
        checks.append(self._check_hourly_frequency())
        checks.append(self._check_daily_trade_count())
        
        # 5. Dollar limits
        checks.append(self._check_trade_risk(estimated_risk))
        checks.append(self._check_daily_loss())
        
        # 6. Strategy-specific (Iron Condor sequence)
        if "Iron Condor" in trade_type:
            checks.append(self._check_iron_condor_sequence(trade_type))
            checks.append(self._check_daily_iron_condors())
        
        # 7. Market conditions (if VIX data available)
        if current_vix is not None:
            checks.append(self._check_vix_level(current_vix))
        
        # Determine overall result
        blocked_checks = [c for c in checks if c.result == RiskCheckResult.BLOCKED]
        warning_checks = [c for c in checks if c.result == RiskCheckResult.WARNING]
        
        all_passed = len(blocked_checks) == 0
        
        # Log results
        if not all_passed:
            logger.warning(f"Trade BLOCKED by {len(blocked_checks)} risk check(s):")
            for check in blocked_checks:
                logger.warning(f"  {check}")
        
        if warning_checks:
            logger.warning(f"Trade has {len(warning_checks)} warning(s):")
            for check in warning_checks:
                logger.warning(f"  {check}")
        
        return all_passed, checks
    
    # =========================================================================
    # INDIVIDUAL RISK CHECKS
    # =========================================================================
    
    def _check_kill_switch(self) -> RiskCheckResponse:
        """Check if kill switch is engaged"""
        if self.kill_switch.is_engaged():
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="kill_switch",
                message="Kill switch is engaged - all trading halted"
            )
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="kill_switch",
            message="Kill switch not engaged"
        )
    
    def _check_trading_hours(self) -> RiskCheckResponse:
        """Check if within allowed trading hours"""
        now = datetime.now().time()
        
        if now < self.config.trading_start_time:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="trading_hours",
                message=f"Before trading start time ({self.config.trading_start_time})",
                current_value=now.hour * 60 + now.minute,
                limit_value=self.config.trading_start_time.hour * 60 + self.config.trading_start_time.minute
            )
        
        if now > self.config.trading_end_time:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="trading_hours",
                message=f"After trading end time ({self.config.trading_end_time})",
                current_value=now.hour * 60 + now.minute,
                limit_value=self.config.trading_end_time.hour * 60 + self.config.trading_end_time.minute
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="trading_hours",
            message=f"Within trading hours ({now.strftime('%H:%M')})"
        )
    
    def _check_time_cutoff(self) -> RiskCheckResponse:
        """Check if too close to market close"""
        now = datetime.now()
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        minutes_to_close = (market_close - now).total_seconds() / 60
        
        if minutes_to_close < self.config.no_trade_last_minutes:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="time_cutoff",
                message=f"Within {self.config.no_trade_last_minutes} minutes of market close",
                current_value=minutes_to_close,
                limit_value=self.config.no_trade_last_minutes
            )
        
        # Warning if close
        if minutes_to_close < self.config.no_trade_last_minutes * 2:
            return RiskCheckResponse(
                result=RiskCheckResult.WARNING,
                check_name="time_cutoff",
                message=f"Approaching cutoff ({minutes_to_close:.0f} min to close)",
                current_value=minutes_to_close,
                limit_value=self.config.no_trade_last_minutes
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="time_cutoff",
            message=f"{minutes_to_close:.0f} minutes until cutoff"
        )
    
    def _check_contracts_per_trade(self, contracts: int) -> RiskCheckResponse:
        """Check if trade size exceeds max contracts per trade"""
        if contracts > self.config.max_contracts_per_trade:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="contracts_per_trade",
                message=f"Exceeds max contracts per trade ({contracts} > {self.config.max_contracts_per_trade})",
                current_value=contracts,
                limit_value=self.config.max_contracts_per_trade
            )
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="contracts_per_trade",
            message=f"{contracts} contracts OK (max: {self.config.max_contracts_per_trade})"
        )
    
    def _check_daily_contracts(self, contracts: int) -> RiskCheckResponse:
        """Check if trade would exceed daily contract limit"""
        projected = self._daily_contracts_traded + contracts
        
        if projected > self.config.max_contracts_per_day:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="daily_contracts",
                message=f"Would exceed daily contract limit ({projected} > {self.config.max_contracts_per_day})",
                current_value=projected,
                limit_value=self.config.max_contracts_per_day
            )
        
        # Warning if close to limit
        if projected > self.config.max_contracts_per_day * 0.8:
            return RiskCheckResponse(
                result=RiskCheckResult.WARNING,
                check_name="daily_contracts",
                message=f"Approaching daily contract limit ({projected}/{self.config.max_contracts_per_day})",
                current_value=projected,
                limit_value=self.config.max_contracts_per_day
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="daily_contracts",
            message=f"Daily contracts: {projected}/{self.config.max_contracts_per_day}"
        )
    
    def _check_open_positions(self) -> RiskCheckResponse:
        """Check if max open positions reached"""
        open_count = len(self._open_positions)
        
        if open_count >= self.config.max_open_positions:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="open_positions",
                message=f"Max open positions reached ({open_count}/{self.config.max_open_positions})",
                current_value=open_count,
                limit_value=self.config.max_open_positions
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="open_positions",
            message=f"Open positions: {open_count}/{self.config.max_open_positions}"
        )
    
    def _check_trade_frequency(self) -> RiskCheckResponse:
        """Check minimum time between trades"""
        if self._last_trade_time is None:
            return RiskCheckResponse(
                result=RiskCheckResult.PASSED,
                check_name="trade_frequency",
                message="No recent trades"
            )
        
        seconds_since_last = (datetime.now() - self._last_trade_time).total_seconds()
        
        if seconds_since_last < self.config.min_seconds_between_trades:
            wait_time = self.config.min_seconds_between_trades - seconds_since_last
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="trade_frequency",
                message=f"Must wait {wait_time:.0f}s between trades",
                current_value=seconds_since_last,
                limit_value=self.config.min_seconds_between_trades
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="trade_frequency",
            message=f"{seconds_since_last:.0f}s since last trade"
        )
    
    def _check_hourly_frequency(self) -> RiskCheckResponse:
        """Check trades in the last hour"""
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)
        
        # Clean old entries
        self._hourly_trade_times = [t for t in self._hourly_trade_times if t > hour_ago]
        recent_count = len(self._hourly_trade_times)
        
        if recent_count >= self.config.max_trades_per_hour:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="hourly_frequency",
                message=f"Exceeded hourly trade limit ({recent_count}/{self.config.max_trades_per_hour})",
                current_value=recent_count,
                limit_value=self.config.max_trades_per_hour
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="hourly_frequency",
            message=f"Hourly trades: {recent_count}/{self.config.max_trades_per_hour}"
        )
    
    def _check_daily_trade_count(self) -> RiskCheckResponse:
        """Check total trades today"""
        if self._daily_trades_count >= self.config.max_trades_per_day:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="daily_trade_count",
                message=f"Exceeded daily trade limit ({self._daily_trades_count}/{self.config.max_trades_per_day})",
                current_value=self._daily_trades_count,
                limit_value=self.config.max_trades_per_day
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="daily_trade_count",
            message=f"Daily trades: {self._daily_trades_count}/{self.config.max_trades_per_day}"
        )
    
    def _check_trade_risk(self, estimated_risk: float) -> RiskCheckResponse:
        """Check if single trade risk is acceptable"""
        if estimated_risk > self.config.max_loss_per_trade:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="trade_risk",
                message=f"Trade risk ${estimated_risk:,.0f} exceeds limit ${self.config.max_loss_per_trade:,.0f}",
                current_value=estimated_risk,
                limit_value=self.config.max_loss_per_trade
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="trade_risk",
            message=f"Trade risk ${estimated_risk:,.0f} OK (max: ${self.config.max_loss_per_trade:,.0f})"
        )
    
    def _check_daily_loss(self) -> RiskCheckResponse:
        """Check daily P&L and enforce loss limit"""
        if self._daily_pnl <= -self.config.max_loss_per_day:
            # Auto-engage kill switch on max daily loss
            self.kill_switch.engage(
                reason=KillSwitchReason.MAX_LOSS,
                details=f"Daily loss ${abs(self._daily_pnl):,.0f} exceeds limit ${self.config.max_loss_per_day:,.0f}",
                engaged_by="system"
            )
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="daily_loss",
                message=f"Daily loss limit breached - KILL SWITCH ENGAGED",
                current_value=self._daily_pnl,
                limit_value=-self.config.max_loss_per_day
            )
        
        # Warning if approaching limit
        if self._daily_pnl <= -self.config.warning_loss_threshold:
            return RiskCheckResponse(
                result=RiskCheckResult.WARNING,
                check_name="daily_loss",
                message=f"Daily P&L ${self._daily_pnl:,.0f} approaching limit",
                current_value=self._daily_pnl,
                limit_value=-self.config.max_loss_per_day
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="daily_loss",
            message=f"Daily P&L: ${self._daily_pnl:,.0f}"
        )
    
    def _check_iron_condor_sequence(self, trade_type: str) -> RiskCheckResponse:
        """Check Iron Condor sequence requirements (Strategy 16)"""
        if trade_type == "Iron Condor 2" and self.config.require_ic1_before_ic2:
            if not self._ic1_executed:
                return RiskCheckResponse(
                    result=RiskCheckResult.BLOCKED,
                    check_name="ic_sequence",
                    message="IC2 requires IC1 to be executed first"
                )
        
        if trade_type in ["Iron Condor 3(a)", "Iron Condor 3(b)"] and self.config.require_ic2_before_ic3:
            if not self._ic2_executed:
                return RiskCheckResponse(
                    result=RiskCheckResult.BLOCKED,
                    check_name="ic_sequence",
                    message="IC3 requires IC2 to be executed first"
                )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="ic_sequence",
            message=f"IC sequence OK (IC1:{self._ic1_executed}, IC2:{self._ic2_executed})"
        )
    
    def _check_daily_iron_condors(self) -> RiskCheckResponse:
        """Check daily Iron Condor count"""
        if self._daily_iron_condors >= self.config.max_iron_condors_per_day:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="daily_iron_condors",
                message=f"Max daily Iron Condors reached ({self._daily_iron_condors}/{self.config.max_iron_condors_per_day})",
                current_value=self._daily_iron_condors,
                limit_value=self.config.max_iron_condors_per_day
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="daily_iron_condors",
            message=f"Daily ICs: {self._daily_iron_condors}/{self.config.max_iron_condors_per_day}"
        )
    
    def _check_vix_level(self, current_vix: float) -> RiskCheckResponse:
        """Check if VIX is within acceptable range"""
        if current_vix > self.config.max_vix_level:
            return RiskCheckResponse(
                result=RiskCheckResult.BLOCKED,
                check_name="vix_level",
                message=f"VIX {current_vix:.1f} exceeds max {self.config.max_vix_level}",
                current_value=current_vix,
                limit_value=self.config.max_vix_level
            )
        
        # Warning if elevated
        if current_vix > self.config.max_vix_level * 0.8:
            return RiskCheckResponse(
                result=RiskCheckResult.WARNING,
                check_name="vix_level",
                message=f"VIX {current_vix:.1f} is elevated",
                current_value=current_vix,
                limit_value=self.config.max_vix_level
            )
        
        return RiskCheckResponse(
            result=RiskCheckResult.PASSED,
            check_name="vix_level",
            message=f"VIX {current_vix:.1f} OK"
        )
    
    # =========================================================================
    # TRADE RECORDING
    # =========================================================================
    
    def record_trade(self, contracts: int, trade_type: str, position_id: str = None):
        """
        Record a completed trade for tracking.
        
        Call this AFTER a trade is successfully executed.
        """
        self._daily_contracts_traded += contracts
        self._daily_trades_count += 1
        self._last_trade_time = datetime.now()
        self._hourly_trade_times.append(datetime.now())
        
        # Track Iron Condor sequence
        if "Iron Condor" in trade_type:
            self._daily_iron_condors += 1
            if trade_type == "Iron Condor 1":
                self._ic1_executed = True
            elif trade_type == "Iron Condor 2":
                self._ic2_executed = True
            elif trade_type in ["Iron Condor 3(a)", "Iron Condor 3(b)"]:
                self._ic3_executed = True
        
        # Track open position
        if position_id:
            self._open_positions.append({
                'id': position_id,
                'type': trade_type,
                'contracts': contracts,
                'opened_at': datetime.now()
            })
        
        logger.info(f"Trade recorded: {trade_type} x{contracts}")
        logger.info(f"  Daily totals: {self._daily_contracts_traded} contracts, "
                   f"{self._daily_trades_count} trades")
    
    def close_position(self, position_id: str, pnl: float):
        """
        Record a position being closed.
        
        Call this when a position is closed to update P&L tracking.
        """
        # Remove from open positions
        self._open_positions = [p for p in self._open_positions if p.get('id') != position_id]
        
        # Update daily P&L
        self._daily_pnl += pnl
        
        logger.info(f"Position {position_id} closed with P&L ${pnl:,.2f}")
        logger.info(f"  Daily P&L: ${self._daily_pnl:,.2f}")
        
        # Check if we've hit loss limit
        if self._daily_pnl <= -self.config.max_loss_per_day:
            self.kill_switch.engage(
                reason=KillSwitchReason.MAX_LOSS,
                details=f"Daily loss ${abs(self._daily_pnl):,.0f} hit limit",
                engaged_by="system"
            )
    
    def update_pnl(self, pnl: float):
        """
        Update daily P&L from external source (e.g., broker updates).
        """
        self._daily_pnl = pnl
        
        # Check loss limit
        if self._daily_pnl <= -self.config.max_loss_per_day:
            self.kill_switch.engage(
                reason=KillSwitchReason.MAX_LOSS,
                details=f"Daily loss ${abs(self._daily_pnl):,.0f} hit limit",
                engaged_by="system"
            )
    
    def get_status(self) -> dict:
        """Get current risk status summary"""
        return {
            'daily_contracts': self._daily_contracts_traded,
            'max_daily_contracts': self.config.max_contracts_per_day,
            'daily_trades': self._daily_trades_count,
            'max_daily_trades': self.config.max_trades_per_day,
            'daily_pnl': self._daily_pnl,
            'max_daily_loss': self.config.max_loss_per_day,
            'open_positions': len(self._open_positions),
            'max_positions': self.config.max_open_positions,
            'ic1_executed': self._ic1_executed,
            'ic2_executed': self._ic2_executed,
            'ic3_executed': self._ic3_executed,
            'kill_switch_engaged': self.kill_switch.is_engaged(),
        }
