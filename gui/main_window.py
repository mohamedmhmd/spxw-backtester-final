import json
import pandas as pd
import logging
import asyncio
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from .back_test_worker import BacktestWorker
from .strategy_config_widget import StrategyConfigWidget
from data.mock_data_provider import MockDataProvider

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


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.data_provider = None
        self.backtest_worker = None
        self.last_results = None  # Initialize this to store results
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
    
    def test_api_connection(self):
        """Test API connection"""
        self.test_connection_btn.setEnabled(False)
        self.status_bar.showMessage("Testing connection...")
        
        # Run test in thread
        QTimer.singleShot(100, self._test_connection_async)
    
    def _test_connection_async(self):
        """Test connection asynchronously"""
        if self.use_mock_data.isChecked():
            # Mock data always succeeds
            QMessageBox.information(self, "Success", "Mock data provider ready!")
            self.status_bar.showMessage("Mock data provider ready", 5000)
            self.test_connection_btn.setEnabled(True)
            return
        
        api_key = self.api_key_input.text()
        
        async def test():
            async with PolygonDataProvider(api_key) as provider:
                return await provider.test_connection()
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(test())
            
            if success:
                QMessageBox.information(self, "Success", "API connection successful!")
                self.status_bar.showMessage("API connection successful", 5000)
            else:
                QMessageBox.warning(self, "Error", "API connection failed. Please check your API key.")
                self.status_bar.showMessage("API connection failed", 5000)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Connection test failed: {str(e)}")
            self.status_bar.showMessage("Connection test failed", 5000)
        
        self.test_connection_btn.setEnabled(True)
    
    def run_backtest(self):
        """Run backtest"""
        # Get configurations
        backtest_config = self.backtest_config_widget.get_config()
        strategy_config = self.strategy_config_widget.get_config()
        
        # Create data provider based on checkbox
        if self.use_mock_data.isChecked():
            self.data_provider = MockDataProvider()
            logger.info("Using mock data provider for backtest")
        else:
            api_key = self.api_key_input.text()
            if not api_key:
                QMessageBox.warning(self, "Error", "Please enter API key")
                return
            self.data_provider = PolygonDataProvider(api_key)
            logger.info("Using Polygon data provider for backtest")
        
        # Reset results
        self.last_results = None
        
        # Disable buttons
        self.run_backtest_btn.setEnabled(False)
        self.stop_backtest_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Create and start worker
        self.backtest_worker = BacktestWorker(
            self.data_provider, backtest_config, strategy_config
        )
        self.backtest_worker.progress.connect(self.update_progress)
        self.backtest_worker.status.connect(self.status_bar.showMessage)
        self.backtest_worker.finished.connect(self.on_backtest_finished)
        self.backtest_worker.error.connect(self.on_backtest_error)
        self.backtest_worker.start()
        
        self.status_bar.showMessage("Backtest started...")
    
    def update_progress(self, value):
        """Update progress bar"""
        self.progress_bar.setValue(value)
    
    def stop_backtest(self):
        """Stop running backtest"""
        if self.backtest_worker and self.backtest_worker.isRunning():
            self.backtest_worker.terminate()
            self.backtest_worker.wait()
            self.on_backtest_finished({})
    
    def on_backtest_finished(self, results):
        """Handle backtest completion"""
        self.run_backtest_btn.setEnabled(True)
        self.stop_backtest_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        
        if results:
            # Store results for export
            self.last_results = results
            
            # Update results widget
            self.results_widget.update_results(results)
            
            # Show summary in status bar
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
            self.status_bar.showMessage("Backtest stopped", 5000)
    
    def on_backtest_error(self, error_msg):
        """Handle backtest error"""
        self.run_backtest_btn.setEnabled(True)
        self.stop_backtest_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        
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
                    self.backtest_config_widget.initial_capital.setValue(bc['initial_capital'])
                    self.backtest_config_widget.commission.setValue(bc['commission_per_contract'])
                    self.backtest_config_widget.use_bid_ask.setChecked(bc['use_bid_ask'])
                    self.backtest_config_widget.granularity.setCurrentText(bc['data_granularity'])
                
                # Load strategy config
                if 'strategy' in config:
                    sc = config['strategy']
                    self.strategy_config_widget.consecutive_candles.setValue(sc['consecutive_candles'])
                    self.strategy_config_widget.volume_threshold.setValue(sc['volume_threshold'])
                    self.strategy_config_widget.lookback_candles.setValue(sc['lookback_candles'])
                    self.strategy_config_widget.avg_range_candles.setValue(sc['avg_range_candles'])
                    self.strategy_config_widget.range_threshold.setValue(sc['range_threshold'])
                    self.strategy_config_widget.trade_size.setValue(sc['trade_size'])
                    self.strategy_config_widget.win_loss_ratio.setValue(sc['target_win_loss_ratio'])
                    
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
        """Export backtest results"""
        if not self.last_results:
            QMessageBox.information(self, "No Results", "Please run a backtest first")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "", "CSV Files (*.csv);;Excel Files (*.xlsx)"
        )
        
        if filename:
            try:
                # Prepare trades data
                trades_data = []
                for trade in self.last_results['trades']:
                    trade_dict = {
                        'entry_time': trade.entry_time,
                        'exit_time': trade.exit_time,
                        'type': trade.trade_type,
                        'size': trade.size,
                        'pnl': trade.pnl,
                        'status': trade.status
                    }
                    
                    # Add strategy-specific details
                    if trade.trade_type == "Iron Condor":
                        trade_dict['net_credit'] = trade.metadata.get('net_credit', 0)
                    elif trade.trade_type == "Straddle":
                        trade_dict['straddle_strike'] = trade.metadata.get('straddle_strike', 0)
                        trade_dict['partial_pnl'] = trade.metadata.get('partial_pnl', 0)
                    
                    trades_data.append(trade_dict)
                
                # Create DataFrame
                df = pd.DataFrame(trades_data)
                
                # Export based on file type
                if filename.endswith('.xlsx'):
                    # Create Excel with multiple sheets
                    with pd.ExcelWriter(filename) as writer:
                        # Trades sheet
                        df.to_excel(writer, sheet_name='Trades', index=False)
                        
                        # Statistics sheet
                        stats_df = pd.DataFrame([self.last_results['statistics']])
                        stats_df.to_excel(writer, sheet_name='Statistics', index=False)
                        
                        # Daily P&L sheet
                        daily_pnl_df = pd.DataFrame(
                            list(self.last_results['daily_pnl'].items()),
                            columns=['Date', 'P&L']
                        )
                        daily_pnl_df.to_excel(writer, sheet_name='Daily P&L', index=False)
                else:
                    # Simple CSV export
                    df.to_csv(filename, index=False)
                
                self.status_bar.showMessage(f"Results exported to {filename}", 5000)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to export results: {e}")
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About SPX 0DTE Backtester",
            """<h2>SPX 0DTE Options Backtester</h2>
            <p>Professional backtesting platform for SPX 0DTE options strategies</p>
            <p><b>Version:</b> 2.0.0</p>
            <p><b>Features:</b></p>
            <ul>
                <li>Iron Condor with configurable win/loss ratios</li>
                <li>Straddle with partial exit capabilities</li>
                <li>Mock data provider for testing</li>
                <li>Real-time data from Polygon.io (Business plan required)</li>
                <li>Comprehensive performance analytics</li>
                <li>Professional GUI with real-time updates</li>
            </ul>
            <p><b>Strategies:</b></p>
            <ul>
                <li><b>Iron Condor (Iron 1):</b> ATM short strikes with target 1.5:1 win/loss ratio</li>
                <li><b>Straddle (Straddle 1):</b> Entered with Iron Condor, partial exits at 2x entry price</li>
            </ul>
            <p><b>Author:</b> Professional Trading Systems</p>"""
        )