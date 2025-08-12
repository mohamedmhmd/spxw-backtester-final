from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
import logging

import pandas as pd

from config.back_test_config import BacktestConfig
#Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    

    async def _close_trade_at_expiry(self, ohlc_data : pd.DataFrame, date: datetime, 
                                   config: BacktestConfig):
        """Close trade at market close using settlement prices"""
        # Get SPX close price
        if ohlc_data.empty:
            logger.error(f"No SPX data for settlement on {date}")
            return
        
        # Use official close price
        settlement_price = ohlc_data.iloc[-1]['close']*10
        if isinstance(date, datetime):
            dt = date
        else:
            dt = datetime.combine(date, datetime.min.time())
        exit_time = dt.replace(hour=16, minute=0, second=0)
        
        # Calculate settlement values for each option

        payoffs = {}
        
        for contract, details in self.contracts.items():
            leg_type = details['leg_type']
            
            # Extract strike from contract symbol
            strike_str = contract[-8:]
            strike = int(strike_str)/1000
            
            # Calculate intrinsic value at expiration
            if 'call' in leg_type:
                value = max(0, settlement_price - strike)
            else:  # put
                value = max(0, strike - settlement_price)
            
            payoffs[contract] = value
        
        self.calculate_pnl(payoffs, config.commission_per_contract)
        
        self.exit_time = exit_time
        self.status = "CLOSED"
        self.exit_signals = {'settlement_price': settlement_price}
        
        logger.info(f"Closed {self.trade_type} at settlement: SPX=${settlement_price:.2f}, P&L=${self.pnl:.2f}")
    

    
