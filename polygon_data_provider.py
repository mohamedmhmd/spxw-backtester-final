import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import aiohttp
import pickle
import gzip
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PolygonDataProvider:
    """
    PRODUCTION Polygon.io data provider supporting true second/tick-level
    OHLCV, options chains, and real-time (to-the-second) options pricing.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.polygon.io"
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache_dir = "data_cache"
        os.makedirs(self.cache_dir, exist_ok=True)

    async def __aenter__(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            self.session = None

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
            if not self.session:
                self.session = aiohttp.ClientSession()
            async with self.session.get(url, params=params) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    async def get_spx_data(self, date: datetime, granularity: str = "minute") -> pd.DataFrame:
        """
        Get SPX index data for the specific date and granularity.
        Use granularity="tick" for tick data; otherwise, use Polygon bars.
        """
        cache_key = f"spx_{date.strftime('%Y%m%d')}_{granularity}"
        cached_data = self._load_from_cache(cache_key)
        if cached_data is not None:
            return cached_data

        if granularity == "tick":
            # Use Polygon /v3/trades/SPX to fetch all trades for that day
            trades = []
            # Polygon's /v3/trades endpoint paginates by timestamp
            start_timestamp = int(date.replace(hour=9, minute=30).timestamp() * 1000)
            end_timestamp = int(date.replace(hour=16, minute=0).timestamp() * 1000)
            url = f"{self.base_url}/v3/trades/SPX"
            params = {
                "timestamp.gte": start_timestamp,
                "timestamp.lt": end_timestamp,
                "limit": 50000,
                "apiKey": self.api_key
            }
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession()
                while True:
                    async with self.session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get("results", [])
                            trades.extend(results)
                            next_url = data.get("next_url")
                            if not next_url or not results:
                                break
                            url = next_url
                        else:
                            logger.error(f"Error fetching SPX trades: {response.status}")
                            break
                if trades:
                    df = pd.DataFrame(trades)
                    df['timestamp'] = pd.to_datetime(df['sip_timestamp'], unit='ms')
                    df.rename(columns={'price': 'close', 'size': 'volume'}, inplace=True)
                    df = df[['timestamp', 'close', 'volume']]
                    self._save_to_cache(cache_key, df)
                    return df
            except Exception as e:
                logger.error(f"Error fetching SPX tick data: {e}")
                return pd.DataFrame()
            return pd.DataFrame()
        else:
            # Fallback to regular bars
            timespan = "minute"
            multiplier = 1 if granularity == "minute" else 5
            start = date.strftime('%Y-%m-%d')
            end = (date + timedelta(days=1)).strftime('%Y-%m-%d')
            url = f"{self.base_url}/v2/aggs/ticker/SPX/range/{multiplier}/{timespan}/{start}/{end}"
            params = {
                "apiKey": self.api_key,
                "adjusted": "true",
                "sort": "asc"
            }
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession()
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
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
                            self._save_to_cache(cache_key, df)
                            return df
                        else:
                            logger.warning(f"No SPX data for {date}")
                            return pd.DataFrame()
                    else:
                        logger.error(f"API error for SPX: {response.status}")
                        return pd.DataFrame()
            except Exception as e:
                logger.error(f"Error fetching SPX data: {e}")
                return pd.DataFrame()

    async def get_spy_volume_data(self, date: datetime, granularity: str = "5min") -> pd.DataFrame:
        """
        Get SPY volume bars or ticks (if granularity='tick').
        """
        cache_key = f"spy_{date.strftime('%Y%m%d')}_{granularity}"
        cached_data = self._load_from_cache(cache_key)
        if cached_data is not None:
            return cached_data

        if granularity == "tick":
            # Use Polygon /v3/trades/SPY
            trades = []
            start_timestamp = int(date.replace(hour=9, minute=30).timestamp() * 1000)
            end_timestamp = int(date.replace(hour=16, minute=0).timestamp() * 1000)
            url = f"{self.base_url}/v3/trades/SPY"
            params = {
                "timestamp.gte": start_timestamp,
                "timestamp.lt": end_timestamp,
                "limit": 50000,
                "apiKey": self.api_key
            }
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession()
                while True:
                    async with self.session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get("results", [])
                            trades.extend(results)
                            next_url = data.get("next_url")
                            if not next_url or not results:
                                break
                            url = next_url
                        else:
                            logger.error(f"Error fetching SPY trades: {response.status}")
                            break
                if trades:
                    df = pd.DataFrame(trades)
                    df['timestamp'] = pd.to_datetime(df['sip_timestamp'], unit='ms')
                    df.rename(columns={'size': 'volume'}, inplace=True)
                    df = df[['timestamp', 'volume']]
                    self._save_to_cache(cache_key, df)
                    return df
            except Exception as e:
                logger.error(f"Error fetching SPY tick data: {e}")
                return pd.DataFrame()
            return pd.DataFrame()
        else:
            # Use bars
            timespan = "minute"
            multiplier = 5 if granularity == "5min" else 1
            start = date.strftime('%Y-%m-%d')
            end = (date + timedelta(days=1)).strftime('%Y-%m-%d')
            url = f"{self.base_url}/v2/aggs/ticker/SPY/range/{multiplier}/{timespan}/{start}/{end}"
            params = {
                "apiKey": self.api_key,
                "adjusted": "true",
                "sort": "asc"
            }
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession()
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'results' in data and data['results']:
                            df = pd.DataFrame(data['results'])
                            df['timestamp'] = pd.to_datetime(df['t'], unit='ms')
                            df.rename(columns={'v': 'volume'}, inplace=True)
                            df = df[['timestamp', 'volume']]
                            self._save_to_cache(cache_key, df)
                            return df
                        else:
                            logger.warning(f"No SPY volume data for {date}")
                            return pd.DataFrame()
                    else:
                        logger.error(f"API error for SPY: {response.status}")
                        return pd.DataFrame()
            except Exception as e:
                logger.error(f"Error fetching SPY data: {e}")
                return pd.DataFrame()

    async def get_option_chain(
        self,
        date: datetime,
        expiration: datetime,
        entry_time: datetime,
        underlying: str = "SPXW"
    ) -> pd.DataFrame:
        """
        Get the option chain as of a specific second (tick-level).
        1. Query all contracts for the expiration (Polygon reference endpoint).
        2. For each contract, fetch the latest quote/trade before entry_time.
        """
        cache_key = f"options_{date.strftime('%Y%m%d')}_{expiration.strftime('%Y%m%d')}_{entry_time.strftime('%H%M%S')}"
        cached_data = self._load_from_cache(cache_key)
        if cached_data is not None:
            return cached_data

        # 1. Get all contracts for this expiry
        exp_str = expiration.strftime('%Y-%m-%d')
        url = f"{self.base_url}/v3/reference/options/contracts"
        params = {
            "underlying_ticker": "SPX",
            "expiration_date": exp_str,
            "limit": 1000,
            "apiKey": self.api_key
        }
        contracts = []
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            while True:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get('results', [])
                        contracts.extend(results)
                        next_url = data.get('next_url')
                        if not next_url or not results:
                            break
                        url = next_url
                    else:
                        logger.error(f"Error fetching contracts: {response.status}")
                        break
        except Exception as e:
            logger.error(f"Error fetching option contracts: {e}")

        # 2. For each contract, fetch the latest trade/quote before entry_time (tick-level)
        records = []
        for opt in contracts:
            contract = opt['ticker']
            strike = float(opt['strike_price'])
            opt_type = 'C' if opt['exercise_style'] == 'call' else 'P'
            quote = await self.get_option_tick_quote(contract, entry_time)
            records.append({
                'timestamp': entry_time,
                'contract': contract,
                'strike': strike,
                'type': opt_type,
                'bid': quote.get('bid', None),
                'ask': quote.get('ask', None),
                'last': quote.get('last', None),
                'volume': quote.get('volume', None)
            })
        df = pd.DataFrame(records)
        self._save_to_cache(cache_key, df)
        return df

    async def get_option_tick_quote(self, contract: str, timestamp: datetime) -> Dict:
        """
        Get the latest quote or trade for a specific contract as of the given timestamp (second).
        Priority: quote -> trade if no quote.
        """
        # 1. Try the /v3/quotes/{options_ticker} endpoint
        url = f"{self.base_url}/v3/quotes/{contract}"
        ts = int(timestamp.timestamp() * 1000)
        params = {
            "timestamp.lte": ts,
            "limit": 1,
            "sort": "desc",
            "apiKey": self.api_key
        }
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    quotes = data.get('results', [])
                    if quotes:
                        q = quotes[0]
                        return {
                            'bid': q.get('bid', None),
                            'ask': q.get('ask', None),
                            'last': q.get('last_price', None),
                            'volume': q.get('size', None)
                        }
        except Exception as e:
            logger.error(f"Error fetching quote for {contract}: {e}")

        # 2. If no quote, fallback to /v3/trades/{options_ticker}
        url = f"{self.base_url}/v3/trades/{contract}"
        try:
            params = {
                "timestamp.lte": ts,
                "limit": 1,
                "sort": "desc",
                "apiKey": self.api_key
            }
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    trades = data.get('results', [])
                    if trades:
                        t = trades[0]
                        return {
                            'bid': None,
                            'ask': None,
                            'last': t.get('price', None),
                            'volume': t.get('size', None)
                        }
        except Exception as e:
            logger.error(f"Error fetching trade for {contract}: {e}")

        # 3. If still nothing, return empty
        return {}

