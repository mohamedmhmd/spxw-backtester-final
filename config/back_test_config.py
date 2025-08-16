from dataclasses import dataclass
from datetime import datetime


@dataclass
class BacktestConfig:
    """Overall backtest configuration"""
    start_date: datetime
    end_date: datetime
    commission_per_contract: float = 0.65
    
    def to_dict(self) -> dict:
        return {
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'commission_per_contract': self.commission_per_contract,
        }