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


class LongStrangle1:
    """
    Long Strangle 1 implementation:
    - Long Strangle 1(a): Buy call at strike closest to high of day
    - Long Strangle 1(b): Buy put at strike closest to low of day
    
    Entry conditions same as Iron 1:
    1) Three consecutive 5-minute candles at volume below 50% of first candle
    2) Last four 5-minute candles not all in same direction
    3) Average range of last two candles below 80% of day's average
    """
    
    @staticmethod
    def _round_to_nearest_strike(price: float, is_call: bool = True) -> int:
        """Round price to nearest 5-point strike"""
        # Round to nearest 5
        return int(round(price / 5) * 5)
    
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
        high_of_day: float,
        low_of_day: float,
        variant: str
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
                'used_capital': ask_price * 100 * size + config.commission_per_contract * size
            }
        }
        
        # Create representation string
        representation = f"Long {leg_type.capitalize()}: {strike}"
        
        # Create trade
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type=f"Long Strangle 1({variant})",
            contracts=trade_contracts,
            size=size,
            used_capital=0.0,
            metadata={
                'net_premium': -ask_price,
                'strategy_name': f"Long Strangle 1({variant})",
                'entry_spx_price': current_price,
                'representation': representation,
                'leg_type': leg_type,
                'variant': variant,
                'strike': strike,
                'high_of_day': high_of_day,
                'low_of_day': low_of_day
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
        """Find and execute Long Strangle 1(a) and 1(b) trades"""
        
        # Check entry signals (same as Iron 1)
        # Using Iron 1 parameters with Long Strangle 1 prefix if available
        if not checker.long_strangle_1_check_entry_signals(i, strategy):
            return None
        
        # Get day's extremes from SPX data
        high_of_day, low_of_day = Common._get_day_extremes(spx_ohlc_data, i)
        
        if high_of_day is None or low_of_day is None:
            logger.warning("Could not determine day's extremes")
            return None
        
        logger.info(f"Long Strangle 1 conditions met - High: {high_of_day:.2f}, Low: {low_of_day:.2f}")
        
        # Round to nearest strikes
        call_strike = int(round(high_of_day / 5) * 5)
        put_strike = int(round(low_of_day / 5) * 5)
        
        # Get expiration date
        if isinstance(date, datetime):
            option_date = date
        else:
            option_date = datetime.combine(date, datetime.min.time())
        
        # Create contracts
        call_contract = LongStrangle1._create_option_contract(call_strike, 'call', option_date)
        put_contract = LongStrangle1._create_option_contract(put_strike, 'put', option_date)
        
        # Get quotes
        call_quote, put_quote = await asyncio.gather(
            LongStrangle1._get_option_quote(call_contract, current_bar_time, data_provider),
            LongStrangle1._get_option_quote(put_contract, current_bar_time, data_provider),
            return_exceptions=True
        )
        
        trades = []
        
        # Execute Long Strangle 1(a) - Call
        if not isinstance(call_quote, Exception) and call_quote:
            # Get trade size for variant (a)
            call_size = getattr(strategy, 'ls_1_trade_a_size', 10)
            
            call_trade = await LongStrangle1._execute_long_leg(
                call_contract,
                call_quote,
                current_bar_time,
                call_size,
                'call',
                call_strike,
                config,
                current_price,
                high_of_day,
                low_of_day,
                'a'
            )
            
            if call_trade:
                logger.info(f"Entered Long Strangle 1(a) at {current_bar_time}: "
                           f"Long Call {call_strike} for ${call_quote.get('ask', 0):.2f}")
                trades.append(call_trade)
            else:
                trades.append(None)
        else:
            logger.warning(f"Could not get quote for call contract {call_contract}")
            trades.append(None)
        
        # Execute Long Strangle 1(b) - Put
        if not isinstance(put_quote, Exception) and put_quote:
            # Get trade size for variant (b)
            put_size = getattr(strategy, 'ls_1_trade_b_size', 10)
            
            put_trade = await LongStrangle1._execute_long_leg(
                put_contract,
                put_quote,
                current_bar_time,
                put_size,
                'put',
                put_strike,
                config,
                current_price,
                high_of_day,
                low_of_day,
                'b'
            )
            
            if put_trade:
                logger.info(f"Entered Long Strangle 1(b) at {current_bar_time}: "
                           f"Long Put {put_strike} for ${put_quote.get('ask', 0):.2f}")
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
        """Public interface to find Long Strangle trades
        
        Returns list of [call_trade, put_trade] where each can be None if not executed
        """
        return await LongStrangle1._find_long_strangle_trades(
            i, strategy, date, current_price, current_bar_time,
            data_provider, config, checker, spx_ohlc_data
        )