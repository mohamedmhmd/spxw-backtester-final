from dataclasses import dataclass

@dataclass
class StrategyConfig:
    """Configuration for Iron Condor and Straddle strategies with all parameters"""
    # General
    name: str = "iron_1"
    trade_type: str = "Iron Condor"
    
    # Iron Condor Entry signal parameters
    consecutive_candles: int = 3
    volume_threshold: float = 0.5
    lookback_candles: int = 4
    avg_range_candles: int = 2
    range_threshold: float = 1.5
    
    # Iron Condor Trade parameters
    trade_size: int = 10
    target_win_loss_ratio: float = 1.5
    
    # Iron Condor strike selection parameters
    min_wing_width: int = 10  # Minimum distance from ATM
    max_wing_width: int = 100  # Maximum distance from ATM
    wing_width_step: int = 5   # Step size for searching
    
    # Straddle parameters
    straddle_distance_multiplier: float = 2.5  # Multiply IC credit by this for distance
    straddle_exit_percentage: float = 0.1  # Exit 50% of position
    straddle_exit_multiplier: float = 1.1  # Exit when price is 2x entry
    
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
            'target_win_loss_ratio': self.target_win_loss_ratio,
            'min_wing_width': self.min_wing_width,
            'max_wing_width': self.max_wing_width,
            'wing_width_step': self.wing_width_step,
            'straddle_distance_multiplier': self.straddle_distance_multiplier,
            'straddle_exit_percentage': self.straddle_exit_percentage,
            'straddle_exit_multiplier': self.straddle_exit_multiplier
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)