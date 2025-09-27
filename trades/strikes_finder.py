import asyncio
from datetime import datetime
from typing import Any, Dict, Tuple, Optional

from pyparsing import Union
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider

class StrikesFinder:
    
  async def _find_iron_condor_strikes(current_price: float, 
    timestamp: datetime,
    strategy, # StrategyConfig 
    data_provider : Union[MockDataProvider, PolygonDataProvider],
    tolerance: float = 0.03
) -> Optional[Dict[str, float]]:
        """
        Ultra-optimized version using gradient descent approach.
        Typically uses only 8-15 API calls total.
        """
        atm_strike = int(round(current_price / 5) * 5)
    
        min_wing = getattr(strategy, 'min_wing_width', 15)
        max_wing = getattr(strategy, 'max_wing_width', 70)
        step = 5
        target_ratio = getattr(strategy, 'iron_1_target_win_loss_ratio', 1.5)
    
        quote_cache = {}
    
        async def get_quotes_for_distance(d: int) -> Tuple[Optional[float], Optional[float], Optional[list]]:
                  """Get ratio and net premium for a specific distance"""
                  symbols = [
                  f"O:SPXW{timestamp.strftime('%y%m%d')}C{atm_strike*1000:08d}",  # Short call
                  f"O:SPXW{timestamp.strftime('%y%m%d')}P{atm_strike*1000:08d}",  # Short put
                  f"O:SPXW{timestamp.strftime('%y%m%d')}C{(atm_strike+d)*1000:08d}",  # Long call
                  f"O:SPXW{timestamp.strftime('%y%m%d')}P{(atm_strike-d)*1000:08d}",  # Long put
                  ]
        
                  # Fetch only uncached quotes
                  to_fetch = [(i, s) for i, s in enumerate(symbols) if s not in quote_cache]
                  fetched = []  # Add this line
                  if to_fetch:
                     fetched = await asyncio.gather(
                              *[data_provider._get_option_tick_quote(s, timestamp) for _, s in to_fetch],
                              return_exceptions=True
                    )
            
                  for (i, symbol), quote in zip(to_fetch, fetched):
                      if not isinstance(quote, Exception):
                         quote_cache[symbol] = quote
                      else:
                         quote_cache[symbol] = None
        
                  quotes = [quote_cache.get(s) for s in symbols]
        
                  if None in quotes:
                     return None, None, None
        
                  sc_bid = quotes[0].get('bid')
                  sp_bid = quotes[1].get('bid')
                  lc_ask = quotes[2].get('ask')
                  lp_ask = quotes[3].get('ask')
        
                  if None in [sc_bid, sp_bid, lc_ask, lp_ask]:
                     return None, None, None
        
                  net_premium = sc_bid + sp_bid - lc_ask - lp_ask
                  max_loss = d - net_premium
        
                  if net_premium <= 0 or max_loss <= 0:
                     return None, None, None
        
                  return net_premium / max_loss, net_premium, {s : quote_cache.get(s) for s in symbols}
    
        # Three-point search to find optimal region quickly
        distances = [min_wing, (min_wing + max_wing) // 2, max_wing]
    
        best_d = None
        best_ratio = None
        best_diff = float('inf')
    
        for d in distances:
            ratio, net_premium, quotes = await get_quotes_for_distance(d)
            if ratio is not None:
               diff = abs(ratio - target_ratio)
               if diff < best_diff:
                  best_diff = diff
                  best_d = d
                  best_ratio = ratio
    
        if best_d is None:
            return None
    
        # Binary search refinement
        if best_ratio < target_ratio:
           # Need smaller distance (higher ratio)
           left, right = min_wing, best_d
        else:
           # Need larger distance (lower ratio)
           left, right = best_d, max_wing
    
        while right - left > step:
           mid = ((left + right) // 2 // step) * step  # Align to step
        
           ratio, net_premium, quotes = await get_quotes_for_distance(mid)
        
           if ratio is None:
              break
        
           diff = abs(ratio - target_ratio)
           if diff < best_diff:
              best_diff = diff
              best_d = mid
              best_ratio = ratio
        
           if diff <= tolerance:
              break
        
           if ratio < target_ratio:
              right = mid
           else:
              left = mid
    
           # Final result
        if best_d:
           ratio, net_premium, quotes = await get_quotes_for_distance(best_d)
        if ratio is not None:
            return {
                'short_call': atm_strike,
                'long_call': atm_strike + best_d,
                'short_put': atm_strike,
                'long_put': atm_strike - best_d,
                'net_premium': net_premium,
                'max_loss': best_d - net_premium,
                'ratio': ratio,
                'distance': best_d,
                'quotes': quotes
            }
    
        return None