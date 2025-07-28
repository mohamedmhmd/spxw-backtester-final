from dataclasses import dataclass


@dataclass
class StrategyConfig:
    """Configuration for Iron Condor strategy"""
    name: str = "iron_1"
    trade_type: str = "Iron Condor"
    consecutive_candles: int = 3
    volume_threshold: float = 0.5
    lookback_candles: int = 4
    avg_range_candles: int = 2
    range_threshold: float = 0.8
    trade_size: int = 10
    target_win_loss_ratio: float = 1.5
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'trade_type': self.trade_type,
            'consecutive_candles': self.consecutive_candles,
            'volume_threshold': self.volume_threshold,
            'lookback_candles': self.lookback_candles,
            'avg_range_candles': self.avg_range_candles,
            'range_threshold': self.range_threshold,
            'trade_size': self.trade_size,
            'target_win_loss_ratio': self.target_win_loss_ratio
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)