from datetime import datetime
from typing import Optional

from pyparsing import Union

from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.trade import Trade
import logging

from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider

#Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)



class Straddle1:
    
    Straddle1_exited = False  # Class variable to track if straddle has been exited
    
    def _calculate_straddle_strike(current_price: float, distance: float) -> int:
        """Calculate straddle strike based on distance from current price"""
        # Distance is in dollar terms from Iron Condor credit
        # Round to nearest 5
        straddle_strike = round((current_price + distance) / 5) * 5
        return int(straddle_strike)

    async def _execute_straddle(date: datetime, entry_time: datetime,
                               current_price: float,
                               strategy: StrategyConfig,
                               iron_condor_trade: Trade,
                               data_provider: Union[MockDataProvider, PolygonDataProvider], config : BacktestConfig) -> Optional[Trade]:
        """Execute Straddle trade"""
        # Create straddle contracts
        exp_str = date.strftime('%y%m%d')
        straddle_distance = iron_condor_trade.metadata['net_premium'] * strategy.straddle_distance_multiplier
        c_strike = Straddle1._calculate_straddle_strike(current_price, straddle_distance)
        p_strike = Straddle1._calculate_straddle_strike(current_price, -straddle_distance)
        contracts = {
            'long_straddle_call': f"O:SPXW{exp_str}C{c_strike*1000:08d}",
            'long_straddle_put': f"O:SPXW{exp_str}P{p_strike*1000:08d}"
        }
        
        # Get quotes
        quotes = await data_provider.get_option_quotes(list(contracts.values()), entry_time)
        
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing straddle quotes, skipping trade")
            return None
        
        # Build trade positions (buy both legs)
        trade_contracts = {}
        net_premium = 0
        strikes_dict = {}
        
        for leg, contract in contracts.items():
            quote = quotes[contract]
            price = quote['ask']

            if 'call' in leg:
                straddle_strike = c_strike
            else:  # put
                straddle_strike = p_strike
            strikes_dict[leg] = straddle_strike
            
            trade_contracts[contract] = {
                'position': strategy.straddle_1_trade_size,  # Long position
                'entry_price': price,
                'leg_type': leg,
                'strike': straddle_strike,
                'remaining_position': "100%",  # Track for partial exits
                'used_capital': price * 100 + config.commission_per_contract
            }
            net_premium += price
        
        representation = f"{strikes_dict["long_straddle_put"]}/{strikes_dict["long_straddle_call"]}"
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Straddle 1",
            contracts=trade_contracts,
            size=strategy.straddle_1_trade_size,
            entry_signals={'triggered_by': 'iron_condor'},
            used_capital=0.0,
            metadata={
                'strategy_name': 'straddle_1',
                'iron_condor_ref': iron_condor_trade,
                'call_straddle_strike': c_strike,
                'put_straddle_strike': p_strike,
                'net_premium': net_premium,
                'exit_percentage': strategy.straddle_exit_percentage,
                'exit_multiplier': strategy.straddle_exit_multiplier,
                'entry_spx_price': current_price,
                'representation': representation
            }
        )
        
        return trade
    

    async def _check_straddle_exits(
    open_straddles,
    current_price: float,
    current_time: datetime,
    config: BacktestConfig,
    data_provider: Union["MockDataProvider", "PolygonDataProvider"]
) -> None:
         """Check if any straddle positions should be partially exited."""
    
         for straddle in open_straddles:
             if straddle.status != "OPEN":
                continue

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
                continue
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
                    Straddle1.Straddle1_exited = True  # Mark that a partial exit has occurred
                    logger.info(
                    f"Partial straddle exit: {leg_type.upper()} at ${exit_price:.2f} "
                    f"(entry: ${entry_price:.2f}, x{exit_multiplier:.1f}), "
                    f"Size: {exit_size}, P&L: ${partial_pnl:.2f}"
                   )
