"""
IBKR Connection Manager

Handles all communication with Interactive Brokers TWS/Gateway.
Every order-related method checks the kill switch before proceeding.

Requirements:
    pip install ib_insync

Usage:
    from execution.ibkr_connection import IBKRConnection
    from config.ibkr_config import IBKRConfig
    from guardrails.kill_switch import KillSwitch
    
    config = IBKRConfig.paper_trading()
    kill_switch = KillSwitch()
    
    connection = IBKRConnection(config, kill_switch)
    await connection.connect()
    
    # Get market data
    spx_price = await connection.get_spx_price()
    
    # Place order (will check kill switch automatically)
    trade = connection.place_order(contract, order)
"""

import asyncio
import logging
from typing import Optional, Callable, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import ib_insync, provide helpful message if not installed
try:
    from ib_insync import IB, Contract, Option, Order, Trade, Position, PortfolioItem
    from ib_insync import LimitOrder, MarketOrder, ComboLeg
    from ib_insync import util
    IB_INSYNC_AVAILABLE = True
except ImportError:
    IB_INSYNC_AVAILABLE = False
    logger.warning("ib_insync not installed. Install with: pip install ib_insync")

# Import our modules
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.ibkr_config import IBKRConfig
from guardrails.kill_switch import KillSwitch, KillSwitchReason


class ConnectionState(Enum):
    """Connection state machine"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class OrderResult:
    """Result of an order operation"""
    success: bool
    order_id: Optional[int] = None
    message: str = ""
    trade: Optional[Any] = None  # ib_insync Trade object


class IBKRConnection:
    """
    Manages connection to Interactive Brokers TWS/Gateway.
    
    CRITICAL: All methods that could potentially send orders check the kill switch first.
    
    Features:
    - Async connection management
    - Auto-reconnect support
    - Event callbacks for status updates
    - Position and account tracking
    - Option chain retrieval
    - Quote streaming
    """
    
    def __init__(self, config: IBKRConfig, kill_switch: KillSwitch):
        """
        Initialize IBKR connection manager.
        
        Args:
            config: IBKR connection configuration
            kill_switch: Global kill switch instance
        """
        if not IB_INSYNC_AVAILABLE:
            raise ImportError(
                "ib_insync is required for IBKR connection. "
                "Install with: pip install ib_insync"
            )
        
        self.config = config
        self.kill_switch = kill_switch
        self.ib = IB()
        self.state = ConnectionState.DISCONNECTED
        
        # Reconnection tracking
        self._reconnect_attempts = 0
        self._reconnect_task: Optional[asyncio.Task] = None
        
        # Callbacks for external integrations
        self._callbacks: Dict[str, List[Callable]] = {
            'connected': [],
            'disconnected': [],
            'error': [],
            'order_status': [],
            'position_update': [],
            'account_update': [],
            'execution': [],
        }
        
        # Set up ib_insync event handlers
        self.ib.connectedEvent += self._on_connected
        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.errorEvent += self._on_error
        self.ib.orderStatusEvent += self._on_order_status
        self.ib.positionEvent += self._on_position
        self.ib.accountValueEvent += self._on_account_value
        self.ib.execDetailsEvent += self._on_execution
        
        logger.info(f"IBKRConnection initialized for {config.get_display_mode()} trading")
    
    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================
    
    async def connect(self) -> bool:
        """
        Establish connection to IBKR.
        
        Returns:
            True if successfully connected, False otherwise
        """
        if self.state == ConnectionState.CONNECTED and self.ib.isConnected():
            logger.info("Already connected to IBKR")
            return True
        
        # Validate config
        is_valid, error = self.config.validate()
        if not is_valid:
            logger.error(f"Invalid IBKR config: {error}")
            return False
        
        self.state = ConnectionState.CONNECTING
        logger.info(f"Connecting to IBKR at {self.config.host}:{self.config.port} "
                   f"(Mode: {self.config.get_display_mode()})...")
        
        try:
            await self.ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                readonly=self.config.readonly,
                timeout=self.config.timeout
            )
            
            # Get account info
            accounts = self.ib.managedAccounts()
            if accounts:
                self.config.account = accounts[0]
                logger.info(f"Connected to account: {self.config.account}")
            
            self.state = ConnectionState.CONNECTED
            self._reconnect_attempts = 0
            
            # Log connection details
            logger.info("=" * 50)
            logger.info("IBKR CONNECTION ESTABLISHED")
            logger.info(f"  Account: {self.config.account}")
            logger.info(f"  Mode: {self.config.get_display_mode()}")
            logger.info(f"  Client ID: {self.config.client_id}")
            logger.info(f"  Readonly: {self.config.readonly}")
            logger.info("=" * 50)
            
            return True
            
        except Exception as e:
            self.state = ConnectionState.ERROR
            logger.error(f"Failed to connect to IBKR: {e}")
            
            # Engage kill switch on connection failure
            self.kill_switch.engage(
                reason=KillSwitchReason.DISCONNECT,
                details=f"Failed to connect to IBKR: {str(e)}",
                engaged_by="system"
            )
            
            return False
    
    def disconnect(self):
        """Disconnect from IBKR"""
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        
        if self.ib.isConnected():
            self.ib.disconnect()
        
        self.state = ConnectionState.DISCONNECTED
        logger.info("Disconnected from IBKR")
    
    async def _auto_reconnect(self):
        """Attempt to automatically reconnect"""
        if not self.config.auto_reconnect:
            return
        
        while self._reconnect_attempts < self.config.max_reconnect_attempts:
            self._reconnect_attempts += 1
            self.state = ConnectionState.RECONNECTING
            
            logger.warning(f"Attempting reconnection {self._reconnect_attempts}/"
                          f"{self.config.max_reconnect_attempts}...")
            
            await asyncio.sleep(self.config.reconnect_delay)
            
            if await self.connect():
                logger.info("Reconnection successful")
                return
        
        logger.error("Max reconnection attempts reached")
        self.kill_switch.engage(
            reason=KillSwitchReason.DISCONNECT,
            details="Failed to reconnect to IBKR after max attempts",
            engaged_by="system"
        )
    
    def is_connected(self) -> bool:
        """Check if connected to IBKR"""
        return self.ib.isConnected() and self.state == ConnectionState.CONNECTED
    
    def get_connection_status(self) -> dict:
        """Get detailed connection status"""
        return {
            'connected': self.is_connected(),
            'state': self.state.value,
            'account': self.config.account,
            'mode': self.config.get_display_mode(),
            'client_id': self.config.client_id,
            'readonly': self.config.readonly,
        }
    
    # =========================================================================
    # CALLBACK MANAGEMENT
    # =========================================================================
    
    def register_callback(self, event: str, callback: Callable):
        """Register a callback for an event type"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
        else:
            logger.warning(f"Unknown event type: {event}")
    
    def unregister_callback(self, event: str, callback: Callable):
        """Remove a callback"""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)
    
    def _emit(self, event: str, *args, **kwargs):
        """Emit an event to all registered callbacks"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {event} callback: {e}")
    
    # =========================================================================
    # MARKET DATA METHODS
    # =========================================================================
    
    async def get_spx_price(self) -> Optional[float]:
        """
        Get current SPX index price.
        
        Returns:
            Current SPX price or None if unavailable
        """
        if not self.is_connected():
            logger.warning("Cannot get SPX price: Not connected")
            return None
        
        try:
            contract = Contract(
                symbol='SPX',
                secType='IND',
                exchange='CBOE',
                currency='USD'
            )
            self.ib.qualifyContracts(contract)
            
            ticker = self.ib.reqMktData(contract, '', False, False)
            
            # Wait for data with timeout
            for _ in range(20):  # 2 second timeout
                await asyncio.sleep(0.1)
                if ticker.marketPrice() and ticker.marketPrice() > 0:
                    break
            
            price = ticker.marketPrice()
            self.ib.cancelMktData(contract)
            
            if price and price > 0:
                logger.debug(f"SPX price: {price}")
                return price
            
            # Fallback to last price
            if ticker.last and ticker.last > 0:
                return ticker.last
            
            logger.warning("Could not get valid SPX price")
            return None
            
        except Exception as e:
            logger.error(f"Error getting SPX price: {e}")
            return None
    
    async def get_spx_option_chain(self, expiry: str) -> List[Option]:
        """
        Get SPX option chain for a specific expiration.
        
        Args:
            expiry: Expiration date in YYYYMMDD format
        
        Returns:
            List of qualified Option contracts
        """
        if not self.is_connected():
            return []
        
        try:
            # Get current SPX price for strike range
            spx_price = await self.get_spx_price()
            if not spx_price:
                return []
            
            # Define strike range (±200 points in 5-point increments)
            strike_range = 200
            strike_step = 5
            
            min_strike = int((spx_price - strike_range) // strike_step * strike_step)
            max_strike = int((spx_price + strike_range) // strike_step * strike_step)
            
            options = []
            for strike in range(min_strike, max_strike + 1, strike_step):
                for right in ['C', 'P']:
                    opt = Option(
                        symbol='SPX',
                        lastTradeDateOrContractMonth=expiry,
                        strike=float(strike),
                        right=right,
                        exchange='SMART',
                        currency='USD',
                        multiplier='100'
                    )
                    options.append(opt)
            
            # Qualify contracts in batches
            qualified = []
            batch_size = 50
            
            for i in range(0, len(options), batch_size):
                batch = options[i:i + batch_size]
                try:
                    result = self.ib.qualifyContracts(*batch)
                    qualified.extend([opt for opt in result if opt.conId > 0])
                except Exception as e:
                    logger.warning(f"Error qualifying batch: {e}")
                
                await asyncio.sleep(0.1)  # Rate limiting
            
            logger.info(f"Qualified {len(qualified)} SPX options for expiry {expiry}")
            return qualified
            
        except Exception as e:
            logger.error(f"Error getting option chain: {e}")
            return []
    
    async def get_option_quotes(self, options: List[Option]) -> Dict[int, Dict]:
        """
        Get real-time quotes for multiple options.
        
        Args:
            options: List of Option contracts
        
        Returns:
            Dict keyed by conId with quote data
        """
        if not self.is_connected() or not options:
            return {}
        
        quotes = {}
        tickers = []
        
        try:
            # Request market data for all options
            for opt in options:
                ticker = self.ib.reqMktData(opt, '', False, False)
                tickers.append((opt, ticker))
            
            # Wait for quotes
            await asyncio.sleep(3)
            
            # Collect quotes
            for opt, ticker in tickers:
                bid = ticker.bid if ticker.bid and ticker.bid > 0 else 0
                ask = ticker.ask if ticker.ask and ticker.ask > 0 else 0
                
                quotes[opt.conId] = {
                    'contract': opt,
                    'strike': opt.strike,
                    'right': opt.right,
                    'bid': bid,
                    'ask': ask,
                    'last': ticker.last if ticker.last else 0,
                    'mid': (bid + ask) / 2 if bid and ask else 0,
                    'bid_size': ticker.bidSize if ticker.bidSize else 0,
                    'ask_size': ticker.askSize if ticker.askSize else 0,
                    'volume': ticker.volume if ticker.volume else 0,
                }
                
                # Cancel market data
                self.ib.cancelMktData(opt)
            
            return quotes
            
        except Exception as e:
            logger.error(f"Error getting option quotes: {e}")
            return {}
    
    async def get_quote(self, contract: Contract) -> Optional[Dict]:
        """
        Get quote for a single contract.
        
        Args:
            contract: The contract to quote
        
        Returns:
            Dict with bid/ask/last/etc or None
        """
        if not self.is_connected():
            return None
        
        try:
            self.ib.qualifyContracts(contract)
            ticker = self.ib.reqMktData(contract, '', False, False)
            
            await asyncio.sleep(2)
            
            result = {
                'bid': ticker.bid if ticker.bid else 0,
                'ask': ticker.ask if ticker.ask else 0,
                'last': ticker.last if ticker.last else 0,
                'mid': (ticker.bid + ticker.ask) / 2 if ticker.bid and ticker.ask else 0,
            }
            
            self.ib.cancelMktData(contract)
            return result
            
        except Exception as e:
            logger.error(f"Error getting quote: {e}")
            return None
    
    # =========================================================================
    # ORDER METHODS - ALL CHECK KILL SWITCH
    # =========================================================================
    
    def place_order(self, contract: Contract, order: Order) -> OrderResult:
        """
        Place an order - CHECKS KILL SWITCH FIRST.
        
        Args:
            contract: The contract to trade
            order: The order specification
        
        Returns:
            OrderResult with success status and details
        """
        # CRITICAL: Check kill switch before ANY order placement
        if self.kill_switch.is_engaged():
            msg = "ORDER BLOCKED: Kill switch is engaged"
            logger.warning(msg)
            return OrderResult(success=False, message=msg)
        
        # Check connection
        if not self.is_connected():
            msg = "ORDER BLOCKED: Not connected to IBKR"
            logger.error(msg)
            return OrderResult(success=False, message=msg)
        
        # Check readonly mode
        if self.config.readonly:
            msg = "ORDER BLOCKED: Connection is in readonly mode"
            logger.error(msg)
            return OrderResult(success=False, message=msg)
        
        try:
            # Final kill switch check right before placing
            if self.kill_switch.is_engaged():
                msg = "ORDER BLOCKED: Kill switch engaged during order preparation"
                logger.warning(msg)
                return OrderResult(success=False, message=msg)
            
            trade = self.ib.placeOrder(contract, order)
            
            logger.info(f"Order placed: {order.action} {order.totalQuantity} "
                       f"{contract.localSymbol or contract.symbol}")
            
            return OrderResult(
                success=True,
                order_id=order.orderId,
                message="Order placed successfully",
                trade=trade
            )
            
        except Exception as e:
            msg = f"Order placement failed: {str(e)}"
            logger.error(msg)
            return OrderResult(success=False, message=msg)
    
    def modify_order(self, order: Order, new_limit_price: Optional[float] = None,
                     new_quantity: Optional[int] = None) -> OrderResult:
        """
        Modify an existing order - CHECKS KILL SWITCH.
        
        Args:
            order: The order to modify
            new_limit_price: New limit price (optional)
            new_quantity: New quantity (optional)
        
        Returns:
            OrderResult with success status
        """
        # Check kill switch for modifications
        if self.kill_switch.is_engaged():
            msg = "ORDER MODIFICATION BLOCKED: Kill switch is engaged"
            logger.warning(msg)
            return OrderResult(success=False, message=msg)
        
        if not self.is_connected():
            return OrderResult(success=False, message="Not connected")
        
        try:
            if new_limit_price is not None:
                order.lmtPrice = new_limit_price
            if new_quantity is not None:
                order.totalQuantity = new_quantity
            
            trade = self.ib.placeOrder(order.contract, order)
            
            logger.info(f"Order modified: {order.orderId}")
            return OrderResult(success=True, order_id=order.orderId, trade=trade)
            
        except Exception as e:
            return OrderResult(success=False, message=str(e))
    
    def cancel_order(self, order: Order) -> bool:
        """
        Cancel a specific order.
        
        NOTE: Cancellations are ALLOWED even with kill switch engaged.
        This is intentional - we always want to be able to cancel orders.
        
        Args:
            order: The order to cancel
        
        Returns:
            True if cancellation request sent, False otherwise
        """
        if not self.is_connected():
            logger.error("Cannot cancel order: Not connected")
            return False
        
        try:
            self.ib.cancelOrder(order)
            logger.info(f"Cancel request sent for order: {order.orderId}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order.orderId}: {e}")
            return False
    
    def cancel_all_orders(self) -> int:
        """
        Cancel ALL open orders - EMERGENCY FUNCTION.
        
        This is always allowed regardless of kill switch state.
        
        Returns:
            Number of orders cancelled
        """
        if not self.is_connected():
            logger.error("Cannot cancel orders: Not connected")
            return 0
        
        open_orders = self.ib.openOrders()
        cancelled = 0
        
        logger.warning(f"CANCELLING ALL {len(open_orders)} OPEN ORDERS")
        
        for order in open_orders:
            try:
                self.ib.cancelOrder(order)
                cancelled += 1
                logger.info(f"Cancelled order: {order.orderId}")
            except Exception as e:
                logger.error(f"Failed to cancel order {order.orderId}: {e}")
        
        logger.warning(f"CANCELLED {cancelled}/{len(open_orders)} ORDERS")
        return cancelled
    
    def get_open_orders(self) -> List[Order]:
        """Get all open orders"""
        if not self.is_connected():
            return []
        return self.ib.openOrders()
    
    def get_open_trades(self) -> List[Trade]:
        """Get all open trades (orders with status)"""
        if not self.is_connected():
            return []
        return self.ib.openTrades()
    
    # =========================================================================
    # POSITION & ACCOUNT METHODS
    # =========================================================================
    
    def get_positions(self) -> List[Position]:
        """Get all current positions"""
        if not self.is_connected():
            return []
        return self.ib.positions()
    
    def get_portfolio(self) -> List[PortfolioItem]:
        """Get portfolio with P&L information"""
        if not self.is_connected():
            return []
        return self.ib.portfolio()
    
    def get_account_values(self) -> Dict[str, float]:
        """
        Get key account values.
        
        Returns:
            Dict with account metrics like NetLiquidation, BuyingPower, etc.
        """
        if not self.is_connected():
            return {}
        
        values = {}
        key_tags = [
            'NetLiquidation',
            'BuyingPower', 
            'TotalCashValue',
            'UnrealizedPnL',
            'RealizedPnL',
            'AvailableFunds',
            'ExcessLiquidity',
            'GrossPositionValue',
        ]
        
        for av in self.ib.accountValues():
            if av.tag in key_tags and av.currency == 'USD':
                try:
                    values[av.tag] = float(av.value)
                except ValueError:
                    pass
        
        return values
    
    def get_account_summary(self) -> Dict[str, Any]:
        """Get comprehensive account summary"""
        values = self.get_account_values()
        positions = self.get_positions()
        
        return {
            'account': self.config.account,
            'mode': self.config.get_display_mode(),
            'connected': self.is_connected(),
            'net_liquidation': values.get('NetLiquidation', 0),
            'buying_power': values.get('BuyingPower', 0),
            'unrealized_pnl': values.get('UnrealizedPnL', 0),
            'realized_pnl': values.get('RealizedPnL', 0),
            'position_count': len(positions),
        }
    
    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================
    
    def _on_connected(self):
        """Handle connection event"""
        self.state = ConnectionState.CONNECTED
        logger.info("IBKR Connected event received")
        self._emit('connected')
    
    def _on_disconnected(self):
        """Handle disconnection event"""
        previous_state = self.state
        self.state = ConnectionState.DISCONNECTED
        logger.warning("IBKR Disconnected")
        
        self._emit('disconnected')
        
        # Engage kill switch on unexpected disconnect
        if previous_state == ConnectionState.CONNECTED:
            self.kill_switch.engage(
                reason=KillSwitchReason.DISCONNECT,
                details="Lost connection to IBKR",
                engaged_by="system"
            )
            
            # Start auto-reconnect if enabled
            if self.config.auto_reconnect:
                self._reconnect_task = asyncio.create_task(self._auto_reconnect())
    
    def _on_error(self, reqId, errorCode, errorString, contract):
        """Handle error event"""
        # Critical errors that should engage kill switch
        critical_errors = {
            1100,  # Connectivity lost
            1101,  # Connectivity restored (with data loss)
            2110,  # Connectivity restored (with data loss)
        }
        
        logger.error(f"IBKR Error {errorCode}: {errorString} (reqId: {reqId})")
        
        if errorCode in critical_errors:
            self.kill_switch.engage(
                reason=KillSwitchReason.ERROR,
                details=f"IBKR Error {errorCode}: {errorString}",
                engaged_by="system"
            )
        
        self._emit('error', errorCode, errorString, contract)
    
    def _on_order_status(self, trade: Trade):
        """Handle order status update"""
        status = trade.orderStatus.status
        logger.info(f"Order status: {trade.order.orderId} -> {status}")
        self._emit('order_status', trade)
    
    def _on_position(self, position: Position):
        """Handle position update"""
        logger.debug(f"Position update: {position.contract.symbol} {position.position}")
        self._emit('position_update', position)
    
    def _on_account_value(self, value):
        """Handle account value update"""
        self._emit('account_update', value)
    
    def _on_execution(self, trade, fill):
        """Handle execution/fill"""
        logger.info(f"Execution: {fill.contract.symbol} {fill.execution.side} "
                   f"{fill.execution.shares} @ {fill.execution.price}")
        self._emit('execution', trade, fill)
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def get_0dte_expiry(self) -> str:
        """Get today's expiration date in YYYYMMDD format"""
        return date.today().strftime('%Y%m%d')
    
    async def wait_for_fill(self, trade: Trade, timeout: int = 30) -> bool:
        """
        Wait for an order to fill.
        
        Args:
            trade: The trade to wait for
            timeout: Maximum seconds to wait
        
        Returns:
            True if filled, False if timeout or cancelled
        """
        start = datetime.now()
        
        while (datetime.now() - start).seconds < timeout:
            if trade.isDone():
                return trade.orderStatus.status == 'Filled'
            await asyncio.sleep(0.5)
        
        return False
    
    def create_limit_order(self, action: str, quantity: int, 
                          limit_price: float) -> LimitOrder:
        """
        Create a limit order.
        
        Args:
            action: 'BUY' or 'SELL'
            quantity: Number of contracts
            limit_price: Limit price
        
        Returns:
            LimitOrder object
        """
        return LimitOrder(
            action=action,
            totalQuantity=quantity,
            lmtPrice=round(limit_price, 2),
            tif='DAY'
        )
    
    def create_market_order(self, action: str, quantity: int) -> MarketOrder:
        """
        Create a market order.
        
        Args:
            action: 'BUY' or 'SELL'
            quantity: Number of contracts
        
        Returns:
            MarketOrder object
        """
        return MarketOrder(
            action=action,
            totalQuantity=quantity,
            tif='DAY'
        )
