from datetime import datetime


class Utilities:

    def _is_trading_day(date: datetime) -> bool:
        """Check if it's a trading day (simplified - doesn't check all holidays)"""
        # Skip major holidays (simplified list)
        holidays = [
            (1, 1),   # New Year's Day
            (7, 4),   # Independence Day
            (12, 25), # Christmas
        ]
        
        for month, day in holidays:
            if date.month == month and date.day == day:
                return False
        
        return True