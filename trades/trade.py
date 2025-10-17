from ctypes import Union
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
import logging

import pandas as pd

from config.back_test_config import BacktestConfig
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
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
    exit_signals: Optional[Dict[str, Any]] = None
    pnl: float = 0.0
    unit_pnl: float = 0.0
    pnl_without_commission: float = 0.0
    unit_pnl_without_commission: float = 0.0
    status: str = "OPEN"  # OPEN, CLOSED
    metadata: Optional[Dict[str, Any]] = None
    used_capital: float = 0.0  # ADD THIS LINE
    unit_used_capital: float = 0.0  # Capital used per unit size
    exit_percentage: float = 0.0 # For partial exits
    
    
    
    def calculate_unit_used_capital(self) -> float:
        self.unit_used_capital = 0.0
        for contract, details in self.contracts.items():
            self.unit_used_capital += details['used_capital']
        return self.unit_used_capital
    
    def calculate_used_capital(self) -> float:
        self.used_capital = self.size*self.unit_used_capital
        return self.used_capital
    
    def calculate_option_pnl(self, contract, details, payoffs: Dict[str, float]) -> float:
        entry_price = details['entry_price']
        payoff = payoffs.get(contract)
        exit_factor = 1 - self.exit_percentage if details.get("exited", False) else 1
        if "long" in details['leg_type']:
            pnl = (payoff - entry_price) *100*exit_factor
        else:  # short
            pnl = (entry_price - payoff) *100*exit_factor
        details['exit_price'] = payoff
        return pnl
    
    def calculate_option_commission(self, contract, details, payoffs: Dict[str, float], commission_per_contract: float) -> float:
        exit_factor = 1 - self.exit_percentage if details.get("exited", False) else 1
        return commission_per_contract*exit_factor if payoffs.get(contract) <= 0 else 2*commission_per_contract*exit_factor
        
    def calculate_unit_pnl(self, payoffs: Dict[str, float], commission_per_contract) -> float:
        self.unit_pnl = 0.0
        for contract, details in self.contracts.items():
            pnl = self.calculate_option_pnl(contract, details, payoffs) - self.calculate_option_commission(contract, details, payoffs, commission_per_contract)
            details['pnl'] = pnl
            self.contracts[contract] = details
            self.unit_pnl += pnl
            
    def calculate_unit_pnl_without_commission(self, payoffs: Dict[str, float]) -> float:
        self.unit_pnl_without_commission = 0.0
        for contract, details in self.contracts.items():
            pnl = self.calculate_option_pnl(contract, details, payoffs)
            details['pnl_without_commission'] = pnl
            self.contracts[contract] = details
            self.unit_pnl_without_commission += pnl
        return self.unit_pnl_without_commission
            
            
    
    def calculate_pnl(self, size : int ) -> float:
        """Calculate P&L for the trade"""
        self.pnl = self.metadata.get('partial_pnl', 0.0)* size  +  size * self.unit_pnl
        self.size = size
        return self.pnl
    
    def calculate_pnl_without_commission(self, size : int ) -> float:
        """Calculate P&L for the trade without commission"""
        self.pnl_without_commission = self.metadata.get('partial_pnl_without_commission', 0.0)* size  +  size * self.unit_pnl_without_commission
        self.size = size
        return self.pnl_without_commission
    

    async def _close_trade_at_expiry(self, ohlc_data : pd.DataFrame, date: datetime, 
                                   config: BacktestConfig, data_provider = None, timestamp: datetime = None):
        """Close trade at market close using settlement prices"""
        # Get SPX close price
        if ohlc_data.empty:
            logger.error(f"No SPX data for settlement on {date}")
            return
        
        # Use official close price
        settlement_price = ohlc_data.iloc[-1]['close']
        self.metadata['exit_spx_price'] = settlement_price
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
                if "Long Strangle 2" in self.trade_type:
                    quote = await data_provider._get_option_tick_quote(contract, timestamp)
                    value = quote.get('ask', 0) if quote is not None else value
                if 'short' in leg_type and value > 0:
                   # add cash required to settle short calls
                   details["used_capital"] += value * 100 + config.commission_per_contract
                elif value > 0:
                     exit_factor = 1 - self.exit_percentage if details.get("exited", False) else 1
                     details["used_capital"] += config.commission_per_contract* exit_factor
            else:  # put
                value = max(0, strike - settlement_price)
                if "Long Strangle 2" in self.trade_type:
                    quote = await data_provider._get_option_tick_quote(contract, timestamp)
                    value = quote.get('ask', 0) if quote is not None else value
                if 'short' in leg_type and value > 0:
                   # add cash required to settle short puts
                   details["used_capital"] += value* 100 + config.commission_per_contract
                elif value > 0:
                     exit_factor = 1 - self.exit_percentage if details.get("exited", False) else 1
                     details["used_capital"] += config.commission_per_contract*exit_factor
            self.contracts[contract] = details
                    
            payoffs[contract] = value
        
        self.calculate_unit_pnl(payoffs, config.commission_per_contract)
        self.calculate_pnl(self.size)
        self.calculate_unit_pnl_without_commission(payoffs)
        self.calculate_pnl_without_commission(self.size)
        self.calculate_unit_used_capital()
        self.calculate_used_capital()
        
        self.exit_time = exit_time
        self.status = "CLOSED"
        self.exit_signals = {'settlement_price': settlement_price}
        
        logger.info(f"Closed {self.trade_type} at settlement: SPX=${settlement_price:.2f}, P&L=${self.pnl:.2f}")
    

    
