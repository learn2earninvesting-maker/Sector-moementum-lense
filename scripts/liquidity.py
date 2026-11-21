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
