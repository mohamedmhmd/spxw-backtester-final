from dataclasses import dataclass

@dataclass
class StrategyConfig:
    """Configuration for Iron Condor and Straddle strategies with all parameters"""
    # General
    name: str = "strategy 1"
    trade_type: str = "Iron Condor 1 & Straddle 1"
    
    # Iron Condor 1 Entry signal parameters
    iron_1_consecutive_candles: int = 3  
    iron_1_volume_threshold: float = 0.5 
    iron_1_lookback_candles: int = 4 
    iron_1_avg_range_candles: int = 2  
    iron_1_range_threshold: float = 0.8  
    iron_1_trade_size: int = 10  
    iron_1_target_win_loss_ratio: float = 1.5  
    min_wing_width: int = 15  
    max_wing_width: int = 70  
    
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
    iron_2_target_win_loss_ratio: float = 1.5
    
    # Straddle 2 parameters
    straddle_2_trade_size: int = 2
    straddle_2_trigger_multiplier: float = 1.0  # 100% in entry rules
    straddle_2_exit_percentage: float = 0.5  # Exit 50% of position
    straddle_2_exit_multiplier: float = 2.0  # Exit when price is 2x entry
    
    # Iron Condor 3 parameters - Iron Butterfly
    iron_3_trade_size: int = 10
    iron_3_trigger_multiplier: float = 1.0  # 100% of Iron 2 net premium
    iron_3_distance_multiplier: float = 1.0  # 100% of Iron 1 net premium for exclusion zone
    iron_3_target_win_loss_ratio: float = 1.5
    iron_3_direction_lookback: int = 4  # Last 4 candles not all same direction
    iron_3_range_recent_candles: int = 2  # Last 2 candles for range check
    iron_3_range_reference_candles: int = 10  # Last 10 candles for reference
    iron_3_range_threshold: float = 1.25  # 125% threshold
    
    #straddle 3 parameters
    straddle_3_trade_size: int = 2
    straddle_3_trigger_multiplier: float = 1.0  # 100% of Iron 2 net premium for strike calculation
    straddle_3_exit_percentage: float = 0.5  # Exit 50% of position
    straddle_3_exit_multiplier: float = 2.0  # Exit when price is 2x entry
    straddle_itm_override_multiplier: float = 2.5
    
    #Credit Spread 1 parameters
    cs_1_consecutive_candles: int = 3  
    cs_1_volume_threshold: float = 0.5 
    cs_1_lookback_candles: int = 4 
    cs_1_avg_range_candles: int = 2  
    cs_1_range_threshold: float = 0.8  
    cs_1_trade_size: int = 10  
    cs_1_target_loss_win_ratio: float = 3.0
    
    #Underlying Cover 1 parameters
    uc_1_cash_risk_percentage: float = 1.0     
    #Long Option 1 parameters
    lo_1_strike_multiplier: float = 5.0 
    lo_1_cover_risk_percentage: float = 1.0
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
            'iron_3_target_win_loss_ratio': self.iron_3_target_win_loss_ratio,
            'iron_3_direction_lookback': self.iron_3_direction_lookback,
            'iron_3_range_recent_candles': self.iron_3_range_recent_candles,
            'iron_3_range_reference_candles': self.iron_3_range_reference_candles,
            'iron_3_range_threshold': self.iron_3_range_threshold,
            # Straddle 3 parameters
            'straddle_3_trade_size': self.straddle_3_trade_size,
            'straddle_3_trigger_multiplier': self.straddle_3_trigger_multiplier,
            'straddle_3_exit_percentage': self.straddle_3_exit_percentage,
            'straddle_3_exit_multiplier': self.straddle_3_exit_multiplier,
            'straddle_itm_override_multiplier': self.straddle_itm_override_multiplier,
            # Credit Spread 1 parameters
            'cs_1_consecutive_candles': self.cs_1_consecutive_candles,
            'cs_1_volume_threshold': self.cs_1_volume_threshold,
            'cs_1_lookback_candles': self.cs_1_lookback_candles,
            'cs_1_avg_range_candles': self.cs_1_avg_range_candles,
            'cs_1_range_threshold': self.cs_1_range_threshold,
            'cs_1_trade_size': self.cs_1_trade_size,
            'cs_1_target_loss_win_ratio': self.cs_1_target_loss_win_ratio,
            # Underlying Cover 1 parameters
            'uc_1_cash_risk_percentage': self.uc_1_cash_risk_percentage,
            # Long Option 1 parameters
            'lo_1_strike_multiplier': self.lo_1_strike_multiplier,
            'lo_1_cover_risk_percentage': self.lo_1_cover_risk_percentage
            

        }
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)