"""
IB Event Loop Thread - Dedicated asyncio event loop for IBKR operations.

This module solves the classic PyQt + asyncio + ib_async event loop conflict
by running all IBKR async operations in a dedicated thread with its own event loop.

RULES:
- Never call await or run_until_complete from PyQt code
- Always use ib_loop_thread.submit(coro) to run async IBKR operations
- Use callbacks or Qt signals to communicate results back to the UI
"""

import asyncio
import threading
import logging
from typing import Callable, Any, Optional, Coroutine
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class IBEventLoopThread(threading.Thread):
    """
    Dedicated thread running a single asyncio event loop for all IBKR operations.
    
    This is the ONLY place where asyncio operations should run.
    PyQt code submits coroutines here via submit() method.
    """
    
    def __init__(self):
        super().__init__(daemon=True, name="IBEventLoopThread")
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._started_event = threading.Event()
        self._stop_requested = False
    
    def run(self):
        """Run the event loop in this thread - called by thread.start()"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        logger.info("IB Event Loop Thread started")
        self._started_event.set()
        
        try:
            self.loop.run_forever()
        finally:
            # Clean shutdown
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()
            logger.info("IB Event Loop Thread stopped")
    
    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        """Wait until the event loop is running. Returns True if ready."""
        return self._started_event.wait(timeout)
    
    def submit(self, coro: Coroutine) -> asyncio.Future:
        """
        Submit a coroutine to run in the IB event loop.
        
        Returns a concurrent.futures.Future that can be used to:
        - Add callbacks via future.add_done_callback(fn)
        - Get result (blocking) via future.result()
        - Check completion via future.done()
        
        Usage:
            future = ib_loop.submit(self.ib.qualifyContractsAsync(contract))
            future.add_done_callback(lambda f: self.on_qualified(f.result()))
        """
        if self.loop is None:
            raise RuntimeError("IB event loop not started - call start() first")
        
        return asyncio.run_coroutine_threadsafe(coro, self.loop)
    
    def stop(self):
        """Stop the event loop gracefully"""
        if self.loop and self.loop.is_running():
            self._stop_requested = True
            self.loop.call_soon_threadsafe(self.loop.stop)


class IBSignalBridge(QObject):
    """
    Qt signal bridge for communicating IB results back to the UI thread.
    
    Use this to safely update UI from IB callback results.
    """
    
    # Generic signals for common operations
    connection_result = pyqtSignal(bool, str)  # success, message
    contract_qualified = pyqtSignal(object)    # qualified contract
    order_placed = pyqtSignal(object)          # trade object
    order_status = pyqtSignal(str, str)        # order_id, status
    account_update = pyqtSignal(dict)          # account summary
    position_update = pyqtSignal(list)         # positions list
    error = pyqtSignal(str)                    # error message
    
    # Custom signal for any data
    result_ready = pyqtSignal(str, object)     # operation_name, result
    
    def __init__(self):
        super().__init__()


# Singleton instance - import this in your modules
_ib_loop_instance: Optional[IBEventLoopThread] = None
_ib_signals_instance: Optional[IBSignalBridge] = None


def get_ib_loop() -> IBEventLoopThread:
    """Get the singleton IB event loop thread instance."""
    global _ib_loop_instance
    if _ib_loop_instance is None:
        _ib_loop_instance = IBEventLoopThread()
    return _ib_loop_instance


def get_ib_signals() -> IBSignalBridge:
    """Get the singleton IB signals bridge instance."""
    global _ib_signals_instance
    if _ib_signals_instance is None:
        _ib_signals_instance = IBSignalBridge()
    return _ib_signals_instance


def start_ib_loop() -> IBEventLoopThread:
    """Start the IB event loop thread (call once at app startup)."""
    loop = get_ib_loop()
    if not loop.is_alive():
        loop.start()
        loop.wait_until_ready()
        logger.info("IB Event Loop ready for operations")
    return loop


def stop_ib_loop():
    """Stop the IB event loop thread (call at app shutdown)."""
    global _ib_loop_instance
    if _ib_loop_instance and _ib_loop_instance.is_alive():
        _ib_loop_instance.stop()
        _ib_loop_instance.join(timeout=5.0)
        _ib_loop_instance = None