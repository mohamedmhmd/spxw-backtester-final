"""
Live Trade Constructor - Builds trades for live execution via IBKR.

This adapts your existing Iron Condor backtesting logic for live trading.
Key features:
- Uses IBKR real-time quotes instead of historical data
- Smart wing optimization (finds better pricing at closer strikes)
- Proper combo order construction for IBKR
- Validates liquidity before trading

Based on your IronCondorBase logic from iron_condor_base.py
"""

import logging
import asyncio
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

logger = logging.getLogger(__name__)

# Check for ib_insync
try:
    from ib_insync import Option, Contract, Order, ComboLeg, LimitOrder
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    logger.warning("ib_insync not available")


class TradeType(Enum):
    """Types of trades we can construct"""
    IRON_CONDOR_1 = "Iron Condor 1"
    IRON_CONDOR_2 = "Iron Condor 2"
    IRON_CONDOR_3A = "Iron Condor 3(a)"
    IRON_CONDOR_3B = "Iron Condor 3(b)"


@dataclass
class OptionLeg:
    """Represents one leg of an options trade"""
    strike: float
    right: str  # 'C' or 'P'
    action: str  # 'BUY' or 'SELL'
    quantity: int
    bid: float = 0.0
    ask: float = 0.0
    contract: Optional[Any] = None  # IBKR Option contract
    
    @property
    def mid(self) -> float:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return 0.0
    
    @property
    def spread(self) -> float:
        if self.bid and self.ask:
            return self.ask - self.bid
        return 0.0
    
    @property
    def spread_pct(self) -> float:
        if self.mid > 0:
            return self.spread / self.mid
        return 1.0


@dataclass
class IronCondorConstruction:
    """A fully constructed Iron Condor ready for execution"""
    trade_type: TradeType
    underlying_price: float
    
    # Strikes
    short_call_strike: float
    short_put_strike: float
    long_call_strike: float
    long_put_strike: float
    
    # Legs
    legs: List[OptionLeg] = field(default_factory=list)
    
    # Pricing
    net_premium: float = 0.0
    max_loss: float = 0.0
    max_profit: float = 0.0
    win_loss_ratio: float = 0.0
    
    # IBKR specific
    combo_contract: Optional[Any] = None
    order: Optional[Any] = None
    
    # Quantities
    quantity: int = 1
    
    @property
    def wing_width(self) -> float:
        """Width of the wings"""
        return self.short_call_strike - self.long_put_strike  # For iron butterfly
    
    @property
    def call_wing(self) -> float:
        return self.long_call_strike - self.short_call_strike
    
    @property
    def put_wing(self) -> float:
        return self.short_put_strike - self.long_put_strike
    
    @property
    def total_contracts(self) -> int:
        return self.quantity * 4  # 4 legs per iron condor
    
    @property
    def representation(self) -> str:
        return (f"{self.long_put_strike}/{self.short_put_strike} "
                f"{self.short_call_strike}/{self.long_call_strike} "
                f"({self.put_wing})")
    
    def to_dict(self) -> dict:
        return {
            'trade_type': self.trade_type.value,
            'underlying_price': self.underlying_price,
            'short_call': self.short_call_strike,
            'short_put': self.short_put_strike,
            'long_call': self.long_call_strike,
            'long_put': self.long_put_strike,
            'net_premium': self.net_premium,
            'max_loss': self.max_loss,
            'max_profit': self.max_profit,
            'ratio': self.win_loss_ratio,
            'quantity': self.quantity,
            'representation': self.representation,
        }


class LiveTradeConstructor:
    """
    Constructs optimal trades based on live IBKR market data.
    
    Key feature: Optimizes wing selection based on actual bid/ask prices.
    If a closer strike offers similar or better pricing, we use it.
    
    This implements the logic from your IronCondorBase.find_iron_condor_strikes()
    adapted for live IBKR data.
    """
    
    def __init__(self, ibkr_connection):
        """
        Initialize constructor.
        
        Args:
            ibkr_connection: IBKRConnection instance
        """
        self.ibkr = ibkr_connection
        self._quote_cache: Dict[str, Dict] = {}
    
    async def construct_iron_condor(
        self,
        underlying_price: float,
        expiry: str,
        target_win_loss_ratio: float,
        quantity: int,
        trade_type: TradeType = TradeType.IRON_CONDOR_1,
        min_wing_width: int = 15,
        max_wing_width: int = 70,
        optimize_wings: bool = True,
        tolerance: float = 0.03
    ) -> Optional[IronCondorConstruction]:
        """
        Construct an Iron Butterfly/Condor trade.
        
        This mirrors your IronCondorBase.find_iron_condor_strikes() logic
        but uses live IBKR quotes.
        
        Iron Butterfly structure (ATM short strikes):
        - Sell 1 ATM Call
        - Sell 1 ATM Put  
        - Buy 1 OTM Call (wing)
        - Buy 1 OTM Put (wing)
        
        Args:
            underlying_price: Current SPX price
            expiry: Expiration date (YYYYMMDD format)
            target_win_loss_ratio: Target ratio (e.g., 1.5 for 1.5:1)
            quantity: Number of contracts
            trade_type: Type of iron condor
            min_wing_width: Minimum distance to wings
            max_wing_width: Maximum distance to wings
            optimize_wings: If True, look for better pricing at closer strikes
            tolerance: Acceptable deviation from target ratio
        
        Returns:
            IronCondorConstruction if successful, None if can't find suitable strikes
        """
        if not self.ibkr or not self.ibkr.is_connected():
            logger.error("IBKR not connected")
            return None
        
        # Find ATM strike (round to nearest 5)
        atm_strike = int(round(underlying_price / 5) * 5)
        logger.info(f"ATM strike: {atm_strike}, underlying: {underlying_price}")
        
        # Use gradient descent approach to find optimal wing distance
        # (Same logic as your find_iron_condor_strikes)
        
        step = 5
        best_distance = None
        best_ratio = None
        best_premium = None
        best_diff = float('inf')
        
        # Three-point search to find optimal region quickly
        test_distances = [min_wing_width, (min_wing_width + max_wing_width) // 2, max_wing_width]
        
        for distance in test_distances:
            result = await self._get_quotes_for_distance(
                atm_strike, distance, expiry, quantity
            )
            
            if result:
                ratio, premium, quotes = result
                diff = abs(ratio - target_win_loss_ratio)
                
                if diff < best_diff:
                    best_diff = diff
                    best_distance = distance
                    best_ratio = ratio
                    best_premium = premium
        
        if best_distance is None:
            logger.error("Could not find any valid strikes")
            return None
        
        # Binary search refinement
        if best_ratio < target_win_loss_ratio:
            # Need smaller distance (higher ratio)
            left, right = min_wing_width, best_distance
        else:
            # Need larger distance (lower ratio)
            left, right = best_distance, max_wing_width
        
        while right - left > step:
            mid = ((left + right) // 2 // step) * step
            
            result = await self._get_quotes_for_distance(
                atm_strike, mid, expiry, quantity
            )
            
            if result is None:
                break
            
            ratio, premium, quotes = result
            diff = abs(ratio - target_win_loss_ratio)
            
            if diff < best_diff:
                best_diff = diff
                best_distance = mid
                best_ratio = ratio
                best_premium = premium
            
            if diff <= tolerance:
                break
            
            if ratio < target_win_loss_ratio:
                right = mid
            else:
                left = mid
        
        # Smart wing optimization
        if optimize_wings and best_distance:
            optimized = await self._optimize_wing_selection(
                atm_strike, best_distance, expiry, quantity, best_premium
            )
            if optimized:
                best_distance = optimized
        
        # Build final construction
        if best_distance:
            return await self._build_construction(
                underlying_price=underlying_price,
                atm_strike=atm_strike,
                wing_distance=best_distance,
                expiry=expiry,
                quantity=quantity,
                trade_type=trade_type
            )
        
        return None
    
    async def _get_quotes_for_distance(
        self,
        atm_strike: float,
        distance: int,
        expiry: str,
        quantity: int
    ) -> Optional[Tuple[float, float, Dict]]:
        """
        Get quotes and calculate ratio for a specific wing distance.
        
        Returns:
            Tuple of (win_loss_ratio, net_premium, quotes_dict) or None
        """
        # Create option contracts
        short_call = self._create_spx_option(atm_strike, 'C', expiry)
        short_put = self._create_spx_option(atm_strike, 'P', expiry)
        long_call = self._create_spx_option(atm_strike + distance, 'C', expiry)
        long_put = self._create_spx_option(atm_strike - distance, 'P', expiry)
        
        contracts = [short_call, short_put, long_call, long_put]
        
        # Get quotes
        quotes = await self.ibkr.get_option_quotes(contracts)
        
        if len(quotes) < 4:
            return None
        
        # Extract prices
        sc_quote = quotes.get(short_call.conId, {})
        sp_quote = quotes.get(short_put.conId, {})
        lc_quote = quotes.get(long_call.conId, {})
        lp_quote = quotes.get(long_put.conId, {})
        
        sc_bid = sc_quote.get('bid', 0)
        sp_bid = sp_quote.get('bid', 0)
        lc_ask = lc_quote.get('ask', 0)
        lp_ask = lp_quote.get('ask', 0)
        
        if not all([sc_bid, sp_bid, lc_ask, lp_ask]):
            return None
        
        # Calculate net premium (credit received)
        net_premium = sc_bid + sp_bid - lc_ask - lp_ask
        
        # Max loss = wing width - net premium
        max_loss = distance - net_premium
        
        if net_premium <= 0 or max_loss <= 0:
            return None
        
        # Win/loss ratio
        ratio = net_premium / max_loss
        
        return ratio, net_premium, {
            'short_call': sc_quote,
            'short_put': sp_quote,
            'long_call': lc_quote,
            'long_put': lp_quote,
        }
    
    async def _optimize_wing_selection(
        self,
        atm_strike: float,
        target_distance: int,
        expiry: str,
        quantity: int,
        target_premium: float
    ) -> Optional[int]:
        """
        Smart wing optimization.
        
        If a closer strike offers similar or better pricing, use it.
        This addresses your requirement: "if we can get a 30-point wing 
        for the same price as a 70-point wing, take the 30."
        
        Returns:
            Optimized distance, or None to keep original
        """
        # Check closer strikes
        for test_distance in range(30, target_distance, 5):
            result = await self._get_quotes_for_distance(
                atm_strike, test_distance, expiry, quantity
            )
            
            if result:
                ratio, premium, quotes = result
                
                # If we can get similar premium at closer strike, use it
                if premium >= target_premium * 0.95:  # Within 5%
                    logger.info(f"Wing optimization: Using {test_distance} instead of {target_distance} "
                               f"(premium ${premium:.2f} vs ${target_premium:.2f})")
                    return test_distance
        
        return None
    
    async def _build_construction(
        self,
        underlying_price: float,
        atm_strike: float,
        wing_distance: int,
        expiry: str,
        quantity: int,
        trade_type: TradeType
    ) -> Optional[IronCondorConstruction]:
        """Build the final IronCondorConstruction object"""
        
        # Get final quotes
        result = await self._get_quotes_for_distance(
            atm_strike, wing_distance, expiry, quantity
        )
        
        if not result:
            return None
        
        ratio, net_premium, quotes = result
        
        # Build legs
        legs = []
        
        # Short Call
        legs.append(OptionLeg(
            strike=atm_strike,
            right='C',
            action='SELL',
            quantity=quantity,
            bid=quotes['short_call'].get('bid', 0),
            ask=quotes['short_call'].get('ask', 0),
            contract=self._create_spx_option(atm_strike, 'C', expiry)
        ))
        
        # Short Put
        legs.append(OptionLeg(
            strike=atm_strike,
            right='P',
            action='SELL',
            quantity=quantity,
            bid=quotes['short_put'].get('bid', 0),
            ask=quotes['short_put'].get('ask', 0),
            contract=self._create_spx_option(atm_strike, 'P', expiry)
        ))
        
        # Long Call (wing)
        legs.append(OptionLeg(
            strike=atm_strike + wing_distance,
            right='C',
            action='BUY',
            quantity=quantity,
            bid=quotes['long_call'].get('bid', 0),
            ask=quotes['long_call'].get('ask', 0),
            contract=self._create_spx_option(atm_strike + wing_distance, 'C', expiry)
        ))
        
        # Long Put (wing)
        legs.append(OptionLeg(
            strike=atm_strike - wing_distance,
            right='P',
            action='BUY',
            quantity=quantity,
            bid=quotes['long_put'].get('bid', 0),
            ask=quotes['long_put'].get('ask', 0),
            contract=self._create_spx_option(atm_strike - wing_distance, 'P', expiry)
        ))
        
        # Calculate risk/reward
        max_loss = (wing_distance * 100 * quantity) - (net_premium * 100 * quantity)
        max_profit = net_premium * 100 * quantity
        
        # Build IBKR combo contract and order
        combo_contract, order = self._build_ibkr_combo(legs, net_premium, quantity)
        
        construction = IronCondorConstruction(
            trade_type=trade_type,
            underlying_price=underlying_price,
            short_call_strike=atm_strike,
            short_put_strike=atm_strike,
            long_call_strike=atm_strike + wing_distance,
            long_put_strike=atm_strike - wing_distance,
            legs=legs,
            net_premium=net_premium,
            max_loss=max_loss,
            max_profit=max_profit,
            win_loss_ratio=ratio,
            combo_contract=combo_contract,
            order=order,
            quantity=quantity
        )
        
        logger.info(f"Constructed {trade_type.value}:")
        logger.info(f"  Strikes: {construction.representation}")
        logger.info(f"  Premium: ${net_premium:.2f}")
        logger.info(f"  Max Loss: ${max_loss:.2f}")
        logger.info(f"  Ratio: {ratio:.2f}")
        
        return construction
    
    def _create_spx_option(self, strike: float, right: str, expiry: str) -> Option:
        """Create an SPX option contract"""
        return Option(
            symbol='SPX',
            lastTradeDateOrContractMonth=expiry,
            strike=float(strike),
            right=right,
            exchange='SMART',
            currency='USD',
            multiplier='100'
        )
    
    def _build_ibkr_combo(
        self,
        legs: List[OptionLeg],
        net_premium: float,
        quantity: int
    ) -> Tuple[Optional[Contract], Optional[Order]]:
        """
        Build IBKR combo contract and order.
        
        Returns:
            Tuple of (combo_contract, limit_order)
        """
        if not IB_AVAILABLE:
            return None, None
        
        # Qualify all leg contracts first
        for leg in legs:
            if leg.contract:
                self.ibkr.ib.qualifyContracts(leg.contract)
        
        # Build combo contract
        combo = Contract()
        combo.symbol = 'SPX'
        combo.secType = 'BAG'
        combo.currency = 'USD'
        combo.exchange = 'SMART'
        
        combo.comboLegs = []
        for leg in legs:
            if leg.contract and leg.contract.conId:
                combo_leg = ComboLeg()
                combo_leg.conId = leg.contract.conId
                combo_leg.ratio = 1
                combo_leg.action = leg.action
                combo_leg.exchange = 'SMART'
                combo.comboLegs.append(combo_leg)
        
        # Build limit order (negative price = credit)
        order = LimitOrder(
            action='BUY',  # "Buying" the spread (receiving credit)
            totalQuantity=quantity,
            lmtPrice=round(-net_premium, 2),  # Negative = credit
            tif='DAY'
        )
        
        return combo, order
    
    async def validate_liquidity(
        self,
        construction: IronCondorConstruction,
        max_spread_pct: float = 0.10
    ) -> Tuple[bool, str]:
        """
        Validate that the trade has acceptable liquidity.
        
        Args:
            construction: The trade to validate
            max_spread_pct: Maximum acceptable spread as percentage of mid
        
        Returns:
            Tuple of (is_valid, reason)
        """
        for leg in construction.legs:
            if leg.spread_pct > max_spread_pct:
                return False, f"Wide spread on {leg.strike}{leg.right}: {leg.spread_pct:.1%}"
            
            if leg.bid <= 0:
                return False, f"No bid on {leg.strike}{leg.right}"
        
        return True, "Liquidity OK"


def get_0dte_expiry() -> str:
    """Get today's expiration date in YYYYMMDD format"""
    return date.today().strftime('%Y%m%d')
