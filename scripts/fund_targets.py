"""List the stocks that need fundamentals from StockScans (run by the evening Claude task, not by GitHub).

Universe (a superset of what the dashboard shows, so every final stock is covered):
  - weekly sheet stocks that can pass the strong-stock rule (MasterScore A/B, EPS 80+, price strength 80+, demand B+)  -> Strong 25
  - every stock on the newest daily VCP sheet (mainboard and SME)                                            -> VCP setups, Confluence
  - delivery-thrusting A/B stocks in early-inflow or confirmed groups from data/flow/latest.json             -> Confluence watchlist
A stock is listed when it has no saved fundamentals, they are older than MAX_AGE days, or they lack metrics added later.

Output (stdout, JSON): {"metrics": [...], "targets": [{"key", "q", "name", "why"}]}
  key = the id the dashboard uses (NSE symbol, or BSE code for BSE-only stocks)
  q   = what to pass to StockScans getRatios: the NSE symbol, or the company name for BSE codes
Usage: python scripts/fund_targets.py [--all]
"""
import datetime as dt
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUND = os.path.join(ROOT, "data", "fund", "stocks.json")
MAX_AGE = 7
BD = {"A+": 13, "A": 12, "A-": 11, "B+": 10}  # buyer demand B+ or better, as in the strong-stock rule

# exact StockScans metric names (max 40 per getRatios call with Sector), in the order the dashboard reads them (keep in sync with FUNDM in index.html)
METRICS = ["ROCE", "ROE", "Debt To Equity", "Interest Coverage", "Revenue Growth YoY", "PAT Growth YoY",
           "EPS Growth 3 Years", "CFO To PAT", "Promoter Holdings", "Change In Promoter Holdings 1 Year",
           "Pledged Percentage", "Change In FII Holdings Latest Quarter", "Change In DII Holdings Latest Quarter",
           "Price To Earnings", "Industry PE Median", "PEG", "PAT", "Operating Cash Flow",
           # forward checks: peak margin, direction, what is priced in
           "OPM", "OPM Median 5 Years", "OPM Latest Quarter", "OPM Preceding Year Quarter",
           "Revenue Latest Quarter", "Revenue Preceding Year Quarter", "Revenue Growth 3 Years",
           "PAT Latest Quarter", "PAT Preceding Year Quarter", "CWIP", "Fixed Assets",
           "Price To Earnings Median 5 Years", "Days Receivable", "Days Receivable 1 Year Back"]


def newest(pattern):
    files = sorted(f for f in glob.glob(pattern) if re.search(r"\d{4}-\d{2}-\d{2}\.json$", f))
    if not files:
        return None
    with open(files[-1]) as f:
        return json.load(f)


def main():
    wk = newest(os.path.join(ROOT, "data", "weeks", "*.json")) or {"stocks": []}
    names = {str(s[1]): s[2] for s in wk["stocks"]}
    grade = {str(s[1]): s[4] for s in wk["stocks"]}
    want = {}

    def add(key, why, name=None):
        key = re.sub(r"-SM$", "", str(key))
        e = want.setdefault(key, {"key": key, "name": name or names.get(key, ""), "why": []})
        if why not in e["why"]:
            e["why"].append(why)

    for s in wk["stocks"]:
        ms, eps, rs, bd = s[4], s[5], s[6], s[7]
        if ms in ("A", "B") and (eps or 0) >= 80 and (rs or 0) >= 80 and bd in BD and "etf" not in s[0]:
            add(s[1], "strong")
    v = newest(os.path.join(ROOT, "data", "vcp", "*.json"))
    if v:
        for r in v.get("main", []) + v.get("sme", []):
            add(r.get("code") or r["sym"], "vcp", r.get("name"))
    try:
        with open(os.path.join(ROOT, "data", "flow", "latest.json")) as f:
            fl = json.load(f)
        good = {g["k"] for g in fl["groups"] if g["q"] in ("lead", "confirmed")}
        sym2g = {str(s[1]): s[0] for s in wk["stocks"]}
        for sym, x in (fl.get("stk") or {}).items():
            if x[5] and sym2g.get(sym) in good and grade.get(sym) in ("A", "B"):
                add(sym, "flow")
    except (OSError, ValueError, KeyError):
        pass

    have = {}
    if os.path.exists(FUND):
        with open(FUND) as f:
            have = json.load(f).get("s", {})
    cut = (dt.date.today() - dt.timedelta(days=MAX_AGE)).isoformat()
    out = []
    for key, e in sorted(want.items()):
        h = have.get(key)
        fresh = h and h.get("d", "") >= cut and (h.get("m") is None or len(h["m"]) >= len(METRICS))
        if "--all" not in sys.argv and fresh:
            continue
        e["q"] = e["name"] if key.isdigit() and e["name"] else key
        out.append(e)
    json.dump({"metrics": METRICS, "universe": len(want), "targets": out}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
