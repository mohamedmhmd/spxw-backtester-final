import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import asyncio
import logging
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from data.polygon_data_provider import PolygonDataProvider
from trades.trade import Trade

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class AnalysisConfig:
    """Configuration for options analysis"""
    start_date: datetime
    end_date: datetime
    bar_minutes: int = 5  # 1, 5, 10, etc.
    dte: int = 0  # 0DTE, 1DTE, 2DTE, etc.
    underlying: str = "I:SPX"  # SPX index
    strike_interval: int = 5  # Strike price interval
    max_concurrent_requests: int = 100000000  # Limit concurrent API requests
    batch_size: int = 500000000000  # Size of batches for parallel processing
    ib_enabled: bool = True
    ib_min_wing_width: int = 15
    ib_max_wing_width: int = 70
    ib_target_win_loss_ratio: float = 1.5
    ib_trade_size: int = 10
    ib_commission_per_contract: float = 0.65
    exclude_first_interval: bool = True
    exclude_last_interval: bool = True

class OptionsAnalyzer:
    """
    Optimized analyzer for SPX options data with maximum parallelization.
    """
    
    def __init__(self, polygon_provider: PolygonDataProvider, config: AnalysisConfig):
        self.provider = polygon_provider
        self.config = config
        self.spx_data = {}  # Date -> DataFrame of OHLC data
        self.options_data = {}  # Date -> Dict of options data
        self.implied_moves = []  # List of all implied move calculations
        self.realized_moves = []  # List of all realized move calculations
        self.analysis_results = None  # Final DataFrame with all calculations
        self._semaphore = asyncio.Semaphore(config.max_concurrent_requests)
        
    async def fetch_all_data(self) -> bool:
        """
        Fetch all required SPX and options data in parallel.
        Returns True if successful, False otherwise.
        """
        try:
            # Get list of trading days
            trading_days = self._get_trading_days(self.config.start_date, self.config.end_date)
            logger.info(f"Fetching data for {len(trading_days)} trading days in parallel")
            
            # Create tasks for all days at once with semaphore to control concurrency
            tasks = [self._fetch_day_data(date) for date in trading_days]
            
            # Execute all fetches in parallel with progress tracking
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for date, result in zip(trading_days, results):
                if isinstance(result, Exception):
                    logger.warning(f"Error fetching data for {date}: {result}")
                elif result is not None and not result.empty:
                    self.spx_data[date] = result
                else:
                    logger.warning(f"No SPX data for {date}")
            
            logger.info(f"Successfully fetched SPX data for {len(self.spx_data)} days")
            return len(self.spx_data) > 0
            
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return False
    
    async def _fetch_day_data(self, date: datetime) -> Optional[pd.DataFrame]:
        """Fetch data for a single day with rate limiting"""
        async with self._semaphore:
            try:
                spx_df = await self.provider.get_ohlc_data(
                    date, 
                    self.config.underlying, 
                    self.config.bar_minutes
                )
                if not spx_df.empty:
                    logger.info(f"Fetched SPX data for {date.strftime('%Y-%m-%d')}")
                return spx_df
            except Exception as e:
                logger.error(f"Error fetching data for {date}: {e}")
                return None
    
    def _get_trading_days(self, start_date: datetime, end_date: datetime) -> List[datetime]:
        """Get list of trading days between start and end dates (excluding weekends)"""
        trading_days = []
        current = start_date
        
        while current <= end_date:
            # Skip weekends (Saturday=5, Sunday=6)
            if current.weekday() < 5:
                trading_days.append(current)
            current += timedelta(days=1)
        
        return trading_days
    
    def _get_intervals_per_day(self) -> int:
        """Calculate number of intervals per trading day based on bar_minutes"""
        # Market hours: 9:30 AM - 4:00 PM = 390 minutes
        return 390//self.config.bar_minutes
    
    async def calculate_implied_moves(self) -> pd.DataFrame:
        """
        Calculate implied moves for all time intervals with maximum parallelization.
        Returns DataFrame with columns: date, timestamp, spx_price, implied_move, and IB trade details
        """
        self.reset_analysis()
        if not self.spx_data:
            logger.warning("No SPX data available for analysis")
            return pd.DataFrame()
        
        logger.info("Starting parallel implied move calculations")
        
        # Pre-fetch all closing prices in parallel
        dates_list = list(self.spx_data.keys())
        closing_prices_tasks = [self._get_closing_price(date) for date in dates_list]
        closing_prices_results = await asyncio.gather(*closing_prices_tasks, return_exceptions=True)
        
        # Create closing prices dict, filtering out errors
        closing_prices = {}
        for date, price in zip(dates_list, closing_prices_results):
            if isinstance(price, Exception):
                logger.warning(f"Error getting closing price for {date}: {price}")
            elif price is not None:
                closing_prices[date] = price
            else:
                logger.warning(f"No closing price for {date}, skipping")
        
        # Prepare all calculation tasks and metadata
        calc_tasks = []
        task_metadata = []
        
        for date, spx_df in self.spx_data.items():
            if date not in closing_prices:
                continue
            
            closing_price = closing_prices[date]
            
            # Filter to get data points at specified intervals
            interval_data = self._filter_to_intervals(spx_df)
            
            # Pre-calculate time remaining for all timestamps at once
            timestamps = interval_data['timestamp']
            time_remaining_values = ((timestamps.dt.normalize() + pd.Timedelta(hours=16)) - timestamps).dt.total_seconds() / 60
            time_remaining_values = time_remaining_values.clip(lower=0).astype(int)
            
            # Create tasks for parallel implied move calculations
            for idx, (_, row) in enumerate(interval_data.iterrows()):
                timestamp = row['timestamp']
                spx_price = row['open']
                
                # Create task for implied move calculation
                implied_task = self._calculate_single_implied_move(date, timestamp, spx_price)
                calc_tasks.append(implied_task)
                
                # Create task for Iron Butterfly calculation if enabled
                ib_task = self._calculate_iron_butterfly_trade(date, timestamp, spx_price, closing_price)
                calc_tasks.append(ib_task)
                
                # Store metadata for result construction
                task_metadata.append({
                    'date': date,
                    'timestamp': timestamp,
                    'time_of_day': timestamp.strftime('%H:%M'),
                    'time_remaining_minutes': time_remaining_values.iloc[idx],
                    'spx_price': spx_price,
                    'realized_move': abs(spx_price - closing_price),
                    'closing_price': closing_price,
                    'task_type': 'implied'
                })
                
                task_metadata.append({
                    'date': date,
                    'timestamp': timestamp,
                    'time_of_day': timestamp.strftime('%H:%M'),
                    'time_remaining_minutes': time_remaining_values.iloc[idx],
                    'spx_price': spx_price,
                    'realized_move': abs(spx_price - closing_price),
                    'closing_price': closing_price,
                    'task_type': 'iron_butterfly'
                })
        
        # Execute all calculations in batches for better performance
        if calc_tasks:
            logger.info(f"Executing {len(calc_tasks)} calculations in parallel batches")
            all_results = await self._execute_in_batches(calc_tasks, self.config.batch_size)
            
            # Collect IB results by key for merging
            ib_results_dict = {}
            implied_results = []
            
            for metadata, result in zip(task_metadata, all_results):
                if isinstance(result, Exception):
                    logger.error(f"Error for {metadata['date']} {metadata['time_of_day']}: {result}")
                    continue
                
                if metadata['task_type'] == 'implied':
                    implied_results.append((metadata, result))
                elif metadata['task_type'] == 'iron_butterfly':
                    if result:  # Iron Butterfly result is a dict
                        key = (metadata['date'], metadata['time_of_day'])
                        ib_results_dict[key] = result
            
            # Merge implied results with IB data into single rows
            results = []
            for metadata, implied_move in implied_results:
                row = {
                    'date': metadata['date'],
                    'timestamp': metadata['timestamp'],
                    'time_of_day': metadata['time_of_day'],
                    'time_remaining_minutes': metadata['time_remaining_minutes'],
                    'spx_price': metadata['spx_price'],
                    'realized_move': metadata['realized_move'],
                    'closing_price': metadata['closing_price'],
                    'implied_move': implied_move if implied_move else np.nan,
                }
                
                # Add IB data if available for this timestamp
                key = (metadata['date'], metadata['time_of_day'])
                if key in ib_results_dict:
                    ib_data = ib_results_dict[key]
                    row['ib_atm_strike'] = ib_data.get('ib_atm_strike')
                    row['ib_wing_width'] = ib_data.get('ib_wing_width')
                    row['ib_long_call_strike'] = ib_data.get('ib_long_call_strike')
                    row['ib_long_put_strike'] = ib_data.get('ib_long_put_strike')
                    row['ib_net_premium'] = ib_data.get('ib_net_premium')
                    row['ib_max_loss'] = ib_data.get('ib_max_loss')
                    row['ib_win_loss_ratio'] = ib_data.get('ib_win_loss_ratio')
                    row['ib_trade_size'] = ib_data.get('ib_trade_size')
                    row['ib_unit_pnl'] = ib_data.get('ib_unit_pnl')
                    row['ib_unit_pnl_without_commission'] = ib_data.get('ib_unit_pnl_without_commission')
                    row['ib_total_pnl'] = ib_data.get('ib_total_pnl')
                    row['ib_total_pnl_without_commission'] = ib_data.get('ib_total_pnl_without_commission')
                    row['ib_result'] = ib_data.get('ib_result')
                    # Add after line 248 (inside the "if key in ib_results_dict:" block)
                    row['ib_contract_representation'] = ib_data.get('ib_contract_representation')
                    row['ib_short_call_leg'] = ib_data.get('ib_short_call_leg')
                    row['ib_short_put_leg'] = ib_data.get('ib_short_put_leg')
                    row['ib_long_call_leg'] = ib_data.get('ib_long_call_leg')
                    row['ib_long_put_leg'] = ib_data.get('ib_long_put_leg')
                    row['ib_short_call_bid'] = ib_data.get('ib_short_call_bid')
                    row['ib_short_put_bid'] = ib_data.get('ib_short_put_bid')
                    row['ib_long_call_ask'] = ib_data.get('ib_long_call_ask')
                    row['ib_long_put_ask'] = ib_data.get('ib_long_put_ask')
                else:
                    row['ib_atm_strike'] = None
                    row['ib_wing_width'] = None
                    row['ib_long_call_strike'] = None
                    row['ib_long_put_strike'] = None
                    row['ib_net_premium'] = None
                    row['ib_max_loss'] = None
                    row['ib_win_loss_ratio'] = None
                    row['ib_trade_size'] = None
                    row['ib_unit_pnl'] = None
                    row['ib_unit_pnl_without_commission'] = None
                    row['ib_total_pnl'] = None
                    row['ib_total_pnl_without_commission'] = None
                    row['ib_result'] = None
                    # Add in the "else" block (around line 251-263), add None values for these columns:
                    row['ib_contract_representation'] = None
                    row['ib_short_call_leg'] = None
                    row['ib_short_put_leg'] = None
                    row['ib_long_call_leg'] = None
                    row['ib_long_put_leg'] = None
                    row['ib_short_call_bid'] = None
                    row['ib_short_put_bid'] = None
                    row['ib_long_call_ask'] = None
                    row['ib_long_put_ask'] = None
                
                results.append(row)
            
            self.analysis_results = pd.DataFrame(results)
            logger.info(f"Completed {len(results)} calculations with IB data merged")
        else:
            logger.warning("No valid data to process after filtering")
            self.analysis_results = pd.DataFrame()
        
        return self.analysis_results
    
    async def _execute_in_batches(self, tasks: List, batch_size: int) -> List:
        """Execute tasks in batches to prevent overwhelming the system"""
        results = []
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            batch_results = await asyncio.gather(*batch, return_exceptions=True)
            results.extend(batch_results)
            logger.debug(f"Completed batch {i//batch_size + 1}/{(len(tasks)-1)//batch_size + 1}")
        return results
    
    def _filter_to_intervals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter DataFrame to only include rows at specified minute intervals"""
        df = df.copy()
        df['minute_of_day'] = (df['timestamp'].dt.hour - 9) * 60 + (df['timestamp'].dt.minute - 30)
        interval_mask = df['minute_of_day'] % self.config.bar_minutes == 0
    
        filtered_df = df[interval_mask].copy()
    
        # Apply time segment exclusions
        if self.config.exclude_first_interval:
           filtered_df = filtered_df[filtered_df['minute_of_day'] > 0]
    
        if self.config.exclude_last_interval:
           filtered_df = filtered_df[filtered_df['minute_of_day'] < 390]
    
        return filtered_df
    
    def reset_analysis(self):
        """Reset analysis state for a fresh run"""
        self.analysis_results = None
        self.implied_moves = []
        self.realized_moves = []
    
    def _calculate_time_remaining(self, timestamp: pd.Timestamp) -> int:
        """Calculate minutes remaining until market close (4:00 PM)"""
        close_time = timestamp.replace(hour=16, minute=0, second=0, microsecond=0)
        remaining = (close_time - timestamp).total_seconds() / 60
        return max(0, int(remaining))
    
    async def _get_closing_price(self, date: datetime) -> Optional[float]:
          """Get closing price for a given date, considering DTE"""
          async with self._semaphore:
                target_date = date
        
                # Adjust for DTE (Days to Expiration)
                if self.config.dte > 0:
                   # Find the next trading day(s) based on DTE
                   for _ in range(self.config.dte):
                            target_date = self._get_next_trading_day(target_date)
        
                # Always fetch official daily close from Polygon (not last intraday bar)
                return await self.provider.get_sp_closing_price(target_date, self.config.underlying)
    
    def _get_next_trading_day(self, date: datetime) -> datetime:
        """Get next trading day (skip weekends)"""
        next_day = date + timedelta(days=1)
        while next_day.weekday() >= 5:  # Saturday = 5, Sunday = 6
            next_day += timedelta(days=1)
        return next_day
    
    async def _calculate_single_implied_move(self, date: datetime, timestamp: pd.Timestamp, 
                                            spx_price: float) -> float:
        """
        Calculate implied move for a single timestamp using option prices.
        """
        async with self._semaphore:
            try:
                # Determine relevant strikes
                atm_strike = self._get_atm_strike(spx_price)
                
                # Check if we're within 1 point of a strike
                if abs(spx_price - atm_strike) <= 1.0:
                    # Use simple ATM straddle calculation
                    straddle_value = await self._calculate_atm_straddle(date, timestamp, atm_strike, spx_price)
                    intrinsic = abs(spx_price - atm_strike)
                    return straddle_value - intrinsic
                else:
                    # Use linear interpolation between strikes
                    return await self._calculate_interpolated_straddle(date, timestamp, spx_price)
                    
            except Exception as e:
                logger.error(f"Error calculating implied move: {e}")
                return np.nan
    
    def _get_atm_strike(self, spx_price: float) -> int:
        """Get the nearest at-the-money strike price"""
        return int(round(spx_price / self.config.strike_interval) * self.config.strike_interval)
    
    async def _calculate_atm_straddle(self, date: datetime, timestamp: pd.Timestamp,
                                     strike: int, spx_price: float) -> float:
        """
        Calculate ATM straddle value when SPX is within 1 point of strike.
        Returns the implied move value.
        """
        exp_date = self._get_expiration_date(date)
        call_contract = self._generate_option_symbol(strike, exp_date, 'C')
        put_contract = self._generate_option_symbol(strike, exp_date, 'P')
        
        # Fetch quotes for both options
        contracts = [call_contract, put_contract]
        quotes = await self.provider.get_option_quotes(contracts, timestamp)
        
        if call_contract in quotes and put_contract in quotes:
            call_quote = quotes[call_contract]
            put_quote = quotes[put_contract]
            
            # Calculate midpoints
            call_mid = (call_quote['bid'] + call_quote['ask']) / 2
            put_mid = (put_quote['bid'] + put_quote['ask']) / 2
            
            # Calculate intrinsic value
            intrinsic = max(0, spx_price - strike)  # For the call if ITM
            
            # Implied move = (Call Mid + Put Mid)
            implied_move = (call_mid + put_mid)
            
            return implied_move
        else:
            logger.warning(f"Missing quotes for strike {strike} at {timestamp}")
            return 0.0
    
    async def _calculate_interpolated_straddle(self, date: datetime, timestamp: pd.Timestamp,
                                              spx_price: float) -> float:
        """
        Calculate implied move using linear interpolation between two strikes.
        Fetches both strikes in parallel for better performance.
        """
        # Find the two surrounding strikes
        lower_strike = int(spx_price / self.config.strike_interval) * self.config.strike_interval
        upper_strike = lower_strike + self.config.strike_interval
        
        # Calculate implied moves for both strikes IN PARALLEL
        lower_task = self._calculate_atm_straddle(date, timestamp, lower_strike, spx_price)
        upper_task = self._calculate_atm_straddle(date, timestamp, upper_strike, spx_price)
        
        lower_implied, upper_implied = await asyncio.gather(lower_task, upper_task)
        
        # Linear interpolation
        weight = (spx_price - lower_strike) / self.config.strike_interval
        implied_move = lower_implied * (1 - weight) + upper_implied * weight
        
        return implied_move
    
    async def _calculate_iron_butterfly_trade(self, date: datetime, timestamp: pd.Timestamp,
                                               spx_price: float, closing_price: float) -> Optional[Dict]:
        """
        Calculate Iron Butterfly trade details at a specific timestamp.
        Uses the Trade class for P&L calculation to match other strategies.
        Returns trade details including entry, max win, max loss, and final P&L.
        """
        if not self.config.ib_enabled:
            return None
            
        try:
            atm_strike = self._get_atm_strike(spx_price)
            min_wing = self.config.ib_min_wing_width
            max_wing = self.config.ib_max_wing_width
            target_ratio = self.config.ib_target_win_loss_ratio
            step = self.config.strike_interval
            tolerance = 0.03
            
            exp_date = self._get_expiration_date(date)
            quote_cache = {}
            
            async def get_quotes_for_distance(d: int) -> Tuple[Optional[float], Optional[float], Optional[Dict]]:
                """Get ratio and net premium for a specific wing distance"""
                # Iron Butterfly: short call and put at ATM, long call and put at wings
                short_call_contract = self._generate_option_symbol(atm_strike, exp_date, 'C')
                short_put_contract = self._generate_option_symbol(atm_strike, exp_date, 'P')
                long_call_contract = self._generate_option_symbol(atm_strike + d, exp_date, 'C')
                long_put_contract = self._generate_option_symbol(atm_strike - d, exp_date, 'P')
                
                symbols = [short_call_contract, short_put_contract, long_call_contract, long_put_contract]
                
                # Fetch uncached quotes
                to_fetch = [(s, s) for s in symbols if s not in quote_cache]
                if to_fetch:
                    tasks = [self.provider._get_option_tick_quote(s, timestamp) for _, s in to_fetch]
                    fetched = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for (_, symbol), quote in zip(to_fetch, fetched):
                        if not isinstance(quote, Exception) and quote:
                            quote_cache[symbol] = quote
                        else:
                            quote_cache[symbol] = None
                
                quotes = {s: quote_cache.get(s) for s in symbols}
                
                if None in quotes.values():
                    return None, None, None
                
                sc_bid = quotes[short_call_contract].get('bid')
                sp_bid = quotes[short_put_contract].get('bid')
                lc_ask = quotes[long_call_contract].get('ask')
                lp_ask = quotes[long_put_contract].get('ask')
                
                if None in [sc_bid, sp_bid, lc_ask, lp_ask]:
                    return None, None, None
                
                net_premium = sc_bid + sp_bid - lc_ask - lp_ask
                max_loss = d - net_premium
                
                if net_premium <= 0 or max_loss <= 0:
                    return None, None, None
                
                ratio = net_premium / max_loss
                return ratio, net_premium, {
                    'short_call': {'contract': short_call_contract, 'bid': sc_bid, 'strike': atm_strike},
                    'short_put': {'contract': short_put_contract, 'bid': sp_bid, 'strike': atm_strike},
                    'long_call': {'contract': long_call_contract, 'ask': lc_ask, 'strike': atm_strike + d},
                    'long_put': {'contract': long_put_contract, 'ask': lp_ask, 'strike': atm_strike - d}
                }
            
            # Three-point search for optimal wing width
            distances = [min_wing, (min_wing + max_wing) // 2, max_wing]
            distances = [d for d in distances if d % step == 0]  # Align to strike intervals
            
            best_d = None
            best_ratio = None
            best_diff = float('inf')
            best_premium = None
            best_quotes = None
            
            for d in distances:
                ratio, net_premium, quotes = await get_quotes_for_distance(d)
                if ratio is not None:
                    diff = abs(ratio - target_ratio)
                    if diff < best_diff:
                        best_diff = diff
                        best_d = d
                        best_ratio = ratio
                        best_premium = net_premium
                        best_quotes = quotes
            
            if best_d is None:
                return None
            
            # Binary search refinement
            if best_ratio < target_ratio:
                left, right = min_wing, best_d
            else:
                left, right = best_d, max_wing
            
            while right - left > step:
                mid = ((left + right) // 2 // step) * step
                ratio, net_premium, quotes = await get_quotes_for_distance(mid)
                
                if ratio is None:
                    break
                
                diff = abs(ratio - target_ratio)
                if diff < best_diff:
                    best_diff = diff
                    best_d = mid
                    best_ratio = ratio
                    best_premium = net_premium
                    best_quotes = quotes
                
                if diff <= tolerance:
                    break
                
                if ratio < target_ratio:
                    right = mid
                else:
                    left = mid
            
            if best_d is None or best_premium is None:
                return None
            
            # Use Trade class for P&L calculation to match other strategies
            size = self.config.ib_trade_size
            commission = self.config.ib_commission_per_contract
            
            # Build contracts dict matching Trade class structure
            contracts = {
                best_quotes['short_call']['contract']: {
                    'position': -size,
                    'entry_price': best_quotes['short_call']['bid'],
                    'leg_type': 'short_call',
                    'strike': atm_strike,
                    'used_capital': commission
                },
                best_quotes['short_put']['contract']: {
                    'position': -size,
                    'entry_price': best_quotes['short_put']['bid'],
                    'leg_type': 'short_put',
                    'strike': atm_strike,
                    'used_capital': commission
                },
                best_quotes['long_call']['contract']: {
                    'position': size,
                    'entry_price': best_quotes['long_call']['ask'],
                    'leg_type': 'long_call',
                    'strike': atm_strike + best_d,
                    'used_capital': best_quotes['long_call']['ask'] * 100 + commission
                },
                best_quotes['long_put']['contract']: {
                    'position': size,
                    'entry_price': best_quotes['long_put']['ask'],
                    'leg_type': 'long_put',
                    'strike': atm_strike - best_d,
                    'used_capital': best_quotes['long_put']['ask'] * 100 + commission
                },
            }
            
            # Calculate payoffs at expiration
            payoffs = {}
            for contract, details in contracts.items():
                strike = details['strike']
                if 'call' in details['leg_type']:
                    payoffs[contract] = max(0, closing_price - strike)
                else:
                    payoffs[contract] = max(0, strike - closing_price)
            
            # Create temporary Trade object to use its P&L calculation
            trade = Trade(
                entry_time=timestamp,
                exit_time=None,
                trade_type="Iron Butterfly Analysis",
                contracts=contracts,
                size=size,
                metadata={'net_premium': best_premium}
            )
            
            # Use Trade class methods for P&L calculation
            trade.calculate_unit_pnl(payoffs, commission)
            trade.calculate_pnl(size)
            trade.calculate_unit_pnl_without_commission(payoffs)
            trade.calculate_pnl_without_commission(size)
            
            return {
                'ib_atm_strike': atm_strike,
                'ib_wing_width': best_d,
                'ib_long_call_strike': atm_strike + best_d,
                'ib_long_put_strike': atm_strike - best_d,
                'ib_net_premium': best_premium,
                'ib_max_loss': best_d - best_premium,
                'ib_win_loss_ratio': best_ratio,
                'ib_trade_size': size,
                'ib_unit_pnl': trade.unit_pnl,
                'ib_unit_pnl_without_commission': trade.unit_pnl_without_commission,
                'ib_total_pnl': trade.pnl,
                'ib_total_pnl_without_commission': trade.pnl_without_commission,
                'ib_result': 'WIN' if trade.pnl > 0 else 'LOSS',
                # Add after line 609 (before the closing brace)
                'ib_contract_representation': f"{atm_strike - best_d}/{atm_strike}  {atm_strike}/{atm_strike + best_d} ({best_d})",
                'ib_short_call_leg': f"Short Call - {atm_strike}",
                'ib_short_put_leg': f"Short Put - {atm_strike}",
                'ib_long_call_leg': f"Long Call - {atm_strike + best_d}",
                'ib_long_put_leg': f"Long Put - {atm_strike - best_d}",
                'ib_short_call_bid': best_quotes['short_call']['bid'],
                'ib_short_put_bid': best_quotes['short_put']['bid'],
                'ib_long_call_ask': best_quotes['long_call']['ask'],
                'ib_long_put_ask': best_quotes['long_put']['ask'],
            }
            
        except Exception as e:
            logger.error(f"Error calculating Iron Butterfly: {e}")
            return None
    
    def _get_expiration_date(self, trade_date: datetime) -> datetime:
        """Get option expiration date based on DTE configuration"""
        exp_date = trade_date
        for _ in range(self.config.dte):
            exp_date = self._get_next_trading_day(exp_date)
        return exp_date
    
    def _generate_option_symbol(self, strike: int, expiration: datetime, 
                               option_type: str) -> str:
        """
        Generate option contract symbol.
        Format: O:SPX[YYMMDD][C/P][STRIKE*1000]
        Example: O:SPX240115C5900000 for Jan 15, 2024, 5900 Call
        """
        exp_str = expiration.strftime('%y%m%d')
        return f"O:SPXW{exp_str}{option_type}{int(strike*1000):08d}"
    
    def generate_chart_data(self) -> Dict:
        """
        Generate data for all 5 chart types in parallel using threading.
        Returns dictionary with data for each chart.
        """
        if self.analysis_results is None or self.analysis_results.empty:
            raise ValueError("No analysis results available. Run calculate_implied_moves first.")
        
        df = self.analysis_results.copy()
        
        logger.info("Generating chart data in parallel")
        
        # Use ThreadPoolExecutor to generate all charts in parallel
        # These are CPU-bound operations on pandas DataFrames
        with ThreadPoolExecutor(max_workers=5) as executor:
            chart1_future = executor.submit(self._generate_chart1_data, df)
            chart2_future = executor.submit(self._generate_chart2_data, df)
            chart3_future = executor.submit(self._generate_chart3_data, df)
            chart4_future = executor.submit(self._generate_chart4_data, df)
            chart5_future = executor.submit(self._generate_chart5_data, df)
            
            chart_data = {
                'chart1': chart1_future.result(),
                'chart2': chart2_future.result(),
                'chart3': chart3_future.result(),
                'chart4': chart4_future.result(),
                'chart5': chart5_future.result(),
                'raw_data': df  # Include raw data for CSV export
            }
        
        logger.info("Chart data generation complete")
        return chart_data
    
    def _generate_chart1_data(self, df: pd.DataFrame) -> Dict:
        """
        Chart 1: Individual decay curves for each trading day.
        Returns dict with date -> {time_remaining, implied, realized} arrays
        """
        chart1_data = {}
        
        for date in df['date'].unique():
            day_data = df[df['date'] == date].sort_values('timestamp')
            
            chart1_data[date.strftime('%Y-%m-%d')] = {
                'time_remaining': day_data['time_remaining_minutes'].tolist(),
                'implied': day_data['implied_move'].tolist(),
                'realized': day_data['realized_move'].tolist(),
                'timestamps': day_data['time_of_day'].tolist()
            }
        
        return chart1_data
    
    def _generate_chart2_data(self, df: pd.DataFrame) -> Dict:
        """
        Chart 2: Average decay curve across all trading days.
        Returns dict with time_of_day -> average implied/realized and IB metrics
        """
        agg_dict = {
            'time_remaining_minutes': 'mean',
            'implied_move': 'mean',
            'realized_move': 'mean'
        }
        
        # Add IB aggregations if columns exist
        if 'ib_net_premium' in df.columns:
            agg_dict['ib_net_premium'] = 'mean'
            agg_dict['ib_max_loss'] = 'mean'
            agg_dict['ib_wing_width'] = 'mean'
            agg_dict['ib_total_pnl'] = ['mean', 'sum', 'count']
            agg_dict['ib_win_loss_ratio'] = 'mean'
        
        avg_by_time = df.groupby('time_of_day').agg(agg_dict)
        
        # Flatten column names if multi-level
        if isinstance(avg_by_time.columns, pd.MultiIndex):
            avg_by_time.columns = ['_'.join(col).strip('_') for col in avg_by_time.columns]
        
        avg_by_time = avg_by_time.reset_index()
        
        result = {
            'time_of_day': avg_by_time['time_of_day'].tolist(),
            'time_remaining': avg_by_time['time_remaining_minutes'].tolist() if 'time_remaining_minutes' in avg_by_time.columns else avg_by_time['time_remaining_minutes_mean'].tolist(),
            'avg_implied': avg_by_time['implied_move'].tolist() if 'implied_move' in avg_by_time.columns else avg_by_time['implied_move_mean'].tolist(),
            'avg_realized': avg_by_time['realized_move'].tolist() if 'realized_move' in avg_by_time.columns else avg_by_time['realized_move_mean'].tolist(),
        }
        
        # Add IB data if available
        if 'ib_net_premium' in df.columns:
            result['ib_avg_premium'] = avg_by_time['ib_net_premium'].tolist() if 'ib_net_premium' in avg_by_time.columns else avg_by_time.get('ib_net_premium_mean', [None]*len(avg_by_time)).tolist()
            result['ib_avg_max_loss'] = avg_by_time['ib_max_loss'].tolist() if 'ib_max_loss' in avg_by_time.columns else avg_by_time.get('ib_max_loss_mean', [None]*len(avg_by_time)).tolist()
            result['ib_avg_wing_width'] = avg_by_time['ib_wing_width'].tolist() if 'ib_wing_width' in avg_by_time.columns else avg_by_time.get('ib_wing_width_mean', [None]*len(avg_by_time)).tolist()
            result['ib_avg_pnl'] = avg_by_time.get('ib_total_pnl_mean', [None]*len(avg_by_time)).tolist()
            result['ib_total_pnl'] = avg_by_time.get('ib_total_pnl_sum', [None]*len(avg_by_time)).tolist()
            result['ib_trade_count'] = avg_by_time.get('ib_total_pnl_count', [None]*len(avg_by_time)).tolist()
            result['ib_avg_ratio'] = avg_by_time['ib_win_loss_ratio'].tolist() if 'ib_win_loss_ratio' in avg_by_time.columns else avg_by_time.get('ib_win_loss_ratio_mean', [None]*len(avg_by_time)).tolist()
            
            # Calculate win rate per time interval
            win_rates = []
            for tod in result['time_of_day']:
                tod_data = df[df['time_of_day'] == tod]
                valid_ib = tod_data[tod_data['ib_total_pnl'].notna()]
                if len(valid_ib) > 0:
                    win_rate = (valid_ib['ib_total_pnl'] > 0).sum() / len(valid_ib) * 100
                    win_rates.append(round(win_rate, 2))
                else:
                    win_rates.append(None)
            result['ib_win_rate'] = win_rates
        
        return result
    
    def _generate_chart3_data(self, df: pd.DataFrame) -> Dict:
        """
        Chart 3: Scatter plot of average implied vs realized for each time interval.
        Returns dict with time_of_day -> (realized, implied) pairs
        """
        # Group by time of day
        avg_by_time = df.groupby('time_of_day').agg({
            'implied_move': 'mean',
            'realized_move': 'mean'
        }).reset_index()
        
        # Calculate distance from equilibrium line (implied = realized)
        avg_by_time['distance_from_equilibrium'] = (
            avg_by_time['implied_move'] - avg_by_time['realized_move']
        )
        
        return {
            'time_of_day': avg_by_time['time_of_day'].tolist(),
            'realized': avg_by_time['realized_move'].tolist(),
            'implied': avg_by_time['implied_move'].tolist(),
            'distance_from_equilibrium': avg_by_time['distance_from_equilibrium'].tolist(),
            'sorted_by_distance': avg_by_time.sort_values('distance_from_equilibrium')[
                ['time_of_day', 'realized_move', 'implied_move', 'distance_from_equilibrium']
            ].to_dict('records')
        }
    
    def _generate_chart4_data(self, df: pd.DataFrame) -> Dict:
        """
        Chart 4: Average implied and realized moves for each trading day.
        Returns dict with date -> average implied/realized and IB metrics
        """
        agg_dict = {
            'implied_move': 'mean',
            'realized_move': 'mean'
        }
        
        # Add IB aggregations if columns exist
        if 'ib_net_premium' in df.columns:
            agg_dict['ib_net_premium'] = 'mean'
            agg_dict['ib_max_loss'] = 'mean'
            agg_dict['ib_total_pnl'] = ['mean', 'sum', 'count']
            agg_dict['ib_wing_width'] = 'mean'
        
        daily_avg = df.groupby('date').agg(agg_dict)
        
        # Flatten column names if multi-level
        if isinstance(daily_avg.columns, pd.MultiIndex):
            daily_avg.columns = ['_'.join(col).strip('_') for col in daily_avg.columns]
        
        daily_avg = daily_avg.reset_index()
        daily_avg = daily_avg.sort_values('date')
        
        result = {
            'dates': [d.strftime('%Y-%m-%d') for d in daily_avg['date']],
            'avg_implied': daily_avg['implied_move'].tolist() if 'implied_move' in daily_avg.columns else daily_avg['implied_move_mean'].tolist(),
            'avg_realized': daily_avg['realized_move'].tolist() if 'realized_move' in daily_avg.columns else daily_avg['realized_move_mean'].tolist(),
            'trend_implied': self._calculate_trend_line(daily_avg['implied_move'] if 'implied_move' in daily_avg.columns else daily_avg['implied_move_mean']),
            'trend_realized': self._calculate_trend_line(daily_avg['realized_move'] if 'realized_move' in daily_avg.columns else daily_avg['realized_move_mean'])
        }
        
        # Add IB data if available
        if 'ib_net_premium' in df.columns:
            result['ib_avg_premium'] = daily_avg['ib_net_premium'].tolist() if 'ib_net_premium' in daily_avg.columns else daily_avg.get('ib_net_premium_mean', [None]*len(daily_avg)).tolist()
            result['ib_avg_max_loss'] = daily_avg['ib_max_loss'].tolist() if 'ib_max_loss' in daily_avg.columns else daily_avg.get('ib_max_loss_mean', [None]*len(daily_avg)).tolist()
            result['ib_avg_pnl'] = daily_avg.get('ib_total_pnl_mean', [None]*len(daily_avg)).tolist()
            result['ib_total_pnl'] = daily_avg.get('ib_total_pnl_sum', [None]*len(daily_avg)).tolist()
            result['ib_trade_count'] = daily_avg.get('ib_total_pnl_count', [None]*len(daily_avg)).tolist()
            result['ib_avg_wing'] = daily_avg['ib_wing_width'].tolist() if 'ib_wing_width' in daily_avg.columns else daily_avg.get('ib_wing_width_mean', [None]*len(daily_avg)).tolist()
            
            # Calculate win rate per day
            win_rates = []
            for d in daily_avg['date']:
                day_data = df[df['date'] == d]
                valid_ib = day_data[day_data['ib_total_pnl'].notna()]
                if len(valid_ib) > 0:
                    win_rate = (valid_ib['ib_total_pnl'] > 0).sum() / len(valid_ib) * 100
                    win_rates.append(round(win_rate, 2))
                else:
                    win_rates.append(None)
            result['ib_win_rate'] = win_rates
            
            # Add IB P&L trend line
            ib_pnl_series = pd.Series(result['ib_avg_pnl']).dropna()
            if len(ib_pnl_series) >= 2:
                result['trend_ib_pnl'] = self._calculate_trend_line(ib_pnl_series)
            else:
                result['trend_ib_pnl'] = {'slope': 0, 'intercept': 0, 'r_squared': 0}
        
        return result
    
    def _generate_chart5_data(self, df: pd.DataFrame) -> Dict:
        """
        Chart 5: Separate chart for each time interval showing implied/realized across all days.
        Returns dict with time_of_day -> {dates, implied, realized} arrays
        """
        chart5_data = {}
        
        # Get unique time intervals
        time_intervals = sorted(df['time_of_day'].unique())
        
        for time_interval in time_intervals:
            interval_data = df[df['time_of_day'] == time_interval].sort_values('date')
            
            chart5_data[time_interval] = {
                'dates': [d.strftime('%Y-%m-%d') for d in interval_data['date']],
                'implied': interval_data['implied_move'].tolist(),
                'realized': interval_data['realized_move'].tolist(),
                'trend_implied': self._calculate_trend_line(interval_data['implied_move']),
                'trend_realized': self._calculate_trend_line(interval_data['realized_move'])
            }
        
        return chart5_data
    
    def _calculate_trend_line(self, values: pd.Series) -> Dict:
        """
        Calculate linear trend line for a series of values.
        Returns dict with slope and intercept for y = mx + b
        """
        if len(values) < 2:
            return {'slope': 0, 'intercept': values.iloc[0] if len(values) > 0 else 0, 'r_squared': 0}
        
        x = np.arange(len(values))
        y = values.values
        
        # Calculate linear regression
        coefficients = np.polyfit(x, y, 1)
        
        return {
            'slope': float(coefficients[0]),
            'intercept': float(coefficients[1]),
            'r_squared': float(np.corrcoef(x, y)[0, 1] ** 2)
        }
    
    def export_to_csv(self, output_dir: str = './output'):
        """
        Export all chart data to CSV files in parallel.
        Creates separate CSV files for each chart type.
        """
        os.makedirs(output_dir, exist_ok=True)
        
        if self.analysis_results is None:
            raise ValueError("No analysis results to export")
        
        logger.info("Starting parallel CSV export")
        
        # Generate chart data
        chart_data = self.generate_chart_data()
        
        # Use ThreadPoolExecutor to export all CSVs in parallel
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = []
            
            # Export raw data
            futures.append(executor.submit(
                self._export_raw_data,
                output_dir,
                self.analysis_results
            ))
            
            # Export chart 1
            futures.append(executor.submit(
                self._export_chart1,
                output_dir,
                chart_data['chart1']
            ))
            
            # Export chart 2
            futures.append(executor.submit(
                self._export_chart2,
                output_dir,
                chart_data['chart2']
            ))
            
            # Export chart 3
            futures.append(executor.submit(
                self._export_chart3,
                output_dir,
                chart_data['chart3']
            ))
            
            # Export chart 4
            futures.append(executor.submit(
                self._export_chart4,
                output_dir,
                chart_data['chart4']
            ))
            
            # Export chart 5
            futures.append(executor.submit(
                self._export_chart5,
                output_dir,
                chart_data['chart5']
            ))
            
            # Wait for all exports to complete
            for future in futures:
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Error during CSV export: {e}")
        
        logger.info(f"All CSV files exported to {output_dir}")
    
    def _export_raw_data(self, output_dir: str, df: pd.DataFrame):
        """Export raw analysis data (includes Iron Butterfly data in same file)"""
        raw_file = os.path.join(output_dir, 'raw_analysis_data.csv')
        df.to_csv(raw_file, index=False)
        logger.info(f"Exported raw data to {raw_file}")
    
    def _export_chart1(self, output_dir: str, chart1_data: Dict):
        """Export chart 1 data"""
        chart1_df = []
        for date, data in chart1_data.items():
            for i in range(len(data['time_remaining'])):
                chart1_df.append({
                    'date': date,
                    'time_of_day': data['timestamps'][i],
                    'time_remaining_minutes': data['time_remaining'][i],
                    'implied_move': data['implied'][i],
                    'realized_move': data['realized'][i]
                })
        pd.DataFrame(chart1_df).to_csv(
            os.path.join(output_dir, 'chart1_daily_decay_curves.csv'), 
            index=False
        )
        logger.info("Exported chart 1 data")
    
    def _export_chart2(self, output_dir: str, chart2_data: Dict):
        """Export chart 2 data (average decay curve with IB averages)"""
        export_dict = {
            'time_of_day': chart2_data['time_of_day'],
            'time_remaining': chart2_data['time_remaining'],
            'avg_implied': chart2_data['avg_implied'],
            'avg_realized': chart2_data['avg_realized']
        }
        
        # Add IB columns if present
        for key in ['ib_avg_premium', 'ib_avg_max_loss', 'ib_avg_wing_width', 
                    'ib_avg_pnl', 'ib_total_pnl', 'ib_trade_count', 'ib_avg_ratio', 'ib_win_rate']:
            if key in chart2_data:
                export_dict[key] = chart2_data[key]
        
        pd.DataFrame(export_dict).to_csv(
            os.path.join(output_dir, 'chart2_average_decay_curve.csv'),
            index=False
        )
        logger.info("Exported chart 2 data")
    
    def _export_chart3(self, output_dir: str, chart3_data: Dict):
        """Export chart 3 data"""
        scatter_df = pd.DataFrame({
            'time_of_day': chart3_data['time_of_day'],
            'realized': chart3_data['realized'],
            'implied': chart3_data['implied'],
            'distance_from_equilibrium': chart3_data['distance_from_equilibrium']
        })
        scatter_df.to_csv(
            os.path.join(output_dir, 'chart3_scatter_plot.csv'),
            index=False
        )
        logger.info("Exported chart 3 data")
    
    def _export_chart4(self, output_dir: str, chart4_data: Dict):
        """Export chart 4 data with proper flattening (includes IB daily averages)"""
        export_dict = {
            'date': chart4_data['dates'],
            'avg_implied': chart4_data['avg_implied'],
            'avg_realized': chart4_data['avg_realized'],
            'trend_implied_slope': chart4_data['trend_implied']['slope'],
            'trend_implied_intercept': chart4_data['trend_implied']['intercept'],
            'trend_implied_r_squared': chart4_data['trend_implied']['r_squared'],
            'trend_realized_slope': chart4_data['trend_realized']['slope'],
            'trend_realized_intercept': chart4_data['trend_realized']['intercept'],
            'trend_realized_r_squared': chart4_data['trend_realized']['r_squared']
        }
        
        # Add IB columns if present
        for key in ['ib_avg_premium', 'ib_avg_max_loss', 'ib_avg_pnl', 'ib_total_pnl', 
                    'ib_trade_count', 'ib_avg_wing', 'ib_win_rate']:
            if key in chart4_data:
                export_dict[key] = chart4_data[key]
        
        # Add IB trend if available
        if 'trend_ib_pnl' in chart4_data:
            export_dict['trend_ib_pnl_slope'] = chart4_data['trend_ib_pnl']['slope']
            export_dict['trend_ib_pnl_intercept'] = chart4_data['trend_ib_pnl']['intercept']
            export_dict['trend_ib_pnl_r_squared'] = chart4_data['trend_ib_pnl']['r_squared']
        
        pd.DataFrame(export_dict).to_csv(
            os.path.join(output_dir, 'chart4_daily_averages.csv'),
            index=False
        )
        logger.info("Exported chart 4 data")
    
    def _export_chart5(self, output_dir: str, chart5_data: Dict):
        """Export chart 5 data"""
        chart5_df = []
        for time_interval, data in chart5_data.items():
            for i in range(len(data['dates'])):
                chart5_df.append({
                    'time_interval': time_interval,
                    'date': data['dates'][i],
                    'implied_move': data['implied'][i],
                    'realized_move': data['realized'][i]
                })
        pd.DataFrame(chart5_df).to_csv(
            os.path.join(output_dir, 'chart5_time_intervals.csv'),
            index=False
        )
        logger.info("Exported chart 5 data")
    
    def get_summary_statistics(self) -> Dict:
        """
        Calculate summary statistics for the analysis.
        """
        if self.analysis_results is None:
            raise ValueError("No analysis results available")
        
        df = self.analysis_results
        
        stats = {
            'total_data_points': len(df),
            'trading_days_analyzed': df['date'].nunique(),
            'intervals_per_day': self._get_intervals_per_day(),
            'average_implied_move': float(df['implied_move'].mean()),
            'average_realized_move': float(df['realized_move'].mean()),
            'implied_std': float(df['implied_move'].std()),
            'realized_std': float(df['realized_move'].std()),
            'implied_over_realized_ratio': float(df['implied_move'].mean() / df['realized_move'].mean()) if df['realized_move'].mean() != 0 else 0,
            'correlation': float(df['implied_move'].corr(df['realized_move'])),
            'config': {
                'start_date': self.config.start_date.strftime('%Y-%m-%d'),
                'end_date': self.config.end_date.strftime('%Y-%m-%d'),
                'bar_minutes': self.config.bar_minutes,
                'dte': self.config.dte,
                'max_concurrent_requests': self.config.max_concurrent_requests,
                'batch_size': self.config.batch_size
            }
        }

        # Add Iron Butterfly statistics from main DataFrame
        if 'ib_total_pnl' in df.columns:
            valid_ib = df[df['ib_total_pnl'].notna()]
            if len(valid_ib) > 0:
                stats['iron_butterfly'] = {
                    'total_trades': len(valid_ib),
                    'trade_size': int(valid_ib['ib_trade_size'].iloc[0]),
                    'win_rate': float((valid_ib['ib_total_pnl'] > 0).sum() / len(valid_ib) * 100),
                    'avg_unit_pnl': float(valid_ib['ib_unit_pnl'].mean()),
                    'avg_total_pnl': float(valid_ib['ib_total_pnl'].mean()),
                    'sum_total_pnl': float(valid_ib['ib_total_pnl'].sum()),
                    'avg_premium': float(valid_ib['ib_net_premium'].mean()),
                    'avg_max_loss': float(valid_ib['ib_max_loss'].mean()),
                    'avg_wing_width': float(valid_ib['ib_wing_width'].mean()),
                }
        
        return stats