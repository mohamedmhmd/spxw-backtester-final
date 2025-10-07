from datetime import datetime, timedelta
import logging
from typing import Dict, Optional, Union

import numpy as np
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.common import Common
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
from trades.signal_checker import OptimizedSignalChecker
import asyncio

from trades.underlying_cover_1 import UnderlyingCover1

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CreditSpread1:
    """
    Credit Spread 1 implementation with two variants:
    - Credit Spread 1(a): Counter-trend (sell at opposite extreme)
    - Credit Spread 1(b): Trend-following (sell at same extreme)
    """
    
    
    @staticmethod
    async def _find_credit_spread_strikes(
        is_call_spread: bool,
        target_strike: float,
        timestamp: datetime,
        strategy: StrategyConfig,
        data_provider: Union[MockDataProvider, PolygonDataProvider],
        target_ratio: float = 3.0,
        tolerance: float = 0.1
    ) -> Optional[Dict]:
        """
        Find optimal credit spread strikes with Loss:Win ratio closest to target (default 3:1)
        """
        # Round target to nearest 5-point strike
        if is_call_spread:
           # For calls, round UP away from the price
           short_strike = int(np.ceil(target_strike / 5) * 5)
        else:
           # For puts, round DOWN away from the price  
           short_strike = int(np.floor(target_strike / 5) * 5)
        
        # Get min/max spread width from strategy config
        min_spread = getattr(strategy, 'min_width', 5)
        max_spread = getattr(strategy, 'max_width', 50)
        step = 5
        
        quote_cache = {}
        
        async def get_spread_quotes(spread_width: int, is_call_spread: bool) -> tuple:
            """Get quotes and calculate ratio for a specific spread width"""
            if is_call_spread:
                # Call spread: short lower strike, long higher strike
                symbols = [
                    f"O:SPXW{timestamp.strftime('%y%m%d')}C{short_strike*1000:08d}",  # Short call
                    f"O:SPXW{timestamp.strftime('%y%m%d')}C{(short_strike + spread_width)*1000:08d}",  # Long call
                ]
            else:
                # Put spread: short higher strike, long lower strike
                symbols = [
                    f"O:SPXW{timestamp.strftime('%y%m%d')}P{short_strike*1000:08d}",  # Short put
                    f"O:SPXW{timestamp.strftime('%y%m%d')}P{(short_strike - spread_width)*1000:08d}",  # Long put
                ]
            
            # Fetch uncached quotes
            to_fetch = [(i, s) for i, s in enumerate(symbols) if s not in quote_cache]
            if to_fetch:
                fetched = await asyncio.gather(
                    *[data_provider._get_option_tick_quote(s, timestamp) for _, s in to_fetch],
                    return_exceptions=True
                )
                
                for (i, symbol), quote in zip(to_fetch, fetched):
                    if not isinstance(quote, Exception):
                        quote_cache[symbol] = quote
                    else:
                        quote_cache[symbol] = None
            
            quotes = [quote_cache.get(s) for s in symbols]
            
            if None in quotes:
                return None, None, None
            
            short_bid = quotes[0].get('bid')
            long_ask = quotes[1].get('ask')
            
            if None in [short_bid, long_ask]:
                return None, None, None
            
            net_credit = short_bid - long_ask
            max_loss = spread_width - net_credit
            
            if net_credit <= 0 or max_loss <= 0:
                return None, None, None
            
            ratio = max_loss / net_credit  # Loss:Win ratio
            
            return ratio, net_credit, {s: quote_cache.get(s) for s in symbols}
        
        
        # Binary search for optimal spread width
        best_width = None
        best_ratio = None
        best_diff = float('inf')
        best_credit = None
        best_quotes = None
        
        left, right = min_spread, max_spread
        
        while left <= right:
            mid = ((left + right) // 2 // step) * step
            
            ratio, net_credit, quotes = await get_spread_quotes(mid, is_call_spread)
            
            if ratio is not None:
                diff = abs(ratio - target_ratio)
                if diff < best_diff:
                    best_diff = diff
                    best_width = mid
                    best_ratio = ratio
                    best_credit = net_credit
                    best_quotes = quotes
                
                if diff <= tolerance:
                    break
                
                if ratio < target_ratio:
                    left = mid + step
                else:
                    right = mid - step
            else:
                # Try narrower spread if current one fails
                right = mid - step
        
        if best_width and best_credit:
            if is_call_spread:
                return {
                    'short_strike': short_strike,
                    'long_strike': short_strike + best_width,
                    'spread_type': 'call',
                    'net_credit': best_credit,
                    'max_loss': best_width - best_credit,
                    'ratio': best_ratio,
                    'width': best_width,
                    'quotes': best_quotes
                }
            else:
                return {
                    'short_strike': short_strike,
                    'long_strike': short_strike - best_width,
                    'spread_type': 'put',
                    'net_credit': best_credit,
                    'max_loss': best_width - best_credit,
                    'ratio': best_ratio,
                    'width': best_width,
                    'quotes': best_quotes
                }
        
        return None
    
    @staticmethod
    def _create_spread_contracts(
        short_strike: float,
        long_strike: float,
        spread_type: str,
        expiration: datetime
        
        
    ) -> Dict[str, str]:
        """Create option contract symbols for credit spread"""
        exp_str = expiration.strftime('%y%m%d')
        
        if spread_type == 'call':
            contracts = {
                'short': f"O:SPXW{exp_str}C{int(short_strike*1000):08d}",
                'long': f"O:SPXW{exp_str}C{int(long_strike*1000):08d}"
            }
        else:  # put spread
            contracts = {
                'short': f"O:SPXW{exp_str}P{int(short_strike*1000):08d}",
                'long': f"O:SPXW{exp_str}P{int(long_strike*1000):08d}"
            }
        
        return contracts
    
    @staticmethod
    async def _execute_spread(
        quotes: Dict[str, Dict],
        entry_time: datetime,
        contracts: Dict[str, str],
        strategy: StrategyConfig,
        net_credit: float,
        current_price: float,
        spread_type: str,
        variant: str,
        config: BacktestConfig,
        market_direction: str,
        spx_spy_ratio: float,
        high_of_day: float,
        low_of_day: float
    ) -> Optional[Trade]:
        """Execute credit spread trade"""
        
        # Check if we have all quotes
        if not all(contract in quotes for contract in contracts.values()):
            logger.warning("Missing option quotes, skipping trade")
            return None
        
        # Get trade size from strategy config
        size = getattr(strategy, 'cs_1_trade_size', 1)
        
        # Build trade positions
        trade_contracts = {}
        
        # Short position
        short_contract = contracts['short']
        short_quote = quotes[short_contract]
        short_price = short_quote['bid']
        short_strike = int(short_contract[-8:]) / 1000
        
        trade_contracts[short_contract] = {
            'position': -size,
            'entry_price': short_price,
            'leg_type': f'short_{spread_type}',
            'strike': short_strike,
            'used_capital': config.commission_per_contract
        }
        
        # Long position
        long_contract = contracts['long']
        long_quote = quotes[long_contract]
        long_price = long_quote['ask']
        long_strike = int(long_contract[-8:]) / 1000
        
        trade_contracts[long_contract] = {
            'position': size,
            'entry_price': long_price,
            'leg_type': f'long_{spread_type}',
            'strike': long_strike,
            'used_capital': long_price * 100 + config.commission_per_contract
        }
        
        # Create representation string
        if spread_type == 'call':
            representation = f"Bear Call Spread: {short_strike}/{long_strike} ({abs(long_strike - short_strike)})"
        else:
            representation = f"Bull Put Spread: {long_strike}/{short_strike} ({abs(long_strike - short_strike)})"
        
        # Create trade
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type=f"Credit Spread 1({variant})",
            contracts=trade_contracts,
            size=size,
            used_capital=0.0,
            metadata={
                'net_premium': net_credit,
                'strategy_name': f"Credit Spread 1({variant})",
                'entry_spx_price': current_price,
                'representation': representation,
                'spread_width': abs(long_strike - short_strike),
                'spread_type': spread_type,
                'variant': variant,
                'wing': abs(long_strike - short_strike),
                'market_direction': market_direction,
                'spx_spy_ratio': spx_spy_ratio,
                'high_of_day': high_of_day,
                'low_of_day': low_of_day,
                
                
            }
        )
        
        return trade
    
    @staticmethod
    async def _find_credit_spread_trade(
        i: int,
        strategy: StrategyConfig,
        date: datetime,
        current_price: float,
        current_bar_time: datetime,
        data_provider: Union[MockDataProvider, PolygonDataProvider],
        config: BacktestConfig,
        checker: OptimizedSignalChecker,
        spx_ohlc_data,
        variant: str = 'a'  # 'a' or 'b'
    ) -> Optional[Trade]:
        """Find and execute Credit Spread 1(a) or 1(b) trade"""
        
        # Check entry signals (same as Iron 1)
        if not checker.cs_1_check_entry_signals_5min(i, strategy):
            return None
        
        # Determine market direction using SPY data
        market_direction = await Common._determine_market_direction(current_price, date, data_provider)
        
        # Get day's extremes from SPX data
        high_of_day, low_of_day = Common._get_day_extremes(spx_ohlc_data, i)
        
        if high_of_day is None or low_of_day is None:
            logger.warning("Could not determine day's extremes")
            return None
        
        # Determine target strike based on variant and market direction
        is_call_spread = False
        if variant == 'a':  # Counter-trend
            if market_direction == 'up':
                target_strike = low_of_day  # Sell spread near low
                is_call_spread = False  # Put spread
            else:  # market down
                target_strike = high_of_day  # Sell spread near high
                is_call_spread = True  # Call spread
        else:  # variant == 'b', Trend-following
            if market_direction == 'up':
                target_strike = high_of_day  # Sell spread near high
                is_call_spread = True  # Call spread
            else:  # market down
                target_strike = low_of_day  # Sell spread near low
                is_call_spread = False  # Put spread
        
        logger.info(f"Credit Spread 1({variant}) conditions met - Market: {market_direction}, "
                   f"Target strike: {target_strike:.2f}")
        
        # Find optimal credit spread strikes
        if isinstance(date, datetime):
            option_date = date
        else:
            option_date = datetime.combine(date, datetime.min.time())
        
        # Get target Loss:Win ratio from strategy config
        target_ratio = getattr(strategy, 'cs_1_target_win_loss_ratio', 3.0)
        
        spread_result = await CreditSpread1._find_credit_spread_strikes(
            is_call_spread,
            target_strike,
            current_bar_time,
            strategy,
            data_provider,
            target_ratio
        )
        
        if not spread_result:
            logger.warning("Could not find suitable credit spread strikes")
            return None
        
        # Create contracts
        contracts = CreditSpread1._create_spread_contracts(
            spread_result['short_strike'],
            spread_result['long_strike'],
            spread_result['spread_type'],
            option_date
        )
        
        # Execute trade
        spx_spy_ratio = await Common._calculate_spx_spy_ratio(date, data_provider)
        trade = await CreditSpread1._execute_spread(
            spread_result['quotes'],
            current_bar_time,
            contracts,
            strategy,
            spread_result['net_credit'],
            current_price,
            spread_result['spread_type'],
            variant,
            config,
            market_direction,
            spx_spy_ratio,
            high_of_day,
            low_of_day
        )
        
        if trade:
            logger.info(f"Entered Credit Spread 1({variant}) at {current_bar_time}: "
                       f"{spread_result['spread_type']} spread {spread_result['short_strike']}/{spread_result['long_strike']} "
                       f"for credit ${spread_result['net_credit']:.2f}")
        
        return trade