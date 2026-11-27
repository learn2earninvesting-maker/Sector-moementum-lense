"""Telegram inbox: save sheets forwarded to your own bot into uploads/, so the dashboard picks them up.

How it is used: forward the daily vcp_setups_YYYY-MM-DD.xlsx (or the weekly Weekly_Ranked_Sector_List .xlsx)
from the Telegram channel to your bot. The "Telegram inbox" GitHub Action runs this script every 20 minutes
in the evening, saves new sheets to uploads/, and starts the publish workflow.

Secrets (GitHub repo -> Settings -> Secrets and variables -> Actions):
  TG_BOT_TOKEN  the token BotFather gave you (required)
  TG_CHAT_ID    your own chat id; the bot tells you this number the first time you message it.
                Until it is set, nothing is saved. Once set, messages from anyone else are ignored.

State: data/tg_inbox.json keeps the last Telegram update id, so nothing is read twice.
Only standard library; no packages needed.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS = os.path.join(ROOT, "uploads")
STATE = os.path.join(ROOT, "data", "tg_inbox.json")
OK_NAME = re.compile(r"^(vcp_setups_\d{4}-\d{2}-\d{2}|weekly_ranked_sector_list[\w\- ]*)\.xlsx$", re.I)
MAX_BYTES = 20 * 1024 * 1024  # Telegram bots can download files up to 20 MB


def api(token, method, **params):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    with urllib.request.urlopen(url, data=data, timeout=60) as r:
        out = json.load(r)
    if not out.get("ok"):
        raise RuntimeError(f"{method}: {out.get('description')}")
    return out["result"]


def reply(token, chat, text):
    try:
        api(token, "sendMessage", chat_id=chat, text=text)
    except Exception as e:  # a failed reply must not stop saving
        print(f"reply failed: {e}")


def safe_name(name):
    name = os.path.basename(name).strip()
    m = re.match(r"(?i)^(weekly_ranked_sector_list)(.*)$", name)
    return name if not m else "Weekly_Ranked_Sector_List" + m.group(2)


def main():
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    allowed = os.environ.get("TG_CHAT_ID", "").strip()
    if not token:
        print("tg_inbox: TG_BOT_TOKEN not set, skipped")
        return 0
    state = {"offset": 0}
    if os.path.exists(STATE):
        with open(STATE) as f:
            state = json.load(f)
    updates = api(token, "getUpdates", offset=state.get("offset", 0), timeout=0)
    saved = []
    for u in updates:
        state["offset"] = u["update_id"] + 1
        msg = u.get("message") or u.get("edited_message")
        if not msg:
            continue
        chat = str(msg["chat"]["id"])
        if not allowed:
            reply(token, chat, f"Your chat id is {chat}.\nAdd it in GitHub as the secret TG_CHAT_ID "
                               "(repo → Settings → Secrets and variables → Actions). Until then nothing is saved.")
            continue
        if chat != allowed:
            continue  # someone else found the bot: ignore silently
        doc = msg.get("document")
        if not doc:
            reply(token, chat, "Forward the vcp_setups_YYYY-MM-DD.xlsx sheet (or the weekly Weekly_Ranked_Sector_List "
                               "sheet) here and it goes to the dashboard.")
            continue
        name = safe_name(doc.get("file_name") or "")
        if not OK_NAME.match(name):
            reply(token, chat, f"Skipped {name or 'this file'}: only vcp_setups_YYYY-MM-DD.xlsx or "
                               "Weekly_Ranked_Sector_List .xlsx files are saved.")
            continue
        if doc.get("file_size", 0) > MAX_BYTES:
            reply(token, chat, f"Skipped {name}: over 20 MB, too big for a bot. Upload it to GitHub instead.")
            continue
        info = api(token, "getFile", file_id=doc["file_id"])
        with urllib.request.urlopen(f"https://api.telegram.org/file/bot{token}/{info['file_path']}", timeout=120) as r:
            blob = r.read()
        if blob[:2] != b"PK":  # .xlsx files are zip archives
            reply(token, chat, f"Skipped {name}: it doesn't look like an Excel file.")
            continue
        os.makedirs(UPLOADS, exist_ok=True)
        with open(os.path.join(UPLOADS, name), "wb") as f:
            f.write(blob)
        saved.append(name)
        reply(token, chat, f"Saved {name} ✓ The dashboard updates in a few minutes.")
    if updates:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as f:
            json.dump(state, f)
    print(f"tg_inbox: {len(updates)} updates, saved {saved}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"saved={len(saved)}\nchanged={1 if updates else 0}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"tg_inbox: failed ({e})")
        sys.exit(0)  # never fail loudly every 20 minutes; the log shows the reason
