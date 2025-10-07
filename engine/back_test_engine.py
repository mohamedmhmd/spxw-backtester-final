from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple, Any, Union
import logging
import asyncio
from data.mock_data_provider import MockDataProvider
from config.back_test_config import BacktestConfig
from data.polygon_data_provider import PolygonDataProvider
from config.strategy_config import StrategyConfig
from trades.iron_condor_3 import IronCondor3
from trades.long_option_1 import LongOption1
from trades.signal_checker import OptimizedSignalChecker
from trades.straddle2 import Straddle2
from trades.straddle3 import Straddle3
from trades.trade import Trade
from engine.statistics import Statistics
from trades.iron_condor_1 import IronCondor1
from trades.iron_condor_2 import IronCondor2
from trades.straddle1 import Straddle1
from trades.underlying_cover_1 import UnderlyingCover1
from utilities.utilities import Utilities
import time as time_module
from trades.credit_spread_1 import CreditSpread1

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestEngine:
    """Complete backtesting engine implementation with Iron Condor and Straddle - Parallelized"""
    
    def __init__(self, data_provider: Union[MockDataProvider, PolygonDataProvider], selected_strategy: str):
        self.data_provider = data_provider
        self.trades: List[Trade] = []
        self.daily_pnl: Dict[datetime, float] = {}
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.current_capital: float = 0.0
        self.open_straddles: List[Trade] = []  # Track open straddles for intraday management
        self.total_capital_used: float = 0.0
        self.selected_strategy = selected_strategy
        
    async def run_backtest(self, config: BacktestConfig, strategy: StrategyConfig) -> Dict[str, Any]:
        """Run complete backtest with parallel daily strategy execution"""
        start_time = time_module.time()
        logger.info(f"Starting parallel backtest from {config.start_date} to {config.end_date}")
        
        self.trades = []
        self.current_capital = 0.0
        self.daily_pnl = {}
        
        # Collect all trading dates first
        trading_dates = self._get_trading_dates(config.start_date, config.end_date)
        logger.info(f"Found {len(trading_dates)} trading dates to process")
        
        # Create tasks for each trading day
        if(self.selected_strategy == "Trades 16"):
           tasks = [
               self._run_daily_strategy_16_task(date, config, strategy)
               for date in trading_dates
           ]
        elif (self.selected_strategy == "Trades 17"):
           tasks = [
            self._run_daily_strategy_17_task(date, config, strategy)
            for date in trading_dates
           ]
        
        # Run all daily strategies in parallel
        logger.info("Running daily strategies in parallel...")
        daily_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and handle any exceptions
        all_trades = []
        daily_pnl_dict = {}
        
        for i, result in enumerate(daily_results):
            date = trading_dates[i]
            
            if isinstance(result, Exception):
                logger.error(f"Error processing {date}: {result}")
                daily_pnl_dict[date] = 0.0
                continue
                
            daily_trades, daily_pnl = result
            all_trades.extend(daily_trades)
            daily_pnl_dict[date] = daily_pnl
        
        # Sort trades by entry time to maintain chronological order
        all_trades.sort(key=lambda trade: trade.entry_time)
        
        self.total_capital_used = sum(trade.used_capital for trade in all_trades)
        
        # Build equity curve sequentially (since it depends on cumulative P&L)
        self.trades = all_trades
        self.daily_pnl = daily_pnl_dict
        self._build_equity_curve(self.total_capital_used, trading_dates)
        
        # Calculate statistics
        stats = Statistics._calculate_statistics(
            self.trades, 
            self.equity_curve, 
            self.daily_pnl, 
            self.selected_strategy
        )
        
        logger.info(f"Backtest completed: {len(self.trades)} total trades.")
        total_time = time_module.time() - start_time
        logger.info(f"Total backtest execution time: {total_time:.2f} seconds")
        
        return {
            'trades': self.trades,
            'daily_pnl': self.daily_pnl,
            'equity_curve': self.equity_curve,
            'statistics': stats
        }
    
    def _get_trading_dates(self, start_date: datetime, end_date: datetime) -> List[datetime]:
        """Get list of all trading dates in the range"""
        trading_dates = []
        current_date = start_date
        
        while current_date <= end_date:
            # Skip weekends
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue
            
            # Skip non-trading days (holidays, etc.)
            if not Utilities._is_trading_day(current_date):
                current_date += timedelta(days=1)
                continue
                
            trading_dates.append(current_date)
            current_date += timedelta(days=1)
            
        return trading_dates
    
    def _build_equity_curve(self, initial_capital: float, trading_dates: List[datetime]):
        """Build equity curve from daily P&L results"""
        self.equity_curve = [(trading_dates[0] if trading_dates else datetime.now(), initial_capital)]
        running_capital = initial_capital
        
        for date in trading_dates:
            daily_pnl = self.daily_pnl.get(date, 0.0)
            running_capital += daily_pnl
            self.equity_curve.append((date, running_capital))
        
        self.current_capital = running_capital
    
    async def _run_daily_strategy_16_task(self, date: datetime, config: BacktestConfig, 
                                      strategy: StrategyConfig) -> Tuple[List[Trade], float]:
        """Wrapper for daily strategy that returns trades and P&L"""
        try:
            daily_trades = await self._run_daily_strategy_16(date, config, strategy)
            daily_pnl = sum(trade.pnl for trade in daily_trades)
            return daily_trades, daily_pnl
        except Exception as e:
            logger.error(f"Error in daily strategy for {date}: {e}")
            return [], 0.0
        
    async def _run_daily_strategy_17_task(self, date: datetime, config: BacktestConfig, 
                                      strategy: StrategyConfig) -> Tuple[List[Trade], float]:
        """Wrapper for daily strategy that returns trades and P&L"""
        try:
            daily_trades = await self._run_daily_strategy_17(date, config, strategy)
            daily_pnl = sum(trade.pnl for trade in daily_trades)
            return daily_trades, daily_pnl
        except Exception as e:
            logger.error(f"Error in daily strategy for {date}: {e}")
            return [], 0.0
    
    async def _run_daily_strategy_16(self, date: datetime, config: BacktestConfig, 
                                  strategy: StrategyConfig) -> List[Trade]:
        """Run strategy for a single day with both Iron Condor and Straddle - allows multiple entries per day"""
        trades = []
        open_straddles = []  # Use local variable instead of instance variable for thread safety
        
        spy_ohlc_data = await self.data_provider.get_ohlc_data(date, "SPY")
        spx_ohlc_data = await self.data_provider.get_ohlc_data(date, "I:SPX")

        if spy_ohlc_data.empty or spx_ohlc_data.empty:
            logger.warning(f"No data available for {date}")
            return trades
        
        #iron 1 and straddle 1
        iron_1_min_bars_needed = max(
            strategy.iron_1_consecutive_candles,
            strategy.iron_1_lookback_candles,
            strategy.iron_1_avg_range_candles
        )
        if len(spy_ohlc_data) < iron_1_min_bars_needed:
            logger.warning(f"Insufficient bars for {date}: {len(spy_ohlc_data)} < {iron_1_min_bars_needed}")
            return trades
        
        active_iron_condors = []
        ic1_found = False
        ic2_found = False
        ic3_found = False
        cs1a_found = False
        cs1b_found = False
        straddle_3_type = ""
        checker = OptimizedSignalChecker(spx_ohlc_data, spy_ohlc_data)
        
        for i in range(iron_1_min_bars_needed, len(spx_ohlc_data)):
            current_bar_time = spx_ohlc_data.iloc[i]['timestamp']
            current_price = spx_ohlc_data.iloc[i]['open']
            
            if not cs1a_found:
                cs1a_trade = await CreditSpread1._find_credit_spread_trade(i,strategy,date,current_price,current_bar_time,
                                                                            self.data_provider, config, checker, spx_ohlc_data,'a')
                if cs1a_trade:
                   trades.append(cs1a_trade)
                   cs1a_found = True 
                   logger.info(f"Entered Credit Spread 1(a) at {current_bar_time}.")
                   
            if not cs1b_found:
                cs1b_trade = await CreditSpread1._find_credit_spread_trade(i,strategy,date,current_price,current_bar_time,
                                                                            self.data_provider, config, checker, spx_ohlc_data,'b')
                if cs1b_trade:
                   trades.append(cs1b_trade)
                   cs1b_found = True 
                   logger.info(f"Entered Credit Spread 1(b) at {current_bar_time}.")
                
            
            if not Straddle1.Straddle1_exited and len(open_straddles) > 0:
               await Straddle1._check_straddle_exits(open_straddles[0], current_price, current_bar_time, config, self.data_provider)
            
            if not Straddle2.Straddle2_exited and len(open_straddles) > 1:
               await Straddle2._check_straddle_exits(open_straddles[1], current_price, current_bar_time, config, self.data_provider)
            if straddle_3_type == "Straddle 3(a)" and not Straddle3.Straddle3a_exited and len(open_straddles) > 2:
               await Straddle3._check_straddle_exits(open_straddles[2], current_price, current_bar_time, config, self.data_provider)
            if straddle_3_type == "Straddle 3(b)" and not Straddle3.Straddle3b_exited and len(open_straddles) > 2:
               await Straddle3._check_straddle_exits(open_straddles[2], current_price, current_bar_time, config, self.data_provider)
            
            if(ic1_found):
                if not ic2_found:
                    iron_2_trade = await IronCondor2._find_iron_trade(i, strategy, 
                                                         date, current_price, current_bar_time,
                                                         self.data_provider, config,
                                                         active_iron_condors[0], checker)
                    if iron_2_trade:
                        trades.append(iron_2_trade)
                        active_iron_condors.append(iron_2_trade)
                        ic2_found = True
                        logger.info(f"Entered Iron Condor 2 at {current_bar_time}.")
                        if isinstance(date, datetime):
                           option_date = date
                        else:
                           option_date = datetime.combine(date, datetime.min.time())
                
                        straddle_2_trade = await Straddle2._execute_straddle(option_date,
                                current_bar_time,
                                current_price,
                                strategy,
                                ic_1_trade,
                                iron_2_trade,
                                open_straddles[0],
                                self.data_provider, config
                        )
                        if straddle_2_trade:
                            trades.append(straddle_2_trade)
                            open_straddles.append(straddle_2_trade)
                            logger.info(f"Entered Straddle 2 at {current_bar_time}.")
                else:
                    if not ic3_found:
                        iron_3_trade = await IronCondor3._find_iron_trade(i,
                              strategy, date,
                              current_price, current_bar_time,
                              self.data_provider,
                              config,
                              ic_1_trade,
                              iron_2_trade, checker
                              )
                        if iron_3_trade:
                            trades.append(iron_3_trade)
                            active_iron_condors.append(iron_3_trade)
                            ic3_found = True 
                            logger.info(f"Entered Iron Condor 3  at {current_bar_time}.")
                            
                            if isinstance(date, datetime):
                               option_date = date
                            else:
                               option_date = datetime.combine(date, datetime.min.time())
                            
                            if iron_3_trade.trade_type == "Iron Condor 3(a)":
                                straddle_3_type = "Straddle 3(a)"
                                straddle_3_trade = await Straddle3._execute_straddle3a(
                                     option_date,
                                     current_bar_time,
                                     current_price,
                                     strategy,
                                     iron_2_trade,
                                     iron_3_trade,
                                     open_straddles[0],
                                     self.data_provider, config
                                )
                                
                                if straddle_3_trade:
                                    trades.append(straddle_3_trade)
                                    open_straddles.append(straddle_3_trade)
                                    logger.info(f"Entered Straddle 3(a) at {current_bar_time}.")
                            elif iron_3_trade.trade_type == "Iron Condor 3(b)":
                                straddle_3_type = "Straddle 3(b)"
                                straddle_3_trade = await Straddle3._execute_straddle3b(
                                     option_date,
                                     current_bar_time,
                                     current_price,
                                     strategy,
                                     ic_1_trade,
                                     iron_2_trade,
                                     iron_3_trade,
                                     open_straddles[0],
                                     self.data_provider, config
                                )
                                if straddle_3_trade:
                                    trades.append(straddle_3_trade)
                                    open_straddles.append(straddle_3_trade)
                                    logger.info(f"Entered Straddle 3(b) at {current_bar_time}.")
                            
                    else:
                        continue
            else:
            
                ic_1_trade = await IronCondor1._find_iron_trade(i, strategy, 
                                                     date, current_price, current_bar_time,
                                                     self.data_provider, config, checker)
                if ic_1_trade:
                   trades.append(ic_1_trade)
                   active_iron_condors.append(ic_1_trade)
                   ic1_found = True 
                   if isinstance(date, datetime):
                      option_date = date
                   else:
                      option_date = datetime.combine(date, datetime.min.time())
                
                   straddle_1_trade = await Straddle1._execute_straddle(
                                option_date,
                                current_bar_time,
                                current_price,
                                strategy,
                                ic_1_trade,
                                self.data_provider, config
                )
                            
                   if straddle_1_trade:
                      trades.append(straddle_1_trade)
                      open_straddles.append(straddle_1_trade)
                      logger.info(f"Entered Straddle 1 at {current_bar_time}.")
            
            
            #break condition - all trades found for the day
            if ic1_found and ic2_found and Straddle1.Straddle1_exited and Straddle2.Straddle2_exited and (Straddle3.Straddle3a_exited or Straddle3.Straddle3b_exited) and cs1a_found:
                break
                    
                    
                        
        # Close any remaining open trades at expiry
        for trade in trades:
            if trade.status == "OPEN":
                await trade._close_trade_at_expiry(spx_ohlc_data, date, config)
        
        logger.info(f"Day {date.strftime('%Y-%m-%d')} completed: {len([t for t in trades if t.trade_type == 'Iron Condor 1'])} Iron Condors, {len([t for t in trades if t.trade_type == 'Straddle 1'])} Straddles")
        return trades
    
    
    async def _run_daily_strategy_17(self, date: datetime, config: BacktestConfig, 
                                  strategy: StrategyConfig) -> List[Trade]:
        """Run strategy for a single day with both Iron Condor and Straddle - allows multiple entries per day"""
        trades = []
        spy_ohlc_data = await self.data_provider.get_ohlc_data(date, "SPY")
        spx_ohlc_data = await self.data_provider.get_ohlc_data(date, "I:SPX")

        if spy_ohlc_data.empty or spx_ohlc_data.empty:
            logger.warning(f"No data available for {date}")
            return trades
        
        #iron 1 and straddle 1
        cs_1_min_bars_needed = max(
            strategy.cs_1_consecutive_candles,
            strategy.cs_1_lookback_candles,
            strategy.cs_1_avg_range_candles
        )
        if len(spy_ohlc_data) < cs_1_min_bars_needed:
            logger.warning(f"Insufficient bars for {date}: {len(spy_ohlc_data)} < {cs_1_min_bars_needed}")
            return trades
        
        cs1a_found = False
        cs1b_found = False
        checker = OptimizedSignalChecker(spx_ohlc_data, spy_ohlc_data)
        active_cs_1_a_trades = []
        active_cs_1_b_trades = []
        active_cover_a_trades = []
        active_cover_b_trades = []
        cv_1_a_found = False
        cv_1_b_found = False
        
        for i in range(cs_1_min_bars_needed, len(spx_ohlc_data)):
            current_bar_time = spx_ohlc_data.iloc[i]['timestamp']
            current_price = spx_ohlc_data.iloc[i]['open']
            
            if not cs1a_found:
                cs1a_trade = await CreditSpread1._find_credit_spread_trade(i,strategy,date,current_price,current_bar_time,
                                                                            self.data_provider, config, checker, spx_ohlc_data,'a')
                if cs1a_trade:
                   trades.append(cs1a_trade)
                   active_cs_1_a_trades.append(cs1a_trade)
                   cs1a_found = True 
                   logger.info(f"Entered Credit Spread 1(a) at {current_bar_time}.")
                   
                   
                   
            if not cs1b_found:
                cs1b_trade = await CreditSpread1._find_credit_spread_trade(i,strategy,date,current_price,current_bar_time,
                                                                            self.data_provider, config, checker, spx_ohlc_data,'b')
                if cs1b_trade:
                   trades.append(cs1b_trade)
                   cs1b_found = True 
                   logger.info(f"Entered Credit Spread 1(b) at {current_bar_time}.")
                   
            if not cv_1_a_found and cs1a_found:
                cv_1_a_list = await UnderlyingCover1.check_and_execute_covers(
                                    spx_ohlc_data,
                                    i,
                                    active_cs_trades=active_cs_1_a_trades,
                                    current_spx_price=current_price,
                                    current_bar_time=current_bar_time,
                                    date=date,
                                    strategy=strategy,
                                    data_provider=self.data_provider,
                                    config=config)
                
                if(len(cv_1_a_list) > 0):
                   cv_1_a_trade = cv_1_a_list[0]
                   active_cover_a_trades.append(cv_1_a_trade)
                   cv_1_a_found = True
                   logger.info(f"Entered Underlying Cover 1(a) at {current_bar_time}.")
                   
                   long_opt_1a = await LongOption1.execute_long_option_with_cover(
                                                                               cs1a_trade,
                                                                               cv_1_a_trade,
                                                                               current_bar_time,
                                                                               date,
                                                                               strategy,
                                                                               self.data_provider,
                                                                               config
                                                                                       )
                   if long_opt_1a:
                       trades.append(long_opt_1a)
                   
            if not cv_1_b_found and cs1b_found:
                cv_1_b_list = await UnderlyingCover1.check_and_execute_covers(
                                    spx_ohlc_data,
                                    i,
                                    active_cs_trades=active_cs_1_b_trades,
                                    current_spx_price=current_price,
                                    current_bar_time=current_bar_time,
                                    date=date,
                                    strategy=strategy,
                                    data_provider=self.data_provider,
                                    config=config)
                
                if(len(cv_1_b_list) > 0):
                   cv_1_b_trade = cv_1_b_list[0]
                   active_cover_b_trades.append(cv_1_b_trade)
                   cv_1_b_found = True
                   logger.info(f"Entered Underlying Cover 1(b) at {current_bar_time}.")
                   
                   long_opt_1b = await LongOption1.execute_long_option_with_cover(
                                                                                  cs1b_trade,
                                                                                  cv_1_b_trade,
                                                                                  current_bar_time,
                                                                                  date,
                                                                                  strategy,
                                                                                  self.data_provider,
                                                                                  config
                                                                                        )
                   if long_opt_1b:
                      trades.append(long_opt_1b)
                
            
            
            
            #break condition - all trades found for the day
            if cs1b_found and cs1a_found and cv_1_a_found and cv_1_b_found:
                break
                    
                    
                        
        # Close any remaining open trades at expiry
        for trade in trades:
            if trade.status == "OPEN":
                await trade._close_trade_at_expiry(spx_ohlc_data, date, config)
                
        await UnderlyingCover1.close_covers_at_market_close(active_cover_a_trades,
        date,
        self.data_provider,
        config)
        
        for cover_a_trade in active_cover_a_trades:
            trades.append(cover_a_trade)
            
            
        await UnderlyingCover1.close_covers_at_market_close(active_cover_b_trades,
        date,
        self.data_provider,
        config)
        
        for cover_b_trade in active_cover_b_trades:
            trades.append(cover_b_trade)
        
        logger.info(f"Day {date.strftime('%Y-%m-%d')} completed: {len([t for t in trades if t.trade_type == 'Iron Condor 1'])} Iron Condors, {len([t for t in trades if t.trade_type == 'Straddle 1'])} Straddles")
        return trades