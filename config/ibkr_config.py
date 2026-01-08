"""
IBKR Connection Configuration

Configuration settings for Interactive Brokers TWS/Gateway connection.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class IBKRConnectionMode(Enum):
    """Connection mode for IBKR"""
    PAPER = "paper"
    LIVE = "live"


@dataclass
class IBKRConfig:
    """
    IBKR connection configuration.
    
    Port mapping:
    - TWS Paper Trading: 7497
    - TWS Live Trading: 7496
    - IB Gateway Paper: 4002
    - IB Gateway Live: 4001
    
    Attributes:
        host: IP address of TWS/Gateway (usually localhost)
        port: Port number based on paper/live mode
        client_id: Unique client identifier (use different IDs for different apps)
        readonly: If True, cannot place orders (extra safety during development)
        account: Account ID (populated after connection)
        timeout: Connection timeout in seconds
        mode: Paper or Live trading mode
    """
    host: str = "127.0.0.1"
    port: int = 7497  # Default to paper trading
    client_id: int = 1
    readonly: bool = False
    account: str = ""
    timeout: int = 30
    mode: IBKRConnectionMode = IBKRConnectionMode.PAPER
    
    # Auto-reconnect settings
    auto_reconnect: bool = True
    reconnect_delay: int = 5  # seconds
    max_reconnect_attempts: int = 5
    
    @classmethod
    def paper_trading(cls, client_id: int = 1) -> 'IBKRConfig':
        """Create config for paper trading via TWS"""
        return cls(
            host="127.0.0.1",
            port=7497,
            client_id=client_id,
            readonly=False,
            mode=IBKRConnectionMode.PAPER
        )
    
    @classmethod
    def paper_gateway(cls, client_id: int = 1) -> 'IBKRConfig':
        """Create config for paper trading via IB Gateway"""
        return cls(
            host="127.0.0.1",
            port=4002,
            client_id=client_id,
            readonly=False,
            mode=IBKRConnectionMode.PAPER
        )
    
    @classmethod
    def live_trading(cls, client_id: int = 1) -> 'IBKRConfig':
        """
        Create config for LIVE trading via TWS.
        
        ⚠️ WARNING: This connects to LIVE trading!
        Real money will be at risk!
        """
        return cls(
            host="127.0.0.1",
            port=7496,
            client_id=client_id,
            readonly=False,
            mode=IBKRConnectionMode.LIVE
        )
    
    @classmethod
    def live_gateway(cls, client_id: int = 1) -> 'IBKRConfig':
        """
        Create config for LIVE trading via IB Gateway.
        
        ⚠️ WARNING: This connects to LIVE trading!
        Real money will be at risk!
        """
        return cls(
            host="127.0.0.1",
            port=4001,
            client_id=client_id,
            readonly=False,
            mode=IBKRConnectionMode.LIVE
        )
    
    @classmethod
    def readonly_observer(cls, client_id: int = 99) -> 'IBKRConfig':
        """Create readonly config for monitoring only (no order capability)"""
        return cls(
            host="127.0.0.1",
            port=7497,
            client_id=client_id,
            readonly=True,
            mode=IBKRConnectionMode.PAPER
        )
    
    def is_paper(self) -> bool:
        """Check if this is paper trading mode"""
        return self.mode == IBKRConnectionMode.PAPER
    
    def is_live(self) -> bool:
        """Check if this is live trading mode"""
        return self.mode == IBKRConnectionMode.LIVE
    
    def get_display_mode(self) -> str:
        """Get human-readable mode string"""
        if self.readonly:
            return "READ-ONLY"
        return "PAPER" if self.is_paper() else "🔴 LIVE"
    
    def validate(self) -> tuple[bool, str]:
        """
        Validate configuration settings.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.host:
            return False, "Host cannot be empty"
        
        if not (1 <= self.port <= 65535):
            return False, f"Invalid port: {self.port}"
        
        if self.client_id < 0:
            return False, f"Client ID must be non-negative: {self.client_id}"
        
        if self.timeout < 1:
            return False, f"Timeout must be at least 1 second: {self.timeout}"
        
        # Warn about suspicious port/mode combinations
        paper_ports = {7497, 4002}
        live_ports = {7496, 4001}
        
        if self.is_paper() and self.port in live_ports:
            return False, f"Paper mode selected but using live port {self.port}"
        
        if self.is_live() and self.port in paper_ports:
            return False, f"Live mode selected but using paper port {self.port}"
        
        return True, ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            'host': self.host,
            'port': self.port,
            'client_id': self.client_id,
            'readonly': self.readonly,
            'account': self.account,
            'timeout': self.timeout,
            'mode': self.mode.value,
            'auto_reconnect': self.auto_reconnect,
            'reconnect_delay': self.reconnect_delay,
            'max_reconnect_attempts': self.max_reconnect_attempts,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'IBKRConfig':
        """Create from dictionary"""
        mode = data.get('mode', 'paper')
        if isinstance(mode, str):
            mode = IBKRConnectionMode(mode)
        
        return cls(
            host=data.get('host', '127.0.0.1'),
            port=data.get('port', 7497),
            client_id=data.get('client_id', 1),
            readonly=data.get('readonly', False),
            account=data.get('account', ''),
            timeout=data.get('timeout', 30),
            mode=mode,
            auto_reconnect=data.get('auto_reconnect', True),
            reconnect_delay=data.get('reconnect_delay', 5),
            max_reconnect_attempts=data.get('max_reconnect_attempts', 5),
        )
