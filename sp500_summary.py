"""Market summary for the morning brief — computed from data.js.

Pure read. build_summary() parses data.js; caption_html() formats a short
Telegram caption (index DoD, breadth, best/worst sector); show_market_section()
gates on whether a fresh NYSE session just closed, so the 7am brief only reports
a market day that actually happened the night before.
"""
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

from market_calendar import latest_us_session  # shared NYSE-calendar logic

HERE = Path(__file__).resolve().parent
DATA = HERE / "data.js"
_ET = ZoneInfo("America/New_York")


def _load() -> dict:
    s = DATA.read_text()
    return json.loads(s[s.index("{"):s.rindex("}") + 1])


def build_summary() -> dict:
    """Index DoD, advancers/decliners, and weight-weighted per-sector DoD."""
    d = _load()
    stocks = d["stocks"]                      # [ticker, sector, price, weight, dod, wow]
    spx = d.get("spxSeries") or []
    index_dod = (((1 + spx[-1]) / (1 + spx[-2]) - 1) * 100) if len(spx) >= 2 else None

    sw, swd = defaultdict(float), defaultdict(float)   # sector weight, weight*dod
    adv = dec = 0
    tw = twd = 0.0
    for r in stocks:                          # tuple: [tkr, sec, price, wt, dod, wow, ...metrics]
        sec, w, dod = r[1], r[3], r[4]
        w = w or 0.0
        sw[sec] += w
        swd[sec] += w * dod
        tw += w
        twd += w * dod
        if dod > 0:
            adv += 1
        elif dod < 0:
            dec += 1
    sectors = sorted(
        ({"name": s, "dod": (swd[s] / sw[s] if sw[s] else 0.0)} for s in sw),
        key=lambda x: x["dod"], reverse=True,
    )
    if index_dod is None:                      # fallback: weight-weighted mean
        index_dod = twd / tw if tw else 0.0
    up = sum(1 for s in sectors if s["dod"] > 0)
    return {
        "asOf": d["asOf"],
        "index_dod": round(index_dod, 2),
        "advancers": adv, "decliners": dec, "total": len(stocks),
        "sectors": [{"name": s["name"], "dod": round(s["dod"], 2)} for s in sectors],
        "up_sectors": up, "down_sectors": len(sectors) - up,
    }


def _breadth_phrase(s: dict) -> str:
    up = s["index_dod"] >= 0
    frac = (s["advancers"] if up else s["decliners"]) / max(1, s["total"])
    word = "gain" if up else "decline"
    if frac >= 0.70:
        return f"Broad-based {word}"
    if frac >= 0.55:
        return f"Mostly {'higher' if up else 'lower'}"
    return "Mixed / narrow"


def caption_html() -> str:
    """Short HTML caption for the treemap photo in the morning brief."""
    s = build_summary()
    d = dt.date.fromisoformat(s["asOf"])
    arrow = "🟢" if s["index_dod"] >= 0 else "🔴"
    sgn = "+" if s["index_dod"] >= 0 else ""
    best, worst = s["sectors"][0], s["sectors"][-1]
    bs = "+" if best["dod"] >= 0 else ""
    ws = "+" if worst["dod"] >= 0 else ""
    return "\n".join([
        f"{arrow} <b>S&amp;P 500</b> · {d:%a %-d %b}: <b>{sgn}{s['index_dod']:.2f}%</b>",
        f"{_breadth_phrase(s)} — {s['advancers']} up / {s['decliners']} down · "
        f"{s['up_sectors']}/{len(s['sectors'])} sectors green.",
        f"Best: {best['name']} {bs}{best['dod']:.2f}% · "
        f"Worst: {worst['name']} {ws}{worst['dod']:.2f}%.",
    ])


def show_market_section(now_utc: dt.datetime | None = None) -> bool:
    """True only if a NYSE session closed within the last ~20h AND data.js reflects
    it — i.e. a real market day happened the night before this morning's brief."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    latest = latest_us_session(now)
    close = dt.datetime.combine(latest, dt.time(16, 0), _ET).astimezone(dt.timezone.utc)
    hours = (now - close).total_seconds() / 3600
    if not (0 <= hours <= 20):
        return False
    try:
        return build_summary()["asOf"] == latest.isoformat()
    except Exception:
        return False


if __name__ == "__main__":
    print("show_market_section:", show_market_section())
    print(caption_html())
