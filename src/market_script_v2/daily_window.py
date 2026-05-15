from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Tuple


def compute_today_window(now: datetime) -> Tuple[datetime, datetime, str]:
    noon = datetime.combine(now.date(), time(12, 0, 0))
    if now >= noon:
        start = noon
        end = noon + timedelta(days=1)
    else:
        start = noon - timedelta(days=1)
        end = noon
    window_tag = start.strftime("%Y-%m-%d_12")
    return start, end, window_tag

