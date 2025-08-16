import logging
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from config.back_test_config import BacktestConfig

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BacktestConfigWidget(QWidget):
    """Widget for backtest configuration"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        layout = QFormLayout()
        
        # Date range
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(QDate.currentDate().addYears(-4))
        layout.addRow("Start Date:", self.start_date)
        
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(QDate.currentDate())
        layout.addRow("End Date:", self.end_date)
        # Commission
        self.commission = QDoubleSpinBox()
        self.commission.setRange(0, 10)
        self.commission.setSingleStep(0.05)
        self.commission.setValue(0.65)
        self.commission.setPrefix("$")
        layout.addRow("Commission/Contract:", self.commission)
        
        
        self.setLayout(layout)
    
    def get_config(self) -> BacktestConfig:
        """Get backtest configuration"""
        return BacktestConfig(
            start_date=self.start_date.date().toPyDate(),
            end_date=self.end_date.date().toPyDate(),
            commission_per_contract=self.commission.value(),
        )