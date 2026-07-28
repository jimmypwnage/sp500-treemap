"""NYSE session calendar — the single source of truth for "which session is done".

Lifted out of refresh.py so the pipeline (fetch_data), the orchestrator (refresh)
and the brief (sp500_summary) all share one definition without an import cycle.

Every freshness decision in this project keys off latest_us_session(): the price
cache expires against it, downloaded bars are truncated to it, and the published
asOf is asserted equal to it. Never compare wall-clock day counts instead — a
calendar delta says nothing about whether a session actually closed.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import holidays

_ET = ZoneInfo("America/New_York")
_NYSE = holidays.financial_holidays("NYSE")


def latest_us_session(now_utc: dt.datetime | None = None) -> dt.date:
    """Date of the most recently *completed* NYSE session (16:00 ET close passed)."""
    et = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(_ET)
    d = et.date()
    if et.time() < dt.time(16, 0):        # today's close hasn't happened yet
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5 or d in _NYSE:  # walk back over weekend / holiday
        d -= dt.timedelta(days=1)
    return d
