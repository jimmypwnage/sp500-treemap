# S&P 500 Treemap

Finviz-style heatmap of the S&P 500. Tiles grouped by GICS sector, sized by
index weight, colored by day-over-day % change. Hover shows a tooltip with
price / DoD / WoW / index weight and a 3-line sparkline (ticker vs. sector vs.
S&P 500, normalized 1-month daily return).

## Files
- `fetch_data.py` — one-shot data pipeline. Writes `data.js`.
- `index.html` — the treemap. Loads `data.js` (`window.SP500`). Open directly in a browser.
- `data.js` — generated data (`window.SP500 = {...}`).
- `closes.pkl` — cached daily closes (skips refetch if <4 days old).
- `mockup.html` — original standalone mockup with sample data (kept for reference).

## Run
```bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
/Users/jimmyteoh/anaconda3/bin/python3 fetch_data.py   # regenerates data.js
open index.html
```

## Data sources (3 network calls — kept low to avoid Yahoo rate limits)
1. **Wikipedia** — constituents + GICS sector. Needs a browser User-Agent header
   (default urllib UA gets HTTP 403).
2. **Slickcharts** (`/sp500`) — index weight per ticker (tile size; ∝ market cap).
   One request instead of ~500 per-ticker `fast_info` calls. Weight column is
   `Portfolio%` (fallback `Weight`).
3. **yfinance** — one bulk `yf.download` of ~1 month daily closes + `^GSPC`
   (`auto_adjust=True`). Series/DoD/WoW/sector lines all derived from this.

## Gotchas
- Do NOT fetch market caps via per-ticker `Ticker.fast_info` in a loop — 500
  requests trips `YFRateLimitError`, which also kills the bulk price download in
  the same run. Slickcharts weight replaces that entirely.
- `fast_info` market cap is attribute `.market_cap` (snake_case); the dict key
  `.get("market_cap")` returns None — the dict key is `marketCap`.
- Tickers: convert `.`→`-` for yfinance (BRK.B→BRK-B). Wikipedia + Slickcharts
  both use `.`.
- Ticker `^GSPC` = the S&P 500 index (the dashed reference line).
- Color scale is **adaptive**: clamp = 92nd percentile of |DoD| across the index,
  so the gradient spans the day's actual spread (legend updates to match). Not a
  fixed ±3%.
- Browser preview pane serves stale static snapshots of `data.js` for files
  outside the project folder; to verify a fresh render, inline `data.js` into a
  throwaway `_preview.html` at a new path. Real browsers load it fine.

## Scope decisions
- Daily close only (no intraday).
- Sector sparkline is index-weight-weighted (matches tile sizing).
- This is a one-shot snapshot generator; rerun `fetch_data.py` to refresh.
