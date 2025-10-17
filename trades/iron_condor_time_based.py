from datetime import datetime, timedelta
import logging
from typing import Dict, Optional, Union
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.common import Common
from trades.iron_condor_base import IronCondorBase
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
import asyncio

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IronCondorTimeBased(IronCondorBase):
    """
    Iron Condor Time-Based Strategy (SPXW 0DTE)
    
    Entry: At specific 5-minute interval
    Exit: Expiration
    
    Wings are equidistant with configurable distance constraints
    """
    
    @staticmethod
    def check_entry_time(current_bar_index: int, strategy: StrategyConfig) -> bool:
        """
        Check if current bar index matches the configured entry interval
        
        Args:
            current_bar_index: Current 5-minute bar index (0-77)
            strategy: Strategy configuration
        
        Returns:
            True if it's time to enter, False otherwise
        """
        entry_interval = getattr(strategy, 'ic_tb_entry_interval', 55)
        return current_bar_index == entry_interval
    
    @staticmethod
    async def find_optimal_iron_condor(
        current_price: float,
        timestamp: datetime,
        strategy: StrategyConfig,
        data_provider: Union[MockDataProvider, PolygonDataProvider]
    ) -> Optional[Dict]:
        """
        Find optimal Iron Condor strikes with equidistant wings
        
        Strategy:
        1. Short options: min_short_distance to max_short_distance from market
        2. Long options: min_wing_width to max_wing_width from short options
        3. Target closest ratio to target_win_loss_ratio
        """
        # Get strategy parameters
        min_short_distance = getattr(strategy, 'ic_tb_min_short_distance', 10)
        max_short_distance = getattr(strategy, 'ic_tb_max_short_distance', 40)
        min_wing_width = getattr(strategy, 'ic_tb_min_wing_width', 10)
        max_wing_width = getattr(strategy, 'ic_tb_max_wing_width', 40)
        target_ratio = getattr(strategy, 'ic_tb_target_win_loss_ratio', 1.5)
        
        # Round current price to nearest strike
        atm_strike = int(round(current_price / 5) * 5)
        
        best_combination = None
        best_ratio_diff = float('inf')
        quote_cache = {}
        
        # Helper function to get quotes
        async def get_option_quotes(short_distance: int, wing_width: int) -> Optional[Dict]:
            """Get quotes for a specific IC combination"""
            symbols = [
                f"O:SPXW{timestamp.strftime('%y%m%d')}C{(atm_strike + short_distance)*1000:08d}",  # Short call
                f"O:SPXW{timestamp.strftime('%y%m%d')}P{(atm_strike - short_distance)*1000:08d}",  # Short put
                f"O:SPXW{timestamp.strftime('%y%m%d')}C{(atm_strike + short_distance + wing_width)*1000:08d}",  # Long call
                f"O:SPXW{timestamp.strftime('%y%m%d')}P{(atm_strike - short_distance - wing_width)*1000:08d}",  # Long put
            ]
            
            # Fetch only uncached quotes
            to_fetch = []
            for symbol in symbols:
                if symbol not in quote_cache:
                    to_fetch.append(symbol)
            
            if to_fetch:
                fetched = await asyncio.gather(
                    *[data_provider._get_option_tick_quote(s, timestamp) for s in to_fetch],
                    return_exceptions=True
                )
                
                for symbol, quote in zip(to_fetch, fetched):
                    if not isinstance(quote, Exception):
                        quote_cache[symbol] = quote
                    else:
                        quote_cache[symbol] = None
            
            # Get all quotes
            quotes = {s: quote_cache.get(s) for s in symbols}
            
            # Check if all quotes are valid
            if None in quotes.values():
                return None
            
            # Calculate net premium and ratio
            sc_bid = quotes[symbols[0]].get('bid')
            sp_bid = quotes[symbols[1]].get('bid')
            lc_ask = quotes[symbols[2]].get('ask')
            lp_ask = quotes[symbols[3]].get('ask')
            
            if None in [sc_bid, sp_bid, lc_ask, lp_ask]:
                return None
            
            net_premium = sc_bid + sp_bid - lc_ask - lp_ask
            max_loss = wing_width - net_premium
            
            if net_premium <= 0 or max_loss <= 0:
                return None
            
            ratio = net_premium / max_loss
            
            return {
                'short_call': atm_strike + short_distance,
                'long_call': atm_strike + short_distance + wing_width,
                'short_put': atm_strike - short_distance,
                'long_put': atm_strike - short_distance - wing_width,
                'net_premium': net_premium,
                'max_loss': max_loss,
                'ratio': ratio,
                'short_distance': short_distance,
                'wing_width': wing_width,
                'quotes': quotes
            }
        
        # Test combinations in a smart order
        # Start with middle values and expand outward
        short_distances = []
        wing_widths = []
        
        # Create search ranges (every 5 points)
        for d in range(min_short_distance, max_short_distance + 1, 5):
            short_distances.append(d)
        
        for w in range(min_wing_width, max_wing_width + 1, 5):
            wing_widths.append(w)
        
        # Sort to start from middle values
        short_distances.sort(key=lambda x: abs(x - (min_short_distance + max_short_distance) // 2))
        wing_widths.sort(key=lambda x: abs(x - (min_wing_width + max_wing_width) // 2))
        
        # Test combinations
        for short_distance in short_distances:
            for wing_width in wing_widths:
                result = await get_option_quotes(short_distance, wing_width)
                
                if result:
                    ratio_diff = abs(result['ratio'] - target_ratio)
                    
                    if ratio_diff < best_ratio_diff:
                        best_ratio_diff = ratio_diff
                        best_combination = result
                        
                        # If we found a very close match, we can stop early
                        if ratio_diff < 0.05:  # Within 5% of target
                            logger.info(f"Found excellent match with ratio {result['ratio']:.3f} "
                                      f"(target: {target_ratio})")
                            return best_combination
        
        if best_combination:
            logger.info(f"Best Iron Condor found - Short distance: {best_combination['short_distance']}, "
                       f"Wing width: {best_combination['wing_width']}, "
                       f"Ratio: {best_combination['ratio']:.3f} (target: {target_ratio})")
        
        return best_combination
    
    @staticmethod
    async def find_trade(
        current_bar_index: int,
        strategy: StrategyConfig,
        date: datetime,
        current_price: float,
        current_bar_time: datetime,
        data_provider: Union[MockDataProvider, PolygonDataProvider],
        config: BacktestConfig,
        spx_ohlc_data
    ) -> Optional[Trade]:
        """
        Find and execute Iron Condor Time-Based trade
        
        Args:
            current_bar_index: Current 5-minute bar index (0-77)
            strategy: Strategy configuration
            date: Current date
            current_price: Current SPX price
            current_bar_time: Current bar timestamp
            data_provider: Data provider for quotes
            config: Backtest configuration
        
        Returns:
            Trade object if executed, None otherwise
        """
        # Check if it's time to enter
        if not IronCondorTimeBased.check_entry_time(current_bar_index, strategy):
            return None
        
        logger.info(f"Iron Condor Time-Based entry triggered at bar {current_bar_index} "
                   f"({current_bar_time}), SPX: ${current_price:.2f}")
        
        # Get option date
        if isinstance(date, datetime):
            option_date = date
        else:
            option_date = datetime.combine(date, datetime.min.time())
        
        # Find optimal Iron Condor
        ic_result = await IronCondorTimeBased.find_optimal_iron_condor(
            current_price,
            current_bar_time,
            strategy,
            data_provider
        )
        
        if not ic_result:
            logger.warning("Could not find suitable Iron Condor strikes")
            return None
        
        # Create option contracts
        ic_strikes = {
            'short_call': ic_result['short_call'],
            'short_put': ic_result['short_put'],
            'long_call': ic_result['long_call'],
            'long_put': ic_result['long_put']
        }
        
        ic_contracts = IronCondorTimeBased.create_option_contracts(ic_strikes, option_date)
        ic_quotes = ic_result['quotes']
        net_premium = ic_result['net_premium']
        
        # Get trade size
        trade_size = getattr(strategy, 'ic_tb_trade_size', 10)
        
        # Execute trade using base class method
        ic_trade = await IronCondorTimeBased.execute(
            ic_quotes,
            current_bar_time,
            ic_contracts,
            strategy,
            net_premium,
            current_price,
            config,
            "Iron Condor Time-Based"
        )
        
        if ic_trade:
            # Override size with strategy-specific size
            ic_trade.size = trade_size
            
            # Add additional metadata
            high_of_day, low_of_day = Common._get_day_extremes(spx_ohlc_data, current_bar_index)
            ic_trade.metadata.update({
                'entry_bar_index': current_bar_index,
                'short_distance': ic_result['short_distance'],
                'wing_width': ic_result['wing_width'],
                'win_loss_ratio': ic_result['ratio'],
                'high_of_day' : high_of_day,
                'low_of_day' : low_of_day,
                'wing' : f"{ic_result['short_distance']}/{ic_result['wing_width']}",
                'strike' : f"{ic_result['long_put']}/{ic_result['short_put']} - {ic_result['short_call']}/{ic_result['long_call']}"
            })
            
            logger.info(f"Entered Iron Condor Time-Based at {current_bar_time}: "
                       f"Strikes: {ic_result['long_put']}/{ic_result['short_put']} - "
                       f"{ic_result['short_call']}/{ic_result['long_call']}, "
                       f"Net Premium: ${net_premium:.2f}, "
                       f"Win/Loss Ratio: {ic_result['ratio']:.3f}")
            
        return ic_trade