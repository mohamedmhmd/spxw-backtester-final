from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Union, Tuple

import pandas as pd
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.common import Common
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider
import asyncio

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UnderlyingCover1:
    """
    Underlying Cover 1 implementation that hedges Credit Spread 1 positions
    by trading SPY when SPX breaches the short strike prices.
    
    Trade logic:
    - Cover 1(a): When SPX breaches short strike of CS 1(a), trade SPY in opposite direction
    - Cover 1(b): When SPX breaches short strike of CS 1(b), trade SPY in same direction
    """
    
    
    
    @staticmethod
    def _calculate_spy_shares(
        cs_trade: Trade,
        spx_spy_ratio: float,
        cash_risk_percentage: float = 1.0
    ) -> int:
        """
        Calculate number of SPY shares to trade based on Credit Spread position.
        
        Formula:
        - 1 option contract = 100 shares underlying
        - SPX:SPY ratio typically ~10:1
        - Cash risk percentage allows partial hedging
        
        Args:
            cs_trade: The Credit Spread trade being hedged
            spx_spy_ratio: Current SPX to SPY price ratio
            cash_risk_percentage: Percentage of cash risk to hedge (default 100%)
        
        Returns:
            Number of SPY shares to trade
        """
        # Get the trade size from Credit Spread
        cs_size = cs_trade.size
        
        # Each option represents 100 shares
        shares_per_contract = 100
        
        # Calculate base shares (CS size * 100 * ratio)
        # Since SPX is ~10x SPY, we need more SPY shares to hedge
        base_shares = cs_size * shares_per_contract * spx_spy_ratio
        
        # Apply cash risk percentage
        adjusted_shares = int(base_shares * cash_risk_percentage)
        
        logger.info(f"Calculated SPY shares: {adjusted_shares} "
                   f"(CS size: {cs_size}, ratio: {spx_spy_ratio:.2f}, "
                   f"cash risk: {cash_risk_percentage*100:.0f}%)")
        
        return adjusted_shares
    
    @staticmethod
    def _get_cs_short_strike(cs_trade: Trade) -> Optional[float]:
        """Extract the short strike from a Credit Spread trade"""
        for contract, details in cs_trade.contracts.items():
            if 'short' in details['leg_type']:
                return details['strike']
        return None
    
    @staticmethod
    def _determine_spy_direction(
        cs_trade: Trade,
        spx_price: float,
        short_strike: float
    ) -> str:
        variant = cs_trade.metadata.get('variant', 'a')
        spread_type = cs_trade.metadata.get('spread_type', '')
        
        if variant == 'a':  # Counter-trend
            if spread_type == 'call' and spx_price > short_strike:
                return 'buy'
            elif spread_type == 'put' and spx_price < short_strike:
                return 'sell'
        else:  # variant == 'b', Trend-following
            if spread_type == 'call' and spx_price > short_strike:
                return 'sell'
            elif spread_type == 'put' and spx_price < short_strike:
                return 'buy'
        
        return None
    
    @staticmethod
    async def _get_spy_quote(
        timestamp: datetime,
        data_provider: Union[MockDataProvider, PolygonDataProvider]
    ) -> Optional[Dict]:
        """Get current SPY quote"""
        try:
            quote = await data_provider.get_spy_quote(timestamp)
            return quote
        except Exception as e:
            logger.error(f"Failed to get SPY quote: {e}")
            return None
    
    @staticmethod
    async def _execute_cover_trade(
        cs_trade: Trade,
        direction: str,
        spy_shares: int,
        spy_quote: Dict,
        entry_time: datetime,
        spx_price: float,
        short_strike: float,
        strategy: StrategyConfig,
        config: BacktestConfig,
        spx_spy_ratio: float,
        high_of_day: float,
        low_of_day: float,
        market_direction: str
    ) -> Optional[Trade]:
        """Execute the Underlying Cover trade"""
        
        # Determine entry price based on direction (market order simulation)
        if direction == 'buy':
            spy_price = spy_quote.get('ask', spy_quote.get('price'))
            position = spy_shares
        else:  # sell
            spy_price = spy_quote.get('bid', spy_quote.get('price'))
            position = -spy_shares
        
        if spy_price is None:
            logger.warning("No valid SPY price available")
            return None
        
        # Calculate capital used (including commission)
        # For SPY, commission is typically per share
        commission_per_share = getattr(config, 'spy_commission_per_share', 0.01)
        total_commission = abs(spy_shares) * commission_per_share
        unit_used_capital = abs(spy_price)*100 + commission_per_share
        capital_used = abs(spy_shares * spy_price) + total_commission
        
        # Build trade contract
        trade_contracts = {
            'SPY': {
                'position': position,
                'entry_price': spy_price,
                'leg_type': direction,
                'shares': abs(spy_shares),
                'used_capital': unit_used_capital,
            }
        }
        
        # Determine variant for trade type
        variant = cs_trade.metadata.get('variant', 'a')
        
        # Create trade
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            trade_type=f"Underlying Cover 1({variant})",
            contracts=trade_contracts,
            size=cs_trade.size*strategy.uc_1_cash_risk_percentage,  # Size same as related CS trade
            used_capital=capital_used,
            unit_used_capital=unit_used_capital,
            metadata={
                'strategy_name': f"Underlying Cover 1({variant})",
                'entry_spx_price': spx_price,
                'entry_spy_price': spy_price,
                'cs_short_strike': short_strike,
                'breach_type': 'above' if spx_price > short_strike else 'below',
                'market_direction': market_direction,
                'shares': abs(spy_shares),
                'related_cs_trade': cs_trade.metadata.get('representation', ''),
                'variant': variant,
                'commission': total_commission,
                'net_premium': 0.0, # No premium for underlying trades
                'representation': "",
                'uc_1_cash_risk_percentage': strategy.uc_1_cash_risk_percentage,
                'spx_spy_ratio': spx_spy_ratio,
                'high_of_day': high_of_day,
                'low_of_day': low_of_day
            }
        )
        
        logger.info(f"Executed Underlying Cover 1({variant}): {direction.upper()} {abs(spy_shares)} SPY @ ${spy_price:.2f} "
                   f"(SPX breached {short_strike:.2f} at {spx_price:.2f})")
        
        return trade
    
    @staticmethod
    async def check_and_execute_covers(
        spx_ohlc_data: pd.DataFrame,
        i: int,
        active_cs_trades: List[Trade],
        current_spx_price: float,
        current_bar_time: datetime,
        date: datetime,
        strategy: StrategyConfig,
        data_provider: Union[MockDataProvider, PolygonDataProvider],
        config: BacktestConfig
    ) -> List[Trade]:
        """
        Check all active Credit Spread trades and execute covers if breached.
        
        Returns:
            List of new Underlying Cover trades executed
        """
        new_covers = []
        
        if not active_cs_trades:
            return new_covers
        
        # Calculate SPX:SPY ratio once for the day
        spx_spy_ratio = await Common._calculate_spx_spy_ratio(date, data_provider)
        
        # Get cash risk percentage from strategy config
        cash_risk_pct = getattr(strategy, 'uc_1_cash_risk_percentage', 1.0)
        
        # Check each active Credit Spread
        for cs_trade in active_cs_trades:
            # Get short strike
            short_strike = UnderlyingCover1._get_cs_short_strike(cs_trade)
            if short_strike is None:
                continue
            
            # Check if breached
            spread_type = cs_trade.metadata.get('spread_type', '')
            breached = False
            
            if spread_type == 'call' and current_spx_price > short_strike:
                breached = True
                logger.info(f"Call spread breached: SPX {current_spx_price:.2f} > strike {short_strike:.2f}")
            elif spread_type == 'put' and current_spx_price < short_strike:
                breached = True
                logger.info(f"Put spread breached: SPX {current_spx_price:.2f} < strike {short_strike:.2f}")
            
            if not breached:
                continue
            
            # Determine SPY trade direction
            direction = UnderlyingCover1._determine_spy_direction(
                cs_trade, current_spx_price, short_strike
            )
            
            if direction is None:
                continue
            
            # Calculate SPY shares to trade
            spy_shares = UnderlyingCover1._calculate_spy_shares(
                cs_trade, spx_spy_ratio, cash_risk_pct
            )
            
            if spy_shares == 0:
                continue
            
            # Get SPY quote
            spy_quote = await UnderlyingCover1._get_spy_quote(current_bar_time, data_provider)
            if spy_quote is None:
                continue
            
            # Execute cover trade
            high_of_day, low_of_day = Common._get_day_extremes(spx_ohlc_data, i)
            market_direction = await Common._determine_market_direction(current_spx_price, date, data_provider)
            cover_trade = await UnderlyingCover1._execute_cover_trade(
                cs_trade,
                direction,
                spy_shares,
                spy_quote,
                current_bar_time,
                current_spx_price,
                short_strike,
                strategy,
                config,
                spx_spy_ratio,
                high_of_day,
                low_of_day,
                market_direction
            )
            
            if cover_trade:
                new_covers.append(cover_trade)
        
        return new_covers
    
    
    
    @staticmethod
    async def close_covers_at_market_close(
        active_cover_trades: List[Trade],
        date: datetime,
        data_provider: Union[MockDataProvider, PolygonDataProvider],
        config: BacktestConfig
    ) -> None:
        """
        Close all Underlying Cover positions at market close to get neutral.
        This sells/buys SPY to flatten all positions.
        """
        if not active_cover_trades:
            return
        
        # Get closing SPY quote
        if isinstance(date, datetime):
            close_time = date.replace(hour=16, minute=0, second=0)
        else:
            close_time = datetime.combine(date, datetime.min.time()).replace(hour=16, minute=0)
        
        spy_quote = await UnderlyingCover1._get_spy_quote(close_time, data_provider)
        if spy_quote is None:
            logger.warning("Could not get closing SPY quote")
            return
        
        for trade in active_cover_trades:
            if trade.status != "OPEN":
                continue
            
            # Get position details
            spy_details = trade.contracts.get('SPY')
            if not spy_details:
                continue
            
            position = spy_details['position']
            entry_price = spy_details['entry_price']
            
            # Determine exit price (opposite of position)
            if position > 0:  # Long position, sell at bid
                exit_price = spy_quote.get('bid', spy_quote.get('price'))
            else:  # Short position, buy at ask
                exit_price = spy_quote.get('ask', spy_quote.get('price'))
            
            if exit_price is None:
                continue
            
            # Calculate P&L
            shares = abs(position)
            commission_per_share = getattr(config, 'spy_commission_per_share', 0.01)
            exit_commission = shares * commission_per_share
            
            if position > 0:  # Long
                unit_pnl_before_commission = (exit_price - entry_price)*int(100*trade.metadata.get('spx_spy_ratio',10))
                pnl_before_commission = (exit_price - entry_price) * shares
            else:  # Short
                unit_pnl_before_commission = (entry_price - exit_price)*int(100*trade.metadata.get('spx_spy_ratio',10))
                pnl_before_commission = (entry_price - exit_price) * shares
            
            unit_pnl = unit_pnl_before_commission - commission_per_share*int(100*trade.metadata.get('spx_spy_ratio',10))
            total_pnl = pnl_before_commission - exit_commission
            
            # Update trade
            spy_details['exit_price'] = exit_price
            spy_details['pnl'] = total_pnl
            trade.contracts['SPY'] = spy_details
            
            trade.exit_time = close_time
            trade.status = "CLOSED"
            trade.unit_pnl = unit_pnl
            trade.unit_pnl_without_commission = unit_pnl_before_commission
            trade.pnl = total_pnl
            trade.pnl_without_commission = pnl_before_commission
            trade.exit_signals = {'market_close': True, 'exit_spy_price': exit_price}
            
            if not trade.metadata:
                trade.metadata = {}
            trade.metadata['exit_spy_price'] = exit_price
            trade.metadata['exit_time'] = close_time
            trade.metadata['exit_spx_price'] = await data_provider.get_sp_closing_price(date, "I:SPX")
            trade.metadata['exit_commission'] = exit_commission
            
            logger.info(f"Closed Underlying Cover 1({trade.metadata.get('variant', 'a')}) at market close: "
                       f"{'SOLD' if position > 0 else 'BOUGHT'} {shares} SPY @ ${exit_price:.2f}, "
                       f"P&L=${total_pnl:.2f}")