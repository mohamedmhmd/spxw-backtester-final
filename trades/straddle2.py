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


class Straddle2:
    
    Straddle2_exited = False  # Class variable to track if straddle has been exited
    
    @staticmethod
    def _determine_straddle_strikes(iron1_trade: Trade, iron2_trade: Trade, straddle1_trade: Trade,
                                   strategy: StrategyConfig) -> Dict[str, Any]:
        """
        Determine Straddle 2 strikes based on Iron 1 and Iron 2 positions.
        
        Entry rules:
        - If Iron 2 short strikes > Iron 1 short strikes: buy same call as Straddle 1
        - If Iron 2 short strikes < Iron 1 short strikes: buy same put as Straddle 1
        - For other option: buy at Iron 1 short strikes +/- 100% Iron 1 net premium
          (furthest away from the OTHER Straddle 2 leg and from Iron 2 short strikes)
        """
        # Get Iron 1 details
        iron1_net_premium = iron1_trade.metadata.get('net_premium', 0)
        iron1_short_call_strike = None
        iron1_short_put_strike = None
        
        for contract_data in iron1_trade.contracts.values():
            if contract_data['leg_type'] == 'short_call':
                iron1_short_call_strike = contract_data['strike']
            elif contract_data['leg_type'] == 'short_put':
                iron1_short_put_strike = contract_data['strike']
        
        # Get Iron 2 details (Iron Butterfly - both shorts at same ATM strike)
        iron2_atm_strike = None
        for contract_data in iron2_trade.contracts.values():
            if contract_data['leg_type'] in ['short_call', 'short_put']:
                iron2_atm_strike = contract_data['strike']
                break  # Both are at same strike for butterfly
        
        # Get Straddle 1 strikes
        straddle1_call_strike = straddle1_trade.metadata.get('call_straddle_strike')
        straddle1_put_strike = straddle1_trade.metadata.get('put_straddle_strike')
        
        # Calculate Iron 1 center for comparison
        iron1_center = (iron1_short_call_strike + iron1_short_put_strike) / 2
        
        # Get strike offset percentage parameter (default 100% = 1.0)
        # Note: Using straddle_2_trigger_multiplier as it represents the 100% parameter
        offset_percentage = getattr(strategy, 'straddle_2_trigger_multiplier', 1.0)
        offset_distance = iron1_net_premium * offset_percentage
        
        # Determine which leg to copy from Straddle 1 and calculate the other
        if iron2_atm_strike > iron1_center:
            # Iron 2 is higher - use same call as Straddle 1
            straddle2_call_strike = straddle1_call_strike
            
            # For put: calculate both possible strikes
            put_option_above = iron1_short_put_strike + offset_distance
            put_option_below = iron1_short_put_strike - offset_distance
            
            if straddle2_call_strike >= iron2_atm_strike:
                chosen_put_strike = put_option_below
            else:
                chosen_put_strike = put_option_above
             
            straddle2_put_strike = round(chosen_put_strike / 5) * 5
            
        else:
            # Iron 2 is lower or equal - use same put as Straddle 1
            straddle2_put_strike = straddle1_put_strike
            
            # For call: calculate both possible strikes
            call_option_above = iron1_short_call_strike + offset_distance
            call_option_below = iron1_short_call_strike - offset_distance
            
            # Choose the call strike that's furthest from BOTH:
            # 1. The put strike we just set (straddle2_put_strike)
            # 2. Iron 2 ATM strike
            if straddle2_put_strike >= iron2_atm_strike:
                chosen_call_strike = call_option_below
            else:
                chosen_call_strike = call_option_above
             
            straddle2_call_strike = round(chosen_call_strike / 5) * 5
        
        return {
            'call_strike': int(straddle2_call_strike),
            'put_strike': int(straddle2_put_strike),
            'iron1_net_premium': iron1_net_premium,
            'iron1_short_call': iron1_short_call_strike,
            'iron1_short_put': iron1_short_put_strike,
            'iron1_center': iron1_center,
            'iron2_atm_strike': iron2_atm_strike,
            'straddle1_call_strike': straddle1_call_strike,
            'straddle1_put_strike': straddle1_put_strike,
            'offset_distance': offset_distance
        }

    @staticmethod
    async def _execute_straddle(date: datetime, entry_time: datetime,
                               current_price: float,
                               strategy: StrategyConfig,
                               iron1_trade: Trade,
                               iron2_trade: Trade,
                               straddle1_trade: Trade,
                               data_provider: Union[MockDataProvider, PolygonDataProvider], 
                               config: BacktestConfig) -> Optional[Trade]:
        """Execute Straddle 2 trade - enters at same time as Iron 2"""
        
        # Determine strike prices
        strike_info = Straddle2._determine_straddle_strikes(iron1_trade, iron2_trade, straddle1_trade, strategy)
        
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
            logger.warning("Missing straddle 2 quotes, skipping trade")
            return None
        
        # Build trade positions (buy both legs)
        trade_contracts = {}
        net_premium = 0
        strikes_dict = {}
        
        # Get trade size (default to 1 if not specified)
        trade_size = getattr(strategy, 'straddle_2_trade_size', 1)
        
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
                'remaining_position': "100%",  # Track as fraction for partial exits
                'used_capital': price * 100 + config.commission_per_contract,
                'exited': False  # Track if partially exited
            }
            net_premium += price
        
        representation = f"{strikes_dict['long_straddle_put']}/{strikes_dict['long_straddle_call']}"
        
        # Get exit parameters from strategy config with proper defaults
        exit_percentage = getattr(strategy, 'straddle_2_exit_percentage', 0.5)  # 50%
        exit_multiplier = getattr(strategy, 'straddle_2_exit_multiplier', 2.0)  # 2x
        
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Straddle 2",
            contracts=trade_contracts,
            size=trade_size,
            entry_signals={'triggered_by': 'iron_condor_2', 'entered_with': 'iron_2'},
            used_capital=0.0,
            metadata={
                'strategy_name': 'straddle_2',
                'iron1_trade_ref': iron1_trade,
                'iron2_trade_ref': iron2_trade,
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
        
        logger.info(f"Entered Straddle 2 at {entry_time}: Call={call_strike}, Put={put_strike}, "
                   f"Net Premium=${net_premium:.2f}")
        
        return trade

    @staticmethod
    async def _check_straddle_exits(
        straddle: Trade,
        current_price: float,
        current_time: datetime,
        config: BacktestConfig,
        data_provider: Union[MockDataProvider, PolygonDataProvider]
    ) -> None:
        """Check if any Straddle 2 positions should be partially exited."""
        # Ensure metadata exists
        if straddle.metadata is None:
            straddle.metadata = {}

        call_straddle_strike = straddle.metadata.get("call_straddle_strike")
        put_straddle_strike = straddle.metadata.get("put_straddle_strike")
        exit_percentage = straddle.metadata.get("exit_percentage", 0.5)
        exit_multiplier = straddle.metadata.get("exit_multiplier", 2.0)

        # --- Strike hit condition ---
        call_hit = current_price >= call_straddle_strike if call_straddle_strike else False
        put_hit = current_price <= put_straddle_strike if put_straddle_strike else False

        if not (call_hit or put_hit):
            return
        
        if call_hit:
            leg_type = "call"
        else:
            leg_type = "put"

        for contract, details in straddle.contracts.items():
            if not leg_type in details["leg_type"]:
                continue
            
            leg_type = details["leg_type"]
            entry_price = details["entry_price"]  # raw option price (not *100)

            # --- Get current quote ---
            quotes = await data_provider.get_option_quotes([contract], current_time)
            if contract not in quotes:
                continue

            current_quote = quotes[contract]
            exit_price = current_quote["bid"]  # raw option price

            # --- Exit condition ---
            if exit_price >= entry_price * exit_multiplier:
                exit_size = exit_percentage

                if exit_size <= 0:
                    continue  # avoid zero-sized exits

                # Calculate partial P&L (SPX = 100× multiplier)
                partial_pnl = (exit_price - entry_price) * exit_size * 100
                # Apply only exit commission (entry commission assumed at open)
                partial_pnl -= config.commission_per_contract * exit_size
                details["used_capital"] += config.commission_per_contract * exit_size

                # Update position
                details["remaining_position"] = f"{(1 - exit_size) * 100:.1f}%"
                details["exited"] = True

                # Update running P&L at trade level
                straddle.metadata["partial_pnl"] = partial_pnl
                straddle.contracts[contract] = details
                straddle.exit_percentage = exit_percentage
                Straddle2.Straddle2_exited = True  # Mark that a partial exit has occurred
                
                logger.info(
                    f"Partial straddle 2 exit: {leg_type.upper()} at ${exit_price:.2f} "
                    f"(entry: ${entry_price:.2f}, x{exit_multiplier:.1f}), "
                    f"Size: {exit_size}, P&L: ${partial_pnl:.2f}"
                )