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
        self.results_widget = ResultsWidget()
        main_layout.addWidget(self.results_widget, 3)
        
        central_widget.setLayout(main_layout)
        
        # Status bar
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
        
        # Menu bar
        self._create_menu_bar()
        
    def update_artificial_progress(self):
        """Update artificial progress by 5% every 8 seconds"""
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
        
        # Strategy Configuration
        strategy_group = QGroupBox("Strategy Parameters")
        strategy_layout = QVBoxLayout()
        self.strategy_config_widget = StrategyConfigWidget()
        self.strategy_config_widget = StrategyConfigWidget()
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
        self.progress_timer.start(20000)  # 8000 milliseconds = 8 seconds
        
        # Create and start worker
        self.backtest_worker = BacktestWorker(
            self.data_provider, backtest_config, strategy_config
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
        # Stop the timer if still running
        self.progress_timer.stop()
    
        # Ensure progress shows 100%
        self.progress_bar.setValue(100)
        self.status_bar.showMessage("Processing results...")
    
        # Small delay for visual effect
        QTimer.singleShot(500, lambda: self.finish_with_results(results))

    def finish_with_results(self, results):
        """Complete the backtest with actual results"""
        # Reset UI
        self.run_backtest_btn.setEnabled(True)
        self.update_results_btn.setEnabled(True)
        self.stop_backtest_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.artificial_progress = 0
    
        if results:
           # Store and display results
           self.last_results = results
           self.results_widget.update_results(results)
        
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


    def update_results_with_new_sizes(self):
        if not self.last_results:
           QMessageBox.information(self, "No Results", "Please run a backtest first")
           return
    
        # Get current trade sizes from strategy config
        strategy_config = self.strategy_config_widget.get_config()
        iron_size = strategy_config.iron_1_trade_size
        straddle_size = strategy_config.straddle_1_trade_size
    
        self.status_bar.showMessage("Updating results with new trade sizes...")
    
        # Create scaled copy of results
        scaled_results = self._scale_results(self.last_results, iron_size, straddle_size)
    
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
           f"(Iron: {iron_size}, Straddle: {straddle_size})", 
        10000
         )
    
        logger.info(f"Results updated with Iron size: {iron_size}, Straddle size: {straddle_size}")
    
    def _scale_results(self, original_results, iron_size, straddle_size):
        scaled_results = copy.deepcopy(original_results)
        total_scaled_pnl = 0.0
        scaled_daily_pnl = {}
        total_capital_used = 0.0
    
        for trade in scaled_results['trades']:
            if trade.trade_type == "Iron Condor 1":
               scale_factor = iron_size
            elif trade.trade_type == "Straddle 1":
               scale_factor = straddle_size
            else:
                scale_factor = 1  # Default fallback
        
            # Scale the trade P&L and size
            original_pnl = trade.pnl/trade.size  # Get per-contract P&L
            trade.pnl = original_pnl * scale_factor
            original_used_capital = trade.used_capital/trade.size  # Get per-contract capital used
            trade.used_capital = original_used_capital*scale_factor  # Scale capital used
            if(trade.trade_type == "Straddle 1"):
                trade.metadata['total_premium'] = (trade.metadata['total_premium']/trade.size) * scale_factor
            
            trade.size = scale_factor
            total_scaled_pnl += trade.pnl
    
    
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

    def _recalculate_statistics(self, trades, equity_curve, daily_pnl):
        if not trades:
           return {}
    
        total_trades = len(trades)
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]
    
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        total_pnl = sum(t.pnl for t in trades)
        avg_trade_pnl = total_pnl / total_trades if total_trades > 0 else 0
    
    # Profit factor
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
        initial_capital = equity_curve[0][1] if equity_curve else 100000
        final_capital = equity_curve[-1][1] if equity_curve else initial_capital
        return_pct = (final_capital - initial_capital) / initial_capital if initial_capital > 0 else 0
    
        # Max drawdown
        max_drawdown = 0
        peak = initial_capital
        for _, value in equity_curve:
            if value > peak:
               peak = value
            drawdown = (peak - value) / peak if peak > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)
    
    # Sharpe ratio (simplified)
        if daily_pnl:
           daily_returns = [pnl/initial_capital for pnl in daily_pnl.values()]
           avg_return = sum(daily_returns) / len(daily_returns)
           return_std = (sum((r - avg_return)**2 for r in daily_returns) / len(daily_returns))**0.5
           sharpe_ratio = (avg_return / return_std * (252**0.5)) if return_std > 0 else 0
        else:
           sharpe_ratio = 0
    
        return {
        'total_trades': total_trades,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_trade_pnl': avg_trade_pnl,
        'profit_factor': profit_factor,
        'return_pct': return_pct,
        'max_drawdown': max_drawdown,
        'sharpe_ratio': sharpe_ratio
    }
    
    
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
                'strategy': self.strategy_config_widget.get_config().to_dict(),
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
                
                # Load strategy config
                if 'strategy' in config:
                    sc = config['strategy']
                    self.strategy_config_widget.consecutive_candles.setValue(sc['consecutive_candles'])
                    self.strategy_config_widget.volume_threshold.setValue(sc['volume_threshold'])
                    self.strategy_config_widget.lookback_candles.setValue(sc['lookback_candles'])
                    self.strategy_config_widget.avg_range_candles.setValue(sc['avg_range_candles'])
                    self.strategy_config_widget.range_threshold.setValue(sc['range_threshold'])
                    self.strategy_config_widget.straddle_1_trade_size.setValue(sc['straddle_1_trade_size'])
                    self.strategy_config_widget.iron_1_trade_size.setValue(sc['iron_1_trade_size'])
                    self.strategy_config_widget.target_win_loss_ratio.setValue(sc['target_win_loss_ratio'])
                    
                    
                    # Load straddle parameters if they exist
                    if 'straddle_distance_multiplier' in sc:
                        self.strategy_config_widget.straddle_distance_multiplier.setValue(sc['straddle_distance_multiplier'])
                    if 'straddle_exit_percentage' in sc:
                        self.strategy_config_widget.straddle_exit_percentage.setValue(sc['straddle_exit_percentage'])
                    if 'straddle_exit_multiplier' in sc:
                        self.strategy_config_widget.straddle_exit_multiplier.setValue(sc['straddle_exit_multiplier'])
                
                self.status_bar.showMessage(f"Configuration loaded from {filename}", 5000)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load configuration: {e}")
    
    def export_results(self):
        """Export backtest results to JSON file"""
        if not self.last_results:
           QMessageBox.information(self, "No Results", "Please run a backtest first")
           return
    
        filename, _ = QFileDialog.getSaveFileName(
        self, "Export Results", f"backtest_results_{datetime.now().strftime('%Y%m%d_%H%M')}.json", 
        "JSON Files (*.json)"
    )
    
        if filename:
           try:
            
            # Helper function to make objects JSON serializable
              def make_serializable(obj):
                """Convert objects to JSON serializable format"""
                if hasattr(obj, 'isoformat'):  # datetime objects
                    return obj.isoformat()
                elif hasattr(obj, 'item'):  # numpy types
                    return obj.item()
                elif hasattr(obj, 'tolist'):  # numpy arrays
                    return obj.tolist()
                elif isinstance(obj, (int, float, str, bool, type(None))):
                    return obj
                elif isinstance(obj, dict):
                    return {k: make_serializable(v) for k, v in obj.items()}
                elif isinstance(obj, (list, tuple)):
                    return [make_serializable(item) for item in obj]
                else:
                    return str(obj)  # Convert everything else to string
            
            # Get actual unique trades (avoid duplicates)
              unique_trades = []
              seen_trades = set()
            
              for trade in self.last_results['trades']:
                # Create unique identifier for trade
                  trade_id = f"{trade.entry_time}_{trade.trade_type}_{trade.size}"
                  if trade_id not in seen_trades:
                     unique_trades.append(trade)
                     seen_trades.add(trade_id)
            
            # Create comprehensive export structure
              export_data = {
                "export_info": {
                    "timestamp": datetime.now().isoformat(),
                    "system_version": "2.0.0",
                    "total_trades": len(unique_trades),  # Use unique count
                    "export_format": "baytides_backtest_v1"
                },
                "configuration": {
                    "backtest_period": {
                        "start_date": self.backtest_config_widget.start_date.date().toString('yyyy-MM-dd'),
                        "end_date": self.backtest_config_widget.end_date.date().toString('yyyy-MM-dd')
                    },
                    "strategy_parameters": {
                        "iron_1_trade_size": self.strategy_config_widget.iron_1_trade_size.value(),
                        "straddle_1_trade_size": self.strategy_config_widget.straddle_1_trade_size.value(),
                        "target_win_loss_ratio": self.strategy_config_widget.target_win_loss_ratio.value(),
                        "consecutive_candles": self.strategy_config_widget.consecutive_candles.value(),
                        "volume_threshold": self.strategy_config_widget.volume_threshold.value(),
                        "range_threshold": self.strategy_config_widget.range_threshold.value()
                    },
                    "trading_parameters": {
                        "commission_per_contract": self.backtest_config_widget.commission.value(),
                        "data_provider": "mock" if self.use_mock_data.isChecked() else "polygon"
                    }
                },
                "performance_summary": make_serializable(self.last_results['statistics']),
                "daily_pnl": {},
                "equity_curve": [],
                "trades": []
            }
            
            # Process daily P&L safely
              for date, pnl in self.last_results['daily_pnl'].items():
                  if hasattr(date, 'strftime'):
                    date_str = date.strftime('%Y-%m-%d')
                  else:
                    date_str = str(date)
                  export_data["daily_pnl"][date_str] = round(float(pnl), 2)
            
            # Process equity curve safely
              for date, value in self.last_results['equity_curve']:
                  if hasattr(date, 'strftime'):
                    date_str = date.strftime('%Y-%m-%d')
                  else:
                    date_str = str(date)
                
                  export_data["equity_curve"].append({
                    "date": date_str,
                    "portfolio_value": round(float(value), 2)
                })
            
            # Add detailed trade information (using unique trades)
              for trade in unique_trades:
                   trade_data = {
                    "entry_time": trade.entry_time.isoformat() if hasattr(trade.entry_time, 'isoformat') else str(trade.entry_time),
                    "exit_time": trade.exit_time.isoformat() if trade.exit_time and hasattr(trade.exit_time, 'isoformat') else None,
                    "trade_type": str(trade.trade_type),
                    "size": int(trade.size),
                    "pnl": round(float(trade.pnl), 2),
                    "status": str(trade.status),
                    "metadata": make_serializable(trade.metadata) if trade.metadata else {},
                    "contracts": {}
                }
                
                # Add contract details with proper structure
                   for contract_symbol, details in trade.contracts.items():
                       trade_data["contracts"][str(contract_symbol)] = {
                        "leg_type": str(details.get('leg_type', '')),
                        "position": int(details.get('position', 0)),
                        "entry_price": round(float(details.get('entry_price', 0)), 4),
                        "exit_price": round(float(details.get('exit_price', 0)), 4),
                        "remaining_position": int(details.get('remaining_position', details.get('position', 0)))
                    }
                
                   export_data["trades"].append(trade_data)
            
            # Save JSON file with proper formatting
              with open(filename, 'w') as f:
                   json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
            
            # Show success message with correct count
              QMessageBox.information(
                self, 
                "Export Successful", 
                f"Results exported successfully to:\n{filename}\n\n"
                f"📊 {len(unique_trades)} trades exported\n"
                f"📈 Complete performance metrics included\n"
                f"⚙️ Configuration settings preserved"
            )
            
              self.status_bar.showMessage(f"Results exported to JSON: {filename}", 5000)
              logger.info(f"JSON export completed: {filename} with {len(unique_trades)} trades")
            
           except Exception as e:
            QMessageBox.warning(self, "Export Error", f"Failed to export results:\n{str(e)}")
            logger.error(f"JSON export error: {e}")  
    
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