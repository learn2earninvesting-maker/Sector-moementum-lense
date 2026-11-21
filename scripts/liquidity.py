"""Liquidity for each week's stocks, from the exchanges' end-of-day files (bhavcopy).

For the 5 trading days up to the sheet date it downloads:
  NSE  https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
       (turnover in Rs lakh and delivery %)
  BSE  https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV
       (UDiFF format; turnover in Rs, keyed by scrip code and ticker)
and writes data/liq/<date>.json:
  {"days": [...dates used...], "s": {SYMBOL: [avg traded value Rs Cr/day, delivery %, days traded]}}

Downloaded files are cached in data/liq/raw/ (gitignored) so reruns are cheap.
Any failure only means no liquidity for that week; the dashboard then falls back to market cap.
"""
import csv
import datetime as dt
import io
import json
import os
import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIQ = os.path.join(ROOT, "data", "liq")
RAW = os.path.join(LIQ, "raw")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}


def _session():
    s = requests.Session()
    s.headers.update(UA)
    for url in ("https://www.nseindia.com", "https://www.bseindia.com"):
        try:
            s.get(url, timeout=20)
        except Exception:
            pass
    return s


def _get(s, url, referer, cache):
    if os.path.exists(cache):
        with open(cache, encoding="utf-8", errors="ignore") as f:
            return f.read()
    for attempt in range(3):
        try:
            r = s.get(url, headers={"Referer": referer}, timeout=40)
            if r.status_code == 200 and len(r.content) > 500 and b"<html" not in r.content[:300].lower():
                text = r.content.decode("utf-8", errors="ignore")
                os.makedirs(RAW, exist_ok=True)
                with open(cache, "w", encoding="utf-8") as f:
                    f.write(text)
                return text
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(2 + attempt * 3)
    return None


def _num(v):
    try:
        return float(str(v).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_nse(text):
    """SYMBOL -> (turnover Rs Cr, delivery %). Equity-type series only."""
    out = {}
    rows = csv.reader(io.StringIO(text))
    head = [h.strip().upper() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    for r in rows:
        if len(r) < len(head):
            continue
        sym, ser = r[ix["SYMBOL"]].strip(), r[ix["SERIES"]].strip().upper()
        if ser not in ("EQ", "BE", "BZ", "SM", "ST", "SZ"):
            continue
        t = _num(r[ix["TURNOVER_LACS"]])
        d = _num(r[ix["DELIV_PER"]]) if "DELIV_PER" in ix else None
        if t is None:
            continue
        a = out.get(sym, (0.0, None))
        out[sym] = (a[0] + t / 100.0, d if d is not None else a[1])
    return out


def parse_bse(text):
    """Scrip code and ticker -> turnover Rs Cr."""
    out = {}
    rows = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    need = ("FinInstrmId", "TckrSymb", "TtlTrfVal")
    if not all(k in ix for k in need):
        return out
    for r in rows:
        if len(r) < len(head):
            continue
        t = _num(r[ix["TtlTrfVal"]])
        if t is None:
            continue
        cr = t / 1e7
        for k in (r[ix["FinInstrmId"]].strip(), r[ix["TckrSymb"]].strip()):
            if k:
                out[k] = out.get(k, 0.0) + cr
    return out


def build(date_str, days=5, lookback=12):
    """Average daily traded value over the last `days` sessions on or before date_str."""
    if requests is None:
        print("liquidity: requests not installed, skipped")
        return None
    s = _session()
    d = dt.date.fromisoformat(date_str)
    used, nse_days, bse_days = [], [], []
    for back in range(lookback):
        if len(used) >= days:
            break
        day = d - dt.timedelta(days=back)
        if day.weekday() >= 5:
            continue
        n = _get(s, f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv",
                 "https://www.nseindia.com/all-reports", os.path.join(RAW, f"nse_{day:%Y%m%d}.csv"))
        b = _get(s, f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{day:%Y%m%d}_F_0000.CSV",
                 "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx", os.path.join(RAW, f"bse_{day:%Y%m%d}.csv"))
        if not n and not b:
            continue  # holiday, or both exchanges unreachable
        used.append(day.isoformat())
        nse_days.append(parse_nse(n) if n else {})
        bse_days.append(parse_bse(b) if b else {})
    if not used:
        print(f"liquidity {date_str}: no exchange files could be downloaded")
        return None
    syms = set().union(*[set(x) for x in nse_days], *[set(x) for x in bse_days])
    res = {}
    for sym in syms:
        tot, traded, dl = 0.0, 0, []
        for nd, bd in zip(nse_days, bse_days):
            v = (nd[sym][0] if sym in nd else 0.0) + bd.get(sym, 0.0)
            if sym in nd and nd[sym][1] is not None:
                dl.append(nd[sym][1])
            if v > 0:
                traded += 1
            tot += v
        res[sym] = [round(tot / len(used), 3), round(sum(dl) / len(dl), 1) if dl else None, traded]
    print(f"liquidity {date_str}: {len(used)} sessions ({', '.join(used)}), {len(res)} symbols, "
          f"NSE files {sum(1 for x in nse_days if x)}, BSE files {sum(1 for x in bse_days if x)}")
    return {"days": used, "s": res}


def ensure(date_str):
    """Create data/liq/<date>.json if missing or built from fewer than 5 sessions. Returns True if present."""
    os.makedirs(LIQ, exist_ok=True)
    path = os.path.join(LIQ, f"{date_str}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                if len(json.load(f).get("days", [])) >= 5:
                    return True
        except Exception:
            pass
    try:
        data = build(date_str)
    except Exception as e:  # never let liquidity break the weekly build
        print(f"liquidity {date_str}: failed ({e})")
        data = None
    if data:
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        return True
    return os.path.exists(path)


# ---------------------------------------------------------------- volume history (VCP "volume drying up")

def parse_nse_vol(text):
    """SYMBOL -> traded quantity (equity-type series, summed)."""
    out = {}
    rows = csv.reader(io.StringIO(text))
    head = [h.strip().upper() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    for r in rows:
        if len(r) < len(head):
            continue
        if r[ix["SERIES"]].strip().upper() not in ("EQ", "BE", "BZ", "SM", "ST", "SZ"):
            continue
        q = _num(r[ix["TTL_TRD_QNTY"]])
        if q is not None:
            sym = r[ix["SYMBOL"]].strip()
            out[sym] = out.get(sym, 0.0) + q
    return out


def parse_bse_vol(text):
    """Scrip code and ticker -> traded quantity."""
    out = {}
    rows = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    if not all(k in ix for k in ("FinInstrmId", "TckrSymb", "TtlTradgVol")):
        return out
    for r in rows:
        if len(r) < len(head):
            continue
        q = _num(r[ix["TtlTradgVol"]])
        if q is None:
            continue
        for k in (r[ix["FinInstrmId"]].strip(), r[ix["TckrSymb"]].strip()):
            if k:
                out[k] = out.get(k, 0.0) + q
    return out


def parse_nse_chg(text):
    """SYMBOL -> daily % change (close vs previous close), EQ-type series."""
    out = {}
    rows = csv.reader(io.StringIO(text))
    head = [h.strip().upper() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    if "CLOSE_PRICE" not in ix or "PREV_CLOSE" not in ix:
        return out
    for r in rows:
        if len(r) < len(head) or r[ix["SERIES"]].strip().upper() not in ("EQ", "BE", "BZ", "SM", "ST", "SZ"):
            continue
        c, p = _num(r[ix["CLOSE_PRICE"]]), _num(r[ix["PREV_CLOSE"]])
        if c and p:
            out[r[ix["SYMBOL"]].strip()] = (c / p - 1) * 100
    return out


def parse_bse_chg(text):
    out = {}
    rows = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    if not all(k in ix for k in ("FinInstrmId", "TckrSymb", "ClsPric", "PrvsClsgPric")):
        return out
    for r in rows:
        if len(r) < len(head):
            continue
        c, p = _num(r[ix["ClsPric"]]), _num(r[ix["PrvsClsgPric"]])
        if c and p:
            for k in (r[ix["FinInstrmId"]].strip(), r[ix["TckrSymb"]].strip()):
                if k:
                    out.setdefault(k, (c / p - 1) * 100)
    return out


def parse_nse_px(text):
    """SYMBOL -> (high, low, close, delivery %)."""
    out = {}
    rows = csv.reader(io.StringIO(text))
    head = [h.strip().upper() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    if not all(k in ix for k in ("HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE")):
        return out
    for r in rows:
        if len(r) < len(head) or r[ix["SERIES"]].strip().upper() not in ("EQ", "BE", "BZ", "SM", "ST", "SZ"):
            continue
        h, l, c = _num(r[ix["HIGH_PRICE"]]), _num(r[ix["LOW_PRICE"]]), _num(r[ix["CLOSE_PRICE"]])
        d = _num(r[ix["DELIV_PER"]]) if "DELIV_PER" in ix else None
        if h and l and c:
            out[r[ix["SYMBOL"]].strip()] = (h, l, c, d)
    return out


def parse_bse_px(text):
    out = {}
    rows = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    if not all(k in ix for k in ("FinInstrmId", "TckrSymb", "HghPric", "LwPric", "ClsPric")):
        return out
    for r in rows:
        if len(r) < len(head):
            continue
        h, l, c = _num(r[ix["HghPric"]]), _num(r[ix["LwPric"]]), _num(r[ix["ClsPric"]])
        if h and l and c:
            for k in (r[ix["FinInstrmId"]].strip(), r[ix["TckrSymb"]].strip()):
                if k:
                    out.setdefault(k, (h, l, c, None))
    return out


def prune_raw(keep_days=140):
    if not os.path.isdir(RAW):
        return
    cut = (dt.date.today() - dt.timedelta(days=keep_days)).strftime("%Y%m%d")
    for f in os.listdir(RAW):
        stamp = f.split("_")[-1].split(".")[0]
        if stamp.isdigit() and stamp < cut:
            os.remove(os.path.join(RAW, f))


def volumes(date_str, keys, sessions=55, lookback=95):
    """Daily traded quantity for each key (NSE symbol or BSE code/ticker), oldest -> newest, for the
    last `sessions` trading days on or before date_str. Returns (days, {key: [qty, ...]})."""
    if requests is None:
        return [], {}
    s = _session()
    d = dt.date.fromisoformat(date_str)
    days, rows, chg, px = [], [], [], []
    for back in range(lookback):
        if len(days) >= sessions:
            break
        day = d - dt.timedelta(days=back)
        if day.weekday() >= 5:
            continue
        n = _get(s, f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv",
                 "https://www.nseindia.com/all-reports", os.path.join(RAW, f"nse_{day:%Y%m%d}.csv"))
        b = _get(s, f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{day:%Y%m%d}_F_0000.CSV",
                 "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx", os.path.join(RAW, f"bse_{day:%Y%m%d}.csv"))
        if not n and not b:
            continue
        nv = parse_nse_vol(n) if n else {}
        bv = parse_bse_vol(b) if b else {}
        nc = parse_nse_chg(n) if n else {}
        bc = parse_bse_chg(b) if b else {}
        npx = parse_nse_px(n) if n else {}
        bpx = parse_bse_px(b) if b else {}
        px.append({k: (npx.get(k) or bpx.get(k)) for k in keys})
        days.append(day.isoformat())
        chg.append({k: (round(nc[k], 2) if k in nc else round(bc[k], 2) if k in bc else None) for k in keys})
        row = {}
        for k in keys:
            bse_only = k.isdigit()
            if (bse_only and not b) or (not bse_only and not n):
                row[k] = None  # that exchange's file is missing for this day, not a zero-volume day
            else:
                row[k] = nv.get(k, 0.0) + bv.get(k, 0.0)
        rows.append(row)
        time.sleep(0.3)
    days.reverse()
    rows.reverse()
    chg.reverse()
    px.reverse()
    hlc = {k: [None if p[k] is None else [round(p[k][0], 2), round(p[k][1], 2), round(p[k][2], 2), p[k][3]] for p in px[-20:]] for k in keys}
    return days, {k: [None if r[k] is None else int(r[k]) for r in rows] for k in keys}, {k: [c[k] for c in chg] for k in keys}, hlc


def voltrend(vol, chg):
    """Volume trend over the last 10 sessions against the 20 before, and up-day vs down-day volume (20 sessions)."""
    pairs = [(v, c) for v, c in zip(vol, chg)]
    last10 = [v for v, _ in pairs[-10:] if v is not None]
    prev20 = [v for v, _ in pairs[-30:-10] if v is not None]
    if len(last10) < 6 or len(prev20) < 12:
        return None
    p = sum(prev20) / len(prev20)
    if p <= 0:
        return None
    up = sum(v for v, c in pairs[-20:] if v is not None and c is not None and c > 0)
    dn = sum(v for v, c in pairs[-20:] if v is not None and c is not None and c < 0)
    base = [v for v in vol[:-5][-50:] if v is not None]
    b = sum(base) / len(base) if base else 0
    last_v, last_c = vol[-1], chg[-1]
    return {"t10": round(sum(last10) / len(last10) / p, 2),
            "udr": round(up / dn, 2) if dn > 0 else (9.99 if up > 0 else None),
            "surge": bool(b and last_v is not None and last_c is not None and last_v >= 1.5 * b and last_c > 0),
            "c1": last_c}


def dryup(series):
    """Average volume of the last 5 sessions against the 50 sessions before them."""
    if len(series) < 25:
        return None
    last = [x for x in series[-5:] if x is not None]
    base = [x for x in series[:-5][-50:] if x is not None]
    if len(last) < 3 or len(base) < 20:
        return None
    b = sum(base) / len(base) if base else 0
    if b <= 0:
        return None
    return {"r5": round(sum(last) / len(last) / b, 2), "r1": None if series[-1] is None else round(series[-1] / b, 2)}
