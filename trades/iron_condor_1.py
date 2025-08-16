from datetime import datetime
from typing import Any, Dict, Optional
import logging
import numpy as np
import pandas as pd
from pyparsing import Union
from config.strategy_config import StrategyConfig
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
import asyncio
import time as time_module

#Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IronCondor1:

    def _check_entry_signals_5min(spx_ohlc_data, spy_ohlc_data: pd.DataFrame, current_idx: int, 
                                  strategy: StrategyConfig) -> Dict[str, Any]:
        """Check entry signals using 5-minute bars only"""
        signals = {
            'entry_signal': False,
            'volume_condition': False,
            'direction_condition': False,
            'range_condition': False,
            'details': {}
        }
        
        # Condition 1: Volume check (consecutive candles below threshold)
        first_candle_volume = spy_ohlc_data.iloc[0]['volume']
        volume_threshold = first_candle_volume * strategy.volume_threshold
        
        volume_ok = True
        volume_checks = []
        for j in range(strategy.consecutive_candles):
            idx = current_idx - strategy.consecutive_candles + j + 1
            if idx >= 0 and idx < len(spy_ohlc_data):
                current_volume = spy_ohlc_data.iloc[idx]['volume']
                volume_checks.append(current_volume)
                if current_volume > volume_threshold:
                    volume_ok = False
                    
        signals['volume_condition'] = volume_ok
        signals['details']['volume_checks'] = volume_checks
        signals['details']['volume_threshold'] = volume_threshold

        if not volume_ok:
            return signals
        
        # Condition 2: Direction check (not all candles in same direction)
        directions = []
        for j in range(strategy.lookback_candles):
            idx = current_idx - strategy.lookback_candles + j + 1
            if idx >= 0 and idx < len(spy_ohlc_data):
                open_price = spy_ohlc_data.iloc[idx]['open']
                close_price = spy_ohlc_data.iloc[idx]['close']
                directions.append(1 if close_price > open_price else -1)
        
        if directions:
            all_same = all(d == directions[0] for d in directions)
            signals['direction_condition'] = not all_same
            signals['details']['directions'] = directions
            if all_same:
                return signals  # Exit early if all same direction
        
        # Condition 3: Range check (recent range below threshold)
        recent_ranges = []
        for j in range(strategy.avg_range_candles):
            idx = current_idx - strategy.avg_range_candles + j + 1
            if idx >= 0 and idx < len(spy_ohlc_data):
                high = spy_ohlc_data.iloc[idx]['high']
                low = spy_ohlc_data.iloc[idx]['low']
                recent_ranges.append(high - low)
        
        if recent_ranges:
            avg_recent_range = np.mean(recent_ranges)
            
            # Calculate average range for all candles up to current
            all_ranges = []
            for j in range(current_idx + 1):
                high = spy_ohlc_data.iloc[j]['high']
                low = spy_ohlc_data.iloc[j]['low']
                all_ranges.append(high - low)
            
            if all_ranges:
                avg_day_range = np.mean(all_ranges)
                range_threshold = avg_day_range * strategy.range_threshold
                signals['range_condition'] = avg_recent_range < range_threshold
                signals['details']['avg_recent_range'] = avg_recent_range
                signals['details']['avg_day_range'] = avg_day_range
                signals['details']['range_threshold'] = range_threshold
        
        # All conditions must be met
        signals['entry_signal'] = (
            signals['volume_condition'] and 
            signals['direction_condition'] and 
            signals['range_condition']
        )
        
        return signals
    
    async def _find_iron_condor_strikes(current_price: float, 
    timestamp: datetime,
    strategy, # StrategyConfig 
    data_provider : Union[MockDataProvider, PolygonDataProvider],
    tolerance: float = 0.05  # Stop early if ratio within 5% of target
) -> Optional[Dict[str, float]]:
         atm_strike = int(round(current_price / 5) * 5)
    
         min_wing = getattr(strategy, 'min_wing_width', 15)
         max_wing = getattr(strategy, 'max_wing_width', 70)
         step = getattr(strategy, 'wing_width_step', 5)
         target_ratio = getattr(strategy, 'target_win_loss_ratio', 1.5)

         distances = list(range(min_wing, max_wing + 1, step))
    
         logger.info(f"Searching {len(distances)} wing distances concurrently for optimal Iron Condor...")
    
   
         sc = atm_strike
         sp = atm_strike
    
         atm_call_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{sc*1000:08d}"
         atm_put_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{sp*1000:08d}"
    
         try:
            qsc, qsp = await asyncio.gather(
            data_provider._get_option_tick_quote(atm_call_symbol, timestamp),
            data_provider._get_option_tick_quote(atm_put_symbol, timestamp),
            return_exceptions=True)
            if isinstance(qsc, Exception) or isinstance(qsp, Exception) or None in [qsc, qsp]:
                logger.error("Failed to get ATM option quotes")
                return None
            
         except Exception as e:
               logger.error(f"Error fetching ATM quotes: {e}")
               return None
    
         option_symbols = []
         symbol_to_distance = {}
         symbol_to_strike_type = {}  # 'call' or 'put'
     
         for d in distances:
             lc = atm_strike + d  # Long call strike
             lp = atm_strike - d  # Long put strike
        
             lc_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{lc*1000:08d}"
             lp_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{lp*1000:08d}"
        
             option_symbols.extend([lc_symbol, lp_symbol])
             symbol_to_distance[lc_symbol] = d
             symbol_to_distance[lp_symbol] = d
             symbol_to_strike_type[lc_symbol] = 'call'
             symbol_to_strike_type[lp_symbol] = 'put'
    
        # Step 3: Fetch all wing option quotes concurrently
         logger.info(f"Fetching {len(option_symbols)} option quotes concurrently...")
    
         start_time = asyncio.get_event_loop().time()
    
         try:
             quote_tasks = [
             data_provider._get_option_tick_quote(symbol, timestamp) 
             for symbol in option_symbols
             ]
        
             all_quotes = await asyncio.gather(*quote_tasks, return_exceptions=True)
        
             fetch_time = asyncio.get_event_loop().time() - start_time
             logger.info(f"Fetched all quotes in {fetch_time:.2f} seconds")
        
         except Exception as e:
             logger.error(f"Error in concurrent quote fetching: {e}")
             return None
    
         # Step 4: Create lookup dictionary for successful quotes
         quote_lookup = {}
         failed_count = 0
    
         for i, symbol in enumerate(option_symbols):
             if i < len(all_quotes):
                quote = all_quotes[i]
             if isinstance(quote, Exception):
                logger.warning(f"Failed to get quote for {symbol}: {quote}")
                failed_count += 1
             elif quote is not None:
                quote_lookup[symbol] = quote
             else:
                failed_count += 1
    
         if failed_count > 0:
            logger.warning(f"Failed to fetch {failed_count} out of {len(option_symbols)} quotes")
    
         # Step 5: Define premium calculation function (moved outside loop)
         def get_premium(q, action):
            if q is None:
               return None
            if action == "long":
               return q.get('ask')
            elif action == "short":
                 return q.get('bid')
            return None
    
         # Step 6: Process all combinations to find best ratio
         best_combo = None
         best_diff = float('inf')
         valid_combos_checked = 0
    
         for d in distances:
             lc = atm_strike + d
             lp = atm_strike - d
        
             lc_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{lc*1000:08d}"
             lp_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{lp*1000:08d}"
        
             # Get quotes from our lookup
             qlc = quote_lookup.get(lc_symbol)
             qlp = quote_lookup.get(lp_symbol)
        
             # All strikes must exist
             if None in [qsc, qlc, qsp, qlp]:
                continue
        
            # Calculate premiums
             sc_mid = get_premium(qsc, "short")
             lc_mid = get_premium(qlc, "long")
             sp_mid = get_premium(qsp, "short")
             lp_mid = get_premium(qlp, "long")
        
             if None in [sc_mid, lc_mid, sp_mid, lp_mid]:
                continue
        
             valid_combos_checked += 1
        
        # Calculate net credit
             net_credit = sc_mid + sp_mid - lc_mid - lp_mid
             max_loss = d - net_credit
        
        # Avoid division by zero/bad combos
             if net_credit <= 0 or max_loss <= 0:
               continue
        
             ratio = net_credit / max_loss
             diff = abs(ratio - target_ratio)
        
             if diff < best_diff:
                best_diff = diff
                best_combo = {
                'short_call': sc,
                'long_call': lc,
                'short_put': sp,
                'long_put': lp,
                'net_credit': net_credit,
                'max_loss': max_loss,
                'ratio': ratio,
                'distance': d
                }
            
            # Early termination if we find a very good match
                if diff <= tolerance:
                   logger.info(f"Found excellent match early (tolerance={tolerance:.1%}): "
                           f"Wing=${d}, Credit=${net_credit:.2f}, Ratio={ratio:.2f}")
                   break
    
         logger.info(f"Processed {valid_combos_checked} valid combinations out of {len(distances)} distances")
    
         # Step 7: Return best result
         if best_combo:
            logger.info(f"Selected Iron Condor: Wing=${best_combo['distance']}, "
                   f"Credit=${best_combo['net_credit']:.2f}, Ratio={best_combo['ratio']:.2f} "
                   f"(Target: {target_ratio:.2f})")
            return best_combo
         else:
             logger.warning("No valid Iron Condor combination found")
             return None
    

    def _calculate_iron_condor_credit(quotes: Dict[str, Dict], contracts: Dict[str, str],
                                    ) -> float:
        """Calculate net credit for Iron Condor based on actual execution prices"""
        total_credit = 0
        total_debit = 0
        
        # Short positions (sell at bid)
        for leg in ['short_call', 'short_put']:
            contract = contracts[leg]
            if contract in quotes:
                price = quotes[contract]['bid']
                total_credit += price
        
        # Long positions (buy at ask)
        for leg in ['long_call', 'long_put']:
            contract = contracts[leg]
            if contract in quotes:
                price = quotes[contract]['ask'] 
                total_debit += price
        
        return total_credit - total_debit
    

    async def _execute_iron_condor(quotes: Dict[str, Dict], entry_time: datetime,
                                  contracts: Dict[str, str], strategy: StrategyConfig,
                                  signals: Dict,
                                  net_credit: float, current_price) -> Optional[Trade]:
        """Execute Iron Condor trade""" 
        # Check if we have all quotes
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing option quotes, skipping trade")
            return None
        
        # Build trade positions
        trade_contracts = {}
        
        # Short positions
        for leg, contract in [('short_call', contracts['short_call']), 
                            ('short_put', contracts['short_put'])]:
            quote = quotes[contract]
            price = quote['bid']
            strike = int(contract[-8:]) / 1000  # Extract strike from contract
            
            trade_contracts[contract] = {
                'position': -strategy.iron_1_trade_size,  # Short position
                'entry_price': price,
                'leg_type': leg,
                'strike': strike
            }
        
        # Long positions
        for leg, contract in [('long_call', contracts['long_call']), 
                            ('long_put', contracts['long_put'])]:
            quote = quotes[contract]
            price = quote['ask']
            strike = int(contract[-8:]) / 1000  # Extract strike from contract
            
            trade_contracts[contract] = {
                'position': strategy.iron_1_trade_size,  # Long position
                'entry_price': price,
                'leg_type': leg,
                'strike': strike
            }
        
        # Create trade with metadata
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Iron Condor 1",
            contracts=trade_contracts,
            size=strategy.iron_1_trade_size,
            entry_signals=signals,
            used_capital = 0,
            metadata={
                'net_credit': net_credit,
                'strategy_name': 'iron_1',
                'spx_price': current_price,
            }
        )
        
        return trade
    
    def _create_option_contracts(strikes: Dict[str, float], 
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
    

    async def _find_iron_trade(spx_ohlc_data, spy_ohlc_data : pd.DataFrame, i : int, 
                                 strategy : StrategyConfig, 
                                 date: datetime,
                                 current_price,
                                 current_bar_time,
                                 data_provider : Union[MockDataProvider, PolygonDataProvider],
                                 ) -> Trade:
        """Find Iron Condor 1 trade based on strategy config"""
        # Check entry conditions for new Iron Condor trades
        signals = IronCondor1._check_entry_signals_5min(spx_ohlc_data, spy_ohlc_data, i, strategy)
            
        if signals['entry_signal']:
            if isinstance(date, datetime):
                option_date = date
            else:
                option_date = datetime.combine(date, datetime.min.time())
                
            ic_result = await IronCondor1._find_iron_condor_strikes(current_price, current_bar_time, strategy, data_provider)
                
            if ic_result:
                ic_strikes = {
                        'short_call': ic_result['short_call'],
                        'short_put': ic_result['short_put'],
                        'long_call': ic_result['long_call'],
                        'long_put': ic_result['long_put']
                }
                    
                ic_contracts = IronCondor1._create_option_contracts(ic_strikes, option_date)
                ic_quotes = await data_provider.get_option_quotes(
                    list(ic_contracts.values()), current_bar_time
                )
                    
                net_credit = IronCondor1._calculate_iron_condor_credit(ic_quotes, ic_contracts)
                    
                if net_credit > 0:
                    ic_trade = await IronCondor1._execute_iron_condor(
                            ic_quotes,
                            current_bar_time,
                            ic_contracts,
                            strategy,
                            signals,
                            net_credit,
                            current_price
                    )
                    logger.info(f"Entered Iron Condor 1 at {current_bar_time}: {ic_strikes}")
                    return ic_trade
        return None