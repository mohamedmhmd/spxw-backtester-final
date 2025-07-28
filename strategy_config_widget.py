import logging

# GUI imports
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

from strategy_config import StrategyConfig

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StrategyConfigWidget(QWidget):
    """Widget for configuring strategy parameters"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        layout = QFormLayout()
        
        # Strategy parameters
        self.consecutive_candles = QSpinBox()
        self.consecutive_candles.setRange(1, 10)
        self.consecutive_candles.setValue(3)
        layout.addRow("Consecutive Candles:", self.consecutive_candles)
        
        self.volume_threshold = QDoubleSpinBox()
        self.volume_threshold.setRange(0.1, 1.0)
        self.volume_threshold.setSingleStep(0.1)
        self.volume_threshold.setValue(0.5)
        layout.addRow("Volume Threshold (%):", self.volume_threshold)
        
        self.lookback_candles = QSpinBox()
        self.lookback_candles.setRange(1, 10)
        self.lookback_candles.setValue(4)
        layout.addRow("Lookback Candles:", self.lookback_candles)
        
        self.avg_range_candles = QSpinBox()
        self.avg_range_candles.setRange(1, 10)
        self.avg_range_candles.setValue(2)
        layout.addRow("Avg Range Candles:", self.avg_range_candles)
        
        self.range_threshold = QDoubleSpinBox()
        self.range_threshold.setRange(0.1, 1.0)
        self.range_threshold.setSingleStep(0.1)
        self.range_threshold.setValue(0.8)
        layout.addRow("Range Threshold (%):", self.range_threshold)
        
        self.trade_size = QSpinBox()
        self.trade_size.setRange(1, 100)
        self.trade_size.setValue(10)
        layout.addRow("Trade Size:", self.trade_size)
        
        self.win_loss_ratio = QDoubleSpinBox()
        self.win_loss_ratio.setRange(1.0, 3.0)
        self.win_loss_ratio.setSingleStep(0.1)
        self.win_loss_ratio.setValue(1.5)
        layout.addRow("Target Win/Loss Ratio:", self.win_loss_ratio)
        
        self.setLayout(layout)
    
    def get_config(self) -> StrategyConfig:
        """Get strategy configuration"""
        return StrategyConfig(
            consecutive_candles=self.consecutive_candles.value(),
            volume_threshold=self.volume_threshold.value(),
            lookback_candles=self.lookback_candles.value(),
            avg_range_candles=self.avg_range_candles.value(),
            range_threshold=self.range_threshold.value(),
            trade_size=self.trade_size.value(),
            target_win_loss_ratio=self.win_loss_ratio.value()
        )