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
                               data_provider: Union[MockDataProvider, PolygonDataProvider]) -> Optional[Trade]:
        """Execute Straddle trade"""
        # Create straddle contracts
        exp_str = date.strftime('%y%m%d')
        straddle_distance = iron_condor_trade.metadata['net_credit'] * strategy.straddle_distance_multiplier
        c_strike = Straddle1._calculate_straddle_strike(current_price, straddle_distance)
        p_strike = Straddle1._calculate_straddle_strike(current_price, -straddle_distance)
        contracts = {
            'straddle_call': f"O:SPXW{exp_str}C{c_strike*1000:08d}",
            'straddle_put': f"O:SPXW{exp_str}P{p_strike*1000:08d}"
        }
        
        # Get quotes
        quotes = await data_provider.get_option_quotes(list(contracts.values()), entry_time)
        
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing straddle quotes, skipping trade")
            return None
        
        # Build trade positions (buy both legs)
        trade_contracts = {}
        total_premium = 0
        
        for leg, contract in contracts.items():
            quote = quotes[contract]
            price = quote['ask']

            if 'call' in leg:
                straddle_strike = c_strike
            else:  # put
                straddle_strike = p_strike
            
            trade_contracts[contract] = {
                'position': 1,  # Long position
                'entry_price': price,
                'leg_type': leg,
                'strike': straddle_strike,
                'remaining_position': 1  # Track for partial exits
            }
            total_premium += price
        
        # Create straddle trade
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Straddle 1",
            contracts=trade_contracts,
            size=strategy.straddle_1_trade_size,
            entry_signals={'triggered_by': 'iron_condor'},
            metadata={
                'strategy_name': 'straddle_1',
                'iron_condor_ref': iron_condor_trade,
                'call_straddle_strike': c_strike,
                'put_straddle_strike': p_strike,
                'total_premium': total_premium,
                'exit_percentage': strategy.straddle_exit_percentage,
                'exit_multiplier': strategy.straddle_exit_multiplier,
                'spx_price': current_price
            }
        )
        
        return trade
    

    async def _check_straddle_exits(open_straddles, current_price: float, current_time: datetime,
                                   config: BacktestConfig, data_provider: Union[MockDataProvider, PolygonDataProvider]) -> None:
        """Check if any straddle positions should be partially exited"""
        for straddle in open_straddles:
            if straddle.status != "OPEN":
                continue
            
            call_straddle_strike = straddle.metadata['call_straddle_strike']
            put_straddle_strike = straddle.metadata['put_straddle_strike']
            exit_percentage = straddle.metadata['exit_percentage']
            exit_multiplier = straddle.metadata['exit_multiplier']
            
            # Check if price hit the straddle strike
            if abs(current_price - call_straddle_strike) < 0.01 or abs(current_price - put_straddle_strike) < 0.01:  # Within penny of strike
                # Determine which leg is ITM
                for contract, details in straddle.contracts.items():
                    if details['remaining_position'] <= 0:
                        continue
                    
                    leg_type = details['leg_type']
                    entry_price = details['entry_price']
                    
                    # Check which leg to potentially exit
                    should_exit = False
                    if 'call' in leg_type and current_price >= call_straddle_strike:
                        should_exit = True
                    elif 'put' in leg_type and current_price <= put_straddle_strike:
                        should_exit = True
                    
                    if should_exit:
                        # Get current quote
                        quotes = await data_provider.get_option_quotes([contract], current_time)
                        if contract in quotes:
                            current_quote = quotes[contract]
                            exit_price = current_quote['bid']
                            
                            # Check if price is 2x or more of entry
                            if exit_price >= entry_price * exit_multiplier:
                                # Execute partial exit
                                exit_size = int(details['position'] * exit_percentage)
                                
                                if exit_size > 0:
                                    # Calculate P&L for partial exit
                                    partial_pnl = (exit_price - entry_price) * exit_size * 100  # SPX multiplier
                                    partial_pnl -= config.commission_per_contract * exit_size  # Exit commission
                                    
                                    # Update position
                                    details['remaining_position'] -= exit_size
                                    details['partial_exits'] = details.get('partial_exits', [])
                                    details['partial_exits'].append({
                                        'time': current_time,
                                        'size': exit_size,
                                        'price': exit_price,
                                        'pnl': partial_pnl
                                    })
                                    
                                    # Add to trade's running P&L
                                    straddle.metadata['partial_pnl'] = straddle.metadata.get('partial_pnl', 0) + partial_pnl
                                    
                                    logger.info(f"Partial straddle exit: {leg_type} at ${exit_price:.2f} "
                                              f"(entry: ${entry_price:.2f}), Size: {exit_size}, P&L: ${partial_pnl:.2f}")