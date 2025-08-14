from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple, Any, Union
import logging
from data.mock_data_provider import MockDataProvider
from config.back_test_config import BacktestConfig
from data.polygon_data_provider import PolygonDataProvider
from config.strategy_config import StrategyConfig
from trades.trade import Trade
from engine.statistics import Statistics
from trades.iron_condor_1 import IronCondor1
from trades.straddle1 import Straddle1
from utilities.utilities import Utilities

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestEngine:
    """Complete backtesting engine implementation with Iron Condor and Straddle"""
    
    def __init__(self, data_provider: Union[MockDataProvider, PolygonDataProvider]):
        self.data_provider = data_provider
        self.trades: List[Trade] = []
        self.daily_pnl: Dict[datetime, float] = {}
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.current_capital: float = 0.0
        self.open_straddles: List[Trade] = []  # Track open straddles for intraday management
        
    async def run_backtest(self, config: BacktestConfig, strategy: StrategyConfig) -> Dict[str, Any]:
        """Run complete backtest"""
        logger.info(f"Starting backtest from {config.start_date} to {config.end_date}")
        
        self.trades = []
        self.current_capital = config.initial_capital
        self.daily_pnl = {}
        self.equity_curve = [(config.start_date, self.current_capital)]
        
        # Process each trading day
        current_date = config.start_date
        while current_date <= config.end_date:
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue
            
            if not Utilities._is_trading_day(current_date):
                current_date += timedelta(days=1)
                continue
            
            logger.info(f"Processing {current_date.strftime('%Y-%m-%d')}")
            
            # Run strategy for the day
            daily_trades = await self._run_daily_strategy(current_date, config, strategy)
            
            # Calculate daily P&L
            daily_pnl = sum(trade.pnl for trade in daily_trades)
            self.daily_pnl[current_date] = daily_pnl
            self.current_capital += daily_pnl
            self.equity_curve.append((current_date, self.current_capital))
            
            # Add trades to history
            self.trades.extend(daily_trades)
            
            current_date += timedelta(days=1)
        
        # Calculate statistics
        stats = Statistics._calculate_statistics(
            self.trades, 
            self.equity_curve, 
            self.current_capital, 
            self.daily_pnl, 
            config
        )
        
        return {
            'trades': self.trades,
            'daily_pnl': self.daily_pnl,
            'equity_curve': self.equity_curve,
            'statistics': stats
        }
    
    
    
    
    async def _run_daily_strategy(self, date: datetime, config: BacktestConfig, 
                                  strategy: StrategyConfig) -> List[Trade]:
        """Run strategy for a single day with both Iron Condor and Straddle - allows multiple entries per day"""
        trades = []
        self.open_straddles = []
        
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
            
            await Straddle1._check_straddle_exits(self.open_straddles, current_price, current_bar_time, config, self.data_provider)
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
                    self.open_straddles.append(straddle_trade)
                    logger.info(f"Entered Straddle 1 at {current_bar_time}.")
        
        
        for trade in trades:
            if trade.status == "OPEN":
                await trade._close_trade_at_expiry(spy_ohlc_data, date, config)
        
        logger.info(f"Day {date.strftime('%Y-%m-%d')} completed: {len([t for t in trades if t.trade_type == 'Iron Condor 1'])} Iron Condors, {len([t for t in trades if t.trade_type == 'Straddle 1'])} Straddles")
        return trades
    
    
    
    
    
    
    