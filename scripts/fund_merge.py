"""Merge fundamentals fetched from StockScans into data/fund/stocks.json (run by the evening Claude task).

Input file (JSON), one entry per stock fetched:
  {"KEY": {"n": "Company name", "sec": "StockScans Sector", "m": {"ROCE": 24.2, "Debt To Equity": 0.27, ...}}, ...}
  KEY is the "key" from fund_targets.py. Values are plain numbers (strip %, commas, Rs Cr); missing = null.
  Stocks StockScans could not find can be listed as {"KEY": null}; they are remembered so they are not retried for 7 days.

Output: data/fund/stocks.json = {"asOf": date, "metrics": [...], "s": {KEY: {"d": date, "n", "sec", "m": [values in METRICS order]}}}
Usage: python scripts/fund_merge.py work.json
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fund_targets import FUND, METRICS  # noqa: E402

KEEP_DAYS = 60


def num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = re.sub(r"[^0-9.\-]", "", str(v))
    try:
        return float(t) if t not in ("", "-", ".") else None
    except ValueError:
        return None


def main(path):
    with open(path) as f:
        new = json.load(f)
    data = {"s": {}}
    if os.path.exists(FUND):
        with open(FUND) as f:
            data = json.load(f)
    today = dt.date.today().isoformat()
    S = data.get("s", {})
    added = missing = 0
    for key, e in new.items():
        key = re.sub(r"-SM$", "", str(key))
        if not e:
            S[key] = {"d": today, "n": "", "sec": "", "m": None}
            missing += 1
            continue
        m = e.get("m") or {}
        old = S.get(key) or {}
        prev = dict(zip(old.get("metrics_order") or METRICS, old.get("m") or [])) if old.get("m") else {}
        vals = [num(m[k]) if k in m else prev.get(k) for k in METRICS]  # a metric not fetched this time keeps its saved value
        S[key] = {"d": today if len(m) >= len(METRICS) - 1 else old.get("d", today), "n": e.get("n") or old.get("n", ""),
                  "sec": e.get("sec") or old.get("sec", ""), "m": vals}
        added += 1
    cut = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    S = {k: v for k, v in S.items() if v.get("d", "") >= cut}
    os.makedirs(os.path.dirname(FUND), exist_ok=True)
    with open(FUND, "w") as f:
        json.dump({"asOf": today, "metrics": METRICS, "s": S}, f, separators=(",", ":"))
    print(f"fund: {added} stocks saved, {missing} not found, {len(S)} on file")


if __name__ == "__main__":
    main(sys.argv[1])
