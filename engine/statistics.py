from typing import Any, Dict

import numpy as np
from config.back_test_config import BacktestConfig


class Statistics:
    
    def _calculate_statistics(trades, equity_curve, daily_pnl, selected_strategy) -> Dict[str, Any]:
        if selected_strategy == "Trades 16":
            return Statistics._calculate_statistics_16(trades, equity_curve, daily_pnl)
        elif selected_strategy == "Trades 17":
            return Statistics._calculate_statistics_17(trades, equity_curve, daily_pnl)
        elif selected_strategy == "Trades 18":
            return Statistics._calculate_statistics_18(trades, equity_curve, daily_pnl)
    
    def _calculate_statistics_16(trades, equity_curve, daily_pnl) -> Dict[str, Any]:
        """Calculate comprehensive backtest statistics"""
        if not trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'return_pct': 0.0,
                'avg_trade_pnl': 0.0,
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'total_capital_used': 0.0,
                'iron_condor_stats': {},
                'straddle_stats': {}
            }
            
        # Calculate total capital used if not provided
        total_capital_used = sum(t.used_capital for t in trades)
        
        ic1 = {t.entry_time: t.pnl for t in trades if t.trade_type == "Iron Condor 1"}
        st1 = {t.entry_time: t.pnl for t in trades if t.trade_type == "Straddle 1"}
        couples1 = [(ic1[t] + st1[t]) > 0 for t in ic1 if t in st1] 
        ic2 = {t.entry_time: t.pnl for t in trades if t.trade_type == "Iron Condor 2"}
        st2 = {t.entry_time: t.pnl for t in trades if t.trade_type == "Straddle 2"}
        couples2 = [(ic2[t] + st2[t]) > 0 for t in ic2 if t in st2]
        ic3 = {t.entry_time: t.pnl for t in trades if "Iron Condor 3" in t.trade_type}
        st3 = {t.entry_time: t.pnl for t in trades if "Straddle 3" in t.trade_type}
        couples3 = [(ic3[t] + st3[t]) > 0 for t in ic3 if t in st3]
        trade_16_win_rate = (sum(couples1) + sum(couples2) + sum(couples3))/ (len(couples1) + len(couples2) + len(couples3)) if couples1 else 0
        
        
        
        # Overall statistics
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]
        
        total_pnl = sum(t.pnl for t in trades)
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        
        # Profit factor
        gross_profits = sum(t.pnl for t in winning_trades)
        gross_losses = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profits / gross_losses if gross_losses > 0 else float('inf')
        
        # Maximum drawdown
        equity_values = [eq[1] for eq in equity_curve]
        if len(equity_values) > 1:
            running_max = np.maximum.accumulate(equity_values)
            drawdowns = (equity_values - running_max) / running_max
            max_drawdown = abs(np.min(drawdowns))
        else:
            max_drawdown = 0
        
        # Sharpe ratio (using capital used instead of initial capital)
        if len(daily_pnl) > 1 and total_capital_used > 0:
            daily_returns = list(daily_pnl.values())
            daily_returns_pct = [r / total_capital_used for r in daily_returns]  # USE total_capital_used
            if np.std(daily_returns_pct) > 0:
                sharpe_ratio = np.sqrt(252) * np.mean(daily_returns_pct) / np.std(daily_returns_pct)
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0
        
        # Total return based on capital used
        if total_capital_used > 0:
            return_pct = (total_pnl / total_capital_used)  # Return on capital used
        else:
            return_pct = 0
        
       
        
        return {
            'total_trades': len(trades)/2,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'trade_16_win_rate': trade_16_win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'return_pct': return_pct,
            'total_capital_used': total_capital_used, 
            'avg_trade_pnl': total_pnl / len(trades) if trades else 0,
            'best_trade': max(trades, key=lambda t: t.pnl).pnl if trades else 0,
            'worst_trade': min(trades, key=lambda t: t.pnl).pnl if trades else 0,
            'iron_1_trades': len(ic1),
            'iron_1_pnl': sum(ic1.values()),
            'iron_1_win_rate': sum(1 for pnl in ic1.values() if pnl > 0) / len(ic1) if ic1 else 0,
            'straddle_1_trades': len(st1),
            'straddle_1_pnl': sum(st1.values()),
            'straddle_1_win_rate': sum(1 for pnl in st1.values() if pnl > 0) / len(st1) if st1 else 0,
            'iron_2_trades': len(ic2), 
            'iron_2_pnl': sum(ic2.values()),
            'iron_2_win_rate': sum(1 for pnl in ic2.values() if pnl > 0) / len(ic2) if ic2 else 0,
            'straddle_2_trades': len(st2),
            'straddle_2_pnl': sum(st2.values()),
            'straddle_2_win_rate': sum(1 for pnl in st2.values() if pnl > 0) / len(st2) if st2 else 0,
            'iron_3_trades': len(ic3),
            'iron_3_pnl': sum(ic3.values()),
            'iron_3_win_rate': sum(1 for pnl in ic3.values() if pnl > 0) / len(ic3) if ic3 else 0,
            'straddle_3_trades': len(st3),
            'straddle_3_pnl': sum(st3.values()),
            'straddle_3_win_rate': sum(1 for pnl in st3.values() if pnl > 0) / len(st3) if st3 else 0,
        }
        
        
    def _calculate_statistics_17(trades, equity_curve, daily_pnl) -> Dict[str, Any]:
        """Calculate comprehensive backtest statistics"""
        if not trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'return_pct': 0.0,
                'avg_trade_pnl': 0.0,
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'total_capital_used': 0.0,
                'iron_condor_stats': {},
                'straddle_stats': {}
            }
            
        # Calculate total capital used if not provided
        total_capital_used = sum(t.used_capital for t in trades)
        
        cs1a = {t.entry_time: t.pnl for t in trades if t.trade_type == "Credit Spread 1(a)"}
        cs1b = {t.entry_time: t.pnl for t in trades if t.trade_type == "Credit Spread 1(b)"}
        cv1a = {t.entry_time: t.pnl for t in trades if t.trade_type == "Underlying Cover 1(a)"}
        cv1b = {t.entry_time: t.pnl for t in trades if t.trade_type == "Underlying Cover 1(b)"}
        lo1a = {t.entry_time: t.pnl for t in trades if t.trade_type == "Long Option 1(a)"}
        lo1b = {t.entry_time: t.pnl for t in trades if t.trade_type == "Long Option 1(b)"}
        trade_17_win_rate = len([t for t in trades if t.pnl > 0])/ len(trades) if trades else 0
        
        # Overall statistics
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]
        
        total_pnl = sum(t.pnl for t in trades)
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        
        # Profit factor
        gross_profits = sum(t.pnl for t in winning_trades)
        gross_losses = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profits / gross_losses if gross_losses > 0 else float('inf')
        
        # Maximum drawdown
        equity_values = [eq[1] for eq in equity_curve]
        if len(equity_values) > 1:
            running_max = np.maximum.accumulate(equity_values)
            drawdowns = (equity_values - running_max) / running_max
            max_drawdown = abs(np.min(drawdowns))
        else:
            max_drawdown = 0
        
        # Sharpe ratio (using capital used instead of initial capital)
        if len(daily_pnl) > 1 and total_capital_used > 0:
            daily_returns = list(daily_pnl.values())
            daily_returns_pct = [r / total_capital_used for r in daily_returns]  # USE total_capital_used
            if np.std(daily_returns_pct) > 0:
                sharpe_ratio = np.sqrt(252) * np.mean(daily_returns_pct) / np.std(daily_returns_pct)
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0
        
        # Total return based on capital used
        if total_capital_used > 0:
            return_pct = (total_pnl / total_capital_used)  # Return on capital used
        else:
            return_pct = 0
        
       
        
        return {
            'total_trades': len(trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'return_pct': return_pct,
            'total_capital_used': total_capital_used, 
            'avg_trade_pnl': total_pnl / len(trades) if trades else 0,
            'best_trade': max(trades, key=lambda t: t.pnl).pnl if trades else 0,
            'worst_trade': min(trades, key=lambda t: t.pnl).pnl if trades else 0,
            'trade_17_win_rate': trade_17_win_rate,
            'cs_1a_trades': len(cs1a),
            'cs_1a_pnl': sum(cs1a.values()),
            'cs_1a_win_rate': sum(1 for pnl in cs1a.values() if pnl > 0) / len(cs1a) if cs1a else 0,
            'cs_1b_trades': len(cs1b),
            'cs_1b_pnl': sum(cs1b.values()),
            'cs_1b_win_rate': sum(1 for pnl in cs1b.values() if pnl > 0) / len(cs1b) if cs1b else 0,
            'uc_1a_trades': len(cv1a),
            'uc_1a_pnl': sum(cv1a.values()),
            'uc_1a_win_rate': sum(1 for pnl in cv1a.values() if pnl > 0) / len(cv1a) if cv1a else 0,
            'uc_1b_trades': len(cv1b),
            'uc_1b_pnl': sum(cv1b.values()),
            'uc_1b_win_rate': sum(1 for pnl in cv1b.values() if pnl > 0) / len(cv1b) if cv1b else 0,
            'lo_1a_trades': len(lo1a),
            'lo_1a_pnl': sum(lo1a.values()),
            'lo_1a_win_rate': sum(1 for pnl in lo1a.values() if pnl > 0) / len(lo1a) if lo1a else 0,
            'lo_1b_trades': len(lo1b),
            'lo_1b_pnl': sum(lo1b.values()),
            'lo_1b_win_rate': sum(1 for pnl in lo1b.values() if pnl > 0) / len(lo1b) if lo1b else 0,
            
        }
        
        
        
    def _calculate_statistics_18(trades, equity_curve, daily_pnl) -> Dict[str, Any]:
        """Calculate comprehensive backtest statistics"""
        if not trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'return_pct': 0.0,
                'avg_trade_pnl': 0.0,
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'total_capital_used': 0.0,
                'iron_condor_stats': {},
                'straddle_stats': {}
            }
            
        # Calculate total capital used if not provided
        total_capital_used = sum(t.used_capital for t in trades)
        
        ls1a = {t.entry_time: t.pnl for t in trades if t.trade_type == "Long Strangle 1(a)"}
        ls1b = {t.entry_time: t.pnl for t in trades if t.trade_type == "Long Strangle 1(b)"}
        ls2a = {t.entry_time: t.pnl for t in trades if t.trade_type == "Long Strangle 2(a)"}
        ls2b = {t.entry_time: t.pnl for t in trades if t.trade_type == "Long Strangle 2(b)"}
        ictb = {t.entry_time: t.pnl for t in trades if t.trade_type == "Iron Condor Time-Based"}
        trade_18_win_rate = len([t for t in trades if t.pnl > 0])/ len(trades) if trades else 0
        
        # Overall statistics
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]
        
        total_pnl = sum(t.pnl for t in trades)
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        
        # Profit factor
        gross_profits = sum(t.pnl for t in winning_trades)
        gross_losses = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profits / gross_losses if gross_losses > 0 else float('inf')
        
        # Maximum drawdown
        equity_values = [eq[1] for eq in equity_curve]
        if len(equity_values) > 1:
            running_max = np.maximum.accumulate(equity_values)
            drawdowns = (equity_values - running_max) / running_max
            max_drawdown = abs(np.min(drawdowns))
        else:
            max_drawdown = 0
        
        # Sharpe ratio (using capital used instead of initial capital)
        if len(daily_pnl) > 1 and total_capital_used > 0:
            daily_returns = list(daily_pnl.values())
            daily_returns_pct = [r / total_capital_used for r in daily_returns]  # USE total_capital_used
            if np.std(daily_returns_pct) > 0:
                sharpe_ratio = np.sqrt(252) * np.mean(daily_returns_pct) / np.std(daily_returns_pct)
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0
        
        # Total return based on capital used
        if total_capital_used > 0:
            return_pct = (total_pnl / total_capital_used)  # Return on capital used
        else:
            return_pct = 0
        
       
        
        return {
            'total_trades': len(trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'return_pct': return_pct,
            'total_capital_used': total_capital_used, 
            'avg_trade_pnl': total_pnl / len(trades) if trades else 0,
            'best_trade': max(trades, key=lambda t: t.pnl).pnl if trades else 0,
            'worst_trade': min(trades, key=lambda t: t.pnl).pnl if trades else 0,
            'trade_18_win_rate': trade_18_win_rate,
            'ls_1a_trades': len(ls1a),
            'ls_1a_pnl': sum(ls1a.values()),
            'ls_1a_win_rate': sum(1 for pnl in ls1a.values() if pnl > 0) / len(ls1a) if ls1a else 0,
            'ls_1b_trades': len(ls1b),
            'ls_1b_pnl': sum(ls1b.values()),
            'ls_1b_win_rate': sum(1 for pnl in ls1b.values() if pnl > 0) / len(ls1b) if ls1b else 0,
            'ls_2a_trades': len(ls2a),
            'ls_2a_pnl': sum(ls2a.values()),
            'ls_2a_win_rate': sum(1 for pnl in ls2a.values() if pnl > 0) / len(ls2a) if ls2a else 0,
            'ls_2b_trades': len(ls2b),
            'ls_2b_pnl': sum(ls2b.values()),
            'ls_2b_win_rate': sum(1 for pnl in ls2b.values() if pnl > 0) / len(ls2b) if ls2b else 0,
            'ic_tb_trades': len(ictb),
            'ic_tb_pnl': sum(ictb.values()),
            'ic_tb_win_rate': sum(1 for pnl in ictb.values() if pnl > 0) / len(ictb) if ictb else 0,
        }    