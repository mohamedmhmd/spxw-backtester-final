#!/usr/bin/env python3
"""
SPX 0DTE Options Backtesting System
Professional backtesting platform for SPX 0DTE options strategies
"""

import sys
import logging
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from engine.ib_loop import start_ib_loop, stop_ib_loop

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from gui.main_window import MainWindow  
def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle('Fusion')
    start_ib_loop()
    logger.info("IB Event Loop started")
    
    # Create and show main window
    window = MainWindow()
    window.show()

    app.aboutToQuit.connect(stop_ib_loop)
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()