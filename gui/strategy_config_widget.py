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
    
    load_configuration_requested = pyqtSignal()
    export_results_requested = pyqtSignal()
    

    def __init__(self, selected_strategy):
        self.selected_strategy = selected_strategy
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
        
        
        
        if self.selected_strategy == "Trades 16":
            self.min_wing_width = QSpinBox()
            self.min_wing_width.setRange(0, 100000)
            self.min_wing_width.setSingleStep(5)
            self.min_wing_width.setValue(15)
            self.min_wing_width.setToolTip("Minimum distance from ATM strike for long options")
            layout.addRow("Min Wing Width ($):", self.min_wing_width)

            self.max_wing_width = QSpinBox()
            self.max_wing_width.setRange(0, 200000)
            self.max_wing_width.setSingleStep(5)
            self.max_wing_width.setValue(70)
            self.max_wing_width.setToolTip("Maximum distance from ATM strike for long options")
            layout.addRow("Max Wing Width ($):", self.max_wing_width)
            # === IRON  CONDOR 1 settings ===
            iron_1_label = QLabel("=== IRON CONDOR 1 SETTINGS ===")
            iron_1_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(iron_1_label)
        
            self.iron_1_trade_size = QSpinBox()
            self.iron_1_trade_size.setRange(0, 1000000)
            self.iron_1_trade_size.setValue(10)
            self.iron_1_trade_size.setToolTip("Number of contracts per iron_1 trade")
            layout.addRow("Iron 1 Size:", self.iron_1_trade_size)

            self.iron_1_consecutive_candles = QSpinBox()
            self.iron_1_consecutive_candles.setRange(1, 100)
            self.iron_1_consecutive_candles.setValue(3)
            self.iron_1_consecutive_candles.setToolTip("Number of consecutive 5-min candles to check for volume condition")
            layout.addRow("Iron 1 Consecutive Candles (Volume Check):", self.iron_1_consecutive_candles)

            self.iron_1_volume_threshold = QDoubleSpinBox()
            self.iron_1_volume_threshold.setRange(0.0, 10000.0)
            self.iron_1_volume_threshold.setSingleStep(0.05)
            self.iron_1_volume_threshold.setValue(0.5)
            self.iron_1_volume_threshold.setToolTip("Volume threshold as fraction of first 5-min candle (0.5 = 50%)")
            layout.addRow("Iron 1 Volume Threshold (% of 1st candle):", self.iron_1_volume_threshold)

            self.iron_1_lookback_candles = QSpinBox()
            self.iron_1_lookback_candles.setRange(1, 100)
            self.iron_1_lookback_candles.setValue(4)
            self.iron_1_lookback_candles.setToolTip("Number of recent candles to check direction (not all same color)")
            layout.addRow("Iron 1 Direction Check Candles:", self.iron_1_lookback_candles)

            self.iron_1_avg_range_candles = QSpinBox()
            self.iron_1_avg_range_candles.setRange(1, 100)
            self.iron_1_avg_range_candles.setValue(2)
            self.iron_1_avg_range_candles.setToolTip("Number of recent candles to average for range comparison")
            layout.addRow("Iron 1 Range Avg Candles:", self.iron_1_avg_range_candles)

            self.iron_1_range_threshold = QDoubleSpinBox()
            self.iron_1_range_threshold.setRange(0.0, 100000.0)
            self.iron_1_range_threshold.setSingleStep(0.05)
            self.iron_1_range_threshold.setValue(0.8)
            self.iron_1_range_threshold.setToolTip("Range threshold as fraction of day's average range (0.8 = 80%)")
            layout.addRow("Iron 1 Range Threshold (% of day avg):", self.iron_1_range_threshold)


            self.iron_1_target_win_loss_ratio = QDoubleSpinBox()
            self.iron_1_target_win_loss_ratio.setRange(0.0, 100000.0)
            self.iron_1_target_win_loss_ratio.setSingleStep(0.1)
            self.iron_1_target_win_loss_ratio.setValue(1.5)
            self.iron_1_target_win_loss_ratio.setToolTip("Target win/loss ratio for strike selection (1.5 = 1.5:1)")
            layout.addRow("Iron 1 Target Win/Loss Ratio:", self.iron_1_target_win_loss_ratio)

        

            # === STRADDLE 1 PARAMETERS ===
            straddle_1_label = QLabel("=== STRADDLE 1 SETTINGS ===")
            straddle_1_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(straddle_1_label)

            self.straddle_1_trade_size = QSpinBox()
            self.straddle_1_trade_size.setRange(0, 1000000)
            self.straddle_1_trade_size.setValue(2)
            self.straddle_1_trade_size.setToolTip("Number of contracts per straddle_1 trade")
            layout.addRow("Straddle 1  Size:", self.straddle_1_trade_size)

            self.straddle_1_distance_multiplier = QDoubleSpinBox()
            self.straddle_1_distance_multiplier.setRange(0.0, 100000.0)
            self.straddle_1_distance_multiplier.setSingleStep(0.1)
            self.straddle_1_distance_multiplier.setValue(2.5)
            self.straddle_1_distance_multiplier.setToolTip("Multiply IC net credit by this to get straddle strike distance")
            layout.addRow("Straddle 1 Strike Distance Multiplier:", self.straddle_1_distance_multiplier)

            self.straddle_1_exit_percentage = QDoubleSpinBox()
            self.straddle_1_exit_percentage.setRange(0.0, 100000.0)
            self.straddle_1_exit_percentage.setSingleStep(0.05)
            self.straddle_1_exit_percentage.setValue(0.5)
            self.straddle_1_exit_percentage.setToolTip("Fraction of position to exit when conditions met (0.5 = 50%)")
            layout.addRow("Straddle 1 Exit Percentage:", self.straddle_1_exit_percentage)

            self.straddle_1_exit_multiplier = QDoubleSpinBox()
            self.straddle_1_exit_multiplier.setRange(0.0, 100000.0)
            self.straddle_1_exit_multiplier.setSingleStep(0.1)
            self.straddle_1_exit_multiplier.setValue(2.0)
            self.straddle_1_exit_multiplier.setToolTip("Exit when current price >= entry price × this multiplier")
            layout.addRow("Straddle 1 Exit Price Multiplier (x entry):", self.straddle_1_exit_multiplier)
        
        
            # === IRON  CONDOR 2 settings ===
            iron_2_label = QLabel("=== IRON CONDOR 2 SETTINGS ===")
            iron_2_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(iron_2_label)
        
            # iron_2_trade_size: int = 10
            self.iron_2_trade_size = QSpinBox()
            self.iron_2_trade_size.setRange(0, 1000000)
            self.iron_2_trade_size.setSingleStep(1)
            self.iron_2_trade_size.setValue(10)
            self.iron_2_trade_size.setToolTip("Number of contracts to trade for Iron Condor 2")
            layout.addRow("Iron 2 Trade Size:", self.iron_2_trade_size)

            # iron_2_trigger_multiplier: float = 1.0
            self.iron_2_trigger_multiplier = QDoubleSpinBox()
            self.iron_2_trigger_multiplier.setRange(0.0, 100000.0)
            self.iron_2_trigger_multiplier.setSingleStep(0.1)
            self.iron_2_trigger_multiplier.setValue(1.0)
            self.iron_2_trigger_multiplier.setToolTip("Multiplier to trigger Iron Condor 2 entry")
            layout.addRow("Iron 2 Trigger Multiplier:", self.iron_2_trigger_multiplier)

            # iron_2_direction_lookback: int = 4
            self.iron_2_direction_lookback = QSpinBox()
            self.iron_2_direction_lookback.setRange(1, 50)
            self.iron_2_direction_lookback.setSingleStep(1)
            self.iron_2_direction_lookback.setValue(4)
            self.iron_2_direction_lookback.setToolTip("Lookback period for direction analysis in Iron Condor 2")
            layout.addRow("Iron 2 Direction Lookback:", self.iron_2_direction_lookback)

            # iron_2_range_recent_candles: int = 2
            self.iron_2_range_recent_candles = QSpinBox()
            self.iron_2_range_recent_candles.setRange(1, 50)
            self.iron_2_range_recent_candles.setSingleStep(1)
            self.iron_2_range_recent_candles.setValue(2)
            self.iron_2_range_recent_candles.setToolTip("Number of recent candles for range calculation in Iron Condor 2")
            layout.addRow("Iron 2 Range Recent Candles:", self.iron_2_range_recent_candles)

            # iron_2_range_reference_candles: int = 10
            self.iron_2_range_reference_candles = QSpinBox()
            self.iron_2_range_reference_candles.setRange(1, 100)
            self.iron_2_range_reference_candles.setSingleStep(1)
            self.iron_2_range_reference_candles.setValue(10)
            self.iron_2_range_reference_candles.setToolTip("Number of reference candles for range calculation in Iron Condor 2")
            layout.addRow("Iron 2 Range Reference Candles:", self.iron_2_range_reference_candles)

            # iron_2_range_threshold: float = 1.25
            self.iron_2_range_threshold = QDoubleSpinBox()
            self.iron_2_range_threshold.setRange(0.0, 100000.0)
            self.iron_2_range_threshold.setSingleStep(0.25)
            self.iron_2_range_threshold.setValue(1.25)
            self.iron_2_range_threshold.setToolTip("Range threshold for Iron Condor 2")
            layout.addRow("Iron 2 Range Threshold:", self.iron_2_range_threshold)

        
            self.iron_2_target_win_loss_ratio = QDoubleSpinBox()
            self.iron_2_target_win_loss_ratio.setRange(0.0, 100000.0)
            self.iron_2_target_win_loss_ratio.setSingleStep(0.1)
            self.iron_2_target_win_loss_ratio.setValue(1.5)
            self.iron_2_target_win_loss_ratio.setToolTip("Target win/loss ratio for Iron Condor 2")
            layout.addRow("Iron 2 Target Win/Loss Ratio:", self.iron_2_target_win_loss_ratio)
        
        
            # === STRADDLE 2 settings ===
            straddle_2_label = QLabel("=== STRADDLE 2 SETTINGS ===")
            straddle_2_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(straddle_2_label)
        
            # straddle_2_trade_size: int = 2
            self.straddle_2_trade_size = QSpinBox()
            self.straddle_2_trade_size.setRange(0, 10000000)
            self.straddle_2_trade_size.setSingleStep(1)
            self.straddle_2_trade_size.setValue(2)
            self.straddle_2_trade_size.setToolTip("Number of contracts to trade for Straddle 2")
            layout.addRow("Straddle 2 Trade Size:", self.straddle_2_trade_size)

            # straddle_2_trigger_multiplier: float = 1.0
            self.straddle_2_trigger_multiplier = QDoubleSpinBox()
            self.straddle_2_trigger_multiplier.setRange(0.0, 100000.0)
            self.straddle_2_trigger_multiplier.setSingleStep(0.1)
            self.straddle_2_trigger_multiplier.setValue(1.0)
            self.straddle_2_trigger_multiplier.setToolTip("Trigger multiplier for Straddle 2 (1.0 = 100%)")
            layout.addRow("Straddle 2 Trigger Multiplier:", self.straddle_2_trigger_multiplier)

            # straddle_2_exit_percentage: float = 0.5
            self.straddle_2_exit_percentage = QDoubleSpinBox()
            self.straddle_2_exit_percentage.setRange(0.0, 100000.0)
            self.straddle_2_exit_percentage.setSingleStep(0.05)
            self.straddle_2_exit_percentage.setValue(0.5)
            self.straddle_2_exit_percentage.setToolTip("Fraction of position to exit for Straddle 2 (0.5 = 50%)")
            layout.addRow("Straddle 2 Exit Percentage:", self.straddle_2_exit_percentage)

            # straddle_2_exit_multiplier: float = 2.0
            self.straddle_2_exit_multiplier = QDoubleSpinBox()
            self.straddle_2_exit_multiplier.setRange(0.0, 100000.0)
            self.straddle_2_exit_multiplier.setSingleStep(0.1)
            self.straddle_2_exit_multiplier.setValue(2.0)
            self.straddle_2_exit_multiplier.setToolTip("Exit multiplier for Straddle 2 (2.0 = 2x entry price)")
            layout.addRow("Straddle 2 Exit Multiplier:", self.straddle_2_exit_multiplier)
        
        
            # === IRON  CONDOR 3 settings ===
            iron_3_label = QLabel("=== IRON CONDOR 3 SETTINGS ===")
            iron_3_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(iron_3_label)
        
            # iron_3_trade_size: int = 10
            self.iron_3_trade_size = QSpinBox()
            self.iron_3_trade_size.setRange(0, 1000000)
            self.iron_3_trade_size.setSingleStep(1)
            self.iron_3_trade_size.setValue(10)
            self.iron_3_trade_size.setToolTip("Number of contracts to trade for Iron Condor 3")
            layout.addRow("Iron 3 Trade Size:", self.iron_3_trade_size)

            # iron_3_trigger_multiplier: float = 1.0
            self.iron_3_trigger_multiplier = QDoubleSpinBox()
            self.iron_3_trigger_multiplier.setRange(0.0, 100000.0)
            self.iron_3_trigger_multiplier.setSingleStep(0.1)
            self.iron_3_trigger_multiplier.setValue(1.0)
            self.iron_3_trigger_multiplier.setToolTip("Trigger multiplier for Iron Condor 3 (1.0 = 100%)")
            layout.addRow("Iron 3 Trigger Multiplier:", self.iron_3_trigger_multiplier)

            # iron_3_distance_multiplier: float = 1.0
            self.iron_3_distance_multiplier = QDoubleSpinBox()
            self.iron_3_distance_multiplier.setRange(0.0, 100000.0)
            self.iron_3_distance_multiplier.setSingleStep(0.1)
            self.iron_3_distance_multiplier.setValue(1.0)
            self.iron_3_distance_multiplier.setToolTip("Distance multiplier for Iron Condor 3 (1.0 = 100%)")
            layout.addRow("Iron 3 Distance Multiplier:", self.iron_3_distance_multiplier)

        
            # iron_3_target_win_loss_ratio: float = 1.5
            self.iron_3_target_win_loss_ratio = QDoubleSpinBox()
            self.iron_3_target_win_loss_ratio.setRange(0.0, 100000.0)
            self.iron_3_target_win_loss_ratio.setSingleStep(0.1)
            self.iron_3_target_win_loss_ratio.setValue(1.5)
            self.iron_3_target_win_loss_ratio.setToolTip("Target win/loss ratio for Iron Condor 3")
            layout.addRow("Iron 3 Target Win/Loss Ratio:", self.iron_3_target_win_loss_ratio)

            # iron_3_direction_lookback: int = 4
            self.iron_3_direction_lookback = QSpinBox()
            self.iron_3_direction_lookback.setRange(1, 100)
            self.iron_3_direction_lookback.setSingleStep(1)
            self.iron_3_direction_lookback.setValue(4)
            self.iron_3_direction_lookback.setToolTip("Lookback period for direction analysis in Iron Condor 3")
            layout.addRow("Iron 3 Direction Lookback:", self.iron_3_direction_lookback)

            # iron_3_range_recent_candles: int = 2
            self.iron_3_range_recent_candles = QSpinBox()
            self.iron_3_range_recent_candles.setRange(1, 100)
            self.iron_3_range_recent_candles.setSingleStep(1)
            self.iron_3_range_recent_candles.setValue(2)
            self.iron_3_range_recent_candles.setToolTip("Number of recent candles for range calculation in Iron Condor 3")
            layout.addRow("Iron 3 Range Recent Candles:", self.iron_3_range_recent_candles)

            # iron_3_range_reference_candles: int = 10
            self.iron_3_range_reference_candles = QSpinBox()
            self.iron_3_range_reference_candles.setRange(1, 100)
            self.iron_3_range_reference_candles.setSingleStep(1)
            self.iron_3_range_reference_candles.setValue(10)
            self.iron_3_range_reference_candles.setToolTip("Number of reference candles for range calculation in Iron Condor 3")
            layout.addRow("Iron 3 Range Reference Candles:", self.iron_3_range_reference_candles)

            # iron_3_range_threshold: float = 1.25
            self.iron_3_range_threshold = QDoubleSpinBox()
            self.iron_3_range_threshold.setRange(0.0, 100000.0)
            self.iron_3_range_threshold.setSingleStep(0.05)
            self.iron_3_range_threshold.setValue(1.25)
            self.iron_3_range_threshold.setToolTip("Range threshold for Iron Condor 3")
            layout.addRow("Iron 3 Range Threshold:", self.iron_3_range_threshold)

            # === STRADDLE 3 settings ===
            straddle_3_label = QLabel("=== STRADDLE 3 SETTINGS ===")
            straddle_3_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(straddle_3_label)

            # straddle_3_trade_size: int
            self.straddle_3_trade_size = QSpinBox()
            self.straddle_3_trade_size.setRange(0, 1000000)
            self.straddle_3_trade_size.setSingleStep(1)
            self.straddle_3_trade_size.setValue(2)
            self.straddle_3_trade_size.setToolTip("Number of contracts to trade for Straddle 3")
            layout.addRow("Straddle 3 Trade Size:", self.straddle_3_trade_size)

            # straddle_3_trigger_multiplier: float
            self.straddle_3_trigger_multiplier = QDoubleSpinBox()
            self.straddle_3_trigger_multiplier.setRange(0.0, 100000.0)
            self.straddle_3_trigger_multiplier.setSingleStep(0.1)
            self.straddle_3_trigger_multiplier.setValue(1.0)
            self.straddle_3_trigger_multiplier.setToolTip("Trigger multiplier for Straddle 3")
            layout.addRow("Straddle 3 Trigger Multiplier:", self.straddle_3_trigger_multiplier)

            # straddle_3_exit_percentage: float
            self.straddle_3_exit_percentage = QDoubleSpinBox()
            self.straddle_3_exit_percentage.setRange(0.0, 100000.0)
            self.straddle_3_exit_percentage.setSingleStep(0.05)
            self.straddle_3_exit_percentage.setValue(0.5)
            self.straddle_3_exit_percentage.setToolTip("Exit percentage for Straddle 3 (0.5 = 50%)")
            layout.addRow("Straddle 3 Exit Percentage:", self.straddle_3_exit_percentage)

            # straddle_3_exit_multiplier: float
            self.straddle_3_exit_multiplier = QDoubleSpinBox()
            self.straddle_3_exit_multiplier.setRange(0.0, 100000000.0)
            self.straddle_3_exit_multiplier.setSingleStep(0.1)
            self.straddle_3_exit_multiplier.setValue(2.0)
            self.straddle_3_exit_multiplier.setToolTip("Exit multiplier for Straddle 3 (2.0 = 2x entry price)")
            layout.addRow("Straddle 3 Exit Multiplier:", self.straddle_3_exit_multiplier)
        
            self.straddle_itm_override_multiplier = QDoubleSpinBox()
            self.straddle_itm_override_multiplier.setRange(0.0, 1000000.0)
            self.straddle_itm_override_multiplier.setSingleStep(0.1)
            self.straddle_itm_override_multiplier.setValue(2.5)
            self.straddle_itm_override_multiplier.setToolTip("Multiplier override for ITM straddles")
            layout.addRow("Straddle ITM Override Multiplier:", self.straddle_itm_override_multiplier)
        
        
        elif self.selected_strategy == "Trades 17":
            self.min_wing_width = QSpinBox()
            self.min_wing_width.setRange(0, 100000)
            self.min_wing_width.setSingleStep(5)
            self.min_wing_width.setValue(15)
            self.min_wing_width.setToolTip("Minimum distance from ATM strike for long options")
            layout.addRow("Min Wing Width ($):", self.min_wing_width)

            self.max_wing_width = QSpinBox()
            self.max_wing_width.setRange(0, 200000)
            self.max_wing_width.setSingleStep(5)
            self.max_wing_width.setValue(70)
            self.max_wing_width.setToolTip("Maximum distance from ATM strike for long options")
            layout.addRow("Max Wing Width ($):", self.max_wing_width)
        
             # === CREDIT SPREAD 1 settings ===
            cs_1_label = QLabel("=== CREDIT SPREAD 1 SETTINGS ===")
            cs_1_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(cs_1_label)
        
            self.cs_1_trade_size = QSpinBox()
            self.cs_1_trade_size.setRange(0, 1000000)
            self.cs_1_trade_size.setValue(10)
            self.cs_1_trade_size.setToolTip("Number of contracts per cs_1 trade")
            layout.addRow("CS 1 Size:", self.cs_1_trade_size)

            self.cs_1_consecutive_candles = QSpinBox()
            self.cs_1_consecutive_candles.setRange(1, 100)
            self.cs_1_consecutive_candles.setValue(3)
            self.cs_1_consecutive_candles.setToolTip("Number of consecutive 5-min candles to check for volume condition")
            layout.addRow("CS 1 Consecutive Candles (Volume Check):", self.cs_1_consecutive_candles)

            self.cs_1_volume_threshold = QDoubleSpinBox()
            self.cs_1_volume_threshold.setRange(0.0, 10000.0)
            self.cs_1_volume_threshold.setSingleStep(0.05)
            self.cs_1_volume_threshold.setValue(0.5)
            self.cs_1_volume_threshold.setToolTip("Volume threshold as fraction of first 5-min candle (0.5 = 50%)")
            layout.addRow("CS 1 Volume Threshold (% of 1st candle):", self.cs_1_volume_threshold)

            self.cs_1_lookback_candles = QSpinBox()
            self.cs_1_lookback_candles.setRange(1, 100)
            self.cs_1_lookback_candles.setValue(4)
            self.cs_1_lookback_candles.setToolTip("Number of recent candles to check direction (not all same color)")
            layout.addRow("CS 1 Direction Check Candles:", self.cs_1_lookback_candles)

            self.cs_1_avg_range_candles = QSpinBox()
            self.cs_1_avg_range_candles.setRange(1, 100)
            self.cs_1_avg_range_candles.setValue(2)
            self.cs_1_avg_range_candles.setToolTip("Number of recent candles to average for range comparison")
            layout.addRow("CS 1 Range Avg Candles:", self.cs_1_avg_range_candles)

            self.cs_1_range_threshold = QDoubleSpinBox()
            self.cs_1_range_threshold.setRange(0.0, 100000.0)
            self.cs_1_range_threshold.setSingleStep(0.05)
            self.cs_1_range_threshold.setValue(0.8)
            self.cs_1_range_threshold.setToolTip("Range threshold as fraction of day's average range (0.8 = 80%)")
            layout.addRow("CS 1 Range Threshold (% of day avg):", self.cs_1_range_threshold)


            self.cs_1_target_loss_win_ratio = QDoubleSpinBox()
            self.cs_1_target_loss_win_ratio.setRange(0.0, 100000.0)
            self.cs_1_target_loss_win_ratio.setSingleStep(0.1)
            self.cs_1_target_loss_win_ratio.setValue(3.0)
            self.cs_1_target_loss_win_ratio.setToolTip("Target loss/win ratio for strike selection")
            layout.addRow("CS 1 Target Loss/Win Ratio:", self.cs_1_target_loss_win_ratio)
            
             # === UNDERLYING COVER 1 settings ===
            uc_1_label = QLabel("=== UNDERLYING COVER 1 SETTINGS ===")
            uc_1_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(uc_1_label)
            
            self.uc_1_cash_risk_percentage = QDoubleSpinBox()
            self.uc_1_cash_risk_percentage.setRange(0.0, 100.0)
            self.uc_1_cash_risk_percentage.setSingleStep(0.1)
            self.uc_1_cash_risk_percentage.setValue(1.0)
            self.uc_1_cash_risk_percentage.setToolTip("Percentage of credit spread cash.")
            layout.addRow("UC 1 Cash  Percentage:", self.uc_1_cash_risk_percentage)
            
            #=== LONG OPTION 1 settings ===
            lo_1_label = QLabel("=== LONG OPTION 1 SETTINGS ===")
            lo_1_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(lo_1_label)
            
            self.lo_1_strike_multiplier = QDoubleSpinBox()
            self.lo_1_strike_multiplier.setRange(0.0, 100000.0)
            self.lo_1_strike_multiplier.setSingleStep(0.1)
            self.lo_1_strike_multiplier.setValue(5.0)
            self.lo_1_strike_multiplier.setToolTip("Multiplier of ATM strike for long option strike.")
            layout.addRow("LO 1 Strike Multiplier:", self.lo_1_strike_multiplier)
            
            self.lo_1_cover_risk_percentage = QDoubleSpinBox()
            self.lo_1_cover_risk_percentage.setRange(0.0, 100.0)
            self.lo_1_cover_risk_percentage.setSingleStep(0.1)
            self.lo_1_cover_risk_percentage.setValue(1.0)
            self.lo_1_cover_risk_percentage.setToolTip("Percentage of underlying cover cash.")
            layout.addRow("LO 1 Cover Risk Percentage:", self.lo_1_cover_risk_percentage)
            
        elif self.selected_strategy == "Trades 18":
            # ===Long Strangle 1 settings ===
            ls_1_label = QLabel("=== Long Strangle 1 SETTINGS ===")
            ls_1_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(ls_1_label)
            
        
            self.ls_1_trade_a_size = QSpinBox()
            self.ls_1_trade_a_size.setRange(0, 1000000)
            self.ls_1_trade_a_size.setValue(10)
            self.ls_1_trade_a_size.setToolTip("Number of calls per long strangle 1 trade")
            layout.addRow("LS 1 Call Size:", self.ls_1_trade_a_size)
            
            self.ls_1_trade_b_size = QSpinBox()
            self.ls_1_trade_b_size.setRange(0, 1000000)
            self.ls_1_trade_b_size.setValue(10)
            self.ls_1_trade_b_size.setToolTip("Number of Puts per long strangle 1 trade")
            layout.addRow("LS 1 Put Size:", self.ls_1_trade_b_size)

            self.ls_1_consecutive_candles = QSpinBox()
            self.ls_1_consecutive_candles.setRange(1, 100)
            self.ls_1_consecutive_candles.setValue(3)
            self.ls_1_consecutive_candles.setToolTip("Number of consecutive 5-min candles to check for volume condition")
            layout.addRow("LS 1 Consecutive Candles (Volume Check):", self.ls_1_consecutive_candles)

            self.ls_1_volume_threshold = QDoubleSpinBox()
            self.ls_1_volume_threshold.setRange(0.0, 10000.0)
            self.ls_1_volume_threshold.setSingleStep(0.05)
            self.ls_1_volume_threshold.setValue(0.5)
            self.ls_1_volume_threshold.setToolTip("Volume threshold as fraction of first 5-min candle (0.5 = 50%)")
            layout.addRow("LS 1 Volume Threshold (% of 1st candle):", self.ls_1_volume_threshold)

            self.ls_1_lookback_candles = QSpinBox()
            self.ls_1_lookback_candles.setRange(1, 100)
            self.ls_1_lookback_candles.setValue(4)
            self.ls_1_lookback_candles.setToolTip("Number of recent candles to check direction (not all same color)")
            layout.addRow("LS 1 Direction Check Candles:", self.ls_1_lookback_candles)

            self.ls_1_avg_range_candles = QSpinBox()
            self.ls_1_avg_range_candles.setRange(1, 100)
            self.ls_1_avg_range_candles.setValue(2)
            self.ls_1_avg_range_candles.setToolTip("Number of recent candles to average for range comparison")
            layout.addRow("LS 1 Range Avg Candles:", self.ls_1_avg_range_candles)

            self.ls_1_range_threshold = QDoubleSpinBox()
            self.ls_1_range_threshold.setRange(0.0, 100000.0)
            self.ls_1_range_threshold.setSingleStep(0.05)
            self.ls_1_range_threshold.setValue(0.8)
            self.ls_1_range_threshold.setToolTip("Range threshold as fraction of day's average range (0.8 = 80%)")
            layout.addRow("LS 1 Range Threshold (% of day avg):", self.ls_1_range_threshold)
            
            # ===Long Strangle 2 settings ===
            ls_2_label = QLabel("=== Long Strangle 2 SETTINGS ===")
            ls_2_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(ls_2_label)
            
        
            self.ls_2_trade_a_size = QSpinBox()
            self.ls_2_trade_a_size.setRange(0, 1000000)
            self.ls_2_trade_a_size.setValue(10)
            self.ls_2_trade_a_size.setToolTip("Number of calls per long strangle 2 trade")
            layout.addRow("LS 2 Call Size:", self.ls_2_trade_a_size)
            
            self.ls_2_trade_b_size = QSpinBox()
            self.ls_2_trade_b_size.setRange(0, 1000000)
            self.ls_2_trade_b_size.setValue(10)
            self.ls_2_trade_b_size.setToolTip("Number of Puts per long strangle 2 trade")
            layout.addRow("LS 2 Put Size:", self.ls_2_trade_b_size)

            self.ls_2_consecutive_candles = QSpinBox()
            self.ls_2_consecutive_candles.setRange(1, 100)
            self.ls_2_consecutive_candles.setValue(3)
            self.ls_2_consecutive_candles.setToolTip("Number of consecutive 5-min candles to check for volume condition")
            layout.addRow("LS 2 Consecutive Candles (Volume Check):", self.ls_2_consecutive_candles)

            self.ls_2_volume_threshold = QDoubleSpinBox()
            self.ls_2_volume_threshold.setRange(0.0, 10000.0)
            self.ls_2_volume_threshold.setSingleStep(0.05)
            self.ls_2_volume_threshold.setValue(0.5)
            self.ls_2_volume_threshold.setToolTip("Volume threshold as fraction of first 5-min candle (0.5 = 50%)")
            layout.addRow("LS 2 Volume Threshold (% of 1st candle):", self.ls_2_volume_threshold)

            self.ls_2_lookback_candles = QSpinBox()
            self.ls_2_lookback_candles.setRange(1, 100)
            self.ls_2_lookback_candles.setValue(4)
            self.ls_2_lookback_candles.setToolTip("Number of recent candles to check direction (not all same color)")
            layout.addRow("LS 2 Direction Check Candles:", self.ls_2_lookback_candles)

            self.ls_2_avg_range_candles = QSpinBox()
            self.ls_2_avg_range_candles.setRange(1, 100)
            self.ls_2_avg_range_candles.setValue(2)
            self.ls_2_avg_range_candles.setToolTip("Number of recent candles to average for range comparison")
            layout.addRow("LS 1 Range Avg Candles:", self.ls_2_avg_range_candles)

            self.ls_2_range_threshold = QDoubleSpinBox()
            self.ls_2_range_threshold.setRange(0.0, 100000.0)
            self.ls_2_range_threshold.setSingleStep(0.05)
            self.ls_2_range_threshold.setValue(0.8)
            self.ls_2_range_threshold.setToolTip("Range threshold as fraction of day's average range (0.8 = 80%)")
            layout.addRow("LS 2 Range Threshold (% of day avg):", self.ls_2_range_threshold)
            
            self.ls_2_range_multiplier = QDoubleSpinBox()
            self.ls_2_range_multiplier.setRange(0.0, 100000.0)
            self.ls_2_range_multiplier.setSingleStep(0.1)
            self.ls_2_range_multiplier.setValue(1.0)
            self.ls_2_range_multiplier.setToolTip("Range multiplier for Long Strangle 2")
            layout.addRow("LS 2 Range Multiplier:", self.ls_2_range_multiplier)
            
            self.ls_2_dte = QSpinBox()
            self.ls_2_dte.setRange(0, 100000)
            self.ls_2_dte.setSingleStep(1)
            self.ls_2_dte.setValue(1)
            self.ls_2_dte.setToolTip("Days to expiration for Long Strangle 2")
            layout.addRow("LS 2 DTE:", self.ls_2_dte)
            
            
            # === Iron Condor settings ===
            ls_3_label = QLabel("=== Iron Condor  SETTINGS ===")
            ls_3_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(ls_3_label)
            
            # Trade Size (number of contracts)
            self.ic_tb_trade_size = QSpinBox()
            self.ic_tb_trade_size.setRange(1, 1000)
            self.ic_tb_trade_size.setSingleStep(1)
            self.ic_tb_trade_size.setValue(10)
            self.ic_tb_trade_size.setToolTip("Number of contracts for Iron Condor Time-Based trades")
            layout.addRow("IC TB Trade Size:", self.ic_tb_trade_size)
            
            # Entry Interval (which 5-minute bar to enter, 0-77)
            self.ic_tb_entry_interval = QSpinBox()
            self.ic_tb_entry_interval.setRange(0, 77)
            self.ic_tb_entry_interval.setSingleStep(1)
            self.ic_tb_entry_interval.setValue(55)
            self.ic_tb_entry_interval.setToolTip("5-minute bar index for entry (0=market open, 77=near close)")
            layout.addRow("IC TB Entry Interval:", self.ic_tb_entry_interval)

            # Minimum Short Distance (minimum distance from market for short options)
            self.ic_tb_min_short_distance = QSpinBox()
            self.ic_tb_min_short_distance.setRange(0, 10000)
            self.ic_tb_min_short_distance.setSingleStep(1)
            self.ic_tb_min_short_distance.setValue(10)
            self.ic_tb_min_short_distance.setToolTip("Minimum distance (points) from market for short options")
            layout.addRow("IC TB Min Short Distance:", self.ic_tb_min_short_distance)

            # Maximum Short Distance (maximum distance from market for short options)
            self.ic_tb_max_short_distance = QSpinBox()
            self.ic_tb_max_short_distance.setRange(0, 100000)
            self.ic_tb_max_short_distance.setSingleStep(1)
            self.ic_tb_max_short_distance.setValue(40)
            self.ic_tb_max_short_distance.setToolTip("Maximum distance (points) from market for short options")
            layout.addRow("IC TB Max Short Distance:", self.ic_tb_max_short_distance)

            # Minimum Wing Width (minimum distance between short and long options)
            self.ic_tb_min_wing_width = QSpinBox()
            self.ic_tb_min_wing_width.setRange(0, 10000)
            self.ic_tb_min_wing_width.setSingleStep(1)
            self.ic_tb_min_wing_width.setValue(10)
            self.ic_tb_min_wing_width.setToolTip("Minimum wing width (points) between short and long options")
            layout.addRow("IC TB Min Wing Width:", self.ic_tb_min_wing_width)

            # Maximum Wing Width (maximum distance between short and long options)
            self.ic_tb_max_wing_width = QSpinBox()
            self.ic_tb_max_wing_width.setRange(0, 100000)
            self.ic_tb_max_wing_width.setSingleStep(1)
            self.ic_tb_max_wing_width.setValue(40)
            self.ic_tb_max_wing_width.setToolTip("Maximum wing width (points) between short and long options")
            layout.addRow("IC TB Max Wing Width:", self.ic_tb_max_wing_width)

          

            self.ic_tb_target_win_loss_ratio = QDoubleSpinBox()
            self.ic_tb_target_win_loss_ratio.setRange(0.0, 10000000.0)
            self.ic_tb_target_win_loss_ratio.setSingleStep(0.1)
            self.ic_tb_target_win_loss_ratio.setValue(1.5)
            self.ic_tb_target_win_loss_ratio.setDecimals(2)
            self.ic_tb_target_win_loss_ratio.setToolTip("Target win:loss ratio for Iron Condor selection")
            layout.addRow("IC TB Target Win/Loss Ratio:", self.ic_tb_target_win_loss_ratio)

            
        elif self.selected_strategy == "Analysis":
            self.analysis_bar_minutes = QSpinBox()
            self.analysis_bar_minutes.setRange(1, 60)
            self.analysis_bar_minutes.setSingleStep(1)
            self.analysis_bar_minutes.setValue(5)
            self.analysis_bar_minutes.setToolTip("Bar duration in minutes for analysis")
            layout.addRow("Analysis Bar Minutes:", self.analysis_bar_minutes)

            self.analysis_dte = QSpinBox()
            self.analysis_dte.setRange(0, 365)
            self.analysis_dte.setSingleStep(1)
            self.analysis_dte.setValue(0)
            self.analysis_dte.setToolTip("Days to expiration for analysis")
            layout.addRow("Analysis DTE:", self.analysis_dte)

            self.option_underlying = QLineEdit()
            self.option_underlying.setText("I:SPX")
            self.option_underlying.setToolTip("Underlying symbol for option analysis")
            layout.addRow("Option Underlying:", self.option_underlying)

            self.strike_price_intervals = QDoubleSpinBox()
            self.strike_price_intervals.setRange(0.1, 1000.0)
            self.strike_price_intervals.setSingleStep(0.1)
            self.strike_price_intervals.setValue(5.0)
            self.strike_price_intervals.setToolTip("Strike price intervals for option analysis")
            layout.addRow("Strike Price Intervals:", self.strike_price_intervals)

            # Iron Butterfly Analysis section
            ib_analysis_label = QLabel("=== IRON BUTTERFLY ANALYSIS ===")
            ib_analysis_label.setStyleSheet("font-weight: bold; color: blue; margin-top: 15px;")
            layout.addRow(ib_analysis_label)

            
            self.ib_analysis_enabled = QCheckBox()
            self.ib_analysis_enabled.setChecked(True)
            self.ib_analysis_enabled.setToolTip("Enable Iron Butterfly trade simulation at each interval")
            layout.addRow("Enable IB Analysis:", self.ib_analysis_enabled)

            self.ib_analysis_trade_size = QSpinBox()
            self.ib_analysis_trade_size.setRange(1, 1000)
            self.ib_analysis_trade_size.setValue(10)
            self.ib_analysis_trade_size.setToolTip("Number of contracts per Iron Butterfly trade")
            layout.addRow("IB Trade Size:", self.ib_analysis_trade_size)
            
            self.ib_analysis_min_wing_width = QSpinBox()
            self.ib_analysis_min_wing_width.setRange(5, 200)
            self.ib_analysis_min_wing_width.setValue(15)
            self.ib_analysis_min_wing_width.setToolTip("Minimum wing width for Iron Butterfly")
            layout.addRow("IB Min Wing Width:", self.ib_analysis_min_wing_width)
            
            self.ib_analysis_max_wing_width = QSpinBox()
            self.ib_analysis_max_wing_width.setRange(10, 300)
            self.ib_analysis_max_wing_width.setValue(70)
            self.ib_analysis_max_wing_width.setToolTip("Maximum wing width for Iron Butterfly")
            layout.addRow("IB Max Wing Width:", self.ib_analysis_max_wing_width)
            
            self.ib_analysis_target_win_loss_ratio = QDoubleSpinBox()
            self.ib_analysis_target_win_loss_ratio.setRange(0.1, 10.0)
            self.ib_analysis_target_win_loss_ratio.setSingleStep(0.1)
            self.ib_analysis_target_win_loss_ratio.setValue(1.5)
            self.ib_analysis_target_win_loss_ratio.setToolTip("Target win/loss ratio for wing selection")
            layout.addRow("IB Target Win/Loss Ratio:", self.ib_analysis_target_win_loss_ratio)




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
        
        # Add buttons at the bottom
        button_layout = QHBoxLayout()
        
        self.load_config_button = QPushButton("Load Configuration")
        self.load_config_button.clicked.connect(self.load_configuration_clicked)
        self.load_config_button.setToolTip("Load strategy configuration from file")
        self.load_config_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        
        self.export_results_button = QPushButton("Export Results")
        self.export_results_button.clicked.connect(self.export_results_clicked)
        self.export_results_button.setToolTip("Export trades and statistics to CSV files")
        self.export_results_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        button_layout.addWidget(self.load_config_button)
        button_layout.addWidget(self.export_results_button)
        button_layout.addStretch()
        
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
        
        # Set window properties
        self.setMinimumWidth(400)
        self.setMaximumHeight(600)

    def load_configuration_clicked(self):
        """Emit signal to request configuration loading"""
        self.load_configuration_requested.emit()
        logger.info("Load configuration requested from strategy widget")

    def export_results_clicked(self):
        """Emit signal to request results export"""
        self.export_results_requested.emit()
        logger.info("Export results requested from strategy widget")

    def get_config(self) -> StrategyConfig:
        """Get full strategy configuration from widget values."""
        if self.selected_strategy == "Trades 16":
            return StrategyConfig(iron_1_consecutive_candles=self.iron_1_consecutive_candles.value(),
            iron_1_volume_threshold=self.iron_1_volume_threshold.value(),
            iron_1_lookback_candles=self.iron_1_lookback_candles.value(),
            iron_1_avg_range_candles=self.iron_1_avg_range_candles.value(),
            iron_1_range_threshold=self.iron_1_range_threshold.value(),
            iron_1_trade_size=self.iron_1_trade_size.value(),
            straddle_1_trade_size=self.straddle_1_trade_size.value(),
            iron_1_target_win_loss_ratio=self.iron_1_target_win_loss_ratio.value(),
            min_wing_width=self.min_wing_width.value(),
            max_wing_width=self.max_wing_width.value(),
            straddle_1_distance_multiplier=self.straddle_1_distance_multiplier.value(),
            straddle_1_exit_percentage=self.straddle_1_exit_percentage.value(),
            straddle_1_exit_multiplier=self.straddle_1_exit_multiplier.value(),
            iron_2_trade_size = self.iron_2_trade_size.value(),
            iron_2_trigger_multiplier = self.iron_2_trigger_multiplier.value(),
            iron_2_direction_lookback = self.iron_2_direction_lookback.value(),
            iron_2_range_recent_candles = self.iron_2_range_recent_candles.value(),
            iron_2_range_reference_candles = self.iron_2_range_reference_candles.value(),
            iron_2_range_threshold = self.iron_2_range_threshold.value(),
            iron_2_target_win_loss_ratio = self.iron_2_target_win_loss_ratio.value(),
            straddle_2_trade_size = self.straddle_2_trade_size.value(),
            straddle_2_trigger_multiplier = self.straddle_2_trigger_multiplier.value(),
            straddle_2_exit_percentage = self.straddle_2_exit_percentage.value(),
            straddle_2_exit_multiplier = self.straddle_2_exit_multiplier.value(),
            iron_3_trade_size = self.iron_3_trade_size.value(),
            iron_3_trigger_multiplier = self.iron_3_trigger_multiplier.value(),
            iron_3_distance_multiplier = self.iron_3_distance_multiplier.value(),
            iron_3_target_win_loss_ratio = self.iron_3_target_win_loss_ratio.value(),
            iron_3_direction_lookback = self.iron_3_direction_lookback.value(),
            iron_3_range_recent_candles = self.iron_3_range_recent_candles.value(),
            iron_3_range_reference_candles = self.iron_3_range_reference_candles.value(),
            iron_3_range_threshold = self.iron_3_range_threshold.value(),
            straddle_3_trade_size = self.straddle_3_trade_size.value(),
            straddle_3_trigger_multiplier = self.straddle_3_trigger_multiplier.value(),
            straddle_3_exit_percentage = self.straddle_3_exit_percentage.value(),
            straddle_3_exit_multiplier = self.straddle_3_exit_multiplier.value(),
            straddle_itm_override_multiplier = self.straddle_itm_override_multiplier.value(),
            )
        elif self.selected_strategy == "Trades 17":
             return StrategyConfig(
            cs_1_consecutive_candles=self.cs_1_consecutive_candles.value(),
            cs_1_volume_threshold=self.cs_1_volume_threshold.value(),
            cs_1_lookback_candles=self.cs_1_lookback_candles.value(),
            cs_1_avg_range_candles=self.cs_1_avg_range_candles.value(),
            cs_1_range_threshold=self.cs_1_range_threshold.value(),
            cs_1_trade_size=self.cs_1_trade_size.value(),
            cs_1_target_loss_win_ratio=self.cs_1_target_loss_win_ratio.value(),
            uc_1_cash_risk_percentage=self.uc_1_cash_risk_percentage.value(),
            lo_1_strike_multiplier=self.lo_1_strike_multiplier.value(),
            lo_1_cover_risk_percentage=self.lo_1_cover_risk_percentage.value(),
            min_wing_width=self.min_wing_width.value(),
            max_wing_width=self.max_wing_width.value(),
            
        )
        elif self.selected_strategy == "Trades 18":
             return StrategyConfig(
            ls_1_trade_a_size=self.ls_1_trade_a_size.value(),
            ls_1_trade_b_size=self.ls_1_trade_b_size.value(),
            ls_1_consecutive_candles=self.ls_1_consecutive_candles.value(),
            ls_1_volume_threshold=self.ls_1_volume_threshold.value(),
            ls_1_lookback_candles=self.ls_1_lookback_candles.value(),
            ls_1_avg_range_candles=self.ls_1_avg_range_candles.value(),
            ls_1_range_threshold=self.ls_1_range_threshold.value(),
            ls_2_trade_a_size=self.ls_2_trade_a_size.value(),
            ls_2_trade_b_size=self.ls_2_trade_b_size.value(),
            ls_2_consecutive_candles=self.ls_2_consecutive_candles.value(),
            ls_2_volume_threshold=self.ls_2_volume_threshold.value(),
            ls_2_lookback_candles=self.ls_2_lookback_candles.value(),
            ls_2_avg_range_candles=self.ls_2_avg_range_candles.value(),
            ls_2_range_threshold=self.ls_2_range_threshold.value(),
            ls_2_range_multiplier=self.ls_2_range_multiplier.value(),
            ls_2_dte=self.ls_2_dte.value(),
            ic_tb_entry_interval=self.ic_tb_entry_interval.value(),
            ic_tb_min_short_distance=self.ic_tb_min_short_distance.value(),
            ic_tb_max_short_distance=self.ic_tb_max_short_distance.value(),
            ic_tb_min_wing_width=self.ic_tb_min_wing_width.value(),
            ic_tb_max_wing_width=self.ic_tb_max_wing_width.value(),
            ic_tb_target_win_loss_ratio=self.ic_tb_target_win_loss_ratio.value(),
            ic_tb_trade_size=self.ic_tb_trade_size.value(),
            
        )
        elif self.selected_strategy == "Analysis":
            return StrategyConfig(
                analysis_bar_minutes=self.analysis_bar_minutes.value(),
                analysis_dte=self.analysis_dte.value(),
                option_underlying=self.option_underlying.text(),
                strike_price_intervals=self.strike_price_intervals.value(),
                ib_analysis_enabled=self.ib_analysis_enabled.isChecked(),
                ib_analysis_min_wing_width=self.ib_analysis_min_wing_width.value(),
                ib_analysis_max_wing_width=self.ib_analysis_max_wing_width.value(),
                ib_analysis_target_win_loss_ratio=self.ib_analysis_target_win_loss_ratio.value(),
                ib_analysis_trade_size=self.ib_analysis_trade_size.value(),  # NEW
            )
    
    def set_config(self, config: StrategyConfig):
        """Set widget values from a strategy configuration."""
        self.strategy_name.setText(config.name)
        self.trade_type.setText(config.trade_type)
        if self.selected_strategy == "Trades 16":
           self.iron_1_consecutive_candles.setValue(config.iron_1_consecutive_candles)
           self.iron_1_volume_threshold.setValue(config.iron_1_volume_threshold)
           self.iron_1_lookback_candles.setValue(config.iron_1_lookback_candles)
           self.iron_1_avg_range_candles.setValue(config.iron_1_avg_range_candles)
           self.iron_1_range_threshold.setValue(config.iron_1_range_threshold)
           self.iron_1_trade_size.setValue(config.iron_1_trade_size)
           self.straddle_1_trade_size.setValue(config.straddle_1_trade_size)
           self.iron_1_target_win_loss_ratio.setValue(config.iron_1_target_win_loss_ratio)
           self.min_wing_width.setValue(config.min_wing_width)
           self.max_wing_width.setValue(config.max_wing_width)
           self.straddle_1_distance_multiplier.setValue(config.straddle_1_distance_multiplier)
           self.straddle_1_exit_percentage.setValue(config.straddle_1_exit_percentage)
           self.straddle_1_exit_multiplier.setValue(config.straddle_1_exit_multiplier)
           self.iron_2_trade_size.setValue(config.iron_2_trade_size)
           self.iron_2_trigger_multiplier.setValue(config.iron_2_trigger_multiplier)
           self.iron_2_direction_lookback.setValue(config.iron_2_direction_lookback)
           self.iron_2_range_recent_candles.setValue(config.iron_2_range_recent_candles)
           self.iron_2_range_reference_candles.setValue(config.iron_2_range_reference_candles)
           self.iron_2_range_threshold.setValue(config.iron_2_range_threshold)
           self.iron_2_target_win_loss_ratio.setValue(config.iron_2_target_win_loss_ratio)
           self.straddle_2_trade_size.setValue(config.straddle_2_trade_size)
           self.straddle_2_trigger_multiplier.setValue(config.straddle_2_trigger_multiplier)
           self.straddle_2_exit_percentage.setValue(config.straddle_2_exit_percentage)
           self.straddle_2_exit_multiplier.setValue(config.straddle_2_exit_multiplier)
           self.iron_3_trade_size.setValue(config.iron_3_trade_size)
           self.iron_3_trigger_multiplier.setValue(config.iron_3_trigger_multiplier)
           self.iron_3_distance_multiplier.setValue(config.iron_3_distance_multiplier)
           self.iron_3_target_win_loss_ratio.setValue(config.iron_3_target_win_loss_ratio)
           self.iron_3_direction_lookback.setValue(config.iron_3_direction_lookback)
           self.iron_3_range_recent_candles.setValue(config.iron_3_range_recent_candles)
           self.iron_3_range_reference_candles.setValue(config.iron_3_range_reference_candles)
           self.iron_3_range_threshold.setValue(config.iron_3_range_threshold)
           self.straddle_3_trade_size.setValue(config.straddle_3_trade_size)
           self.straddle_3_trigger_multiplier.setValue(config.straddle_3_trigger_multiplier)
           self.straddle_3_exit_percentage.setValue(config.straddle_3_exit_percentage)
           self.straddle_3_exit_multiplier.setValue(config.straddle_3_exit_multiplier)
           self.straddle_itm_override_multiplier.setValue(config.straddle_itm_override_multiplier)
           self.cs_1_consecutive_candles.setValue(config.cs_1_consecutive_candles)
           self.cs_1_volume_threshold.setValue(config.cs_1_volume_threshold)
        elif self.selected_strategy == "Trades 17":
           self.cs_1_lookback_candles.setValue(config.cs_1_lookback_candles)
           self.cs_1_avg_range_candles.setValue(config.cs_1_avg_range_candles)
           self.cs_1_range_threshold.setValue(config.cs_1_range_threshold)
           self.cs_1_trade_size.setValue(config.cs_1_trade_size)
           self.cs_1_target_loss_win_ratio.setValue(config.cs_1_target_loss_win_ratio)
           self.uc_1_cash_risk_percentage.setValue(config.uc_1_cash_risk_percentage)
           self.lo_1_cover_risk_percentage = config.lo_1_cover_risk_percentage
           self.lo_1_strike_multiplier.setValue(config.lo_1_strike_multiplier)
           self.min_wing_width.setValue(config.min_wing_width)
           self.max_wing_width.setValue(config.max_wing_width)
        elif self.selected_strategy == "Trades 18":
           self.ls_1_trade_a_size.setValue(config.ls_1_trade_a_size)
           self.ls_1_trade_b_size.setValue(config.ls_1_trade_b_size)
           self.ls_1_consecutive_candles.setValue(config.ls_1_consecutive_candles)
           self.ls_1_volume_threshold.setValue(config.ls_1_volume_threshold)
           self.ls_1_lookback_candles.setValue(config.ls_1_lookback_candles)
           self.ls_1_avg_range_candles.setValue(config.ls_1_avg_range_candles)
           self.ls_1_range_threshold.setValue(config.ls_1_range_threshold)
           self.ls_2_trade_a_size.setValue(config.ls_2_trade_a_size)
           self.ls_2_trade_b_size.setValue(config.ls_2_trade_b_size)
           self.ls_2_consecutive_candles.setValue(config.ls_2_consecutive_candles)
           self.ls_2_volume_threshold.setValue(config.ls_2_volume_threshold)
           self.ls_2_lookback_candles.setValue(config.ls_2_lookback_candles)
           self.ls_2_avg_range_candles.setValue(config.ls_2_avg_range_candles)
           self.ls_2_range_threshold.setValue(config.ls_2_range_threshold)
           self.ls_2_range_multiplier.setValue(config.ls_2_range_multiplier)
           self.ls_2_dte.setValue(config.ls_2_dte)
           self.ic_tb_entry_interval.setValue(config.ic_tb_entry_interval)
           self.ic_tb_min_short_distance.setValue(config.ic_tb_min_short_distance)
           self.ic_tb_max_short_distance.setValue(config.ic_tb_max_short_distance)
           self.ic_tb_min_wing_width.setValue(config.ic_tb_min_wing_width)
           self.ic_tb_max_wing_width.setValue(config.ic_tb_max_wing_width)
           self.ic_tb_target_win_loss_ratio.setValue(config.ic_tb_target_win_loss_ratio)
           self.ic_tb_trade_size.setValue(config.ic_tb_trade_size)

        elif self.selected_strategy == "Analysis":
           self.analysis_bar_minutes.setValue(config.analysis_bar_minutes)
           self.analysis_dte.setValue(config.analysis_dte)
           self.option_underlying.setText(config.option_underlying)
           self.strike_price_intervals.setValue(config.strike_price_intervals)
              
           
              

        
