from dataclasses import dataclass

@dataclass
class StrategyConfig:
    """Configuration for Iron Condor and Straddle strategies with all parameters"""
    # General
    name: str = "strategy 1"
    trade_type: str = "Iron Condor 1 & Straddle 1"
    
    # Iron Condor 1 Entry signal parameters
    iron_1_consecutive_candles: int = 3  # Three consecutive 5min candles
    iron_1_volume_threshold: float = 0.5  # 50% of first candle volume
    iron_1_lookback_candles: int = 4  # Last four 5min candles for direction check
    iron_1_avg_range_candles: int = 2  # Last two 5min candles for range check
    iron_1_range_threshold: float = 0.8  # 80% of day's average range
    iron_1_trade_size: int = 10  # 10 contracts (configurable)
    iron_1_target_win_loss_ratio: float = 1.5  # Target 1.5:1 win/loss ratio
    min_wing_width: int = 15  # Minimum distance from ATM
    max_wing_width: int = 70  # Maximum distance from ATM
    
    # Straddle 1 parameters
    straddle_1_trade_size: int = 2
    straddle_1_distance_multiplier: float = 2.5  # Multiply IC credit by 2.5 for distance
    straddle_1_exit_percentage: float = 0.5  # Exit 50% of position
    straddle_1_exit_multiplier: float = 2.0  # Exit when price is 2x entry
    
    # Iron Condor 2 parameters
    iron_2_trade_size: int = 10 
    iron_2_trigger_multiplier  : float = 1.0
    iron_2_direction_lookback: int = 4
    iron_2_range_recent_candles: int = 2
    iron_2_range_reference_candles: int = 10
    iron_2_range_threshold: float = 1.25
    iron_2_min_distance: int = 5
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'trade_type': self.trade_type,
            'consecutive_candles': self.iron_1_consecutive_candles,
            'volume_threshold': self.iron_1_volume_threshold,
            'lookback_candles': self.iron_1_lookback_candles,
            'avg_range_candles': self.iron_1_avg_range_candles,
            'range_threshold': self.iron_1_range_threshold,
            'iron_1_trade_size': self.iron_1_trade_size,
            'straddle_1_trade_size': self.straddle_1_trade_size,
            'target_win_loss_ratio': self.iron_1_target_win_loss_ratio,
            'min_wing_width': self.min_wing_width,
            'max_wing_width': self.max_wing_width,
            'straddle_distance_multiplier': self.straddle_1_distance_multiplier,
            'straddle_exit_percentage': self.straddle_1_exit_percentage,
            'straddle_exit_multiplier': self.straddle_1_exit_multiplier
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)