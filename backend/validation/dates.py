from datetime import datetime, timedelta
from typing import Optional, Tuple, Union
import logging

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    pass


def parse_date_range(
    date_token: Optional[Union[str, dict]], reference_date: datetime
) -> Optional[Tuple[datetime, datetime]]:
    """
    Parse a date token into a concrete (start, end) tuple.

    Token types:
    - None → None (no date filter)
    - "today" → today only
    - "yesterday" → yesterday only
    - "this_week" → Monday to today
    - "last_week" → last Monday to last Sunday
    - "this_month" → 1st of month to today
    - "last_month" → 1st to last day of last month
    - "this_year" → Jan 1 to today
    - "last_year" → Jan 1 to Dec 31 of last year
    - {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"} → explicit range

    Returns: (start_datetime, end_datetime) or None
    """
    if date_token is None:
        return None

    if isinstance(date_token, dict):
        try:
            start = datetime.strptime(date_token.get("from", ""), "%Y-%m-%d")
            end = datetime.strptime(date_token.get("to", ""), "%Y-%m-%d")
            end = end.replace(hour=23, minute=59, second=59)
            return (start, end)
        except (ValueError, KeyError, TypeError) as e:
            raise ValidationError(f"Invalid date range format: {e}")

    token = str(date_token).lower().strip()

    if token == "today":
        start = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = reference_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        return (start, end)

    elif token == "yesterday":
        yesterday = reference_date - timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
        return (start, end)

    elif token == "this_week":
        monday = reference_date - timedelta(days=reference_date.weekday())
        start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = reference_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        return (start, end)

    elif token == "last_week":
        today_weekday = reference_date.weekday()
        last_sunday = reference_date - timedelta(days=today_weekday + 1)
        last_monday = last_sunday - timedelta(days=6)
        start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = last_sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
        return (start, end)

    elif token == "this_month":
        start = reference_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = reference_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        return (start, end)

    elif token == "last_month":
        first_of_this_month = reference_date.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        last_of_last_month = first_of_this_month - timedelta(seconds=1)
        first_of_last_month = last_of_last_month.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return (first_of_last_month, last_of_last_month)

    elif token == "this_year":
        start = reference_date.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        end = reference_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        return (start, end)

    elif token == "last_year":
        start = reference_date.replace(
            year=reference_date.year - 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end = reference_date.replace(
            year=reference_date.year - 1,
            month=12,
            day=31,
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
        return (start, end)

    else:
        raise ValidationError(
            f"Unknown date token '{token}'. Use: today, yesterday, this_week, last_week, "
            "this_month, last_month, this_year, last_year, or a dict with 'from' and 'to' keys"
        )
