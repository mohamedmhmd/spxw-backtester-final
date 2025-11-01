import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import asyncio
import logging
from dataclasses import dataclass
import json
from data.polygon_data_provider import PolygonDataProvider

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

class OptionsAnalyzer:
    """
    Analyzes SPX options data to compute implied vs realized movements
    and generates data for 5 different chart types.
    """
    
    def __init__(self, polygon_provider: PolygonDataProvider, config: AnalysisConfig):
        self.provider = polygon_provider
        self.config = config
        self.spx_data = {}  # Date -> DataFrame of OHLC data
        self.options_data = {}  # Date -> Dict of options data
        self.implied_moves = []  # List of all implied move calculations
        self.realized_moves = []  # List of all realized move calculations
        self.analysis_results = None  # Final DataFrame with all calculations
        
    async def fetch_all_data(self) -> bool:
        """
        Fetch all required SPX and options data for the analysis period.
        Returns True if successful, False otherwise.
        """
        try:
            # Get list of trading days
            trading_days = self._get_trading_days(self.config.start_date, self.config.end_date)
            logger.info(f"Fetching data for {len(trading_days)} trading days")
            
            # Fetch SPX OHLC data for each day
            for date in trading_days:
                logger.info(f"Fetching SPX data for {date.strftime('%Y-%m-%d')}")
                spx_df = await self.provider.get_ohlc_data(date, self.config.underlying, self.config.bar_minutes)
                if not spx_df.empty:
                    self.spx_data[date] = spx_df
                else:
                    logger.warning(f"No SPX data for {date}")
            
            logger.info(f"Successfully fetched SPX data for {len(self.spx_data)} days")
            return len(self.spx_data) > 0
            
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return False
    
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
    Calculate implied moves for all time intervals.
    Returns DataFrame with columns: date, timestamp, spx_price, implied_move
    """
          if not self.spx_data:
             logger.warning("No SPX data available for analysis")
             return pd.DataFrame()
    
          # Pre-calculate constants
          intervals_per_day = self._get_intervals_per_day()
    
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
    
          # Prepare all calculation tasks
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
                  spx_price = row['close']
            
                  task = self._calculate_single_implied_move(date, timestamp, spx_price)
                  calc_tasks.append(task)
            
                  # Store metadata for result construction
                  task_metadata.append({
                'date': date,
                'timestamp': timestamp,
                'time_of_day': timestamp.strftime('%H:%M'),
                'time_remaining_minutes': time_remaining_values.iloc[idx],
                'spx_price': spx_price,
                'realized_move': abs(spx_price - closing_price),
                'closing_price': closing_price
            })
    
          # Execute all implied move calculations in parallel
          if calc_tasks:
             implied_moves = await asyncio.gather(*calc_tasks, return_exceptions=True)
        
             # Combine results
             results = []
             for metadata, implied_move in zip(task_metadata, implied_moves):
                 if isinstance(implied_move, Exception):
                    logger.error(f"Error calculating implied move for {metadata['date']} {metadata['time_of_day']}: {implied_move}")
                    implied_move = 0.0  # Or np.nan if you prefer
            
                 metadata['implied_move'] = implied_move
            
                 # Only log every 10th result to reduce logging overhead
                 if len(results) % 10 == 0:
                    logger.info(f"Date: {metadata['date'].strftime('%Y-%m-%d')}, "
                          f"Time: {metadata['time_of_day']}, "
                          f"SPX: {metadata['spx_price']:.2f}, "
                          f"Implied: {implied_move:.2f}, "
                          f"Realized: {metadata['realized_move']:.2f}")
            
                 results.append(metadata)
        
             self.analysis_results = pd.DataFrame(results)
          else:
              logger.warning("No valid data to process after filtering")
              self.analysis_results = pd.DataFrame()
    
          return self.analysis_results
    
    def _filter_to_intervals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter DataFrame to only include rows at specified minute intervals"""
        # Create a mask for the specified intervals
        df['minute_of_day'] = (df['timestamp'].dt.hour - 9) * 60 + (df['timestamp'].dt.minute - 30)
        interval_mask = df['minute_of_day'] % self.config.bar_minutes == 0
        return df[interval_mask].copy()
    
    def _calculate_time_remaining(self, timestamp: pd.Timestamp) -> int:
        """Calculate minutes remaining until market close (4:00 PM)"""
        close_time = timestamp.replace(hour=16, minute=0, second=0, microsecond=0)
        remaining = (close_time - timestamp).total_seconds() / 60
        return max(0, int(remaining))
    
    async def _get_closing_price(self, date: datetime) -> Optional[float]:
        """Get closing price for a given date, considering DTE"""
        target_date = date
        
        # Adjust for DTE (Days to Expiration)
        if self.config.dte > 0:
            # Find the next trading day(s) based on DTE
            for _ in range(self.config.dte):
                target_date = self._get_next_trading_day(target_date)
        
        # Get closing price from cached data or fetch if needed
        if target_date in self.spx_data:
            df = self.spx_data[target_date]
            if not df.empty:
                return df.iloc[-1]['close']
        
        # If not in cache, fetch from Polygon
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
        This is a simplified calculation - you'll need to implement the actual
        option chain fetching and calculation based on your requirements.
        """
        try:
            # Determine relevant strikes
            atm_strike = self._get_atm_strike(spx_price)
            
            # Check if we're within 1 point of a strike
            if abs(spx_price - atm_strike) <= 1.0:
                # Use simple ATM straddle calculation
                return await self._calculate_atm_straddle(date, timestamp, atm_strike, spx_price)
            else:
                # Use linear interpolation between strikes
                return await self._calculate_interpolated_straddle(date, timestamp, spx_price)
                
        except Exception as e:
            logger.error(f"Error calculating implied move: {e}")
            return 0.0
    
    def _get_atm_strike(self, spx_price: float) -> int:
        """Get the nearest at-the-money strike price"""
        return int(round(spx_price / self.config.strike_interval) * self.config.strike_interval)
    
    async def _calculate_atm_straddle(self, date: datetime, timestamp: pd.Timestamp,
                                     strike: int, spx_price: float) -> float:
        """
        Calculate ATM straddle value when SPX is within 1 point of strike.
        Returns the implied move value.
        """
        # Generate option contract symbols for the given strike and expiration
        # This is a placeholder - you'll need to implement actual contract generation
        # based on your DTE configuration
        
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
            
            # Implied move = (Call Mid + Put Mid) - Intrinsic Value
            implied_move = (call_mid + put_mid) - intrinsic
            
            return implied_move
        else:
            logger.warning(f"Missing quotes for strike {strike} at {timestamp}")
            return 0.0
    
    async def _calculate_interpolated_straddle(self, date: datetime, timestamp: pd.Timestamp,
                                              spx_price: float) -> float:
        """
        Calculate implied move using linear interpolation between two strikes.
        """
        # Find the two surrounding strikes
        lower_strike = int(spx_price / self.config.strike_interval) * self.config.strike_interval
        upper_strike = lower_strike + self.config.strike_interval
        
        # Calculate implied moves for both strikes
        lower_implied = await self._calculate_atm_straddle(date, timestamp, lower_strike, spx_price)
        upper_implied = await self._calculate_atm_straddle(date, timestamp, upper_strike, spx_price)
        
        # Linear interpolation
        weight = (spx_price - lower_strike) / self.config.strike_interval
        implied_move = lower_implied * (1 - weight) + upper_implied * weight
        
        return implied_move
    
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
        return f"O:SPXW{exp_str}C{int(strike*1000):08d}"
    
    def generate_chart_data(self) -> Dict:
        """
        Generate data for all 5 chart types.
        Returns dictionary with data for each chart.
        """
        if self.analysis_results is None or self.analysis_results.empty:
            raise ValueError("No analysis results available. Run calculate_implied_moves first.")
        
        df = self.analysis_results.copy()
        
        chart_data = {
            'chart1': self._generate_chart1_data(df),
            'chart2': self._generate_chart2_data(df),
            'chart3': self._generate_chart3_data(df),
            'chart4': self._generate_chart4_data(df),
            'chart5': self._generate_chart5_data(df),
            'raw_data': df  # Include raw data for CSV export
        }
        
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
        Returns dict with time_of_day -> average implied/realized
        """
        # Group by time of day and calculate averages
        avg_by_time = df.groupby('time_of_day').agg({
            'time_remaining_minutes': 'mean',
            'implied_move': 'mean',
            'realized_move': 'mean'
        }).reset_index()
        
        return {
            'time_of_day': avg_by_time['time_of_day'].tolist(),
            'time_remaining': avg_by_time['time_remaining_minutes'].tolist(),
            'avg_implied': avg_by_time['implied_move'].tolist(),
            'avg_realized': avg_by_time['realized_move'].tolist()
        }
    
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
        Returns dict with date -> average implied/realized
        """
        # Calculate daily averages
        daily_avg = df.groupby('date').agg({
            'implied_move': 'mean',
            'realized_move': 'mean'
        }).reset_index()
        
        # Sort by date (most recent on the right)
        daily_avg = daily_avg.sort_values('date')
        
        return {
            'dates': [d.strftime('%Y-%m-%d') for d in daily_avg['date']],
            'avg_implied': daily_avg['implied_move'].tolist(),
            'avg_realized': daily_avg['realized_move'].tolist(),
            'trend_implied': self._calculate_trend_line(daily_avg['implied_move']),
            'trend_realized': self._calculate_trend_line(daily_avg['realized_move'])
        }
    
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
            return {'slope': 0, 'intercept': values.iloc[0] if len(values) > 0 else 0}
        
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
        Export all chart data to CSV files.
        Creates separate CSV files for each chart type.
        """
        os.makedirs(output_dir, exist_ok=True)
        
        if self.analysis_results is None:
            raise ValueError("No analysis results to export")
        
        # Export raw data
        raw_file = os.path.join(output_dir, 'raw_analysis_data.csv')
        self.analysis_results.to_csv(raw_file, index=False)
        logger.info(f"Exported raw data to {raw_file}")
        
        # Generate and export chart-specific data
        chart_data = self.generate_chart_data()
        
        # Chart 1: Individual day decay curves
        chart1_df = []
        for date, data in chart_data['chart1'].items():
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
        
        # Chart 2: Average decay curve
        pd.DataFrame(chart_data['chart2']).to_csv(
            os.path.join(output_dir, 'chart2_average_decay_curve.csv'),
            index=False
        )
        
        # Chart 3: Scatter plot data
        scatter_df = pd.DataFrame({
            'time_of_day': chart_data['chart3']['time_of_day'],
            'realized': chart_data['chart3']['realized'],
            'implied': chart_data['chart3']['implied'],
            'distance_from_equilibrium': chart_data['chart3']['distance_from_equilibrium']
        })
        scatter_df.to_csv(
            os.path.join(output_dir, 'chart3_scatter_plot.csv'),
            index=False
        )
        
        # Chart 4: Daily averages
        pd.DataFrame(chart_data['chart4']).to_csv(
            os.path.join(output_dir, 'chart4_daily_averages.csv'),
            index=False
        )
        
        # Chart 5: Time interval data
        chart5_df = []
        for time_interval, data in chart_data['chart5'].items():
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
        
        logger.info(f"All CSV files exported to {output_dir}")
    
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
            'implied_over_realized_ratio': float(df['implied_move'].mean() / df['realized_move'].mean()),
            'correlation': float(df['implied_move'].corr(df['realized_move'])),
            'config': {
                'start_date': self.config.start_date.strftime('%Y-%m-%d'),
                'end_date': self.config.end_date.strftime('%Y-%m-%d'),
                'bar_minutes': self.config.bar_minutes,
                'dte': self.config.dte
            }
        }
        
        return stats