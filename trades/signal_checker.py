import numpy as np
from typing import Dict, Any
import pandas as pd
from config.strategy_config import StrategyConfig

class OptimizedSignalChecker:
    """Cache numpy arrays for repeated signal checking"""
    
    def __init__(self, spx_ohlc_data: pd.DataFrame, spy_ohlc_data: pd.DataFrame):
        """Initialize and cache numpy arrays once"""
        # Cache SPX arrays
        self.spx_open = spx_ohlc_data['open'].values
        self.spx_close = spx_ohlc_data['close'].values
        self.spx_high = spx_ohlc_data['high'].values
        self.spx_low = spx_ohlc_data['low'].values
        self.len_spx = len(self.spx_open)
        
        # Cache SPY arrays
        self.spy_volume = spy_ohlc_data['volume'].values
        self.len_spy = len(self.spy_volume)
        
        # Pre-calculate all ranges once (used repeatedly)
        self.all_ranges = self.spx_high - self.spx_low
        
        # Pre-calculate directions for all candles (1 for up, -1 for down)
        self.all_directions = np.where(self.spx_close > self.spx_open, 1, -1)
        
    def iron_1_check_entry_signals_5min(self, current_idx: int, strategy: StrategyConfig) -> bool:
        """Check Iron 1 entry signals - ULTRA OPTIMIZED VERSION"""
        # Condition 1: Volume check
        volume_threshold = self.spy_volume[0] * strategy.iron_1_volume_threshold
        vol_start = max(0, current_idx - strategy.iron_1_consecutive_candles)
        vol_end = min(self.len_spy, current_idx)
        
        if vol_end <= vol_start:
            return False
            
        volume_slice = self.spy_volume[vol_start:vol_end]
        if not np.all(volume_slice <= volume_threshold):
            return False
        
        # Condition 2: Direction check
        dir_start = max(0, current_idx - strategy.iron_1_lookback_candles)
        dir_end = min(self.len_spx, current_idx)
        
        if dir_end <= dir_start:
            return False
            
        # Use pre-calculated directions
        directions = self.all_directions[dir_start:dir_end]
        
        # Fast check if all same
        if np.all(directions == directions[0]):
            return False
        
        # Condition 3: Range check
        range_start = max(0, current_idx - strategy.iron_1_avg_range_candles)
        range_end = min(self.len_spx, current_idx)
        
        if range_end <= range_start or current_idx <= 0:
            return False
            
        # Use pre-calculated ranges
        avg_recent_range = np.mean(self.all_ranges[range_start:range_end])
        avg_day_range = np.mean(self.all_ranges[:current_idx])
        range_threshold = avg_day_range * strategy.iron_1_range_threshold
        
        return avg_recent_range < range_threshold
    
    def iron_2_check_entry_conditions(self, current_idx: int, strategy_config: StrategyConfig) -> bool:
        """
        Check Iron 2 entry conditions - OPTIMIZED VERSION
        1) Last four 5-minute candles not all in same direction
        2) Average range of last two candles <= 125% of average of last ten candles
        """
        # Ensure we have enough data
        if current_idx < strategy_config.iron_2_range_reference_candles:
            return False
        
        # Condition 1: Direction check (last 4 candles)
        dir_start = current_idx - strategy_config.iron_2_direction_lookback
        dir_end = current_idx
        
        if dir_start < 0:
            return False
        
        # Use pre-calculated directions
        directions = self.all_directions[dir_start:dir_end]
        
        # If all same direction, fail immediately
        if np.all(directions == directions[0]):
                return False
        
        # Condition 2: Range comparison
        # Calculate indices for last 2 and last 10 candles
        recent_start = current_idx - strategy_config.iron_2_range_recent_candles
        recent_end = current_idx
        ref_start = current_idx - strategy_config.iron_2_range_reference_candles
        ref_end = current_idx
        
        if recent_start < 0 or ref_start < 0:
            return False
        
        # Use pre-calculated ranges
        avg_last_2 = np.mean(self.all_ranges[recent_start:recent_end])
        avg_last_10 = np.mean(self.all_ranges[ref_start:ref_end])
        threshold = avg_last_10 * strategy_config.iron_2_range_threshold
        
        return avg_last_2 <= threshold
    
    def iron_3_check_entry_conditions(self, current_idx: int, strategy_config: StrategyConfig) -> bool:
        """
        Check Iron 3 entry conditions - OPTIMIZED VERSION
        (same for both 3a and 3b):
        1) Last four 5-minute candles not all in same direction
        2) Average range of last two candles <= 125% of average of last ten candles
        """
        # Get parameters with defaults
        direction_lookback = getattr(strategy_config, 'iron_3_direction_lookback', 4)
        range_recent = getattr(strategy_config, 'iron_3_range_recent_candles', 2)
        range_reference = getattr(strategy_config, 'iron_3_range_reference_candles', 10)
        range_threshold_mult = getattr(strategy_config, 'iron_3_range_threshold', 1.25)
        
        # Ensure sufficient data
        if current_idx < range_reference:
            return False
        
        # Condition 1: Direction check
        dir_start = current_idx - direction_lookback
        dir_end = current_idx
        
        if dir_start < 0:
            return False
        
        # Use pre-calculated directions
        directions = self.all_directions[dir_start:dir_end]
        
        # If all same direction, fail immediately
        if np.all(directions == directions[0]):
            return False
        
        # Condition 2: Range check
        recent_start = current_idx - range_recent
        recent_end = current_idx
        ref_start = current_idx - range_reference
        ref_end = current_idx
        
        if recent_start < 0 or ref_start < 0:
            return False
        
        # Use pre-calculated ranges
        avg_recent = np.mean(self.all_ranges[recent_start:recent_end])
        avg_reference = np.mean(self.all_ranges[ref_start:ref_end])
        threshold = avg_reference * range_threshold_mult
        
        return avg_recent <= threshold
    
    def cs_1_check_entry_signals_5min(self, current_idx: int, strategy: StrategyConfig) -> bool:
        """Check Iron 1 entry signals - ULTRA OPTIMIZED VERSION"""
        # Condition 1: Volume check
        volume_threshold = self.spy_volume[0] * strategy.cs_1_volume_threshold
        vol_start = max(0, current_idx - strategy.cs_1_consecutive_candles)
        vol_end = min(self.len_spy, current_idx)
        
        if vol_end <= vol_start:
            return False
            
        volume_slice = self.spy_volume[vol_start:vol_end]
        if not np.all(volume_slice <= volume_threshold):
            return False
        
        # Condition 2: Direction check
        dir_start = max(0, current_idx - strategy.cs_1_lookback_candles)
        dir_end = min(self.len_spx, current_idx)
        
        if dir_end <= dir_start:
            return False
            
        # Use pre-calculated directions
        directions = self.all_directions[dir_start:dir_end]
        
        # Fast check if all same
        if np.all(directions == directions[0]):
            return False
        
        # Condition 3: Range check
        range_start = max(0, current_idx - strategy.cs_1_avg_range_candles)
        range_end = min(self.len_spx, current_idx)
        
        if range_end <= range_start or current_idx <= 0:
            return False
            
        # Use pre-calculated ranges
        avg_recent_range = np.mean(self.all_ranges[range_start:range_end])
        avg_day_range = np.mean(self.all_ranges[:current_idx])
        range_threshold = avg_day_range * strategy.cs_1_range_threshold
        
        return avg_recent_range < range_threshold
    
    
    def long_strangle_1_check_entry_signals(self, current_idx: int, strategy: StrategyConfig) -> bool:
        """Check strangle 1 entry signals - ULTRA OPTIMIZED VERSION"""
        # Condition 1: Volume check
        volume_threshold = self.spy_volume[0] * strategy.ls_1_volume_threshold
        vol_start = max(0, current_idx - strategy.ls_1_consecutive_candles)
        vol_end = min(self.len_spy, current_idx)
        
        if vol_end <= vol_start:
            return False
            
        volume_slice = self.spy_volume[vol_start:vol_end]
        if not np.all(volume_slice <= volume_threshold):
            return False
        
        # Condition 2: Direction check
        dir_start = max(0, current_idx - strategy.ls_1_lookback_candles)
        dir_end = min(self.len_spx, current_idx)
        
        if dir_end <= dir_start:
            return False
            
        # Use pre-calculated directions
        directions = self.all_directions[dir_start:dir_end]
        
        # Fast check if all same
        if np.all(directions == directions[0]):
            return False
        
        # Condition 3: Range check
        range_start = max(0, current_idx - strategy.ls_1_avg_range_candles)
        range_end = min(self.len_spx, current_idx)
        
        if range_end <= range_start or current_idx <= 0:
            return False
            
        # Use pre-calculated ranges
        avg_recent_range = np.mean(self.all_ranges[range_start:range_end])
        avg_day_range = np.mean(self.all_ranges[:current_idx])
        range_threshold = avg_day_range * strategy.ls_1_range_threshold
        
        return avg_recent_range < range_threshold
    
    
    