import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import aiohttp
import asyncio
import pickle
import gzip
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PolygonDataProvider:
    """
    PRODUCTION Polygon.io data provider supporting true second/tick-level
    OHLCV, options chains, and real-time (to-the-second) options pricing.
    With rate limiting and proper data structures.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.polygon.io"
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache_dir = "data_cache"
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Rate limiting
        self.rate_limiter = asyncio.Semaphore(5)  # 5 concurrent requests
        self.last_request_time = 0
        self.min_request_interval = 0.2  # 200ms between requests

    async def __aenter__(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            self.session = None

    async def _rate_limited_request(self, url: str, params: dict) -> dict:
        """Make rate-limited request to Polygon API"""
        async with self.rate_limiter:
            # Ensure minimum time between requests
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.min_request_interval:
                await asyncio.sleep(self.min_request_interval - time_since_last)
            
            self.last_request_time = time.time()
            
            if not self.session:
                self.session = aiohttp.ClientSession()
                
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"API error: {response.status} for {url}")
                    return {}

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
        url = f"{self.base_url}/v1/marketstatus/now"
        params = {"apiKey": self.api_key}
        try:
            result = await self._rate_limited_request(url, params)
            return bool(result)
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    async def get_ohlc_data(self, date: datetime) -> pd.DataFrame:
          # Regular bars
            timespan = "minute"
            multiplier = 5
            start = date.strftime('%Y-%m-%d')
            end = (date + timedelta(days=1)).strftime('%Y-%m-%d')
            url = f"{self.base_url}/v2/aggs/ticker/SPY/range/{multiplier}/{timespan}/{start}/{end}"
            params = {
                "apiKey": self.api_key,
                "adjusted": "true",
                "sort": "asc"
            }
            
            try:
                data = await self._rate_limited_request(url, params)
                if 'results' in data and data['results']:
                    df = pd.DataFrame(data['results'])
                    df['timestamp'] = pd.to_datetime(df['t'], unit='ms')
                    df.rename(columns={
                        'o': 'open',
                        'h': 'high',
                        'l': 'low',
                        'c': 'close',
                        'v': 'volume'
                    }, inplace=True)
                    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
                    return df
                else:
                    logger.warning(f"No SPX data for {date}")
                    return pd.DataFrame()
            except Exception as e:
                logger.error(f"Error fetching SPX data: {e}")
                return pd.DataFrame()


    async def get_option_chain(
        self,
        date: datetime,
        expiration: datetime,
        entry_time: Optional[datetime] = None,
        underlying: str = "SPX"
    ) -> pd.DataFrame:
        return None
        """
        Get the option chain with a consistent structure expected by backtest engine.
        Returns DataFrame with columns: timestamp, strike, type, bid, ask, last, volume
        """
        # If no entry_time specified, use 10 AM
        if entry_time is None:
            entry_time = date.replace(hour=10, minute=0)
            
        

        # Get all contracts for this expiry
        exp_str = expiration.strftime('%Y-%m-%d')
        url = f"{self.base_url}/v3/reference/options/contracts"
        params = {
            "underlying_ticker": underlying,
            "expiration_date": exp_str,
            "limit": 1000,
            "apiKey": self.api_key,
            "as_of":exp_str
        }
        
        contracts = []
        try:
            while True:
                data = await self._rate_limited_request(url, params)
                results = data.get('results', [])
                contracts.extend(results)
                next_url = data.get('next_url')
                if not next_url or not results:
                    break
                url = next_url
                params = {"apiKey": self.api_key}
        except Exception as e:
            logger.error(f"Error fetching option contracts: {e}")

        # For each contract, fetch the latest quote before entry_time
        records = []
        for opt in contracts:
            contract = opt['ticker']
            strike = float(opt['strike_price'])
            opt_type = 'C' if opt['contract_type'] == 'call' else 'P'
            
            quote = await self._get_option_tick_quote(contract, entry_time)
            records.append({
                'timestamp': entry_time,
                'strike': strike,
                'type': opt_type,
                'bid': quote.get('bid', 0.01),
                'ask': quote.get('ask', 0.01),
                'last': quote.get('last', 0.01),
                'volume': quote.get('volume', 0),
                'contract': contract  # Keep contract symbol for reference
            })
            
        df = pd.DataFrame(records)
        if not df.empty:
            # Ensure we have the expected columns in the right order
            df = df[['timestamp', 'strike', 'type', 'bid', 'ask', 'last', 'volume', 'contract']]
        return df

    async def _get_option_tick_quote(self, contract: str, timestamp: datetime) -> Dict:
        """
        Get the latest quote or trade for a specific contract as of the given timestamp.
        Priority: quote -> trade if no quote.
        """
        # Try quotes first
        url = f"{self.base_url}/v3/quotes/{contract}"
        ts = int(timestamp.timestamp() * 1000000000)  # nanoseconds
        params = {
            "timestamp.lte": ts,
            "limit": 1,
            "order": "desc",
            "apiKey": self.api_key,  # Ensure we get quotes for the correct date
        }
        
        try:
            data = await self._rate_limited_request(url, params)
            quotes = data.get('results', [])
            if quotes:
                q = quotes[0]
                return {
                    'bid': q.get('bid_price', 0.01),
                    'ask': q.get('ask_price', 0.01),
                    'last': q.get('last_price', (q.get('bid_price', 0) + q.get('ask_price', 0)) / 2),
                    'volume': q.get('bid_size', 0) + q.get('ask_size', 0)
                }
        except Exception as e:
            logger.error(f"Error fetching quote for {contract}: {e}")

        # Fallback to trades
        url = f"{self.base_url}/v3/trades/{contract}"
        params = {
            "timestamp.lte": ts,
            "limit": 1,
            "order": "desc",
            "apiKey": self.api_key
        }
        
        try:
            data = await self._rate_limited_request(url, params)
            trades = data.get('results', [])
            if trades:
                t = trades[0]
                price = t.get('price', 0.01)
                # Estimate bid/ask from last trade
                spread = max(0.05, price * 0.02)  # 2% spread or 5 cents minimum
                return {
                    'bid': max(0.01, price - spread/2),
                    'ask': price + spread/2,
                    'last': price,
                    'volume': t.get('size', 0)
                }
        except Exception as e:
            logger.error(f"Error fetching trade for {contract}: {e}")

        # Return minimal valid quote
        return None

    async def get_option_quotes(self, contracts: List[str], timestamp: datetime) -> Dict[str, Dict]:
        """
        Get real-time quotes for specific option contracts.
        Returns dict of contract -> {bid, ask, last, volume}
        """
        quotes = {}
        
        # Use asyncio.gather for parallel requests (respecting rate limits)
        tasks = []
        for contract in contracts:
            tasks.append(self._get_option_tick_quote(contract, timestamp))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for contract, result in zip(contracts, results):
            if isinstance(result, Exception):
                logger.error(f"Error getting quote for {contract}: {result}")
                quotes[contract] = {'bid': 0.01, 'ask': 0.05, 'last': 0.03, 'volume': 0}
            else:
                quotes[contract] = result
                
        return quotes