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
        
    def check_entry_signals_5min(self, current_idx: int, strategy: StrategyConfig) -> Dict[str, Any]:
        """Check entry signals - ULTRA OPTIMIZED VERSION"""
        # Condition 1: Volume check
        volume_threshold = self.spy_volume[0] * strategy.iron_1_volume_threshold
        vol_start = max(0, current_idx - strategy.iron_1_consecutive_candles)
        vol_end = min(self.len_spy, current_idx)
        
        if vol_end <= vol_start:
            return False
            
        volume_slice = self.spy_volume[vol_start:vol_end]
        volume_ok = np.all(volume_slice <= volume_threshold)
        
        if not volume_ok:
            return False
        
        # Condition 2: Direction check
        dir_start = max(0, current_idx - strategy.iron_1_lookback_candles)
        dir_end = min(self.len_spx, current_idx)
        
        if dir_end <= dir_start:
            return False
            
        # Vectorized direction calculation
        close_slice = self.spx_close[dir_start:dir_end]
        open_slice = self.spx_open[dir_start:dir_end]
        directions = np.where(close_slice > open_slice, 1, -1)
        
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
        range_ok = avg_recent_range < range_threshold
        
        return range_ok