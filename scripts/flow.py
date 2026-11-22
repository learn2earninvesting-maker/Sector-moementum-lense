"""Liquidity flow: which industry groups delivery-based money is moving into, before price confirms it.

Data: NSE's daily "sec_bhavdata_full" file (the same one liquidity.py already caches in data/liq/raw/).
Only DELIVERED quantity is used, never total traded volume, so intraday and high-frequency round trips
(buy and sell the same day, zero delivery) add nothing. Only the EQ series is used: BE/BZ (trade-for-trade)
are 100% delivery by rule and SME boards are too thin, so both would distort the signal.

Groups: each stock's NovaWealth industry group, taken from the latest weekly sheet in data/weeks/.
ETF groups are left out. Stocks trading under Rs 2.5 Cr a day (20-session average) are left out.

For each stock, on each session (recent = last 10 sessions, base = the 40 sessions before them):
  delivery value  = delivered qty x average traded price (Rs Cr)
  thrust          = recent avg delivery value >= 1.3 x base avg, AND price up over the 10 sessions,
                    AND delivery % not more than 5 pts below its base (else it is a volume spike, not accumulation)
  up-day share    = share of recent delivery value delivered on up-close days
  delivery % shift= delivered/traded qty, recent minus base (percentage points)
  above 50D       = close above its 50-session average (split-safe, from daily % changes)

Group Flow Score (0-100) = 35% thrust breadth (40% of members thrusting = full marks)
                         + 30% group delivery value, recent vs base (0.9x = 0, 1.6x = full)
                         + 20% up-day share of delivery (45% = 0, 75% = full)
                         + 15% delivery % shift (-4 pts = 0, +4 pts = full)
Price Score = % of the group's stocks above their 50-session average.

Reading:  Flow >= 60 and Price < 50  -> "Early inflow" (the lead signal)
          Flow >= 60 and Price >= 50 -> "Confirmed"
          Price >= 60 and group delivery value under 0.85x its base -> "Leaders losing flow"
          else                       -> "Neutral"

Track record: for every past session, groups flagged Early inflow are compared with all groups over the
next 20 sessions (equal-weight returns). Builds up automatically as history accumulates.

Writes data/flow/latest.json and data/flow/history.json.  Run:  python scripts/flow.py
FLOW_OFFLINE=1 uses only cached files (for testing).
"""
import csv
import datetime as dt
import glob
import io
import json
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import liquidity  # noqa: E402  (shared download helpers and cache folder)

ROOT = liquidity.ROOT
OUT = os.path.join(ROOT, "data", "flow")
WEEKS = os.path.join(ROOT, "data", "weeks")
LOOKBACK_DAYS = 135          # calendar days of files; liquidity.prune_raw keeps 140
RECENT, BASE = 10, 40        # sessions
NEED = RECENT + BASE         # sessions of history needed before a day can be scored
FWD = 20                     # sessions ahead for the track record
MIN_TV = 2.5                 # Rs Cr per day, 20-session average traded value
THRUST = 1.3
KEEP_HISTORY = 260           # sessions kept in history.json


def num(v):
    try:
        v = str(v).strip().replace(",", "")
        return None if v in ("", "-") else float(v)
    except ValueError:
        return None


def parse_day(text):
    """SYMBOL -> (close, prev_close, avg_price, traded_qty, delivered_qty, turnover Rs Cr). EQ series only."""
    out = {}
    rows = csv.reader(io.StringIO(text))
    try:
        head = [h.strip().upper() for h in next(rows)]
    except StopIteration:
        return out
    ix = {h: i for i, h in enumerate(head)}
    need = ("SYMBOL", "SERIES", "PREV_CLOSE", "CLOSE_PRICE", "AVG_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS", "DELIV_QTY")
    if not all(k in ix for k in need):
        return out
    for r in rows:
        if len(r) < len(head) or r[ix["SERIES"]].strip().upper() != "EQ":
            continue
        c, p, a = num(r[ix["CLOSE_PRICE"]]), num(r[ix["PREV_CLOSE"]]), num(r[ix["AVG_PRICE"]])
        q, d, t = num(r[ix["TTL_TRD_QNTY"]]), num(r[ix["DELIV_QTY"]]), num(r[ix["TURNOVER_LACS"]])
        if not (c and p and a and q) or d is None or t is None:
            continue
        out[r[ix["SYMBOL"]].strip()] = (c, p, a, q, d, t / 100.0)
    return out


def load_days(end):
    """Parsed NSE files, oldest -> newest, for trading days in the lookback window."""
    offline = os.environ.get("FLOW_OFFLINE") == "1"
    s = None if offline or liquidity.requests is None else liquidity._session()
    days, data = [], []
    for back in range(LOOKBACK_DAYS):
        day = end - dt.timedelta(days=back)
        if day.weekday() >= 5:
            continue
        cache = os.path.join(liquidity.RAW, f"nse_{day:%Y%m%d}.csv")
        if offline or s is None:
            text = open(cache, encoding="utf-8", errors="ignore").read() if os.path.exists(cache) else None
        else:
            fresh = not os.path.exists(cache)
            text = liquidity._get(s, f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv",
                                  "https://www.nseindia.com/all-reports", cache)
            if fresh:
                time.sleep(0.3)
        if not text:
            continue  # holiday, not yet published, or unreachable
        parsed = parse_day(text)
        if len(parsed) < 200:
            continue  # not a real bhavcopy
        days.append(day.isoformat())
        data.append(parsed)
    days.reverse()
    data.reverse()
    return days, data


def group_map():
    """NSE symbol -> group key, group key -> {name, R}, from the latest weekly sheet."""
    files = sorted(glob.glob(os.path.join(WEEKS, "*.json")))
    if not files:
        return {}, {}, None
    with open(files[-1]) as f:
        wk = json.load(f)
    from convert import key, clean
    groups = {}
    for g in wk["groups"]:
        groups[key(g["name"])] = {"name": clean(g["name"]), "R": g.get("R")}
    sym2g, names = {}, {}
    for s in wk["stocks"]:
        gk, sym = s[0], str(s[1])
        name = groups.get(gk, {}).get("name", "")
        if sym.isdigit() or "etf" in gk or "ETF" in name.upper().split("-")[-1]:
            continue
        sym2g[sym] = gk
        names[sym] = s[2]
    return sym2g, groups, {"date": wk["date"], "names": names}


def clip(x):
    return max(0.0, min(100.0, x))


def mean(v):
    return sum(v) / len(v) if v else None


def score_series(days, data, sym2g):
    """Per-symbol aligned arrays, then group metrics for every scorable session."""
    n = len(days)
    syms = [s for s in sym2g if any(s in d for d in data[-RECENT:])]
    A = {}
    for s in syms:
        rows = [d.get(s) for d in data]
        chg = [None if r is None else r[0] / r[1] - 1 for r in rows]
        lvl, v = [], 1.0
        for c in chg:
            if c is not None:
                v *= 1 + c
            lvl.append(v)  # split-safe price index
        A[s] = {"r": rows, "chg": chg, "lvl": lvl,
                "dv": [None if r is None else r[4] * r[2] / 1e7 for r in rows]}
    per_day = []  # list of {gk: metrics}
    stock_detail = {}
    for i in range(n):
        if i < NEED - 1:
            per_day.append(None)
            continue
        G = {}
        last = i == n - 1
        for s in syms:
            a = A[s]
            rec = [j for j in range(i - RECENT + 1, i + 1) if a["r"][j] is not None]
            base = [j for j in range(i - NEED + 1, i - RECENT + 1) if a["r"][j] is not None]
            if len(rec) < 8 or len(base) < 30 or a["r"][i] is None:
                continue
            tv = mean([a["r"][j][5] for j in range(max(0, i - 19), i + 1) if a["r"][j] is not None])
            if tv is None or tv < MIN_TV:
                continue
            dv_rec = mean([a["dv"][j] for j in rec])
            dv_base = mean([a["dv"][j] for j in base])
            if not dv_base:
                continue
            ratio = dv_rec / dv_base
            ret10 = a["lvl"][i] / a["lvl"][i - RECENT] - 1
            up_dv = sum(a["dv"][j] for j in rec if a["chg"][j] is not None and a["chg"][j] > 0)
            dq_r = sum(a["r"][j][4] for j in rec); tq_r = sum(a["r"][j][3] for j in rec)
            dq_b = sum(a["r"][j][4] for j in base); tq_b = sum(a["r"][j][3] for j in base)
            ma50 = mean(a["lvl"][i - NEED + 1:i + 1])
            dvt = sum(a["dv"][j] for j in rec)
            # thrust also needs delivery share holding up: a volume spike with falling delivery % is churn
            dshare_ok = tq_r > 0 and tq_b > 0 and dq_r / tq_r >= dq_b / tq_b - 0.05
            m = {"ratio": ratio, "thrust": ratio >= THRUST and ret10 > 0 and dshare_ok, "dvr": dv_rec, "dvb": dv_base, "dvt": dvt,
                 "up": up_dv, "dq_r": dq_r, "tq_r": tq_r, "dq_b": dq_b, "tq_b": tq_b,
                 "above": a["lvl"][i] > ma50, "ret10": ret10}
            G.setdefault(sym2g[s], []).append(m)
            if last:
                stock_detail[s] = {"tv": tv, "ratio": ratio, "ret10": ret10, "up": up_dv / dvt if dvt else 0,
                                   "dp": 100 * dq_r / tq_r if tq_r else None, "dpb": 100 * dq_b / tq_b if tq_b else None,
                                   "add": dv_rec - dv_base, "thrust": m["thrust"], "above": m["above"]}
        out = {}
        for gk, ms in G.items():
            if len(ms) < 3:
                continue
            thr = 100 * sum(m["thrust"] for m in ms) / len(ms)
            rg = sum(m["dvr"] for m in ms) / sum(m["dvb"] for m in ms)
            up = sum(m["up"] for m in ms) / (sum(m["dvt"] for m in ms) or 1)
            ds = 100 * (sum(m["dq_r"] for m in ms) / sum(m["tq_r"] for m in ms) - sum(m["dq_b"] for m in ms) / sum(m["tq_b"] for m in ms))
            s1, s2, s3, s4 = clip(thr / 40 * 100), clip((rg - 0.9) / 0.7 * 100), clip((up - 0.45) / 0.30 * 100), clip((ds + 4) / 8 * 100)
            F = 0.35 * s1 + 0.30 * s2 + 0.20 * s3 + 0.15 * s4
            P = 100 * sum(m["above"] for m in ms) / len(ms)
            out[gk] = {"F": round(F, 1), "P": round(P, 1), "n": len(ms), "thr": round(thr, 1), "rg": round(rg, 2),
                       "up": round(100 * up, 1), "ds": round(ds, 2), "s": [round(s1), round(s2), round(s3), round(s4)]}
        per_day.append(out)
    # equal-weight daily group return, every session (for the track record)
    dret = []
    for i in range(n):
        by = {}
        for s in syms:
            c = A[s]["chg"][i]
            if c is not None and abs(c) < 0.25:
                by.setdefault(sym2g[s], []).append(c)
        dret.append({gk: round(100 * mean(v), 3) for gk, v in by.items() if len(v) >= 3})
    return per_day, dret, stock_detail


def quad(F, P, rg=None):
    if F >= 60 and P < 50:
        return "lead"
    if F >= 60:
        return "confirmed"
    if P >= 60 and rg is not None and rg < 0.85:
        return "fading"
    return "neutral"


def merge_history(days, per_day, dret):
    path = os.path.join(OUT, "history.json")
    H = {"days": [], "g": {}}
    if os.path.exists(path):
        try:
            with open(path) as f:
                H = json.load(f)
        except Exception:
            pass
    old = {}
    for gk, ser in H["g"].items():
        for d, v in zip(H["days"], ser):
            old.setdefault(d, {})[gk] = v
    for d, pd, dr in zip(days, per_day, dret):
        row = {}
        for gk in set(dr) | set(pd or {}):
            m = (pd or {}).get(gk)
            row[gk] = [m["F"] if m else None, m["P"] if m else None, dr.get(gk), m["rg"] if m else None]
        old[d] = row
    alld = sorted(old)[-KEEP_HISTORY:]
    gks = sorted({gk for d in alld for gk in old[d]})
    H = {"days": alld, "g": {gk: [old[d].get(gk) for d in alld] for gk in gks}}
    return H


def track_record(H):
    """Next-20-session return of each quadrant's groups vs the median group, over every scored session."""
    days, G = H["days"], H["g"]
    res = {q: {"days": 0, "sig": 0, "beat": 0, "ex": []} for q in ("lead", "confirmed", "fading")}
    for i in range(len(days) - FWD):
        fwd = {}
        for gk, ser in G.items():
            rs = [ser[j][2] if ser[j] else None for j in range(i + 1, i + FWD + 1)]
            if sum(r is None for r in rs) > 3:
                continue
            v = 1.0
            for r in rs:
                v *= 1 + (r or 0) / 100
            fwd[gk] = 100 * (v - 1)
        if len(fwd) < 20:
            continue
        med = st.median(fwd.values())
        seen = set()
        for gk, ser in G.items():
            e = ser[i]
            if not e or e[0] is None or gk not in fwd:
                continue
            q = quad(e[0], e[1], e[3] if len(e) > 3 else None)
            if q in res:
                res[q]["sig"] += 1
                res[q]["beat"] += fwd[gk] > med
                res[q]["ex"].append(fwd[gk] - med)
                seen.add(q)
        for q in seen:
            res[q]["days"] += 1
    out = {}
    for q, r in res.items():
        out[q] = {"sessions": r["days"], "signals": r["sig"],
                  "hit": round(100 * r["beat"] / r["sig"], 1) if r["sig"] else None,
                  "excess": round(mean(r["ex"]), 2) if r["ex"] else None}
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    sym2g, groups, wk = group_map()
    if not sym2g:
        print("flow: no weekly sheet in data/weeks, skipped")
        return
    days, data = load_days(dt.date.today())
    print(f"flow: {len(days)} NSE sessions loaded ({days[0] if days else '-'} to {days[-1] if days else '-'})")
    if len(days) < NEED:
        print(f"flow: need {NEED} sessions, have {len(days)}; skipped")
        return
    per_day, dret, detail = score_series(days, data, sym2g)
    H = merge_history(days, per_day, dret)
    with open(os.path.join(OUT, "history.json"), "w") as f:
        json.dump(H, f, separators=(",", ":"))
    today = per_day[-1]
    back5 = per_day[-6] if len(per_day) >= 6 and per_day[-6] else {}
    members = {}
    for sym, d in detail.items():
        members.setdefault(sym2g[sym], []).append((sym, d))
    rows = []
    for gk, m in today.items():
        top = sorted(members.get(gk, []), key=lambda x: -x[1]["add"])[:6]
        rows.append({"k": gk, "name": groups.get(gk, {}).get("name", gk), "R": groups.get(gk, {}).get("R"), **m,
                     "q": quad(m["F"], m["P"], m["rg"]), "F5": back5.get(gk, {}).get("F"),
                     "top": [{"sym": s, "name": wk["names"].get(s, ""), "x": round(d["ratio"], 2), "r10": round(100 * d["ret10"], 1),
                              "up": round(100 * d["up"]), "dp": None if d["dp"] is None else round(d["dp"], 1),
                              "dpb": None if d["dpb"] is None else round(d["dpb"], 1), "tv": round(d["tv"], 1),
                              "t": d["thrust"]} for s, d in top]})
    rows.sort(key=lambda r: -r["F"])
    latest = {"date": days[-1], "week": wk["date"], "sessions": len(days), "scored": sum(1 for p in per_day if p),
              "stocks": len(detail), "groups": rows,
              # per stock: [delivery x, 10d %, up-day delivery %, delivery % now, delivery % base, thrust, above 50D, Rs Cr/day]
              "stk": {s: [round(d["ratio"], 2), round(100 * d["ret10"], 1), round(100 * d["up"]),
                          None if d["dp"] is None else round(d["dp"], 1), None if d["dpb"] is None else round(d["dpb"], 1),
                          1 if d["thrust"] else 0, 1 if d["above"] else 0, round(d["tv"], 1)] for s, d in detail.items()}, "test": track_record(H), "hist_days": len(H["days"]),
              "rules": {"recent": RECENT, "base": BASE, "thrust": THRUST, "min_tv": MIN_TV, "fwd": FWD}}
    with open(os.path.join(OUT, "latest.json"), "w") as f:
        json.dump(latest, f, separators=(",", ":"))
    q = {k: sum(1 for r in rows if r["q"] == k) for k in ("lead", "confirmed", "fading", "neutral")}
    print(f"flow {days[-1]}: {len(rows)} groups from {len(detail)} stocks; {q}; track record {latest['test']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the site build
        import traceback
        traceback.print_exc()
        print(f"flow: failed ({e})")
