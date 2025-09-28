from datetime import datetime
from typing import Dict, Optional, Tuple
import logging
from pyparsing import Union
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
import asyncio

#Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IronCondorBase:
    
    async def execute(quotes: Dict[str, Dict], entry_time: datetime,
                                  contracts: Dict[str, str], strategy: StrategyConfig,
                                  net_premium: float, current_price, config : BacktestConfig, trade_type : str) -> Optional[Trade]:
        """Execute Iron Condor trade""" 
        # Check if we have all quotes
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing option quotes, skipping trade")
            return None
        
        size = IronCondorBase.get_size_from_trade_type(strategy, trade_type)
        
        # Build trade positions
        trade_contracts = {}
        strikes_dict = {}
        # Short positions
        for leg, contract in [('short_call', contracts['short_call']), 
                            ('short_put', contracts['short_put'])]:
            quote = quotes[contract]
            price = quote['bid']
            strike = int(contract[-8:]) / 1000  # Extract strike from contract
            strikes_dict[leg] = strike
            
            trade_contracts[contract] = {
                'position': -size,  # Short position
                'entry_price': price,
                'leg_type': leg,
                'strike': strike,
                'used_capital': config.commission_per_contract
            }
        
        # Long positions
        for leg, contract in [('long_call', contracts['long_call']), 
                            ('long_put', contracts['long_put'])]:
            quote = quotes[contract]
            price = quote['ask']
            strike = int(contract[-8:]) / 1000  # Extract strike from contract
            strikes_dict[leg] = strike
            
            trade_contracts[contract] = {
                'position': size,  # Long position
                'entry_price': price,
                'leg_type': leg,
                'strike': strike,
                'used_capital': price * 100 + config.commission_per_contract
            }
        
        representation = f"{strikes_dict['long_put']}/{strikes_dict['short_put']}  {strikes_dict['short_call']}/{strikes_dict['long_call']} ({strikes_dict['short_put'] - strikes_dict['long_put']})"
        # Create trade with metadata
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type=trade_type,
            contracts=trade_contracts,
            size=size,
            used_capital = 0.0,
            metadata={
                'net_premium': net_premium,
                'strategy_name': trade_type,
                'entry_spx_price': current_price,
                'representation': representation,
                'wing' : strikes_dict['short_put'] - strikes_dict['long_put']
            }
        )
        
        return trade
    
    
    def get_size_from_trade_type(strategy: StrategyConfig, trade_type: str) -> int:
        if trade_type == "Iron Condor 1":
            return strategy.iron_1_trade_size
        elif trade_type == "Iron Condor 2":
            return strategy.iron_2_trade_size
        elif trade_type == "Iron Condor 3(a)":
            return strategy.iron_3_trade_size
        elif trade_type == "Iron Condor 3(b)":
            return strategy.iron_3_trade_size
        else:
            raise ValueError(f"Unknown trade type: {trade_type}")
        
    def create_option_contracts(strikes: Dict[str, float], 
                               expiration: datetime) -> Dict[str, str]:
        """Create option contract symbols"""
        exp_str = expiration.strftime('%y%m%d')
        
        contracts = {
            'short_call': f"O:SPXW{exp_str}C{int(strikes['short_call']*1000):08d}",
            'short_put': f"O:SPXW{exp_str}P{int(strikes['short_put']*1000):08d}",
            'long_call': f"O:SPXW{exp_str}C{int(strikes['long_call']*1000):08d}",
            'long_put': f"O:SPXW{exp_str}P{int(strikes['long_put']*1000):08d}"
        }
        
        return contracts
    
    async def find_iron_condor_strikes(current_price: float, 
    timestamp: datetime,
    strategy, 
    data_provider : Union[MockDataProvider, PolygonDataProvider], target_ratio: float,
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