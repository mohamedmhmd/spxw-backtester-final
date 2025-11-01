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