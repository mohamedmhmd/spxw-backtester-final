from datetime import datetime
from typing import Any, Dict, Optional, List
import logging
import numpy as np
import pandas as pd
from pyparsing import Union
from config.back_test_config import BacktestConfig
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


class IronCondor2:
    @staticmethod
    def _check_iron2_trigger_price(current_price: float, iron1_trade: Trade, strategy_config : StrategyConfig) -> bool:
        """
        Check if current price triggers Iron 2 entry based on Iron 1 positions
        
        Trigger: SPX moves to Iron 1 short strikes +/- 100% net premium collected
        """
        # Get Iron 1 trade details
        iron_1_net_premium = iron1_trade.metadata.get('net_premium', 0)
            
        # Find short strikes from trade contracts
        iron_1_short_strike = None    
        for contract_symbol, contract_data in iron1_trade.contracts.items():
            if contract_data['leg_type'] == 'short_call':
                iron_1_short_strike = contract_data['strike']
                break
                
        # Calculate trigger prices: short strikes +/- 100% of net premium
        upper_trigger = iron_1_short_strike + strategy_config.iron_2_trigger_multiplier* iron_1_net_premium
        lower_trigger = iron_1_short_strike - strategy_config.iron_2_trigger_multiplier* iron_1_net_premium
            
        # Check if current price is at or beyond trigger levels
        if current_price >= upper_trigger or current_price <= lower_trigger:
            logger.info(f"Iron 2 trigger price reached: {current_price:.2f} "
                           f"(triggers: {lower_trigger:.2f} - {upper_trigger:.2f})")
            return True
                
        return False

    @staticmethod
    def _check_iron2_entry_conditions(spx_ohlc_data: pd.DataFrame, current_idx: int, strategy_config : StrategyConfig) -> Dict[str, Any]:
        """
        Check Iron 2 entry conditions:
        1) Last four 5-minute candles not all in same direction
        2) Average range of last two candles <= 125% of average of last ten candles
        """
        signals = {
            'entry_signal': False,
            'direction_condition': False,
            'range_condition': False,
            'details': {}
        }
        
        # Ensure we have enough data
        if current_idx < strategy_config.iron_2_range_reference_candles:
            return signals
            
        # Condition 1: Last four candles not all in same direction
        directions = []
        for j in range(strategy_config.iron_2_direction_lookback):  # Last 4 candles
            idx = current_idx - strategy_config.iron_2_direction_lookback  + j  # +1 because current_idx is 0-based
            if idx >= 0 and idx < len(spx_ohlc_data):
                open_price = spx_ohlc_data.iloc[idx]['open']
                close_price = spx_ohlc_data.iloc[idx]['close']
                directions.append(1 if close_price > open_price else -1)
        
        if len(directions) == strategy_config.iron_2_direction_lookback:
            all_same_direction = all(d == directions[0] for d in directions)
            signals['direction_condition'] = not all_same_direction
            signals['details']['last_4_directions'] = directions
            signals['details']['all_same_direction'] = all_same_direction
            if all_same_direction:
                return signals
        
        # Condition 2: Range comparison
        # Get ranges for last 2 candles
        last_2_ranges = []
        for j in range(strategy_config.iron_2_range_recent_candles):  # Last 2 candles
            idx = current_idx - strategy_config.iron_2_range_recent_candles + j
            if idx >= 0 and idx < len(spx_ohlc_data):
                high = spx_ohlc_data.iloc[idx]['high']
                low = spx_ohlc_data.iloc[idx]['low']
                last_2_ranges.append(high - low)
        
        # Get ranges for last 10 candles
        last_10_ranges = []
        for j in range(strategy_config.iron_2_range_reference_candles):  # Last 10 candles
            idx = current_idx - strategy_config.iron_2_range_reference_candles + j
            if idx >= 0 and idx < len(spx_ohlc_data):
                high = spx_ohlc_data.iloc[idx]['high']
                low = spx_ohlc_data.iloc[idx]['low']
                last_10_ranges.append(high - low)
        
        if len(last_2_ranges) == strategy_config.iron_2_range_recent_candles and len(last_10_ranges) == strategy_config.iron_2_range_reference_candles:
            avg_last_2 = np.mean(last_2_ranges)
            avg_last_10 = np.mean(last_10_ranges)
            threshold = avg_last_10 * strategy_config.iron_2_range_threshold  # 125%
            
            signals['range_condition'] = avg_last_2 <= threshold
            signals['details']['avg_last_2_range'] = avg_last_2
            signals['details']['avg_last_10_range'] = avg_last_10
            signals['details']['range_threshold'] = threshold
            signals['details']['range_ratio'] = avg_last_2 / avg_last_10 if avg_last_10 > 0 else 0
        
        # Both conditions must be met
        signals['entry_signal'] = signals['direction_condition'] and signals['range_condition']
        
        return signals

   

    @staticmethod
    async def _find_iron_butterfly_strikes(current_price: float,
                                         timestamp: datetime,
                                         strategy: StrategyConfig,
                                         data_provider: Union[MockDataProvider, PolygonDataProvider],
                                         tolerance: float = 0.05) -> Optional[Dict[str, float]]:
        """
        Find Iron Butterfly strikes: sell ATM call/put, buy equidistant long calls/puts
        Target win:loss ratio of 1.5:1
        """
        # ATM strikes (same for both call and put in Iron Butterfly)
        atm_strike = int(round(current_price / 5) * 5)
        
        min_wing = getattr(strategy, 'min_wing_width', 10)
        max_wing = getattr(strategy, 'max_wing_width', 50)
        step = 5
        target_ratio = getattr(strategy, 'iron_2_target_win_loss_ratio', 1.5)
        
        distances = list(range(min_wing, max_wing + 1, step))
        
        logger.info(f"Searching Iron Butterfly strikes for ATM {atm_strike} with {len(distances)} wing distances...")
        
        # Get ATM quotes
        atm_call_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{atm_strike*1000:08d}"
        atm_put_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{atm_strike*1000:08d}"
        
        try:
            qsc, qsp = await asyncio.gather(
                data_provider._get_option_tick_quote(atm_call_symbol, timestamp),
                data_provider._get_option_tick_quote(atm_put_symbol, timestamp),
                return_exceptions=True
            )
            
            if isinstance(qsc, Exception) or isinstance(qsp, Exception) or None in [qsc, qsp]:
                logger.error("Failed to get ATM option quotes for Iron Butterfly")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching ATM quotes: {e}")
            return None
        
        # Prepare wing option symbols
        option_symbols = []
        symbol_to_distance = {}
        
        for d in distances:
            lc = atm_strike + d  # Long call strike
            lp = atm_strike - d  # Long put strike
            
            lc_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{lc*1000:08d}"
            lp_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{lp*1000:08d}"
            
            option_symbols.extend([lc_symbol, lp_symbol])
            symbol_to_distance[lc_symbol] = d
            symbol_to_distance[lp_symbol] = d
        
        # Fetch all wing quotes concurrently
        logger.info(f"Fetching {len(option_symbols)} wing option quotes...")
        
        try:
            quote_tasks = [
                data_provider._get_option_tick_quote(symbol, timestamp)
                for symbol in option_symbols
            ]
            
            all_quotes = await asyncio.gather(*quote_tasks, return_exceptions=True)
            
        except Exception as e:
            logger.error(f"Error fetching wing quotes: {e}")
            return None
        
        # Create quote lookup
        quote_lookup = {}
        failed_count = 0
        
        for i, symbol in enumerate(option_symbols):
            if i < len(all_quotes):
                quote = all_quotes[i]
                if isinstance(quote, Exception):
                    failed_count += 1
                elif quote is not None:
                    quote_lookup[symbol] = quote
                else:
                    failed_count += 1
        
        if failed_count > 0:
            logger.warning(f"Failed to fetch {failed_count} out of {len(option_symbols)} wing quotes")
        
        # Find best combination
        def get_premium(q, action):
            if q is None:
                return None
            return q.get('ask') if action == "long" else q.get('bid')
        
        best_combo = None
        best_diff = float('inf')
        valid_combos_checked = 0
        
        for d in distances:
            lc = atm_strike + d
            lp = atm_strike - d
            
            lc_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{lc*1000:08d}"
            lp_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{lp*1000:08d}"
            
            qlc = quote_lookup.get(lc_symbol)
            qlp = quote_lookup.get(lp_symbol)
            
            if None in [qsc, qsp, qlc, qlp]:
                continue
            
            # Calculate premiums (Iron Butterfly: sell ATM call/put, buy wing call/put)
            sc_mid = get_premium(qsc, "short")  # Sell ATM call
            sp_mid = get_premium(qsp, "short")  # Sell ATM put
            lc_mid = get_premium(qlc, "long")   # Buy wing call
            lp_mid = get_premium(qlp, "long")   # Buy wing put
            
            if None in [sc_mid, sp_mid, lc_mid, lp_mid]:
                continue
            
            valid_combos_checked += 1
            
            # Net credit calculation
            net_premium = sc_mid + sp_mid - lc_mid - lp_mid
            max_loss = d - net_premium  # Wing width minus net credit
            
            if net_premium <= 0 or max_loss <= 0:
                continue
            
            ratio = net_premium / max_loss
            diff = abs(ratio - target_ratio)
            
            if diff < best_diff:
                best_diff = diff
                best_combo = {
                    'short_call': atm_strike,    # ATM call (sold)
                    'short_put': atm_strike,     # ATM put (sold)
                    'long_call': lc,             # Wing call (bought)
                    'long_put': lp,              # Wing put (bought)
                    'net_premium': net_premium,
                    'max_loss': max_loss,
                    'ratio': ratio,
                    'distance': d
                }
                
                # Early termination for good match
                if diff <= tolerance:
                    logger.info(f"Found excellent Iron Butterfly match: Wing=${d}, "
                               f"Credit=${net_premium:.2f}, Ratio={ratio:.2f}")
                    break
        
        logger.info(f"Processed {valid_combos_checked} valid Iron Butterfly combinations")
        
        if best_combo:
            logger.info(f"Selected Iron Butterfly: ATM={atm_strike}, Wing=${best_combo['distance']}, "
                       f"Net Premium=${best_combo['net_premium']:.2f}, Ratio={best_combo['ratio']:.2f}")
            return best_combo
        else:
            logger.warning("No valid Iron Butterfly combination found")
            return None

    @staticmethod
    def _calculate_iron_butterfly_credit(quotes: Dict[str, Dict], contracts: Dict[str, str]) -> float:
        """Calculate net credit for Iron Butterfly"""
        total_credit = 0
        total_debit = 0
        
        # Short positions (sell at bid) - ATM call and put
        for leg in ['short_call', 'short_put']:
            contract = contracts[leg]
            if contract in quotes:
                price = quotes[contract]['bid']
                total_credit += price
        
        # Long positions (buy at ask) - Wing call and put
        for leg in ['long_call', 'long_put']:
            contract = contracts[leg]
            if contract in quotes:
                price = quotes[contract]['ask']
                total_debit += price
        
        return total_credit - total_debit

    @staticmethod
    async def _execute_iron_butterfly(quotes: Dict[str, Dict], entry_time: datetime,
                                    contracts: Dict[str, str], strategy: StrategyConfig,
                                    signals: Dict, net_premium: float, current_price: float,
                                    config: BacktestConfig) -> Optional[Trade]:
        """Execute Iron Butterfly trade"""
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing option quotes for Iron Butterfly, skipping trade")
            return None
        
        trade_contracts = {}
        strikes_dict = {}
        
        # Short positions (ATM call and put)
        for leg, contract in [('short_call', contracts['short_call']), 
                             ('short_put', contracts['short_put'])]:
            quote = quotes[contract]
            price = quote['bid']
            strike = int(contract[-8:]) / 1000
            strikes_dict[leg] = strike
            
            trade_contracts[contract] = {
                'position': -strategy.iron_2_trade_size,
                'entry_price': price,
                'leg_type': leg,
                'strike': strike,
                'used_capital': config.commission_per_contract
            }
        
        # Long positions (wing call and put)
        for leg, contract in [('long_call', contracts['long_call']), 
                             ('long_put', contracts['long_put'])]:
            quote = quotes[contract]
            price = quote['ask']
            strike = int(contract[-8:]) / 1000
            strikes_dict[leg] = strike
            
            trade_contracts[contract] = {
                'position': strategy.iron_2_trade_size,
                'entry_price': price,
                'leg_type': leg,
                'strike': strike,
                'used_capital': price * 100 + config.commission_per_contract
            }
        
        # Create representation string for Iron Butterfly
        representation = f"{strikes_dict['long_put']}/{strikes_dict['short_put']} {strikes_dict['short_call']}/{strikes_dict['long_call']} ({strikes_dict['short_put'] - strikes_dict['long_put']})"
        
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Iron Condor 2",
            contracts=trade_contracts,
            size=strategy.iron_2_trade_size,
            used_capital=0.0,
            metadata={
                'net_premium': net_premium,
                'strategy_name': 'iron_2',
                'entry_spx_price': current_price,
                'representation': representation,
                'butterfly_type': 'iron_butterfly',
                'wing' : strikes_dict['short_put'] - strikes_dict['long_put']
            }
        )
        
        return trade

    @staticmethod
    def _create_option_contracts(strikes: Dict[str, float], expiration: datetime) -> Dict[str, str]:
        """Create option contract symbols for Iron Butterfly"""
        exp_str = expiration.strftime('%y%m%d')
        
        contracts = {
            'short_call': f"O:SPXW{exp_str}C{int(strikes['short_call']*1000):08d}",
            'short_put': f"O:SPXW{exp_str}P{int(strikes['short_put']*1000):08d}",
            'long_call': f"O:SPXW{exp_str}C{int(strikes['long_call']*1000):08d}",
            'long_put': f"O:SPXW{exp_str}P{int(strikes['long_put']*1000):08d}"
        }
        
        return contracts

    @staticmethod
    async def _find_iron_trade(spx_ohlc_data: pd.DataFrame, 
                              i: int, strategy: StrategyConfig, date: datetime,
                              current_price: float, current_bar_time: datetime,
                              data_provider: Union[MockDataProvider, PolygonDataProvider],
                              config: BacktestConfig, 
                              iron1_trade: Trade = None) -> Optional[Trade]:
        """
        Find Iron Butterfly (Iron 2) trade based on strategy config and existing Iron 1 trades
        """
        
        # Check if price triggers Iron 2 entry based on Iron 1 positions
        if not IronCondor2._check_iron2_trigger_price(current_price, iron1_trade, strategy):
            return None
        
        # Check Iron 2 specific entry conditions
        signals = IronCondor2._check_iron2_entry_conditions(spx_ohlc_data, i, strategy)
        
        if not signals['entry_signal']:
            return None
        
        logger.info(f"Iron 2 entry conditions met at {current_bar_time}")
        
        # Find optimal Iron Butterfly strikes
        if isinstance(date, datetime):
            option_date = date
        else:
            option_date = datetime.combine(date, datetime.min.time())
        

        ib_result = await IronCondor2._find_iron_butterfly_strikes(
            current_price, current_bar_time, strategy, data_provider, 
        )
        
        if not ib_result:
            return None
        
        # Create Iron Butterfly strikes dictionary
        ib_strikes = {
            'short_call': ib_result['short_call'],
            'short_put': ib_result['short_put'],
            'long_call': ib_result['long_call'],
            'long_put': ib_result['long_put']
        }
        
        # Create option contracts and get quotes
        ib_contracts = IronCondor2._create_option_contracts(ib_strikes, option_date)
        ib_quotes = await data_provider.get_option_quotes(
            list(ib_contracts.values()), current_bar_time
        )
        
        # Calculate net premium
        net_premium = IronCondor2._calculate_iron_butterfly_credit(ib_quotes, ib_contracts)
        
        if net_premium <= 0:
            logger.warning(f"Iron Butterfly net premium not positive: {net_premium}")
            return None
        
        # Execute Iron Butterfly trade
        ib_trade = await IronCondor2._execute_iron_butterfly(
            ib_quotes, current_bar_time, ib_contracts, strategy,
            signals, net_premium, current_price, config
        )
        
        if ib_trade:
            logger.info(f"Entered Iron Butterfly (Iron 2) at {current_bar_time}: {ib_strikes}")
            
        return ib_trade