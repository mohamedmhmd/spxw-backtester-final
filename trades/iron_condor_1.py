from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import logging
import numpy as np
import pandas as pd
from pyparsing import Union
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.strikes_finder import StrikesFinder
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
import asyncio
import time as time_module
from trades.signal_checker import OptimizedSignalChecker

#Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IronCondor1:

    async def _execute_iron_condor(quotes: Dict[str, Dict], entry_time: datetime,
                                  contracts: Dict[str, str], strategy: StrategyConfig,
                                  net_premium: float, current_price, config : BacktestConfig) -> Optional[Trade]:
        """Execute Iron Condor trade""" 
        # Check if we have all quotes
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing option quotes, skipping trade")
            return None
        
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
                'position': -strategy.iron_1_trade_size,  # Short position
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
                'position': strategy.iron_1_trade_size,  # Long position
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
            trade_type="Iron Condor 1",
            contracts=trade_contracts,
            size=strategy.iron_1_trade_size,
            used_capital = 0.0,
            metadata={
                'net_premium': net_premium,
                'strategy_name': 'iron_1',
                'entry_spx_price': current_price,
                'representation': representation,
                'wing' : strikes_dict['short_put'] - strikes_dict['long_put']
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
    

    async def _find_iron_trade(i : int, 
                                 strategy : StrategyConfig, 
                                 date: datetime,
                                 current_price,
                                 current_bar_time,
                                 data_provider : Union[MockDataProvider, PolygonDataProvider],
                                 config : BacktestConfig, checker : OptimizedSignalChecker) -> Trade:
        """Find Iron Condor 1 trade based on strategy config"""
        # Check entry conditions for new Iron Condor trades    
        if checker.iron_1_check_entry_signals_5min(i, strategy):
            if isinstance(date, datetime):
                option_date = date
            else:
                option_date = datetime.combine(date, datetime.min.time())
                
            ic_result = await StrikesFinder._find_iron_condor_strikes(current_price, current_bar_time, strategy, data_provider)
                
            if ic_result:
                ic_strikes = {
                        'short_call': ic_result['short_call'],
                        'short_put': ic_result['short_put'],
                        'long_call': ic_result['long_call'],
                        'long_put': ic_result['long_put']
                }
                    
                ic_contracts = IronCondor1._create_option_contracts(ic_strikes, option_date)
                ic_quotes = ic_result['quotes']
                    
                net_premium = ic_result['net_premium']
                    
                if net_premium > 0:
                    ic_trade = await IronCondor1._execute_iron_condor(
                            ic_quotes,
                            current_bar_time,
                            ic_contracts,
                            strategy,
                            net_premium,
                            current_price, config
                    )
                    logger.info(f"Entered Iron Condor 1 at {current_bar_time}: {ic_strikes}")
                    return ic_trade
        return None