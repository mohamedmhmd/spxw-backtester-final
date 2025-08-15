from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple, Any, Union
import logging
import asyncio
from data.mock_data_provider import MockDataProvider
from config.back_test_config import BacktestConfig
from data.polygon_data_provider import PolygonDataProvider
from config.strategy_config import StrategyConfig
from trades.trade import Trade
from engine.statistics import Statistics
from trades.iron_condor_1 import IronCondor1
from trades.straddle1 import Straddle1
from utilities.utilities import Utilities
import time as time_module

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestEngine:
    """Complete backtesting engine implementation with Iron Condor and Straddle - Parallelized"""
    
    def __init__(self, data_provider: Union[MockDataProvider, PolygonDataProvider]):
        self.data_provider = data_provider
        self.trades: List[Trade] = []
        self.daily_pnl: Dict[datetime, float] = {}
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.current_capital: float = 0.0
        self.open_straddles: List[Trade] = []  # Track open straddles for intraday management
        
    async def run_backtest(self, config: BacktestConfig, strategy: StrategyConfig) -> Dict[str, Any]:
        """Run complete backtest with parallel daily strategy execution"""
        start_time = time_module.time()
        logger.info(f"Starting parallel backtest from {config.start_date} to {config.end_date}")
        
        self.trades = []
        self.current_capital = config.initial_capital
        self.daily_pnl = {}
        
        # Collect all trading dates first
        trading_dates = self._get_trading_dates(config.start_date, config.end_date)
        logger.info(f"Found {len(trading_dates)} trading dates to process")
        
        # Create tasks for each trading day
        tasks = [
            self._run_daily_strategy_task(date, config, strategy)
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
        
        # Build equity curve sequentially (since it depends on cumulative P&L)
        self.trades = all_trades
        self.daily_pnl = daily_pnl_dict
        self._build_equity_curve(config.initial_capital, trading_dates)
        
        # Calculate statistics
        stats = Statistics._calculate_statistics(
            self.trades, 
            self.equity_curve, 
            self.current_capital, 
            self.daily_pnl, 
            config
        )
        
        logger.info(f"Backtest completed: {len(self.trades)} total trades")
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
    
    async def _run_daily_strategy_task(self, date: datetime, config: BacktestConfig, 
                                      strategy: StrategyConfig) -> Tuple[List[Trade], float]:
        """Wrapper for daily strategy that returns trades and P&L"""
        try:
            daily_trades = await self._run_daily_strategy(date, config, strategy)
            daily_pnl = sum(trade.pnl for trade in daily_trades)
            return daily_trades, daily_pnl
        except Exception as e:
            logger.error(f"Error in daily strategy for {date}: {e}")
            return [], 0.0
    
    async def _run_daily_strategy(self, date: datetime, config: BacktestConfig, 
                                  strategy: StrategyConfig) -> List[Trade]:
        """Run strategy for a single day with both Iron Condor and Straddle - allows multiple entries per day"""
        trades = []
        open_straddles = []  # Use local variable instead of instance variable for thread safety
        
        spy_ohlc_data = await self.data_provider.get_ohlc_data(date, "SPY")
        spx_ohlc_data = await self.data_provider.get_ohlc_data(date, "I:SPX")

        if spy_ohlc_data.empty:
            logger.warning(f"No data available for {date}")
            return trades
        
        min_bars_needed = max(
            strategy.consecutive_candles,
            strategy.lookback_candles,
            strategy.avg_range_candles
        )
        if len(spy_ohlc_data) < min_bars_needed:
            logger.warning(f"Insufficient bars for {date}: {len(spy_ohlc_data)} < {min_bars_needed}")
            return trades
        
        active_iron_condors = []
        ic1_found = False
        for i in range(min_bars_needed, len(spx_ohlc_data)):
            current_bar_time = spx_ohlc_data.iloc[i]['timestamp']
            current_price = spx_ohlc_data.iloc[i]['open']
            if current_bar_time.time() < time(9, 30) or current_bar_time.time() >= time(16, 0):
                continue
            
            await Straddle1._check_straddle_exits(open_straddles, current_price, current_bar_time, config, self.data_provider)
            if(ic1_found):
                continue
            
            ic_trade = await IronCondor1._find_iron_trade(spx_ohlc_data, spy_ohlc_data, i, strategy, 
                                                     date, current_price, current_bar_time,
                                                     self.data_provider)
            if ic_trade:
                trades.append(ic_trade)
                active_iron_condors.append(ic_trade)
                ic1_found = True 
                if isinstance(date, datetime):
                   option_date = date
                else:
                   option_date = datetime.combine(date, datetime.min.time())
                
                straddle_trade = await Straddle1._execute_straddle(
                                option_date,
                                current_bar_time,
                                current_price,
                                strategy,
                                ic_trade,
                                self.data_provider
                )
                            
                if straddle_trade:
                    trades.append(straddle_trade)
                    open_straddles.append(straddle_trade)
                    logger.info(f"Entered Straddle 1 at {current_bar_time}.")
        
        # Close any remaining open trades at expiry
        for trade in trades:
            if trade.status == "OPEN":
                await trade._close_trade_at_expiry(spx_ohlc_data, date, config)
        
        logger.info(f"Day {date.strftime('%Y-%m-%d')} completed: {len([t for t in trades if t.trade_type == 'Iron Condor 1'])} Iron Condors, {len([t for t in trades if t.trade_type == 'Straddle 1'])} Straddles")
        return trades