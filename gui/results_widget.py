
from datetime import datetime
from typing import Dict, List, Tuple, Any
import logging
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from config.trade import Trade

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ResultsWidget(QWidget):
    """Widget for displaying backtest results"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Create tabs
        self.tabs = QTabWidget()
        
        # Statistics tab
        self.stats_widget = self._create_stats_widget()
        self.tabs.addTab(self.stats_widget, "Statistics")
        
        # Equity curve tab
        self.equity_widget = self._create_equity_widget()
        self.tabs.addTab(self.equity_widget, "Equity Curve")
        
        # Trades tab
        self.trades_widget = self._create_trades_widget()
        self.tabs.addTab(self.trades_widget, "Trades")
        
        # Daily P&L tab
        self.daily_pnl_widget = self._create_daily_pnl_widget()
        self.tabs.addTab(self.daily_pnl_widget, "Daily P&L")
        
        layout.addWidget(self.tabs)
        self.setLayout(layout)
    
    def _create_stats_widget(self):
        """Create statistics display widget"""
        widget = QWidget()
        layout = QGridLayout()
        
        # Statistics labels
        self.stats_labels = {}
        stats_names = [
            ('total_trades', 'Total Trades'),
            ('win_rate', 'Win Rate'),
            ('total_pnl', 'Total P&L'),
            ('avg_trade_pnl', 'Avg Trade P&L'),
            ('profit_factor', 'Profit Factor'),
            ('sharpe_ratio', 'Sharpe Ratio'),
            ('max_drawdown', 'Max Drawdown'),
            ('return_pct', 'Total Return %')
        ]
        
        row = 0
        for key, name in stats_names:
            label = QLabel(f"{name}:")
            label.setStyleSheet("font-weight: bold;")
            value_label = QLabel("--")
            self.stats_labels[key] = value_label
            
            layout.addWidget(label, row, 0)
            layout.addWidget(value_label, row, 1)
            row += 1
        
        widget.setLayout(layout)
        return widget
    
    def _create_equity_widget(self):
        """Create equity curve chart"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Create matplotlib figure
        self.equity_figure = Figure(figsize=(10, 6))
        self.equity_canvas = FigureCanvas(self.equity_figure)
        layout.addWidget(self.equity_canvas)
        
        widget.setLayout(layout)
        return widget
    
    def _create_trades_widget(self):
        """Create trades table"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Create table
        self.trades_table = QTableWidget()
        self.trades_table.setColumnCount(7)
        self.trades_table.setHorizontalHeaderLabels([
            "Entry Time", "Exit Time", "Type", "Size", 
            "Entry Signals", "P&L", "Status"
        ])
        
        # Set column widths
        header = self.trades_table.horizontalHeader()
        header.setStretchLastSection(True)
        
        layout.addWidget(self.trades_table)
        widget.setLayout(layout)
        return widget
    
    def _create_daily_pnl_widget(self):
        """Create daily P&L chart"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Create matplotlib figure
        self.pnl_figure = Figure(figsize=(10, 6))
        self.pnl_canvas = FigureCanvas(self.pnl_figure)
        layout.addWidget(self.pnl_canvas)
        
        widget.setLayout(layout)
        return widget
    
    def update_results(self, results: Dict[str, Any]):
        """Update all results displays"""
        # Update statistics
        stats = results['statistics']
        for key, label in self.stats_labels.items():
            if key in stats:
                value = stats[key]
                if key in ['total_pnl', 'avg_trade_pnl']:
                    label.setText(f"${value:,.2f}")
                elif key in ['win_rate', 'max_drawdown', 'return_pct']:
                    label.setText(f"{value:.2%}")
                elif key in ['profit_factor', 'sharpe_ratio']:
                    label.setText(f"{value:.2f}")
                else:
                    label.setText(str(value))
        
        # Update equity curve
        self._plot_equity_curve(results['equity_curve'])
        
        # Update trades table
        self._update_trades_table(results['trades'])
        
        # Update daily P&L
        self._plot_daily_pnl(results['daily_pnl'])
    
    def _plot_equity_curve(self, equity_curve: List[Tuple[datetime, float]]):
        """Plot equity curve"""
        self.equity_figure.clear()
        ax = self.equity_figure.add_subplot(111)
        
        dates = [eq[0] for eq in equity_curve]
        values = [eq[1] for eq in equity_curve]
        
        ax.plot(dates, values, 'b-', linewidth=2)
        ax.set_title('Equity Curve', fontsize=14, fontweight='bold')
        ax.set_xlabel('Date')
        ax.set_ylabel('Portfolio Value ($)')
        ax.grid(True, alpha=0.3)
        
        # Format y-axis
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        
        self.equity_figure.tight_layout()
        self.equity_canvas.draw()
    
    def _update_trades_table(self, trades: List[Trade]):
        """Update trades table"""
        self.trades_table.setRowCount(len(trades))
        
        for i, trade in enumerate(trades):
            # Entry time
            self.trades_table.setItem(i, 0, QTableWidgetItem(
                trade.entry_time.strftime('%Y-%m-%d %H:%M')
            ))
            
            # Exit time
            exit_time = trade.exit_time.strftime('%Y-%m-%d %H:%M') if trade.exit_time else "--"
            self.trades_table.setItem(i, 1, QTableWidgetItem(exit_time))
            
            # Type
            self.trades_table.setItem(i, 2, QTableWidgetItem(trade.trade_type))
            
            # Size
            self.trades_table.setItem(i, 3, QTableWidgetItem(str(trade.size)))
            
            # Entry signals
            signals = ", ".join([k for k, v in trade.entry_signals.items() if v and k.endswith('_condition')])
            self.trades_table.setItem(i, 4, QTableWidgetItem(signals))
            
            # P&L
            pnl_item = QTableWidgetItem(f"${trade.pnl:,.2f}")
            if trade.pnl >= 0:
                pnl_item.setForeground(QColor(0, 128, 0))
            else:
                pnl_item.setForeground(QColor(255, 0, 0))
            self.trades_table.setItem(i, 5, pnl_item)
            
            # Status
            self.trades_table.setItem(i, 6, QTableWidgetItem(trade.status))
    
    def _plot_daily_pnl(self, daily_pnl: Dict[datetime, float]):
        """Plot daily P&L"""
        self.pnl_figure.clear()
        ax = self.pnl_figure.add_subplot(111)
        
        dates = list(daily_pnl.keys())
        pnls = list(daily_pnl.values())
        
        # Create bar chart
        colors = ['g' if pnl >= 0 else 'r' for pnl in pnls]
        ax.bar(dates, pnls, color=colors, alpha=0.7)
        
        ax.set_title('Daily P&L', fontsize=14, fontweight='bold')
        ax.set_xlabel('Date')
        ax.set_ylabel('P&L ($)')
        ax.grid(True, alpha=0.3)
        
        # Format y-axis
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        
        # Add zero line
        ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        
        self.pnl_figure.tight_layout()
        self.pnl_canvas.draw()