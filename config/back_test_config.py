from dataclasses import dataclass
from datetime import datetime


@dataclass
class BacktestConfig:
    """Overall backtest configuration"""
    start_date: datetime
    end_date: datetime
    initial_capital: float = 100000.0
    commission_per_contract: float = 0.65
    slippage_ticks: int = 1
    
    def to_dict(self) -> dict:
        return {
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'initial_capital': self.initial_capital,
            'commission_per_contract': self.commission_per_contract,
            'slippage_ticks': self.slippage_ticks,
        }