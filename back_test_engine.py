import sys
import os
import json
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple, Optional, Any
import logging
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import asyncio
import aiohttp
from collections import defaultdict
import pickle
import gzip
from mock_data_provider import MockDataProvider

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== Configuration Classes ====================

from back_test_config import BacktestConfig
from polygon_data_provider import PolygonDataProvider
from strategy_config import StrategyConfig
from trade import Trade

class BacktestEngine:
    """Complete backtesting engine implementation"""
    
    def __init__(self, data_provider: MockDataProvider):
        self.data_provider = data_provider
        self.trades: List[Trade] = []
        self.daily_pnl: Dict[datetime, float] = {}
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.current_capital: float = 0.0
        
    async def run_backtest(self, config: BacktestConfig, strategy: StrategyConfig) -> Dict[str, Any]:
        """Run complete backtest"""
        logger.info(f"Starting backtest from {config.start_date} to {config.end_date}")
        
        self.current_capital = config.initial_capital
        self.trades = []
        self.daily_pnl = {}
        self.equity_curve = [(config.start_date, config.initial_capital)]
        
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
        """Run strategy for a single day"""
        trades = []
        
        # Get market data
        spx_data = await self.data_provider.get_spx_data(date, "5min")
        spy_data = await self.data_provider.get_spy_volume_data(date)
        
        if spx_data.empty or spy_data.empty:
            logger.warning(f"No data available for {date}")
            return trades
        
        # Check for entry signals throughout the day
        market_open = time(9, 30)
        market_close = time(16, 0)
        if isinstance(date, datetime):
           dt = date
        else:
           dt = datetime.combine(date, datetime.min.time())
        
        for i in range(len(spx_data)):
            current_time = spx_data.iloc[i]['timestamp'].time()
            
            # Only trade during market hours
            if current_time < market_open or current_time >= market_close:
                continue
            
            # Check entry conditions
            signals = self._check_entry_signals(spx_data, spy_data, i, strategy)
            
            if signals['entry_signal']:
                # Find option strikes
                current_price = spx_data.iloc[i]['close']
                strikes = self._find_iron_condor_strikes(current_price, strategy)
                
                if strikes:
                    # Get option quotes
                    expiration = dt.replace(hour=16, minute=0, second=0)
                    contracts = self._create_option_contracts(strikes, expiration)
                    
                    # Create trade
                    trade = await self._execute_iron_condor(
                        date, spx_data.iloc[i]['timestamp'], 
                        contracts, strategy, config, signals
                    )
                    
                    if trade:
                        trades.append(trade)
                        logger.info(f"Entered Iron Condor at {current_time}")
        
        # Close all trades at market close
        for trade in trades:
            if trade.status == "OPEN":
                await self._close_trade_at_expiry(trade, date, config)
        
        return trades
    
    def _check_entry_signals(self, spx_data: pd.DataFrame, spy_data: pd.DataFrame, 
                            current_idx: int, strategy: StrategyConfig) -> Dict[str, Any]:
        """Check if entry conditions are met"""
        signals = {
            'entry_signal': False,
            'volume_condition': False,
            'direction_condition': False,
            'range_condition': False,
            'details': {}
        }
        
        # Need enough history
        if current_idx < max(strategy.consecutive_candles, strategy.lookback_candles, 
                           strategy.avg_range_candles):
            return signals
        
        # Condition 1: Volume check
        if not spy_data.empty:
            first_candle_volume = spy_data.iloc[0]['volume']
            volume_threshold = first_candle_volume * strategy.volume_threshold
            
            volume_ok = True
            for j in range(strategy.consecutive_candles):
                idx = current_idx - strategy.consecutive_candles + j + 1
                current_volume = spy_data.iloc[idx]['volume'] if idx < len(spy_data) else 0
                if current_volume > volume_threshold:
                    volume_ok = False
                    break
            
            signals['volume_condition'] = volume_ok
        
        # Condition 2: Direction check
        directions = []
        for j in range(strategy.lookback_candles):
            idx = current_idx - strategy.lookback_candles + j + 1
            if idx >= 0 and idx < len(spx_data):
                close = spx_data.iloc[idx]['close']
                open_price = spx_data.iloc[idx]['open']
                directions.append(1 if close > open_price else -1)
        
        if directions:
            all_same = all(d == directions[0] for d in directions)
            signals['direction_condition'] = not all_same
        
        # Condition 3: Range check
        recent_ranges = []
        for j in range(strategy.avg_range_candles):
            idx = current_idx - strategy.avg_range_candles + j + 1
            if idx >= 0 and idx < len(spx_data):
                high = spx_data.iloc[idx]['high']
                low = spx_data.iloc[idx]['low']
                recent_ranges.append(high - low)
        
        if recent_ranges:
            avg_recent_range = np.mean(recent_ranges)
            
            # Calculate average range for the day
            all_ranges = []
            for j in range(len(spx_data[:current_idx+1])):
                high = spx_data.iloc[j]['high']
                low = spx_data.iloc[j]['low']
                all_ranges.append(high - low)
            
            if all_ranges:
                avg_day_range = np.mean(all_ranges)
                range_threshold = avg_day_range * strategy.range_threshold
                signals['range_condition'] = avg_recent_range < range_threshold
        
        # All conditions must be met
        signals['entry_signal'] = (signals['volume_condition'] and 
                                 signals['direction_condition'] and 
                                 signals['range_condition'])
        
        return signals
    
    def _find_iron_condor_strikes(self, current_price: float, 
                                 strategy: StrategyConfig) -> Optional[Dict[str, float]]:
        """Find strikes for Iron Condor with target win/loss ratio"""
        # Round to nearest 5
        atm_strike = round(current_price / 5) * 5
        
        # For 1.5:1 win/loss ratio, we need specific strike distances
        # This is simplified - in reality would use option pricing models
        strike_distance = 25  # Start with 25 points
        
        strikes = {
            'short_call': atm_strike,
            'short_put': atm_strike,
            'long_call': atm_strike + strike_distance,
            'long_put': atm_strike - strike_distance
        }
        
        return strikes
    
    def _create_option_contracts(self, strikes: Dict[str, float], 
                               expiration: datetime) -> Dict[str, str]:
        """Create option contract symbols"""
        exp_str = expiration.strftime('%y%m%d')
        
        contracts = {
            'short_call': f"O:SPXW{exp_str}C{int(strikes['short_call']):08d}",
            'short_put': f"O:SPXW{exp_str}P{int(strikes['short_put']):08d}",
            'long_call': f"O:SPXW{exp_str}C{int(strikes['long_call']):08d}",
            'long_put': f"O:SPXW{exp_str}P{int(strikes['long_put']):08d}"
        }
        
        return contracts
    
    async def _execute_iron_condor(self, date: datetime, entry_time: datetime,
                                  contracts: Dict[str, str], strategy: StrategyConfig,
                                  config: BacktestConfig, signals: Dict) -> Optional[Trade]:
        """Execute Iron Condor trade"""
        # Get option quotes
        quotes = await self.data_provider.get_option_quotes(list(contracts.values()), entry_time)
        
        # Check if we have all quotes
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing option quotes, skipping trade")
            return None
        
        # Build trade positions
        trade_contracts = {}
        
        # Short positions
        for leg, contract in [('short_call', contracts['short_call']), 
                            ('short_put', contracts['short_put'])]:
            quote = quotes[contract]
            if config.use_bid_ask:
                price = quote['bid']  # Sell at bid
            else:
                price = (quote['bid'] + quote['ask']) / 2
            
            trade_contracts[contract] = {
                'position': -strategy.trade_size,
                'entry_price': price,
                'leg_type': leg
            }
        
        # Long positions
        for leg, contract in [('long_call', contracts['long_call']), 
                            ('long_put', contracts['long_put'])]:
            quote = quotes[contract]
            if config.use_bid_ask:
                price = quote['ask']  # Buy at ask
            else:
                price = (quote['bid'] + quote['ask']) / 2
            
            trade_contracts[contract] = {
                'position': strategy.trade_size,
                'entry_price': price,
                'leg_type': leg
            }
        
        # Create trade
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Iron Condor",
            contracts=trade_contracts,
            size=strategy.trade_size,
            entry_signals=signals
        )
        
        return trade
    
    async def _close_trade_at_expiry(self, trade: Trade, date: datetime, 
                                   config: BacktestConfig):
        """Close trade at market close using settlement prices"""
        # Get SPX close price
        spx_data = await self.data_provider.get_spx_data(date, "minute")
        if spx_data.empty:
            logger.error(f"No SPX data for settlement on {date}")
            return
        
        # Use official close price
        settlement_price = spx_data.iloc[-1]['close']
        if isinstance(date, datetime):
           dt = date
        else:
           dt = datetime.combine(date, datetime.min.time())
        exit_time = dt.replace(hour=16, minute=0, second=0)
        
        # Calculate settlement values for each option
        exit_prices = {}
        
        for contract, details in trade.contracts.items():
            leg_type = details['leg_type']
            
            # Extract strike from contract symbol
            strike_str = contract[-8:]
            strike = int(strike_str)
            
            # Calculate intrinsic value at expiration
            if 'call' in leg_type:
                value = max(0, settlement_price - strike)
            else:  # put
                value = max(0, strike - settlement_price)
            
            exit_prices[contract] = value
        
        # Calculate P&L
        trade.calculate_pnl(exit_prices, config.commission_per_contract)
        trade.exit_time = exit_time
        trade.status = "CLOSED"
        trade.exit_signals = {'settlement_price': settlement_price}
        
        logger.info(f"Closed trade at settlement: P&L = ${trade.pnl:.2f}")
    
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
                'return_pct': 0.0
            }
        
        # Basic statistics
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
        running_max = np.maximum.accumulate(equity_values)
        drawdowns = (equity_values - running_max) / running_max
        max_drawdown = abs(np.min(drawdowns)) if len(drawdowns) > 0 else 0
        
        # Sharpe ratio (simplified - assuming 252 trading days)
        if len(self.daily_pnl) > 1:
            daily_returns = list(self.daily_pnl.values())
            sharpe_ratio = np.sqrt(252) * np.mean(daily_returns) / np.std(daily_returns) if np.std(daily_returns) > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Total return
        return_pct = ((self.current_capital - config.initial_capital) / config.initial_capital) * 100
        
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
            'worst_trade': min(self.trades, key=lambda t: t.pnl).pnl if self.trades else 0
        }