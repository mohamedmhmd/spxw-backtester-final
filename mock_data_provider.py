import os
import pandas as pd
import pickle
import gzip
import logging
import numpy as np
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional
from scipy.stats import norm
from scipy.ndimage import gaussian_filter1d

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MockDataProvider:
    """
    Highly realistic mock provider that emulates SPX price, SPY volume, and options.
    Simulates actual market microstructure, volatility patterns, and options behavior.
    """

    def __init__(self):
        self.cache_dir = "data_cache"
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Realistic market parameters
        self.spx_base_price = 4500.0
        self.spy_base_volume = 80000000  # 80M shares typical daily
        
        # Market regimes (randomly selected per day)
        self.regimes = {
            'normal': {'vol': 0.012, 'trend': 0.0001, 'vol_mult': 1.0},
            'volatile': {'vol': 0.025, 'trend': -0.0002, 'vol_mult': 1.5},
            'trending': {'vol': 0.015, 'trend': 0.0003, 'vol_mult': 1.2},
            'quiet': {'vol': 0.008, 'trend': 0.0, 'vol_mult': 0.7}
        }
        
        # Intraday patterns
        self.intraday_patterns = self._create_intraday_patterns()

    def _create_intraday_patterns(self) -> Dict:
        """Create realistic intraday volume and volatility patterns"""
        minutes = np.arange(390)  # 6.5 hours
        
        # Volume: U-shaped with opening/closing spikes
        volume_base = 0.5 + 0.5 * np.abs(np.cos(np.pi * minutes / 390))
        volume_open = np.exp(-minutes / 15) * 2
        volume_close = np.exp(-(390 - minutes) / 15) * 1.5
        volume_lunch = 1 - 0.3 * np.exp(-((minutes - 180) ** 2) / 1800)
        volume_pattern = (volume_base + volume_open + volume_close) * volume_lunch
        volume_pattern = gaussian_filter1d(volume_pattern, sigma=5)
        
        # Volatility: Higher at open/close
        vol_pattern = np.ones(390)
        vol_pattern[:30] = 1.5   # First 30 min
        vol_pattern[-30:] = 1.3  # Last 30 min
        vol_pattern = gaussian_filter1d(vol_pattern, sigma=10)
        
        return {
            'volume': volume_pattern / volume_pattern.mean(),
            'volatility': vol_pattern
        }

    def _get_market_regime(self, date: datetime) -> Dict:
        """Deterministically select market regime based on date"""
        date_hash = hash(date.strftime('%Y%m%d')) % 100
        
        if date_hash < 60:
            return self.regimes['normal']
        elif date_hash < 80:
            return self.regimes['volatile']
        elif date_hash < 90:
            return self.regimes['trending']
        else:
            return self.regimes['quiet']

    def _generate_garch_returns(self, n_periods: int, base_vol: float, seed: int) -> np.ndarray:
        """Generate returns using GARCH(1,1) for realistic volatility clustering"""
        np.random.seed(seed)
        
        # GARCH parameters
        omega = 0.000001
        alpha = 0.06
        beta = 0.92
        
        returns = np.zeros(n_periods)
        vol = np.zeros(n_periods)
        vol[0] = base_vol
        
        for t in range(1, n_periods):
            returns[t-1] = np.random.normal(0, vol[t-1])
            vol[t] = np.sqrt(omega + alpha * returns[t-1]**2 + beta * vol[t-1]**2)
        
        returns[-1] = np.random.normal(0, vol[-1])
        return returns

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
        """Always returns True for mock provider"""
        return True

    async def get_spx_data(self, date: datetime, granularity: str = "minute") -> pd.DataFrame:
        """Generate highly realistic SPX price data with market microstructure"""
        # Use cache for consistency
        #cache_key = f"spx_{date.strftime('%Y%m%d')}_{granularity}"
        #cached_data = self._load_from_cache(cache_key)
        #if cached_data is not None:
            #return cached_data

        # Ensure reproducible results
        seed = int(date.strftime('%Y%m%d'))
        np.random.seed(seed)
        
        # Get market regime
        regime = self._get_market_regime(date)
        
        # Set up trading times
        freq_map = {
            "tick": "1s",
            "minute": "1min",
            "1min": "1min", 
            "5min": "5min",
            "5minute": "5min"
        }
        freq = freq_map.get(granularity, "1min")
        
        if isinstance(date, datetime):
            dt = date
        else:
            dt = datetime.combine(date, datetime.min.time())
            
        market_open = pd.Timestamp(dt.replace(hour=9, minute=30))
        market_close = pd.Timestamp(dt.replace(hour=16, minute=0))
        times = pd.date_range(market_open, market_close, freq=freq)
        n_periods = len(times)
        
        # Calculate base price with potential overnight gap
        gap = 0
        if date.weekday() == 0 or np.random.random() < 0.3:  # Monday or 30% chance
            gap = np.random.normal(0, 10) * regime['vol'] / 0.012
        
        base_price = self.spx_base_price + gap
        
        # Generate returns with GARCH volatility
        returns = self._generate_garch_returns(n_periods, regime['vol'], seed)
        
        # Add trend
        returns += regime['trend']
        
        # Apply intraday volatility pattern
        minutes_from_open = ((times - market_open).total_seconds() / 60).astype(int)
        minutes_from_open = np.clip(minutes_from_open, 0, 389)
        vol_adjustment = self.intraday_patterns['volatility'][minutes_from_open]
        returns = returns * vol_adjustment
        
        # Calculate prices
        cum_returns = np.cumsum(returns)
        prices = base_price * np.exp(cum_returns)
        
        # Add microstructure noise for tick data
        if granularity == "tick":
            tick_noise = np.random.normal(0, 0.02, n_periods)
            prices += tick_noise
        
        # Generate realistic OHLC
        if granularity == "tick":
            # For ticks, minimal OHLC variation
            df = pd.DataFrame({
                'timestamp': times,
                'open': prices,
                'high': prices + np.abs(np.random.normal(0, 0.05, n_periods)),
                'low': prices - np.abs(np.random.normal(0, 0.05, n_periods)),
                'close': prices,
                'volume': np.random.poisson(100, n_periods)
            })
        else:
            # For bars, realistic OHLC relationships
            # High/Low based on realized volatility within bar
            bar_vol = np.abs(returns) * np.sqrt(n_periods / 78)  # Scale by bar size
            high_offset = np.abs(np.random.normal(0.5, 0.25, n_periods)) * bar_vol * prices
            low_offset = np.abs(np.random.normal(0.5, 0.25, n_periods)) * bar_vol * prices
            
            # Open with small gap from previous close
            open_prices = np.zeros(n_periods)
            open_prices[0] = prices[0] + np.random.normal(0, 0.1)
            for i in range(1, n_periods):
                open_prices[i] = prices[i-1] + np.random.normal(0, 0.05)
            
            # Close with random walk within range
            close_prices = prices + np.random.normal(0, bar_vol * prices * 0.3)
            
            # Volume with intraday pattern
            volume_pattern = self.intraday_patterns['volume'][minutes_from_open]
            base_volume = 1000000 / 78 if freq == "5T" else 1000000 / 390
            volumes = np.random.gamma(2, base_volume/2, n_periods) * volume_pattern * regime['vol_mult']
            
            # Add volume spikes (news events)
            n_spikes = np.random.poisson(2)
            if n_spikes > 0:
                spike_times = np.random.choice(n_periods, min(n_spikes, n_periods), replace=False)
                volumes[spike_times] *= np.random.uniform(2, 4, len(spike_times))
            
            df = pd.DataFrame({
                'timestamp': times,
                'open': open_prices,
                'high': prices + high_offset,
                'low': prices - low_offset,
                'close': close_prices,
                'volume': volumes.astype(int)
            })
        
        # Ensure OHLC constraints
        df['high'] = df[['open', 'high', 'close']].max(axis=1)
        df['low'] = df[['open', 'low', 'close']].min(axis=1)
        
        #self._save_to_cache(cache_key, df)
        return df

    async def get_spy_volume_data(self, date: datetime, granularity: str = "5min") -> pd.DataFrame:
        """Generate realistic SPY volume data correlated with market conditions"""
        # Default to 5min for SPY volume
        if granularity not in ["5min", "5minute"]:
            granularity = "5min"
            
        #cache_key = f"spy_{date.strftime('%Y%m%d')}_{granularity}"
        #cached_data = self._load_from_cache(cache_key)
        #if cached_data is not None:
            #return cached_data

        seed = int(date.strftime('%Y%m%d')) + 1000
        np.random.seed(seed)
        
        regime = self._get_market_regime(date)
        
        # Set up times
        freq_map = {"5min": "5T", "5minute": "5T", "minute": "1T", "1min": "1T"}
        freq = freq_map.get(granularity, "5T")
        
        if isinstance(date, datetime):
            dt = date
        else:
            dt = datetime.combine(date, datetime.min.time())
            
        market_open = pd.Timestamp(dt.replace(hour=9, minute=30))
        market_close = pd.Timestamp(dt.replace(hour=16, minute=0))
        times = pd.date_range(market_open, market_close, freq=freq)
        n_periods = len(times)
        
        # Minutes from open for pattern
        if freq == "5T":
            minutes_from_open = np.arange(0, 390, 5)[:n_periods]
        else:
            minutes_from_open = np.arange(0, 390)[:n_periods]
        
        
        # Apply volume pattern
        # This block ensures your volume_pattern matches your bar count!

        pattern = self.intraday_patterns['volume']

        if len(pattern) != n_periods:
        # Resample the pattern to n_periods
        # Downsample: average in bins
           if n_periods < len(pattern):
               pattern = pattern[:n_periods*int(len(pattern)/n_periods)]
               pattern = pattern.reshape((n_periods, -1)).mean(axis=1)
        # Upsample: repeat values or interpolate
           else:
               pattern = np.interp(
            np.linspace(0, len(pattern)-1, n_periods),
            np.arange(len(pattern)),
            pattern
        )
           
        volume_pattern = pattern

        #volume_pattern = self.intraday_patterns['volume'][minutes_from_open]
        
        # Base volume calculation
        base_volume = self.spy_base_volume / n_periods
        
        # Generate volumes with gamma distribution
        shape = 3.0  # More realistic distribution
        scale = base_volume / shape
        volumes = np.random.gamma(shape, scale, n_periods)
        
        # Apply patterns and regime
        volumes = volumes * volume_pattern * regime['vol_mult']
        
        # Ensure first bar has high volume
        volumes[0] *= np.random.uniform(2.5, 4.0)
        
        # Add correlation with volatility
        vol_correlation = 1 + 0.5 * (regime['vol'] - 0.012) / 0.012
        volumes = volumes * vol_correlation
        
        # Random volume spikes
        n_spikes = np.random.poisson(3)
        if n_spikes > 0:
            spike_indices = np.random.choice(range(1, n_periods-1), 
                                           min(n_spikes, n_periods-2), replace=False)
            volumes[spike_indices] *= np.random.uniform(1.5, 3.0, len(spike_indices))
        
        df = pd.DataFrame({
            'timestamp': times,
            'volume': volumes.astype(int)
        })
        
        #self._save_to_cache(cache_key, df)
        return df

    async def get_option_chain(self, date: datetime, expiration: datetime, 
                              underlying: str = "SPX", granularity: str = "minute") -> pd.DataFrame:
        """Generate highly realistic option chain with proper Greeks and market microstructure"""
        #cache_key = f"options_{date.strftime('%Y%m%d')}_{expiration.strftime('%Y%m%d')}"
        #cached_data = self._load_from_cache(cache_key)
        #if cached_data is not None:
            #return cached_data

        # Get underlying price at typical entry time (10 AM)
        spx_df = await self.get_spx_data(date, "minute")
        if spx_df.empty:
            return pd.DataFrame()
            
        # Find price at 10 AM
        if isinstance(date, datetime):
            dt = date
        else:
            dt = datetime.combine(date, datetime.min.time())
        entry_time = pd.Timestamp(dt.replace(hour=10, minute=0))
        mask = spx_df['timestamp'] <= entry_time
        if mask.any():
            underlying_price = spx_df.loc[mask, 'close'].iloc[-1]
        else:
            underlying_price = spx_df.iloc[0]['close']
        
        # Time to expiration calculation
        current_time = datetime.combine(date, time(10, 0))
        expiry_time = datetime.combine(expiration, time(16, 0))
        hours_to_expiry = max((expiry_time - current_time).total_seconds() / 3600, 0.1)
        dte = hours_to_expiry / 24
        time_to_expiry_years = hours_to_expiry / (252 * 6.5)
        
        # Market parameters
        r = 0.0525  # Current risk-free rate
        regime = self._get_market_regime(date)
        
        # Generate realistic strike range
        atm_strike = round(underlying_price / 5) * 5
        strikes = []
        
        # Dense strikes near ATM
        for i in range(-10, 11):
            strikes.append(atm_strike + i * 5)
        
        # Wider strikes further out
        for i in range(11, 21):
            strikes.append(atm_strike + i * 10)
            strikes.append(atm_strike - i * 10)
            
        # Far OTM strikes
        for i in range(3, 8):
            strikes.append(atm_strike + 200 + i * 25)
            strikes.append(atm_strike - 200 - i * 25)
        
        strikes = sorted([s for s in set(strikes) if s > 0])
        
        options = []
        
        for strike in strikes:
            moneyness = strike / underlying_price
            
            for cp in ['C', 'P']:
                # Calculate IV with realistic smile
                base_iv = 0.15 * regime['vol'] / 0.012  # Scale with regime
                
                # Term structure: higher IV for shorter dated options
                term_mult = 1 + 0.5 * np.exp(-dte)
                
                # Volatility smile/skew
                if cp == 'P' and moneyness < 1.0:  # OTM puts
                    skew = 0.15 * (1 - moneyness) ** 0.5
                elif cp == 'C' and moneyness > 1.0:  # OTM calls
                    skew = 0.08 * (moneyness - 1) ** 0.6
                else:
                    skew = 0
                
                iv = base_iv * term_mult * (1 + skew) + np.random.normal(0, 0.005)
                iv = np.clip(iv, 0.05, 0.80)
                
                # Black-Scholes pricing
                S = underlying_price
                K = strike
                T = time_to_expiry_years
                
                if T <= 0:
                    # At expiration
                    if cp == 'C':
                        price = max(0, S - K)
                    else:
                        price = max(0, K - S)
                else:
                    d1 = (np.log(S/K) + (r + 0.5*iv**2)*T) / (iv*np.sqrt(T))
                    d2 = d1 - iv*np.sqrt(T)
                    
                    if cp == 'C':
                        price = S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
                    else:
                        price = K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)
                
                price = max(price, 0.01)
                
                # Calculate realistic bid-ask spreads
                base_spread = 0.05  # 5 cents minimum
                
                # Wider spreads for OTM options
                otm_adjustment = 1 + 2 * abs(1 - moneyness)
                
                # Wider spreads for low priced options
                price_adjustment = 1 + 0.5 * np.exp(-price)
                
                # Time decay effect on spreads
                time_adjustment = 1 + np.exp(-dte)
                
                spread = base_spread * otm_adjustment * price_adjustment * time_adjustment
                spread = min(spread, price * 0.5)  # Cap at 50% of price
                
                bid = max(0.01, round(price - spread/2, 2))
                ask = round(price + spread/2, 2)
                last = round(np.random.uniform(bid, ask), 2)
                
                # Volume decreases with distance from ATM
                distance_from_atm = abs(strike - atm_strike) / atm_strike
                base_volume = 1000 * np.exp(-distance_from_atm * 10)
                volume = int(np.random.poisson(max(1, base_volume)))
                
                # Greeks
                if T > 0:
                    # Delta
                    if cp == 'C':
                        delta = norm.cdf(d1)
                    else:
                        delta = norm.cdf(d1) - 1
                    
                    # Gamma
                    gamma = norm.pdf(d1) / (S * iv * np.sqrt(T))
                    
                    # Theta (per day)
                    term1 = -S * norm.pdf(d1) * iv / (2 * np.sqrt(T))
                    if cp == 'C':
                        term2 = -r * K * np.exp(-r*T) * norm.cdf(d2)
                    else:
                        term2 = r * K * np.exp(-r*T) * norm.cdf(-d2)
                    theta = (term1 + term2) / 252
                    
                    # Vega
                    vega = S * norm.pdf(d1) * np.sqrt(T) / 100
                else:
                    delta = 1.0 if (cp == 'C' and S > K) else 0.0
                    gamma = 0.0
                    theta = 0.0
                    vega = 0.0
                
                options.append({
                    'contract': f"O:SPXW{expiration.strftime('%y%m%d')}{cp}{strike:08d}",
                    'timestamp': pd.Timestamp(current_time),
                    'strike': strike,
                    'type': cp,
                    'bid': bid,
                    'ask': ask,
                    'last': last,
                    'volume': volume,
                    'open_interest': int(volume * np.random.uniform(10, 50)),
                    'iv': round(iv, 4),
                    'delta': round(delta, 4),
                    'gamma': round(gamma, 6),
                    'theta': round(theta, 2),
                    'vega': round(vega, 2)
                })

        df = pd.DataFrame(options)
        #self._save_to_cache(cache_key, df)
        return df

    async def get_option_quotes(self, contracts: List[str], timestamp: datetime) -> Dict[str, Dict]:
        """Generate real-time option quotes with intraday price movement"""
        results = {}
        
        # Use timestamp for consistent randomness
        seed = hash(timestamp.strftime('%Y%m%d%H%M')) % 2**32
        np.random.seed(seed)
        
        for contract in contracts:
            try:
                # Parse contract: O:SPXWYYMMDDCXXXXXXXX or O:SPXWYYMMDDPXXXXXXXX
                if ':' in contract:
                    parts = contract.split(':')[-1]
                else:
                    parts = contract
                
                # Extract components
                if parts.startswith('SPXW'):
                    expiry_str = parts[4:10]
                    cp = parts[10]
                    strike = int(parts[11:]) / 1000
                else:
                    # Handle alternative format
                    raise ValueError("Unknown contract format")
                
                # Get current underlying price
                date = timestamp.date()
                spx_data = await self.get_spx_data(date, "minute")
                
                if not spx_data.empty:
                    # Find price at timestamp
                    mask = spx_data['timestamp'] <= timestamp
                    if mask.any():
                        underlying_price = spx_data.loc[mask, 'close'].iloc[-1]
                    else:
                        underlying_price = spx_data.iloc[0]['close']
                    
                    # Time calculations
                    expiry_date = datetime.strptime(expiry_str, '%y%m%d')
                    expiry_time = datetime.combine(expiry_date, time(16, 0))
                    hours_to_expiry = max((expiry_time - timestamp).total_seconds() / 3600, 0.1)
                    T = hours_to_expiry / (252 * 6.5)
                    
                    # Get regime
                    regime = self._get_market_regime(date)
                    
                    # Calculate theoretical value and Greeks
                    r = 0.0525
                    moneyness = strike / underlying_price
                    
                    # IV with intraday adjustment
                    base_iv = 0.15 * regime['vol'] / 0.012
                    if cp == 'P' and moneyness < 1.0:
                        skew = 0.15 * (1 - moneyness) ** 0.5
                    elif cp == 'C' and moneyness > 1.0:
                        skew = 0.08 * (moneyness - 1) ** 0.6
                    else:
                        skew = 0
                    
                    # Add intraday volatility changes
                    minutes_since_open = (timestamp.hour - 9) * 60 + timestamp.minute - 30
                    intraday_vol_adj = 1 + 0.1 * np.sin(2 * np.pi * minutes_since_open / 390)
                    
                    iv = base_iv * (1 + skew) * intraday_vol_adj
                    iv = np.clip(iv, 0.05, 0.80)
                    
                    # Price option
                    if T <= 0:
                        if cp == 'C':
                            price = max(0, underlying_price - strike)
                        else:
                            price = max(0, strike - underlying_price)
                    else:
                        d1 = (np.log(underlying_price/strike) + (r + 0.5*iv**2)*T) / (iv*np.sqrt(T))
                        d2 = d1 - iv*np.sqrt(T)
                        
                        if cp == 'C':
                            price = underlying_price*norm.cdf(d1) - strike*np.exp(-r*T)*norm.cdf(d2)
                        else:
                            price = strike*np.exp(-r*T)*norm.cdf(-d2) - underlying_price*norm.cdf(-d1)
                    
                    price = max(price, 0.01)
                    
                    # Dynamic spread calculation
                    base_spread = 0.05
                    otm_factor = 1 + 3 * abs(1 - moneyness)
                    time_factor = 1 + 2 * np.exp(-hours_to_expiry/6.5)
                    spread = min(base_spread * otm_factor * time_factor, price * 0.5)
                    
                    # Add some randomness to simulate market makers
                    spread_noise = np.random.uniform(0.8, 1.2)
                    spread *= spread_noise
                    
                    bid = max(0.01, round(price - spread/2, 2))
                    ask = round(price + spread/2, 2)
                    last = round(np.random.uniform(bid, ask), 2)
                    
                    # Volume based on moneyness and time
                    distance_from_atm = abs(strike - underlying_price) / underlying_price
                    base_volume = 500 * np.exp(-distance_from_atm * 10) * np.exp(-hours_to_expiry/24)
                    volume = int(np.random.poisson(max(1, base_volume)))
                    
                    results[contract] = {
                        "bid": bid,
                        "ask": ask,
                        "last": last,
                        "iv": round(iv, 4),
                        "volume": volume
                    }
                else:
                    # No data available
                    results[contract] = {"bid": 0, "ask": 0, "last": 0, "iv": 0, "volume": 0}
                    
            except Exception as e:
                logger.error(f"Error parsing contract {contract}: {e}")
                results[contract] = {"bid": 0, "ask": 0, "last": 0, "iv": 0, "volume": 0}
        
        return results