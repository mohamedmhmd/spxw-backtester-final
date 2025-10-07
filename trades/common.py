from datetime import datetime, timedelta
from typing import Union

from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider

# Set up logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Common:
    @staticmethod
    async def _determine_market_direction(current_price : float, date : datetime, data_provider : Union[MockDataProvider, PolygonDataProvider]) -> str:
        """
        Determine if SPY (the market) is up or down for the day
        Returns: 'up' if current price > open, 'down' otherwise
        """
        
        yesterday_close = await data_provider.get_sp_closing_price(date - timedelta(days=1), "I:SPX")
        
        return 'up' if current_price > yesterday_close else 'down'
    
    @staticmethod
    def _get_day_extremes(spx_ohlc_data, current_idx: int) -> tuple:
        """
        Get the high and low of the day up to current index
        Returns: (high_of_day, low_of_day)
        """
        if current_idx < 0:
            return None, None
        
        # Get data from start of day to current index
        day_data = spx_ohlc_data.iloc[:current_idx + 1]
        high_of_day = day_data['high'].max()
        low_of_day = day_data['low'].min()
        
        return high_of_day, low_of_day
    
    @staticmethod
    async def _calculate_spx_spy_ratio(
        date: datetime,
        data_provider: Union[MockDataProvider, PolygonDataProvider]
    ) -> float:
        """
        Calculate the SPX:SPY conversion ratio for the day.
        Typically around 10:1 but needs daily calculation.
        """
        try:
            # Get SPX price
            spx_price = await data_provider.get_sp_closing_price(date - timedelta(days=1), "I:SPX")
            
            # Get SPY price
            spy_price = await data_provider.get_sp_closing_price(date - timedelta(days=1), "SPY")
            
            ratio = spx_price / spy_price
            logger.info(f"SPX:SPY ratio for {date}: {ratio:.2f} (SPX: ${spx_price:.2f}, SPY: ${spy_price:.2f})")
            return ratio
            
        except Exception as e:
            logger.warning(f"Could not calculate SPX:SPY ratio, using default 10:1. Error: {e}")
            return 10.0