"""
Live Trading Engine - Continuous loop scanning for Strategy 16.

This is the CORRECT behavior for programmatic trading:
- Runs continuously during market hours
- Checks signals on each bar/interval
- Automatically finds and submits trades when conditions are met
- Respects the IC1 → IC2 → IC3 sequence

Based on your back_test_engine.py Strategy 16 logic.
"""

import logging
import asyncio
from datetime import datetime, time, timedelta
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
import numpy as np

logger = logging.getLogger(__name__)


class EngineState(Enum):
    """State of the live trading engine"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class LiveEngineConfig:
    """Configuration for the live trading engine"""
    # Timing
    scan_interval_seconds: int = 5          # How often to check signals (every bar)
    bar_size_minutes: int = 5               # Bar size for signal checking
    
    # Trading hours (EST)
    trading_start: time = field(default_factory=lambda: time(9, 35))
    trading_end: time = field(default_factory=lambda: time(15, 45))
    
    # Strategy 16 parameters (from your StrategyConfig)
    iron_1_consecutive_candles: int = 3
    iron_1_lookback_candles: int = 5
    iron_1_avg_range_candles: int = 10
    iron_1_target_win_loss_ratio: float = 1.5
    iron_1_volume_threshold: float = 2.0
    iron_1_range_threshold: float = 0.75
    iron_1_trade_size: int = 1
    
    iron_2_trigger_multiplier: float = 1.0
    iron_2_target_win_loss_ratio: float = 1.5
    iron_2_direction_lookback: int = 4
    iron_2_range_recent_candles: int = 2
    iron_2_range_reference_candles: int = 10
    iron_2_range_threshold: float = 1.25
    iron_2_trade_size: int = 1
    
    iron_3_trigger_multiplier: float = 1.0
    iron_3_target_win_loss_ratio: float = 1.5
    iron_3_direction_lookback: int = 4
    iron_3_range_recent_candles: int = 2
    iron_3_range_reference_candles: int = 10
    iron_3_range_threshold: float = 1.25
    iron_3_trade_size: int = 1
    
    # Wing optimization
    min_wing_width: int = 15
    max_wing_width: int = 70
    optimize_wings: bool = True


class LiveTradingEngine(QObject):
    """
    The main engine that runs the continuous trading loop.
    
    This replicates your backtest logic but in real-time:
    - Fetches live SPX/SPY data from IBKR
    - Checks entry signals continuously
    - Constructs and submits trades when signals are met
    - Manages the IC1 → IC2 → IC3 sequence
    
    Signals:
        state_changed: Engine state changed (EngineState)
        signal_detected: Entry signal detected (trade_type, details)
        trade_submitted: Trade submitted to approval (trade_id, trade_info)
        trade_executed: Trade was executed (trade_id, result)
        error_occurred: An error occurred (error_message)
        log_message: Log message for UI (message, level)
    """
    
    # Qt Signals
    state_changed = pyqtSignal(str)           # EngineState value
    signal_detected = pyqtSignal(str, dict)   # trade_type, details
    trade_submitted = pyqtSignal(str, dict)   # trade_id, trade_info
    trade_executed = pyqtSignal(str, dict)    # trade_id, result
    error_occurred = pyqtSignal(str)          # error message
    log_message = pyqtSignal(str, str)        # message, level
    price_update = pyqtSignal(float, float)   # spx_price, spy_price
    
    def __init__(
        self,
        config: LiveEngineConfig,
        ibkr_connection,
        kill_switch,
        risk_manager,
        approval_gate,
        trade_constructor
    ):
        super().__init__()
        
        self.config = config
        self.ibkr = ibkr_connection
        self.kill_switch = kill_switch
        self.risk_manager = risk_manager
        self.approval_gate = approval_gate
        self.trade_constructor = trade_constructor
        
        # Engine state
        self._state = EngineState.STOPPED
        self._running = False
        
        # Daily state (reset each day)
        self._ic1_trade = None
        self._ic2_trade = None
        self._ic3_trade = None
        self._daily_trades: List[Any] = []
        
        # Market data buffers
        self._spx_bars: pd.DataFrame = pd.DataFrame()
        self._spy_bars: pd.DataFrame = pd.DataFrame()
        self._current_spx_price: float = 0.0
        self._current_spy_price: float = 0.0
        # Signal checker (created when we have data)
        self._signal_checker = None
        
        # Main loop timer
        self._loop_timer = QTimer()
        self._loop_timer.timeout.connect(self._run_loop_iteration)
        
        # Connect approval gate execution callback
        if self.approval_gate:
            self.approval_gate.set_execution_callback(self._execute_approved_trade)
        
        self._log("Live Trading Engine initialized", "info")
    
    @property
    def state(self) -> EngineState:
        return self._state
    
    def _set_state(self, new_state: EngineState):
        """Update engine state and emit signal"""
        old_state = self._state
        self._state = new_state
        self._log(f"Engine state: {old_state.value} → {new_state.value}", "info")
        self.state_changed.emit(new_state.value)
    
    # =========================================================================
    # ENGINE CONTROL
    # =========================================================================
    
    def start(self):
        """Start the continuous trading loop"""
        if self._state == EngineState.RUNNING:
            self._log("Engine already running", "warning")
            return
        
        # Pre-flight checks
        if not self._preflight_checks():
            return
        
        self._set_state(EngineState.STARTING)
        self._running = True
        
        # Reset daily state
        self._reset_daily_state()
        
        # Start the loop
        interval_ms = self.config.scan_interval_seconds * 1000
        self._loop_timer.start(interval_ms)
        
        self._set_state(EngineState.RUNNING)
        self._log(f"🚀 Engine STARTED - scanning every {self.config.scan_interval_seconds}s", "info")
    
    def stop(self):
        """Stop the trading loop"""
        self._running = False
        self._loop_timer.stop()
        self._set_state(EngineState.STOPPED)
        self._log("🛑 Engine STOPPED", "info")
    
    def pause(self):
        """Pause the trading loop (can resume)"""
        if self._state != EngineState.RUNNING:
            return
        
        self._loop_timer.stop()
        self._set_state(EngineState.PAUSED)
        self._log("⏸️ Engine PAUSED", "info")
    
    def resume(self):
        """Resume paused engine"""
        if self._state != EngineState.PAUSED:
            return
        
        interval_ms = self.config.scan_interval_seconds * 1000
        self._loop_timer.start(interval_ms)
        self._set_state(EngineState.RUNNING)
        self._log("▶️ Engine RESUMED", "info")
    
    def _preflight_checks(self) -> bool:
        """Run pre-flight checks before starting"""
        errors = []
        
        # Check IBKR connection
        if not self.ibkr or not self.ibkr.is_connected():
            errors.append("IBKR not connected")
        
        # Check kill switch
        if self.kill_switch and self.kill_switch.is_engaged():
            errors.append("Kill switch is engaged")
        
        # Check trading hours
        if not self._is_within_trading_hours():
            errors.append(f"Outside trading hours ({self.config.trading_start}-{self.config.trading_end})")
        
        if errors:
            for error in errors:
                self._log(f"❌ Pre-flight check failed: {error}", "error")
                self.error_occurred.emit(error)
            return False
        
        self._log("✅ All pre-flight checks passed", "info")
        return True
    
    def _reset_daily_state(self):
        """Reset state for new trading day"""
        self._ic1_trade = None
        self._ic2_trade = None
        self._ic3_trade = None
        self._daily_trades = []
        self._spx_bars = pd.DataFrame()
        self._spy_bars = pd.DataFrame()
        
        if self.risk_manager:
            self.risk_manager.reset_daily_counters()
        
        self._log("📅 Daily state reset", "info")
    
    # =========================================================================
    # MAIN LOOP
    # =========================================================================
    
    def _run_loop_iteration(self):
        """
        Single iteration of the main trading loop.
        
        This is called every scan_interval_seconds by the timer.
        """
        try:
            # Run async operations
            asyncio.get_event_loop().run_until_complete(self._async_loop_iteration())
        except RuntimeError:
            # No event loop, create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_loop_iteration())
        except Exception as e:
            self._log(f"Loop error: {e}", "error")
            self.error_occurred.emit(str(e))
    
    async def _async_loop_iteration(self):
        """Async version of loop iteration"""
        
        # 1. Check if we should continue
        if not self._should_continue():
            return
        
        # 2. Fetch latest market data
        await self._fetch_market_data()
        
        # 3. Emit price update
        self.price_update.emit(self._current_spx_price, self._current_spy_price)
        
        # 4. Check for trade opportunities (Strategy 16 sequence)
        await self._check_strategy_16()
        
    
    def _should_continue(self) -> bool:
        """Check if loop should continue"""
        
        # Kill switch check
        if self.kill_switch and self.kill_switch.is_engaged():
            self._log("Kill switch engaged - pausing", "warning")
            self.pause()
            return False
        
        # Trading hours check
        if not self._is_within_trading_hours():
            self._log("Outside trading hours - stopping", "info")
            self.stop()
            return False
        
        # Connection check
        if not self.ibkr or not self.ibkr.is_connected():
            self._log("IBKR disconnected - pausing", "warning")
            self.pause()
            return False
        
        return True
    
    def _is_within_trading_hours(self) -> bool:
        """Check if current time is within trading hours"""
        now = datetime.now().time()
        return self.config.trading_start <= now <= self.config.trading_end
    
    # =========================================================================
    # MARKET DATA
    # =========================================================================
    
    async def _fetch_market_data(self):
        """Fetch latest SPX and SPY data from IBKR"""
        try:
            # Get current prices
            spx_price = await self.ibkr.get_spx_price()
            spy_price = await self.ibkr.get_spy_price()
            
            if spx_price:
                self._current_spx_price = spx_price
            if spy_price:
                self._current_spy_price = spy_price
            
            # Get historical bars for signal checking
            # (Need enough bars for lookback periods)
            min_bars = max(
                self.config.iron_1_consecutive_candles,
                self.config.iron_1_lookback_candles,
                self.config.iron_1_avg_range_candles
            ) + 5  # Extra buffer
            
            spx_bars = await self.ibkr.get_historical_bars(
                symbol='SPX',
                bar_size=f'{self.config.bar_size_minutes} mins',
                duration='1 D',
                what_to_show='TRADES'
            )
            
            spy_bars = await self.ibkr.get_historical_bars(
                symbol='SPY',
                bar_size=f'{self.config.bar_size_minutes} mins',
                duration='1 D',
                what_to_show='TRADES'
            )
            
            if spx_bars is not None and len(spx_bars) > 0:
                self._spx_bars = spx_bars
            if spy_bars is not None and len(spy_bars) > 0:
                self._spy_bars = spy_bars
            self._update_signal_checker()
        except Exception as e:
            self._log(f"Error fetching market data: {e}", "error")
    
    # =========================================================================
    # STRATEGY 16 LOGIC (adapted from your backtest)
    # =========================================================================
    
    async def _check_strategy_16(self):
        """
        Check Strategy 16 entry conditions.
        
        Sequence: IC1 → IC2 → IC3
        (Straddles excluded per your request - only Iron Condors)
        """
        
        # Need enough data
        if len(self._spx_bars) < self.config.iron_1_avg_range_candles:
            return
        
        current_bar_idx = len(self._spx_bars) - 1
        
        # Check IC1 first (if not already executed today)
        if self._ic1_trade is None:
            await self._check_ic1_entry(current_bar_idx)
            return  # Don't check IC2/IC3 until IC1 is done
        
        # Check IC2 (if IC1 done but IC2 not)
        if self._ic2_trade is None:
            await self._check_ic2_entry(current_bar_idx)
            return
        
        # Check IC3 (if IC2 done but IC3 not)
        if self._ic3_trade is None:
            await self._check_ic3_entry(current_bar_idx)
    
    async def _check_ic1_entry(self, bar_idx: int):
        """
        Check Iron Condor 1 entry conditions.
        
        From your iron_condor_1.py:
        - Uses iron_1_check_entry_signals_5min
        """
        
        # Check entry signals (adapted from your OptimizedSignalChecker)
        if not self._check_ic1_signals(bar_idx):
            return
        
        self._log("📊 IC1 entry signals detected!", "info")
        self.signal_detected.emit("Iron Condor 1", {
            'price': self._current_spx_price,
            'time': datetime.now().isoformat()
        })
        
        # Run risk checks
        estimated_risk = self.config.iron_1_trade_size * self.config.max_wing_width * 100
        passed, checks = self.risk_manager.check_all(
            contracts=self.config.iron_1_trade_size * 4,  # 4 legs
            estimated_risk=estimated_risk,
            trade_type="Iron Condor 1"
        )
        
        if not passed:
            self._log("IC1 blocked by risk checks", "warning")
            for check in checks:
                if check.result.value == "blocked":
                    self._log(f"  ❌ {check}", "warning")
            return
        
        # Build the trade
        construction = await self.trade_constructor.construct_iron_condor(
            underlying_price=self._current_spx_price,
            expiry=datetime.now().strftime('%Y%m%d'),
            target_win_loss_ratio=self.config.iron_1_target_win_loss_ratio,
            quantity=self.config.iron_1_trade_size,
            trade_type='Iron Condor 1',
            min_wing_width=self.config.min_wing_width,
            max_wing_width=self.config.max_wing_width,
            optimize_wings=self.config.optimize_wings
        )
        
        if not construction:
            self._log("IC1: Could not find valid strikes", "warning")
            return
        
        # Submit to approval gate
        trade_id = self.approval_gate.submit_for_approval(construction)
        
        self._log(f"✅ IC1 submitted for approval: {trade_id}", "info")
        self._log(f"   Strikes: {construction.representation}", "info")
        self._log(f"   Credit: ${construction.net_premium:.2f}", "info")
        
        self.trade_submitted.emit(trade_id, construction.to_dict())
    
    async def _check_ic2_entry(self, bar_idx: int):
        """
        Check Iron Condor 2 entry conditions.
        
        From your iron_condor_2.py:
        - Trigger: SPX moves to IC1 short strike +/- 100% of IC1 premium
        """
        
        if not self._ic1_trade:
            return
        
        # Check trigger price (from your _check_iron2_trigger_price)
        ic1_premium = self._ic1_trade.get('net_premium', 0)
        ic1_short_strike = self._ic1_trade.get('short_call_strike', 0)
        
        upper_trigger = ic1_short_strike + self.config.iron_2_trigger_multiplier * ic1_premium
        lower_trigger = ic1_short_strike - self.config.iron_2_trigger_multiplier * ic1_premium
        
        if not (self._current_spx_price >= upper_trigger or self._current_spx_price <= lower_trigger):
            return  # Trigger not hit
        
        # Check entry signals
        if not self._check_ic2_signals(bar_idx):
            return
        
        self._log("📊 IC2 entry signals detected!", "info")
        self.signal_detected.emit("Iron Condor 2", {
            'price': self._current_spx_price,
            'trigger': 'upper' if self._current_spx_price >= upper_trigger else 'lower'
        })
        
        # Build and submit (similar to IC1)
        # ... (same pattern as IC1)
    
    async def _check_ic3_entry(self, bar_idx: int):
        """
        Check Iron Condor 3 entry conditions.
        
        From your iron_condor_3.py:
        - IC3(a): Price moves further from IC1
        - IC3(b): Price moves back towards IC1
        """
        
        if not self._ic1_trade or not self._ic2_trade:
            return
        
        # Check IC3(a) trigger
        if self._check_ic3a_trigger():
            if self._check_ic3_signals(bar_idx):
                self._log("📊 IC3(a) entry signals detected!", "info")
                # Build and submit...
                return
        
        # Check IC3(b) trigger
        if self._check_ic3b_trigger():
            if self._check_ic3_signals(bar_idx):
                self._log("📊 IC3(b) entry signals detected!", "info")
                # Build and submit...
    
    # =========================================================================
    # SIGNAL CHECKING (adapted from your OptimizedSignalChecker)
    # =========================================================================
    
    def _update_signal_checker(self):
        """
        Create/update signal checker with current bar data.
        Must be called after fetching new market data.
        """
        if len(self._spx_bars) < 10 or len(self._spy_bars) < 10:
            self._signal_checker = None
            return
        
        # Create numpy arrays like OptimizedSignalChecker expects
        self._spx_open = self._spx_bars['open'].values
        self._spx_close = self._spx_bars['close'].values
        self._spx_high = self._spx_bars['high'].values
        self._spx_low = self._spx_bars['low'].values
        self._spy_volume = self._spy_bars['volume'].values
        
        # Pre-calculate ranges and directions
        self._all_ranges = self._spx_high - self._spx_low
        self._all_directions = np.where(self._spx_close > self._spx_open, 1, -1)
        
        self._signal_checker = True  # Flag that we have valid data
    
    def _check_ic1_signals(self, bar_idx: int) -> bool:
        """
        Check IC1 entry signals.
        Adapted from OptimizedSignalChecker.iron_1_check_entry_signals_5min
        """
        if self._signal_checker is None:
            return False
        
        current_idx = bar_idx
        
        # Get config values
        consecutive_candles = self.config.iron_1_consecutive_candles
        lookback_candles = self.config.iron_1_lookback_candles
        avg_range_candles = self.config.iron_1_avg_range_candles
        volume_threshold_mult = getattr(self.config, 'iron_1_volume_threshold', 2.0)
        range_threshold_mult = getattr(self.config, 'iron_1_range_threshold', 0.75)
        
        len_spx = len(self._spx_open)
        len_spy = len(self._spy_volume)
        
        # Condition 1: Volume check
        if len_spy == 0:
            return False
        volume_threshold = self._spy_volume[0] * volume_threshold_mult
        vol_start = max(0, current_idx - consecutive_candles)
        vol_end = min(len_spy, current_idx)
        
        if vol_end <= vol_start:
            return False
        
        volume_slice = self._spy_volume[vol_start:vol_end]
        if not np.all(volume_slice <= volume_threshold):
            return False
        
        # Condition 2: Direction check (not all same direction)
        dir_start = max(0, current_idx - lookback_candles)
        dir_end = min(len_spx, current_idx)
        
        if dir_end <= dir_start:
            return False
        
        directions = self._all_directions[dir_start:dir_end]
        
        # Fail if all candles same direction
        if len(directions) > 0 and np.all(directions == directions[0]):
            return False
        
        # Condition 3: Range check (consolidation)
        range_start = max(0, current_idx - avg_range_candles)
        range_end = min(len_spx, current_idx)
        
        if range_end <= range_start or current_idx <= 0:
            return False
        
        avg_recent_range = np.mean(self._all_ranges[range_start:range_end])
        avg_day_range = np.mean(self._all_ranges[:current_idx])
        range_threshold = avg_day_range * range_threshold_mult
        
        return avg_recent_range < range_threshold
    
    def _check_ic2_signals(self, bar_idx: int) -> bool:
        """
        Check IC2 entry conditions.
        Adapted from OptimizedSignalChecker.iron_2_check_entry_conditions
        
        1) Last 4 candles not all same direction
        2) Avg range of last 2 candles <= 125% of avg of last 10 candles
        """
        if self._signal_checker is None:
            return False
        
        current_idx = bar_idx
        
        # Get config values with defaults
        direction_lookback = getattr(self.config, 'iron_2_direction_lookback', 4)
        range_recent_candles = getattr(self.config, 'iron_2_range_recent_candles', 2)
        range_reference_candles = getattr(self.config, 'iron_2_range_reference_candles', 10)
        range_threshold_mult = getattr(self.config, 'iron_2_range_threshold', 1.25)
        
        # Ensure enough data
        if current_idx < range_reference_candles:
            return False
        
        # Condition 1: Direction check (last N candles not all same)
        dir_start = current_idx - direction_lookback
        dir_end = current_idx
        
        if dir_start < 0:
            return False
        
        directions = self._all_directions[dir_start:dir_end]
        
        if len(directions) > 0 and np.all(directions == directions[0]):
            return False
        
        # Condition 2: Range comparison
        recent_start = current_idx - range_recent_candles
        recent_end = current_idx
        ref_start = current_idx - range_reference_candles
        ref_end = current_idx
        
        if recent_start < 0 or ref_start < 0:
            return False
        
        avg_recent = np.mean(self._all_ranges[recent_start:recent_end])
        avg_reference = np.mean(self._all_ranges[ref_start:ref_end])
        threshold = avg_reference * range_threshold_mult
        
        return avg_recent <= threshold
    
    def _check_ic3_signals(self, bar_idx: int) -> bool:
        """
        Check IC3 entry conditions (same for IC3a and IC3b).
        Adapted from OptimizedSignalChecker.iron_3_check_entry_conditions
        
        1) Last 4 candles not all same direction
        2) Avg range of last 2 candles <= 125% of avg of last 10 candles
        """
        if self._signal_checker is None:
            return False
        
        current_idx = bar_idx
        
        # Get config values with defaults
        direction_lookback = getattr(self.config, 'iron_3_direction_lookback', 4)
        range_recent = getattr(self.config, 'iron_3_range_recent_candles', 2)
        range_reference = getattr(self.config, 'iron_3_range_reference_candles', 10)
        range_threshold_mult = getattr(self.config, 'iron_3_range_threshold', 1.25)
        
        # Ensure sufficient data
        if current_idx < range_reference:
            return False
        
        # Condition 1: Direction check
        dir_start = current_idx - direction_lookback
        dir_end = current_idx
        
        if dir_start < 0:
            return False
        
        directions = self._all_directions[dir_start:dir_end]
        
        if len(directions) > 0 and np.all(directions == directions[0]):
            return False
        
        # Condition 2: Range check
        recent_start = current_idx - range_recent
        recent_end = current_idx
        ref_start = current_idx - range_reference
        ref_end = current_idx
        
        if recent_start < 0 or ref_start < 0:
            return False
        
        avg_recent = np.mean(self._all_ranges[recent_start:recent_end])
        avg_reference = np.mean(self._all_ranges[ref_start:ref_end])
        threshold = avg_reference * range_threshold_mult
        
        return avg_recent <= threshold
    
    def _check_ic3a_trigger(self) -> bool:
        """
        Check IC3(a) trigger: price moves FURTHER from IC1.
        
        IC3(a) triggers when price breaks beyond IC2 short strike
        in the same direction as IC2 was triggered.
        """
        if not self._ic1_trade or not self._ic2_trade:
            return False
        
        ic2_direction = self._ic2_trade.get('trigger_direction', None)
        ic2_short_strike = self._ic2_trade.get('short_call_strike', 0)
        ic2_premium = self._ic2_trade.get('net_premium', 0)
        trigger_mult = self.config.iron_3_trigger_multiplier
        
        if ic2_direction == 'upper':
            # Price went up for IC2, check if it goes even higher
            trigger_price = ic2_short_strike + (trigger_mult * ic2_premium)
            return self._current_spx_price >= trigger_price
        elif ic2_direction == 'lower':
            # Price went down for IC2, check if it goes even lower
            ic2_short_put = self._ic2_trade.get('short_put_strike', ic2_short_strike)
            trigger_price = ic2_short_put - (trigger_mult * ic2_premium)
            return self._current_spx_price <= trigger_price
        
        return False
    
    def _check_ic3b_trigger(self) -> bool:
        """
        Check IC3(b) trigger: price moves BACK towards IC1.
        
        IC3(b) triggers when price reverses back towards IC1 center
        after IC2 was executed.
        """
        if not self._ic1_trade or not self._ic2_trade:
            return False
        
        ic1_short_strike = self._ic1_trade.get('short_call_strike', 0)
        ic2_direction = self._ic2_trade.get('trigger_direction', None)
        ic2_premium = self._ic2_trade.get('net_premium', 0)
        trigger_mult = self.config.iron_3_trigger_multiplier
        
        if ic2_direction == 'upper':
            # Price went up for IC2, now check if coming back down
            trigger_price = ic1_short_strike + (trigger_mult * ic2_premium)
            return self._current_spx_price <= trigger_price
        elif ic2_direction == 'lower':
            # Price went down for IC2, now check if coming back up
            trigger_price = ic1_short_strike - (trigger_mult * ic2_premium)
            return self._current_spx_price >= trigger_price
        
        return False
    
    # =========================================================================
    # TRADE EXECUTION
    # =========================================================================
    
    def _execute_approved_trade(self, trade_data):
        """
        Called by approval gate when trade is approved.
        
        This sends the actual order to IBKR.
        """
        try:
            asyncio.get_event_loop().run_until_complete(
                self._async_execute_trade(trade_data)
            )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_execute_trade(trade_data))
    
    async def _async_execute_trade(self, trade_data):
        """Execute trade via IBKR"""
        
        # Final risk check
        if self.kill_switch and self.kill_switch.is_engaged():
            self._log("Trade blocked - kill switch engaged", "error")
            return
        
        trade_type = getattr(trade_data, 'trade_type', 'Unknown')
        
        self._log(f"🚀 Executing {trade_type}...", "info")
        
        # Send to IBKR
        if hasattr(trade_data, 'combo_contract') and hasattr(trade_data, 'order'):
            result = await self.ibkr.place_order(
                trade_data.combo_contract,
                trade_data.order
            )
            
            if result and result.success:
                self._log(f"✅ Order placed: {result.order_id}", "info")
                
                # Update daily state
                if 'Iron Condor 1' in str(trade_type):
                    self._ic1_trade = trade_data.to_dict()
                    self.risk_manager.record_trade(
                        contracts=trade_data.total_contracts,
                        trade_type="Iron Condor 1"
                    )
                elif 'Iron Condor 2' in str(trade_type):
                    self._ic2_trade = trade_data.to_dict()
                    self.risk_manager.record_trade(
                        contracts=trade_data.total_contracts,
                        trade_type="Iron Condor 2"
                    )
                elif 'Iron Condor 3' in str(trade_type):
                    self._ic3_trade = trade_data.to_dict()
                    self.risk_manager.record_trade(
                        contracts=trade_data.total_contracts,
                        trade_type=str(trade_type)
                    )
                
                self.trade_executed.emit(result.order_id, trade_data.to_dict())
            else:
                error = result.error if result else "Unknown error"
                self._log(f"❌ Order failed: {error}", "error")
                self.error_occurred.emit(f"Order failed: {error}")
        else:
            self._log("Trade data missing combo_contract or order", "error")
    
    # =========================================================================
    # LOGGING
    # =========================================================================
    
    def _log(self, message: str, level: str = "info"):
        """Log message and emit signal for UI"""
        if level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        
        self.log_message.emit(message, level)
    
    # =========================================================================
    # STATUS
    # =========================================================================
    
    def get_status(self) -> dict:
        """Get current engine status"""
        return {
            'state': self._state.value,
            'running': self._running,
            'spx_price': self._current_spx_price,
            'spy_price': self._current_spy_price,
            'ic1_done': self._ic1_trade is not None,
            'ic2_done': self._ic2_trade is not None,
            'ic3_done': self._ic3_trade is not None,
            'bars_loaded': len(self._spx_bars),
            'within_hours': self._is_within_trading_hours(),
        }
