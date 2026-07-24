#!/usr/bin/env python3
"""S&P 500 treemap data pipeline (one-shot, low request count).

Three network calls total, to stay well clear of Yahoo rate limits:
  1. Wikipedia  -> constituents + GICS sector
  2. Slickcharts-> index weight (tile size; proportional to market cap)
  3. yfinance   -> one bulk download of ~1 month daily closes (+ ^GSPC)

Outputs data.js (window.SP500) consumed by index.html.
Daily closes are cached to closes.pkl so reruns don't refetch.
"""
import json, sys, os, datetime as dt
from io import StringIO
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

WIN_DAYS = 32
OUT = "data.js"
CACHE = "closes.pkl"
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
def get_closes(yf_tickers, use_cache=True):
    if use_cache and os.path.exists(CACHE):
        closes = pd.read_pickle(CACHE)
        if (dt.date.today() - closes.index[-1].date()).days <= 4:
            print(f"[prices] cache hit: {closes.shape}", file=sys.stderr)
            return closes
    end = dt.date.today() + dt.timedelta(days=1)
    start = end - dt.timedelta(days=WIN_DAYS)
    data = yf.download(yf_tickers + ["^GSPC"], start=start.isoformat(),
                       end=end.isoformat(), interval="1d", auto_adjust=True,
                       progress=False, threads=True)
    closes = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data
    closes = closes.dropna(how="all")
    if closes.shape[0] == 0:
        sys.exit("[prices] EMPTY download (rate limited?). Wait and rerun.")
    closes.to_pickle(CACHE)
    print(f"[prices] {closes.shape[0]} trading days, {closes.shape[1]} symbols", file=sys.stderr)
    return closes


# ---------------------------------------------------------------- build
def main():
    df = get_constituents()
    weights = get_weights()
    closes = get_closes(df["yf"].tolist())

    dates = [d.strftime("%Y-%m-%d") for d in closes.index]

    def norm(sym_series):
        s = sym_series.dropna()
        if len(s) < 2 or s.iloc[0] == 0:
            return None
        base = s.iloc[0]
        return [round(v / base - 1, 5) for v in s.reindex(closes.index).ffill().values]

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
        wow = (col.iloc[-1] / col.iloc[-6] - 1) * 100    # 5 trading days back
        w = weights.get(sym)
        s = norm(closes[sym])
        if s is None:
            continue
        stocks.append([sym, sec, round(price, 2),
                       round(float(w), 3) if pd.notna(w) else None,
                       round(dod, 2), round(wow, 2)])
        series[sym] = s
        sector_members.setdefault(sec, []).append((sym, float(w) if pd.notna(w) else 0.0))

    # weight-weighted sector series (equal-weight fallback)
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
        "asOf": dates[-1],
        "window": f"{len(dates)} trading days (daily close)",
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dates": dates,
        "stocks": stocks,
        "series": series,
        "sectorSeries": sector_series,
        "spxSeries": norm(closes["^GSPC"]),
    }
    with open(OUT, "w") as f:
        f.write("window.SP500 = ")
        json.dump(payload, f, separators=(",", ":"))
        f.write(";\n")
    withw = sum(1 for s in stocks if s[3])
    print(f"[done] {len(stocks)} stocks ({withw} with weight) -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
