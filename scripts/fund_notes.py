"""Save the evening task's "management read" for the day's A/B names into data/fund/notes.json.

Input file (JSON), written by the evening Claude task after reading StockScans' guidance report,
latest concall summary, growth catalysts and forensic report for each name:
  {"KEY": {"g": "raised" | "maintained" | "cut" | "mixed" | "none",   # latest guidance direction
           "rec": [delivered, partial, missed],                          # counts from the guidance report
           "drivers": ["...", "..."],                                    # up to 3 forward drivers, own words
           "risks": ["...", "..."],                                      # up to 3 risks or forensic flags, own words
           "line": "one plain-English sentence on the next 12-24 months"}}
Notes older than 45 days are dropped.  Usage: python scripts/fund_notes.py notes_work.json
"""
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES = os.path.join(ROOT, "data", "fund", "notes.json")
G = {"raised", "maintained", "cut", "mixed", "none"}


def clean_list(v, n=3, cap=140):
    return [str(x).strip()[:cap] for x in (v or []) if str(x).strip()][:n]


def main(path):
    with open(path) as f:
        new = json.load(f)
    data = {"s": {}}
    if os.path.exists(NOTES):
        with open(NOTES) as f:
            data = json.load(f)
    today = dt.date.today().isoformat()
    S = data.get("s", {})
    for key, e in new.items():
        if not e:
            continue
        rec = [int(x) for x in (e.get("rec") or [0, 0, 0])][:3]
        S[re.sub(r"-SM$", "", str(key))] = {"d": today, "g": e.get("g") if e.get("g") in G else "none", "rec": rec,
                                            "drivers": clean_list(e.get("drivers")), "risks": clean_list(e.get("risks")),
                                            "line": str(e.get("line", "")).strip()[:220]}
    cut = (dt.date.today() - dt.timedelta(days=45)).isoformat()
    S = {k: v for k, v in S.items() if v.get("d", "") >= cut}
    os.makedirs(os.path.dirname(NOTES), exist_ok=True)
    with open(NOTES, "w") as f:
        json.dump({"asOf": today, "s": S}, f, separators=(",", ":"), ensure_ascii=False)
    print(f"notes: {len(new)} saved, {len(S)} on file")


if __name__ == "__main__":
    main(sys.argv[1])
