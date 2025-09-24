from datetime import datetime
from typing import Any, Dict, Optional, Union
import logging
import numpy as np
import pandas as pd
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
import asyncio

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IronCondor3:
    """
    Iron Condor 3 implementation with two variants:
    - Iron 3(a): Iron Butterfly when price moves further from Iron 1
    - Iron 3(b): Iron Condor when price moves back towards Iron 1
    """
    
    @staticmethod
    def _check_iron3a_trigger_price(current_price: float, iron1_trade: Trade, iron2_trade: Trade, 
                                   strategy_config: StrategyConfig) -> bool:
        """
        Check if current price triggers Iron 3(a) entry.
        Trigger: SPX moves to Iron 2 short strike +/- 100% of Iron 2 net premium
        """
                # Get Iron 1 trade details
        iron_1_net_premium = iron1_trade.metadata.get('net_premium', 0)
            
        # Find short strikes from trade contracts
        iron_1_short_strike = None
        
        for contract_symbol, contract_data in iron1_trade.contracts.items():
            if contract_data['leg_type'] == 'short_call':
                iron_1_short_strike = contract_data['strike']
                break
                
        d = iron_1_short_strike - iron_1_net_premium
        u = iron_1_short_strike + iron_1_net_premium
        
        if current_price >= d and current_price <= u:
            return False
        
        iron2_net_premium = iron2_trade.metadata.get('net_premium', 0)
        
        # Iron 2 is an Iron Butterfly, so both shorts are at same ATM strike
        iron2_atm_strike = None
        for contract_data in iron2_trade.contracts.values():
            if contract_data['leg_type'] in ['short_call', 'short_put']:
                iron2_atm_strike = contract_data['strike']
                break
        
        if iron2_atm_strike is None:
            return False
        
        # Calculate trigger prices
        trigger_multiplier = getattr(strategy_config, 'iron_3_trigger_multiplier', 1.0)
        upper_trigger = iron2_atm_strike + trigger_multiplier * iron2_net_premium
        lower_trigger = iron2_atm_strike - trigger_multiplier * iron2_net_premium
        
        if current_price >= upper_trigger or current_price <= lower_trigger:
            logger.info(f"Iron 3(a) trigger price reached: {current_price:.2f} "
                       f"(triggers: {lower_trigger:.2f} - {upper_trigger:.2f})")
            return True
        
        return False
    
    @staticmethod
    def _check_iron3b_trigger_price(current_price: float, iron1_trade: Trade,
                                   iron2_trade: Trade, strategy_config: StrategyConfig) -> bool:
        """
        Check if current price triggers Iron 3(b) entry.
        Trigger: SPX moves back, crosses Iron 1, reaches Iron 1 strike +/- 100% of Iron 1 premium
        (in opposite direction from Iron 2)
        """
        iron1_net_premium = iron1_trade.metadata.get('net_premium', 0)
        
        # Get Iron 1 strikes
        iron1_short_strike = None
        for contract_data in iron1_trade.contracts.values():
            if contract_data['leg_type'] == 'short_call':
                iron1_short_strike = contract_data['strike']
        
        # Get Iron 2 ATM strike to determine direction
        iron2_atm_strike = None
        for contract_data in iron2_trade.contracts.values():
            if contract_data['leg_type'] in ['short_call', 'short_put']:
                iron2_atm_strike = contract_data['strike']
                break
        
        trigger_multiplier = getattr(strategy_config, 'iron_3_trigger_multiplier', 1.0)
        
        # Determine which trigger to check (opposite direction from Iron 2)
        if iron2_atm_strike > iron1_short_strike:
            # Iron 2 was set above, so Iron 3(b) triggers below
            trigger_price = iron1_short_strike - trigger_multiplier * iron1_net_premium
            if current_price <= trigger_price:
                logger.info(f"Iron 3(b) trigger price reached: {current_price:.2f} "
                           f"(trigger: {trigger_price:.2f})")
                return True
        else:
            # Iron 2 was set below, so Iron 3(b) triggers above
            trigger_price = iron1_short_strike + trigger_multiplier * iron1_net_premium
            if current_price >= trigger_price:
                logger.info(f"Iron 3(b) trigger price reached: {current_price:.2f} "
                           f"(trigger: {trigger_price:.2f})")
                return True
        
        return False
    
    @staticmethod
    def _check_iron3_entry_conditions(spx_ohlc_data: pd.DataFrame, current_idx: int,
                                     strategy_config: StrategyConfig) -> Dict[str, Any]:
        """
        Check Iron 3 entry conditions (same for both 3a and 3b):
        1) Last four 5-minute candles not all in same direction
        2) Average range of last two candles <= 125% of average of last ten candles
        """
        signals = {
            'entry_signal': False,
            'direction_condition': False,
            'range_condition': False,
            'details': {}
        }
        
        # Get parameters with defaults
        direction_lookback = getattr(strategy_config, 'iron_3_direction_lookback', 4)
        range_recent = getattr(strategy_config, 'iron_3_range_recent_candles', 2)
        range_reference = getattr(strategy_config, 'iron_3_range_reference_candles', 10)
        range_threshold_mult = getattr(strategy_config, 'iron_3_range_threshold', 1.25)
        
        # Ensure sufficient data
        if current_idx < range_reference:
            return signals
        
        # Condition 1: Direction check
        directions = []
        for j in range(direction_lookback):
            idx = current_idx - direction_lookback + j
            if idx >= 0 and idx < len(spx_ohlc_data):
                open_price = spx_ohlc_data.iloc[idx]['open']
                close_price = spx_ohlc_data.iloc[idx]['close']
                directions.append(1 if close_price > open_price else -1)
        
        if len(directions) == direction_lookback:
            all_same = all(d == directions[0] for d in directions)
            signals['direction_condition'] = not all_same
            signals['details']['directions'] = directions
            if all_same:
                return signals
        
        # Condition 2: Range check
        recent_ranges = []
        for j in range(range_recent):
            idx = current_idx - range_recent + j
            if idx >= 0 and idx < len(spx_ohlc_data):
                high = spx_ohlc_data.iloc[idx]['high']
                low = spx_ohlc_data.iloc[idx]['low']
                recent_ranges.append(high - low)
        
        reference_ranges = []
        for j in range(range_reference):
            idx = current_idx - range_reference + j
            if idx >= 0 and idx < len(spx_ohlc_data):
                high = spx_ohlc_data.iloc[idx]['high']
                low = spx_ohlc_data.iloc[idx]['low']
                reference_ranges.append(high - low)
        
        if len(recent_ranges) == range_recent and len(reference_ranges) == range_reference:
            avg_recent = np.mean(recent_ranges)
            avg_reference = np.mean(reference_ranges)
            threshold = avg_reference * range_threshold_mult
            
            signals['range_condition'] = avg_recent <= threshold
            signals['details']['avg_recent_range'] = avg_recent
            signals['details']['avg_reference_range'] = avg_reference
            signals['details']['range_threshold'] = threshold
        
        signals['entry_signal'] = signals['direction_condition'] and signals['range_condition']
        
        return signals
    
    @staticmethod
    def _check_minimum_distance_iron3a(current_price: float, iron2_trade: Trade,
                                      iron1_trade: Trade, strategy_config: StrategyConfig) -> bool:
        """
        Ensure Iron 3(a) is not too close to Iron 2 short strikes +/- 100% of Iron 1 net premium
        """
        iron1_net_premium = iron1_trade.metadata.get('net_premium', 0)
        
        # Get Iron 2 ATM strike
        iron2_atm_strike = None
        for contract_data in iron2_trade.contracts.values():
            if contract_data['leg_type'] in ['short_call', 'short_put']:
                iron2_atm_strike = contract_data['strike']
                break
        
        if iron2_atm_strike is None:
            return False
        
        # Calculate exclusion zone
        multiplier = getattr(strategy_config, 'iron_3_distance_multiplier', 1.0)
        upper_boundary = iron2_atm_strike + multiplier * iron1_net_premium
        lower_boundary = iron2_atm_strike - multiplier * iron1_net_premium
        
        min_distance = getattr(strategy_config, 'iron_3_min_distance', 5)
        
        if (abs(current_price - upper_boundary) < min_distance or 
            abs(current_price - lower_boundary) < min_distance):
            logger.info(f"Iron 3(a) too close to Iron 2 boundaries: {current_price:.2f}")
            return False
        
        return True
    
    @staticmethod
    def _check_minimum_distance_iron3b(current_price: float, iron1_trade: Trade,
                                      strategy_config: StrategyConfig) -> bool:
        """
        Ensure Iron 3(b) is not too close to Iron 1 short strikes +/- 100% of Iron 1 net premium
        """
        iron1_net_premium = iron1_trade.metadata.get('net_premium', 0)
        
        # Get Iron 1 strikes
        iron1_short_call = None
        iron1_short_put = None
        for contract_data in iron1_trade.contracts.values():
            if contract_data['leg_type'] == 'short_call':
                iron1_short_call = contract_data['strike']
            elif contract_data['leg_type'] == 'short_put':
                iron1_short_put = contract_data['strike']
        
        if None in [iron1_short_call, iron1_short_put]:
            return False
        
        # Calculate exclusion zones
        multiplier = getattr(strategy_config, 'iron_3_distance_multiplier', 1.0)
        upper_boundary = iron1_short_call + multiplier * iron1_net_premium
        lower_boundary = iron1_short_put - multiplier * iron1_net_premium
        
        min_distance = getattr(strategy_config, 'iron_3_min_distance', 5)
        
        if (abs(current_price - upper_boundary) < min_distance or 
            abs(current_price - lower_boundary) < min_distance):
            logger.info(f"Iron 3(b) too close to Iron 1 boundaries: {current_price:.2f}")
            return False
        
        return True
    
    @staticmethod
    async def _find_iron_butterfly_strikes(current_price: float, timestamp: datetime,
                                          strategy: StrategyConfig,
                                          data_provider: Union[MockDataProvider, PolygonDataProvider],
                                          tolerance: float = 0.05) -> Optional[Dict[str, float]]:
        """Find Iron Butterfly strikes for Iron 3(a)"""
        atm_strike = int(round(current_price / 5) * 5)
        
        min_wing = getattr(strategy, 'min_wing_width')
        max_wing = getattr(strategy, 'max_wing_width')
        step = 5
        target_ratio = getattr(strategy, 'iron_3_target_win_loss_ratio', 1.5)
        
        distances = list(range(min_wing, max_wing + 1, step))
        
        logger.info(f"Searching Iron 3(a) Butterfly strikes for ATM {atm_strike}")
        
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
                logger.error("Failed to get ATM quotes for Iron 3(a)")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching ATM quotes: {e}")
            return None
        
        # Prepare and fetch wing options
        option_symbols = []
        for d in distances:
            lc_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{(atm_strike + d)*1000:08d}"
            lp_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{(atm_strike - d)*1000:08d}"
            option_symbols.extend([lc_symbol, lp_symbol])
        
        try:
            all_quotes = await asyncio.gather(
                *[data_provider._get_option_tick_quote(s, timestamp) for s in option_symbols],
                return_exceptions=True
            )
        except Exception as e:
            logger.error(f"Error fetching wing quotes: {e}")
            return None
        
        # Create quote lookup
        quote_lookup = {}
        for i, symbol in enumerate(option_symbols):
            if i < len(all_quotes) and not isinstance(all_quotes[i], Exception) and all_quotes[i]:
                quote_lookup[symbol] = all_quotes[i]
        
        # Find best combination
        best_combo = None
        best_diff = float('inf')
        
        for d in distances:
            lc_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{(atm_strike + d)*1000:08d}"
            lp_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{(atm_strike - d)*1000:08d}"
            
            qlc = quote_lookup.get(lc_symbol)
            qlp = quote_lookup.get(lp_symbol)
            
            if None in [qsc, qsp, qlc, qlp]:
                continue
            
            # Calculate premiums
            sc_bid = qsc.get('bid')
            sp_bid = qsp.get('bid')
            lc_ask = qlc.get('ask')
            lp_ask = qlp.get('ask')
            
            if None in [sc_bid, sp_bid, lc_ask, lp_ask]:
                continue
            
            net_premium = sc_bid + sp_bid - lc_ask - lp_ask
            max_loss = d - net_premium
            
            if net_premium <= 0 or max_loss <= 0:
                continue
            
            ratio = net_premium / max_loss
            diff = abs(ratio - target_ratio)
            
            if diff < best_diff:
                best_diff = diff
                best_combo = {
                    'short_call': atm_strike,
                    'short_put': atm_strike,
                    'long_call': atm_strike + d,
                    'long_put': atm_strike - d,
                    'net_premium': net_premium,
                    'max_loss': max_loss,
                    'ratio': ratio,
                    'distance': d
                }
                
                if diff <= tolerance:
                    break
        
        if best_combo:
            logger.info(f"Selected Iron 3(a) Butterfly: ATM={atm_strike}, Wing={best_combo['distance']}, "
                       f"Ratio={best_combo['ratio']:.2f}")
        
        return best_combo
    
    @staticmethod
    async def _find_iron_condor_strikes(current_price: float, timestamp: datetime,
                                       strategy: StrategyConfig,
                                       data_provider: Union[MockDataProvider, PolygonDataProvider],
                                       tolerance: float = 0.05) -> Optional[Dict[str, float]]:
        """Find Iron Condor strikes for Iron 3(b) - sells ATM, buys closest for 1.5:1 ratio"""
        atm_strike = int(round(current_price / 5) * 5)
        
        min_wing = getattr(strategy, 'iron_3b_min_wing_width', 5)
        max_wing = getattr(strategy, 'iron_3b_max_wing_width', 30)
        step = 5
        target_ratio = getattr(strategy, 'iron_3b_target_win_loss_ratio', 1.5)
        
        distances = list(range(min_wing, max_wing + 1, step))
        
        logger.info(f"Searching Iron 3(b) Condor strikes for ATM {atm_strike}")
        
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
                logger.error("Failed to get ATM quotes for Iron 3(b)")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching ATM quotes: {e}")
            return None
        
        # Prepare and fetch wing options
        option_symbols = []
        for d in distances:
            lc_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{(atm_strike + d)*1000:08d}"
            lp_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{(atm_strike - d)*1000:08d}"
            option_symbols.extend([lc_symbol, lp_symbol])
        
        try:
            all_quotes = await asyncio.gather(
                *[data_provider._get_option_tick_quote(s, timestamp) for s in option_symbols],
                return_exceptions=True
            )
        except Exception as e:
            logger.error(f"Error fetching wing quotes: {e}")
            return None
        
        # Create quote lookup
        quote_lookup = {}
        for i, symbol in enumerate(option_symbols):
            if i < len(all_quotes) and not isinstance(all_quotes[i], Exception) and all_quotes[i]:
                quote_lookup[symbol] = all_quotes[i]
        
        # Find best combination (preferring closest strikes that meet ratio)
        best_combo = None
        
        for d in distances:
            lc_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}C{(atm_strike + d)*1000:08d}"
            lp_symbol = f"O:SPXW{timestamp.strftime('%y%m%d')}P{(atm_strike - d)*1000:08d}"
            
            qlc = quote_lookup.get(lc_symbol)
            qlp = quote_lookup.get(lp_symbol)
            
            if None in [qsc, qsp, qlc, qlp]:
                continue
            
            # Calculate premiums
            sc_bid = qsc.get('bid')
            sp_bid = qsp.get('bid')
            lc_ask = qlc.get('ask')
            lp_ask = qlp.get('ask')
            
            if None in [sc_bid, sp_bid, lc_ask, lp_ask]:
                continue
            
            net_premium = sc_bid + sp_bid - lc_ask - lp_ask
            max_loss = d - net_premium
            
            if net_premium <= 0 or max_loss <= 0:
                continue
            
            ratio = net_premium / max_loss
            
            # For Iron 3(b), we want ratio >= target (1.5:1 or better)
            if ratio >= target_ratio:
                best_combo = {
                    'short_call': atm_strike,
                    'short_put': atm_strike,
                    'long_call': atm_strike + d,
                    'long_put': atm_strike - d,
                    'net_premium': net_premium,
                    'max_loss': max_loss,
                    'ratio': ratio,
                    'distance': d
                }
                break  # Take first (closest) that meets criteria
        
        if best_combo:
            logger.info(f"Selected Iron 3(b) Condor: ATM={atm_strike}, Wing={best_combo['distance']}, "
                       f"Ratio={best_combo['ratio']:.2f}")
        
        return best_combo
    
    @staticmethod
    def _create_option_contracts(strikes: Dict[str, float], expiration: datetime) -> Dict[str, str]:
        """Create option contract symbols"""
        exp_str = expiration.strftime('%y%m%d')
        
        contracts = {
            'short_call': f"O:SPXW{exp_str}C{int(strikes['short_call']*1000):08d}",
            'short_put': f"O:SPXW{exp_str}P{int(strikes['short_put']*1000):08d}",
            'long_call': f"O:SPXW{exp_str}C{int(strikes['long_call']*1000):08d}",
            'long_put': f"O:SPXW{exp_str}P{int(strikes['long_put']*1000):08d}"
        }
        
        return contracts
    
    @staticmethod
    def _calculate_net_credit(quotes: Dict[str, Dict], contracts: Dict[str, str]) -> float:
        """Calculate net credit for Iron structure"""
        total_credit = 0
        total_debit = 0
        
        for leg in ['short_call', 'short_put']:
            contract = contracts[leg]
            if contract in quotes:
                total_credit += quotes[contract]['bid']
        
        for leg in ['long_call', 'long_put']:
            contract = contracts[leg]
            if contract in quotes:
                total_debit += quotes[contract]['ask']
        
        return total_credit - total_debit
    
    @staticmethod
    async def _execute_iron_trade(quotes: Dict[str, Dict], entry_time: datetime,
                                 contracts: Dict[str, str], strategy: StrategyConfig,
                                 signals: Dict, net_premium: float, current_price: float,
                                 config: BacktestConfig, trade_type: str,
                                 strikes: Dict) -> Optional[Trade]:
        """Execute Iron 3(a) or 3(b) trade"""
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning(f"Missing option quotes for {trade_type}, skipping trade")
            return None
        
        trade_contracts = {}
        strikes_dict = {}
        
        # Determine trade size
        if '3(a)' in trade_type:
            trade_size = getattr(strategy, 'iron_3_trade_size', 10)
        else:
            trade_size = getattr(strategy, 'iron_3_trade_size', 10)
        
        # Short positions
        for leg, contract in [('short_call', contracts['short_call']), 
                             ('short_put', contracts['short_put'])]:
            quote = quotes[contract]
            price = quote['bid']
            strike = strikes[leg]
            strikes_dict[leg] = strike
            
            trade_contracts[contract] = {
                'position': -trade_size,
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
            strike = strikes[leg]
            strikes_dict[leg] = strike
            
            trade_contracts[contract] = {
                'position': trade_size,
                'entry_price': price,
                'leg_type': leg,
                'strike': strike,
                'used_capital': price * 100 + config.commission_per_contract
            }
        
        # Create representation
        if '3(a)' in trade_type:
            # Iron Butterfly format
            representation = f"{strikes_dict['long_put']}/{strikes_dict['short_put']} {strikes_dict['short_call']}/{strikes_dict['long_call']} ({strikes_dict['short_put'] - strikes_dict['long_put']})"
            structure_type = 'iron_butterfly'
        else:
            # Iron Condor format
            representation = f"{strikes_dict['long_put']}/{strikes_dict['short_put']}  {strikes_dict['short_call']}/{strikes_dict['long_call']} ({strikes_dict['short_put'] - strikes_dict['long_put']})"
            structure_type = 'iron_condor'
        
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type=trade_type,
            contracts=trade_contracts,
            size=trade_size,
            entry_signals=signals,
            used_capital=0.0,
            metadata={
                'net_premium': net_premium,
                'strategy_name': 'iron_3a' if '3(a)' in trade_type else 'iron_3b',
                'entry_spx_price': current_price,
                'representation': representation,
                'structure_type': structure_type,
                'no_exit': True,  # Flag to indicate no exit rules,
                'wing' : strikes_dict['short_put'] - strikes_dict['long_put']
            }
        )
        
        return trade
    
    @staticmethod
    async def _find_iron_trade(spx_ohlc_data: pd.DataFrame, i: int,
                              strategy: StrategyConfig, date: datetime,
                              current_price: float, current_bar_time: datetime,
                              data_provider: Union[MockDataProvider, PolygonDataProvider],
                              config: BacktestConfig,
                              iron1_trade: Optional[Trade] = None,
                              iron2_trade: Optional[Trade] = None,
                              iron3a_executed: bool = False) -> Optional[Trade]:
        """
        Find Iron 3(a) or 3(b) trade based on market conditions.
        Iron 3(a) takes precedence; Iron 3(b) only if no 3(a) executed.
        """
        
        # Check for Iron 3(a) first (if not already executed)
        if not iron3a_executed and iron2_trade:
            # Check trigger price
            if IronCondor3._check_iron3a_trigger_price(current_price, iron1_trade, iron2_trade, strategy):
                # Check minimum distance
                if IronCondor3._check_minimum_distance_iron3a(current_price, iron2_trade, iron1_trade, strategy):
                    # Check entry conditions
                    signals = IronCondor3._check_iron3_entry_conditions(spx_ohlc_data, i, strategy)
                    
                    if signals['entry_signal']:
                        logger.info(f"Iron 3(a) entry conditions met at {current_bar_time}")
                        
                        # Find Iron Butterfly strikes
                        if isinstance(date, datetime):
                            option_date = date
                        else:
                            option_date = datetime.combine(date, datetime.min.time())
                        
                        iron_result = await IronCondor3._find_iron_butterfly_strikes(
                            current_price, current_bar_time, strategy, data_provider
                        )
                        
                        if iron_result:
                            strikes = {
                                'short_call': iron_result['short_call'],
                                'short_put': iron_result['short_put'],
                                'long_call': iron_result['long_call'],
                                'long_put': iron_result['long_put']
                            }
                            
                            contracts = IronCondor3._create_option_contracts(strikes, option_date)
                            quotes = await data_provider.get_option_quotes(
                                list(contracts.values()), current_bar_time
                            )
                            
                            net_premium = IronCondor3._calculate_net_credit(quotes, contracts)
                            
                            if net_premium > 0:
                                trade = await IronCondor3._execute_iron_trade(
                                    quotes, current_bar_time, contracts, strategy,
                                    signals, net_premium, current_price, config,
                                    "Iron Condor 3(a)", strikes
                                )
                                
                                if trade:
                                    logger.info(f"Entered Iron 3(a) at {current_bar_time}: {strikes}")
                                    return trade
        
        # Check for Iron 3(b) only if no 3(a) has been executed
        if iron3a_executed:
            return None
        
        if iron1_trade and iron2_trade:
            # Check trigger price
            if IronCondor3._check_iron3b_trigger_price(current_price, iron1_trade, iron2_trade, strategy):
                # Check minimum distance
                if IronCondor3._check_minimum_distance_iron3b(current_price, iron1_trade, strategy):
                    # Check entry conditions
                    signals = IronCondor3._check_iron3_entry_conditions(spx_ohlc_data, i, strategy)
                    
                    if signals['entry_signal']:
                        logger.info(f"Iron 3(b) entry conditions met at {current_bar_time}")
                        
                        # Find Iron Condor strikes
                        if isinstance(date, datetime):
                            option_date = date
                        else:
                            option_date = datetime.combine(date, datetime.min.time())
                        
                        iron_result = await IronCondor3._find_iron_condor_strikes(
                            current_price, current_bar_time, strategy, data_provider
                        )
                        
                        if iron_result:
                            strikes = {
                                'short_call': iron_result['short_call'],
                                'short_put': iron_result['short_put'],
                                'long_call': iron_result['long_call'],
                                'long_put': iron_result['long_put']
                            }
                            
                            contracts = IronCondor3._create_option_contracts(strikes, option_date)
                            quotes = await data_provider.get_option_quotes(
                                list(contracts.values()), current_bar_time
                            )
                            
                            net_premium = IronCondor3._calculate_net_credit(quotes, contracts)
                            
                            if net_premium > 0:
                                trade = await IronCondor3._execute_iron_trade(
                                    quotes, current_bar_time, contracts, strategy,
                                    signals, net_premium, current_price, config,
                                    "Iron Condor 3(b)", strikes
                                )
                                
                                if trade:
                                    logger.info(f"Entered Iron 3(b) at {current_bar_time}: {strikes}")
                                    return trade
        
        return None