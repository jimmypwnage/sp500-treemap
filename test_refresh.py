"""Self-tests for the session-freshness logic (market_calendar + fetch_data cache).

Standalone — no pytest:  python test_refresh.py
Exits non-zero if any check fails. No network: yf.download is stubbed.

Backs the 2026-07-28 stale-data fix. Two independent bugs let the treemap serve a
Friday-morning intraday quote as "Friday's close" for four days:

  1. get_closes() wrote whatever yfinance returned, including the in-progress
     session's partial bar, under that day's date. The 24 Jul run at 22:02 SGT
     (10:02 ET, market open) stored META at 602.97; the real close was 595.19.
     That also poisoned should_refresh(), which then believed Friday was already
     published and skipped the Saturday run that would have corrected it.
  2. The cache expired on a wall-clock `<= 4 days` window, so it only ever
     refetched on day 5 — missing most sessions, not just Monday's.

Both are now gated on latest_us_session(). The walk test below replays a full
12-day cycle so a regression shows up here rather than a week later in the bot.
"""
from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import fetch_data
import refresh
from market_calendar import latest_us_session

SGT = ZoneInfo("Asia/Singapore")
_FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  ok   {msg}")
    else:
        _FAILS.append(msg)
        print(f"  FAIL {msg}")


def eq(got, exp, msg: str) -> None:
    check(got == exp, f"{msg}  (got {got}, want {exp})")


def at(d: dt.date, hh: int, mm: int, tz=SGT) -> dt.datetime:
    """A wall-clock instant in `tz`, as UTC — for injecting into latest_us_session."""
    return dt.datetime.combine(d, dt.time(hh, mm), tz).astimezone(dt.timezone.utc)


# ------------------------------------------------------------ calendar
def test_latest_us_session() -> None:
    print("\nlatest_us_session")
    # 16:00 ET is the boundary: before it, today's close hasn't happened.
    eq(latest_us_session(at(dt.date(2026, 7, 28), 15, 59, ZoneInfo("America/New_York"))),
       dt.date(2026, 7, 27), "Tue 15:59 ET -> Mon (today not closed yet)")
    eq(latest_us_session(at(dt.date(2026, 7, 28), 16, 0, ZoneInfo("America/New_York"))),
       dt.date(2026, 7, 28), "Tue 16:00 ET -> Tue (close just happened)")

    # The SGT schedule: the 06:30 job sees the previous US session.
    eq(latest_us_session(at(dt.date(2026, 7, 28), 6, 30)),
       dt.date(2026, 7, 27), "Tue 06:30 SGT -> Mon 27 (the session that went missing)")
    eq(latest_us_session(at(dt.date(2026, 7, 25), 6, 30)),
       dt.date(2026, 7, 24), "Sat 06:30 SGT -> Fri 24 (Friday HAS closed by then)")
    eq(latest_us_session(at(dt.date(2026, 7, 27), 6, 30)),
       dt.date(2026, 7, 24), "Mon 06:30 SGT -> Fri 24 (weekend walk-back)")

    # Holidays walk back too: 2026-07-03 is the observed Independence Day holiday.
    eq(latest_us_session(at(dt.date(2026, 7, 4), 6, 30)),
       dt.date(2026, 7, 2), "Sat 4 Jul 06:30 SGT -> Thu 2 (holiday skipped)")


# ------------------------------------------------------------ cache harness
def _frame(end: dt.date, periods: int = 180, extra: dt.date | None = None) -> pd.DataFrame:
    """Synthetic close history ending at `end`, optionally plus a partial bar."""
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=periods)
    if extra is not None:
        idx = idx.append(pd.DatetimeIndex([pd.Timestamp(extra)]))
    return pd.DataFrame({"AAPL": range(len(idx)), "^GSPC": range(len(idx))},
                        index=idx, dtype=float)


class Harness:
    """Runs get_closes against a temp cache with yf.download stubbed out."""

    def __init__(self, tmp: Path):
        self.cache = tmp / "closes.pkl"
        self.calls = 0
        self.serve_through: dt.date | None = None   # what "yfinance" has
        self.partial: dt.date | None = None         # an in-progress bar it also returns
        fetch_data.CACHE = str(self.cache)
        fetch_data.yf = self                        # stub: we expose .download

    def download(self, *a, **kw):
        self.calls += 1
        return _frame(self.serve_through, extra=self.partial)

    def seed(self, tip: dt.date, **kw) -> None:
        _frame(tip, **kw).to_pickle(self.cache)

    def run(self, cutoff: dt.date):
        before = self.calls
        self.serve_through = self.serve_through or cutoff
        closes = fetch_data.get_closes(["AAPL"], cutoff)
        return closes, self.calls > before


def test_cache_expiry(h: Harness) -> None:
    print("\ncache expiry (session-based, not day-count)")
    h.seed(dt.date(2026, 7, 24))

    # The exact regression: Tue 06:30 SGT, cache tip Fri 24, cutoff Mon 27.
    # delta is 4 calendar days -> the old `<= 4` window served the stale pickle.
    h.serve_through = dt.date(2026, 7, 27)
    closes, fetched = h.run(dt.date(2026, 7, 27))
    check(fetched, "tip Fri 24 + cutoff Mon 27 -> REFETCH (old code cached: delta==4)")
    eq(closes.index[-1].date(), dt.date(2026, 7, 27), "  and the frame now reaches Mon 27")

    # Same session again (e.g. /sp500 on-demand later that day) -> no refetch.
    _, fetched = h.run(dt.date(2026, 7, 27))
    check(not fetched, "tip == cutoff -> cache hit (reruns stay cheap)")

    # A short cache is refetched even when the tip is current.
    h.seed(dt.date(2026, 7, 27), periods=fetch_data.W6)      # < W6 + 5
    _, fetched = h.run(dt.date(2026, 7, 27))
    check(fetched, "history shorter than W6+5 -> refetch regardless of tip")


def test_partial_bar_truncated(h: Harness) -> None:
    print("\npartial-bar truncation")
    # Reproduces the 24 Jul 22:02 SGT run: fetching mid-session, when yfinance
    # returns an in-progress bar for a day whose 16:00 ET close hasn't happened.
    h.seed(dt.date(2026, 7, 17))
    h.serve_through = dt.date(2026, 7, 23)
    h.partial = dt.date(2026, 7, 24)          # today, still trading
    closes, fetched = h.run(dt.date(2026, 7, 23))
    check(fetched, "stale tip -> refetch")
    eq(closes.index[-1].date(), dt.date(2026, 7, 23),
       "in-progress 24 Jul bar dropped (this is what stored META 602.97)")

    cached = pd.read_pickle(h.cache)
    eq(cached.index[-1].date(), dt.date(2026, 7, 23),
       "partial bar never reaches the cache either")
    h.partial = None


def test_full_cycle(h: Harness) -> None:
    """Replay 12 consecutive 06:30 SGT runs: refetch iff a new session closed."""
    print("\n12-day cycle (the walk that exposed the day-count bug)")
    start_tip = tip = dt.date(2026, 7, 29)
    h.seed(tip)
    stale_days, got = [], []
    seen = set()
    for i in range(12):
        d = dt.date(2026, 7, 30) + dt.timedelta(days=i)
        cutoff = latest_us_session(at(d, 6, 30))
        seen.add(cutoff)
        if cutoff <= tip:
            continue                      # should_refresh() skips before any call
        h.serve_through = cutoff
        closes, fetched = h.run(cutoff)
        if not fetched or closes.index[-1].date() != cutoff:
            stale_days.append(f"{d:%a %d %b}->{cutoff}")
        got.append(cutoff)
        tip = cutoff
        h.seed(tip)

    # Every session the window exposed must be fetched exactly once, in order.
    want = sorted(s for s in seen if s > start_tip)
    check(not stale_days, f"every new session fetched (stale: {stale_days or 'none'})")
    eq(got, want, f"fetched each of the {len(want)} sessions exactly once, in order")
    eq(len(got), len(set(got)), "no session fetched twice (cache still absorbs reruns)")


# ------------------------------------------------------------ post-condition
def test_assert_fresh() -> None:
    print("\nassert_fresh post-condition")
    real_asof, real_latest = refresh.published_asof, refresh.latest_us_session
    try:
        refresh.latest_us_session = lambda *a, **k: dt.date(2026, 7, 27)

        refresh.published_asof = lambda: dt.date(2026, 7, 24)
        try:
            refresh.assert_fresh()
            check(False, "stale asOf must raise")
        except RuntimeError as e:
            check("2026-07-24" in str(e) and "2026-07-27" in str(e),
                  "stale asOf raises naming both dates (this run reported success)")

        refresh.published_asof = lambda: dt.date(2026, 7, 27)
        try:
            refresh.assert_fresh()
            check(True, "current asOf passes")
        except RuntimeError as e:
            check(False, f"current asOf must not raise ({e})")
    finally:
        refresh.published_asof, refresh.latest_us_session = real_asof, real_latest


def main() -> int:
    real_yf, real_cache = fetch_data.yf, fetch_data.CACHE
    try:
        test_latest_us_session()
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp))
            test_cache_expiry(h)
            test_partial_bar_truncated(h)
            test_full_cycle(h)
        test_assert_fresh()
    finally:
        fetch_data.yf, fetch_data.CACHE = real_yf, real_cache

    print()
    if _FAILS:
        print(f"{len(_FAILS)} FAILED:")
        for f in _FAILS:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
