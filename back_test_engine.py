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
        spx_data = await self.data_provider.get_spx_data(date, config.data_granularity)
        spy_data = await self.data_provider.get_spy_volume_data(date, config.data_granularity)
        
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
                option_chain = await self.data_provider.get_option_chain(date, date, 
                              "SPX", config.data_granularity)
                strikes = self._find_iron_condor_strikes(current_price, option_chain, strategy)
                
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
    
    def _check_entry_signals(
        self, 
        spx_data: pd.DataFrame, 
        spy_data: pd.DataFrame, 
        current_idx: int, 
        strategy: 'StrategyConfig',
        bar_interval: str = "5T"
    ) -> Dict[str, Any]:
        """
        Check if entry conditions are met, always using 5-minute bars even if
        source data is tick/second/minute level.

        Returns a dictionary with signal booleans and details.
        """
        import numpy as np

        # Initialize signal dictionary
        signals = {
            'entry_signal': False,
            'volume_condition': False,
            'direction_condition': False,
            'range_condition': False,
            'details': {}
        }

        # --- Step 1: Ensure 5-min bars ---
        def _ensure_5min(df, ohlc_cols=None):
            """
            Resample the input DataFrame to 5-minute bars.
            If ohlc_cols is provided, aggregate OHLCV; otherwise, just volume.
            """
            df = df.copy()
            if not pd.infer_freq(df['timestamp']):
                df = df.set_index('timestamp')
            if ohlc_cols:  # For SPX (OHLCV)
                return df.resample(bar_interval).agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna().reset_index()
            else:          # For SPY (volume only)
                return df.resample(bar_interval).agg({'volume': 'sum'}).dropna().reset_index()

        # Convert SPX and SPY data to 5-minute bars if needed
        if 'open' in spx_data.columns and 'high' in spx_data.columns and 'low' in spx_data.columns and 'close' in spx_data.columns:
            spx_bars = _ensure_5min(spx_data, ohlc_cols=True)
        else:
            raise ValueError("SPX data missing OHLC columns")
        if 'volume' in spy_data.columns:
            spy_bars = _ensure_5min(spy_data)
        else:
            raise ValueError("SPY data missing volume column")

        # Remap current_idx to new bars (if originally called from tick index)
        # If not enough bars, return default signals
        if len(spx_bars) <= max(
            strategy.consecutive_candles,
            strategy.lookback_candles,
            strategy.avg_range_candles
        ):
            return signals
        # Always use most recent bar for signal calculation
        idx = len(spx_bars) - 1

        # --- Volume Condition ---
        # Check if the last N consecutive SPY 5-min bars have volume below threshold
        if not spy_bars.empty:
            first_candle_volume = spy_bars.iloc[0]['volume']
            volume_threshold = first_candle_volume * strategy.volume_threshold
            volume_ok = True
            for j in range(strategy.consecutive_candles):
                k = idx - strategy.consecutive_candles + j + 1
                current_volume = spy_bars.iloc[k]['volume'] if k < len(spy_bars) else 0
                if current_volume > volume_threshold:
                    volume_ok = False
                    break
            signals['volume_condition'] = volume_ok

        # --- Direction Condition ---
        # Check if all last N bars are not the same direction (not all up or all down)
        directions = []
        for j in range(strategy.lookback_candles):
            k = idx - strategy.lookback_candles + j + 1
            if k >= 0 and k < len(spx_bars):
                close = spx_bars.iloc[k]['close']
                open_price = spx_bars.iloc[k]['open']
                directions.append(1 if close > open_price else -1)
        if directions:
            all_same = all(d == directions[0] for d in directions)
            signals['direction_condition'] = not all_same

        # --- Range Condition ---
        # Check if the average range of recent bars is below a threshold
        recent_ranges = []
        for j in range(strategy.avg_range_candles):
            k = idx - strategy.avg_range_candles + j + 1
            if k >= 0 and k < len(spx_bars):
                high = spx_bars.iloc[k]['high']
                low = spx_bars.iloc[k]['low']
                recent_ranges.append(high - low)
        if recent_ranges:
            avg_recent_range = np.mean(recent_ranges)
            all_ranges = [spx_bars.iloc[m]['high'] - spx_bars.iloc[m]['low'] for m in range(idx+1)]
            if all_ranges:
                avg_day_range = np.mean(all_ranges)
                range_threshold = avg_day_range * strategy.range_threshold
                signals['range_condition'] = avg_recent_range < range_threshold

        # --- Final signal ---
        # Entry signal is True only if all conditions are met
        signals['entry_signal'] = (
            signals['volume_condition'] and
            signals['direction_condition'] and
            signals['range_condition']
        )
        return signals

    def _check_entry_signals(
        self, 
        spx_data: pd.DataFrame, 
        spy_data: pd.DataFrame, 
        current_idx: int, 
        strategy: 'StrategyConfig',
        bar_interval: str = "5min"
    ) -> Dict[str, Any]:
        """
        Check if entry conditions are met, always using 5-minute bars even if
        source data is tick/second/minute level.

        Returns a dictionary with signal booleans and details.
        """
        signals = {
            'entry_signal': False,
            'volume_condition': False,
            'direction_condition': False,
            'range_condition': False,
            'details': {}
        }

        # --- Step 1: Ensure 5-min bars ---
        def _ensure_5min(df : pd.DataFrame, ohlc_cols=None):
            df = df.copy()
            if not isinstance(df.index, pd.DatetimeIndex):
                 df = df.set_index('timestamp')
            if ohlc_cols:  # For SPX
                return df.resample(bar_interval).agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna().reset_index()
            else:          # For SPY (volume only)
                return df.resample(bar_interval).agg({'volume': 'sum'}).dropna().reset_index()

        # Convert to 5min bars if needed
        if 'open' in spx_data.columns and 'high' in spx_data.columns and 'low' in spx_data.columns and 'close' in spx_data.columns:
            spx_bars = _ensure_5min(spx_data, ohlc_cols=True)
        else:
            raise ValueError("SPX data missing OHLC columns")
        if 'volume' in spy_data.columns:
            spy_bars = _ensure_5min(spy_data)
        else:
            raise ValueError("SPY data missing volume column")

        # Remap current_idx to new bars (if originally called from tick index)
        if len(spx_bars) <= max(
            strategy.consecutive_candles,
            strategy.lookback_candles,
            strategy.avg_range_candles
        ):
            return signals
        # Always use most recent bar
        idx = len(spx_bars) - 1

        # --- Volume Condition ---
        if not spy_bars.empty:
            first_candle_volume = spy_bars.iloc[0]['volume']
            volume_threshold = first_candle_volume * strategy.volume_threshold
            volume_ok = True
            for j in range(strategy.consecutive_candles):
                k = idx - strategy.consecutive_candles + j + 1
                current_volume = spy_bars.iloc[k]['volume'] if k < len(spy_bars) else 0
                if current_volume > volume_threshold:
                    volume_ok = False
                    break
            signals['volume_condition'] = volume_ok

        # --- Direction Condition ---
        directions = []
        for j in range(strategy.lookback_candles):
            k = idx - strategy.lookback_candles + j + 1
            if k >= 0 and k < len(spx_bars):
                close = spx_bars.iloc[k]['close']
                open_price = spx_bars.iloc[k]['open']
                directions.append(1 if close > open_price else -1)
        if directions:
            all_same = all(d == directions[0] for d in directions)
            signals['direction_condition'] = not all_same

        # --- Range Condition ---
        recent_ranges = []
        for j in range(strategy.avg_range_candles):
            k = idx - strategy.avg_range_candles + j + 1
            if k >= 0 and k < len(spx_bars):
                high = spx_bars.iloc[k]['high']
                low = spx_bars.iloc[k]['low']
                recent_ranges.append(high - low)
        if recent_ranges:
            avg_recent_range = np.mean(recent_ranges)
            all_ranges = [spx_bars.iloc[m]['high'] - spx_bars.iloc[m]['low'] for m in range(idx+1)]
            if all_ranges:
                avg_day_range = np.mean(all_ranges)
                range_threshold = avg_day_range * strategy.range_threshold
                signals['range_condition'] = avg_recent_range < range_threshold

        # --- Final signal ---
        signals['entry_signal'] = (
            signals['volume_condition'] and
            signals['direction_condition'] and
            signals['range_condition']
        )
        return signals



    
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
    
    def _find_iron_condor_strikes(
        self,
        current_price: float,
        option_chain: pd.DataFrame,
        strategy: "StrategyConfig"
    ) -> Optional[Dict[str, float]]:
        """
        Find Iron Condor strikes for a target win/loss ratio using option prices
        from the provided mock option_chain DataFrame.

        Args:
            current_price (float): The current underlying price.
            option_chain (pd.DataFrame): DataFrame with columns ['strike', 'type', 'bid', 'ask'].
            strategy (StrategyConfig): Strategy configuration object.

        Returns:
            Optional[Dict[str, float]]: Dict of strike prices for each leg, or None if not possible.
        """
        # Round ATM to nearest 5
        atm_strike = int(round(current_price / 5) * 5)
        available_strikes = sorted(option_chain['strike'].unique())

        # Configurable search window
        min_wing = getattr(strategy, 'min_wing', 15)
        max_wing = getattr(strategy, 'max_wing', 70)
        step = 5

        target_ratio = getattr(strategy, 'win_loss_ratio', 1.5)
        best_combo = None
        best_diff = float('inf')

        for d in range(min_wing, max_wing+1, step):
            sc = atm_strike
            lc = atm_strike + d
            sp = atm_strike
            lp = atm_strike - d
            # All strikes must exist
            if not all(s in available_strikes for s in [lc, sc, sp, lp]):
                continue

            # Helper to get mid quote
            def get_mid(cp, strike):
                row = option_chain[(option_chain['strike']==strike) & (option_chain['type']==cp)]
                if not row.empty:
                    bid, ask = row.iloc[0]['bid'], row.iloc[0]['ask']
                    return (bid + ask) / 2
                return None

            sc_mid = get_mid('C', sc)
            lc_mid = get_mid('C', lc)
            sp_mid = get_mid('P', sp)
            lp_mid = get_mid('P', lp)
            if None in [sc_mid, lc_mid, sp_mid, lp_mid]:
                continue

            # Short at bid (sell), long at ask (buy)
            net_credit = sc_mid + sp_mid - lc_mid - lp_mid
            max_loss = d - net_credit

            # Avoid division by zero/bad combos
            if net_credit <= 0 or max_loss <= 0:
                continue

            ratio = net_credit / max_loss
            diff = abs(ratio - target_ratio)
            if diff < best_diff:
                best_diff = diff
                best_combo = {
                    'short_call': sc,
                    'long_call': lc,
                    'short_put': sp,
                    'long_put': lp,
                    'net_credit': net_credit,
                    'max_loss': max_loss,
                    'ratio': ratio,
                    'distance': d
                }
        if best_combo:
            # Optionally log diagnostics
            print(f"Selected Iron Condor: {best_combo}")
            return {k: best_combo[k] for k in ['short_call', 'long_call', 'short_put', 'long_put']}
        return None
    
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