from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class Trade:
    """Represents a single trade"""
    entry_time: datetime
    exit_time: Optional[datetime]
    trade_type: str
    contracts: Dict[str, Dict]  # contract -> {position, entry_price, exit_price}
    size: int
    entry_signals: Dict[str, Any]
    exit_signals: Optional[Dict[str, Any]] = None
    pnl: float = 0.0
    status: str = "OPEN"  # OPEN, CLOSED
    
    def calculate_pnl(self, exit_prices: Dict[str, float], commission_per_contract: float):
        """Calculate P&L for the trade"""
        total_pnl = 0.0
        total_commissions = 0.0
        
        for contract, details in self.contracts.items():
            position = details['position']
            entry_price = details['entry_price']
            exit_price = exit_prices.get(contract, details.get('exit_price', 0))
            
            # Calculate raw P&L
            if position > 0:  # Long
                pnl = (exit_price - entry_price) * position * 100  # SPX multiplier is 100
            else:  # Short
                pnl = (entry_price - exit_price) * abs(position) * 100
            
            total_pnl += pnl
            total_commissions += abs(position) * commission_per_contract * 2  # Entry and exit
            
            # Update exit price
            details['exit_price'] = exit_price
        
        self.pnl = total_pnl - total_commissions
        return self.pnl