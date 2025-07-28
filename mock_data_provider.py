import os
import pandas as pd
import pickle
import gzip
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MockDataProvider:
    """Mock provider that emulates SPX price, SPY volume, and options for backtesting."""

    def __init__(self):
        self.cache_dir = "data_cache"
        os.makedirs(self.cache_dir, exist_ok=True)
        self.spread = 1.5  # $1.50 bid/ask spread for options

    def _get_cache_path(self, cache_key: str) -> str:
        return os.path.join(self.cache_dir, f"{cache_key}.pkl.gz")

    def _load_from_cache(self, cache_key: str) -> Optional[pd.DataFrame]:
        cache_path = self._get_cache_path(cache_key)
        if os.path.exists(cache_path):
            try:
                with gzip.open(cache_path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.error(f"Error loading cache: {e}")
        return None

    def _save_to_cache(self, cache_key: str, data: pd.DataFrame):
        cache_path = self._get_cache_path(cache_key)
        try:
            with gzip.open(cache_path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    async def test_connection(self) -> bool:
        # Always returns True (it's a mock!)
        return True

    async def get_spx_data(self, date: datetime, granularity: str = "minute") -> pd.DataFrame:
        """
        Generate synthetic SPX price OHLCV data.
        """
        #cache_key = f"spx_{date.strftime('%Y%m%d')}_{granularity}"
        #cached_data = self._load_from_cache(cache_key)
        #if cached_data is not None:
            #return cached_data

        #np.random.seed(hash(date.strftime('%Y%m%d')) % 2**32)  # Same data per day

        # Set up trading times
        if granularity == "tick":
            freq = "1s"
        elif granularity in ["minute", "1m"]:
            freq = "1min"
        elif granularity in ["5min", "5minute"]:
            freq = "5min"
        else:
            freq = "1min"
        
        
        if isinstance(date, datetime):
           dt = date
        else:
           dt = datetime.combine(date, datetime.min.time())
        market_open = pd.Timestamp(dt.replace(hour=9, minute=30))
        market_close = pd.Timestamp(dt.replace(hour=16, minute=0))

        times = pd.date_range(market_open, market_close, freq=freq)

        # Generate price as a random walk with volatility spike at open/close
        base_price = 4500 + 200 * np.sin((times.hour*60+times.minute)/390 * 2 * np.pi)
        walk = np.cumsum(np.random.normal(0, 1.5, len(times)))
        prices = base_price + walk
        high = prices + np.abs(np.random.normal(2, 1, len(times)))
        low = prices - np.abs(np.random.normal(2, 1, len(times)))
        open_ = prices + np.random.normal(0, 0.5, len(times))
        close = prices + np.random.normal(0, 0.5, len(times))
        volume = np.random.poisson(350 if freq == "1min" else 1800, len(times))
        # Add bigger volume at open and close
        volume[0] *= 4
        volume[-1] *= 3

        df = pd.DataFrame({
            "timestamp": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume
        })
        #self._save_to_cache(cache_key, df)
        return df

    async def get_spy_volume_data(self, date: datetime, granularity: str = "minute") -> pd.DataFrame:
        """
        Generate synthetic SPY volume bars for the day (only 'timestamp' and 'volume').
        """
        #cache_key = f"spy_{date.strftime('%Y%m%d')}_5min"
        #cached_data = self._load_from_cache(cache_key)
        #if cached_data is not None:
            #return cached_data

        # Set up trading times
        if granularity == "tick":
            freq = "1s"
        elif granularity in ["minute", "1m"]:
            freq = "1min"
        elif granularity in ["5min", "5minute"]:
            freq = "5min"
        else:
            freq = "1min"
        if isinstance(date, datetime):
           dt = date
        else:
           dt = datetime.combine(date, datetime.min.time())
        market_open = pd.Timestamp(dt.replace(hour=9, minute=30))
        market_close = pd.Timestamp(dt.replace(hour=16, minute=0))
        
        times = pd.date_range(market_open, market_close, freq=freq)
        np.random.seed(hash(date.strftime('%Y%m%d')) % 2**32 + 1)

        volume = np.random.poisson(150000, len(times))
        volume[0] *= 2
        volume[-1] *= 1.5
        df = pd.DataFrame({"timestamp": times, "volume": volume})
        #self._save_to_cache(cache_key, df)
        return df

    async def get_option_chain(self, date: datetime, expiration: datetime, underlying: str = "SPX", granularity: str = "minute") -> pd.DataFrame:
        """
        Generate a synthetic option chain for a given expiry.
        """
        #cache_key = f"options_{date.strftime('%Y%m%d')}_{expiration.strftime('%Y%m%d')}"
        #cached_data = self._load_from_cache(cache_key)
        #if cached_data is not None:
            #return cached_data

        # Get SPX close price for that day (ATM center)
        spx_df = await self.get_spx_data(date, "minute")
        if spx_df.empty:
            return pd.DataFrame()
        underlying_price = spx_df['close'].iloc[-1]

        min_strike = int((underlying_price * 0.92) / 5) * 5
        max_strike = int((underlying_price * 1.08) / 5) * 5
        strikes = list(range(min_strike, max_strike + 5, 5))
        options = []
        days = (expiration - date).days + 1
        r = 0.02
        sigma = 0.17 + 0.05*np.random.rand()  # IV 17%~22%

        for strike in strikes:
            for cp in ['C', 'P']:
                # Black-Scholes formula (simplified, ignoring dividends)
                S = underlying_price
                K = strike
                T = max(days/252, 1/252)
                if T <= 0:
                    T = 1/252
                d1 = (np.log(S/K)+(r+0.5*sigma**2)*T)/(sigma*np.sqrt(T))
                d2 = d1-sigma*np.sqrt(T)
                from scipy.stats import norm
                if cp == 'C':
                    price = S*norm.cdf(d1)-K*np.exp(-r*T)*norm.cdf(d2)
                else:
                    price = K*np.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1)
                price = max(price, 0.01)
                bid = price - self.spread/2 + np.random.normal(0, 0.1)
                ask = price + self.spread/2 + np.random.normal(0, 0.1)
                last = price + np.random.normal(0, 0.2)
                volume = np.random.poisson(30)
                iv = sigma + np.random.normal(0, 0.01)
                options.append({
                    'contract': f"MOCK:{underlying}_{expiration.strftime('%y%m%d')}{cp}{K:08d}",
                    'timestamp': pd.Timestamp(date.replace(hour=16, minute=0)),
                    'strike': K,
                    'type': cp,
                    'bid': max(0.01, round(bid,2)),
                    'ask': max(0.01, round(ask,2)),
                    'last': max(0.01, round(last,2)),
                    'volume': volume,
                    'iv': round(iv, 4)
                })

        df = pd.DataFrame(options)
        #self._save_to_cache(cache_key, df)
        return df

    async def get_option_quotes(self, contracts: List[str], timestamp: datetime) -> Dict[str, Dict]:
        """
        Generate synthetic option quotes for a list of contract symbols.
        """
        results = {}
        np.random.seed(hash(timestamp.strftime('%Y%m%d%H%M')) % 2**32)
        for c in contracts:
            # Parse contract symbol for K and C/P
            try:
                parts = c.split(':')[-1]
                underlying = parts[:3]
                rest = parts[3:]
                expiry = rest[1:7]
                cp = rest[7]
                strike = int(rest[8:]) / 1000
                bid = max(0.01, round(np.random.uniform(8, 55), 2))
                ask = bid + np.random.uniform(1, 3)
                last = np.random.uniform(bid, ask)
                iv = np.random.uniform(0.15, 0.23)
                results[c] = {
                    "bid": bid,
                    "ask": round(ask, 2),
                    "last": round(last, 2),
                    "iv": round(iv, 4),
                    "volume": np.random.poisson(30)
                }
            except Exception as e:
                results[c] = {"bid":0, "ask":0, "last":0, "iv":0, "volume":0}
        return results

# Example usage (sync context):
# import asyncio
# mock = MockDataProvider()
# data = asyncio.run(mock.get_spx_data(datetime(2024, 7, 1), "5min"))
# print(data.head())
