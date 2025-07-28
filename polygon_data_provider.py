import pandas as pd
import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import aiohttp
import pickle
import gzip
import logging
# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PolygonDataProvider:
    """Complete implementation of Polygon.io data provider"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.polygon.io"
        self.session = None
        self.cache_dir = "data_cache"
        os.makedirs(self.cache_dir, exist_ok=True)
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _get_cache_path(self, cache_key: str) -> str:
        """Get cache file path"""
        return os.path.join(self.cache_dir, f"{cache_key}.pkl.gz")
    
    def _load_from_cache(self, cache_key: str) -> Optional[pd.DataFrame]:
        """Load data from cache"""
        cache_path = self._get_cache_path(cache_key)
        if os.path.exists(cache_path):
            try:
                with gzip.open(cache_path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.error(f"Error loading cache: {e}")
        return None
    
    def _save_to_cache(self, cache_key: str, data: pd.DataFrame):
        """Save data to cache"""
        cache_path = self._get_cache_path(cache_key)
        try:
            with gzip.open(cache_path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")
    
    async def test_connection(self) -> bool:
          """Test Polygon API connection (lightweight)."""
          url = f"{self.base_url}/v1/marketstatus/now"
          params = {"apiKey": self.api_key}
          try:
             async with self.session.get(url, params=params) as response:
                   return response.status == 200
          except Exception as e:
                  return False
    
    async def get_spx_data(self, date: datetime, granularity: str = "minute") -> pd.DataFrame:
        """Get SPX index data for a specific date"""
        cache_key = f"spx_{date.strftime('%Y%m%d')}_{granularity}"
        
        # Check cache first
        cached_data = self._load_from_cache(cache_key)
        if cached_data is not None:
            return cached_data
        
        # Determine timespan and multiplier
        if granularity == "tick":
            # For tick data, we need to use trades endpoint
            return await self._get_tick_data("SPX", date)
        elif granularity == "minute":
            timespan = "minute"
            multiplier = 1
        elif granularity == "5min":
            timespan = "minute"
            multiplier = 5
        else:
            timespan = "minute"
            multiplier = 1
        
        # Format dates
        start = date.strftime('%Y-%m-%d')
        end = (date + timedelta(days=1)).strftime('%Y-%m-%d')
        
        url = f"{self.base_url}/v2/aggs/ticker/SPX/range/{multiplier}/{timespan}/{start}/{end}"
        params = {
            "apiKey": self.api_key,
            "adjusted": "true",
            "sort": "asc"
        }
        
        try:
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
                        
                        # Save to cache
                        self._save_to_cache(cache_key, df)
                        return df
                    else:
                        logger.warning(f"No data for SPX on {date}")
                        return pd.DataFrame()
                else:
                    logger.error(f"API error: {response.status}")
                    return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching SPX data: {e}")
            return pd.DataFrame()
    
    async def _get_tick_data(self, symbol: str, date: datetime) -> pd.DataFrame:
        """Get tick-level trade data"""
        cache_key = f"{symbol}_{date.strftime('%Y%m%d')}_ticks"
        
        # Check cache
        cached_data = self._load_from_cache(cache_key)
        if cached_data is not None:
            return cached_data
        
        all_trades = []
        timestamp = int(date.timestamp() * 1000000000)  # nanoseconds
        end_timestamp = int((date + timedelta(days=1)).timestamp() * 1000000000)
        
        while timestamp < end_timestamp:
            url = f"{self.base_url}/v3/trades/{symbol}"
            params = {
                "apiKey": self.api_key,
                "timestamp.gte": timestamp,
                "timestamp.lt": end_timestamp,
                "limit": 50000,
                "sort": "timestamp"
            }
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'results' in data and data['results']:
                            all_trades.extend(data['results'])
                            
                            # Check if there's more data
                            if 'next_url' not in data:
                                break
                            
                            # Update timestamp for next request
                            last_timestamp = data['results'][-1]['participant_timestamp']
                            timestamp = last_timestamp + 1
                        else:
                            break
                    else:
                        logger.error(f"API error getting ticks: {response.status}")
                        break
            except Exception as e:
                logger.error(f"Error fetching tick data: {e}")
                break
        
        if all_trades:
            df = pd.DataFrame(all_trades)
            df['timestamp'] = pd.to_datetime(df['participant_timestamp'], unit='ns')
            df.rename(columns={'price': 'close', 'size': 'volume'}, inplace=True)
            df = df[['timestamp', 'close', 'volume']]
            
            # Save to cache
            self._save_to_cache(cache_key, df)
            return df
        
        return pd.DataFrame()
    
    async def get_spy_volume_data(self, date: datetime) -> pd.DataFrame:
        """Get SPY volume data for entry signal calculations"""
        cache_key = f"spy_{date.strftime('%Y%m%d')}_5min"
        
        # Check cache
        cached_data = self._load_from_cache(cache_key)
        if cached_data is not None:
            return cached_data
        
        start = date.strftime('%Y-%m-%d')
        end = (date + timedelta(days=1)).strftime('%Y-%m-%d')
        
        url = f"{self.base_url}/v2/aggs/ticker/SPY/range/5/minute/{start}/{end}"
        params = {
            "apiKey": self.api_key,
            "adjusted": "true",
            "sort": "asc"
        }
        
        try:
            self.session = aiohttp.ClientSession()
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'results' in data and data['results']:
                        df = pd.DataFrame(data['results'])
                        df['timestamp'] = pd.to_datetime(df['t'], unit='ms')
                        df.rename(columns={'v': 'volume'}, inplace=True)
                        df = df[['timestamp', 'volume']]
                        
                        # Save to cache
                        self._save_to_cache(cache_key, df)
                        return df
                    else:
                        return pd.DataFrame()
                else:
                    logger.error(f"API error for SPY: {response.status}")
                    return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching SPY data: {e}")
            return pd.DataFrame()
    
    async def get_option_chain(self, date: datetime, expiration: datetime) -> pd.DataFrame:
        """Get full option chain for a specific expiration"""
        cache_key = f"options_{date.strftime('%Y%m%d')}_{expiration.strftime('%Y%m%d')}"
        
        # Check cache
        cached_data = self._load_from_cache(cache_key)
        if cached_data is not None:
            return cached_data
        
        # Format contract date
        exp_str = expiration.strftime('%y%m%d')
        
        # Get strikes around current SPX price
        # First, get current SPX price
        spx_data = await self.get_spx_data(date, "minute")
        if spx_data.empty:
            return pd.DataFrame()
        
        current_price = spx_data.iloc[-1]['close']
        
        # Generate strike prices (SPX strikes are in increments of 5)
        min_strike = int((current_price * 0.9) / 5) * 5
        max_strike = int((current_price * 1.1) / 5) * 5
        strikes = list(range(min_strike, max_strike + 5, 5))
        
        all_options = []
        
        for strike in strikes:
            for option_type in ['C', 'P']:
                # SPX-W format: SPXW YYMMDD C/P STRIKE
                contract = f"O:SPXW{exp_str}{option_type}{strike:08d}"
                
                # Get option quotes
                url = f"{self.base_url}/v2/aggs/ticker/{contract}/range/1/minute/{date.strftime('%Y-%m-%d')}/{date.strftime('%Y-%m-%d')}"
                params = {
                    "apiKey": self.api_key,
                    "adjusted": "true",
                    "sort": "asc"
                }
                
                try:
                    async with self.session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if 'results' in data and data['results']:
                                for result in data['results']:
                                    option_data = {
                                        'timestamp': pd.to_datetime(result['t'], unit='ms'),
                                        'contract': contract,
                                        'strike': strike,
                                        'type': option_type,
                                        'bid': result.get('l', 0),  # Using low as proxy for bid
                                        'ask': result.get('h', 0),  # Using high as proxy for ask
                                        'last': result.get('c', 0),
                                        'volume': result.get('v', 0)
                                    }
                                    all_options.append(option_data)
                except Exception as e:
                    logger.error(f"Error fetching option {contract}: {e}")
                    continue
        
        if all_options:
            df = pd.DataFrame(all_options)
            # Save to cache
            self._save_to_cache(cache_key, df)
            return df
        
        return pd.DataFrame()
    
    async def get_option_quotes(self, contracts: List[str], timestamp: datetime) -> Dict[str, Dict]:
        """Get real-time quotes for specific option contracts"""
        quotes = {}
        
        for contract in contracts:
            # Get snapshot quote
            url = f"{self.base_url}/v2/snapshot/options/{contract}"
            params = {"apiKey": self.api_key}
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'results' in data:
                            result = data['results']
                            quotes[contract] = {
                                'bid': result.get('day', {}).get('l', 0),
                                'ask': result.get('day', {}).get('h', 0),
                                'last': result.get('day', {}).get('c', 0),
                                'volume': result.get('day', {}).get('v', 0)
                            }
                    else:
                        logger.error(f"Error getting quote for {contract}: {response.status}")
                        quotes[contract] = {'bid': 0, 'ask': 0, 'last': 0, 'volume': 0}
            except Exception as e:
                logger.error(f"Error fetching quote for {contract}: {e}")
                quotes[contract] = {'bid': 0, 'ask': 0, 'last': 0, 'volume': 0}
        
        return quotes