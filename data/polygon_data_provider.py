import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import aiohttp
import asyncio
import pickle
import gzip
import logging
import time
import ssl
import json
from datetime import datetime, time as et_time
from typing import Callable, Optional
import websockets
from collections import deque


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
        self.rate_limiter = asyncio.Semaphore(200)  # 5 concurrent requests
        self.last_request_time = 0
        self.min_request_interval = 0.0  # 200ms between requests
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

    async def get_ohlc_data(self, date: datetime, underlying: str, multiplier : int = 5) -> pd.DataFrame:
          timespan = "minute"
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
    
    
    async def get_sp_closing_price(self, date: datetime, underlying) -> Optional[float]:
    
          # Format date for API call
          date_str = date.strftime('%Y-%m-%d')
    
           # Use daily aggregates endpoint for closing price
          url = f"{self.base_url}/v2/aggs/ticker/{underlying}/range/1/day/{date_str}/{date_str}"
          params = {
        "apiKey": self.api_key,
        "adjusted": "true"
    }
    
          try:
            data = await self._rate_limited_request(url, params)
        
            if 'results' in data and data['results']:
               # Should only have one result for single day
               result = data['results'][0]
               closing_price = result.get('c')  # 'c' is close price
            
               if closing_price:
                  logger.info(f"SPX closing price for {date_str}: ${closing_price:.2f}")
                  return float(closing_price)
               else:
                  logger.warning(f"No closing price in data for {date_str}")
                  return None
            else:
                logger.warning(f"No SPX data available for {date_str}")
                return None
            
          except Exception as e:
            logger.error(f"Error fetching SPX closing price for {date_str}: {e}")
            return None
        
        
        
    async def get_spy_quote(self, timestamp: datetime) -> Optional[Dict]:
    # Try quotes first
          url = f"{self.base_url}/v3/quotes/SPY"
          ts = int(timestamp.timestamp() * 1000000000)  # nanoseconds
          params = {
        "timestamp.lte": ts,
        "limit": 1,
        "order": "desc",
        "apiKey": self.api_key
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
             logger.error(f"Error fetching SPY quote: {e}")
    
          # Fallback to trades
          url = f"{self.base_url}/v3/trades/SPY"
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
                spread = max(0.01, price * 0.001)  # 0.1% spread or 1 cent minimum
                return {
                'bid': max(0.01, price - spread/2),
                'ask': price + spread/2,
                'last': price,
                'volume': t.get('size', 0)
            }
          except Exception as e:
                logger.error(f"Error fetching SPY trade: {e}")
    
        # No data available
          logger.warning(f"No SPY quote/trade data available for timestamp {timestamp}")
          return None
    


    """
Additional methods for PolygonDataProvider class to support options analysis.
Add these methods to your existing PolygonDataProvider class.
"""



    async def get_option_chain(self, underlying: str, expiration_date: datetime, 
                          strike_range: Tuple[int, int] = None) -> pd.DataFrame:
           """
              Get option chain for a specific expiration date.
    
           Args:
        underlying: The underlying symbol (e.g., "SPX")
        expiration_date: The expiration date for options
        strike_range: Optional tuple of (min_strike, max_strike) to filter strikes
    
    Returns:
        DataFrame with option chain data including calls and puts
    """
           exp_str = expiration_date.strftime('%Y-%m-%d')
    
           #     Get all option contracts for this expiration
           url = f"{self.base_url}/v3/reference/options/contracts"
           params = {
        "underlying_ticker": underlying.replace("I:", ""),  # Remove index prefix
        "expiration_date": exp_str,
        "limit": 1000,
        "apiKey": self.api_key,
        "order": "asc",
        "sort": "strike_price"
    }
    
           if strike_range:
              params["strike_price.gte"] = strike_range[0]
              params["strike_price.lte"] = strike_range[1]
    
           try:
              all_contracts = []
              data = await self._rate_limited_request(url, params)
        
              if 'results' in data:
                  all_contracts.extend(data['results'])
            
                  # Handle pagination if needed
                  while 'next_url' in data and data['next_url']:
                      data = await self._rate_limited_request(data['next_url'])
                      if 'results' in data:
                          all_contracts.extend(data['results'])
        
              if all_contracts:
                 df = pd.DataFrame(all_contracts)
                 # Parse contract details
                 df['strike'] = df['strike_price'].astype(float)
                 df['type'] = df['contract_type'].apply(lambda x: 'C' if x == 'call' else 'P')
                 df['symbol'] = df['ticker']
            
                 return df
              else:
                   logger.warning(f"No option contracts found for {underlying} expiring {exp_str}")
                   return pd.DataFrame()
            
           except Exception as e:
                  logger.error(f"Error fetching option chain: {e}")
                  return pd.DataFrame()


    async def get_historical_option_quote(self, contract: str, timestamp: datetime) -> Dict:
          """
    Get historical option quote at a specific timestamp.
    
    Args:
        contract: Option contract symbol
        timestamp: Specific timestamp for the quote
    
    Returns:
        Dict with bid, ask, mid, volume
       """
        # First try to get quote data
          url = f"{self.base_url}/v3/quotes/{contract}"
    
          # Create a time window around the timestamp (within 1 minute)
          ts_start = int((timestamp - timedelta(seconds=30)).timestamp() * 1000000000)
          ts_end = int((timestamp + timedelta(seconds=30)).timestamp() * 1000000000)
    
          params = {
             "timestamp.gte": ts_start,
            "timestamp.lte": ts_end,
        "limit": 10,
        "order": "asc",
        "apiKey": self.api_key
    }
    
          try:
             data = await self._rate_limited_request(url, params)
             quotes = data.get('results', [])
        
             if quotes:
                # Find quote closest to target timestamp
                target_ts = timestamp.timestamp() * 1000000000
                closest_quote = min(quotes, key=lambda q: abs(q.get('sip_timestamp', 0) - target_ts))
            
                bid = closest_quote.get('bid_price', 0.01)
                ask = closest_quote.get('ask_price', 0.05)
            
                return {
                'bid': bid,
                'ask': ask,
                'mid': (bid + ask) / 2,
                'spread': ask - bid,
                'bid_size': closest_quote.get('bid_size', 0),
                'ask_size': closest_quote.get('ask_size', 0),
                'timestamp': datetime.fromtimestamp(closest_quote.get('sip_timestamp', 0) / 1e9)
            }
          except Exception as e:
            logger.error(f"Error fetching historical quote for {contract}: {e}")
    
            # Fallback to trades if no quotes available
            return await self._get_historical_trade_as_quote(contract, timestamp)


    async def _get_historical_trade_as_quote(self, contract: str, timestamp: datetime) -> Dict:
          """
    Get historical trade data and convert to quote format.
    Used as fallback when quote data is unavailable.
    """
          url = f"{self.base_url}/v3/trades/{contract}"
    
          ts_start = int((timestamp - timedelta(seconds=30)).timestamp() * 1000000000)
          ts_end = int((timestamp + timedelta(seconds=30)).timestamp() * 1000000000)
    
          params = {
        "timestamp.gte": ts_start,
        "timestamp.lte": ts_end,
        "limit": 10,
        "order": "asc",
        "apiKey": self.api_key
    }
    
          try:
             data = await self._rate_limited_request(url, params)
             trades = data.get('results', [])
        
             if trades:
                # Calculate weighted average price from trades
                total_value = sum(t.get('price', 0) * t.get('size', 0) for t in trades)
                total_size = sum(t.get('size', 0) for t in trades)
            
                if total_size > 0:
                   avg_price = total_value / total_size
                   # Estimate bid/ask from trade price with typical spread
                   spread = max(0.05, avg_price * 0.015)  # 1.5% spread or 5 cents minimum
                
                   return {
                    'bid': max(0.01, avg_price - spread/2),
                    'ask': avg_price + spread/2,
                    'mid': avg_price,
                    'spread': spread,
                    'volume': total_size,
                    'trade_based': True  # Flag that this is trade-based
                }
          except Exception as e:
                logger.error(f"Error fetching historical trade for {contract}: {e}")
    
                # Return minimal valid quote if no data available
                return {
        'bid': 0.01,
        'ask': 0.05,
        'mid': 0.03,
        'spread': 0.04,
        'volume': 0,
        'no_data': True
    }


    async def get_batch_option_quotes(self, contracts: List[str], timestamp: datetime) -> Dict[str, Dict]:
          """
    Get quotes for multiple option contracts efficiently.
    
    Args:
        contracts: List of option contract symbols
        timestamp: Timestamp for the quotes
    
    Returns:
        Dict mapping contract symbol to quote data
    """
    
           # Batch the requests but respect rate limits
          batch_size = 10  # Process 10 contracts at a time
          all_quotes = {}
    
          for i in range(0, len(contracts), batch_size):
              batch = contracts[i:i + batch_size]
        
              # Create tasks for parallel execution
              tasks = [self.get_historical_option_quote(contract, timestamp) for contract in batch]
         
              # Execute batch with rate limiting
              results = await asyncio.gather(*tasks, return_exceptions=True)
        
           # Process results
              for contract, result in zip(batch, results):
                  if isinstance(result, Exception):
                     logger.error(f"Error fetching quote for {contract}: {result}")
                     all_quotes[contract] = {
                    'bid': 0.01,
                    'ask': 0.05,
                    'mid': 0.03,
                    'spread': 0.04,
                    'volume': 0,
                    'error': str(result)
                }
                  else:
                       all_quotes[contract] = result
        
                       # Small delay between batches to respect rate limits
                       if i + batch_size < len(contracts):
                          await asyncio.sleep(0.1)
    
                       return all_quotes


    async def get_option_greeks(self, contract: str, timestamp: datetime, 
                           underlying_price: float) -> Dict:
          """
    Get option Greeks for a contract at a specific time.
    Note: Polygon may not provide Greeks directly, so this might need 
    calculation based on Black-Scholes model.
    """
          # Try to get snapshot data which might include Greeks
          url = f"{self.base_url}/v3/snapshot/options/{contract}"
          params = {"apiKey": self.api_key}
    
          try:
             data = await self._rate_limited_request(url, params)
        
             if 'results' in data:
                 result = data['results']
                 greeks = result.get('greeks', {})
            
             return {
                'delta': greeks.get('delta', 0),
                'gamma': greeks.get('gamma', 0),
                'theta': greeks.get('theta', 0),
                'vega': greeks.get('vega', 0),
                'rho': greeks.get('rho', 0),
                'implied_volatility': result.get('implied_volatility', 0)
            }
          except Exception as e:
                logger.error(f"Error fetching Greeks for {contract}: {e}")
    
                   # Return empty Greeks if not available
                return {
        'delta': 0,
        'gamma': 0,
        'theta': 0,
        'vega': 0,
        'rho': 0,
        'implied_volatility': 0
    }


    async def get_vix_data(self, date: datetime) -> Optional[float]:
          """
    Get VIX (volatility index) data for a specific date.
    Useful for understanding market volatility context.
    """
          url = f"{self.base_url}/v2/aggs/ticker/I:VIX/range/1/day/{date.strftime('%Y-%m-%d')}/{date.strftime('%Y-%m-%d')}"
          params = {
        "apiKey": self.api_key,
        "adjusted": "true"
    }
    
          try:
             data = await self._rate_limited_request(url, params)
        
             if 'results' in data and data['results']:
                result = data['results'][0]
                return result.get('c')  # Closing VIX value
          except Exception as e:
                logger.error(f"Error fetching VIX data: {e}")
    
                return None


    async def validate_market_hours(self, timestamp: datetime) -> bool:
          """
          Check if timestamp is during regular market hours.
           """
          # Check if it's a weekday
          if timestamp.weekday() >= 5:  # Saturday = 5, Sunday = 6
             return False
    
          # Check time (9:30 AM - 4:00 PM ET)
          market_time = timestamp.time()
          market_open = pd.Timestamp('09:30:00').time()
          market_close = pd.Timestamp('16:00:00').time()
    
          return market_open <= market_time <= market_close


    async def get_market_holidays(self, year: int) -> List[datetime]:
           """
    Get list of market holidays for a given year.
    """
           url = f"{self.base_url}/v1/marketstatus/upcoming"
           params = {"apiKey": self.api_key}
    
           try:
              data = await self._rate_limited_request(url, params)
        
              holidays = []
              if 'results' in data:
                 for holiday in data['results']:
                     if holiday.get('status') == 'closed':
                        date_str = holiday.get('date')
                     if date_str:
                        holiday_date = datetime.strptime(date_str, '%Y-%m-%d')
                        if holiday_date.year == year:
                            holidays.append(holiday_date)
        
              return holidays
           except Exception as e:
              logger.error(f"Error fetching market holidays: {e}")
              return []
           

class PolygonLiveDataProvider:
    """
    Polygon.io WebSocket live data provider for real-time aggregated bars.
    
    Uses Polygon's aggregated minute bars (AM.*) for SPX and SPY.
    Accumulates bars throughout the trading day for signal checking.
    
    Usage:
        provider = PolygonLiveDataProvider(api_key)
        await provider.connect()
        provider.subscribe_bars("I:SPX", callback_function)
        provider.subscribe_bars("SPY", callback_function)
    """
    
    # Polygon WebSocket endpoints
    STOCKS_WS_URL = "wss://socket.polygon.io/stocks"
    OPTIONS_WS_URL = "wss://socket.polygon.io/options"
    INDICES_WS_URL = "wss://socket.polygon.io/indices"  # For SPX
    
    def __init__(self, api_key: str, bar_size_minutes: int = 5):
        """
        Initialize live data provider.
        
        Args:
            api_key: Polygon.io API key
            bar_size_minutes: Bar aggregation size (default 5 minutes)
        """
        self.api_key = api_key
        self.bar_size_minutes = bar_size_minutes
        
        # WebSocket connections
        self._stocks_ws = None
        self._indices_ws = None
        self._options_ws = None
        
        # Connection state
        self._connected = False
        self._running = False
        
        # Bar buffers - store today's bars for signal checking
        # Key: symbol, Value: list of bar dicts
        self._bar_buffers: Dict[str, deque] = {
            'I:SPX': deque(maxlen=500),  # ~8 hours of 5-min bars
            'SPY': deque(maxlen=500),
        }
        
        # Current bar being built (for 5-min aggregation from 1-min bars)
        self._current_bars: Dict[str, dict] = {}
        
        # Callbacks for new bars
        self._bar_callbacks: Dict[str, List[Callable]] = {}
        
        # Last bar timestamps (for tracking 5-min completions)
        self._last_bar_times: Dict[str, datetime] = {}
        
        # Latest prices
        self._latest_prices: Dict[str, float] = {
            'I:SPX': 0.0,
            'SPY': 0.0,
        }
        
        self.logger = logging.getLogger(__name__)
    
    # -------------------------------------------------------------------------
    # CONNECTION MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def connect(self) -> bool:
        """
        Establish WebSocket connections to Polygon.
        
        Returns:
            True if all connections successful
        """
        try:
            self._running = True
            
            # Connect to indices (for SPX)
            self._indices_ws = await websockets.connect(
                self.INDICES_WS_URL,
                ping_interval=30,
                ping_timeout=10
            )
            await self._authenticate(self._indices_ws)
            
            # Connect to stocks (for SPY)
            self._stocks_ws = await websockets.connect(
                self.STOCKS_WS_URL,
                ping_interval=30,
                ping_timeout=10
            )
            await self._authenticate(self._stocks_ws)
            
            self._connected = True
            self.logger.info("Connected to Polygon WebSocket feeds")
            
            # Start listening tasks
            asyncio.create_task(self._listen_indices())
            asyncio.create_task(self._listen_stocks())
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to Polygon WebSocket: {e}")
            self._connected = False
            return False
    
    async def disconnect(self):
        """Close all WebSocket connections"""
        self._running = False
        self._connected = False
        
        if self._indices_ws:
            await self._indices_ws.close()
        if self._stocks_ws:
            await self._stocks_ws.close()
        if self._options_ws:
            await self._options_ws.close()
        
        self.logger.info("Disconnected from Polygon WebSocket feeds")
    
    async def _authenticate(self, ws):
        """Authenticate WebSocket connection"""
        auth_msg = {"action": "auth", "params": self.api_key}
        await ws.send(json.dumps(auth_msg))
        
        response = await ws.recv()
        data = json.loads(response)
        
        if isinstance(data, list) and len(data) > 0:
            if data[0].get('status') == 'auth_success':
                self.logger.info("WebSocket authentication successful")
                return True
        
        raise Exception(f"WebSocket authentication failed: {data}")
    
    # -------------------------------------------------------------------------
    # SUBSCRIPTIONS
    # -------------------------------------------------------------------------
    
    async def subscribe_bars(self, symbol: str, callback: Optional[Callable] = None):
        """
        Subscribe to aggregated minute bars for a symbol.
        
        Args:
            symbol: "I:SPX" for SPX index, "SPY" for SPY ETF
            callback: Function called when new 5-min bar completes
                      Signature: callback(symbol, bar_data)
        """
        if callback:
            if symbol not in self._bar_callbacks:
                self._bar_callbacks[symbol] = []
            self._bar_callbacks[symbol].append(callback)
        
        # Subscribe to aggregated minute bars
        # AM.* = Aggregated Minute bars
        if symbol.startswith('I:'):
            # Index subscription (SPX)
            clean_symbol = symbol.replace('I:', '')
            subscribe_msg = {
                "action": "subscribe",
                "params": f"AM.{clean_symbol}"  # Aggregated minute for indices
            }
            if self._indices_ws:
                await self._indices_ws.send(json.dumps(subscribe_msg))
                self.logger.info(f"Subscribed to {symbol} aggregated bars")
        else:
            # Stock subscription (SPY)
            subscribe_msg = {
                "action": "subscribe",
                "params": f"AM.{symbol}"  # Aggregated minute for stocks
            }
            if self._stocks_ws:
                await self._stocks_ws.send(json.dumps(subscribe_msg))
                self.logger.info(f"Subscribed to {symbol} aggregated bars")
    
    async def subscribe_quotes(self, option_symbol: str, callback: Callable):
        """
        Subscribe to real-time option quotes (for order execution).
        
        Args:
            option_symbol: e.g., "O:SPXW250109C06000000"
            callback: Function called on quote update
        """
        if not self._options_ws:
            self._options_ws = await websockets.connect(
                self.OPTIONS_WS_URL,
                ping_interval=30,
                ping_timeout=10
            )
            await self._authenticate(self._options_ws)
            asyncio.create_task(self._listen_options())
        
        subscribe_msg = {
            "action": "subscribe",
            "params": f"Q.{option_symbol}"  # Quote channel for options
        }
        await self._options_ws.send(json.dumps(subscribe_msg))
    
    # -------------------------------------------------------------------------
    # WEBSOCKET LISTENERS
    # -------------------------------------------------------------------------
    
    async def _listen_indices(self):
        """Listen to indices WebSocket (SPX)"""
        while self._running and self._indices_ws:
            try:
                message = await self._indices_ws.recv()
                await self._process_message(message, 'I:SPX')
            except websockets.ConnectionClosed:
                self.logger.warning("Indices WebSocket connection closed")
                break
            except Exception as e:
                self.logger.error(f"Error in indices listener: {e}")
    
    async def _listen_stocks(self):
        """Listen to stocks WebSocket (SPY)"""
        while self._running and self._stocks_ws:
            try:
                message = await self._stocks_ws.recv()
                await self._process_message(message, 'SPY')
            except websockets.ConnectionClosed:
                self.logger.warning("Stocks WebSocket connection closed")
                break
            except Exception as e:
                self.logger.error(f"Error in stocks listener: {e}")
    
    async def _listen_options(self):
        """Listen to options WebSocket (for quotes)"""
        while self._running and self._options_ws:
            try:
                message = await self._options_ws.recv()
                # Process option quotes for order execution
                await self._process_option_message(message)
            except websockets.ConnectionClosed:
                self.logger.warning("Options WebSocket connection closed")
                break
            except Exception as e:
                self.logger.error(f"Error in options listener: {e}")
    
    async def _process_message(self, message: str, default_symbol: str):
        """
        Process incoming WebSocket message.
        
        Polygon sends 1-minute aggregated bars. We aggregate these into
        5-minute bars for signal checking.
        """
        try:
            data = json.loads(message)
            
            if not isinstance(data, list):
                return
            
            for item in data:
                ev = item.get('ev')
                
                if ev == 'AM':  # Aggregated Minute bar
                    await self._handle_minute_bar(item, default_symbol)
                    
        except json.JSONDecodeError:
            pass
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
    
    async def _handle_minute_bar(self, bar_data: dict, default_symbol: str):
        """
        Handle incoming 1-minute bar and aggregate into 5-minute bars.
        
        Polygon AM bar format:
        {
            "ev": "AM",
            "sym": "SPY",
            "v": 1234,       # Volume
            "av": 12345,     # Accumulated volume
            "op": 450.00,    # Official open price
            "vw": 450.50,    # VWAP
            "o": 450.10,     # Open
            "c": 450.50,     # Close
            "h": 450.60,     # High
            "l": 450.00,     # Low
            "a": 450.30,     # Today's VWAP
            "z": 100,        # Average trade size
            "s": 1704380400000,  # Start timestamp (ms)
            "e": 1704380460000,  # End timestamp (ms)
        }
        """
        # Determine symbol
        symbol = bar_data.get('sym', '')
        if symbol == 'SPX':
            symbol = 'I:SPX'
        elif symbol == '' and default_symbol:
            symbol = default_symbol
        
        # Parse bar
        bar_time = datetime.fromtimestamp(bar_data.get('s', 0) / 1000)
        
        # Update latest price
        close_price = bar_data.get('c', 0)
        if close_price > 0:
            self._latest_prices[symbol] = close_price
        
        # Check if within market hours (9:30 AM - 4:00 PM ET)
        if not self._is_market_hours(bar_time):
            return
        
        # Aggregate into 5-minute bars
        bar_minute = bar_time.minute
        five_min_slot = (bar_minute // self.bar_size_minutes) * self.bar_size_minutes
        slot_time = bar_time.replace(minute=five_min_slot, second=0, microsecond=0)
        
        # Initialize or update current bar
        if symbol not in self._current_bars or self._current_bars[symbol].get('slot_time') != slot_time:
            # New 5-minute bar - save previous if exists
            if symbol in self._current_bars and self._current_bars[symbol]:
                await self._finalize_bar(symbol)
            
            # Start new bar
            self._current_bars[symbol] = {
                'slot_time': slot_time,
                'timestamp': slot_time,
                'open': bar_data.get('o', 0),
                'high': bar_data.get('h', 0),
                'low': bar_data.get('l', 0),
                'close': bar_data.get('c', 0),
                'volume': bar_data.get('v', 0),
                'bar_count': 1,
            }
        else:
            # Update existing bar
            current = self._current_bars[symbol]
            current['high'] = max(current['high'], bar_data.get('h', 0))
            current['low'] = min(current['low'], bar_data.get('l', 0)) if current['low'] > 0 else bar_data.get('l', 0)
            current['close'] = bar_data.get('c', 0)
            current['volume'] += bar_data.get('v', 0)
            current['bar_count'] += 1
        
        # Check if 5-minute bar is complete (received all 5 constituent bars)
        # Or use time-based completion
        if self._is_bar_complete(symbol, bar_time):
            await self._finalize_bar(symbol)
    
    def _is_bar_complete(self, symbol: str, current_time: datetime) -> bool:
        """Check if current 5-minute bar is complete"""
        if symbol not in self._current_bars:
            return False
        
        current_bar = self._current_bars[symbol]
        slot_time = current_bar.get('slot_time')
        
        if not slot_time:
            return False
        
        # Bar is complete when we're in the next 5-minute slot
        next_slot = slot_time.minute + self.bar_size_minutes
        if current_time.minute >= next_slot or (next_slot >= 60 and current_time.minute < self.bar_size_minutes):
            return True
        
        return False
    
    async def _finalize_bar(self, symbol: str):
        """Finalize and store completed 5-minute bar"""
        if symbol not in self._current_bars:
            return
        
        bar = self._current_bars[symbol]
        if not bar or bar.get('bar_count', 0) == 0:
            return
        
        # Add to buffer
        self._bar_buffers[symbol].append({
            'timestamp': bar['timestamp'],
            'open': bar['open'],
            'high': bar['high'],
            'low': bar['low'],
            'close': bar['close'],
            'volume': bar.get('volume', 0),
        })
        
        self.logger.debug(f"Completed 5-min bar for {symbol}: {bar['timestamp']} "
                         f"O:{bar['open']:.2f} H:{bar['high']:.2f} L:{bar['low']:.2f} C:{bar['close']:.2f}")
        
        # Invoke callbacks
        if symbol in self._bar_callbacks:
            for callback in self._bar_callbacks[symbol]:
                try:
                    await callback(symbol, bar)
                except Exception as e:
                    self.logger.error(f"Error in bar callback: {e}")
        
        # Clear current bar
        self._current_bars[symbol] = {}
    
    async def _process_option_message(self, message: str):
        """Process option quote message"""
        # Handle option quote updates for order execution
        pass
    
    # -------------------------------------------------------------------------
    # DATA ACCESS
    # -------------------------------------------------------------------------
    
    def get_bars_dataframe(self, symbol: str) -> pd.DataFrame:
        """
        Get accumulated bars as DataFrame (for signal checking).
        
        Returns DataFrame with columns: timestamp, open, high, low, close, volume
        """
        if symbol not in self._bar_buffers:
            return pd.DataFrame()
        
        bars = list(self._bar_buffers[symbol])
        if not bars:
            return pd.DataFrame()
        
        return pd.DataFrame(bars)
    
    def get_latest_price(self, symbol: str) -> float:
        """Get latest price for symbol"""
        return self._latest_prices.get(symbol, 0.0)
    
    def get_bar_count(self, symbol: str) -> int:
        """Get number of bars accumulated today"""
        return len(self._bar_buffers.get(symbol, []))
    
    def clear_buffers(self):
        """Clear bar buffers (call at start of new day)"""
        for symbol in self._bar_buffers:
            self._bar_buffers[symbol].clear()
        self._current_bars = {}
        self.logger.info("Cleared bar buffers for new trading day")
    
    def _is_market_hours(self, dt: datetime) -> bool:
        """Check if timestamp is during market hours"""
        market_open = datetime.time(9, 30)
        market_close = datetime.time(16, 0)
        return market_open <= dt.time() <= market_close
    
    @property
    def is_connected(self) -> bool:
        return self._connected