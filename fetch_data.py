#!/usr/bin/env python3
"""S&P 500 treemap data pipeline (one-shot, low request count).

Three network calls total, to stay well clear of Yahoo rate limits:
  1. Wikipedia  -> constituents + GICS sector
  2. Slickcharts-> index weight (tile size; proportional to market cap)
  3. yfinance   -> one bulk download of ~8 months daily closes (+ ^GSPC, ^IRX)

From that one download we compute, per stock:
  - price, DoD %, WoW %                 (tail of the series)
  - a ~1-month normalized sparkline     (last SPARK_N trading days)
  - 3m / 6m annualized Sharpe ratio     (daily excess returns, x sqrt(252))
  - 6m annualized volatility %          (daily returns, x sqrt(252))
Risk-free rate = latest ^IRX (13-week T-bill) yield; falls back to 0.

Outputs data.js (window.SP500) consumed by the treemap pages.
Daily closes are cached to closes.pkl so reruns don't refetch.

Everything is gated on market_calendar.latest_us_session() — the cache expires
against it and downloaded bars are truncated to it, so a run during US market
hours can never record an intraday quote as a close.
"""
import json, sys, os, datetime as dt
from io import StringIO
from math import sqrt
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

from market_calendar import latest_us_session

HIST_DAYS = 260      # calendar days to pull (~176 trading days; covers 6m + buffer)
SPARK_N   = 22       # trading days in the tooltip sparkline (~1 month)
W3, W6    = 63, 126  # trading-day windows for 3m / 6m
ANN       = 252      # trading days per year
OUT       = "data.js"
CACHE     = "closes.pkl"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"


def fetch(url):
    return urlopen(Request(url, headers={"User-Agent": UA}), timeout=30).read().decode()


# ---------------------------------------------------------------- constituents
def get_constituents():
    html = fetch("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    df = pd.read_html(StringIO(html))[0][["Symbol", "GICS Sector"]].copy()
    df.columns = ["ticker", "sector"]
    df["yf"] = df["ticker"].str.replace(".", "-", regex=False)  # BRK.B -> BRK-B
    df = df.drop_duplicates("yf").reset_index(drop=True)
    print(f"[constituents] {len(df)} tickers", file=sys.stderr)
    return df


# ---------------------------------------------------------------- weights
def get_weights():
    """Slickcharts S&P 500 -> {yf_symbol: index weight %}. One request."""
    html = fetch("https://www.slickcharts.com/sp500")
    tbl = pd.read_html(StringIO(html))[0]
    sym = tbl["Symbol"].astype(str).str.replace(".", "-", regex=False)
    wt = (tbl["Portfolio%"] if "Portfolio%" in tbl.columns else tbl["Weight"])
    wt = pd.to_numeric(wt.astype(str).str.replace("%", "").str.strip(), errors="coerce")
    weights = dict(zip(sym, wt))
    print(f"[weights] {sum(pd.notna(v) for v in weights.values())} resolved", file=sys.stderr)
    return weights


# ---------------------------------------------------------------- prices
def get_closes(yf_tickers, cutoff, use_cache=True):
    """Daily closes through `cutoff` (the latest completed NYSE session).

    The cache is reused only when it already holds `cutoff` — never on a
    wall-clock day count, which says nothing about whether a session closed.
    Downloaded rows are truncated to `cutoff` so an in-progress session's
    partial bar is never stored as that day's close.
    """
    if use_cache and os.path.exists(CACHE):
        closes = pd.read_pickle(CACHE)
        enough = closes.shape[0] >= W6 + 5
        if enough and closes.index[-1].date() >= cutoff:
            print(f"[prices] cache hit: {closes.shape} (through {closes.index[-1].date()})",
                  file=sys.stderr)
            return closes
    end = cutoff + dt.timedelta(days=1)
    start = end - dt.timedelta(days=HIST_DAYS)
    data = yf.download(yf_tickers + ["^GSPC", "^IRX"], start=start.isoformat(),
                       end=end.isoformat(), interval="1d", auto_adjust=True,
                       progress=False, threads=True)
    closes = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data
    closes = closes.dropna(how="all")
    closes = closes[closes.index.date <= cutoff]   # drop any in-progress session
    if closes.shape[0] == 0:
        sys.exit("[prices] EMPTY download (rate limited?). Wait and rerun.")
    if closes.index[-1].date() < cutoff:
        print(f"[prices] WARNING: upstream has no bar for {cutoff} "
              f"(latest {closes.index[-1].date()})", file=sys.stderr)
    closes.to_pickle(CACHE)
    print(f"[prices] {closes.shape[0]} trading days, {closes.shape[1]} symbols "
          f"(through {closes.index[-1].date()})", file=sys.stderr)
    return closes


def risk_free_daily(closes):
    """Latest ^IRX yield (percent) -> per-day risk-free. Falls back to 0."""
    try:
        irx = closes["^IRX"].dropna()
        ann = float(irx.iloc[-1]) / 100.0
        if not (0.0 <= ann <= 0.15):
            raise ValueError(f"implausible ^IRX {ann}")
        print(f"[rf] ^IRX {ann*100:.2f}% annual", file=sys.stderr)
        return ann / ANN
    except Exception as e:
        print(f"[rf] ^IRX unavailable ({e}); using rf=0", file=sys.stderr)
        return 0.0


# ---------------------------------------------------------------- build
def main():
    cutoff = latest_us_session()
    df = get_constituents()
    weights = get_weights()
    closes = get_closes(df["yf"].tolist(), cutoff)
    rf_d = risk_free_daily(closes)

    spark_idx = closes.index[-SPARK_N:]
    spark_dates = [d.strftime("%Y-%m-%d") for d in spark_idx]

    def spark(sym):
        s = closes[sym].reindex(spark_idx).ffill().bfill()
        if s.isna().all() or s.iloc[0] == 0:
            return None
        base = s.iloc[0]
        return [round(v / base - 1, 5) for v in s.values]

    def window_metrics(r_s, r_m, rf):
        """(sharpe, sortino, vol%, alpha%ann, beta) for aligned daily returns."""
        if len(r_s) < 20:
            return (None, None, None, None, None)
        sd = r_s.std(ddof=1)
        mean = r_s.mean()
        sharpe = float((mean - rf) / sd * sqrt(ANN)) if sd and pd.notna(sd) else None
        short = (r_s[r_s < rf] - rf)                       # downside vs rf target
        dd = sqrt(float((short ** 2).sum()) / len(r_s))
        sortino = float((mean - rf) / dd * sqrt(ANN)) if dd else None
        vol = float(sd * sqrt(ANN) * 100) if pd.notna(sd) else None
        ex_s, ex_m = r_s - rf, r_m - rf                    # CAPM regression vs S&P
        varm = ex_m.var(ddof=1)
        beta = float(ex_s.cov(ex_m) / varm) if varm else None
        alpha = float((ex_s.mean() - beta * ex_m.mean()) * ANN * 100) if beta is not None else None
        r = lambda v, n: (round(v, n) if v is not None else None)
        return (r(sharpe, 2), r(sortino, 2), r(vol, 1), r(alpha, 1), r(beta, 2))

    rets_all = closes.pct_change(fill_method=None)
    stocks, series, sector_members = [], {}, {}
    for _, row in df.iterrows():
        sym, sec = row["yf"], row["sector"]
        if sym not in closes.columns:
            continue
        col = closes[sym].dropna()
        if len(col) < 6:
            continue
        price = float(col.iloc[-1])
        dod = (col.iloc[-1] / col.iloc[-2] - 1) * 100
        wow = (col.iloc[-1] / col.iloc[-6] - 1) * 100          # 5 trading days back
        pair = rets_all[[sym, "^GSPC"]].dropna()               # align stock vs market
        n = len(pair)
        m3 = window_metrics(pair[sym].tail(W3), pair["^GSPC"].tail(W3), rf_d) if n >= 40 else (None,)*5
        m6 = window_metrics(pair[sym].tail(W6), pair["^GSPC"].tail(W6), rf_d) if n >= 80 else (None,)*5
        sh3, so3, v3, a3, b3 = m3
        sh6, so6, v6, a6, b6 = m6
        w = weights.get(sym)
        sp = spark(sym)
        if sp is None:
            continue
        # [tkr, sec, price, wt, dod, wow, sh3, sh6, so3, so6, a3, a6, b3, b6, v3, v6]
        stocks.append([sym, sec, round(price, 2),
                       round(float(w), 3) if pd.notna(w) else None,
                       round(dod, 2), round(wow, 2),
                       sh3, sh6, so3, so6, a3, a6, b3, b6, v3, v6])
        series[sym] = sp
        sector_members.setdefault(sec, []).append((sym, float(w) if pd.notna(w) else 0.0))

    # weight-weighted sector sparkline (equal-weight fallback)
    sector_series = {}
    for sec, members in sector_members.items():
        rows = [series[s] for s, _ in members if series.get(s)]
        wt = [w for s, w in members if series.get(s)]
        if not rows:
            continue
        n = len(rows[0]); tot = sum(wt)
        if tot <= 0:
            wt = [1.0] * len(rows); tot = float(len(rows))
        sector_series[sec] = [round(sum(rows[i][t] * wt[i] for i in range(len(rows))) / tot, 5)
                              for t in range(n)]

    payload = {
        "asOf": closes.index[-1].strftime("%Y-%m-%d"),
        "window": f"{closes.shape[0]} trading days history · daily close",
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "rfAnnualPct": round(rf_d * ANN * 100, 2),
        "dates": spark_dates,
        # [tkr, sec, price, wt, dod, wow, sh3, sh6, sortino3, sortino6, alpha3, alpha6, beta3, beta6, vol3, vol6]
        "stocks": stocks,
        "series": series,
        "sectorSeries": sector_series,
        "spxSeries": spark("^GSPC"),
    }
    with open(OUT, "w") as f:
        f.write("window.SP500 = ")
        json.dump(payload, f, separators=(",", ":"))
        f.write(";\n")
    withw = sum(1 for s in stocks if s[3])
    withsh = sum(1 for s in stocks if s[7] is not None)
    print(f"[done] {len(stocks)} stocks ({withw} w/ weight, {withsh} w/ 6m Sharpe) -> {OUT}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
