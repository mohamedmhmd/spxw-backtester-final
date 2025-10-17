from datetime import datetime, timedelta
import logging
from typing import Dict, Optional, Union, List

import numpy as np
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.common import Common
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
from trades.signal_checker import OptimizedSignalChecker
import asyncio

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LongStrangle2:
    """
    Long Strangle 2 implementation:
    - Long Strangle 2(a): Buy call at strike = market + distance
    - Long Strangle 2(b): Buy put at strike = market - distance
    
    Distance = configurable % of largest 5-minute bar range of the day
    
    Entry conditions same as Iron 1:
    1) Three consecutive 5-minute candles at volume below 50% of first candle
    2) Last four 5-minute candles not all in same direction
    3) Average range of last two candles below 80% of day's average
    """
    
    @staticmethod
    def _round_to_nearest_strike(price: float, interval: int = 5) -> int:
        """Round price to nearest strike interval (default 5)"""
        return int(round(price / interval) * interval)
    
    @staticmethod
    def _get_largest_bar_range(spx_ohlc_data, up_to_index: int) -> float:
        """Get the largest 5-minute bar range of the day up to current index"""
        if up_to_index <= 0:
            return 0.0
        
        # Calculate range for each bar up to current index
        high_values = spx_ohlc_data['high'].values[:up_to_index]
        low_values = spx_ohlc_data['low'].values[:up_to_index]
        ranges = high_values - low_values
        
        # Return the maximum range
        return float(np.max(ranges)) if len(ranges) > 0 else 0.0
    
    @staticmethod
    def _get_expiration_date(current_date: datetime, dte: int) -> datetime:
        """
        Get the expiration date based on DTE (Days To Expiration)
        dte: Number of trading days until expiration
        """
        # For simplicity, assuming all weekdays are trading days
        # In production, should check for holidays
        exp_date = current_date
        days_added = 0
        
        while days_added < dte:
            exp_date += timedelta(days=1)
            # Skip weekends
            if exp_date.weekday() < 5:  # Monday = 0, Friday = 4
                days_added += 1
        
        return exp_date
    
    @staticmethod
    def _create_option_contract(
        strike: float,
        option_type: str,
        expiration: datetime
    ) -> str:
        """Create option contract symbol"""
        exp_str = expiration.strftime('%y%m%d')
        type_char = 'C' if option_type == 'call' else 'P'
        return f"O:SPXW{exp_str}{type_char}{int(strike*1000):08d}"
    
    @staticmethod
    async def _get_option_quote(
        contract: str,
        timestamp: datetime,
        data_provider: Union[MockDataProvider, PolygonDataProvider]
    ) -> Optional[Dict]:
        """Get option quote for a contract"""
        try:
            quote = await data_provider._get_option_tick_quote(contract, timestamp)
            return quote
        except Exception as e:
            logger.error(f"Error getting quote for {contract}: {e}")
            return None
    
    @staticmethod
    async def _execute_long_leg(
        contract: str,
        quote: Dict,
        entry_time: datetime,
        size: int,
        leg_type: str,
        strike: float,
        config: BacktestConfig,
        current_price: float,
        distance: float,
        largest_range: float,
        range_multiplier: float,
        variant: str,
        expiration: datetime,
        contract_symbol: str
    ) -> Optional[Trade]:
        """Execute a single long option leg (call or put)"""
        
        # Get ask price for long position
        ask_price = quote.get('ask')
        if ask_price is None or ask_price <= 0:
            logger.warning(f"Invalid ask price for {contract}")
            return None
        
        # Build trade position
        trade_contracts = {
            contract: {
                'position': size,
                'entry_price': ask_price,
                'leg_type': f'long_{leg_type}',
                'strike': strike,
                'expiration': expiration,
                'used_capital': ask_price * 100 + config.commission_per_contract
            }
        }
        
        # Create representation string
        representation = f"Long {leg_type.capitalize()}: {strike}"
        
        # Create trade
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type=f"Long Strangle 2({variant})",
            contracts=trade_contracts,
            size=size,
            used_capital=0.0,
            metadata={
                'net_premium': -ask_price,
                'strategy_name': f"Long Strangle 2({variant})",
                'entry_spx_price': current_price,
                'representation': representation,
                'leg_type': leg_type,
                'variant': variant,
                'strike': strike,
                'distance_from_market': distance,
                'largest_bar_range': largest_range,
                'range_multiplier': range_multiplier,
                'expiration': expiration,
                'contract_symbol': contract_symbol
            }
        )
        
        return trade
    
    @staticmethod
    async def _find_long_strangle_trades(
        i: int,
        strategy: StrategyConfig,
        date: datetime,
        current_price: float,
        current_bar_time: datetime,
        data_provider: Union[MockDataProvider, PolygonDataProvider],
        config: BacktestConfig,
        checker: OptimizedSignalChecker,
        spx_ohlc_data
    ) -> List[Optional[Trade]]:
        """Find and execute Long Strangle 2(a) and 2(b) trades"""
        
        # Check entry signals (same as Iron 1)
        # Using checker method - assuming it exists
        if not checker.long_strangle_2_check_entry_signals(i, strategy):
            return None
        
        # Get largest bar range of the day
        largest_range = LongStrangle2._get_largest_bar_range(spx_ohlc_data, i)
        
        if largest_range <= 0:
            logger.warning("No valid bar ranges found for the day")
            return None
        
        # Get range multiplier (default to 100% if not specified)
        range_multiplier = getattr(strategy, 'ls_2_range_multiplier', 1.0)
        
        # Calculate distance from market
        calculated_distance = largest_range * range_multiplier
        
        # Round distance to nearest 5
        distance = LongStrangle2._round_to_nearest_strike(calculated_distance, 5)
        
        # Round current price to nearest 5
        center_strike = LongStrangle2._round_to_nearest_strike(current_price, 5)
        
        # Calculate strikes
        call_strike = center_strike + distance
        put_strike = center_strike - distance
        
        logger.info(f"Long Strangle 2 conditions met - Market: {current_price:.2f} (rounded to {center_strike}), "
                   f"Largest range: {largest_range:.2f}, Multiplier: {range_multiplier:.1%}, "
                   f"Distance: {distance}, Call: {call_strike}, Put: {put_strike}")
        
        # Get DTE setting (default to 1DTE - next trading day)
        dte = getattr(strategy, 'ls_2_dte', 1)
        
        # Get expiration date
        if isinstance(date, datetime):
            current_date = date
        else:
            current_date = datetime.combine(date, datetime.min.time())
        
        expiration_date = LongStrangle2._get_expiration_date(current_date, dte)
        
        # Create contracts
        call_contract = LongStrangle2._create_option_contract(call_strike, 'call', expiration_date)
        put_contract = LongStrangle2._create_option_contract(put_strike, 'put', expiration_date)
        
        # Get quotes
        call_quote, put_quote = await asyncio.gather(
            LongStrangle2._get_option_quote(call_contract, current_bar_time, data_provider),
            LongStrangle2._get_option_quote(put_contract, current_bar_time, data_provider),
            return_exceptions=True
        )
        
        trades = []
        
        # Execute Long Strangle 2(a) - Call
        if not isinstance(call_quote, Exception) and call_quote:
            # Get trade size for variant (a)
            call_size = getattr(strategy, 'ls_2_trade_a_size', 10)
            
            call_trade = await LongStrangle2._execute_long_leg(
                call_contract,
                call_quote,
                current_bar_time,
                call_size,
                'call',
                call_strike,
                config,
                current_price,
                distance,
                largest_range,
                range_multiplier,
                'a', 
                expiration_date,
                call_contract
            )
            
            if call_trade:
                logger.info(f"Entered Long Strangle 2(a) at {current_bar_time}: "
                           f"Long Call {call_strike} for ${call_quote.get('ask', 0):.2f} "
                           f"(expires {expiration_date.strftime('%Y-%m-%d')})")
                trades.append(call_trade)
            else:
                trades.append(None)
        else:
            logger.warning(f"Could not get quote for call contract {call_contract}")
            trades.append(None)
        
        # Execute Long Strangle 2(b) - Put
        if not isinstance(put_quote, Exception) and put_quote:
            # Get trade size for variant (b)
            put_size = getattr(strategy, 'ls_2_trade_b_size', 10)
            
            put_trade = await LongStrangle2._execute_long_leg(
                put_contract,
                put_quote,
                current_bar_time,
                put_size,
                'put',
                put_strike,
                config,
                current_price,
                distance,
                largest_range,
                range_multiplier,
                'b',
                expiration_date,
                put_contract
            )
            
            if put_trade:
                logger.info(f"Entered Long Strangle 2(b) at {current_bar_time}: "
                           f"Long Put {put_strike} for ${put_quote.get('ask', 0):.2f} "
                           f"(expires {expiration_date.strftime('%Y-%m-%d')})")
                trades.append(put_trade)
            else:
                trades.append(None)
        else:
            logger.warning(f"Could not get quote for put contract {put_contract}")
            trades.append(None)
        
        return trades
    
    @staticmethod
    async def find_trades(
        i: int,
        strategy: StrategyConfig,
        date: datetime,
        current_price: float,
        current_bar_time: datetime,
        data_provider: Union[MockDataProvider, PolygonDataProvider],
        config: BacktestConfig,
        checker: OptimizedSignalChecker,
        spx_ohlc_data
    ) -> List[Optional[Trade]]:
        """Public interface to find Long Strangle 2 trades
        
        Returns list of [call_trade, put_trade] where each can be None if not executed
        """
        return await LongStrangle2._find_long_strangle_trades(
            i, strategy, date, current_price, current_bar_time,
            data_provider, config, checker, spx_ohlc_data
        )