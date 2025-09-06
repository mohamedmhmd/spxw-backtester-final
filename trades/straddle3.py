from datetime import datetime
from typing import Optional, Dict, Any, Union
import logging

from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Straddle3:
    """
    Straddle 3 implementation with two variants:
    - Straddle 3(a): Linked to Iron 3(a)
    - Straddle 3(b): Linked to Iron 3(b)
    """
    
    Straddle3a_exited = False  # Class variable to track if straddle 3(a) has been exited
    Straddle3b_exited = False  # Class variable to track if straddle 3(b) has been exited
    
    @staticmethod
    def _determine_straddle3a_strikes(iron2_trade: Trade, iron3_trade: Trade,
                                     straddle1_trade: Trade, strategy: StrategyConfig) -> Dict[str, Any]:
        """
        Determine Straddle 3(a) strikes based on Iron positions.
        
        Entry rules:
        - If Iron 3 strike > Iron 2 strike: buy same call as Straddle 1
        - If Iron 3 strike < Iron 2 strike: buy same put as Straddle 1
        - For other option: buy at Iron 2 short strikes +/- 100% Iron 2 net premium
          (opposite direction of other straddle 3(a) trade, furthest from Iron 3 short strikes)
        """
        # Get Iron 2 details (Iron Butterfly - ATM strike)
        iron2_net_premium = iron2_trade.metadata.get('net_premium', 0)
        iron2_atm_strike = None
        for contract_data in iron2_trade.contracts.values():
            if contract_data['leg_type'] in ['short_call', 'short_put']:
                iron2_atm_strike = contract_data['strike']
                break
        
        # Get Iron 3(a) ATM strike (Iron Butterfly)
        iron3_atm_strike = None
        for contract_data in iron3_trade.contracts.values():
            if contract_data['leg_type'] in ['short_call', 'short_put']:
                iron3_atm_strike = contract_data['strike']
                break
        
        # Get Straddle 1 strikes
        straddle1_call_strike = straddle1_trade.metadata.get('call_straddle_strike')
        straddle1_put_strike = straddle1_trade.metadata.get('put_straddle_strike')
        
        # Get offset multiplier (default 100% = 1.0)
        offset_multiplier = getattr(strategy, 'straddle_3_trigger_multiplier', 1.0)
        offset_distance = iron2_net_premium * offset_multiplier
        
        # Determine which leg to copy from Straddle 1
        if iron3_atm_strike > iron2_atm_strike:
            # Iron 3 is higher - use same call as Straddle 1
            straddle3_call_strike = straddle1_call_strike
            
            # For put: buy at Iron 2 +/- offset (opposite direction, furthest from Iron 3)
            put_option_above = iron2_atm_strike + offset_distance
            put_option_below = iron2_atm_strike - offset_distance
            
            # Choose the option furthest from Iron 3 strikes
            if straddle3_call_strike >= iron3_atm_strike:
                chosen_put_strike = put_option_below
            else:
                chosen_put_strike = put_option_above
            
            straddle3_put_strike = round(chosen_put_strike / 5) * 5
            
        else:
            # Iron 3 is lower - use same put as Straddle 1
            straddle3_put_strike = straddle1_put_strike
            
            # For call: buy at Iron 2 +/- offset (opposite direction, furthest from Iron 3)
            call_option_above = iron2_atm_strike + offset_distance
            call_option_below = iron2_atm_strike - offset_distance
            
            # Choose the option furthest from Iron 3 strikes
            if straddle3_put_strike >= iron3_atm_strike:
                chosen_call_strike = call_option_below
            else:
                chosen_call_strike = call_option_above
            
            straddle3_call_strike = round(chosen_call_strike / 5) * 5
        
        return {
            'call_strike': int(straddle3_call_strike),
            'put_strike': int(straddle3_put_strike),
            'iron2_net_premium': iron2_net_premium,
            'iron2_atm_strike': iron2_atm_strike,
            'iron3_atm_strike': iron3_atm_strike,
            'straddle1_call_strike': straddle1_call_strike,
            'straddle1_put_strike': straddle1_put_strike,
            'offset_distance': offset_distance
        }
    
    @staticmethod
    def _determine_straddle3b_strikes(iron1_trade: Trade, iron2_trade: Trade, iron3_trade: Trade,
                                     straddle1_trade: Trade, strategy: StrategyConfig) -> Dict[str, Any]:
        """
        Determine Straddle 3(b) strikes based on Iron positions.
        
        Entry rules:
        - If Iron 3(b) short strikes < Iron 1 short strike: buy same put as Straddle 1
        - Otherwise: buy same call as Straddle 1
        - For other option: buy at Iron 2 short strikes +/- 100% Iron 2 net premium
          (direction further away from Iron 2 short strikes)
        """
        # Get Iron 1 center strike
        iron1_short_call = None
        iron1_short_put = None
        for contract_data in iron1_trade.contracts.values():
            if contract_data['leg_type'] == 'short_call':
                iron1_short_call = contract_data['strike']
            elif contract_data['leg_type'] == 'short_put':
                iron1_short_put = contract_data['strike']
        iron1_center = (iron1_short_call + iron1_short_put) / 2 if iron1_short_call and iron1_short_put else None
        
        # Get Iron 2 details (Iron Butterfly - ATM strike)
        iron2_net_premium = iron2_trade.metadata.get('net_premium', 0)
        iron2_atm_strike = None
        for contract_data in iron2_trade.contracts.values():
            if contract_data['leg_type'] in ['short_call', 'short_put']:
                iron2_atm_strike = contract_data['strike']
                break
        
        # Get Iron 3(b) ATM strike (Iron Condor - sells ATM)
        iron3_atm_strike = None
        for contract_data in iron3_trade.contracts.values():
            if contract_data['leg_type'] in ['short_call', 'short_put']:
                iron3_atm_strike = contract_data['strike']
                break
        
        # Get Straddle 1 strikes
        straddle1_call_strike = straddle1_trade.metadata.get('call_straddle_strike')
        straddle1_put_strike = straddle1_trade.metadata.get('put_straddle_strike')
        
        # Get offset multiplier (same parameter as 3a)
        offset_multiplier = getattr(strategy, 'straddle_3_trigger_multiplier', 1.0)
        offset_distance = iron2_net_premium * offset_multiplier
        
        # Determine which leg to copy from Straddle 1
        if iron3_atm_strike < iron1_center:
            # Iron 3(b) is lower than Iron 1 - use same put as Straddle 1
            straddle3_put_strike = straddle1_put_strike
            
            # For call: buy at Iron 2 +/- offset (further from Iron 2)
            call_option_above = iron2_atm_strike + offset_distance
            call_option_below = iron2_atm_strike - offset_distance
            
            # Choose the option further from Iron 2
            if straddle3_put_strike >= iron2_atm_strike:
                chosen_call_strike = call_option_below
            else:
                chosen_call_strike = call_option_above
            
            straddle3_call_strike = round(chosen_call_strike / 5) * 5
            
        else:
            # Iron 3(b) is higher or equal - use same call as Straddle 1
            straddle3_call_strike = straddle1_call_strike
            
            # For put: buy at Iron 2 +/- offset (further from Iron 2)
            put_option_above = iron2_atm_strike + offset_distance
            put_option_below = iron2_atm_strike - offset_distance
            
            # Choose the option further from Iron 2
            if straddle3_call_strike >= iron2_atm_strike:
                chosen_put_strike = put_option_below
            else:
                chosen_put_strike = put_option_above
            
            straddle3_put_strike = round(chosen_put_strike / 5) * 5
        
        return {
            'call_strike': int(straddle3_call_strike),
            'put_strike': int(straddle3_put_strike),
            'iron1_center': iron1_center,
            'iron2_net_premium': iron2_net_premium,
            'iron2_atm_strike': iron2_atm_strike,
            'iron3_atm_strike': iron3_atm_strike,
            'straddle1_call_strike': straddle1_call_strike,
            'straddle1_put_strike': straddle1_put_strike,
            'offset_distance': offset_distance
        }
    
    @staticmethod
    async def _execute_straddle3a(date: datetime, entry_time: datetime,
                                 current_price: float, strategy: StrategyConfig,
                                 iron2_trade: Trade,
                                 iron3_trade: Trade, straddle1_trade: Trade,
                                 data_provider: Union[MockDataProvider, PolygonDataProvider],
                                 config: BacktestConfig) -> Optional[Trade]:
        """Execute Straddle 3(a) trade - enters at same time as Iron 3(a)"""
        Straddle3.Straddle3a_exited = False
        
        # Determine strike prices
        strike_info = Straddle3._determine_straddle3a_strikes(
            iron2_trade, iron3_trade, straddle1_trade, strategy
        )
        
        call_strike = strike_info['call_strike']
        put_strike = strike_info['put_strike']
        
        # Create straddle contracts
        exp_str = date.strftime('%y%m%d')
        contracts = {
            'long_straddle_call': f"O:SPXW{exp_str}C{call_strike*1000:08d}",
            'long_straddle_put': f"O:SPXW{exp_str}P{put_strike*1000:08d}"
        }
        
        # Get quotes
        quotes = await data_provider.get_option_quotes(list(contracts.values()), entry_time)
        
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing straddle 3(a) quotes, skipping trade")
            return None
        
        # Build trade positions (buy both legs)
        trade_contracts = {}
        net_premium = 0
        strikes_dict = {}
        
        # Get trade size
        trade_size = getattr(strategy, 'straddle_3_trade_size', 2)
        
        for leg, contract in contracts.items():
            quote = quotes[contract]
            price = quote['ask']  # Buying at ask
            
            if 'call' in leg:
                straddle_strike = call_strike
            else:  # put
                straddle_strike = put_strike
            strikes_dict[leg] = straddle_strike
            
            trade_contracts[contract] = {
                'position': trade_size,  # Long position
                'entry_price': price,
                'leg_type': leg,
                'strike': straddle_strike,
                'remaining_position': "100%",  # Track for partial exits
                'used_capital': price * 100 + config.commission_per_contract,
                'exited': False  # Track if partially exited
            }
            net_premium += price
        
        representation = f"{strikes_dict['long_straddle_put']}/{strikes_dict['long_straddle_call']}"
        
        # Get exit parameters from strategy config
        exit_percentage = getattr(strategy, 'straddle_3_exit_percentage', 0.5)  # 50%
        exit_multiplier = getattr(strategy, 'straddle_3_exit_multiplier', 2.0)  # 2x
        
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Straddle 3(a)",
            contracts=trade_contracts,
            size=trade_size,
            entry_signals={'triggered_by': 'iron_3a', 'entered_with': 'iron_3a'},
            used_capital=0.0,
            metadata={
                'strategy_name': 'straddle_3a',
                'iron2_trade_ref': iron2_trade,
                'iron3_trade_ref': iron3_trade,
                'straddle1_trade_ref': straddle1_trade,
                'call_straddle_strike': call_strike,
                'put_straddle_strike': put_strike,
                'net_premium': net_premium,
                'exit_percentage': exit_percentage,
                'exit_multiplier': exit_multiplier,
                'entry_spx_price': current_price,
                'representation': representation,
                'strike_calculation_details': strike_info,
                'partial_pnl': 0.0  # Initialize to track partial exits
            }
        )
        
        logger.info(f"Entered Straddle 3(a) at {entry_time}: Call={call_strike}, Put={put_strike}, "
                   f"Net Premium=${net_premium:.2f}")
        
        return trade
    
    @staticmethod
    async def _execute_straddle3b(date: datetime, entry_time: datetime,
                                 current_price: float, strategy: StrategyConfig,
                                 iron1_trade: Trade, iron2_trade: Trade,
                                 iron3_trade: Trade, straddle1_trade: Trade,
                                 data_provider: Union[MockDataProvider, PolygonDataProvider],
                                 config: BacktestConfig) -> Optional[Trade]:
        """Execute Straddle 3(b) trade - enters at same time as Iron 3(b)"""
        Straddle3.Straddle3b_exited = False
        
        # Determine strike prices
        strike_info = Straddle3._determine_straddle3b_strikes(
            iron1_trade, iron2_trade, iron3_trade, straddle1_trade, strategy
        )
        
        call_strike = strike_info['call_strike']
        put_strike = strike_info['put_strike']
        
        # Create straddle contracts
        exp_str = date.strftime('%y%m%d')
        contracts = {
            'long_straddle_call': f"O:SPXW{exp_str}C{call_strike*1000:08d}",
            'long_straddle_put': f"O:SPXW{exp_str}P{put_strike*1000:08d}"
        }
        
        # Get quotes
        quotes = await data_provider.get_option_quotes(list(contracts.values()), entry_time)
        
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing straddle 3(b) quotes, skipping trade")
            return None
        
        # Build trade positions (buy both legs)
        trade_contracts = {}
        net_premium = 0
        strikes_dict = {}
        
        # Get trade size
        trade_size = getattr(strategy, 'straddle_3_trade_size', 2)
        
        for leg, contract in contracts.items():
            quote = quotes[contract]
            price = quote['ask']  # Buying at ask
            
            if 'call' in leg:
                straddle_strike = call_strike
            else:  # put
                straddle_strike = put_strike
            strikes_dict[leg] = straddle_strike
            
            trade_contracts[contract] = {
                'position': trade_size,  # Long position
                'entry_price': price,
                'leg_type': leg,
                'strike': straddle_strike,
                'remaining_position': "100%",  # Track for partial exits
                'used_capital': price * 100 + config.commission_per_contract,
                'exited': False  # Track if partially exited
            }
            net_premium += price
        
        representation = f"{strikes_dict['long_straddle_put']}/{strikes_dict['long_straddle_call']}"
        
        # Get exit parameters from strategy config (same as 3a)
        exit_percentage = getattr(strategy, 'straddle_3_exit_percentage', 0.5)  # 50%
        exit_multiplier = getattr(strategy, 'straddle_3_exit_multiplier', 2.0)  # 2x
        
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Straddle 3(b)",
            contracts=trade_contracts,
            size=trade_size,
            entry_signals={'triggered_by': 'iron_3b', 'entered_with': 'iron_3b'},
            used_capital=0.0,
            metadata={
                'strategy_name': 'straddle_3b',
                'iron1_trade_ref': iron1_trade,
                'iron2_trade_ref': iron2_trade,
                'iron3_trade_ref': iron3_trade,
                'straddle1_trade_ref': straddle1_trade,
                'call_straddle_strike': call_strike,
                'put_straddle_strike': put_strike,
                'net_premium': net_premium,
                'exit_percentage': exit_percentage,
                'exit_multiplier': exit_multiplier,
                'entry_spx_price': current_price,
                'representation': representation,
                'strike_calculation_details': strike_info,
                'partial_pnl': 0.0  # Initialize to track partial exits
            }
        )
        
        logger.info(f"Entered Straddle 3(b) at {entry_time}: Call={call_strike}, Put={put_strike}, "
                   f"Net Premium=${net_premium:.2f}")
        
        return trade
    
    @staticmethod
    async def _check_straddle_exits(straddle: Trade, current_price: float,
                                   current_time: datetime, config: BacktestConfig,
                                   data_provider: Union[MockDataProvider, PolygonDataProvider]) -> None:
        """Check if any Straddle 3 positions should be partially exited."""
        # Ensure metadata exists
        if straddle.metadata is None:
            straddle.metadata = {}
        
        call_straddle_strike = straddle.metadata.get("call_straddle_strike")
        put_straddle_strike = straddle.metadata.get("put_straddle_strike")
        exit_percentage = straddle.metadata.get("exit_percentage", 0.5)
        exit_multiplier = straddle.metadata.get("exit_multiplier", 2.0)
        
        # Check if strike is hit
        call_hit = current_price >= call_straddle_strike if call_straddle_strike else False
        put_hit = current_price <= put_straddle_strike if put_straddle_strike else False
        
        if not (call_hit or put_hit):
            return
        
        if call_hit:
            leg_type = "call"
        else:
            leg_type = "put"
        
        for contract, details in straddle.contracts.items():
            if leg_type not in details["leg_type"]:
                continue
            
            # Skip if already exited
            if details.get("exited", False):
                continue
            
            entry_price = details["entry_price"]  # raw option price (not *100)
            
            # Get current quote
            quotes = await data_provider.get_option_quotes([contract], current_time)
            if contract not in quotes:
                continue
            
            current_quote = quotes[contract]
            exit_price = current_quote["bid"]  # raw option price
            
            # Exit condition: price is 2x or more the original price
            if exit_price >= entry_price * exit_multiplier:
                exit_size = exit_percentage
                
                if exit_size <= 0:
                    continue
                
                # Calculate partial P&L (SPX = 100× multiplier)
                partial_pnl = (exit_price - entry_price) * exit_size * 100 * details['position']
                # Apply exit commission
                partial_pnl -= config.commission_per_contract * exit_size
                details["used_capital"] += config.commission_per_contract * exit_size
                
                # Update position
                remaining_pct = (1 - exit_size) * 100
                details["remaining_position"] = f"{remaining_pct:.1f}%"
                details["exited"] = True
                
                # Update running P&L at trade level
                current_partial_pnl = straddle.metadata.get("partial_pnl", 0.0)
                straddle.metadata["partial_pnl"] = current_partial_pnl + partial_pnl
                straddle.contracts[contract] = details
                
                # Set appropriate exit flag
                if "3(a)" in straddle.trade_type:
                    Straddle3.Straddle3a_exited = True
                else:
                    Straddle3.Straddle3b_exited = True
                
                logger.info(
                    f"Partial {straddle.trade_type} exit: {leg_type.upper()} at ${exit_price:.2f} "
                    f"(entry: ${entry_price:.2f}, x{exit_multiplier:.1f}), "
                    f"Size: {exit_size}, P&L: ${partial_pnl:.2f}"
                )
    
    @staticmethod
    async def _execute_straddle(date: datetime, entry_time: datetime,
                               current_price: float, strategy: StrategyConfig,
                               iron1_trade: Trade, iron2_trade: Trade,
                               iron3_trade: Trade, straddle1_trade: Trade,
                               data_provider: Union[MockDataProvider, PolygonDataProvider],
                               config: BacktestConfig, trade_type: str) -> Optional[Trade]:
        """Main entry point to execute Straddle 3 trades"""
        if "3(a)" in trade_type:
            return await Straddle3._execute_straddle3a(
                date, entry_time, current_price, strategy,
                iron1_trade, iron2_trade, iron3_trade, straddle1_trade,
                data_provider, config
            )
        else:  # 3(b)
            return await Straddle3._execute_straddle3b(
                date, entry_time, current_price, strategy,
                iron1_trade, iron2_trade, iron3_trade, straddle1_trade,
                data_provider, config
            )