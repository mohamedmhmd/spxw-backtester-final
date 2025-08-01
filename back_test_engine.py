import sys
import os
import json
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple, Optional, Any, Union
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

# Import configurations and providers
from back_test_config import BacktestConfig
from polygon_data_provider import PolygonDataProvider
from strategy_config import StrategyConfig
from trade import Trade

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
    
    def _ensure_5min_bars(self, df: pd.DataFrame, has_ohlc: bool = True) -> pd.DataFrame:
        """Convert any timeframe data to 5-minute bars"""
        if df.empty:
            return df
            
        df = df.copy()
        if 'timestamp' in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index('timestamp')
        
        if has_ohlc:
            # Resample OHLCV data
            resampled = df.resample('5T').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
        else:
            # Resample volume-only data
            resampled = df.resample('5T').agg({
                'volume': 'sum'
            }).dropna()
        
        return resampled.reset_index()
    
    async def _run_daily_strategy(self, date: datetime, config: BacktestConfig, 
                                  strategy: StrategyConfig) -> List[Trade]:
        """Run strategy for a single day with both Iron Condor and Straddle"""
        trades = []
        self.open_straddles = []  # Reset for new day
        
        # Get market data
        spx_data = await self.data_provider.get_spx_data(date, config.data_granularity)
        spy_data = await self.data_provider.get_spy_volume_data(date, config.data_granularity)
        
        if spx_data.empty or spy_data.empty:
            logger.warning(f"No data available for {date}")
            return trades
        
        # Convert to 5-minute bars
        spx_5min = self._ensure_5min_bars(spx_data, has_ohlc=True)
        spy_5min = self._ensure_5min_bars(spy_data, has_ohlc=False)
        
        # Ensure we have the same timestamps
        merged_data = pd.merge(
            spx_5min, 
            spy_5min, 
            on='timestamp', 
            how='inner',
            suffixes=('_spx', '_spy')
        )
        
        if merged_data.empty:
            logger.warning(f"No overlapping data for {date}")
            return trades
        
        # Need minimum bars for all conditions
        min_bars_needed = max(
            strategy.consecutive_candles,
            strategy.lookback_candles,
            strategy.avg_range_candles
        )
        
        if len(merged_data) < min_bars_needed:
            logger.warning(f"Insufficient bars for {date}: {len(merged_data)} < {min_bars_needed}")
            return trades
        
        # Track if we've entered trades today
        iron_condor_entered = False
        
        # Check for entry signals and manage trades throughout the day
        for i in range(min_bars_needed, len(merged_data)):
            current_bar_time = merged_data.iloc[i]['timestamp']
            current_price = merged_data.iloc[i]['close']
            
            # Only trade during regular hours (9:30 AM - 4:00 PM)
            if current_bar_time.time() < time(9, 30) or current_bar_time.time() >= time(16, 0):
                continue
            
            # Check for Straddle exit conditions first
            await self._check_straddle_exits(current_price, current_bar_time, config)
            
            
            # Check entry conditions if we haven't entered yet
            if not iron_condor_entered:
                signals = self._check_entry_signals_5min(merged_data, i, strategy)
                
                if signals['entry_signal']:
                    # Prepare for option trades
                    if isinstance(date, datetime):
                        option_date = date
                    else:
                        option_date = datetime.combine(date, datetime.min.time())
                    
                    # Get option chain
                    option_chain = await self.data_provider.get_option_chain(
                        option_date, 
                        option_date,  # 0DTE
                        "SPX",
                        config.data_granularity
                    )
                    
                    if option_chain.empty:
                        logger.warning(f"No option chain data at {current_bar_time}")
                        continue
                    
                    # Find Iron Condor strikes
                    ic_result = self._find_iron_condor_strikes(current_price, option_chain, strategy)
                    
                    if ic_result:
                        ic_strikes = {
                            'short_call': ic_result['short_call'],
                            'short_put': ic_result['short_put'],
                            'long_call': ic_result['long_call'],
                            'long_put': ic_result['long_put']
                        }
                        
                        # Create option contracts for Iron Condor
                        ic_contracts = self._create_option_contracts(ic_strikes, option_date)
                        
                        # Get quotes and calculate net credit BEFORE executing
                        ic_quotes = await self.data_provider.get_option_quotes(
                            list(ic_contracts.values()), current_bar_time
                        )
                        
                        # Calculate net credit
                        net_credit = self._calculate_iron_condor_credit(ic_quotes, ic_contracts, config)
                        
                        if net_credit > 0:
                            # Execute Iron Condor trade
                            ic_trade = await self._execute_iron_condor(
                                option_date,
                                current_bar_time,
                                ic_contracts,
                                strategy,
                                config,
                                signals,
                                net_credit
                            )
                            
                            if ic_trade:
                                trades.append(ic_trade)
                                iron_condor_entered = True
                                logger.info(f"Entered Iron Condor at {current_bar_time}: {ic_strikes}")
                                
                                # Calculate Straddle strikes based on Iron Condor credit
                                straddle_distance = net_credit * strategy.straddle_distance_multiplier
                                straddle_strike = self._calculate_straddle_strike(
                                    current_price, straddle_distance
                                )
                                
                                # Execute Straddle trade
                                straddle_trade = await self._execute_straddle(
                                    option_date,
                                    current_bar_time,
                                    straddle_strike,
                                    option_chain,
                                    strategy,
                                    config,
                                    ic_trade
                                )
                                
                                if straddle_trade:
                                    trades.append(straddle_trade)
                                    self.open_straddles.append(straddle_trade)
                                    logger.info(f"Entered Straddle at {current_bar_time}: Strike={straddle_strike}")
        
        # Close all trades at market close
        for trade in trades:
            if trade.status == "OPEN":
                await self._close_trade_at_expiry(trade, date, config)
        
        return trades
    
    def _check_entry_signals_5min(self, merged_data: pd.DataFrame, current_idx: int, 
                                  strategy: StrategyConfig) -> Dict[str, Any]:
        """Check entry signals using 5-minute bars only"""
        signals = {
            'entry_signal': False,
            'volume_condition': False,
            'direction_condition': False,
            'range_condition': False,
            'details': {}
        }
        
        # Condition 1: Volume check (consecutive candles below threshold)
        first_candle_volume = merged_data.iloc[0]['volume_spy']
        volume_threshold = first_candle_volume * strategy.volume_threshold
        
        volume_ok = True
        volume_checks = []
        for j in range(strategy.consecutive_candles):
            idx = current_idx - strategy.consecutive_candles + j + 1
            if idx >= 0 and idx < len(merged_data):
                current_volume = merged_data.iloc[idx]['volume_spy']
                volume_checks.append(current_volume)
                if current_volume > volume_threshold:
                    volume_ok = False
                    
        signals['volume_condition'] = volume_ok
        signals['details']['volume_checks'] = volume_checks
        signals['details']['volume_threshold'] = volume_threshold
        
        # Condition 2: Direction check (not all candles in same direction)
        directions = []
        for j in range(strategy.lookback_candles):
            idx = current_idx - strategy.lookback_candles + j + 1
            if idx >= 0 and idx < len(merged_data):
                open_price = merged_data.iloc[idx]['open']
                close_price = merged_data.iloc[idx]['close']
                directions.append(1 if close_price > open_price else -1)
        
        if directions:
            all_same = all(d == directions[0] for d in directions)
            signals['direction_condition'] = not all_same
            signals['details']['directions'] = directions
        
        # Condition 3: Range check (recent range below threshold)
        recent_ranges = []
        for j in range(strategy.avg_range_candles):
            idx = current_idx - strategy.avg_range_candles + j + 1
            if idx >= 0 and idx < len(merged_data):
                high = merged_data.iloc[idx]['high']
                low = merged_data.iloc[idx]['low']
                recent_ranges.append(high - low)
        
        if recent_ranges:
            avg_recent_range = np.mean(recent_ranges)
            
            # Calculate average range for all candles up to current
            all_ranges = []
            for j in range(current_idx + 1):
                high = merged_data.iloc[j]['high']
                low = merged_data.iloc[j]['low']
                all_ranges.append(high - low)
            
            if all_ranges:
                avg_day_range = np.mean(all_ranges)
                range_threshold = avg_day_range * strategy.range_threshold
                signals['range_condition'] = avg_recent_range < range_threshold
                signals['details']['avg_recent_range'] = avg_recent_range
                signals['details']['avg_day_range'] = avg_day_range
                signals['details']['range_threshold'] = range_threshold
        
        # All conditions must be met
        signals['entry_signal'] = (
            signals['volume_condition'] and 
            signals['direction_condition'] and 
            signals['range_condition']
        )
        
        return signals
    
    def _find_iron_condor_strikes(self, current_price: float, option_chain: pd.DataFrame,
                                 strategy: StrategyConfig) -> Optional[Dict[str, float]]:
        """Find Iron Condor strikes targeting specific win/loss ratio"""
        # Round ATM to nearest 5
        atm_strike = int(round(current_price / 5) * 5)
        available_strikes = sorted(option_chain['strike'].unique())

        # Configurable search window
        min_wing = getattr(strategy, 'min_wing_width', 15)
        max_wing = getattr(strategy, 'max_wing_width', 70)
        step = getattr(strategy, 'wing_width_step', 5)

        target_ratio = getattr(strategy, 'target_win_loss_ratio', 1.5)
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

            # Calculate net credit
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
            logger.info(f"Selected Iron Condor: Wing=${best_combo['distance']}, "
                       f"Credit=${best_combo['net_credit']:.2f}, Ratio={best_combo['ratio']:.2f}")
            return best_combo
        
        return None
    
    def _calculate_iron_condor_credit(self, quotes: Dict[str, Dict], contracts: Dict[str, str],
                                    config: BacktestConfig) -> float:
        """Calculate net credit for Iron Condor based on actual execution prices"""
        total_credit = 0
        total_debit = 0
        
        # Short positions (sell at bid)
        for leg in ['short_call', 'short_put']:
            contract = contracts[leg]
            if contract in quotes:
                price = quotes[contract]['bid'] if config.use_bid_ask else (quotes[contract]['bid'] + quotes[contract]['ask']) / 2
                total_credit += price
        
        # Long positions (buy at ask)
        for leg in ['long_call', 'long_put']:
            contract = contracts[leg]
            if contract in quotes:
                price = quotes[contract]['ask'] if config.use_bid_ask else (quotes[contract]['bid'] + quotes[contract]['ask']) / 2
                total_debit += price
        
        return total_credit - total_debit
    
    def _calculate_straddle_strike(self, current_price: float, distance: float) -> int:
        """Calculate straddle strike based on distance from current price"""
        # Distance is in dollar terms from Iron Condor credit
        # Round to nearest 5
        straddle_strike = round((current_price + distance) / 5) * 5
        return int(straddle_strike)
    
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
                                  config: BacktestConfig, signals: Dict,
                                  net_credit: float) -> Optional[Trade]:
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
        
        # Create trade with metadata
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Iron Condor",
            contracts=trade_contracts,
            size=strategy.trade_size,
            entry_signals=signals,
            metadata={
                'net_credit': net_credit,
                'strategy_name': 'iron_1'
            }
        )
        
        return trade
    
    async def _execute_straddle(self, date: datetime, entry_time: datetime,
                               straddle_strike: int, option_chain: pd.DataFrame,
                               strategy: StrategyConfig, config: BacktestConfig,
                               iron_condor_trade: Trade) -> Optional[Trade]:
        """Execute Straddle trade"""
        # Create straddle contracts
        exp_str = date.strftime('%y%m%d')
        contracts = {
            'straddle_call': f"O:SPXW{exp_str}C{straddle_strike:08d}",
            'straddle_put': f"O:SPXW{exp_str}P{straddle_strike:08d}"
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
            if config.use_bid_ask:
                price = quote['ask']  # Buy at ask
            else:
                price = (quote['bid'] + quote['ask']) / 2
            
            trade_contracts[contract] = {
                'position': strategy.trade_size,  # Long position
                'entry_price': price,
                'leg_type': leg,
                'strike': straddle_strike,
                'remaining_position': strategy.trade_size  # Track for partial exits
            }
            total_premium += price * strategy.trade_size
        
        # Create straddle trade
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type="Straddle",
            contracts=trade_contracts,
            size=strategy.trade_size,
            entry_signals={'triggered_by': 'iron_condor'},
            metadata={
                'strategy_name': 'straddle_1',
                'iron_condor_ref': iron_condor_trade,
                'straddle_strike': straddle_strike,
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
            
            straddle_strike = straddle.metadata['straddle_strike']
            exit_percentage = straddle.metadata['exit_percentage']
            exit_multiplier = straddle.metadata['exit_multiplier']
            
            # Check if price hit the straddle strike
            if abs(current_price - straddle_strike) < 0.01:  # Within penny of strike
                # Determine which leg is ITM
                for contract, details in straddle.contracts.items():
                    if details['remaining_position'] <= 0:
                        continue
                    
                    leg_type = details['leg_type']
                    entry_price = details['entry_price']
                    
                    # Check which leg to potentially exit
                    should_exit = False
                    if 'call' in leg_type and current_price >= straddle_strike:
                        should_exit = True
                    elif 'put' in leg_type and current_price <= straddle_strike:
                        should_exit = True
                    
                    if should_exit:
                        # Get current quote
                        quotes = await self.data_provider.get_option_quotes([contract], current_time)
                        if contract in quotes:
                            current_quote = quotes[contract]
                            exit_price = current_quote['bid'] if config.use_bid_ask else (current_quote['bid'] + current_quote['ask']) / 2
                            
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
        
        # For straddles, account for any partial exits
        if trade.trade_type == "Straddle":
            # Calculate P&L only for remaining positions
            total_pnl = trade.metadata.get('partial_pnl', 0)  # Start with partial exit P&L
            
            for contract, details in trade.contracts.items():
                remaining = details.get('remaining_position', details['position'])
                if remaining > 0:
                    entry_price = details['entry_price']
                    exit_price = exit_prices[contract]
                    position_pnl = (exit_price - entry_price) * remaining * 100  # SPX multiplier
                    position_pnl -= config.commission_per_contract * remaining  # Exit commission
                    total_pnl += position_pnl
            
            # Account for entry commissions
            total_pnl -= config.commission_per_contract * trade.size * 2  # 2 legs
            
            trade.pnl = total_pnl
        else:
            # Standard P&L calculation for Iron Condor
            trade.calculate_pnl(exit_prices, config.commission_per_contract)
        
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