"""
scripts/series_redundancy_test.py
=================================
Преизползваем тест: носи ли една серия НЕЗАВИСИМА стойност, или дублира друга?

Произход: ZHVI vs Case-Shiller проверка (2026-06-08). Виж
docs/decisions/ZHVI-retirement-2026-06-08.md за изводите от онзи конкретен run.

Pre-registered gates:
  1. Дублиране    — YoY corr candidate↔reference. >0.95 = огледало.
  2. Лаг/лидерство — крос-корелация на MoM импулса (lags -6..+6). k>0 => candidate води.
  3. Смутинг      — MoM std. candidate ≪ reference = изглажда волатилността.
  4. Обрати       — пик/дъно на YoY в зададен прозорец, кой пръв.
  5. Остатък      — R² на регресия candidate~reference + структура на остатъка.

Usage:
  python scripts/series_redundancy_test.py --candidate CSUSHPISA --reference SPCS20RSA,USSTHPI
  python scripts/series_redundancy_test.py --candidate path/to/series.csv --reference CSUSHPISA
    (CSV формат: две колони date,value; или Zillow-style cache JSON с {key:{history:{date:val}}})

Без API ключ — FRED public CSV (fredgraph.csv). ASCII-safe изход (Windows конзола).
"""
from __future__ import annotations

import argparse
import io
import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"


def _month_end(s: pd.Series) -> pd.Series:
    s = s.copy()
    s.index = pd.to_datetime(s.index) + pd.offsets.MonthEnd(0)
    return s[~s.index.duplicated(keep="last")].sort_index()


def fetch_fred(series_id: str, timeout: int = 60) -> pd.Series:
    req = urllib.request.Request(
        FRED_CSV.format(id=series_id), headers={"User-Agent": "Mozilla/5.0 redundancy-test"}
    )
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
    df = pd.read_csv(io.StringIO(raw))
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return _month_end(df.set_index("date")["value"].dropna())


def load_local(path: str) -> pd.Series:
    p = Path(path)
    if p.suffix.lower() == ".json":
        obj = json.load(open(p, encoding="utf-8"))
        # Zillow-style: {KEY: {"history": {date: val}}} — взима първия ключ
        entry = next(iter(obj.values()))
        hist = entry.get("history", entry)
        return _month_end(pd.Series({k: float(v) for k, v in hist.items()}))
    df = pd.read_csv(p)
    df = df.iloc[:, :2]
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return _month_end(df.set_index("date")["value"].dropna())


def get_series(spec: str) -> pd.Series:
    return load_local(spec) if ("/" in spec or "\\" in spec or "." in spec) else fetch_fred(spec)


def yoy(s):
    return (s / s.shift(12) - 1.0) * 100


def mom(s):
    return (s / s.shift(1) - 1.0) * 100


def xcorr(a, b, lags):
    return {k: a.corr(b.shift(-k)) for k in lags}  # a[t] vs b[t+k]; k>0 => a води b


def run(candidate: str, refs: list[str], peak_window=("2020-01-01", "2024-12-31")) -> None:
    cand = get_series(candidate)
    series = {"CAND": cand}
    for r in refs:
        series[r] = get_series(r)

    print("=" * 64)
    print(f"  Redundancy test:  CAND={candidate}  vs  {', '.join(refs)}")
    print("=" * 64)
    for name, s in series.items():
        print(f"  {name:10s} n={len(s):4d}  {s.index[0].date()}..{s.index[-1].date()}  last={s.iloc[-1]:,.2f}")

    Y = pd.DataFrame({k: yoy(v) for k, v in series.items()}).dropna()
    M = pd.DataFrame({k: mom(v) for k, v in series.items()}).dropna()
    print(f"\n  Common YoY window: {Y.index[0].date()}..{Y.index[-1].date()} (n={len(Y)})")

    print("\n[1] YoY correlation:")
    print(Y.corr().round(4).to_string())

    print("\n[3] MoM std (smoothing):")
    for k in series:
        print(f"    {k:10s} std={M[k].std():.3f}")

    primary = refs[0]
    print(f"\n[2] Cross-corr  CAND_MoM[t] vs {primary}_MoM[t+k]  (k>0 => CAND води):")
    xm = xcorr(M["CAND"], M[primary], range(-6, 7))
    best = max(xm, key=lambda k: xm[k])
    for k in range(-6, 7):
        print(f"    k={k:+d} corr={xm[k]:+.3f}" + ("  <== max" if k == best else ""))
    print(f"    >>> best lag k*={best:+d}")

    print(f"\n[4] Turning points YoY ({peak_window[0]}..{peak_window[1]}):")
    win = Y.loc[peak_window[0]:peak_window[1]]
    for k in series:
        pk = win[k].idxmax(); tr = win.loc[pk:][k].idxmin()
        print(f"    {k:10s} peak={pk.date()} ({win.loc[pk,k]:+.1f}%)  trough={tr.date()} ({win.loc[tr,k]:+.1f}%)")

    x = Y[primary].values; y = Y["CAND"].values
    A = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = pd.Series(y - A @ coef, index=Y.index)
    r2 = 1 - (resid**2).sum() / ((y - y.mean()) ** 2).sum()
    print(f"\n[5] CAND ~ a*{primary}+b:  R2={r2:.4f}  resid_std={resid.std():.3f}")
    print("    largest |resid|:")
    for ts, v in resid.reindex(resid.abs().sort_values(ascending=False).index).head(5).items():
        print(f"      {ts.date()} {v:+.2f}pp")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Series redundancy / lead-lag test")
    ap.add_argument("--candidate", required=True, help="FRED id или path (csv/json)")
    ap.add_argument("--reference", required=True, help="comma-separated FRED ids/paths (1-ви = primary)")
    a = ap.parse_args()
    run(a.candidate, [r.strip() for r in a.reference.split(",") if r.strip()])
