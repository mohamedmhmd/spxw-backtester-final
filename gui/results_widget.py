from datetime import datetime
from typing import Dict, List, Tuple, Any
import logging
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from trades.trade import Trade
from collections import defaultdict
import mplcursors

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StatsCard(QFrame):
    """Individual statistics card with enhanced styling"""
    
    def __init__(self, title: str, value: str = "--", color: str = "#2196F3"):
        super().__init__()
        self.setFrameStyle(QFrame.Shape.Box)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                padding: 12px;
            }}
            QFrame:hover {{
                border-color: {color};
            }}
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(4)  # Reduced spacing
        layout.setContentsMargins(8, 8, 8, 8)  # Add explicit margins
        
        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 11px;
                font-weight: 500;
                margin: 0;
            }
        """)
        title_label.setWordWrap(True)  # Allow title to wrap if needed
        
        # Value
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 18px;
                font-weight: bold;
                margin: 0;
            }}
        """)
        self.value_label.setWordWrap(True)  # Allow wrapping for long numbers
        self.value_label.setMinimumHeight(25)  # Ensure minimum height for text
        
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        # Remove the stretch - it can cause text to be compressed
        # layout.addStretch()  # REMOVE THIS LINE
        
        self.setLayout(layout)
        self.setMinimumHeight(80)  # Reduced from 100
        self.setMinimumWidth(150)  # Add minimum width to prevent squashing
        
    def update_value(self, value: str, color: str = None):
        """Update the value and optionally the color"""
        self.value_label.setText(value)
        if color:
            self.value_label.setStyleSheet(f"""
                QLabel {{
                    color: {color};
                    font-size: 18px;
                    font-weight: bold;
                    margin: 0;
                }}
            """)
class EnhancedTableWidget(QTableWidget):
    """Enhanced table with better styling and functionality"""
    
    def __init__(self):
        super().__init__()
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        
        # Enhanced styling
        self.setStyleSheet("""
            QTableWidget {
                gridline-color: #E0E0E0;
                background-color: white;
                alternate-background-color: #F8F9FA;
                selection-background-color: #E3F2FD;
                border: 1px solid #E0E0E0;
                border-radius: 4px;
            }
            QTableWidget::item {
                padding: 8px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #E3F2FD;
                color: #1976D2;
            }
            QHeaderView::section {
                background-color: #F5F5F5;
                padding: 12px 8px;
                border: none;
                border-bottom: 2px solid #E0E0E0;
                font-weight: bold;
                color: #424242;
            }
        """)


class LegsDisplayWidget(QWidget):
    """Custom widget for displaying trade legs in a structured way"""
    
    def __init__(self, contracts: Dict):
        super().__init__()
        self.setMaximumHeight(120)
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)
        
        for leg_type, details in contracts.items():
            leg_frame = QFrame()
            leg_frame.setStyleSheet("""
                QFrame {
                    background-color: #F8F9FA;
                    border: 1px solid #E0E0E0;
                    border-radius: 4px;
                    padding: 4px;
                }
            """)
            
            leg_layout = QHBoxLayout()
            leg_layout.setContentsMargins(6, 3, 6, 3)
            
            # Leg type
            type_label = QLabel(leg_type)
            type_label.setStyleSheet("font-weight: bold; color: #1976D2; font-size: 11px;")
            
            # Details
            details_text = " | ".join([f"{k}: {v}" for k, v in details.items()])
            details_label = QLabel(details_text)
            details_label.setStyleSheet("color: #666; font-size: 11px;")
            details_label.setWordWrap(True)
            
            leg_layout.addWidget(type_label)
            leg_layout.addWidget(details_label, 1)
            leg_frame.setLayout(leg_layout)
            
            layout.addWidget(leg_frame)
        
        self.setLayout(layout)


class ResultsWidget(QWidget):
    """Enhanced widget for displaying backtest results"""
    
    def __init__(self, selected_strategy):
        super().__init__()
        self.selected_strategy = selected_strategy
        self.setStyleSheet("""
            QWidget {
                background-color: #FAFAFA;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #E0E0E0;
                background-color: white;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #F5F5F5;
                border: 1px solid #E0E0E0;
                padding: 12px 24px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: white;
                border-bottom-color: white;
                font-weight: bold;
                color: #1976D2;
            }
            QTabBar::tab:hover:!selected {
                background-color: #E3F2FD;
            }
        """)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        
        # Title
        title = QLabel("Backtest Results")
        title.setStyleSheet("""
            QLabel {
                font-size: 28px;
                font-weight: bold;
                color: #212121;
                margin-bottom: 8px;
            }
        """)
        layout.addWidget(title)
        
        # Create tabs
        self.tabs = QTabWidget()
        
        # Statistics tab
        self.stats_widget = self._create_stats_widget()
        self.tabs.addTab(self.stats_widget, "📊 Statistics")
        
        # Equity curve tab
        self.equity_widget = self._create_equity_widget()
        self.tabs.addTab(self.equity_widget, "📈 Equity Curve")
        
        # Trades tab
        self.trades_widget = self._create_trades_widget()
        self.tabs.addTab(self.trades_widget, "📋 Trades")
        
        
        # Daily P&L tab
        self.daily_pnl_widget = self._create_daily_pnl_widget()
        self.tabs.addTab(self.daily_pnl_widget, "📅 Daily P&L")
        
        layout.addWidget(self.tabs)
        self.setLayout(layout)
        
        # Weekly P&L tab
        self.weekly_pnl_widget = self._create_weekly_pnl_widget()
        self.tabs.addTab(self.weekly_pnl_widget, "📊 Weekly P&L")

        # Quarterly P&L tab
        self.quarterly_pnl_widget = self._create_quarterly_pnl_widget()
        self.tabs.addTab(self.quarterly_pnl_widget, "📈 Quarterly P&L")

        # Annual P&L tab
        self.annual_pnl_widget = self._create_annual_pnl_widget()
        self.tabs.addTab(self.annual_pnl_widget, "📅 Annual P&L")
    
    def _create_stats_widget(self):
        """Create statistics display widget with cards in a scrollable area"""
        # Create the main widget that will contain the scroll area
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
    
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
        QScrollArea {
            border: none;
            background-color: white;
        }
        QScrollBar:vertical {
            background: #f0f0f0;
            width: 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background: #c0c0c0;
            border-radius: 6px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background: #a0a0a0;
        }
    """)
    
        # Create the scrollable content widget
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: white;")
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(24, 24, 24, 24)
    
        # Performance Summary Header
        summary_label = QLabel("Performance Summary")
        summary_label.setStyleSheet("""
        QLabel {
            font-size: 20px;
            font-weight: bold;
            color: #212121;
            margin-bottom: 16px;
        }
    """)
        layout.addWidget(summary_label)
    
        # Create cards grid with better spacing
        cards_layout = QGridLayout()
        cards_layout.setSpacing(12)  # Reduced from 16 for more compact layout
        cards_layout.setContentsMargins(0, 0, 0, 0)
    
        # Initialize stat cards (now with 27 stats including capital used)
        self.stat_cards = {}
        if self.selected_strategy == "Trades 16":
           stats_config = [
        ('total_trades', 'Total Trades', '#2196F3'),
        ('trade_16_win_rate', 'Trades 16 Win Rate', '#4CAF50'),
        ('total_pnl', 'Total P&L', '#FF9800'),
        ('total_capital_used', 'Capital Used', '#9E9E9E'),
        ('avg_trade_pnl', 'Avg Trade P&L', '#9C27B0'),
        ('profit_factor', 'Profit Factor', '#00BCD4'),
        ('sharpe_ratio', 'Sharpe Ratio', '#795548'),
        ('max_drawdown', 'Max Drawdown', '#F44336'),
        ('return_pct', 'Return on Capital', '#607D8B'),
        ('iron_1_trades', 'Iron 1 Trades', '#3F51B5'),
        ('iron_1_pnl', 'Iron 1 P&L', '#E91E63'),
        ('iron_1_win_rate', 'Iron 1 Win Rate', '#8BC34A'),
        ('iron_2_trades', 'Iron 2 Trades', '#FF5722'),
        ('iron_2_pnl', 'Iron 2 P&L', '#009688'),
        ('iron_2_win_rate', 'Iron 2 Win Rate', '#CDDC39'),
        ('iron_3_trades', 'Iron 3 Trades', '#673AB7'),
        ('iron_3_pnl', 'Iron 3 P&L', '#FFC107'),
        ('iron_3_win_rate', 'Iron 3 Win Rate', '#03A9F4'),
        ('straddle_1_trades', 'Straddle 1 Trades', '#FF5722'),
        ('straddle_1_pnl', 'Straddle 1 P&L', '#009688'),
        ('straddle_1_win_rate', 'Straddle 1 Win Rate', '#CDDC39'),
        ('straddle_2_trades', 'Straddle 2 Trades', '#673AB7'),
        ('straddle_2_pnl', 'Straddle 2 P&L', '#FFC107'),
        ('straddle_2_win_rate', 'Straddle 2 Win Rate', '#03A9F4'),
        ('straddle_3_trades', 'Straddle 3 Trades', '#E91E63'),
        ('straddle_3_pnl', 'Straddle 3 P&L', '#8BC34A'),
        ('straddle_3_win_rate', 'Straddle 3 Win Rate', '#FF9800'),
    ]
        elif self.selected_strategy == "Trades 17":
             stats_config = [
        ('total_trades', 'Total Trades', '#2196F3'),
        ('trade_17_win_rate', 'Trades 17 Win Rate', '#4CAF50'),
        ('total_pnl', 'Total P&L', '#FF9800'),
        ('total_capital_used', 'Capital Used', '#9E9E9E'),
        ('avg_trade_pnl', 'Avg Trade P&L', '#9C27B0'),
        ('profit_factor', 'Profit Factor', '#00BCD4'),
        ('sharpe_ratio', 'Sharpe Ratio', '#795548'),
        ('max_drawdown', 'Max Drawdown', '#F44336'),
        ('return_pct', 'Return on Capital', '#607D8B'),
        ('cs_1a_trades', 'CS 1(a) Trades', '#3F51B5'),
        ('cs_1a_pnl', 'CS 1(a) P&L', '#E91E63'),
        ('cs_1a_win_rate', 'CS 1(a) Win Rate', '#8BC34A'),
        ('cs_1b_trades', 'CS 1(b) Trades', '#3F51B5'),
        ('cs_1b_pnl', 'CS 1(b) P&L', '#E91E63'),
        ('cs_1b_win_rate', 'CS 1(b) Win Rate', '#8BC34A'),
        ('uc_1a_trades', 'UC 1(a) Trades', '#FF5722'),
        ('uc_1a_pnl', 'UC 1(a) P&L', '#009688'),
        ('uc_1a_win_rate', 'UC 1(a) Win Rate', '#CDDC39'),
        ('uc_1b_trades', 'UC 1(b) Trades', '#FF5722'),
        ('uc_1b_pnl', 'UC 1(b) P&L', '#009688'),
        ('uc_1b_win_rate', 'UC 1(b) Win Rate', '#CDDC39'),
        ('lo_1a_trades', 'LO 1(a) Trades', '#673AB7'),
        ('lo_1a_pnl', 'LO 1(a) P&L', '#FFC107'),
        ('lo_1a_win_rate', 'LO 1(a) Win Rate', '#03A9F4'),
        ('lo_1b_trades', 'LO 1(b) Trades', '#673AB7'),
        ('lo_1b_pnl', 'LO 1(b) P&L', '#FFC107'),
        ('lo_1b_win_rate', 'LO 1(b) Win Rate', '#03A9F4'),
    ]   
             
        elif self.selected_strategy == "Trades 18":
             stats_config = [
        ('total_trades', 'Total Trades', '#2196F3'),
        ('trade_18_win_rate', 'Trades 18 Win Rate', '#4CAF50'),
        ('total_pnl', 'Total P&L', '#FF9800'),
        ('total_capital_used', 'Capital Used', '#9E9E9E'),
        ('avg_trade_pnl', 'Avg Trade P&L', '#9C27B0'),
        ('profit_factor', 'Profit Factor', '#00BCD4'),
        ('sharpe_ratio', 'Sharpe Ratio', '#795548'),
        ('max_drawdown', 'Max Drawdown', '#F44336'),
        ('return_pct', 'Return on Capital', '#607D8B'),
        ('ls_1a_trades', 'LS 1(a) Trades', '#3F51B5'),
        ('ls_1a_pnl', 'LS 1(a) P&L', '#E91E63'),
        ('ls_1a_win_rate', 'LS 1(a) Win Rate', '#8BC34A'),
        ('ls_1b_trades', 'LS 1(b) Trades', '#3F51B5'),
        ('ls_1b_pnl', 'LS 1(b) P&L', '#E91E63'),
        ('ls_1b_win_rate', 'LS 1(b) Win Rate', '#8BC34A'),
    ]
        # Arrange in 3 rows x 3 columns for better layout
        for i, (key, name, color) in enumerate(stats_config):
            card = StatsCard(name, "--", color)
            self.stat_cards[key] = card
            row = i // 3  # 3 cards per row
            col = i % 3
            cards_layout.addWidget(card, row, col)
    
        # Make columns stretch equally
        for i in range(3):
            cards_layout.setColumnStretch(i, 1)
    
        layout.addLayout(cards_layout)
    
        # Set the layout to the content widget
        content_widget.setLayout(layout)
    
        # Set the content widget as the scroll area's widget
        scroll_area.setWidget(content_widget)
    
        # Add scroll area to main layout
        main_layout.addWidget(scroll_area)
        main_widget.setLayout(main_layout)
    
        return main_widget
    
    def _create_equity_widget(self):
        """Create equity curve chart with enhanced styling"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Create matplotlib figure
        self.equity_figure = Figure(figsize=(12, 8), facecolor='white')
        self.equity_canvas = FigureCanvas(self.equity_figure)
        layout.addWidget(self.equity_canvas)
        
        widget.setLayout(layout)
        return widget
    
    def _create_trades_widget(self):
        """Create enhanced trades table"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        
        # Header
        header_label = QLabel("Trade History")
        header_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #212121;
            }
        """)
        layout.addWidget(header_label)
        
        # Create enhanced table
        self.trades_table = EnhancedTableWidget()
        if self.selected_strategy == "Trades 16":
           self.trades_table.setColumnCount(9)
           self.trades_table.setHorizontalHeaderLabels([
            "Entry Time", "Exit Time", "Type", "Entry SPX Price", "Exit SPX Price", "Strategy Details", 
             "Size", "Net Premium", "P&L"
        ])
        elif self.selected_strategy == "Trades 17":
            self.trades_table.setColumnCount(13)
            self.trades_table.setHorizontalHeaderLabels([
            "Entry Time", "Exit Time", "Type", "Market Direction", "Entry SPX Price", "Exit SPX Price", 
            "SPX/SPY Ratio", "High of the Day", "Low of the Day","Strategy Details", "Size", "Net Premium", "P&L"
        ])
        elif self.selected_strategy == "Trades 18":
            self.trades_table.setColumnCount(11)
            self.trades_table.setHorizontalHeaderLabels([
            "Entry Time", "Exit Time", "Type", "Entry SPX Price", "Exit SPX Price", 
            "High of the Day", "Low of the Day","Strategy Details", "Size", "Net Premium", "P&L"
        ])
        
        # Set column widths for optimal horizontal scrolling
        header = self.trades_table.horizontalHeader()
        if self.selected_strategy == "Trades 16":
           # Set specific widths that work well for scrolling
           self.trades_table.setColumnWidth(0, 120)  # Entry Time
           self.trades_table.setColumnWidth(1, 120)  # Exit Time  
           self.trades_table.setColumnWidth(2, 150)  # Type
           self.trades_table.setColumnWidth(3, 100)  # Entry SPX Price
           self.trades_table.setColumnWidth(4, 100)  # Exit SPX Price
           self.trades_table.setColumnWidth(5, 200)  # Strategy Details - Made much wider
           self.trades_table.setColumnWidth(6, 80)   # Size
           self.trades_table.setColumnWidth(7, 120)  # Net Premium
           self.trades_table.setColumnWidth(8, 100)  # P&L
           
        elif self.selected_strategy == "Trades 17":
            # Set specific widths that work well for scrolling
            self.trades_table.setColumnWidth(0, 120)  # Entry Time
            self.trades_table.setColumnWidth(1, 120)  # Exit Time  
            self.trades_table.setColumnWidth(2, 150)  # Type
            self.trades_table.setColumnWidth(3, 120)  # Market Direction
            self.trades_table.setColumnWidth(4, 120)  # Entry SPX Price
            self.trades_table.setColumnWidth(5, 100)  # Exit SPX Price
            self.trades_table.setColumnWidth(6, 120)   # SPX/SPY Ratio
            self.trades_table.setColumnWidth(7, 120)  # High of the Day
            self.trades_table.setColumnWidth(8, 120)  # Low of the Day
            self.trades_table.setColumnWidth(9, 200)  # Strategy Details - Made much wider
            self.trades_table.setColumnWidth(10, 80)   # Size
            self.trades_table.setColumnWidth(11, 120)  # Net Premium
            self.trades_table.setColumnWidth(12, 100)  # P&L
            
        elif self.selected_strategy == "Trades 18":
            # Set specific widths that work well for scrolling
            self.trades_table.setColumnWidth(0, 120)  # Entry Time
            self.trades_table.setColumnWidth(1, 120)  # Exit Time  
            self.trades_table.setColumnWidth(2, 150)  # Type
            self.trades_table.setColumnWidth(3, 120)  # Entry SPX Price
            self.trades_table.setColumnWidth(4, 100)  # Exit SPX Price
            self.trades_table.setColumnWidth(5, 120)  # High of the Day
            self.trades_table.setColumnWidth(6, 120)  # Low of the Day
            self.trades_table.setColumnWidth(7, 200)  # Strategy Details - Made much wider
            self.trades_table.setColumnWidth(8, 80)   # Size
            self.trades_table.setColumnWidth(9, 120)  # Net Premium
            self.trades_table.setColumnWidth(10, 100)  # P&L
        
        # Allow manual column resizing
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        
        # Enable horizontal scrolling when content exceeds widget width
        self.trades_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        layout.addWidget(self.trades_table)
        widget.setLayout(layout)
        return widget
    
    
    
    def _create_daily_pnl_widget(self):
        """Create daily P&L chart with enhanced styling"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Create matplotlib figure
        self.pnl_figure = Figure(figsize=(12, 8), facecolor='white')
        self.pnl_canvas = FigureCanvas(self.pnl_figure)
        layout.addWidget(self.pnl_canvas)
        
        widget.setLayout(layout)
        return widget
    
    
    def _create_weekly_pnl_widget(self):
        """Create weekly P&L chart widget"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
    
        # Create matplotlib figure
        self.weekly_pnl_figure = Figure(figsize=(12, 8), facecolor='white')
        self.weekly_pnl_canvas = FigureCanvas(self.weekly_pnl_figure)
        layout.addWidget(self.weekly_pnl_canvas)
    
        widget.setLayout(layout)
        return widget

    def _create_quarterly_pnl_widget(self):
        """Create quarterly P&L chart widget"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
    
        # Create matplotlib figure
        self.quarterly_pnl_figure = Figure(figsize=(12, 8), facecolor='white')
        self.quarterly_pnl_canvas = FigureCanvas(self.quarterly_pnl_figure)
        layout.addWidget(self.quarterly_pnl_canvas)
    
        widget.setLayout(layout)
        return widget

    def _create_annual_pnl_widget(self):
        """Create annual P&L chart widget"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
    
        # Create matplotlib figure
        self.annual_pnl_figure = Figure(figsize=(12, 8), facecolor='white')
        self.annual_pnl_canvas = FigureCanvas(self.annual_pnl_figure)
        layout.addWidget(self.annual_pnl_canvas)
    
        widget.setLayout(layout)
        return widget

    def _aggregate_pnl_by_period(self, daily_pnl: Dict[datetime, float], period: str) -> Dict:
        """Aggregate daily P&L by specified period"""
        if not daily_pnl:
           return {}
    
        aggregated = defaultdict(float)
    
        for date, pnl in daily_pnl.items():
            if period == 'weekly':
               # Get week number and year
               week_key = f"{date.year}-W{date.isocalendar()[1]:02d}"
               aggregated[week_key] += pnl
            elif period == 'quarterly':
               # Get quarter and year
               quarter = (date.month - 1) // 3 + 1
               quarter_key = f"{date.year}-Q{quarter}"
               aggregated[quarter_key] += pnl
            elif period == 'annual':
               # Get year
               aggregated[date.year] += pnl
    
        return dict(aggregated)

    def _plot_period_pnl(self, figure, period_pnl: Dict, title: str):
        """Plot P&L for a specific period"""
        figure.clear()
        ax = figure.add_subplot(111)
    
        if not period_pnl:
           ax.text(0.5, 0.5, f'No {title.lower()} data available', 
               transform=ax.transAxes, ha='center', va='center',
               fontsize=14, color='gray')
           figure.canvas.draw()
           return
    
        # Sort by period
        sorted_periods = sorted(period_pnl.items())
        periods = [p[0] for p in sorted_periods]
        pnls = [p[1] for p in sorted_periods]
    
        # Create bar chart
        colors = ['#4CAF50' if pnl >= 0 else '#F44336' for pnl in pnls]
        bars = ax.bar(range(len(periods)), pnls, color=colors, alpha=0.7, edgecolor='white', linewidth=0.5)
    
        # Add value labels on bars
        for i, (bar, pnl) in enumerate(zip(bars, pnls)):
            height = bar.get_height()
            if abs(height) > max(abs(min(pnls)), max(pnls)) * 0.05:  # Only label significant bars
               ax.text(bar.get_x() + bar.get_width()/2., height + (max(pnls)*0.02 if height >= 0 else min(pnls)*0.02),
                   f'${height:,.0f}', ha='center', va='bottom' if height >= 0 else 'top',
                   fontsize=9, fontweight='bold')
    
        # Set x-axis labels
        ax.set_xticks(range(len(periods)))
        ax.set_xticklabels(periods, rotation=45, ha='right')
    
        # Styling
        ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Period', fontsize=12)
        ax.set_ylabel('P&L ($)', fontsize=12)
        ax.grid(True, alpha=0.3, linestyle='--', axis='y')
        ax.set_facecolor('#FAFAFA')
    
        # Format y-axis
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        ax.tick_params(labelsize=10)
    
        # Add zero line
        ax.axhline(y=0, color='#424242', linestyle='-', alpha=0.6, linewidth=1)
    
        # Add summary statistics
        if pnls:
           total_pnl = sum(pnls)
           avg_pnl = total_pnl / len(pnls)
           positive_periods = sum(1 for pnl in pnls if pnl > 0)
           total_periods = len(pnls)
           win_rate = (positive_periods / total_periods) * 100 if total_periods > 0 else 0
        
           stats_text = (f'Total P&L: ${total_pnl:,.0f}\n'
                     f'Avg {title.split()[0]} P&L: ${avg_pnl:,.0f}\n'
                     f'Win Rate: {win_rate:.1f}% ({positive_periods}/{total_periods})')
        
           ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
               verticalalignment='top',
               bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='#E0E0E0'))
    
        figure.tight_layout()
        figure.canvas.draw()
    
    def update_results(self, results: Dict[str, Any]):
        """Update all results displays"""
        # Update statistics cards
        stats = results['statistics']
        for key, card in self.stat_cards.items():
            if key in stats:
               value = stats[key]
            if key in ['total_pnl', 'avg_trade_pnl', 'total_capital_used', 'iron_1_pnl', 'iron_2_pnl', 'iron_3_pnl',
                       'straddle_1_pnl', 'straddle_2_pnl', 'straddle_3_pnl', 'cs_1a_pnl', 'cs_1b_pnl', 'uc_1a_pnl',
                       'uc_1b_pnl', 'lo_1a_pnl', 'lo_1b_pnl', 'ls_1a_pnl', 'ls_1b_pnl']:
                # Use shorter format for large numbers
                if abs(value) >= 1000000:
                    formatted_value = f"${value/1000000:.2f}M"
                elif abs(value) >= 1000:
                    formatted_value = f"${value/1000:.1f}K"
                else:
                    formatted_value = f"${value:.2f}"
                
                if key == 'total_capital_used':
                    color = "#9E9E9E"
                else:
                    color = "#4CAF50" if value >= 0 else "#F44336"
            elif key in ['trade_16_win_rate', 'trade_17_win_rate', 'trade_18_win_rate', 'max_drawdown', 'return_pct', 'iron_1_win_rate', 'iron_2_win_rate', 'iron_3_win_rate',
                         'straddle_1_win_rate', 'straddle_2_win_rate', 'straddle_3_win_rate', 'cs_1a_win_rate', 'cs_1b_win_rate', 'uc_1a_win_rate',
                         'uc_1b_win_rate', 'lo_1a_win_rate', 'lo_1b_win_rate', 'ls_1a_win_rate', 'ls_1b_win_rate']:
                formatted_value = f"{value:.1%}"
                if key == 'max_drawdown':
                    color = "#F44336"
                elif key in ['trade_16_win_rate', 'trade_17_win_rate', 'trade_18_win_rate','iron_1_win_rate', 'iron_2_win_rate', 'iron_3_win_rate',
                             'straddle_1_win_rate', 'straddle_2_win_rate', 'straddle_3_win_rate', 'cs_1a_win_rate', 'cs_1b_win_rate', 'uc_1a_win_rate',
                             'uc_1b_win_rate', 'lo_1a_win_rate', 'lo_1b_win_rate', 'ls_1a_win_rate', 'ls_1b_win_rate']:
                    color = "#4CAF50" if value >= 0.5 else "#FF9800"
                else:
                    color = "#4CAF50" if value >= 0 else "#F44336"
            elif key in ['profit_factor', 'sharpe_ratio']:
                formatted_value = f"{value:.2f}"
                color = "#4CAF50" if value >= 1.0 else "#FF9800"
            else:
                formatted_value = str(value)
                color = "#2196F3"
            
            card.update_value(formatted_value, color)
        
        # Update charts and table
        self._plot_equity_curve(results['equity_curve'])
        self._update_trades_table(results['trades'])
        self._plot_daily_pnl(results['daily_pnl'])
        # Aggregate and plot period P&L
        weekly_pnl = self._aggregate_pnl_by_period(results['daily_pnl'], 'weekly')
        quarterly_pnl = self._aggregate_pnl_by_period(results['daily_pnl'], 'quarterly')
        annual_pnl = self._aggregate_pnl_by_period(results['daily_pnl'], 'annual')

        self._plot_period_pnl(self.weekly_pnl_figure, weekly_pnl, 'Weekly P&L')
        self._plot_period_pnl(self.quarterly_pnl_figure, quarterly_pnl, 'Quarterly P&L')
        self._plot_period_pnl(self.annual_pnl_figure, annual_pnl, 'Annual P&L')
    
    def _plot_equity_curve(self, equity_curve: List[Tuple[datetime, float]]):
        """Plot enhanced equity curve with proper cumulative P&L"""
        self.equity_figure.clear()
        ax = self.equity_figure.add_subplot(111)
        
        if not equity_curve:
            ax.text(0.5, 0.5, 'No equity data available', 
                   transform=ax.transAxes, ha='center', va='center',
                   fontsize=14, color='gray')
            self.equity_canvas.draw()
            return
        
        # Extract and validate data
        dates = [eq[0] for eq in equity_curve]
        values = [eq[1] for eq in equity_curve]
        
        # Debug: Check if all values are the same (flat line issue)
        if len(set(values)) == 1:
            # If all values are the same, this suggests the equity curve calculation is wrong
            # Let's add some debugging info
            print(f"WARNING: Equity curve appears flat. All values = {values[0]}")
            print(f"Equity curve data points: {len(values)}")
        
        # Plot with enhanced styling
        line = ax.plot(dates, values, color='#1976D2', linewidth=3, alpha=0.9, marker='o', markersize=3)[0]
        ax.fill_between(dates, values, alpha=0.1, color='#1976D2')
        
        # Styling
        ax.set_title('Portfolio Equity Curve', fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Date', fontsize=12)
        ax.set_ylabel('Portfolio Value ($)', fontsize=12)
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.set_facecolor('#FAFAFA')
        
        # Format axes with better scaling
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        ax.tick_params(labelsize=10)
        
        # Auto-scale Y axis to show variance better
        if len(values) > 1:
            y_range = max(values) - min(values)
            if y_range > 0:
                padding = y_range * 0.1  # 10% padding
                ax.set_ylim(min(values) - padding, max(values) + padding)
        
        # Rotate dates for better readability
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        # Add statistics box with more detailed info
        if values and len(values) > 1:
            total_return = ((values[-1] - values[0]) / values[0]) * 100 if values[0] != 0 else 0
            max_value = max(values)
            min_value = min(values)
            volatility = self._calculate_volatility(values)
            
            stats_text = (f'Total Return: {total_return:.1f}%\n'
                         f'Max Value: ${max_value:,.0f}\n'
                         f'Min Value: ${min_value:,.0f}\n'
                         f'Volatility: {volatility:.1f}%')
            
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
                   verticalalignment='top', 
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='#E0E0E0'))
        
        self.equity_figure.tight_layout()
        self.equity_canvas.draw()
    
    def _calculate_volatility(self, values: List[float]) -> float:
        """Calculate simple volatility of equity curve"""
        if len(values) < 2:
            return 0.0
        
        returns = []
        for i in range(1, len(values)):
            if values[i-1] != 0:
                daily_return = (values[i] - values[i-1]) / values[i-1]
                returns.append(daily_return)
        
        if not returns:
            return 0.0
        
        # Calculate standard deviation
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        volatility = (variance ** 0.5) * 100  # Convert to percentage
        
        return volatility
    
    
    def _update_trades_table(self, trades: List[Trade]):
        if self.selected_strategy == "Trades 16":
            self._update_trades_table_16(trades)
        elif self.selected_strategy == "Trades 17":
            self._update_trades_table_17(trades)
        elif self.selected_strategy == "Trades 18":
            self._update_trades_table_18(trades)
    
    def _update_trades_table_16(self, trades: List[Trade]):
        """Update trades table with enhanced formatting"""
        self.trades_table.setRowCount(len(trades))
        
        for i, trade in enumerate(trades):
            # Entry time
            entry_item = QTableWidgetItem(trade.entry_time.strftime('%Y-%m-%d\n%H:%M'))
            entry_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 0, entry_item)
            
            # Exit time
            if trade.exit_time:
                exit_text = trade.exit_time.strftime('%Y-%m-%d\n%H:%M')
            else:
                exit_text = "Open"
            exit_item = QTableWidgetItem(exit_text)
            exit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 1, exit_item)
            
            # Type with color coding
            type_item = QTableWidgetItem(f"{trade.trade_type} \n {trade.metadata.get('representation', '')}")
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setBackground(QColor("#E3F2FD"))
            self.trades_table.setItem(i, 2, type_item)
            
            # Entry SPX Price
            entry_spx_price = trade.metadata.get('entry_spx_price', 'N/A')
            spx_item = QTableWidgetItem(f"${entry_spx_price:,.2f}" if isinstance(entry_spx_price, (int, float)) else str(entry_spx_price))
            spx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 3, spx_item)
            
            # Exit SPX Price
            exit_spx_price = trade.metadata.get('exit_spx_price', 'N/A')
            spx_item = QTableWidgetItem(f"${exit_spx_price:,.2f}" if isinstance(exit_spx_price, (int, float)) else str(exit_spx_price))
            spx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 4, spx_item)
            
            # Legs details with elegant formatting
            legs_widget = QWidget()
            legs_layout = QVBoxLayout()
            legs_layout.setContentsMargins(6, 6, 6, 6)
            legs_layout.setSpacing(4)
            
            fields = ['position', 'entry_price', 'exit_price', 'strike', 'leg_type', 'remaining_position']
            for leg_name, details in trade.contracts.items():
                # Create a frame for each leg
                leg_frame = QFrame()
                leg_frame.setStyleSheet("""
                    QFrame {
                        background-color: #F8F9FA;
                        border: 1px solid #E0E0E0;
                        border-radius: 4px;
                        padding: 4px;
                        margin: 1px;
                    }
                """)
                
                leg_frame_layout = QVBoxLayout()
                leg_frame_layout.setContentsMargins(4, 3, 4, 3)
                leg_frame_layout.setSpacing(2)
                
                # Leg name header
                leg_header = QLabel(leg_name)
                leg_header.setStyleSheet("""
                    QLabel {
                        font-weight: bold; 
                        color: #1976D2; 
                        font-size: 10px;
                        margin-bottom: 2px;
                    }
                """)
                leg_frame_layout.addWidget(leg_header)
                
                # Leg details in organized rows
                details_text = []
                for key, value in details.items():
                    if not key in fields:
                            continue
                    if isinstance(value, float):
                        formatted_value = f"{value:.2f}"
                    else:
                        formatted_value = str(value)
                    details_text.append(f"{key}: {formatted_value}")
                
                # Split details into multiple lines for better readability
                if len(details_text) > 0:
                    # Group details for better layout
                    for detail in details_text:
                        detail_label = QLabel(f"• {detail}")
                        detail_label.setStyleSheet("""
                            QLabel {
                                color: #555; 
                                font-size: 9px;
                                margin: 0px;
                                padding: 1px 0px;
                            }
                        """)
                        detail_label.setWordWrap(True)
                        leg_frame_layout.addWidget(detail_label)
                
                leg_frame.setLayout(leg_frame_layout)
                legs_layout.addWidget(leg_frame)
            
            legs_widget.setLayout(legs_layout)
            self.trades_table.setCellWidget(i, 5, legs_widget)
            
            # Size
            size_item = QTableWidgetItem(str(trade.size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 6, size_item)
            
            # Net Premium
            sign = -1 if "Straddle" in trade.trade_type else 1
            net_premium = trade.metadata['net_premium']*sign if trade.size != 0 else 0
            
            premium_item = QTableWidgetItem(f"${net_premium:,.2f}")
            premium_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if net_premium >= 0:
                premium_item.setForeground(QColor("#4CAF50"))
            else:
                premium_item.setForeground(QColor("#F44336"))
            self.trades_table.setItem(i, 7, premium_item)
                
            
            # P&L with enhanced styling
            pnl_item = QTableWidgetItem(f"${trade.pnl:,.2f}")
            pnl_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            pnl_item.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            
            if trade.pnl >= 0:
                pnl_item.setForeground(QColor("#4CAF50"))
                pnl_item.setBackground(QColor("#E8F5E8"))
            else:
                pnl_item.setForeground(QColor("#F44336"))
                pnl_item.setBackground(QColor("#FFEBEE"))
            
            self.trades_table.setItem(i, 8, pnl_item)
            
        
        # Adjust row heights
        self.trades_table.resizeRowsToContents()
        
        
    def _update_trades_table_17(self, trades: List[Trade]):
        """Update trades table with enhanced formatting"""
        self.trades_table.setRowCount(len(trades))
        
        for i, trade in enumerate(trades):
            # Entry time
            entry_item = QTableWidgetItem(trade.entry_time.strftime('%Y-%m-%d\n%H:%M'))
            entry_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 0, entry_item)
            
            # Exit time
            if trade.exit_time:
                exit_text = trade.exit_time.strftime('%Y-%m-%d\n%H:%M')
            else:
                exit_text = "Open"
            exit_item = QTableWidgetItem(exit_text)
            exit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 1, exit_item)
            
            # Type with color coding
            type_item = QTableWidgetItem(f"{trade.trade_type} \n {trade.metadata.get('representation', '')}")
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setBackground(QColor("#E3F2FD"))
            self.trades_table.setItem(i, 2, type_item)
            
            #Market Direction
            direction_item = QTableWidgetItem(trade.metadata.get('market_direction', 'N/A'))
            direction_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 3, direction_item)
            
            # Entry SPX Price
            entry_spx_price = trade.metadata.get('entry_spx_price', 'N/A')
            spx_item = QTableWidgetItem(f"${entry_spx_price:,.2f}" if isinstance(entry_spx_price, (int, float)) else str(entry_spx_price))
            spx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 4, spx_item)
            
            # Exit SPX Price
            exit_spx_price = trade.metadata.get('exit_spx_price', 'N/A')
            spx_item = QTableWidgetItem(f"${exit_spx_price:,.2f}" if isinstance(exit_spx_price, (int, float)) else str(exit_spx_price))
            spx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 5, spx_item)
            
            #SPX/SPY Ratio
            spx_spy_ratio = trade.metadata.get('spx_spy_ratio', 'N/A')
            ratio_item = QTableWidgetItem(f"{spx_spy_ratio:.2f}" if isinstance(spx_spy_ratio, (int, float)) else str(spx_spy_ratio))
            ratio_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 6, ratio_item)
            
            #high of the day
            high_of_day = trade.metadata.get('high_of_day', 'N/A')
            high_item = QTableWidgetItem(f"${high_of_day:,.2f}" if isinstance(high_of_day, (int, float)) else str(high_of_day))
            high_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 7, high_item)
            
            #low of the day
            low_of_day = trade.metadata.get('low_of_day', 'N/A')
            low_item = QTableWidgetItem(f"${low_of_day:,.2f}" if isinstance(low_of_day, (int, float)) else str(low_of_day))
            low_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 8, low_item)
            
            # Legs details with elegant formatting
            legs_widget = QWidget()
            legs_layout = QVBoxLayout()
            legs_layout.setContentsMargins(6, 6, 6, 6)
            legs_layout.setSpacing(4)
            
            fields = ['position', 'entry_price', 'exit_price', 'strike', 'leg_type', 'remaining_position']
            for leg_name, details in trade.contracts.items():
                # Create a frame for each leg
                leg_frame = QFrame()
                leg_frame.setStyleSheet("""
                    QFrame {
                        background-color: #F8F9FA;
                        border: 1px solid #E0E0E0;
                        border-radius: 4px;
                        padding: 4px;
                        margin: 1px;
                    }
                """)
                
                leg_frame_layout = QVBoxLayout()
                leg_frame_layout.setContentsMargins(4, 3, 4, 3)
                leg_frame_layout.setSpacing(2)
                
                # Leg name header
                leg_header = QLabel(leg_name)
                leg_header.setStyleSheet("""
                    QLabel {
                        font-weight: bold; 
                        color: #1976D2; 
                        font-size: 10px;
                        margin-bottom: 2px;
                    }
                """)
                leg_frame_layout.addWidget(leg_header)
                
                # Leg details in organized rows
                details_text = []
                for key, value in details.items():
                    if not key in fields:
                            continue
                    if isinstance(value, float):
                        formatted_value = f"{value:.2f}"
                    else:
                        formatted_value = str(value)
                    details_text.append(f"{key}: {formatted_value}")
                
                # Split details into multiple lines for better readability
                if len(details_text) > 0:
                    # Group details for better layout
                    for detail in details_text:
                        detail_label = QLabel(f"• {detail}")
                        detail_label.setStyleSheet("""
                            QLabel {
                                color: #555; 
                                font-size: 9px;
                                margin: 0px;
                                padding: 1px 0px;
                            }
                        """)
                        detail_label.setWordWrap(True)
                        leg_frame_layout.addWidget(detail_label)
                
                leg_frame.setLayout(leg_frame_layout)
                legs_layout.addWidget(leg_frame)
            
            legs_widget.setLayout(legs_layout)
            self.trades_table.setCellWidget(i, 9, legs_widget)
            
            # Size
            size_item = QTableWidgetItem(str(trade.size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 10, size_item)
            
            # Net Premium
            net_premium = trade.metadata['net_premium'] if trade.size != 0 else 0
            
            premium_item = QTableWidgetItem(f"${net_premium:,.2f}")
            premium_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if net_premium >= 0:
                premium_item.setForeground(QColor("#4CAF50"))
            else:
                premium_item.setForeground(QColor("#F44336"))
            self.trades_table.setItem(i, 11, premium_item)
                
            
            # P&L with enhanced styling
            pnl_item = QTableWidgetItem(f"${trade.pnl:,.2f}")
            pnl_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            pnl_item.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            
            if trade.pnl >= 0:
                pnl_item.setForeground(QColor("#4CAF50"))
                pnl_item.setBackground(QColor("#E8F5E8"))
            else:
                pnl_item.setForeground(QColor("#F44336"))
                pnl_item.setBackground(QColor("#FFEBEE"))
            
            self.trades_table.setItem(i, 12, pnl_item)
            
        
        # Adjust row heights
        self.trades_table.resizeRowsToContents()
        
        
    def _update_trades_table_18(self, trades: List[Trade]):
        """Update trades table with enhanced formatting"""
        self.trades_table.setRowCount(len(trades))
        
        for i, trade in enumerate(trades):
            # Entry time
            entry_item = QTableWidgetItem(trade.entry_time.strftime('%Y-%m-%d\n%H:%M'))
            entry_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 0, entry_item)
            
            # Exit time
            if trade.exit_time:
                exit_text = trade.exit_time.strftime('%Y-%m-%d\n%H:%M')
            else:
                exit_text = "Open"
            exit_item = QTableWidgetItem(exit_text)
            exit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 1, exit_item)
            
            # Type with color coding
            type_item = QTableWidgetItem(f"{trade.trade_type} \n {trade.metadata.get('representation', '')}")
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setBackground(QColor("#E3F2FD"))
            self.trades_table.setItem(i, 2, type_item)
            
            
            # Entry SPX Price
            entry_spx_price = trade.metadata.get('entry_spx_price', 'N/A')
            spx_item = QTableWidgetItem(f"${entry_spx_price:,.2f}" if isinstance(entry_spx_price, (int, float)) else str(entry_spx_price))
            spx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 3, spx_item)
            
            # Exit SPX Price
            exit_spx_price = trade.metadata.get('exit_spx_price', 'N/A')
            spx_item = QTableWidgetItem(f"${exit_spx_price:,.2f}" if isinstance(exit_spx_price, (int, float)) else str(exit_spx_price))
            spx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 4, spx_item)
            
            
            
            #high of the day
            high_of_day = trade.metadata.get('high_of_day', 'N/A')
            high_item = QTableWidgetItem(f"${high_of_day:,.2f}" if isinstance(high_of_day, (int, float)) else str(high_of_day))
            high_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 5, high_item)
            
            #low of the day
            low_of_day = trade.metadata.get('low_of_day', 'N/A')
            low_item = QTableWidgetItem(f"${low_of_day:,.2f}" if isinstance(low_of_day, (int, float)) else str(low_of_day))
            low_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 6, low_item)
            
            # Legs details with elegant formatting
            legs_widget = QWidget()
            legs_layout = QVBoxLayout()
            legs_layout.setContentsMargins(6, 6, 6, 6)
            legs_layout.setSpacing(4)
            
            fields = ['position', 'entry_price', 'exit_price', 'strike', 'leg_type', 'remaining_position']
            for leg_name, details in trade.contracts.items():
                # Create a frame for each leg
                leg_frame = QFrame()
                leg_frame.setStyleSheet("""
                    QFrame {
                        background-color: #F8F9FA;
                        border: 1px solid #E0E0E0;
                        border-radius: 4px;
                        padding: 4px;
                        margin: 1px;
                    }
                """)
                
                leg_frame_layout = QVBoxLayout()
                leg_frame_layout.setContentsMargins(4, 3, 4, 3)
                leg_frame_layout.setSpacing(2)
                
                # Leg name header
                leg_header = QLabel(leg_name)
                leg_header.setStyleSheet("""
                    QLabel {
                        font-weight: bold; 
                        color: #1976D2; 
                        font-size: 10px;
                        margin-bottom: 2px;
                    }
                """)
                leg_frame_layout.addWidget(leg_header)
                
                # Leg details in organized rows
                details_text = []
                for key, value in details.items():
                    if not key in fields:
                            continue
                    if isinstance(value, float):
                        formatted_value = f"{value:.2f}"
                    else:
                        formatted_value = str(value)
                    details_text.append(f"{key}: {formatted_value}")
                
                # Split details into multiple lines for better readability
                if len(details_text) > 0:
                    # Group details for better layout
                    for detail in details_text:
                        detail_label = QLabel(f"• {detail}")
                        detail_label.setStyleSheet("""
                            QLabel {
                                color: #555; 
                                font-size: 9px;
                                margin: 0px;
                                padding: 1px 0px;
                            }
                        """)
                        detail_label.setWordWrap(True)
                        leg_frame_layout.addWidget(detail_label)
                
                leg_frame.setLayout(leg_frame_layout)
                legs_layout.addWidget(leg_frame)
            
            legs_widget.setLayout(legs_layout)
            self.trades_table.setCellWidget(i, 7, legs_widget)
            
            # Size
            size_item = QTableWidgetItem(str(trade.size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.trades_table.setItem(i, 8, size_item)
            
            # Net Premium
            net_premium = trade.metadata['net_premium'] if trade.size != 0 else 0
            
            premium_item = QTableWidgetItem(f"${net_premium:,.2f}")
            premium_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if net_premium >= 0:
                premium_item.setForeground(QColor("#4CAF50"))
            else:
                premium_item.setForeground(QColor("#F44336"))
            self.trades_table.setItem(i, 9, premium_item)
                
            
            # P&L with enhanced styling
            pnl_item = QTableWidgetItem(f"${trade.pnl:,.2f}")
            pnl_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            pnl_item.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            
            if trade.pnl >= 0:
                pnl_item.setForeground(QColor("#4CAF50"))
                pnl_item.setBackground(QColor("#E8F5E8"))
            else:
                pnl_item.setForeground(QColor("#F44336"))
                pnl_item.setBackground(QColor("#FFEBEE"))
            
            self.trades_table.setItem(i, 10, pnl_item)
            
        
        # Adjust row heights
        self.trades_table.resizeRowsToContents()
        
    
    def _plot_daily_pnl(self, daily_pnl: Dict[datetime, float]):
        """Plot enhanced daily P&L"""
        self.pnl_figure.clear()
        ax = self.pnl_figure.add_subplot(111)
        
        dates = list(daily_pnl.keys())
        pnls = list(daily_pnl.values())
        
        # Create enhanced bar chart
        colors = ['#4CAF50' if pnl >= 0 else '#F44336' for pnl in pnls]
        bars = ax.bar(dates, pnls, color=colors, alpha=0.7, edgecolor='white', linewidth=0.5)
        
        # Add hover functionality
        cursor = mplcursors.cursor(bars, hover=True)

        @cursor.connect("add")
        def on_hover(sel):
            index = sel.index  # safer than sel.target.index
            sel.annotation.set_text(
            f"Date: {dates[index].strftime('%Y-%m-%d')}\n"
            f"P&L: ${pnls[index]:,.2f}"
    )
            sel.annotation.get_bbox_patch().set(fc="white", alpha=0.9)
        
        # Add value labels on bars
        for bar, pnl in zip(bars, pnls):
            height = bar.get_height()
            if abs(height) > max(abs(min(pnls)), max(pnls)) * 0.1:  # Only label significant bars
                ax.text(bar.get_x() + bar.get_width()/2., height + (50 if height >= 0 else -50),
                       f'${height:,.0f}', ha='center', va='bottom' if height >= 0 else 'top',
                       fontsize=8, fontweight='bold')
        
        ax.set_title('Daily Profit & Loss', fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Date', fontsize=12)
        ax.set_ylabel('P&L ($)', fontsize=12)
        ax.grid(True, alpha=0.3, linestyle='--')
        
        # Format y-axis
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        ax.tick_params(labelsize=10)
        
        # Add zero line
        ax.axhline(y=0, color='#424242', linestyle='-', alpha=0.6, linewidth=1)
        
        # Add summary statistics
        if pnls:
            avg_daily = sum(pnls) / len(pnls)
            win_days = sum(1 for pnl in pnls if pnl > 0)
            total_days = len(pnls)
            win_rate_daily = (win_days / total_days) * 100
            
            stats_text = f'Avg Daily P&L: ${avg_daily:,.0f}\nWin Rate: {win_rate_daily:.1f}%\nWin Days: {win_days}/{total_days}'
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
                   verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
        
        self.pnl_figure.tight_layout()
        self.pnl_canvas.draw()