from datetime import datetime
import json
import pandas as pd
import logging
import asyncio
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import json
import unicodedata 

from engine.statistics import Statistics
from .back_test_worker import BacktestWorker
from .strategy_config_widget import StrategyConfigWidget
from data.mock_data_provider import MockDataProvider
import copy
import sys
import platform
import xlsxwriter


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== Configuration Classes ====================

from gui.back_test_config_widget import BacktestConfigWidget
from gui.results_widget import ResultsWidget
from data.polygon_data_provider import PolygonDataProvider

class ConnectionTestWorker(QThread):
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, api_key: str, use_mock: bool):
        super().__init__()
        self.api_key = api_key
        self.use_mock = use_mock
        
        
    def run(self):
        try:
            if self.use_mock:
                self.finished.emit(True, "Mock data provider ready!")
                return
            
            success = self._test_polygon_connection()
            if success:
                self.finished.emit(True, "API connection successful!")
            else:
                self.finished.emit(False, "API connection failed. Please check your API key.")
        except Exception as e:
            self.finished.emit(False, f"Connection test failed: {str(e)}")
    
    def _test_polygon_connection(self) -> bool:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def test_async():
                async with PolygonDataProvider(self.api_key) as provider:
                    return await provider.test_connection()
            
            result = loop.run_until_complete(test_async())
            loop.close()
            return result
        except Exception as e:
            logger.error(f"Polygon connection test failed: {e}")
            return False
class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.data_provider = None
        self.backtest_worker = None
        self.last_results = None  # Initialize this to store results
        self.connection_worker = None
        logger.info(f"Platform: {platform.system()} {platform.release()}")
        logger.info(f"Python: {sys.version}")
        
        # Add artificial progress tracking
        self.artificial_progress = 0
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_artificial_progress)
        
        self.init_ui()
        self.setup_style()
        
    def init_ui(self):
        """Initialize UI"""
        self.setWindowTitle("SPX 0DTE Options Backtester")
        self.setGeometry(100, 100, 1400, 900)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout()
        
        # Left panel - Configuration
        left_panel = self._create_left_panel()
        main_layout.addWidget(left_panel, 1)
        
        # Right panel - Results
        self.results_widget = ResultsWidget(self.get_selected_strategy())
        main_layout.addWidget(self.results_widget, 3)
        
        central_widget.setLayout(main_layout)
        
        # Status bar
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
        
        # Menu bar
        self._create_menu_bar()
        
    def update_artificial_progress(self):
        if self.artificial_progress < 98:
           self.artificial_progress += 2
    
        # Update progress bar
        self.progress_bar.setValue(self.artificial_progress)
    
        # Update status message
        self.status_bar.showMessage(f"Backtest in progress... {self.artificial_progress}%")
    
           
    def complete_artificial_backtest(self):
        """Complete the artificial backtest"""
        # Reset UI state
        self.run_backtest_btn.setEnabled(True)
        self.update_results_btn.setEnabled(True)
        self.stop_backtest_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.artificial_progress = 0
    
        # Show completion message
        self.status_bar.showMessage("Backtest completed.", 5000)
    
    def _create_left_panel(self):
        """Create configuration panel"""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("Configuration")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # API Configuration
        api_group = QGroupBox("API Configuration")
        api_layout = QVBoxLayout()
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setText("VGG0V1GnGumf21Yw7mMDwg7_derXxQSP")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_layout.addWidget(QLabel("Polygon.io API Key:"))
        api_layout.addWidget(self.api_key_input)
        
        # Add mock data checkbox
        self.use_mock_data = QCheckBox("Use Mock Data (No API Required)")
        self.use_mock_data.setToolTip(
            "Enable this to use realistic mock data instead of real Polygon.io data.\n"
            "Perfect for testing strategies without API costs."
        )
        self.use_mock_data.setChecked(False)  # Default to mock data
        self.use_mock_data.stateChanged.connect(self.on_mock_data_changed)
        api_layout.addWidget(self.use_mock_data)
        
        self.test_connection_btn = QPushButton("Test Connection")
        self.test_connection_btn.clicked.connect(self.test_api_connection)
        api_layout.addWidget(self.test_connection_btn)
        
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)
        
        # Backtest Configuration
        backtest_group = QGroupBox("Backtest Settings")
        backtest_layout = QVBoxLayout()
        self.backtest_config_widget = BacktestConfigWidget()
        backtest_layout.addWidget(self.backtest_config_widget)
        backtest_group.setLayout(backtest_layout)
        layout.addWidget(backtest_group)
        
        strategy_selection_group = QGroupBox("Strategy Selection")
        strategy_selection_layout = QVBoxLayout()

        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["Trades 16", "Trades 17"])
        self.strategy_combo.setCurrentIndex(0)  # Default to Trades 16
        
        self.strategy_combo.currentIndexChanged.connect(self.on_strategy_changed)

        strategy_selection_layout.addWidget(QLabel("Select strategy to run:"))
        strategy_selection_layout.addWidget(self.strategy_combo)

        strategy_selection_group.setLayout(strategy_selection_layout)
        layout.addWidget(strategy_selection_group)
        
        # Strategy Configuration
        strategy_group = QGroupBox("Strategy Parameters")
        strategy_group.setObjectName("Strategy Parameters") 
        strategy_layout = QVBoxLayout()
        strategy = self.get_selected_strategy()
        self.strategy_config_widget = StrategyConfigWidget(strategy)
        # Connect strategy widget signals
        self.strategy_config_widget.load_configuration_requested.connect(self.load_configuration)
        self.strategy_config_widget.export_results_requested.connect(self.export_results)
        strategy_layout.addWidget(self.strategy_config_widget)
        strategy_group.setLayout(strategy_layout)
        layout.addWidget(strategy_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.run_backtest_btn = QPushButton("Run Backtest")
        self.run_backtest_btn.clicked.connect(self.run_backtest)
        self.run_backtest_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        button_layout.addWidget(self.run_backtest_btn)
        
        self.stop_backtest_btn = QPushButton("Stop")
        self.stop_backtest_btn.clicked.connect(self.stop_backtest)
        self.stop_backtest_btn.setEnabled(False)
        self.stop_backtest_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        button_layout.addWidget(self.stop_backtest_btn)

        self.update_results_btn = QPushButton("Update Results")
        self.update_results_btn.clicked.connect(self.update_results_with_new_sizes)
        self.update_results_btn.setEnabled(False)  # Disabled until we have results
        self.update_results_btn.setStyleSheet("""
    QPushButton {
        background-color: #FF9800;
        color: white;
        font-weight: bold;
        padding: 10px;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #F57C00;
    }
    QPushButton:disabled {
        background-color: #cccccc;
    }
""")
        button_layout.addWidget(self.update_results_btn)
        
        layout.addLayout(button_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()
        panel.setLayout(layout)
        return panel
    
    def get_selected_strategy(self):
        """Get the selected strategy name"""
        return self.strategy_combo.currentText()
    
    def on_strategy_changed(self, index):
        """Handle strategy selection change"""
        strategy = self.get_selected_strategy()
    
        # Remove old strategy config widget
        strategy_group = self.findChild(QGroupBox, "Strategy Parameters")
        if strategy_group:
           layout = strategy_group.layout()
           if layout:
              # Remove old widget
              old_widget = layout.takeAt(0)
              if old_widget:
                old_widget.widget().deleteLater()
            
              # Create new widget with selected strategy
              self.strategy_config_widget = StrategyConfigWidget(strategy)
              self.strategy_config_widget.load_configuration_requested.connect(self.load_configuration)
              self.strategy_config_widget.export_results_requested.connect(self.export_results)
              layout.addWidget(self.strategy_config_widget)
              
        central_widget = self.centralWidget()
        if central_widget:
           main_layout = central_widget.layout()
           if main_layout and main_layout.count() >= 2:
              # Remove old results widget (it's the second item in the horizontal layout)
              old_results_item = main_layout.itemAt(1)
              if old_results_item:
                old_results_widget = old_results_item.widget()
                if old_results_widget:
                    main_layout.removeWidget(old_results_widget)
                    old_results_widget.deleteLater()
              
              
              # Create new results widget with the selected strategy
              self.results_widget = ResultsWidget(strategy)
              main_layout.addWidget(self.results_widget, 3)  # Keep the 3:1 ratio
            
        
        logger.info(f"Strategy changed to: {strategy}")
        self.status_bar.showMessage(f"Strategy changed to: {strategy}", 3000)
    
    def _create_menu_bar(self):
        """Create menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('File')
        
        save_config_action = QAction('Save Configuration', self)
        save_config_action.triggered.connect(self.save_configuration)
        file_menu.addAction(save_config_action)
        
        load_config_action = QAction('Load Configuration', self)
        load_config_action.triggered.connect(self.load_configuration)
        file_menu.addAction(load_config_action)
        
        file_menu.addSeparator()
        
        export_results_action = QAction('Export Results', self)
        export_results_action.triggered.connect(self.export_results)
        file_menu.addAction(export_results_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('Exit', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Help menu
        help_menu = menubar.addMenu('Help')
        
        about_action = QAction('About', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def setup_style(self):
        """Set up application style"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
    
    def on_mock_data_changed(self, state):
        """Handle mock data checkbox change"""
        if state == 2:  # Checked
            self.api_key_input.setEnabled(False)
            self.status_bar.showMessage("Using mock data provider", 3000)
        else:
            self.api_key_input.setEnabled(True)
            self.status_bar.showMessage("Using real Polygon.io API", 3000)
            
    def _sanitize_api_key(self, s: str) -> str:
          # Trim, drop any whitespace (including zero-width) and control chars
          s = s.strip()
          s = ''.join(ch for ch in s if not ch.isspace())
          s = ''.join(ch for ch in s if unicodedata.category(ch)[0] != 'C')
          return s
    
    def test_api_connection(self):
       self.test_connection_btn.setEnabled(False)
       self.test_connection_btn.setText("Testing...")
       self.status_bar.showMessage("Testing connection...")
    
       api_key = self._sanitize_api_key(self.api_key_input.text())
       use_mock = self.use_mock_data.isChecked()
    
       self.connection_worker = ConnectionTestWorker(api_key, use_mock)
       self.connection_worker.finished.connect(self.on_connection_test_finished)
       self.connection_worker.start()
       
    def on_connection_test_finished(self, success: bool, message: str):
        self.test_connection_btn.setEnabled(True)
        self.test_connection_btn.setText("Test Connection")
    
        if success:
           QMessageBox.information(self, "Success", message)
           self.status_bar.showMessage(message, 5000)
        else:
           QMessageBox.warning(self, "Error", message)
           self.status_bar.showMessage("Connection test failed", 5000)
    
        if self.connection_worker:
           self.connection_worker.deleteLater()
           self.connection_worker = None
           
    def _quick_validation(self) -> bool:
        api_key = self._sanitize_api_key(self.api_key_input.text())
        return len(api_key) > 10
    
    def _test_connection_async(self):
        """Test connection asynchronously"""
        if self.use_mock_data.isChecked():
            # Mock data always succeeds
            QMessageBox.information(self, "Success", "Mock data provider ready!")
            self.status_bar.showMessage("Mock data provider ready", 5000)
            self.test_connection_btn.setEnabled(True)
            return
        
        api_key = self._sanitize_api_key(self.api_key_input.text())
        
        async def test():
            async with PolygonDataProvider(api_key) as provider:
                return await provider.test_connection()
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(test())
            
            if success:
                QMessageBox.information(self, "Success", f"API connection successful! {api_key}")
                self.status_bar.showMessage("API connection successful", 5000)
            else:
                QMessageBox.warning(self, "Error", f"API connection failed. Please check your API key : {api_key}.")
                self.status_bar.showMessage("API connection failed", 5000)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Connection test failed: {str(e)}")
            self.status_bar.showMessage("Connection test failed", 5000)
        
        self.test_connection_btn.setEnabled(True)
    
    def _test_connection(self):
        api_key = self._sanitize_api_key(self.api_key_input.text())
        async def test():
            async with PolygonDataProvider(api_key) as provider:
                return await provider.test_connection()
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(test())
            
            if not success:
                QMessageBox.information(self, "Error", "API connection failed. Please check your API key.")
                return False
            return True
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Connection test failed: {str(e)}")
            self.status_bar.showMessage("Connection test failed", 5000)
    
    def run_backtest(self):
        """Run backtest"""
        if not self._test_connection():
            return
        # Get configurations
        backtest_config = self.backtest_config_widget.get_config()
        strategy_config = self.strategy_config_widget.get_config()
        
        selected_strategy = self.get_selected_strategy()
        
        # Create data provider based on checkbox
        if self.use_mock_data.isChecked():
            self.data_provider = MockDataProvider()
            logger.info("Using mock data provider for backtest")
        else:
            api_key = self._sanitize_api_key(self.api_key_input.text())
            if not api_key:
                QMessageBox.warning(self, "Error", "Please enter API key")
                return
            self.data_provider = PolygonDataProvider(api_key)
            logger.info("Using Polygon data provider for backtest")
        
        # Reset results
        self.last_results = None
        
        # Reset results and progress
        self.last_results = None
        self.artificial_progress = 0
        
        # Disable buttons
        self.run_backtest_btn.setEnabled(False)
        self.stop_backtest_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Start artificial progress timer (fires every 8 seconds)
        self.progress_timer.start(2400)  # 8000 milliseconds = 8 seconds
        
        # Create and start worker
        self.backtest_worker = BacktestWorker(
            self.data_provider, backtest_config, strategy_config, selected_strategy
        )
        # Disconnect the original progress signal and connect to finished only
        # self.backtest_worker.progress.connect(self.update_progress)  # Comment out or remove
        self.backtest_worker.status.connect(self.status_bar.showMessage)
        self.backtest_worker.finished.connect(self.on_backtest_finished_with_progress)
        self.backtest_worker.error.connect(self.on_backtest_error)
        self.backtest_worker.start()
        
        self.status_bar.showMessage("Backtest started...")
    
    def update_progress(self, value):
        """Update progress bar"""
        self.progress_bar.setValue(value)
    
    def stop_backtest(self):
        """Stop running backtest and artificial progress"""
        # Stop the progress timer
        self.progress_timer.stop()
        self.artificial_progress = 0
    
        # Stop the worker if running
        if self.backtest_worker and self.backtest_worker.isRunning():
           self.backtest_worker.terminate()
           self.backtest_worker.wait()
    
       # Reset UI
        self.run_backtest_btn.setEnabled(True)
        self.stop_backtest_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
    
        self.status_bar.showMessage("Backtest stopped", 5000)
    
    def on_backtest_finished_with_progress(self, results):
        """Handle backtest completion with artificial progress"""
        self.status_bar.showMessage("Processing results...")
        self.finish_with_results(results)

    def finish_with_results(self, results):
        """Complete the backtest with actual results"""
        # Reset UI
        self.run_backtest_btn.setEnabled(True)
        self.update_results_btn.setEnabled(True)
        self.stop_backtest_btn.setEnabled(False)
        
        if results:
           # Store and display results
           self.last_results = results
           if(self.progress_bar.value() < 80):
               self.progress_bar.setValue(80)
           self.results_widget.update_results(results)
           self.progress_bar.setValue(95)
        
           # Show summary
           stats = results.get('statistics', {})
           total_trades = stats.get('total_trades', 0)
           total_pnl = stats.get('total_pnl', 0)
           win_rate = stats.get('win_rate', 0)
        
           self.status_bar.showMessage(
            f"Backtest completed: {total_trades} trades, "
            f"P&L: ${total_pnl:,.2f}, Win Rate: {win_rate:.1%}", 
            10000
        )
           logger.info(f"Backtest completed successfully with {total_trades} trades")
        else:
           self.status_bar.showMessage("Backtest completed (no results)", 5000)
        self.progress_bar.setValue(100)
        self.progress_bar.setVisible(False)
        self.artificial_progress = 0
        self.progress_timer.stop()
        


    def update_results_with_new_sizes(self):
        if not self.last_results:
           QMessageBox.information(self, "No Results", "Please run a backtest first")
           return
    
        # Get current trade sizes from strategy config
        strategy_config = self.strategy_config_widget.get_config()
        iron_1_size = strategy_config.iron_1_trade_size
        straddle_1_size = strategy_config.straddle_1_trade_size
        iron_2_size = strategy_config.iron_2_trade_size
        straddle_2_size = strategy_config.straddle_2_trade_size
        iron_3_size = strategy_config.iron_3_trade_size
        straddle_3_size = strategy_config.straddle_3_trade_size
        cs_1_size = strategy_config.cs_1_trade_size
    
        self.status_bar.showMessage("Updating results with new trade sizes...")
    
        # Create scaled copy of results
        scaled_results = self._scale_results(self.last_results, iron_1_size, straddle_1_size, iron_2_size, straddle_2_size, iron_3_size, straddle_3_size, cs_1_size)
        self.last_results = scaled_results  # Update last_results to the scaled version
        # Update results widget
        self.results_widget.update_results(scaled_results)
    
    # Show summary in status bar
        stats = scaled_results.get('statistics', {})
        total_trades = stats.get('total_trades', 0)
        total_pnl = stats.get('total_pnl', 0)
        win_rate = stats.get('win_rate', 0)
    
        self.status_bar.showMessage(
           f"Results updated: {total_trades} trades, "
           f"P&L: ${total_pnl:,.2f}, Win Rate: {win_rate:.1%} "
           f"(Iron 1: {iron_1_size}, Straddle 1: {straddle_1_size}), (Iron 2: {iron_2_size} Straddle 2: {straddle_2_size})"
           , 
        10000
         )
    
        logger.info(f"Results updated with Iron 1 size: {iron_1_size}, Straddle 1 size: {straddle_1_size}, Iron 2 size: {iron_2_size} Straddle 2 size: {straddle_2_size}")
    
    def _scale_results(self, original_results, iron_1_size, straddle_1_size, iron_2_size, straddle_2_size, iron_3_size, straddle_3_size, cs_1_size):
        scaled_results = copy.deepcopy(original_results)
        scaled_daily_pnl = {}
        total_capital_used = 0.0
    
        for trade in scaled_results['trades']:
            if trade.trade_type == "Iron Condor 1":
               scale_factor = iron_1_size
            elif trade.trade_type == "Straddle 1":
               scale_factor = straddle_1_size
            elif trade.trade_type == "Iron Condor 2":
               scale_factor = iron_2_size
            elif trade.trade_type == "Straddle 2":
               scale_factor = straddle_2_size
            elif "Iron Condor 3" in trade.trade_type:
               scale_factor = iron_3_size
            elif "Straddle 3" in trade.trade_type:
               scale_factor = straddle_3_size
            elif trade.trade_type == "Credit Spread 1(a)" or trade.trade_type == "Credit Spread 1(b)":
               scale_factor = cs_1_size
            elif trade.trade_type == "Underlying Cover 1(a)":
               scale_factor = int(cs_1_size*trade.metadata.get('uc_1_cash_risk_percentage',1))
            else:
                scale_factor = 1  # Default fallback
        
            # Scale the trade P&L and size
            trade.calculate_pnl(scale_factor)
            trade.calculate_pnl_without_commission(scale_factor)
            trade.calculate_used_capital()
            
            for contract, details in trade.contracts.items():
                   sign = 1 if details['position'] > 0 else -1
                   details['position'] = scale_factor*sign if trade.trade_type != "Underlying Cover 1(a)" else int(scale_factor*100*trade.metadata.get('spx_spy_ratio',10.0))*sign
                   trade.contracts[contract] = details
               
    
    
        total_capital_used = sum(t.used_capital for t in scaled_results['trades'])
    # Recalculate daily P&L
        for date, trades_that_day in self._group_trades_by_date(scaled_results['trades']).items():
            daily_pnl = sum(trade.pnl for trade in trades_that_day)
            scaled_daily_pnl[date] = daily_pnl
    
        scaled_results['daily_pnl'] = scaled_daily_pnl
    
        # Recalculate equity curve
        scaled_results['equity_curve'] = self._recalculate_equity_curve(
        total_capital_used,  # Initial capital
        scaled_daily_pnl
    )
    
    # Recalculate statistics
        scaled_results['statistics'] = Statistics._calculate_statistics(
        scaled_results['trades'], 
        scaled_results['equity_curve'], 
        scaled_daily_pnl,
        self.get_selected_strategy()
    )
    
        return scaled_results

    def _group_trades_by_date(self, trades):
        from collections import defaultdict
        grouped = defaultdict(list)
    
        for trade in trades:
            trade_date = trade.entry_time.date()
            grouped[trade_date] = grouped[trade_date] + [trade]
    
        return dict(grouped)

    def _recalculate_equity_curve(self, initial_capital, daily_pnl):
        equity_curve = []
        running_capital = initial_capital
        sorted_dates = sorted(daily_pnl.keys())
    
        if sorted_dates:
           equity_curve.append((sorted_dates[0], initial_capital))
        
        for date in sorted_dates:
            running_capital += daily_pnl[date]
            equity_curve.append((date, running_capital))
    
        return equity_curve

    
    def on_backtest_error(self, error_msg):
        """Handle backtest error"""
        # Stop artificial progress
        self.progress_timer.stop()
        self.artificial_progress = 0
    
        # Reset UI
        self.run_backtest_btn.setEnabled(True)
        self.stop_backtest_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
    
        QMessageBox.critical(self, "Backtest Error", f"Error: {error_msg}")
        self.status_bar.showMessage("Backtest failed", 5000)
        logger.error(f"Backtest error: {error_msg}")
    
    def save_configuration(self):
        """Save current configuration to file"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Configuration", "", "JSON Files (*.json)"
        )
        
        if filename:
            config = {
                'backtest': self.backtest_config_widget.get_config().to_dict(),
                'strategy': self.get_selected_strategy(),
                'strategy_parameters': self.strategy_config_widget.get_config().to_dict(),
                'api_key': self.api_key_input.text(),
                'use_mock_data': self.use_mock_data.isChecked()
            }
            
            try:
                with open(filename, 'w') as f:
                    json.dump(config, f, indent=2, default=str)
                self.status_bar.showMessage(f"Configuration saved to {filename}", 5000)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save configuration: {e}")
    
    def load_configuration(self):
        """Load configuration from file"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Configuration", "", "JSON Files (*.json)"
        )
        
        if filename:
            try:
                with open(filename, 'r') as f:
                    config = json.load(f)
                
                # Load API key
                if 'api_key' in config:
                    self.api_key_input.setText(config['api_key'])
                
                # Load mock data setting
                if 'use_mock_data' in config:
                    self.use_mock_data.setChecked(config['use_mock_data'])
                
                # Load backtest config
                if 'backtest' in config:
                    bc = config['backtest']
                    self.backtest_config_widget.start_date.setDate(
                        QDate.fromString(bc['start_date'][:10], 'yyyy-MM-dd')
                    )
                    self.backtest_config_widget.end_date.setDate(
                        QDate.fromString(bc['end_date'][:10], 'yyyy-MM-dd')
                    )
                   
                    self.backtest_config_widget.commission.setValue(bc['commission_per_contract'])
                    self.backtest_config_widget.spy_commission_per_share.setValue(bc['spy_commission_per_share'])
                
                
                # Load strategy config
                if 'strategy_parameters' in config:
                    strategy = config['strategy']
                    index = self.strategy_combo.findText(strategy)
                    if index != -1:
                        self.strategy_combo.setCurrentIndex(index)
                          
                    sc = config['strategy_parameters']
                    if strategy == "Trades 16":
                       self.strategy_config_widget.iron_1_consecutive_candles.setValue(sc['iron_1_consecutive_candles'])
                       self.strategy_config_widget.iron_1_volume_threshold.setValue(sc['iron_1_volume_threshold'])
                       self.strategy_config_widget.iron_1_lookback_candles.setValue(sc['iron_1_lookback_candles'])
                       self.strategy_config_widget.iron_1_avg_range_candles.setValue(sc['iron_1_avg_range_candles'])
                       self.strategy_config_widget.iron_1_range_threshold.setValue(sc['iron_1_range_threshold'])
                       self.strategy_config_widget.straddle_1_trade_size.setValue(sc['straddle_1_trade_size'])
                       self.strategy_config_widget.iron_1_trade_size.setValue(sc['iron_1_trade_size'])
                       self.strategy_config_widget.iron_1_target_win_loss_ratio.setValue(sc['iron_1_target_win_loss_ratio'])
                       self.strategy_config_widget.iron_2_trade_size.setValue(sc['iron_2_trade_size'])
                       self.strategy_config_widget.iron_2_trigger_multiplier.setValue(sc['iron_2_trigger_multiplier'])
                       self.strategy_config_widget.iron_2_direction_lookback.setValue(sc['iron_2_direction_lookback'])
                       self.strategy_config_widget.iron_2_range_recent_candles.setValue(sc['iron_2_range_recent_candles'])
                       self.strategy_config_widget.iron_2_range_reference_candles.setValue(sc['iron_2_range_reference_candles'])
                       self.strategy_config_widget.iron_2_range_threshold.setValue(sc['iron_2_range_threshold'])
                       self.strategy_config_widget.iron_2_target_win_loss_ratio.setValue(sc['iron_2_target_win_loss_ratio'])
                       self.strategy_config_widget.straddle_2_trade_size.setValue(sc['straddle_2_trade_size'])
                       self.strategy_config_widget.straddle_2_trigger_multiplier.setValue(sc['straddle_2_trigger_multiplier'])
                       self.strategy_config_widget.straddle_2_exit_percentage.setValue(sc['straddle_2_exit_percentage'])
                       self.strategy_config_widget.straddle_2_exit_multiplier.setValue(sc['straddle_2_exit_multiplier'])
                       self.strategy_config_widget.straddle_1_distance_multiplier.setValue(sc['straddle_1_distance_multiplier'])
                       self.strategy_config_widget.straddle_1_exit_percentage.setValue(sc['straddle_1_exit_percentage'])
                       self.strategy_config_widget.straddle_1_exit_multiplier.setValue(sc['straddle_1_exit_multiplier'])
                       self.strategy_config_widget.iron_3_trade_size.setValue(sc['iron_3_trade_size'])
                       self.strategy_config_widget.iron_3_trigger_multiplier.setValue(sc['iron_3_trigger_multiplier'])
                       self.strategy_config_widget.iron_3_distance_multiplier.setValue(sc['iron_3_distance_multiplier'])
                       self.strategy_config_widget.iron_3_target_win_loss_ratio.setValue(sc['iron_3_target_win_loss_ratio'])
                       self.strategy_config_widget.iron_3_direction_lookback.setValue(sc['iron_3_direction_lookback'])
                       self.strategy_config_widget.iron_3_range_recent_candles.setValue(sc['iron_3_range_recent_candles'])
                       self.strategy_config_widget.iron_3_range_reference_candles.setValue(sc['iron_3_range_reference_candles'])
                       self.strategy_config_widget.iron_3_range_threshold.setValue(sc['iron_3_range_threshold'])
                       self.strategy_config_widget.straddle_3_trade_size.setValue(sc['straddle_3_trade_size'])
                       self.strategy_config_widget.straddle_3_trigger_multiplier.setValue(sc['straddle_3_trigger_multiplier'])
                       self.strategy_config_widget.straddle_3_exit_percentage.setValue(sc['straddle_3_exit_percentage'])
                       self.strategy_config_widget.straddle_3_exit_multiplier.setValue(sc['straddle_3_exit_multiplier'])
                       self.strategy_config_widget.straddle_itm_override_multiplier.setValue(sc['straddle_itm_override_multiplier'])
                    elif strategy == "Trades 17":
                          self.strategy_config_widget.cs_1_trade_size.setValue(sc['cs_1_trade_size'])
                          self.strategy_config_widget.cs_1_lookback_candles.setValue(sc['cs_1_lookback_candles'])
                          self.strategy_config_widget.cs_1_avg_range_candles.setValue(sc['cs_1_avg_range_candles'])
                          self.strategy_config_widget.cs_1_range_threshold.setValue(sc['cs_1_range_threshold'])
                          self.strategy_config_widget.cs_1_target_win_loss_ratio.setValue(sc['cs_1_target_win_loss_ratio'])
                          self.strategy_config_widget.cs_1_volume_threshold.setValue(sc['cs_1_volume_threshold'])
                          self.strategy_config_widget.cs_1_consecutive_candles.setValue(sc['cs_1_consecutive_candles'])
                          self.strategy_config_widget.lo_1_cover_risk_percentage.setValue(sc['lo_1_cover_risk_percentage'])
                          self.strategy_config_widget.lo_1_strike_multiplier.setValue(sc['lo_1_strike_multiplier'])



                        
                
                self.status_bar.showMessage(f"Configuration loaded from {filename}", 5000)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load configuration: {e}")
    
    def export_results(self):
        """Export backtest results to Excel file with three tabs using XlsxWriter"""
        if not self.last_results:
           QMessageBox.information(self, "No Results", "Please run a backtest first")
           return

        filename, _ = QFileDialog.getSaveFileName(
        self,
        "Export Results",
        f"backtest_results_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        "Excel Files (*.xlsx)"
    )

        if not filename:
           return

        try:
           # Prepare data for Tab 1: Grouped Trades
           grouped_trades_data = []
           for trade in self.last_results["trades"]:
               wings = trade.metadata.get("wing", "")
               short_strikes = ""
               if "Iron Condor" in trade.trade_type:
                  for contract, details in trade.contracts.items():
                    if "short" in details.get('leg_type', ''):
                        short_strikes = f"{details.get('strike', '')}"
               elif "Credit Spread" in trade.trade_type:
                  for contract, details in trade.contracts.items():
                    if "short" in details.get('leg_type', ''):
                        short_strikes = f"{details.get('strike', '')}"
               elif "Long Option" in trade.trade_type:
                   for contract, details in trade.contracts.items():
                    if "long" in details.get('leg_type', ''):
                        short_strikes = f"{details.get('strike', '')}"

               trade_label = trade.trade_type
               if trade.metadata.get("representation"):
                  trade_label = f"{trade.trade_type} {trade.metadata['representation']}"

               grouped_trades_data.append({
                "Date": trade.entry_time.strftime("%b %d, %Y") if trade.entry_time else "",
                "Trade Label": trade_label,
                "Short Strikes": short_strikes,
                "Wings": wings if wings else "",
                "Size": trade.size,
                "Entry Time": trade.entry_time.strftime("%I:%M %p"),
                "Net Premium": f"{-trade.metadata.get('net_premium', 0):.2f}" if "Iron Condor" in trade.trade_type else f"{trade.metadata.get('net_premium', 0):.2f}",
                "Entry SPX Price": f"{trade.metadata.get('entry_spx_price', ''):.2f}",
                "Exit SPX Price": f"{trade.metadata.get('exit_spx_price', ''):.2f}",
                "PnL without Commission": f"${trade.pnl_without_commission:,.0f}",
                "PnL": f"${trade.pnl:,.0f}"
            })

        # Prepare data for Tab 2: Individual Trades
           individual_trades_data = []
           for trade in self.last_results["trades"]:
               trade_group = trade.trade_type
               for contract, details in trade.contracts.items():
                   position_type = "Long" if ("long" in details.get('leg_type', '') or "buy" in details.get('leg_type', '')) else "Short" if ("short" in details.get('leg_type', '') or "sell" in details.get('leg_type', '')) else ""
                   option_type = "Call" if "call" in details.get('leg_type', '') else "Put" if "put" in details.get('leg_type', '') else ""
                   
                   strike_string  = f"{details.get('strike', '')}"
                   trade_detail = f"{strike_string} {position_type} {option_type}".strip()
                   entry_price = details.get('entry_price', 0)
                   exit_price = details.get('exit_price', 0)
                   position = details.get('position', 0)
                   individual_pnl_no_comm = details.get('pnl_without_commission', 0) * abs(position)
                   individual_pnl = details.get('pnl', 0) * abs(position)

                   individual_trades_data.append({
                    "Date": trade.entry_time.strftime("%b %d, %Y") if trade.entry_time else "",
                    "Trade Detail": trade_detail,
                    "Trade Group": trade_group,
                    "Entry Size": abs(position),
                    "Entry Time": trade.entry_time.strftime("%I:%M %p") if trade.entry_time else "",
                    "Net Premium": f"{entry_price:.2f}" if 'Long' in position_type else f"{-entry_price:.2f}",
                    "Entry SPX Price": f"{trade.metadata.get('entry_spx_price', ''):.2f}" if trade.metadata and trade.metadata.get('entry_spx_price') else "",
                    "Exit SPX Price": f"{trade.metadata.get('exit_spx_price', ''):.2f}" if trade.metadata and trade.metadata.get('exit_spx_price') else "",
                    "PnL without Commission": f"${individual_pnl_no_comm:,.0f}",
                    "PnL": f"${individual_pnl:,.0f}"
                })

        # Prepare data for Tab 3: Daily PnL
           daily_pnl_dict = {}
           for trade in self.last_results["trades"]:
               # Use exit_time if available (for closed trades), otherwise use entry_time
               trade_date = trade.exit_time if trade.exit_time else trade.entry_time
               if trade_date:
                  date_key = trade_date.date()
                  if date_key not in daily_pnl_dict:
                    daily_pnl_dict[date_key] = {
                        'pnl': 0.0,
                        'pnl_without_commission': 0.0
                    }
                  daily_pnl_dict[date_key]['pnl'] += trade.pnl
                  daily_pnl_dict[date_key]['pnl_without_commission'] += trade.pnl_without_commission

           # Convert daily PnL dictionary to list format and sort by date
           daily_pnl_data = []
           for date, pnl_values in sorted(daily_pnl_dict.items()):
               daily_pnl_data.append({
                "Date": date.strftime("%b %d, %Y"),
                "PnL": f"${pnl_values['pnl']:,.0f}",
                "PnL without Commission": f"${pnl_values['pnl_without_commission']:,.0f}"
            })

           # Create DataFrames
           df_grouped = pd.DataFrame(grouped_trades_data)
           df_individual = pd.DataFrame(individual_trades_data)
           df_daily_pnl = pd.DataFrame(daily_pnl_data)

           # Export with XlsxWriter
           with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
                df_grouped.to_excel(writer, sheet_name='Grouped Trades', index=False)
                df_individual.to_excel(writer, sheet_name='Individual Trades', index=False)
                df_daily_pnl.to_excel(writer, sheet_name='Daily PnL', index=False)

                workbook = writer.book
                grouped_sheet = writer.sheets['Grouped Trades']
                individual_sheet = writer.sheets['Individual Trades']
                daily_pnl_sheet = writer.sheets['Daily PnL']

                # Formatting
                header_format = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#366092', 'font_color': 'white'})
                light_fill_format = workbook.add_format({'bg_color': '#F2F2F2'})
                center_align = workbook.add_format({'align': 'center'})
                right_align = workbook.add_format({'align': 'right'})

                # Function to format a sheet
                def format_sheet(sheet, df):
                    for col_num, col_name in enumerate(df.columns):
                        sheet.write(0, col_num, col_name, header_format)
                        column_width = min(max(df[col_name].astype(str).map(len).max(), len(col_name)) + 2, 50)
                        sheet.set_column(col_num, col_num, column_width)

                    for row_num in range(1, len(df) + 1):
                       if row_num % 2 == 0:
                          sheet.set_row(row_num, cell_format=light_fill_format)

                    # Align PnL columns right, others center
                    for col_num, col_name in enumerate(df.columns):
                        if 'PnL' in col_name:
                           sheet.set_column(col_num, col_num, None, right_align)
                        elif col_name in ['Short Strikes', 'Wings', 'Size', 'Date']:
                           sheet.set_column(col_num, col_num, None, center_align)

                format_sheet(grouped_sheet, df_grouped)
                format_sheet(individual_sheet, df_individual)
                format_sheet(daily_pnl_sheet, df_daily_pnl)

                # Add a summary row to Daily PnL sheet if there's data
                if len(daily_pnl_data) > 0:
                   total_row = len(df_daily_pnl) + 1
                   total_format = workbook.add_format({'bold': True, 'bg_color': '#E0E0E0', 'align': 'right'})
                
                   # Write "Total" label
                   daily_pnl_sheet.write(total_row, 0, "Total", total_format)
                
                   # Calculate and write totals
                   total_pnl = sum(daily_pnl_dict[date]['pnl'] for date in daily_pnl_dict)
                   total_pnl_no_comm = sum(daily_pnl_dict[date]['pnl_without_commission'] for date in daily_pnl_dict)
                
                   daily_pnl_sheet.write(total_row, 1, f"${total_pnl:,.0f}", total_format)
                   daily_pnl_sheet.write(total_row, 2, f"${total_pnl_no_comm:,.0f}", total_format)

           QMessageBox.information(
            self,
            "Export Successful",
            f"Results exported successfully to:\n{filename}\n\n"
            f"📊 {len(grouped_trades_data)} grouped trades\n"
            f"📋 {len(individual_trades_data)} individual contract details\n"
            f"📅 {len(daily_pnl_data)} daily PnL records"
        )
           self.status_bar.showMessage(f"Results exported to {filename}", 5000)
           logger.info(f"Results exported to Excel: {filename}")

        except ImportError:
           QMessageBox.warning(
            self,
            "Missing Dependency",
            "Please install XlsxWriter to export to Excel:\npip install XlsxWriter"
        )
        except Exception as e:
            QMessageBox.warning(self, "Export Error", f"Failed to export results:\n{str(e)}")
            logger.error(f"Export error: {e}")

    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About SPX 0DTE Backtester",
            """<h2>SPX 0DTE Options Backtester</h2>
            <p>Professional backtesting platform for SPX 0DTE options strategies</p>
            <p><b>Version:</b> 1.0.0</p>
            <p><b>Features:</b></p>
            <ul>
                <li>Iron Condor with configurable win/loss ratios</li>
                <li>Straddle with partial exit capabilities</li>
                <li>Mock data provider for testing</li>
                <li>Real-time data from Polygon.io</li>
                <li>Comprehensive performance analytics</li>
                <li>Professional GUI with real-time updates</li>
            </ul>
            <p><b>Strategies:</b></p>
            <ul>
                <li><b>Iron Condor (Iron 1):</b> ATM short strikes with target 1.5:1 win/loss ratio</li>
                <li><b>Straddle (Straddle 1):</b> Entered with Iron Condor, partial exits at 2x entry price</li>
            </ul>
            <p><b>Author:</b> Mohamed Mahmoud Khouna </p>"""
        )