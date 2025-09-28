from datetime import datetime
import logging
from pyparsing import Union
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.iron_condor_base import IronCondorBase
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
from trades.signal_checker import OptimizedSignalChecker

#Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IronCondor1(IronCondorBase):

    
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
                
            ic_result = await IronCondor1.find_iron_condor_strikes(current_price, current_bar_time, strategy, data_provider, strategy.iron_1_target_win_loss_ratio)
                
            if ic_result:
                ic_strikes = {
                        'short_call': ic_result['short_call'],
                        'short_put': ic_result['short_put'],
                        'long_call': ic_result['long_call'],
                        'long_put': ic_result['long_put']
                }
                    
                ic_contracts = IronCondor1.create_option_contracts(ic_strikes, option_date)
                ic_quotes = ic_result['quotes']
                    
                net_premium = ic_result['net_premium']
                    
                if net_premium > 0:
                    ic_trade = await IronCondor1.execute(
                            ic_quotes,
                            current_bar_time,
                            ic_contracts,
                            strategy,
                            net_premium,
                            current_price, config, "Iron Condor 1"
                    )
                    logger.info(f"Entered Iron Condor 1 at {current_bar_time}: {ic_strikes}")
                    return ic_trade
        return None