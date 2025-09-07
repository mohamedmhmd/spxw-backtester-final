from typing import Any, Dict

import numpy as np
from config.back_test_config import BacktestConfig


class Statistics:
    
    def _calculate_statistics(trades, equity_curve, daily_pnl) -> Dict[str, Any]:
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
        
        # Separate trades by type
        iron_1_condor_trades = [t for t in trades if t.trade_type == "Iron Condor 1"]
        straddle_2_trades = [t for t in trades if t.trade_type == "Straddle 1"]
        ic1 = {t.entry_time: t.pnl for t in trades if t.trade_type == "Iron Condor 1"}
        st1 = {t.entry_time: t.pnl for t in trades if t.trade_type == "Straddle 1"}
        couples1 = [(ic1[t] + st1[t]) > 0 for t in ic1 if t in st1] 
        ic2 = {t.entry_time: t.pnl for t in trades if t.trade_type == "Iron Condor 2"}
        st2 = {t.entry_time: t.pnl for t in trades if t.trade_type == "Straddle 2"}
        couples2 = [(ic2[t] + st2[t]) > 0 for t in ic2 if t in st2]
        ic3 = {t.entry_time: t.pnl for t in trades if "Iron Condor 3" in t.trade_type}
        st3 = {t.entry_time: t.pnl for t in trades if "Straddle 3" in t.trade_type}
        couples3 = [(ic3[t] + st3[t]) > 0 for t in ic3 if t in st3]
        win_rate = (sum(couples1) + sum(couples2) + sum(couples3))/ (len(couples1) + len(couples2) + len(couples3)) if couples1 and couples2 and couples3 else 0
        
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
        
        # Iron Condor specific stats
        ic_stats = {}
        if iron_1_condor_trades:
            ic_wins = [t for t in iron_1_condor_trades if t.pnl > 0]
            ic_losses = [t for t in iron_1_condor_trades if t.pnl < 0]
            ic_stats = {
                'total_trades': len(iron_1_condor_trades),
                'winning_trades': len(ic_wins),
                'losing_trades': len(ic_losses),
                'win_rate': len(ic_wins) / len(iron_1_condor_trades),
                'total_pnl': sum(t.pnl for t in iron_1_condor_trades),
                'avg_pnl': np.mean([t.pnl for t in iron_1_condor_trades]),
                'avg_credit': np.mean([t.metadata.get('net_credit', 0) for t in iron_1_condor_trades])
            }
        
        # Straddle specific stats
        straddle_stats = {}
        if straddle_2_trades:
            straddle_wins = [t for t in straddle_2_trades if t.pnl > 0]
            straddle_losses = [t for t in straddle_2_trades if t.pnl < 0]
            
            # Count partial exits
            partial_exit_count = 0
            total_partial_pnl = 0
            for trade in straddle_2_trades:
                for contract, details in trade.contracts.items():
                    if 'partial_exits' in details:
                        partial_exit_count += len(details['partial_exits'])
                        for exit in details['partial_exits']:
                            total_partial_pnl += exit['pnl']
            
            straddle_stats = {
                'total_trades': len(straddle_2_trades),
                'winning_trades': len(straddle_wins),
                'losing_trades': len(straddle_losses),
                'win_rate': len(straddle_wins) / len(straddle_2_trades),
                'total_pnl': sum(t.pnl for t in straddle_2_trades),
                'avg_pnl': np.mean([t.pnl for t in straddle_2_trades]),
                'partial_exits': partial_exit_count,
                'partial_exit_pnl': total_partial_pnl
            }
        
        return {
            'total_trades': len(trades)/2,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
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
            'iron_condor_stats': ic_stats,
            'straddle_stats': straddle_stats
        }