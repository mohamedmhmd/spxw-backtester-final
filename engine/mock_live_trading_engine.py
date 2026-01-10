"""
Mock Live Trading Engine - IBKR Integration Version

This version:
1. Submits trades through the approval gate (appears in pending table)
2. When approved, actually sends orders to IBKR TWS/Gateway
3. Updates positions table after execution
"""

import logging
import asyncio
from datetime import datetime, time, timedelta, date
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum
import random

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

logger = logging.getLogger(__name__)


class EngineState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class MockEngineConfig:
    scan_interval_seconds: int = 60
    bar_size_minutes: int = 5
    trading_start: time = field(default_factory=lambda: time(0, 0))
    trading_end: time = field(default_factory=lambda: time(23, 59))
    iron_1_target_win_loss_ratio: float = 1.5
    iron_1_trade_size: int = 1
    iron_2_trigger_multiplier: float = 1.0
    iron_2_target_win_loss_ratio: float = 1.5
    iron_2_trade_size: int = 1
    iron_3_trigger_multiplier: float = 1.0
    iron_3_target_win_loss_ratio: float = 1.5
    iron_3_trade_size: int = 1
    min_wing_width: int = 15
    max_wing_width: int = 70
    optimize_wings: bool = True
    mock_spx_price: float = 6000.0
    mock_spy_price: float = 600.0
    wing_width: int = 25


class MockTradeConstruction:
    """
    Mock trade construction object that stores strike info for IBKR order building.
    """
    def __init__(self, trade_type: str, strikes: dict, quantity: int, 
                 net_premium: float, max_loss: float, spx_price: float, expiry: str):
        self.trade_type = trade_type
        self.strikes = strikes
        self.quantity = quantity
        self.net_premium = net_premium
        self.max_loss = max_loss
        self.max_profit = net_premium * 100 * quantity
        self.win_loss_ratio = net_premium / max_loss if max_loss > 0 else 0
        self.spx_price = spx_price
        self.expiry = expiry  # YYYYMMDD format
        
        self.representation = (f"{strikes['long_put']}/{strikes['short_put']} - "
                              f"{strikes['short_call']}/{strikes['long_call']}")
        
        # Will be populated when building IBKR order
        self.combo_contract = None
        self.order = None
        self.leg_contracts = {}
    
    def to_dict(self) -> dict:
        return {
            'trade_type': self.trade_type,
            'strikes': self.strikes,
            'quantity': self.quantity,
            'net_premium': self.net_premium,
            'max_loss': self.max_loss,
            'max_profit': self.max_profit,
            'win_loss_ratio': self.win_loss_ratio,
            'representation': self.representation,
            'spx_price': self.spx_price,
            'expiry': self.expiry,
        }


class MockLiveTradingEngine(QObject):
    """
    Mock trading engine that sends real orders to IBKR when approved.
    """
    
    state_changed = pyqtSignal(str)
    signal_detected = pyqtSignal(str, dict)
    trade_submitted = pyqtSignal(str, dict)
    trade_executed = pyqtSignal(str, dict)
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str, str)
    price_update = pyqtSignal(float, float)
    
    def __init__(
        self,
        config: MockEngineConfig,
        ibkr_connection,
        kill_switch,
        risk_manager,
        approval_gate,
        trade_constructor,
        polygon_api_key: str = ""
    ):
        super().__init__()
        
        self.config = config
        self.ibkr = ibkr_connection
        self.kill_switch = kill_switch
        self.risk_manager = risk_manager
        self.approval_gate = approval_gate
        self.trade_constructor = trade_constructor
        
        self._state = EngineState.STOPPED
        self._running = False
        self._current_spx_price = config.mock_spx_price
        self._current_spy_price = config.mock_spy_price
        self._trade_count = 0
        
        self._loop_timer = QTimer()
        self._loop_timer.timeout.connect(self._run_loop_iteration)
        
        # Connect approval gate execution callback
        if self.approval_gate:
            self.approval_gate.set_execution_callback(self._execute_approved_trade)
        
        self._log("🧪 MOCK Engine initialized - will send REAL orders to IBKR", "info")
    
    @property
    def state(self) -> EngineState:
        return self._state
    
    def _set_state(self, new_state: EngineState):
        old_state = self._state
        self._state = new_state
        self._log(f"Engine state: {old_state.value} → {new_state.value}", "info")
        self.state_changed.emit(new_state.value)
    
    def start(self):
        if self._state == EngineState.RUNNING:
            self._log("Engine already running", "warning")
            return
        
        if not self._preflight_checks():
            return
        
        self._set_state(EngineState.STARTING)
        self._running = True
        self._trade_count = 0
        
        interval_ms = self.config.scan_interval_seconds * 1000
        self._loop_timer.start(interval_ms)
        
        self._set_state(EngineState.RUNNING)
        self._log(f"🚀 MOCK Engine STARTED - submitting every {self.config.scan_interval_seconds}s", "info")
        
        # Submit first trade immediately
        self._run_loop_iteration()
    
    def stop(self):
        self._running = False
        self._loop_timer.stop()
        self._set_state(EngineState.STOPPED)
        self._log(f"🛑 MOCK Engine STOPPED - {self._trade_count} trades submitted", "info")
    
    def pause(self):
        if self._state != EngineState.RUNNING:
            return
        self._loop_timer.stop()
        self._set_state(EngineState.PAUSED)
        self._log("⏸️ MOCK Engine PAUSED", "info")
    
    def resume(self):
        if self._state != EngineState.PAUSED:
            return
        interval_ms = self.config.scan_interval_seconds * 1000
        self._loop_timer.start(interval_ms)
        self._set_state(EngineState.RUNNING)
        self._log("▶️ MOCK Engine RESUMED", "info")
    
    def _preflight_checks(self) -> bool:
        errors = []
        
        if not self.approval_gate:
            errors.append("Approval gate not configured")
        
        if not self.ibkr or not self.ibkr.is_connected():
            errors.append("IBKR not connected")
        
        if self.kill_switch and self.kill_switch.is_engaged():
            errors.append("Kill switch is engaged")
        
        if errors:
            for error in errors:
                self._log(f"❌ Pre-flight failed: {error}", "error")
                self.error_occurred.emit(error)
            return False
        
        self._log("✅ Pre-flight checks passed", "info")
        return True
    
    def _run_loop_iteration(self):
        if self.kill_switch and self.kill_switch.is_engaged():
            self._log("Kill switch engaged - stopping", "warning")
            self.stop()
            return
        
        # Simulate price movement
        self._current_spx_price += random.uniform(-5, 5)
        self._current_spy_price = self._current_spx_price / 10
        
        self.price_update.emit(self._current_spx_price, self._current_spy_price)
        
        self._trade_count += 1
        self._log(f"📊 Creating Iron Butterfly #{self._trade_count} @ SPX {self._current_spx_price:.2f}", "info")
        
        self._submit_mock_trade()
    
    def _submit_mock_trade(self):
        """Create and submit a mock trade to the approval gate"""
        
        # Calculate strikes
        atm_strike = round(self._current_spx_price / 5) * 5
        wing_width = self.config.wing_width
        
        strikes = {
            'short_call': atm_strike,
            'short_put': atm_strike,
            'long_call': atm_strike + wing_width,
            'long_put': atm_strike - wing_width,
        }
        
        # Get today's expiry for 0DTE
        expiry = date.today().strftime('%Y%m%d')
        
        # Estimate premium
        net_premium = wing_width * 0.3
        max_loss = wing_width - net_premium
        
        # Create construction object
        construction = MockTradeConstruction(
            trade_type=f"Iron Butterfly #{self._trade_count}",
            strikes=strikes,
            quantity=self.config.iron_1_trade_size,
            net_premium=net_premium,
            max_loss=max_loss,
            spx_price=self._current_spx_price,
            expiry=expiry
        )
        
        self.signal_detected.emit("Iron Butterfly (Mock)", construction.to_dict())
        
        if self.approval_gate:
            trade_id = self.approval_gate.submit_for_approval(construction)
            self._log(f"✅ Trade {trade_id} submitted to approval gate", "info")
            self._log(f"   Strikes: {construction.representation}", "info")
            self._log(f"   Expiry: {expiry}", "info")
            self.trade_submitted.emit(trade_id, construction.to_dict())
        else:
            self._log("❌ No approval gate!", "error")
    
    def _execute_approved_trade(self, trade_data):
        """
        Called by approval gate when trade is approved.
        This actually sends the order to IBKR!
        """
        self._log(f"🚀 Executing approved trade: {getattr(trade_data, 'trade_type', 'Unknown')}", "info")
        
        # Run async execution
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._async_execute_to_ibkr(trade_data))
            else:
                loop.run_until_complete(self._async_execute_to_ibkr(trade_data))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_execute_to_ibkr(trade_data))
    
    async def _async_execute_to_ibkr(self, trade_data):
        """Build and send order to IBKR"""
        
        if not self.ibkr or not self.ibkr.is_connected():
            self._log("❌ IBKR not connected - cannot execute", "error")
            return
        
        if self.kill_switch and self.kill_switch.is_engaged():
            self._log("❌ Kill switch engaged - cannot execute", "error")
            return
        
        try:
            from ib_insync import Option, Contract, ComboLeg, LimitOrder
            
            strikes = trade_data.strikes
            expiry = trade_data.expiry
            quantity = trade_data.quantity
            
            self._log(f"   Building IBKR order for {trade_data.representation}", "info")
            self._log(f"   Expiry: {expiry}, Qty: {quantity}", "info")
            
            # Create option contracts for each leg
            leg_contracts = {}
            
            for leg_type in ['short_call', 'short_put', 'long_call', 'long_put']:
                strike = strikes[leg_type]
                right = 'C' if 'call' in leg_type else 'P'
                
                opt = Option(
                    symbol='SPX',
                    lastTradeDateOrContractMonth=expiry,
                    strike=float(strike),
                    right=right,
                    exchange='SMART',
                    currency='USD',
                    multiplier='100'
                )
                leg_contracts[leg_type] = opt
            
            # Qualify all contracts
            self._log("   Qualifying contracts with IBKR...", "info")
            all_opts = list(leg_contracts.values())
            
            qualified = self.ibkr.ib.qualifyContracts(*all_opts)
            
            # Check qualification
            qualified_count = sum(1 for c in all_opts if c.conId > 0)
            if qualified_count != 4:
                self._log(f"❌ Only qualified {qualified_count}/4 contracts", "error")
                for leg_type, opt in leg_contracts.items():
                    self._log(f"   {leg_type}: conId={opt.conId}, strike={opt.strike}", "info")
                return
            
            self._log(f"   ✅ All 4 contracts qualified", "info")
            
            # Build combo legs
            legs = []
            for leg_type, opt in leg_contracts.items():
                action = 'SELL' if 'short' in leg_type else 'BUY'
                leg = ComboLeg(
                    conId=opt.conId,
                    ratio=1,
                    action=action,
                    exchange='SMART'
                )
                legs.append(leg)
                self._log(f"   Leg: {action} {opt.strike}{opt.right} (conId={opt.conId})", "info")
            
            # Create combo contract
            combo = Contract(
                symbol='SPX',
                secType='BAG',
                exchange='SMART',
                currency='USD',
                comboLegs=legs
            )
            
            # Create limit order
            # For Iron Butterfly, we receive credit (sell the combo)
            limit_price = round(trade_data.net_premium, 2)
            
            order = LimitOrder(
                action='SELL',
                totalQuantity=quantity,
                lmtPrice=limit_price,
                tif='DAY'
            )
            
            self._log(f"   Placing order: SELL {quantity} @ ${limit_price:.2f} credit", "info")
            
            # Place the order
            trade = self.ibkr.ib.placeOrder(combo, order)
            
            self._log(f"✅ Order placed! Order ID: {trade.order.orderId}", "info")
            self._log(f"   Status: {trade.orderStatus.status}", "info")
            
            # Emit execution signal
            self.trade_executed.emit(
                str(trade.order.orderId),
                {
                    'order_id': trade.order.orderId,
                    'status': trade.orderStatus.status,
                    'strikes': trade_data.representation,
                    'quantity': quantity,
                    'limit_price': limit_price,
                }
            )
            
        except ImportError as e:
            self._log(f"❌ ib_insync not available: {e}", "error")
        except Exception as e:
            self._log(f"❌ Error executing order: {e}", "error")
            import traceback
            self._log(traceback.format_exc(), "error")
    
    def _log(self, message: str, level: str = "info"):
        if level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        self.log_message.emit(message, level)
    
    def get_status(self) -> dict:
        return {
            'state': self._state.value,
            'running': self._running,
            'spx_price': self._current_spx_price,
            'spy_price': self._current_spy_price,
            'trade_count': self._trade_count,
            'mode': 'MOCK',
        }