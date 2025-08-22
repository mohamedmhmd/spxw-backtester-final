import os
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
import aiohttp
import asyncio
import pickle
import gzip
import logging
import time
import ssl


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PolygonDataProvider:
    """
    Polygon.io data provider supporting true second/tick-level
    OHLCV, options chains, and real-time (to-the-second) options pricing.
    With rate limiting and proper data structures.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.polygon.io"
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Rate limiting
        self.rate_limiter = asyncio.Semaphore(5)  # 5 concurrent requests
        self.last_request_time = 0
        self.min_request_interval = 0.2  # 200ms between requests
        self.ssl_context = self._create_ssl_context()

    async def __aenter__(self):
        if not self.session:
            connector = aiohttp.TCPConnector(
            ssl=self.ssl_context,
            limit=100,
            limit_per_host=10,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )
        
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'User-Agent': 'SPX-0DTE-Backtester/1.0.0',
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate'
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            self.session = None
            
    def _create_ssl_context(self):
        """Create SSL context with proper configuration for macOS"""
        try:
           ssl_context = ssl.create_default_context()
           if hasattr(ssl, 'Purpose'):
              ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
           ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
           if os.name == 'posix':  # Unix-like systems including macOS
              try:
                ssl_context.load_default_certs()
              except Exception as e:
                logger.warning(f"Could not load default certificates: {e}")
           return ssl_context
        except Exception as e:
            logger.error(f"Error creating SSL context: {e}")
            return None

    async def _rate_limited_request(self, url: str, params: dict = None) -> dict:
          """Make rate-limited request to Polygon API"""
          async with self.rate_limiter:
                current_time = time.time()
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.min_request_interval:
                   await asyncio.sleep(self.min_request_interval - time_since_last)
        
                self.last_request_time = time.time()
        
                if not self.session:
                   self.session = aiohttp.ClientSession()
        
                if params:
                   async with self.session.get(url, params=params) as response:
                         if response.status == 200:
                            return await response.json()
                         else:
                            logger.error(f"API error: {response.status} for {url}")
                            return {}
                else:
                    async with self.session.get(url) as response:
                          if response.status == 200:
                             return await response.json()
                          else:
                             logger.error(f"API error: {response.status} for {url}")
                             return {}

    

    async def test_connection(self) -> bool:
        url = f"{self.base_url}/v1/marketstatus/now"
        params = {"apiKey": self.api_key}
        try:
            result = await self._rate_limited_request(url, params)
            return bool(result)
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    async def get_ohlc_data(self, date: datetime, underlying: str) -> pd.DataFrame:
          timespan = "minute"
          multiplier = 5
          start = date.strftime('%Y-%m-%d')
          end = start
          url = f"{self.base_url}/v2/aggs/ticker/{underlying}/range/{multiplier}/{timespan}/{start}/{end}"
          params = {
          "apiKey": self.api_key,
          "adjusted": "true",
          "sort": "asc",
          "limit": 50000
        }
    
          try:
              all_results = []
              data = await self._rate_limited_request(url, params)
        
              if 'results' in data and data['results']:
                 all_results.extend(data['results'])
                 while 'next_url' in data and data['next_url']:
                       logger.info(f"Fetching next page of data for {underlying} on {date}")
                       next_url = data['next_url']
                       data = await self._rate_limited_request(next_url)
                
                       if 'results' in data and data['results']:
                          all_results.extend(data['results'])
                       else:
                          break
            
                 if all_results:
                    df = pd.DataFrame(all_results)
                    df = await self.process_ohlc_data(df, underlying, date)
                    logger.info(f"Fetched {len(df)} bars for {underlying} on {date}")
                    return df
                 else:
                      logger.warning(f"No {underlying} data for {date}")
                      return pd.DataFrame()
              else:
                  logger.warning(f"No {underlying} data for {date}")
                  return pd.DataFrame()
            
          except Exception as e:
               logger.error(f"Error fetching {underlying} data: {e}")
               return pd.DataFrame()  

    

    async def process_ohlc_data(self, df: pd.DataFrame, underlying : str, date: datetime) -> pd.DataFrame:
        df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
        df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp'])        
        df = df[
                    (df['timestamp'].dt.time >= pd.Timestamp('09:30:00').time()) & 
                    (df['timestamp'].dt.time <= pd.Timestamp('16:00:00').time())
                    ]
        if(underlying == "I:SPX"):
             df.rename(columns={
            'o': 'open',
            'h': 'high',
            'l': 'low',
            'c': 'close',
                     }, inplace=True)
             df = df[['timestamp', 'open', 'high', 'low', 'close']]
        elif(underlying == "SPY"):
            df.rename(columns={
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume'
            }, inplace=True)
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