import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple, Optional, Any, Union
import logging
from data.mock_data_provider import MockDataProvider
from config.back_test_config import BacktestConfig
from data.polygon_data_provider import PolygonDataProvider
from config.strategy_config import StrategyConfig
from config.trade import Trade
from trades.iron_condor_1 import IronCondor1

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
            # Skip weekends
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue
            
            # Check if market is open (skip holidays - simplified)
            if not self._is_trading_day(current_date):
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
        stats = self._calculate_statistics(config)
        
        return {
            'trades': self.trades,
            'daily_pnl': self.daily_pnl,
            'equity_curve': self.equity_curve,
            'statistics': stats
        }
    
    def _is_trading_day(self, date: datetime) -> bool:
        """Check if it's a trading day (simplified - doesn't check all holidays)"""
        # Skip major holidays (simplified list)
        holidays = [
            (1, 1),   # New Year's Day
            (7, 4),   # Independence Day
            (12, 25), # Christmas
        ]
        
        for month, day in holidays:
            if date.month == month and date.day == day:
                return False
        
        return True
    
    
    async def _run_daily_strategy(self, date: datetime, config: BacktestConfig, 
                                  strategy: StrategyConfig) -> List[Trade]:
        """Run strategy for a single day with both Iron Condor and Straddle - allows multiple entries per day"""
        trades = []
        self.open_straddles = []  # Reset for new day
        
        # Get market data
        ohlc_data = await self.data_provider.get_ohlc_data(date)

        #ohlc_data= ohlc_data[ohlc_data['timestamp'].dt.time >=  time(9, 30) and 
                             #ohlc_data['timestamp'].dt.time <= time(16, 0)]
        
        if ohlc_data.empty:
            logger.warning(f"No data available for {date}")
            return trades
        
        # Need minimum bars for all conditions
        min_bars_needed = max(
            strategy.consecutive_candles,
            strategy.lookback_candles,
            strategy.avg_range_candles
        )
        
        if len(ohlc_data) < min_bars_needed:
            logger.warning(f"Insufficient bars for {date}: {len(ohlc_data)} < {min_bars_needed}")
            return trades
        
        # Track active Iron Condor trades for the day
        active_iron_condors = []
        
        ic1_found = False
        # Check for entry signals and manage trades throughout the day
        for i in range(min_bars_needed + 18, len(ohlc_data)):
            current_bar_time = ohlc_data.iloc[i]['timestamp']
            current_price = ohlc_data.iloc[i]['open']
            
            # Only trade during regular hours (9:30 AM - 4:00 PM)
            if current_bar_time.time() < time(9, 30) or current_bar_time.time() >= time(16, 0):
                continue
            
            # Check for Straddle exit conditions first
            await self._check_straddle_exits(current_price, current_bar_time, config)

            if(ic1_found):
                # If we already found an Iron Condor, skip further checks
                continue
            
            ic_trade = await IronCondor1._find_iron_trade(ohlc_data, i, strategy, 
                                                     date, current_price, current_bar_time,
                                                     self.data_provider)
                        
            if ic_trade:
                trades.append(ic_trade)
                active_iron_condors.append(ic_trade)
                ic1_found = True  # Mark that we found an Iron Condor
                # Calculate Straddle strikes based on Iron Condor credit
                net_credit = ic_trade.metadata.get('net_credit')
                straddle_distance = net_credit * strategy.straddle_distance_multiplier
                straddle_strike = self._calculate_straddle_strike(current_price*10, straddle_distance)
                            
                # Execute Straddle trade
                if isinstance(date, datetime):
                   option_date = date
                else:
                   option_date = datetime.combine(date, datetime.min.time())
                
                straddle_trade = await self._execute_straddle(
                                option_date,
                                current_bar_time,
                                current_price*10,
                                straddle_distance,
                                strategy,
                                ic_trade
                )
                            
                if straddle_trade:
                    trades.append(straddle_trade)
                    self.open_straddles.append(straddle_trade)
                    logger.info(f"Entered Straddle #{len(self.open_straddles)} at {current_bar_time}: Strike={straddle_strike}")
        
        # Close all trades at market close
        for trade in trades:
            if trade.status == "OPEN":
                await self._close_trade_at_expiry(ohlc_data, trade, date, config)
        
        logger.info(f"Day {date.strftime('%Y-%m-%d')} completed: {len([t for t in trades if t.trade_type == 'Iron Condor'])} Iron Condors, {len([t for t in trades if t.trade_type == 'Straddle'])} Straddles")
        
        return trades
    
    
    
    
    
    
    
    def _calculate_straddle_strike(self, current_price: float, distance: float) -> int:
        """Calculate straddle strike based on distance from current price"""
        # Distance is in dollar terms from Iron Condor credit
        # Round to nearest 5
        straddle_strike = round((current_price + distance) / 5) * 5
        return int(straddle_strike)
    
    
    
    
    
    async def _execute_straddle(self, date: datetime, entry_time: datetime,
                               current_price: float,
                               straddle_distance : float,
                               strategy: StrategyConfig,
                               iron_condor_trade: Trade) -> Optional[Trade]:
        """Execute Straddle trade"""
        # Create straddle contracts
        exp_str = date.strftime('%y%m%d')
        c_strike = self._calculate_straddle_strike(current_price, straddle_distance)
        p_strike = self._calculate_straddle_strike(current_price, -straddle_distance)
        contracts = {
            'straddle_call': f"O:SPXW{exp_str}C{c_strike*1000:08d}",
            'straddle_put': f"O:SPXW{exp_str}P{p_strike*1000:08d}"
        }
        
        # Get quotes
        quotes = await self.data_provider.get_option_quotes(list(contracts.values()), entry_time)
        
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
                'position': strategy.straddle_1_trade_size,  # Long position
                'entry_price': price,
                'leg_type': leg,
                'strike': straddle_strike,
                'remaining_position': strategy.straddle_1_trade_size  # Track for partial exits
            }
            total_premium += price * strategy.straddle_1_trade_size
        
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
                'exit_multiplier': strategy.straddle_exit_multiplier
            }
        )
        
        return trade
    
    async def _check_straddle_exits(self, current_price: float, current_time: datetime,
                                   config: BacktestConfig):
        """Check if any straddle positions should be partially exited"""
        for straddle in self.open_straddles:
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
                        quotes = await self.data_provider.get_option_quotes([contract], current_time)
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
    
    async def _close_trade_at_expiry(self, ohlc_data : pd.DataFrame, trade: Trade, date: datetime, 
                                   config: BacktestConfig):
        """Close trade at market close using settlement prices"""
        # Get SPX close price
        if ohlc_data.empty:
            logger.error(f"No SPX data for settlement on {date}")
            return
        
        # Use official close price
        settlement_price = ohlc_data.iloc[-1]['close']*10
        if isinstance(date, datetime):
            dt = date
        else:
            dt = datetime.combine(date, datetime.min.time())
        exit_time = dt.replace(hour=16, minute=0, second=0)
        
        # Calculate settlement values for each option

        payoffs = {}
        
        for contract, details in trade.contracts.items():
            leg_type = details['leg_type']
            
            # Extract strike from contract symbol
            strike_str = contract[-8:]
            strike = int(strike_str)/1000
            
            # Calculate intrinsic value at expiration
            if 'call' in leg_type:
                value = max(0, settlement_price - strike)
            else:  # put
                value = max(0, strike - settlement_price)
            
            payoffs[contract] = value
        
        trade.calculate_pnl(payoffs, config.commission_per_contract)
        
        trade.exit_time = exit_time
        trade.status = "CLOSED"
        trade.exit_signals = {'settlement_price': settlement_price}
        
        logger.info(f"Closed {trade.trade_type} at settlement: SPX=${settlement_price:.2f}, P&L=${trade.pnl:.2f}")
    
    def _calculate_statistics(self, config: BacktestConfig) -> Dict[str, Any]:
        """Calculate comprehensive backtest statistics"""
        if not self.trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'return_pct': 0.0,
                'avg_trade_pnl': 0.0,
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'iron_condor_stats': {},
                'straddle_stats': {}
            }
        
        # Separate trades by type
        iron_condor_trades = [t for t in self.trades if t.trade_type == "Iron Condor"]
        straddle_trades = [t for t in self.trades if t.trade_type == "Straddle"]
        
        # Overall statistics
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl < 0]
        
        total_pnl = sum(t.pnl for t in self.trades)
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        
        # Profit factor
        gross_profits = sum(t.pnl for t in winning_trades)
        gross_losses = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profits / gross_losses if gross_losses > 0 else float('inf')
        
        # Maximum drawdown
        equity_values = [eq[1] for eq in self.equity_curve]
        if len(equity_values) > 1:
            running_max = np.maximum.accumulate(equity_values)
            drawdowns = (equity_values - running_max) / running_max
            max_drawdown = abs(np.min(drawdowns))
        else:
            max_drawdown = 0
        
        # Sharpe ratio (simplified - assuming 252 trading days)
        if len(self.daily_pnl) > 1:
            daily_returns = list(self.daily_pnl.values())
            daily_returns_pct = [r / config.initial_capital for r in daily_returns]
            if np.std(daily_returns_pct) > 0:
                sharpe_ratio = np.sqrt(252) * np.mean(daily_returns_pct) / np.std(daily_returns_pct)
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0
        
        # Total return
        return_pct = ((self.current_capital - config.initial_capital) / config.initial_capital) * 100
        
        # Iron Condor specific stats
        ic_stats = {}
        if iron_condor_trades:
            ic_wins = [t for t in iron_condor_trades if t.pnl > 0]
            ic_losses = [t for t in iron_condor_trades if t.pnl < 0]
            ic_stats = {
                'total_trades': len(iron_condor_trades),
                'winning_trades': len(ic_wins),
                'losing_trades': len(ic_losses),
                'win_rate': len(ic_wins) / len(iron_condor_trades),
                'total_pnl': sum(t.pnl for t in iron_condor_trades),
                'avg_pnl': np.mean([t.pnl for t in iron_condor_trades]),
                'avg_credit': np.mean([t.metadata.get('net_credit', 0) for t in iron_condor_trades])
            }
        
        # Straddle specific stats
        straddle_stats = {}
        if straddle_trades:
            straddle_wins = [t for t in straddle_trades if t.pnl > 0]
            straddle_losses = [t for t in straddle_trades if t.pnl < 0]
            
            # Count partial exits
            partial_exit_count = 0
            total_partial_pnl = 0
            for trade in straddle_trades:
                for contract, details in trade.contracts.items():
                    if 'partial_exits' in details:
                        partial_exit_count += len(details['partial_exits'])
                        for exit in details['partial_exits']:
                            total_partial_pnl += exit['pnl']
            
            straddle_stats = {
                'total_trades': len(straddle_trades),
                'winning_trades': len(straddle_wins),
                'losing_trades': len(straddle_losses),
                'win_rate': len(straddle_wins) / len(straddle_trades),
                'total_pnl': sum(t.pnl for t in straddle_trades),
                'avg_pnl': np.mean([t.pnl for t in straddle_trades]),
                'partial_exits': partial_exit_count,
                'partial_exit_pnl': total_partial_pnl
            }
        
        return {
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(self.trades) if self.trades else 0,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'return_pct': return_pct,
            'avg_trade_pnl': total_pnl / len(self.trades) if self.trades else 0,
            'best_trade': max(self.trades, key=lambda t: t.pnl).pnl if self.trades else 0,
            'worst_trade': min(self.trades, key=lambda t: t.pnl).pnl if self.trades else 0,
            'iron_condor_stats': ic_stats,
            'straddle_stats': straddle_stats
        }