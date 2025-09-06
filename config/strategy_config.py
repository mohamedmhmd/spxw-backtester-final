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
    iron_2_target_win_loss_ratio: float = 1.5
    
    # Straddle 2 parameters
    straddle_2_trade_size: int = 2
    straddle_2_trigger_multiplier: float = 1.0  # 100% in entry rules
    straddle_2_exit_percentage: float = 0.5  # Exit 50% of position
    straddle_2_exit_multiplier: float = 2.0  # Exit when price is 2x entry
    
    # Iron Condor 3(a) parameters - Iron Butterfly
    iron_3_trade_size: int = 10
    iron_3_trigger_multiplier: float = 1.0  # 100% of Iron 2 net premium
    iron_3_distance_multiplier: float = 1.0  # 100% of Iron 1 net premium for exclusion zone
    iron_3_min_distance: int = 2  # Minimum distance from exclusion boundaries
    iron_3_target_win_loss_ratio: float = 1.5
    iron_3_direction_lookback: int = 4  # Last 4 candles not all same direction
    iron_3_range_recent_candles: int = 2  # Last 2 candles for range check
    iron_3_range_reference_candles: int = 10  # Last 10 candles for reference
    iron_3_range_threshold: float = 1.25  # 125% threshold
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'trade_type': self.trade_type,
            'iron_1_consecutive_candles': self.iron_1_consecutive_candles,
            'iron_1_volume_threshold': self.iron_1_volume_threshold,
            'iron_1_lookback_candles': self.iron_1_lookback_candles,
            'iron_1_avg_range_candles': self.iron_1_avg_range_candles,
            'iron_1_range_threshold': self.iron_1_range_threshold,
            'iron_1_trade_size': self.iron_1_trade_size,
            'straddle_1_trade_size': self.straddle_1_trade_size,
            'iron_1_target_win_loss_ratio': self.iron_1_target_win_loss_ratio,
            'min_wing_width': self.min_wing_width,
            'max_wing_width': self.max_wing_width,
            'straddle_1_distance_multiplier': self.straddle_1_distance_multiplier,
            'straddle_1_exit_percentage': self.straddle_1_exit_percentage,
            'straddle_1_exit_multiplier': self.straddle_1_exit_multiplier,
            'iron_2_trade_size': self.iron_2_trade_size,
            'iron_2_trigger_multiplier': self.iron_2_trigger_multiplier,
            'iron_2_direction_lookback': self.iron_2_direction_lookback,
            'iron_2_range_recent_candles': self.iron_2_range_recent_candles,
            'iron_2_range_reference_candles': self.iron_2_range_reference_candles,
            'iron_2_range_threshold': self.iron_2_range_threshold,
            'iron_2_min_distance': self.iron_2_min_distance,
            'iron_2_target_win_loss_ratio': self.iron_2_target_win_loss_ratio,
            'straddle_2_trade_size': self.straddle_2_trade_size,
            'straddle_2_trigger_multiplier': self.straddle_2_trigger_multiplier,
            'straddle_2_exit_percentage': self.straddle_2_exit_percentage,
            'straddle_2_exit_multiplier': self.straddle_2_exit_multiplier,
            'straddle_2_trade_size': self.straddle_2_trade_size,
            'straddle_2_trigger_multiplier': self.straddle_2_trigger_multiplier,
            'straddle_2_exit_percentage': self.straddle_2_exit_percentage,
            'straddle_2_exit_multiplier': self.straddle_2_exit_multiplier,
            # Iron 3 parameters
            'iron_3_trade_size': self.iron_3_trade_size,
            'iron_3_trigger_multiplier': self.iron_3_trigger_multiplier,
            'iron_3_distance_multiplier': self.iron_3_distance_multiplier,
            'iron_3_min_distance': self.iron_3_min_distance,
            'iron_3_target_win_loss_ratio': self.iron_3_target_win_loss_ratio,
            'iron_3_direction_lookback': self.iron_3_direction_lookback,
            'iron_3_range_recent_candles': self.iron_3_range_recent_candles,
            'iron_3_range_reference_candles': self.iron_3_range_reference_candles,
            'iron_3_range_threshold': self.iron_3_range_threshold,

        }
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)