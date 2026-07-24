# S&P 500 Treemap

Finviz-style heatmap of the S&P 500. Tiles grouped by GICS sector, sized by
index weight. **Seven pages**, one shared engine: the default colours by day-over-day %
change; six analytical pages colour by risk-adjusted metrics (3m/6m Sharpe, Sortino, Alpha).
Tap a tile for a rich tooltip (3m/6m Sharpe/Sortino/Alpha/Beta/Vol grid + a ticker-vs-sector-
vs-S&P sparkline); tap a sector header to zoom in. Built as a Telegram Mini App.

## Files
- `fetch_data.py` — data pipeline. Writes `data.js`.
- `refresh.py` — orchestrator: fetch_data → render `sp500.png` → git push to Pages.
- `sp500_summary.py` — reads `data.js` → market DoD summary for the morning brief
  (`build_summary`, `caption_html`, `show_market_section` freshness gate). Imported
  in-process by ButlerPapa (SP500_DIR on sys.path); reuses `refresh.latest_us_session`.
- `treemap.js` + `treemap.css` — **shared rendering engine** used by all pages. A page
  sets `window.CHART=<metric key>` (+ optional `window.NAV=true`) before loading data.js +
  treemap.js. Engine handles: colour (adaptive diverging clamp), squarify layout, tap-to-pin
  tooltip (hover preview on desktop), sector drill-down (tap header → zoom, `‹ All sectors`
  back bar), Telegram SDK (`ready`/`expand`/`disableVerticalSwipes`/haptics — no-ops outside
  Telegram), and the nav pills. Metric registry `MET` maps key→tuple index+label+formatter.
- **Pages** (each a thin HTML that sets `window.CHART`):
  - `index.html` — DoD %, **no nav** (kept clean so the bot `sp500.png` is uncluttered).
  - `sharpe-3m/6m.html`, `sortino-3m/6m.html`, `alpha-3m/6m.html` — analytical views, `NAV=true`
    (nav pill row to switch between all 7).
- `data.js` — generated data (`window.SP500 = {...}`). **Stock tuple (16 fields):**
  `[tkr, sec, price, wt, dod, wow, sh3, sh6, sortino3, sortino6, alpha3, alpha6, beta3, beta6, vol3, vol6]`.
  Anything parsing it (e.g. `sp500_summary.py`) must use **index access**, not 6-tuple unpacking.
- `sp500.png` — rendered snapshot (gitignored; what the Telegram bot sends).
- `closes.pkl` — cached daily closes (gitignored; skips refetch if <4 days old).
- `mockup.html` — original standalone mockup with sample data (kept for reference).

## Hosting — GitHub Pages (Telegram Mini App)
- Repo: `jimmypwnage/sp500-treemap` (public). Live URL:
  **https://jimmypwnage.github.io/sp500-treemap/**
- Pages serves `index.html` + `data.js` from `main` branch root. Same URL always
  shows the latest data — no per-run files.
- This URL is opened as a Telegram **Mini App** via a `web_app` button in
  FinancePapa (`/sp500`). Telegram requires public HTTPS; Pages provides it.
- `git push` auth is via the `gh` credential helper (`gh auth setup-git`, done).

## Run
```bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
/Users/jimmyteoh/anaconda3/bin/python3 refresh.py            # guarded: skips if no new session
/Users/jimmyteoh/anaconda3/bin/python3 refresh.py --force    # ignore guard, always rebuild
/Users/jimmyteoh/anaconda3/bin/python3 fetch_data.py         # data only, no PNG/publish
open index.html
```

## Refresh triggers + market guard
- **Daily refresh lives in ButlerPapa** (`core/scheduler.py` job `sp500_refresh`, 06:30 SGT,
  just before the 7am brief). Registered via ButlerPapa's `_wrap`, so a genuine failure
  pings the owner automatically; a guard-skip is silent.
- **FinancePapa `/sp500`** only builds **on demand** when no `sp500.png` exists yet, and calls
  `refresh.py --force` so it always works (even on a weekend).
- **`should_refresh()`** computes the latest completed NYSE session (US/Eastern + `holidays`
  NYSE calendar) and compares to the `asOf` date already in `data.js`. If there's no newer
  session it **returns before any network call** — this covers weekends AND US holidays.
  Net effect on the 06:30 SGT schedule: refreshes **Tue–Sat SGT** (Mon–Fri US sessions),
  skips **Sun/Mon SGT** and the morning after a US holiday.
- `publish()` pushes only when `data.js` actually changed (no-op otherwise).
- `--force` (or `refresh(force=True)`) bypasses the guard — used by the on-demand build.
- Dep: `holidays` (`holidays.financial_holidays("NYSE")`) + stdlib `zoneinfo`.

## PNG rendering
Headless Chrome screenshots `index.html` (no Python deps): `--headless=new
--force-device-scale-factor=2 --window-size=1600,1000 --virtual-time-budget=6000`.
`file://` URL must percent-encode the spaces in the Google Drive path.

## Data sources (3 network calls — kept low to avoid Yahoo rate limits)
1. **Wikipedia** — constituents + GICS sector. Needs a browser User-Agent header
   (default urllib UA gets HTTP 403).
2. **Slickcharts** (`/sp500`) — index weight per ticker (tile size; ∝ market cap).
   One request instead of ~500 per-ticker `fast_info` calls. Weight column is
   `Portfolio%` (fallback `Weight`).
3. **yfinance** — one bulk `yf.download` of **~8 months** daily closes + `^GSPC` + `^IRX`
   (`auto_adjust=True`). Everything below is derived from this one download.

## Chart metrics (per stock, from daily returns)
All tiles are sized by index weight; each page colours by one metric (diverging red↔green at 0,
adaptive 92nd-pct clamp). Windows: **3m = last 63 trading days, 6m = 126**. Annualized ×√252.
Risk-free = latest **^IRX** (13-week T-bill) yield → `rf_daily = IRX/100/252` (falls back to 0).
- **Sharpe** = `mean(r − rf) / std(r) × √252`.
- **Sortino** = `mean(r − rf) / downside_dev × √252`, `downside_dev = sqrt(mean(min(0, r−rf)²))`.
- **Alpha** (CAPM/Jensen, vs ^GSPC) = regression intercept of daily excess returns, ×252 → % ann.
  **Beta** = the regression slope (shown in tooltip, not its own page).
- **Volatility** = `std(r) × √252` %, shown in the tooltip (3m + 6m).
- DoD/WoW + the ~1-month sparkline (`SPARK_N=22`) come from the tail of the same series.
Tooltip shows a 3m/6m grid of all five metrics; the current page's metric row is highlighted.
`fetch_data.py`: `HIST_DAYS`, `W3/W6`, `SPARK_N`, `window_metrics()` are the knobs.

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
