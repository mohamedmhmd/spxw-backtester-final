from datetime import datetime
import logging
from typing import Dict, List, Optional, Union
import numpy as np
from config.back_test_config import BacktestConfig
from config.strategy_config import StrategyConfig
from trades.trade import Trade
from data.mock_data_provider import MockDataProvider
from data.polygon_data_provider import PolygonDataProvider

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LongOption1:
    """
    Long Option 1 implementation that protects Underlying Cover positions.
    
    Trade logic:
    - Buys long options in opposite direction of the Cover trade
    - Strike is calculated as: CS short strike +/- (net premium * multiplier)
    - Size matches the Cover trade to protect 100% of risk
    - Triggered at same time as Underlying Cover 1
    """
    
    @staticmethod
    def _calculate_long_option_strike(
        cs_trade: Trade,
        strategy: StrategyConfig
    ) -> tuple[float, str]:
        """
        Calculate the strike for the long option protection.
        
        Formula: short_strike +/- (net_premium * strike_multiplier)
        - For put spreads (Cover sells SPY): buy call at short_strike + offset
        - For call spreads (Cover buys SPY): buy put at short_strike - offset
        
        Args:
            cs_trade: The Credit Spread trade being protected
            strategy: Strategy configuration with lo_1_strike_multiplier
            
        Returns:
            tuple: (strike_price, option_type) where option_type is 'call' or 'put'
        """
        # Get short strike from Credit Spread
        short_strike = None
        for contract, details in cs_trade.contracts.items():
            if 'short' in details['leg_type']:
                short_strike = details['strike']
                break
        
        if short_strike is None:
            logger.error("Could not find short strike in Credit Spread")
            return None, None
        
        # Get net premium from Credit Spread (this is negative in metadata)
        net_premium = abs(cs_trade.metadata.get('net_premium', 0.0))
        
        # Get strike multiplier from strategy config (default 5 from documentation)
        strike_multiplier = getattr(strategy, 'lo_1_strike_multiplier', 5.0)
        
        # Calculate offset
        offset = net_premium * strike_multiplier
        
        # Determine option type and strike based on spread type
        spread_type = cs_trade.metadata.get('spread_type', '')
        
        if spread_type == 'put':
            # Put spread breached = Cover sold SPY = need Call protection
            target_strike = short_strike + offset
            option_type = 'call'
        elif spread_type == 'call':
            # Call spread breached = Cover bought SPY = need Put protection
            target_strike = short_strike - offset
            option_type = 'put'
        else:
            logger.error(f"Unknown spread type: {spread_type}")
            return None, None
        
        # Round to nearest 5-point strike
        rounded_strike = int(np.round(target_strike / 5) * 5)
        
        logger.info(f"Calculated Long Option strike: {rounded_strike} {option_type} "
                   f"(short: {short_strike}, premium: ${net_premium:.2f}, "
                   f"multiplier: {strike_multiplier}, offset: {offset:.2f})")
        
        return rounded_strike, option_type
    
    @staticmethod
    def _create_option_symbol(
        strike: float,
        option_type: str,
        expiration: datetime
    ) -> str:
        """Create SPX option contract symbol"""
        exp_str = expiration.strftime('%y%m%d')
        option_code = 'C' if option_type == 'call' else 'P'
        return f"O:SPXW{exp_str}{option_code}{int(strike*1000):08d}"
    
    @staticmethod
    async def _execute_long_option(
        cs_trade: Trade,
        cover_trade: Trade,
        strike: float,
        option_type: str,
        timestamp: datetime,
        date: datetime,
        strategy: StrategyConfig,
        data_provider: Union[MockDataProvider, PolygonDataProvider],
        config: BacktestConfig
    ) -> Optional[Trade]:
        """Execute the Long Option protection trade"""
        
        # Create option symbol
        option_symbol = LongOption1._create_option_symbol(strike, option_type, date)
        
        # Get option quote
        try:
            quote = await data_provider._get_option_tick_quote(option_symbol, timestamp)
            if not quote:
                logger.warning(f"No quote available for {option_symbol}")
                return None
        except Exception as e:
            logger.error(f"Failed to get quote for {option_symbol}: {e}")
            return None
        
        # Use ask price for buying
        option_price = quote.get('ask')
        if option_price is None or option_price <= 0:
            logger.warning(f"Invalid option price for {option_symbol}: {option_price}")
            return None
        
        # Get cover risk percentage from strategy (default 100%)
        cover_risk_pct = getattr(strategy, 'lo_1_cover_risk_percentage', 1.0)
        
        # Calculate size based on Cover trade and cover risk percentage
        # Cover trade size already accounts for cash_risk_percentage
        # We need to match that to protect the SPY position
        size = int(cover_trade.size * cover_risk_pct)
        
        if size == 0:
            logger.warning("Calculated size is 0, skipping Long Option trade")
            return None
        
        # Build trade contract
        unit_used_capital = option_price * 100 + config.commission_per_contract
        
        trade_contracts = {
            option_symbol: {
                'position': size,
                'entry_price': option_price,
                'leg_type': f'long_{option_type}',
                'strike': strike,
                'used_capital': unit_used_capital
            }
        }
        
        # Determine variant
        variant = cs_trade.metadata.get('variant', 'a')
        
        # Create trade
        trade = Trade(
            entry_time=timestamp,
            exit_time=None,
            trade_type=f"Long Option 1({variant})",
            contracts=trade_contracts,
            size=size,
            used_capital=0.0,
            metadata={
                'strategy_name': f"Long Option 1({variant})",
                'entry_spx_price': cover_trade.metadata.get('entry_spx_price'),
                'option_type': option_type,
                'strike': strike,
                'variant': variant,
                'related_cs_trade': cs_trade.metadata.get('representation', ''),
                'related_cover_trade': f"{cover_trade.metadata.get('direction', '').upper()} "
                                      f"{cover_trade.metadata.get('shares', 0)} SPY",
                'net_premium': -option_price,  # Negative because we're buying
                'representation': f"Long {option_type.capitalize()} @ {strike}",
                'lo_1_cover_risk_percentage': cover_risk_pct,
                'lo_1_strike_multiplier': getattr(strategy, 'lo_1_strike_multiplier', 5.0),
                'market_direction': cover_trade.metadata.get('market_direction', ''),
                'high_of_day': cover_trade.metadata.get('high_of_day', None),
                'low_of_day': cover_trade.metadata.get('low_of_day', None),
                'spx_spy_ratio': cover_trade.metadata.get('spx_spy_ratio', None)
            }
        )
        
        logger.info(f"Executed Long Option 1({variant}): BOUGHT {size} {option_type} @ ${strike} "
                   f"for ${option_price:.2f} (protecting {cover_trade.metadata.get('shares', 0)} SPY)")
        
        return trade
    
    @staticmethod
    async def execute_long_option_with_cover(
        cs_trade: Trade,
        cover_trade: Trade,
        timestamp: datetime,
        date: datetime,
        strategy: StrategyConfig,
        data_provider: Union[MockDataProvider, PolygonDataProvider],
        config: BacktestConfig
    ) -> Optional[Trade]:
        """
        Execute Long Option trade when Underlying Cover is triggered.
        This should be called immediately after a Cover trade is executed.
        
        Args:
            cs_trade: The Credit Spread trade being hedged
            cover_trade: The Underlying Cover trade that was just executed
            timestamp: Current timestamp
            date: Trading date
            strategy: Strategy configuration
            data_provider: Data provider
            config: Backtest configuration
            
        Returns:
            Long Option trade if successful, None otherwise
        """
        # Calculate strike and option type
        strike, option_type = LongOption1._calculate_long_option_strike(cs_trade, strategy)
        
        if strike is None or option_type is None:
            logger.warning("Could not calculate Long Option strike")
            return None
        
        # Execute the trade
        long_option_trade = await LongOption1._execute_long_option(
            cs_trade,
            cover_trade,
            strike,
            option_type,
            timestamp,
            date,
            strategy,
            data_provider,
            config,
        )
        
        return long_option_trade