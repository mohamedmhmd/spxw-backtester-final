import logging
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from config.strategy_config import StrategyConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StrategyConfigWidget(QWidget):
    """Widget for configuring all strategy parameters"""

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        # Create main layout with scroll area for better organization
        main_layout = QVBoxLayout()
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Create widget to hold form
        form_widget = QWidget()
        layout = QFormLayout()
        
        # Add section headers and organize parameters
        
        # === GENERAL STRATEGY INFO ===
        general_label = QLabel("=== GENERAL STRATEGY SETTINGS ===")
        general_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 10px;")
        layout.addRow(general_label)
        
        self.strategy_name = QLineEdit()
        self.strategy_name.setText("iron_1")
        layout.addRow("Strategy Name:", self.strategy_name)
        
        self.trade_type = QLineEdit()
        self.trade_type.setText("Iron Condor")
        self.trade_type.setReadOnly(True)
        layout.addRow("Trade Type:", self.trade_type)

        # === IRON CONDOR ENTRY SIGNAL PARAMETERS ===
        entry_label = QLabel("=== IRON CONDOR ENTRY CONDITIONS ===")
        entry_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
        layout.addRow(entry_label)

        self.consecutive_candles = QSpinBox()
        self.consecutive_candles.setRange(1, 10)
        self.consecutive_candles.setValue(3)
        self.consecutive_candles.setToolTip("Number of consecutive 5-min candles to check for volume condition")
        layout.addRow("Consecutive Candles (Volume Check):", self.consecutive_candles)

        self.volume_threshold = QDoubleSpinBox()
        self.volume_threshold.setRange(0.1, 1.0)
        self.volume_threshold.setSingleStep(0.05)
        self.volume_threshold.setValue(0.5)
        self.volume_threshold.setToolTip("Volume threshold as fraction of first 5-min candle (0.5 = 50%)")
        layout.addRow("Volume Threshold (% of 1st candle):", self.volume_threshold)

        self.lookback_candles = QSpinBox()
        self.lookback_candles.setRange(1, 10)
        self.lookback_candles.setValue(4)
        self.lookback_candles.setToolTip("Number of recent candles to check direction (not all same color)")
        layout.addRow("Direction Check Candles:", self.lookback_candles)

        self.avg_range_candles = QSpinBox()
        self.avg_range_candles.setRange(1, 10)
        self.avg_range_candles.setValue(2)
        self.avg_range_candles.setToolTip("Number of recent candles to average for range comparison")
        layout.addRow("Range Avg Candles:", self.avg_range_candles)

        self.range_threshold = QDoubleSpinBox()
        self.range_threshold.setRange(0.1, 2.0)
        self.range_threshold.setSingleStep(0.05)
        self.range_threshold.setValue(0.8)
        self.range_threshold.setToolTip("Range threshold as fraction of day's average range (0.8 = 80%)")
        layout.addRow("Range Threshold (% of day avg):", self.range_threshold)

        # === IRON CONDOR TRADE PARAMETERS ===
        ic_trade_label = QLabel("=== IRON CONDOR TRADE SETTINGS ===")
        ic_trade_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
        layout.addRow(ic_trade_label)

        self.iron_1_trade_size = QSpinBox()
        self.iron_1_trade_size.setRange(1, 100)
        self.iron_1_trade_size.setValue(10)
        self.iron_1_trade_size.setToolTip("Number of contracts per iron_1 trade")
        layout.addRow("Iron 1 Size:", self.iron_1_trade_size)

        self.target_win_loss_ratio = QDoubleSpinBox()
        self.target_win_loss_ratio.setRange(1.0, 5.0)
        self.target_win_loss_ratio.setSingleStep(0.1)
        self.target_win_loss_ratio.setValue(1.5)
        self.target_win_loss_ratio.setToolTip("Target win/loss ratio for strike selection (1.5 = 1.5:1)")
        layout.addRow("Target Win/Loss Ratio:", self.target_win_loss_ratio)

        # === IRON CONDOR STRIKE SELECTION ===
        ic_strikes_label = QLabel("=== IRON CONDOR STRIKE SELECTION ===")
        ic_strikes_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
        layout.addRow(ic_strikes_label)

        self.min_wing_width = QSpinBox()
        self.min_wing_width.setRange(5, 100)
        self.min_wing_width.setSingleStep(5)
        self.min_wing_width.setValue(15)
        self.min_wing_width.setToolTip("Minimum distance from ATM strike for long options")
        layout.addRow("Min Wing Width ($):", self.min_wing_width)

        self.max_wing_width = QSpinBox()
        self.max_wing_width.setRange(10, 200)
        self.max_wing_width.setSingleStep(5)
        self.max_wing_width.setValue(70)
        self.max_wing_width.setToolTip("Maximum distance from ATM strike for long options")
        layout.addRow("Max Wing Width ($):", self.max_wing_width)

        self.wing_width_step = QSpinBox()
        self.wing_width_step.setRange(1, 20)
        self.wing_width_step.setValue(5)
        self.wing_width_step.setToolTip("Step size when searching for optimal wing width")
        layout.addRow("Wing Width Step ($):", self.wing_width_step)

        # === STRADDLE PARAMETERS ===
        straddle_label = QLabel("=== STRADDLE SETTINGS ===")
        straddle_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
        layout.addRow(straddle_label)

        self.straddle_1_trade_size = QSpinBox()
        self.straddle_1_trade_size.setRange(1, 100)
        self.straddle_1_trade_size.setValue(2)
        self.straddle_1_trade_size.setToolTip("Number of contracts per straddle_1 trade")
        layout.addRow("Straddle 1  Size:", self.straddle_1_trade_size)

        self.straddle_distance_multiplier = QDoubleSpinBox()
        self.straddle_distance_multiplier.setRange(1.0, 10.0)
        self.straddle_distance_multiplier.setSingleStep(0.1)
        self.straddle_distance_multiplier.setValue(2.5)
        self.straddle_distance_multiplier.setToolTip("Multiply IC net credit by this to get straddle strike distance")
        layout.addRow("Strike Distance Multiplier:", self.straddle_distance_multiplier)

        self.straddle_exit_percentage = QDoubleSpinBox()
        self.straddle_exit_percentage.setRange(0.01, 1.0)
        self.straddle_exit_percentage.setSingleStep(0.05)
        self.straddle_exit_percentage.setValue(0.5)
        self.straddle_exit_percentage.setToolTip("Fraction of position to exit when conditions met (0.5 = 50%)")
        layout.addRow("Exit Percentage:", self.straddle_exit_percentage)

        self.straddle_exit_multiplier = QDoubleSpinBox()
        self.straddle_exit_multiplier.setRange(1.0, 10.0)
        self.straddle_exit_multiplier.setSingleStep(0.1)
        self.straddle_exit_multiplier.setValue(2.0)
        self.straddle_exit_multiplier.setToolTip("Exit when current price >= entry price × this multiplier")
        layout.addRow("Exit Price Multiplier (x entry):", self.straddle_exit_multiplier)
        
        # Add some spacing at the end
        spacer_label = QLabel("")
        spacer_label.setMinimumHeight(20)
        layout.addRow(spacer_label)
        
        # Set the layout to the form widget
        form_widget.setLayout(layout)
        
        # Add form widget to scroll area
        scroll.setWidget(form_widget)
        
        # Add scroll area to main layout
        main_layout.addWidget(scroll)
        
        # Add buttons at the bottom
        button_layout = QHBoxLayout()
        
        self.reset_button = QPushButton("Reset to Defaults")
        self.reset_button.clicked.connect(self.reset_to_defaults)
        self.reset_button.setToolTip("Reset all parameters to strategy defaults")
        
        self.validate_button = QPushButton("Validate Settings")
        self.validate_button.clicked.connect(self.validate_settings)
        self.validate_button.setToolTip("Check if current settings are valid")
        
        button_layout.addWidget(self.reset_button)
        button_layout.addWidget(self.validate_button)
        button_layout.addStretch()
        
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
        
        # Set window properties
        self.setMinimumWidth(400)
        self.setMaximumHeight(600)

    def reset_to_defaults(self):
        """Reset all parameters to strategy defaults"""
        self.strategy_name.setText("iron_1")
        self.consecutive_candles.setValue(3)
        self.volume_threshold.setValue(0.5)
        self.lookback_candles.setValue(4)
        self.avg_range_candles.setValue(2)
        self.range_threshold.setValue(0.8)
        self.trade_size.setValue(10)
        self.target_win_loss_ratio.setValue(1.5)
        self.min_wing_width.setValue(15)
        self.max_wing_width.setValue(70)
        self.wing_width_step.setValue(5)
        self.straddle_distance_multiplier.setValue(2.5)
        self.straddle_exit_percentage.setValue(0.5)
        self.straddle_exit_multiplier.setValue(2.0)
        
        logger.info("Reset all parameters to defaults")

    def validate_settings(self):
        """Validate current settings and show results"""
        errors = []
        warnings = []
        
        # Check logical constraints
        if self.min_wing_width.value() >= self.max_wing_width.value():
            errors.append("Min wing width must be less than max wing width")
        
        if self.wing_width_step.value() > (self.max_wing_width.value() - self.min_wing_width.value()):
            warnings.append("Wing width step is larger than search range")
        
        if self.consecutive_candles.value() > self.lookback_candles.value():
            warnings.append("Consecutive candles > lookback candles may cause issues")
        
        if self.volume_threshold.value() > 0.8:
            warnings.append("Volume threshold > 80% may result in very few signals")
        
        if self.range_threshold.value() > 1.0:
            warnings.append("Range threshold > 100% may result in very few signals")
        
        if self.straddle_exit_percentage.value() > 0.8:
            warnings.append("Straddle exit percentage > 80% exits most of position")
        
        # Show results
        if errors:
            QMessageBox.critical(self, "Validation Errors", 
                               f"Please fix these errors:\n\n" + "\n".join(f"• {error}" for error in errors))
        elif warnings:
            QMessageBox.warning(self, "Validation Warnings", 
                              f"Consider reviewing these settings:\n\n" + "\n".join(f"• {warning}" for warning in warnings))
        else:
            QMessageBox.information(self, "Validation Success", 
                                  "All settings look good!")
        
        logger.info(f"Validation complete: {len(errors)} errors, {len(warnings)} warnings")

    def get_config(self) -> StrategyConfig:
        """Get full strategy configuration from widget values."""
        return StrategyConfig(
            name=self.strategy_name.text(),
            trade_type=self.trade_type.text(),
            consecutive_candles=self.consecutive_candles.value(),
            volume_threshold=self.volume_threshold.value(),
            lookback_candles=self.lookback_candles.value(),
            avg_range_candles=self.avg_range_candles.value(),
            range_threshold=self.range_threshold.value(),
            iron_1_trade_size=self.iron_1_trade_size.value(),
            straddle_1_trade_size=self.straddle_1_trade_size.value(),
            target_win_loss_ratio=self.target_win_loss_ratio.value(),
            min_wing_width=self.min_wing_width.value(),
            max_wing_width=self.max_wing_width.value(),
            wing_width_step=self.wing_width_step.value(),
            straddle_distance_multiplier=self.straddle_distance_multiplier.value(),
            straddle_exit_percentage=self.straddle_exit_percentage.value(),
            straddle_exit_multiplier=self.straddle_exit_multiplier.value()
        )
    
    def set_config(self, config: StrategyConfig):
        """Set widget values from a strategy configuration."""
        self.strategy_name.setText(config.name)
        self.trade_type.setText(config.trade_type)
        self.consecutive_candles.setValue(config.consecutive_candles)
        self.volume_threshold.setValue(config.volume_threshold)
        self.lookback_candles.setValue(config.lookback_candles)
        self.avg_range_candles.setValue(config.avg_range_candles)
        self.range_threshold.setValue(config.range_threshold)
        self.iron_1_trade_size.setValue(config.iron_1_trade_size)
        self.straddle_1_trade_size.setValue(config.straddle_1_trade_size)
        self.target_win_loss_ratio.setValue(config.target_win_loss_ratio)
        self.min_wing_width.setValue(config.min_wing_width)
        self.max_wing_width.setValue(config.max_wing_width)
        self.wing_width_step.setValue(config.wing_width_step)
        self.straddle_distance_multiplier.setValue(config.straddle_distance_multiplier)
        self.straddle_exit_percentage.setValue(config.straddle_exit_percentage)
        self.straddle_exit_multiplier.setValue(config.straddle_exit_multiplier)