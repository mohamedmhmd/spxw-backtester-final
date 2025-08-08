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
    metadata: Optional[Dict[str, Any]] = None
    
    def calculate_pnl(self, payoffs: Dict[str, float], commission_per_contract: float):
        """Calculate P&L for the trade"""
        total_pnl = self.metadata.get('partial_pnl', 0.0)
        total_commissions = 0.0
        
        for contract, details in self.contracts.items():
            remaining = details.get('remaining_position', details['position'])
            entry_price = details['entry_price']
            payoff = payoffs.get(contract)
            
            # Calculate raw P&L
            if remaining > 0:  # Long
                pnl = (payoff - entry_price) * remaining  # SPX multiplier is 100
            else:  # Short
                pnl = (entry_price - payoff) * abs(remaining)
            
            total_pnl += pnl
            total_commissions += abs(remaining) * commission_per_contract * 2  # Entry and exit
            
            # Update exit price
            details['exit_price'] = payoff
        
        self.pnl = total_pnl - total_commissions
        return self.pnl