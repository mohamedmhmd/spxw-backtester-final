from datetime import datetime
from typing import Optional
import logging
from pyparsing import Union
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.iron_condor_base import IronCondorBase
from trades.signal_checker import OptimizedSignalChecker
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider

#Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IronCondor2(IronCondorBase):
    
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
    async def _find_iron_trade(i: int, strategy: StrategyConfig, date: datetime,
                              current_price: float, current_bar_time: datetime,
                              data_provider: Union[MockDataProvider, PolygonDataProvider],
                              config: BacktestConfig, 
                              iron1_trade: Trade, checker : OptimizedSignalChecker) -> Optional[Trade]:
        """
        Find Iron Butterfly (Iron 2) trade based on strategy config and existing Iron 1 trades
        """
        
        # Check if price triggers Iron 2 entry based on Iron 1 positions
        if not IronCondor2._check_iron2_trigger_price(current_price, iron1_trade, strategy):
            return None
         
        if not checker.iron_2_check_entry_conditions(i, strategy):
            return None
        
        logger.info(f"Iron 2 entry conditions met at {current_bar_time}")
        
        # Find optimal Iron Butterfly strikes
        if isinstance(date, datetime):
            option_date = date
        else:
            option_date = datetime.combine(date, datetime.min.time())
        

        ib_result = await IronCondor2.find_iron_condor_strikes(current_price, current_bar_time, strategy, data_provider, strategy.iron_2_target_win_loss_ratio)
        
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
        ib_contracts = IronCondor2.create_option_contracts(ib_strikes, option_date)
        ib_quotes = await data_provider.get_option_quotes(
            list(ib_contracts.values()), current_bar_time
        )
        
        # Calculate net premium
        net_premium = ib_result['net_premium']
        
        if net_premium <= 0:
            logger.warning(f"Iron Butterfly net premium not positive: {net_premium}")
            return None
        
        # Execute Iron Butterfly trade
        ib_trade = await IronCondorBase.execute(
            ib_quotes, current_bar_time, ib_contracts, strategy,
            net_premium, current_price, config, "Iron Condor 2"
        )
        
        if ib_trade:
            logger.info(f"Entered Iron Butterfly (Iron 2) at {current_bar_time}: {ib_strikes}")
            
        return ib_trade