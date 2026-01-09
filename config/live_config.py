from dataclasses import dataclass, field
from datetime import time

@dataclass
class PolygonLiveConfig:
    """Configuration for Polygon live data"""
    api_key: str = ""  # Must be set
    
    # WebSocket settings
    reconnect_attempts: int = 5
    reconnect_delay_seconds: int = 5
    heartbeat_interval_seconds: int = 30
    
    # Bar aggregation
    bar_size_minutes: int = 5
    
    # Buffer sizes
    max_bars_per_symbol: int = 500  # ~8 hours of 5-min bars