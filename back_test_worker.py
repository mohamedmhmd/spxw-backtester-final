import asyncio
import logging
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from back_test_engine import BacktestEngine  # Assuming this is defined in backtest_engine.py
# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BacktestWorker(QThread):
    """Worker thread for running backtests"""
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, data_provider, config, strategy):
        super().__init__()
        self.data_provider = data_provider
        self.config = config
        self.strategy = strategy
        
    def run(self):
        """Run backtest in thread"""
        try:
            self.status.emit("Starting backtest...")
            
            # Create new event loop for thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run backtest
            engine = BacktestEngine(self.data_provider)
            results = loop.run_until_complete(
                engine.run_backtest(self.config, self.strategy)
            )
            
            self.finished.emit(results)
            
        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"Backtest error: {e}", exc_info=True)