from datetime import datetime
from typing import Any, Dict, Optional, Union
import logging
import numpy as np
import pandas as pd
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.iron_condor_base import IronCondorBase
from trades.signal_checker import OptimizedSignalChecker
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


class IronCondor3(IronCondorBase):
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
        iron_1_net_premium = iron1_trade.metadata.get('net_premium', 0)
        iron_1_short_strike = None
        for contract_symbol, contract_data in iron1_trade.contracts.items():
            if contract_data['leg_type'] == 'short_call':
                iron_1_short_strike = contract_data['strike']
                break      
        d = iron_1_short_strike - iron_1_net_premium
        u = iron_1_short_strike + iron_1_net_premium
        
        if current_price > d and current_price < u:
            return False 
        
        
        iron2_net_premium = iron2_trade.metadata.get('net_premium', 0)
        iron2_atm_strike = None
        for contract_data in iron2_trade.contracts.values():
            if contract_data['leg_type'] in ['short_call', 'short_put']:
                iron2_atm_strike = contract_data['strike']
                break
        
        trigger_multiplier = getattr(strategy_config, 'iron_3_trigger_multiplier', 1.0)
        if abs(iron2_atm_strike - d) < abs(iron2_atm_strike - u):
            lower_trigger = iron2_atm_strike - trigger_multiplier * iron2_net_premium
            if(current_price <= lower_trigger):
                logger.info(f"Iron 3(a) trigger price reached: {current_price:.2f} "
                           f"(trigger: {lower_trigger:.2f})")
                return True
        else:
            upper_trigger = iron2_atm_strike + trigger_multiplier * iron2_net_premium
            if(current_price >= upper_trigger):
                logger.info(f"Iron 3(a) trigger price reached: {current_price:.2f} "
                           f"(trigger: {upper_trigger:.2f})")
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
    async def _find_iron_trade(i: int,
                              strategy: StrategyConfig, date: datetime,
                              current_price: float, current_bar_time: datetime,
                              data_provider: Union[MockDataProvider, PolygonDataProvider],
                              config: BacktestConfig,
                              iron1_trade: Optional[Trade],
                              iron2_trade: Optional[Trade],
                              checker : OptimizedSignalChecker) -> Optional[Trade]:
        """
        Find Iron 3(a) or 3(b) trade based on market conditions.
        Iron 3(a) takes precedence; Iron 3(b) only if no 3(a) executed.
        """
        
        # Check for Iron 3(a) first (if not already executed)
        if iron2_trade:
            # Check trigger price
            if IronCondor3._check_iron3a_trigger_price(current_price, iron1_trade, iron2_trade, strategy):
                # Check minimum distance
                    # Check entry conditions
                    if checker.iron_3_check_entry_conditions(i, strategy):
                        logger.info(f"Iron 3(a) entry conditions met at {current_bar_time}")
                        
                        # Find Iron Butterfly strikes
                        if isinstance(date, datetime):
                            option_date = date
                        else:
                            option_date = datetime.combine(date, datetime.min.time())
                        
                        iron_result = await IronCondor3.find_iron_condor_strikes(current_price, current_bar_time, strategy, data_provider, strategy.iron_3_target_win_loss_ratio)
                        
                        if iron_result:
                            strikes = {
                                'short_call': iron_result['short_call'],
                                'short_put': iron_result['short_put'],
                                'long_call': iron_result['long_call'],
                                'long_put': iron_result['long_put']
                            }
                            
                            contracts = IronCondor3.create_option_contracts(strikes, option_date)
                            quotes = await data_provider.get_option_quotes(
                                list(contracts.values()), current_bar_time
                            )
                            
                            net_premium = iron_result['net_premium']
                            
                            if net_premium > 0:
                                trade = await IronCondorBase.execute(
                                    quotes, current_bar_time, contracts, strategy,
                                     net_premium, current_price, config,
                                    "Iron Condor 3(a)"
                                )
                                
                                if trade:
                                    logger.info(f"Entered Iron 3(a) at {current_bar_time}: {strikes}")
                                    return trade
        
        
        if iron1_trade and iron2_trade:
            # Check trigger price
            if IronCondor3._check_iron3b_trigger_price(current_price, iron1_trade, iron2_trade, strategy):
                # Check minimum distance
                    # Check entry conditions
                    if checker.iron_3_check_entry_conditions(i, strategy):
                        logger.info(f"Iron 3(b) entry conditions met at {current_bar_time}")
                        
                        # Find Iron Condor strikes
                        if isinstance(date, datetime):
                            option_date = date
                        else:
                            option_date = datetime.combine(date, datetime.min.time())
                        
                        iron_result = await IronCondor3.find_iron_condor_strikes(
                            current_price, current_bar_time, strategy, data_provider, strategy.iron_3_target_win_loss_ratio
                        )
                        
                        if iron_result:
                            strikes = {
                                'short_call': iron_result['short_call'],
                                'short_put': iron_result['short_put'],
                                'long_call': iron_result['long_call'],
                                'long_put': iron_result['long_put']
                            }
                            
                            contracts = IronCondor3.create_option_contracts(strikes, option_date)
                            quotes = await data_provider.get_option_quotes(
                                list(contracts.values()), current_bar_time
                            )
                            
                            net_premium = iron_result['net_premium']
                            
                            if net_premium > 0:
                                trade = await IronCondorBase.execute(
                                    quotes, current_bar_time, contracts, strategy,
                                   net_premium, current_price, config,
                                    "Iron Condor 3(b)"
                                )
                                
                                if trade:
                                    logger.info(f"Entered Iron 3(b) at {current_bar_time}: {strikes}")
                                    return trade
        
        return None