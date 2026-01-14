"""
IBKR Connection Worker - FIXED VERSION

This module provides thread-safe IBKR connection handling that integrates
with the dedicated IB event loop thread.

REPLACES: The IBKRConnectionWorker class in live_trading_panel.py
"""

import logging
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal

# Import the dedicated IB loop
from engine.ib_loop import get_ib_loop, get_ib_signals, start_ib_loop

logger = logging.getLogger(__name__)


class IBKRConnectionManager(QObject):
    """
    Manages IBKR connection using the dedicated IB event loop thread.
    
    This replaces IBKRConnectionWorker (QThread-based) with a cleaner approach
    that uses the shared IB event loop.
    
    USAGE:
        manager = IBKRConnectionManager(config, kill_switch)
        manager.connection_success.connect(on_connected)
        manager.connection_failed.connect(on_failed)
        manager.connect()
    """
    
    # Signals for connection status
    connection_success = pyqtSignal(object)  # Emits IBKRConnection
    connection_failed = pyqtSignal(str)      # Emits error message
    disconnected = pyqtSignal()
    account_update = pyqtSignal(dict)        # Emits account info
    
    def __init__(self, config, kill_switch):
        super().__init__()
        self.config = config
        self.kill_switch = kill_switch
        self.connection = None
        
        # Get the IB loop
        self._ib_loop = get_ib_loop()
        
        # Ensure loop is started
        if not self._ib_loop.is_alive():
            start_ib_loop()
    
    def connect(self):
        """
        Start connection to IBKR.
        Non-blocking - results come via signals.
        """
        logger.info("Starting IBKR connection...")
        
        # Submit connection task to IB loop
        future = self._ib_loop.submit(self._async_connect())
        future.add_done_callback(self._on_connect_complete)
    
    def disconnect(self):
        """Disconnect from IBKR."""
        if self.connection:
            try:
                self.connection.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
            finally:
                self.connection = None
                self.disconnected.emit()
    
    def _on_connect_complete(self, future):
        """Callback when connection attempt completes."""
        try:
            result = future.result()
            if result['success']:
                self.connection = result['connection']
                self.connection_success.emit(self.connection)
                
                # Get account info
                if result.get('account_info'):
                    self.account_update.emit(result['account_info'])
            else:
                self.connection_failed.emit(result.get('error', 'Unknown error'))
        except Exception as e:
            logger.error(f"Connection callback error: {e}")
            self.connection_failed.emit(str(e))
    
    async def _async_connect(self) -> dict:
        """
        Async connection logic - runs in IB event loop thread.
        """
        try:
            # Import here to avoid issues if not installed
            from execution.ibkr_connection import IBKRConnection
            
            # Create connection
            connection = IBKRConnection(self.config, self.kill_switch)
            
            # Connect (this is the async part)
            success = await connection.connect()
            
            if success:
                logger.info("IBKR connection successful")
                
                # Get account info
                account_info = {}
                try:
                    account_info = await connection.get_account_summary()
                except Exception as e:
                    logger.warning(f"Could not get account info: {e}")
                
                return {
                    'success': True,
                    'connection': connection,
                    'account_info': account_info
                }
            else:
                return {
                    'success': False,
                    'error': "Connection failed - check TWS/Gateway is running"
                }
                
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def request_account_update(self):
        """Request fresh account info."""
        if not self.connection or not self.connection.is_connected():
            return
        
        future = self._ib_loop.submit(self._async_get_account())
        future.add_done_callback(self._on_account_update)
    
    async def _async_get_account(self) -> dict:
        """Get account info asynchronously."""
        if not self.connection:
            return {}
        try:
            return await self.connection.get_account_summary()
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return {}
    
    def _on_account_update(self, future):
        """Callback for account update."""
        try:
            result = future.result()
            if result:
                self.account_update.emit(result)
        except Exception as e:
            logger.error(f"Account update callback error: {e}")


class SafeIBKROperations:
    """
    Helper class providing safe, non-blocking IBKR operations.
    
    All methods submit async tasks to the IB loop and use callbacks.
    """
    
    def __init__(self, ib_connection):
        self.ib = ib_connection
        self._ib_loop = get_ib_loop()
        self._signals = get_ib_signals()
    
    def qualify_contracts(self, contracts, callback):
        """
        Qualify contracts safely.
        
        Args:
            contracts: Single contract or list of contracts
            callback: Function to call with results - callback(qualified_contracts)
        """
        if not isinstance(contracts, list):
            contracts = [contracts]
        
        future = self._ib_loop.submit(
            self._async_qualify(contracts)
        )
        future.add_done_callback(
            lambda f: self._handle_qualify_result(f, callback)
        )
    
    async def _async_qualify(self, contracts):
        """Qualify contracts in IB loop."""
        return await self.ib.ib.qualifyContractsAsync(*contracts)
    
    def _handle_qualify_result(self, future, callback):
        """Handle qualification result."""
        try:
            result = future.result()
            callback(result)
        except Exception as e:
            logger.error(f"Contract qualification error: {e}")
            callback(None)
    
    def place_order(self, contract, order, callback):
        """
        Place order safely.
        
        Args:
            contract: Contract to trade
            order: Order object
            callback: Function to call with trade result - callback(trade)
        """
        future = self._ib_loop.submit(
            self._async_place_order(contract, order)
        )
        future.add_done_callback(
            lambda f: self._handle_order_result(f, callback)
        )
    
    async def _async_place_order(self, contract, order):
        """Place order in IB loop."""
        return self.ib.ib.placeOrder(contract, order)
    
    def _handle_order_result(self, future, callback):
        """Handle order result."""
        try:
            trade = future.result()
            callback(trade)
        except Exception as e:
            logger.error(f"Order placement error: {e}")
            callback(None)
    
    def request_positions(self, callback):
        """
        Request current positions.
        
        Args:
            callback: Function to call with positions - callback(positions)
        """
        future = self._ib_loop.submit(self._async_positions())
        future.add_done_callback(
            lambda f: self._handle_positions_result(f, callback)
        )
    
    async def _async_positions(self):
        """Get positions in IB loop."""
        return await self.ib.ib.reqPositionsAsync()
    
    def _handle_positions_result(self, future, callback):
        """Handle positions result."""
        try:
            positions = future.result()
            callback(list(positions))
        except Exception as e:
            logger.error(f"Positions request error: {e}")
            callback([])