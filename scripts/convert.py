"""Convert weekly NovaWealth 'Ranked Sector List' workbooks in uploads/ into JSON
for the dashboard (data/weeks/<date>.json) and rebuild data/index.json.

Run from the repo root:  python scripts/convert.py
Mirrors parseWorkbook() and build() in index.html, so the website and this
script always agree on scores and segments.
"""
import datetime as dt
import glob
import json
import os
import re

import openpyxl
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS = os.path.join(ROOT, "uploads")
WEEKS = os.path.join(ROOT, "data", "weeks")
INDEX = os.path.join(ROOT, "data", "index.json")


def clean(s):
    return re.sub(r"\s+IN$", "", str(s or ""))


def key(s):
    return re.sub(r"[^a-z0-9]", "", clean(s).lower())


def num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    m = re.sub(r"[^0-9.\-]", "", str(v if v is not None else ""))
    try:
        return float(m)
    except ValueError:
        return None


def text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def parse(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    fname = os.path.basename(path)
    date = None
    m = re.search(r"(\d{2})[_\-.](\d{2})[_\-.](\d{4})", fname)
    if m:
        date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    groups, stocks = [], []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        for r in rows[:4]:
            d = re.search(r"as of (\d{2})-(\d{2})-(\d{4})", " ".join(text(c) for c in r), re.I)
            if d and not date:
                date = f"{d.group(3)}-{d.group(2)}-{d.group(1)}"
        hi = next((i for i, r in enumerate(rows) if "IndustryGroupRankCurrent" in r), -1)
        if hi >= 0:
            h = rows[hi]
            ix = lambda k: h.index(k)
            for r in rows[hi + 1:]:
                r = r + [None] * (len(h) - len(r))
                name, R = r[ix("IndustryGroupName")], num(r[ix("IndustryGroupRankCurrent")])
                if not name or R is None:
                    continue
                groups.append({
                    "name": clean(name), "sym": r[ix("Symbol")], "n": num(r[ix("NumberOfStocks")]) or 0,
                    "R": R, "W": num(r[ix("IndustryGroupRankLastWeek")]),
                    "M3": num(r[ix("IndustryGroupRankLast3MonthAgo")]), "M6": num(r[ix("IndustryGroupRankLast6MonthAgo")]),
                    "ytd": num(r[ix("PricePercentChangeYTD")]), "cap": num(r[ix("MarketCapital")]),
                })
            continue
        si = next((i for i, r in enumerate(rows) if "Symbol" in r and "MasterScore" in r), -1)
        if si >= 0:
            h = rows[si]
            ix = lambda k: h.index(k)
            for r in rows[si + 1:]:
                r = r + [None] * (len(h) - len(r))
                sy = r[ix("Symbol")]
                if sy is None or sy == "":
                    continue
                stocks.append([
                    key(r[ix("IndustryGroupName")] or ws.title), text(sy), r[ix("CompanyName")] or "",
                    num(r[ix("MarketCapital")]), text(r[ix("MasterScore")]), num(r[ix("EPSRank")]),
                    num(r[ix("PriceStrength")]), text(r[ix("BuyerDemand")]), num(r[ix("Price")]),
                    num(r[ix("PricePercChange")]),
                ])
    if not groups:
        raise ValueError(f"{fname}: no sheet with an IndustryGroupRankCurrent column")
    if not date:
        date = dt.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    return {"date": date, "file": fname, "groups": groups, "stocks": stocks}


def segment(R, W, M3, M6):
    if max(R, W, M3, M6) <= 45:
        return "L"
    if R <= 45 and M6 - R >= 60:
        return "E"
    if M3 >= 120 and M6 >= 120 and M3 - R >= 15 and W > R:
        return "T"
    best = min(W, M3, M6)
    if best <= 45 and R - best >= 40:
        return "F"
    return "R"


BD = {"A+": 13, "A": 12, "A-": 11, "B+": 10, "B": 9, "B-": 8, "C+": 7, "C": 6, "C-": 5, "D+": 4, "D": 3, "D-": 2, "E": 1}


def summarise(raw):
    """Per-week summary used for week-on-week changes and conviction streaks."""
    G = raw["groups"]
    N = len(G)
    for g in G:
        g["k"] = key(g["name"])
        g["score"] = round((.4 * (N + 1 - g["R"]) + .35 * (g["M3"] - g["R"]) + .15 * (g["M6"] - g["R"]) + .1 * (g["W"] - g["R"])) * 10) / 10
    for i, g in enumerate(sorted(G, key=lambda g: (-g["score"], g["R"]))):
        g["mr"] = i + 1
    by = {g["k"]: g for g in G}
    picks = []
    for s in raw["stocks"]:
        g = by.get(s[0])
        if not g:
            continue
        ms, eps, rs, bd = s[4], s[5] or 0, s[6] or 0, BD.get(s[7], 0)
        if ms in ("A", "B") and eps >= 80 and rs >= 80 and bd >= 10 and g["mr"] <= 25 and g["n"] > 3 and s[1] not in picks:
            picks.append(s[1])
    br = {}
    for g in G:
        st = [s for s in raw["stocks"] if s[0] == g["k"]]
        if st:
            br[g["k"]] = round(100 * sum(1 for s in st if (s[6] or 0) >= 70) / len(st))
    return {
        "date": raw["date"], "file": raw.get("file"), "groups": N,
        "segs": {g["k"]: segment(g["R"], g["W"], g["M3"], g["M6"]) for g in G},
        "mr": {g["k"]: g["mr"] for g in G},
        "R": {g["k"]: g["R"] for g in G},
        "W": {g["k"]: g["W"] for g in G},
        "br": br,
        "picks": picks,
    }


def median(v):
    v = sorted(v)
    n = len(v)
    return None if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


def scorecard(prev_raw, prev_picks, raw):
    """How last week's shortlist did by this week's sheet, against every stock.
    Price moves beyond +/-40% in a week are skipped as likely splits or bonus issues."""
    p0 = {s[1]: s[8] for s in prev_raw["stocks"] if s[8]}
    ret = {}
    for s in raw["stocks"]:
        a = p0.get(s[1])
        if a and s[8]:
            r = (s[8] / a - 1) * 100
            if abs(r) <= 40:
                ret[s[1]] = round(r, 2)
    pr = [(sym, ret[sym]) for sym in prev_picks if sym in ret]
    if not pr:
        return None
    mkt = median(list(ret.values()))
    vals = [r for _, r in pr]
    return {
        "from": prev_raw["date"], "n": len(pr),
        "pick_med": round(median(vals), 2), "pick_mean": round(sum(vals) / len(vals), 2),
        "mkt_med": round(mkt, 2), "beat": round(100 * sum(1 for r in vals if r > mkt) / len(vals)),
        "ret": dict(pr),
    }


VCPDIR = os.path.join(ROOT, "data", "vcp")
VCOLS = {"Rank": "rk", "Symbol": "sym", "Exchange": "ex", "Close (₹)": "close", "ADR %": "adr", "% from 52w High": "hi",
         "20d Value (Cr)": "val", "RS 63d %": "rs", "Inside Day": "inside", "Sector": "sector", "Industry": "industry"}


def is_vcp(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    names = set(wb.sheetnames)
    wb.close()
    return "Mainboard" in names and "SME" in names


def parse_vcp(path):
    """Daily VCP setup sheet -> {date, main:[...], sme:[...]}; 'code' is the key into the sector sheet."""
    fname = os.path.basename(path)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", fname) or re.search(r"(\d{2})[_\-.](\d{2})[_\-.](\d{4})", fname)
    if m:
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if len(m.group(1)) == 4 else f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    else:
        date = dt.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    wb = openpyxl.load_workbook(path, data_only=True)
    out = {"date": date, "file": fname}
    for sheet, key in (("Mainboard", "main"), ("SME", "sme")):
        ws = wb[sheet]
        head = [c.value for c in ws[1]]
        rows = []
        for r in ws.iter_rows(min_row=2):
            if r[0].value is None or r[1].value is None:
                continue
            o = {}
            for i, h in enumerate(head):
                if h in VCOLS:
                    v = r[i].value
                    o[VCOLS[h]] = v if not isinstance(v, str) else v.strip()
                if h == "Screener" and r[i].hyperlink is not None:
                    o["code"] = r[i].hyperlink.target.rstrip("/").split("/")[-1]
            o["inside"] = str(o.get("inside") or "").lower().startswith("y")
            o.setdefault("code", re.sub(r"-SM$", "", str(o["sym"])))
            rows.append(o)
        out[key] = rows
    return out


def main():
    os.makedirs(WEEKS, exist_ok=True)
    os.makedirs(VCPDIR, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(UPLOADS, "*.xls*"))):
        if is_vcp(path):
            v = parse_vcp(path)
            with open(os.path.join(VCPDIR, v["date"] + ".json"), "w") as f:
                json.dump(v, f, separators=(",", ":"), default=str)
            print(f"{os.path.basename(path)} -> data/vcp/{v['date']}.json ({len(v['main'])} mainboard, {len(v['sme'])} SME)")
            continue
        raw = parse(path)
        out = os.path.join(WEEKS, raw["date"] + ".json")
        with open(out, "w") as f:
            json.dump(raw, f, separators=(",", ":"))
        print(f"{os.path.basename(path)} -> data/weeks/{raw['date']}.json "
              f"({len(raw['groups'])} groups, {len(raw['stocks'])} stocks)")
    index, prev = [], None
    for out in sorted(glob.glob(os.path.join(WEEKS, "*.json"))):
        with open(out) as f:
            raw = json.load(f)
        entry = summarise(raw)
        if prev:
            entry["sc"] = scorecard(prev[0], prev[1]["picks"], raw)
        index.append(entry)
        prev = (raw, entry)
    if os.environ.get("SKIP_LIQUIDITY") != "1":
        import liquidity
        for e in index:
            e["liq"] = liquidity.ensure(e["date"])
    else:
        for e in index:
            e["liq"] = os.path.exists(os.path.join(ROOT, "data", "liq", e["date"] + ".json"))
    with open(INDEX, "w") as f:
        json.dump(index, f, separators=(",", ":"))
    vidx = []
    for out in sorted(glob.glob(os.path.join(VCPDIR, "????-??-??.json"))):
        with open(out) as f:
            v = json.load(f)
        vidx.append({"date": v["date"], "main": [r["code"] for r in v["main"]], "sme": [r["code"] for r in v["sme"]],
                     "close": {r["code"]: r.get("close") for r in v["main"] + v["sme"]}})
    with open(os.path.join(VCPDIR, "index.json"), "w") as f:
        json.dump(vidx, f, separators=(",", ":"))
    print(f"data/vcp/index.json: {len(vidx)} day(s)")
    print(f"data/index.json: {len(index)} week(s)")


if __name__ == "__main__":
    main()
