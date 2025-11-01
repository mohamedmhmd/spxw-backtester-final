"""
Options Analysis Charts Widget
A PyQt6-based GUI for displaying the 5 chart types from options analysis.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
import mplcursors

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StatsCard(QFrame):
    """Individual statistics card for displaying analysis metrics"""
    
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
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }}
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)
        
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
        title_label.setWordWrap(True)
        
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
        self.value_label.setWordWrap(True)
        self.value_label.setMinimumHeight(25)
        
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        
        self.setLayout(layout)
        self.setMinimumHeight(80)
        self.setMinimumWidth(150)
        
    def update_value(self, value: str, color: Optional[str] = None):
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


class OptionsChartsWidget(QWidget):
    """Main widget for displaying options analysis charts in tabs"""
    
    def __init__(self, chart_data: Optional[Dict] = None, stats: Optional[Dict] = None):
        super().__init__()
        self.chart_data = chart_data
        self.stats = stats
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
                min-width: 120px;
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
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
        """)
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)
        
        # Header section
        header_layout = QVBoxLayout()
        
        # Title
        title = QLabel("Options Analysis: Implied vs Realized Movements")
        title.setStyleSheet("""
            QLabel {
                font-size: 28px;
                font-weight: bold;
                color: #212121;
                margin-bottom: 8px;
            }
        """)
        header_layout.addWidget(title)
        
        # Subtitle with configuration info
        if self.stats and 'config' in self.stats:
            config = self.stats['config']
            subtitle = QLabel(
                f"Analysis Period: {config.get('start_date', 'N/A')} to {config.get('end_date', 'N/A')} | "
                f"Interval: {config.get('bar_minutes', 5)} min | "
                f"DTE: {config.get('dte', 0)}"
            )
            subtitle.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    color: #666666;
                    margin-bottom: 16px;
                }
            """)
            header_layout.addWidget(subtitle)
        
        main_layout.addLayout(header_layout)
        
        # Statistics cards
        if self.stats:
            stats_layout = QHBoxLayout()
            stats_layout.setSpacing(12)
            
            # Create stat cards
            self.stat_cards = {
                'days': StatsCard("Trading Days", 
                                str(self.stats.get('trading_days_analyzed', '--')), 
                                "#2196F3"),
                'points': StatsCard("Data Points", 
                                  f"{self.stats.get('total_data_points', 0):,}", 
                                  "#4CAF50"),
                'implied': StatsCard("Avg Implied", 
                                   f"${self.stats.get('average_implied_move', 0):.2f}", 
                                   "#FF9800"),
                'realized': StatsCard("Avg Realized", 
                                    f"${self.stats.get('average_realized_move', 0):.2f}", 
                                    "#9C27B0"),
                'ratio': StatsCard("Impl/Real Ratio", 
                                 f"{self.stats.get('implied_over_realized_ratio', 0):.3f}", 
                                 "#F44336"),
                'correlation': StatsCard("Correlation", 
                                       f"{self.stats.get('correlation', 0):.3f}", 
                                       "#00BCD4")
            }
            
            for card in self.stat_cards.values():
                stats_layout.addWidget(card)
            
            stats_layout.addStretch()
            main_layout.addLayout(stats_layout)
        
        # Create tabs for charts
        self.tabs = QTabWidget()
        
        # Tab 1: Daily Decay Curves
        self.daily_decay_widget = self._create_daily_decay_widget()
        self.tabs.addTab(self.daily_decay_widget, "📊 Daily Decay Curves")
        
        # Tab 2: Average Decay Curve
        self.avg_decay_widget = self._create_avg_decay_widget()
        self.tabs.addTab(self.avg_decay_widget, "📈 Average Decay")
        
        # Tab 3: Scatter Plot
        self.scatter_widget = self._create_scatter_widget()
        self.tabs.addTab(self.scatter_widget, "🎯 Implied vs Realized")
        
        # Tab 4: Daily Averages
        self.daily_avg_widget = self._create_daily_avg_widget()
        self.tabs.addTab(self.daily_avg_widget, "📅 Daily Averages")
        
        # Tab 5: Time Intervals
        self.time_intervals_widget = self._create_time_intervals_widget()
        self.tabs.addTab(self.time_intervals_widget, "⏰ Time Intervals")
        
        main_layout.addWidget(self.tabs)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.refresh_button = QPushButton("🔄 Refresh Charts")
        self.refresh_button.clicked.connect(self.refresh_charts)
        button_layout.addWidget(self.refresh_button)
        
        self.export_button = QPushButton("💾 Export Charts")
        self.export_button.clicked.connect(self.export_charts)
        button_layout.addWidget(self.export_button)
        
        button_layout.addStretch()
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
        
        # Plot initial data if available
        if self.chart_data:
            self.update_charts(self.chart_data, self.stats)
    
    def _create_daily_decay_widget(self) -> QWidget:
        """Create widget for Chart 1: Daily Decay Curves"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Description
        desc = QLabel(
            "Individual decay curves for each trading day showing how implied "
            "and realized moves change throughout the day."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("QLabel { color: #666666; margin: 10px; }")
        layout.addWidget(desc)
        
        # Create matplotlib figure with scroll area for multiple charts
        scroll_area = QScrollArea()
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout()
        
        self.daily_decay_figure = Figure(figsize=(16, 40))  # Tall figure for scrolling
        self.daily_decay_canvas = FigureCanvas(self.daily_decay_figure)
        
        scroll_layout.addWidget(self.daily_decay_canvas)
        scroll_content.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)
        
        layout.addWidget(scroll_area)
        widget.setLayout(layout)
        
        return widget
    
    def _create_avg_decay_widget(self) -> QWidget:
        """Create widget for Chart 2: Average Decay Curve"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Description
        desc = QLabel(
            "Average pattern of implied vs realized movement throughout the trading day, "
            "calculated across all analyzed days."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("QLabel { color: #666666; margin: 10px; }")
        layout.addWidget(desc)
        
        # Create matplotlib figure
        self.avg_decay_figure = Figure(figsize=(12, 6))
        self.avg_decay_canvas = FigureCanvas(self.avg_decay_figure)
        
        # Add toolbar
        toolbar = NavigationToolbar(self.avg_decay_canvas, widget)
        layout.addWidget(toolbar)
        layout.addWidget(self.avg_decay_canvas)
        
        # Add control panel
        control_panel = QHBoxLayout()
        
        self.show_trend_check = QCheckBox("Show Trend Lines")
        self.show_trend_check.setChecked(True)
        self.show_trend_check.stateChanged.connect(self._update_avg_decay_plot)
        control_panel.addWidget(self.show_trend_check)
        
        self.show_fill_check = QCheckBox("Show Fill Between Lines")
        self.show_fill_check.setChecked(True)
        self.show_fill_check.stateChanged.connect(self._update_avg_decay_plot)
        control_panel.addWidget(self.show_fill_check)
        
        control_panel.addStretch()
        layout.addLayout(control_panel)
        
        widget.setLayout(layout)
        return widget
    
    def _create_scatter_widget(self) -> QWidget:
        """Create widget for Chart 3: Scatter Plot"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Description
        desc = QLabel(
            "Scatter plot showing the relationship between average implied and realized "
            "moves for each time interval. Points above the equilibrium line indicate "
            "implied > realized."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("QLabel { color: #666666; margin: 10px; }")
        layout.addWidget(desc)
        
        # Create matplotlib figure
        self.scatter_figure = Figure(figsize=(10, 10))
        self.scatter_canvas = FigureCanvas(self.scatter_figure)
        
        # Add toolbar
        toolbar = NavigationToolbar(self.scatter_canvas, widget)
        layout.addWidget(toolbar)
        layout.addWidget(self.scatter_canvas)
        
        # Add statistics panel
        stats_panel = QHBoxLayout()
        
        self.distance_label = QLabel("Average Distance from Equilibrium: --")
        self.distance_label.setStyleSheet("QLabel { font-weight: bold; color: #1976D2; }")
        stats_panel.addWidget(self.distance_label)
        
        stats_panel.addStretch()
        
        self.show_labels_check = QCheckBox("Show Time Labels")
        self.show_labels_check.setChecked(False)
        self.show_labels_check.stateChanged.connect(self._update_scatter_plot)
        stats_panel.addWidget(self.show_labels_check)
        
        layout.addLayout(stats_panel)
        
        widget.setLayout(layout)
        return widget
    
    def _create_daily_avg_widget(self) -> QWidget:
        """Create widget for Chart 4: Daily Averages Timeline"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Description
        desc = QLabel(
            "Timeline showing the trend of average daily implied and realized moves "
            "over the analysis period."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("QLabel { color: #666666; margin: 10px; }")
        layout.addWidget(desc)
        
        # Create matplotlib figure
        self.daily_avg_figure = Figure(figsize=(14, 6))
        self.daily_avg_canvas = FigureCanvas(self.daily_avg_figure)
        
        # Add toolbar
        toolbar = NavigationToolbar(self.daily_avg_canvas, widget)
        layout.addWidget(toolbar)
        layout.addWidget(self.daily_avg_canvas)
        
        # Control panel
        control_panel = QHBoxLayout()
        
        self.ma_spinner = QSpinBox()
        self.ma_spinner.setMinimum(1)
        self.ma_spinner.setMaximum(20)
        self.ma_spinner.setValue(5)
        self.ma_spinner.setSuffix(" days")
        self.ma_spinner.valueChanged.connect(self._update_daily_avg_plot)
        
        control_panel.addWidget(QLabel("Moving Average:"))
        control_panel.addWidget(self.ma_spinner)
        
        self.show_ma_check = QCheckBox("Show Moving Average")
        self.show_ma_check.setChecked(True)
        self.show_ma_check.stateChanged.connect(self._update_daily_avg_plot)
        control_panel.addWidget(self.show_ma_check)
        
        control_panel.addStretch()
        layout.addLayout(control_panel)
        
        widget.setLayout(layout)
        return widget
    
    def _create_time_intervals_widget(self) -> QWidget:
        """Create widget for Chart 5: Time Intervals Analysis"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Description
        desc = QLabel(
            "Separate charts for each time interval showing implied and realized "
            "moves across all trading days."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("QLabel { color: #666666; margin: 10px; }")
        layout.addWidget(desc)
        
        # Time interval selector
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("Select Time Interval:"))
        
        self.time_interval_combo = QComboBox()
        self.time_interval_combo.currentTextChanged.connect(self._update_time_interval_plot)
        selector_layout.addWidget(self.time_interval_combo)
        
        selector_layout.addStretch()
        layout.addLayout(selector_layout)
        
        # Create matplotlib figure
        self.time_intervals_figure = Figure(figsize=(16, 24))  # Large for grid
        self.time_intervals_canvas = FigureCanvas(self.time_intervals_figure)
        
        # Scroll area for multiple charts
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.time_intervals_canvas)
        scroll_area.setWidgetResizable(True)
        
        layout.addWidget(scroll_area)
        
        widget.setLayout(layout)
        return widget
    
    def update_charts(self, chart_data: Dict):
        """Update all charts with new data"""
        self.chart_data = chart_data
        
        
        # Update statistics cards
        stats = chart_data.get('statistics', {})
        self.stats = stats
        if stats and hasattr(self, 'stat_cards'):
            self.stat_cards['days'].update_value(str(stats.get('trading_days_analyzed', '--')))
            self.stat_cards['points'].update_value(f"{stats.get('total_data_points', 0):,}")
            self.stat_cards['implied'].update_value(f"${stats.get('average_implied_move', 0):.2f}")
            self.stat_cards['realized'].update_value(f"${stats.get('average_realized_move', 0):.2f}")
            self.stat_cards['ratio'].update_value(f"{stats.get('implied_over_realized_ratio', 0):.3f}")
            self.stat_cards['correlation'].update_value(f"{stats.get('correlation', 0):.3f}")
        
        # Update each chart
        if 'chart1' in chart_data:
            self._plot_daily_decay_curves(chart_data['chart1'])
        
        if 'chart2' in chart_data:
            self._plot_avg_decay_curve(chart_data['chart2'])
        
        if 'chart3' in chart_data:
            self._plot_scatter(chart_data['chart3'])
        
        if 'chart4' in chart_data:
            self._plot_daily_averages(chart_data['chart4'])
        
        if 'chart5' in chart_data:
            self._plot_time_intervals(chart_data['chart5'])
    
    def _plot_daily_decay_curves(self, data: Dict):
        """Plot Chart 1: Daily Decay Curves"""
        self.daily_decay_figure.clear()
        
        num_days = len(data)
        cols = 4  # 4 columns for better visibility
        rows = (num_days + cols - 1) // cols
        
        # Create grid spec for better layout control
        gs = GridSpec(rows, cols, figure=self.daily_decay_figure, 
                     hspace=0.4, wspace=0.3)
        
        self.daily_decay_figure.suptitle(
            'Daily Option Decay Curves - Implied vs Realized Movement',
            fontsize=16, fontweight='bold', y=0.99
        )
        
        # Plot each day
        for idx, (date_str, day_data) in enumerate(data.items()):
            row = idx // cols
            col = idx % cols
            ax = self.daily_decay_figure.add_subplot(gs[row, col])
            
            time_remaining = day_data['time_remaining']
            implied = day_data['implied']
            realized = day_data['realized']
            
            # Plot lines with markers
            ax.plot(time_remaining, implied, 'b-', label='Implied', 
                   linewidth=1.5, marker='o', markersize=2, alpha=0.8)
            ax.plot(time_remaining, realized, 'r-', label='Realized', 
                   linewidth=1.5, marker='s', markersize=2, alpha=0.8)
            
            # Styling
            ax.set_title(date_str, fontsize=10, fontweight='bold')
            ax.set_xlabel('Min to Close', fontsize=8)
            ax.set_ylabel('Move ($)', fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(True, alpha=0.3, linestyle='--')
            ax.invert_xaxis()
            
            # Add legend only to first subplot
            if idx == 0:
                ax.legend(fontsize=8, loc='upper right', framealpha=0.9)
            
            # Add shaded area between curves
            ax.fill_between(time_remaining, implied, realized, 
                          where=(np.array(implied) >= np.array(realized)),
                          alpha=0.1, color='blue')
            ax.fill_between(time_remaining, implied, realized,
                          where=(np.array(implied) < np.array(realized)),
                          alpha=0.1, color='red')
        
        # Hide unused subplots
        for idx in range(num_days, rows * cols):
            row = idx // cols
            col = idx % cols
            ax = self.daily_decay_figure.add_subplot(gs[row, col])
            ax.axis('off')
        
        self.daily_decay_canvas.draw()
    
    def _plot_avg_decay_curve(self, data: Dict):
        """Plot Chart 2: Average Decay Curve"""
        self._avg_decay_data = data  # Store for updates
        self._update_avg_decay_plot()
    
    def _update_avg_decay_plot(self):
        """Update the average decay curve plot based on current settings"""
        if not hasattr(self, '_avg_decay_data'):
            return
        
        data = self._avg_decay_data
        self.avg_decay_figure.clear()
        ax = self.avg_decay_figure.add_subplot(111)
        
        time_remaining = data['time_remaining']
        avg_implied = data['avg_implied']
        avg_realized = data['avg_realized']
        
        # Main lines with enhanced styling
        line1 = ax.plot(time_remaining, avg_implied, 'b-', label='Average Implied',
                       linewidth=2.5, marker='o', markersize=4, alpha=0.9)
        line2 = ax.plot(time_remaining, avg_realized, 'r-', label='Average Realized',
                       linewidth=2.5, marker='s', markersize=4, alpha=0.9)
        
        # Add trend lines if checked
        if self.show_trend_check.isChecked():
            z_implied = np.polyfit(time_remaining, avg_implied, 2)
            p_implied = np.poly1d(z_implied)
            z_realized = np.polyfit(time_remaining, avg_realized, 2)
            p_realized = np.poly1d(z_realized)
            
            x_smooth = np.linspace(min(time_remaining), max(time_remaining), 100)
            ax.plot(x_smooth, p_implied(x_smooth), 'b--', alpha=0.5,
                   label='Implied Trend', linewidth=1.5)
            ax.plot(x_smooth, p_realized(x_smooth), 'r--', alpha=0.5,
                   label='Realized Trend', linewidth=1.5)
        
        # Add fill between curves if checked
        if self.show_fill_check.isChecked():
            ax.fill_between(time_remaining, avg_implied, avg_realized,
                          where=(np.array(avg_implied) >= np.array(avg_realized)),
                          alpha=0.2, color='blue', label='Implied > Realized')
            ax.fill_between(time_remaining, avg_implied, avg_realized,
                          where=(np.array(avg_implied) < np.array(avg_realized)),
                          alpha=0.2, color='red', label='Realized > Implied')
        
        # Add interactive hover
        cursor = mplcursors.cursor([line1[0], line2[0]], hover=True)
        
        @cursor.connect("add")
        def on_hover(sel):
            idx = sel.index
            if sel.artist == line1[0]:
                label = "Implied"
                value = avg_implied[idx]
            else:
                label = "Realized"
                value = avg_realized[idx]
            
            sel.annotation.set_text(
                f"{label}\n"
                f"Time to Close: {time_remaining[idx]:.0f} min\n"
                f"Move: ${value:.2f}"
            )
            sel.annotation.get_bbox_patch().set(fc="white", alpha=0.95)
        
        # Styling
        ax.set_title('Average Option Decay Curve Throughout Trading Day',
                    fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('Minutes Remaining Until Close', fontsize=12)
        ax.set_ylabel('Average Move ($)', fontsize=12)
        ax.legend(loc='upper right', fontsize=10, framealpha=0.9)
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.invert_xaxis()
        
        # Add statistics annotation
        if len(avg_implied) > 0:
            avg_diff = np.mean(np.array(avg_implied) - np.array(avg_realized))
            max_diff = np.max(np.abs(np.array(avg_implied) - np.array(avg_realized)))
            
            stats_text = (f'Avg Difference: ${avg_diff:.2f}\n'
                         f'Max Difference: ${max_diff:.2f}')
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
                   verticalalignment='top',
                   bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.8))
        
        self.avg_decay_figure.tight_layout()
        self.avg_decay_canvas.draw()
    
    def _plot_scatter(self, data: Dict):
        """Plot Chart 3: Scatter Plot"""
        self._scatter_data = data  # Store for updates
        self._update_scatter_plot()
    
    def _update_scatter_plot(self):
        """Update the scatter plot based on current settings"""
        if not hasattr(self, '_scatter_data'):
            return
        
        data = self._scatter_data
        self.scatter_figure.clear()
        ax = self.scatter_figure.add_subplot(111)
        
        realized = data['realized']
        implied = data['implied']
        time_labels = data['time_of_day']
        distances = data['distance_from_equilibrium']
        
        # Create scatter with color gradient
        colors = range(len(realized))
        scatter = ax.scatter(realized, implied, c=colors, cmap='viridis',
                           s=80, alpha=0.7, edgecolors='black', linewidth=0.5)
        
        # Add equilibrium line
        min_val = min(min(realized), min(implied)) * 0.9
        max_val = max(max(realized), max(implied)) * 1.1
        ax.plot([min_val, max_val], [min_val, max_val], 'k--', alpha=0.5,
               label='Equilibrium Line (Implied = Realized)', linewidth=2)
        
        # Add labels if checked
        if self.show_labels_check.isChecked():
            for i, txt in enumerate(time_labels):
                ax.annotate(txt, (realized[i], implied[i]),
                          xytext=(3, 3), textcoords='offset points',
                          fontsize=7, alpha=0.7)
        else:
            # Only label outliers
            sorted_indices = np.argsort(np.abs(distances))[-5:]
            for idx in sorted_indices:
                ax.annotate(time_labels[idx],
                          xy=(realized[idx], implied[idx]),
                          xytext=(5, 5), textcoords='offset points',
                          fontsize=8, alpha=0.8, fontweight='bold')
        
        # Interactive hover
        cursor = mplcursors.cursor(scatter, hover=True)
        
        @cursor.connect("add")
        def on_hover(sel):
            idx = sel.index
            sel.annotation.set_text(
                f"Time: {time_labels[idx]}\n"
                f"Realized: ${realized[idx]:.2f}\n"
                f"Implied: ${implied[idx]:.2f}\n"
                f"Distance: ${distances[idx]:.2f}"
            )
            sel.annotation.get_bbox_patch().set(fc="yellow", alpha=0.95)
        
        # Styling
        ax.set_title('Implied vs Realized Movement by Time of Day',
                    fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('Average Realized Move ($)', fontsize=12)
        ax.set_ylabel('Average Implied Move ($)', fontsize=12)
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.legend(loc='upper left', fontsize=10)
        
        # Add colorbar
        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label('Time of Day (Earlier → Later)', fontsize=10)
        
        # Update distance label
        avg_distance = np.mean(np.abs(distances))
        self.distance_label.setText(f"Average Distance from Equilibrium: ${avg_distance:.2f}")
        
        # Add zones
        ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3, linewidth=0.5)
        ax.axvline(x=0, color='gray', linestyle='-', alpha=0.3, linewidth=0.5)
        
        self.scatter_figure.tight_layout()
        self.scatter_canvas.draw()
    
    def _plot_daily_averages(self, data: Dict):
        """Plot Chart 4: Daily Averages Timeline"""
        self._daily_avg_data = data  # Store for updates
        self._update_daily_avg_plot()
    
    def _update_daily_avg_plot(self):
        """Update the daily averages plot based on current settings"""
        if not hasattr(self, '_daily_avg_data'):
            return
        
        data = self._daily_avg_data
        self.daily_avg_figure.clear()
        ax = self.daily_avg_figure.add_subplot(111)
        
        # Convert dates to datetime
        dates = pd.to_datetime(data['dates'])
        avg_implied = data['avg_implied']
        avg_realized = data['avg_realized']
        
        # Main lines
        line1 = ax.plot(dates, avg_implied, 'b-', label='Average Implied',
                       linewidth=2, marker='o', markersize=5, alpha=0.9)
        line2 = ax.plot(dates, avg_realized, 'r-', label='Average Realized',
                       linewidth=2, marker='s', markersize=5, alpha=0.9)
        
        # Add trend lines
        x_numeric = np.arange(len(dates))
        z_implied = np.polyfit(x_numeric, avg_implied, 1)
        z_realized = np.polyfit(x_numeric, avg_realized, 1)
        p_implied = np.poly1d(z_implied)
        p_realized = np.poly1d(z_realized)
        
        ax.plot(dates, p_implied(x_numeric), 'b--', alpha=0.5,
               label=f'Implied Trend (slope: {z_implied[0]:.3f})', linewidth=1)
        ax.plot(dates, p_realized(x_numeric), 'r--', alpha=0.5,
               label=f'Realized Trend (slope: {z_realized[0]:.3f})', linewidth=1)
        
        # Add moving averages if checked
        if self.show_ma_check.isChecked():
            window = self.ma_spinner.value()
            if window > 1 and len(dates) > window:
                ma_implied = pd.Series(avg_implied).rolling(window=window, min_periods=1).mean()
                ma_realized = pd.Series(avg_realized).rolling(window=window, min_periods=1).mean()
                ax.plot(dates, ma_implied, 'c-', alpha=0.6,
                       label=f'{window}-Day MA (Implied)', linewidth=1.5)
                ax.plot(dates, ma_realized, 'm-', alpha=0.6,
                       label=f'{window}-Day MA (Realized)', linewidth=1.5)
        
        # Interactive hover
        cursor = mplcursors.cursor([line1[0], line2[0]], hover=True)
        
        @cursor.connect("add")
        def on_hover(sel):
            idx = sel.index
            date_str = dates[idx].strftime('%Y-%m-%d')
            if sel.artist == line1[0]:
                label = "Implied"
                value = avg_implied[idx]
            else:
                label = "Realized"
                value = avg_realized[idx]
            
            sel.annotation.set_text(
                f"{label}\n"
                f"Date: {date_str}\n"
                f"Avg Move: ${value:.2f}"
            )
            sel.annotation.get_bbox_patch().set(fc="white", alpha=0.95)
        
        # Styling
        ax.set_title('Daily Average Implied vs Realized Movement Over Time',
                    fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('Trading Date', fontsize=12)
        ax.set_ylabel('Average Daily Move ($)', fontsize=12)
        ax.legend(loc='upper left', fontsize=9, ncol=2)
        ax.grid(True, alpha=0.3, linestyle='--')
        
        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=max(1, len(dates)//10)))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        # Add statistics box
        if len(avg_implied) > 0:
            total_impl = sum(avg_implied)
            total_real = sum(avg_realized)
            ratio = total_impl / total_real if total_real != 0 else 0
            
            stats_text = (f'Total Implied: ${total_impl:.0f}\n'
                         f'Total Realized: ${total_real:.0f}\n'
                         f'Overall Ratio: {ratio:.3f}')
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
                   verticalalignment='top',
                   bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
        
        self.daily_avg_figure.tight_layout()
        self.daily_avg_canvas.draw()
    
    def _plot_time_intervals(self, data: Dict):
        """Plot Chart 5: Time Intervals Analysis"""
        self._time_intervals_data = data
        
        # Populate combo box with time intervals
        self.time_interval_combo.clear()
        self.time_interval_combo.addItem("All Intervals")
        self.time_interval_combo.addItems(list(data.keys()))
        
        self._update_time_interval_plot()
    
    def _update_time_interval_plot(self):
        """Update the time intervals plot"""
        if not hasattr(self, '_time_intervals_data'):
            return
        
        data = self._time_intervals_data
        self.time_intervals_figure.clear()
        
        selected = self.time_interval_combo.currentText()
        
        if selected == "All Intervals" or selected == "":
            # Plot all intervals in a grid
            num_intervals = len(data)
            cols = 4
            rows = (num_intervals + cols - 1) // cols
            
            gs = GridSpec(rows, cols, figure=self.time_intervals_figure,
                         hspace=0.4, wspace=0.3)
            
            self.time_intervals_figure.suptitle(
                'Implied vs Realized by Time Interval Across All Trading Days',
                fontsize=16, fontweight='bold', y=0.99
            )
            
            for idx, (time_interval, interval_data) in enumerate(data.items()):
                row = idx // cols
                col = idx % cols
                ax = self.time_intervals_figure.add_subplot(gs[row, col])
                
                dates = pd.to_datetime(interval_data['dates'])
                implied = interval_data['implied']
                realized = interval_data['realized']
                
                # Plot with smaller markers for clarity
                ax.plot(dates, implied, 'b-', label='Implied',
                       linewidth=1, marker='o', markersize=2, alpha=0.8)
                ax.plot(dates, realized, 'r-', label='Realized',
                       linewidth=1, marker='s', markersize=2, alpha=0.8)
                
                # Add trend lines
                if len(dates) > 1:
                    x_numeric = np.arange(len(dates))
                    z_implied = np.polyfit(x_numeric, implied, 1)
                    z_realized = np.polyfit(x_numeric, realized, 1)
                    ax.plot(dates, np.poly1d(z_implied)(x_numeric),
                           'b--', alpha=0.4, linewidth=0.8)
                    ax.plot(dates, np.poly1d(z_realized)(x_numeric),
                           'r--', alpha=0.4, linewidth=0.8)
                
                # Styling
                ax.set_title(f'{time_interval}', fontsize=10, fontweight='bold')
                ax.set_xlabel('', fontsize=7)
                ax.set_ylabel('Move ($)', fontsize=7)
                ax.tick_params(labelsize=6)
                ax.grid(True, alpha=0.3, linestyle='--')
                
                # Format dates
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
                ax.xaxis.set_major_locator(
                    mdates.DayLocator(interval=max(1, len(dates)//3))
                )
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
                
                # Legend only on first
                if idx == 0:
                    ax.legend(fontsize=7, loc='upper right')
            
            # Hide unused subplots
            for idx in range(num_intervals, rows * cols):
                row = idx // cols
                col = idx % cols
                ax = self.time_intervals_figure.add_subplot(gs[row, col])
                ax.axis('off')
        
        else:
            # Plot single selected interval with more detail
            if selected in data:
                ax = self.time_intervals_figure.add_subplot(111)
                interval_data = data[selected]
                
                dates = pd.to_datetime(interval_data['dates'])
                implied = interval_data['implied']
                realized = interval_data['realized']
                
                # Plot with larger markers
                line1 = ax.plot(dates, implied, 'b-', label='Implied',
                               linewidth=2, marker='o', markersize=6, alpha=0.9)
                line2 = ax.plot(dates, realized, 'r-', label='Realized',
                               linewidth=2, marker='s', markersize=6, alpha=0.9)
                
                # Add fill between
                ax.fill_between(dates, implied, realized,
                              where=(np.array(implied) >= np.array(realized)),
                              alpha=0.2, color='blue')
                ax.fill_between(dates, implied, realized,
                              where=(np.array(implied) < np.array(realized)),
                              alpha=0.2, color='red')
                
                # Interactive hover
                cursor = mplcursors.cursor([line1[0], line2[0]], hover=True)
                
                @cursor.connect("add")
                def on_hover(sel):
                    idx = sel.index
                    date_str = dates[idx].strftime('%Y-%m-%d')
                    if sel.artist == line1[0]:
                        label = "Implied"
                        value = implied[idx]
                    else:
                        label = "Realized"
                        value = realized[idx]
                    
                    sel.annotation.set_text(
                        f"{label}\n"
                        f"Date: {date_str}\n"
                        f"Move: ${value:.2f}"
                    )
                    sel.annotation.get_bbox_patch().set(fc="white", alpha=0.95)
                
                # Styling
                ax.set_title(f'Implied vs Realized at {selected}',
                           fontsize=14, fontweight='bold', pad=20)
                ax.set_xlabel('Trading Date', fontsize=12)
                ax.set_ylabel('Move ($)', fontsize=12)
                ax.legend(loc='upper left', fontsize=10)
                ax.grid(True, alpha=0.3, linestyle='--')
                
                # Format x-axis
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
                ax.xaxis.set_major_locator(
                    mdates.WeekdayLocator(interval=max(1, len(dates)//10))
                )
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
                
                # Add statistics
                if len(implied) > 0:
                    avg_impl = np.mean(implied)
                    avg_real = np.mean(realized)
                    std_impl = np.std(implied)
                    std_real = np.std(realized)
                    
                    stats_text = (f'Avg Implied: ${avg_impl:.2f} (σ={std_impl:.2f})\n'
                                f'Avg Realized: ${avg_real:.2f} (σ={std_real:.2f})')
                    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
                           fontsize=10, verticalalignment='top',
                           bbox=dict(boxstyle='round', facecolor='lightgray',
                                   alpha=0.8))
        
        self.time_intervals_figure.tight_layout()
        self.time_intervals_canvas.draw()
    
    def refresh_charts(self):
        """Refresh all charts with current data"""
        if self.chart_data:
            self.update_charts(self.chart_data)
            QMessageBox.information(self, "Success", "Charts refreshed successfully!")
    
    def export_charts(self):
        """Export all charts to files"""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Export Directory", ""
        )
        
        if directory:
            try:
                # Export each chart
                import os
                
                # Chart 1
                self.daily_decay_figure.savefig(
                    os.path.join(directory, 'chart1_daily_decay.png'),
                    dpi=150, bbox_inches='tight'
                )
                
                # Chart 2
                self.avg_decay_figure.savefig(
                    os.path.join(directory, 'chart2_avg_decay.png'),
                    dpi=150, bbox_inches='tight'
                )
                
                # Chart 3
                self.scatter_figure.savefig(
                    os.path.join(directory, 'chart3_scatter.png'),
                    dpi=150, bbox_inches='tight'
                )
                
                # Chart 4
                self.daily_avg_figure.savefig(
                    os.path.join(directory, 'chart4_daily_avg.png'),
                    dpi=150, bbox_inches='tight'
                )
                
                # Chart 5
                self.time_intervals_figure.savefig(
                    os.path.join(directory, 'chart5_time_intervals.png'),
                    dpi=150, bbox_inches='tight'
                )
                
                QMessageBox.information(
                    self, "Success",
                    f"Charts exported successfully to {directory}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Error",
                    f"Failed to export charts: {str(e)}"
                )