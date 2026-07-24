#!/usr/bin/env python3
"""Refresh the S&P 500 treemap end-to-end:

  1. regenerate data.js   (fetch_data.main)
  2. render sp500.png      (headless Chrome screenshot of index.html)
  3. publish to GitHub Pages (git commit + push, only if data changed)

Guarded by should_refresh(): on weekends / US market holidays (i.e. when the
previous session produced no new close) the scheduled run skips *before* any
network call. Pass --force (or force=True) to bypass the guard — used by the
bot's on-demand first build so /sp500 always works, even on a weekend.

Run standalone (`python refresh.py [--force]`) or import and call refresh().
"""
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import holidays

HERE = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PNG = HERE / "sp500.png"
DATA = HERE / "data.js"
GIT_NAME = "Teoh, Min Wei"
GIT_EMAIL = "mteoh3@gatech.edu"
_ET = ZoneInfo("America/New_York")
_NYSE = holidays.financial_holidays("NYSE")


# --------------------------------------------------------------- market guard
def latest_us_session(now_utc: dt.datetime | None = None) -> dt.date:
    """Date of the most recently *completed* NYSE session (16:00 ET close passed)."""
    et = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(_ET)
    d = et.date()
    if et.time() < dt.time(16, 0):        # today's close hasn't happened yet
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5 or d in _NYSE:  # walk back over weekend / holiday
        d -= dt.timedelta(days=1)
    return d


def published_asof() -> dt.date | None:
    """The asOf date currently baked into data.js, or None if absent."""
    try:
        m = re.search(r'"asOf":"(\d{4}-\d{2}-\d{2})"', DATA.read_text())
        return dt.date.fromisoformat(m.group(1)) if m else None
    except FileNotFoundError:
        return None


def should_refresh() -> tuple[bool, str]:
    """Refresh only if a newer NYSE session exists than what we've published."""
    latest = latest_us_session()
    have = published_asof()
    if have is not None and latest <= have:
        return False, f"no new session (latest {latest:%a %Y-%m-%d} already published)"
    return True, f"new session {latest:%a %Y-%m-%d} (had {have})"


# --------------------------------------------------------------- steps
def render_png():
    """Screenshot index.html to sp500.png at 2x desktop width."""
    file_url = "file://" + str(HERE / "index.html").replace(" ", "%20")
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=2", "--window-size=1600,1000",
         "--virtual-time-budget=6000", f"--screenshot={PNG}", file_url],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not PNG.exists() or PNG.stat().st_size == 0:
        raise RuntimeError("PNG render failed (empty/missing file)")
    print(f"[png] {PNG.stat().st_size // 1024} KB", file=sys.stderr)


def publish() -> str:
    """Commit + push page assets only when something actually changed.

    Adds all tracked files (data.js + every .html page + treemap.js/.css); the
    binary snapshot/cache are gitignored. Daily runs typically only change data.js.
    """
    subprocess.run(["git", "add", "-A"], cwd=HERE, check=True)
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE).returncode
    if changed == 0:
        print("[publish] no changes, skipping push", file=sys.stderr)
        return "no_change"
    subprocess.run(
        ["git", "-c", f"user.name={GIT_NAME}", "-c", f"user.email={GIT_EMAIL}",
         "commit", "-m", "data refresh"], cwd=HERE, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=HERE, check=True)
    print("[publish] pushed to GitHub Pages", file=sys.stderr)
    return "published"


def refresh(force: bool = False) -> str:
    os.chdir(HERE)                      # fetch_data uses relative paths
    if not force:
        go, reason = should_refresh()
        if not go:
            print(f"[skip] {reason}", file=sys.stderr)
            return "skipped"
        print(f"[refresh] {reason}", file=sys.stderr)
    import fetch_data
    fetch_data.main()
    render_png()
    return publish()


if __name__ == "__main__":
    refresh(force="--force" in sys.argv)
