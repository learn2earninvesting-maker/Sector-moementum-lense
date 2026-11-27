# Sector Momentum Lens

A weekly dashboard for the NovaWealth / Markets Decoded **Weekly Ranked Sector List**. It ranks all industry groups by momentum, sorts them into segments (Emerging, Established, Turnaround, Fading, Rangebound) and writes the week's insights in plain English, with one tab per insight.

## Built on the NovaWealth guide

The tabs follow the guide's weekly routine: **Top 25** (new names by MomentumRank) → **Emerging / Established / Fading / Turnarounds** (rank journeys) → **Stock picks** (MasterScore A/B, EPS rank 80+, price strength 80+, buyer demand B+ or better, inside the top 25 sectors, plus a separate "price-led" list for high price strength with weak earnings) → **Conviction** (sectors and stocks that keep showing up week after week). Stock cells use the guide's colours: green for 80+ or A grades, amber for C, red for D/E or under 50.

## Week vs week (the Weekly section)

Each new sheet is compared with the previous one:

- **Scorecard:** how last week's shortlist moved against every stock, plus a running record.
- **Shortlist changes:** new names, drop-outs (with the reason) and stocks with rising grades.
- **Speed:** sectors whose climb is speeding up or slowing down.
- **Trends:** week-by-week rank lines, breadth changes, segment mix and early warnings (from 3 weeks).
- **Segment changes:** which groups moved between segments.

## Daily VCP setups (Setups section)

Upload each day's `vcp_setups_YYYY-MM-DD.xlsx` to the same **uploads** folder. The site recognises it and adds:

- **VCP setups:** every setup checked against the weekly sector sheet, with a fit score out of 100 (sector 25, grades 25, pattern 25, RS 63d 10, liquidity 15), daily swing in ₹, trade-up-to size and links. A liquidity filter (default ₹2.5 Cr+ traded per day) hides thin names.
- **Setup clusters:** which sectors the setups sit in, coloured by that sector's MomentumRank.
- **Setup tracker:** new, dropped and days-on-list, with the price move since first listed (from the second day).

## Next-session plan (Setups → Next-session plan)

Built from each daily VCP sheet plus the last 20 sessions of exchange data: **Ready / Watching / Avoid**, each with buy-above trigger, max entry, stop, 2R/3R targets and position size from your capital and risk %. SME stocks always show as red tiles. The site refreshes automatically at about 8 pm IST on weekdays so the day's exchange files are included.

## Each week (about 1 minute, works from a phone browser)

1. Open this repo on github.com and go to the **uploads** folder.
2. **Add file → Upload files**, drop in the new `.xlsx`, and click **Commit changes**.
3. Wait about a minute. The action converts the sheet and republishes the site. Your link now shows the new week, and the **Since last upload** tab shows what changed.

The week is taken from the date in the file name (`..._21_11_2026_...`) or from "Data as of" inside the sheet. Re-uploading a week replaces that week.

## Liquidity flow (Sectors → Liquidity flow)

Shows which industry groups **delivery-based** money is moving into, before price confirms it. Built every weekday at about 8 pm IST from NSE's daily delivery file (`sec_bhavdata_full`), with no upload needed.

- **Delivery only:** delivered shares × average price. Intraday and high-frequency round trips (bought and sold the same day) deliver nothing, so they cannot move the score. Only the EQ series is used (BE/BZ are 100% delivery by rule; SME is too thin). Stocks under ₹2.5 Cr a day are left out.
- **Flow Score (0–100) per group:** 35% share of stocks "thrusting" (10-session delivery value ≥ 1.3× the 40 sessions before, with price up) + 30% group delivery value vs base + 20% share delivered on up days + 15% change in delivery %.
- **Price Score:** share of the group's stocks above their 50-day average.
- **Reading:** Flow 60+ with Price under 50 = **Early inflow** (the lead signal). Flow 60+ with Price 50+ = **Confirmed**. Price 60+ with delivery value under 0.85× base = **Leaders losing flow**.
- **Track record:** every session's signals are checked against the next 20 sessions (vs the median group), so you can see whether early inflow really leads. It needs about two months of history to mean much and fills in by itself.

Groups come from the latest weekly sheet. `scripts/flow.py` writes `data/flow/latest.json` and `data/flow/history.json`. The first run downloads about four months of NSE files, which takes a few minutes.

## Fundamentals (StockScans)

Every final stock (Strong 25, VCP setups, Confluence and its watchlist) gets a fundamental check from StockScans. StockScans can't be reached from GitHub, so the **evening Claude task** (about 8:40 pm IST on weekdays) runs `scripts/fund_targets.py`, fetches the missing or week-old names from StockScans, saves them with `scripts/fund_merge.py` to `data/fund/stocks.json`, and pushes. The site scores them:

- **Score out of 100** from what is available: growth (sales and profit YoY, 3-year EPS), quality (ROCE, ROE, cash flow vs profit), balance sheet (debt/equity, interest cover, pledge), ownership (promoter level and change, FII + DII change last quarter) and valuation (PE vs industry, PEG). Banks and finance companies use ROE instead of ROCE, debt and cash flow.
- **Strong** 70+, **OK** 50–69, **Weak** under 50. **Red flag**: pledge over 10%, promoter stake down more than 3 points in a year, losses, negative operating cash flow, debt/equity over 2, interest cover under 1.5x.
- A **Fundamentals** filter (Any / Hide weak & red flags / Strong only) sits on Strong 25, VCP setups and Confluence. In Confluence, A-list needs fundamentals OK or Strong, and a red flag moves a setup to Skip.

## Send sheets from Telegram (no GitHub step)

The VCP sheet arrives in a Telegram channel, so a small bot of your own carries it to the repo. Forward the sheet to the bot, and the **Telegram inbox** Action (every 20 minutes from 3:30 to 11:10 pm IST on weekdays, every 3 hours at weekends) saves it to `uploads/` and republishes the dashboard. The bot replies "Saved ✓".

One-time setup:
1. In Telegram, open **@BotFather**, send `/newbot`, pick a name, and copy the token it gives you.
2. In GitHub: repo → Settings → Secrets and variables → Actions → **New repository secret**: name `TG_BOT_TOKEN`, value = the token.
3. Send any message to your new bot. Within 20 minutes it replies with your chat id. Add a second secret `TG_CHAT_ID` with that number. From then on the bot only accepts files from you.

Accepted files: `vcp_setups_YYYY-MM-DD.xlsx` and `Weekly_Ranked_Sector_List…xlsx`, up to 20 MB. The upload icon in the app still works for viewing a sheet on one device, but it does not publish it.

## Install it as an app

- **Android (Chrome):** open the link → Share icon in the dashboard → **Install the app** (or Chrome menu → Install app).
- **iPhone (Safari):** open the link → Safari's Share button → **Add to Home Screen**.

It opens full-screen like an app, works offline with the last week you opened, and picks up new weeks automatically when online.

## Sharing

- **The link:** anyone with it sees the latest published week. Tabs have their own links, e.g. `.../#emerging`.
- **Share summary / Share this insight:** copies a ready-to-paste message for WhatsApp, Telegram or email (on a phone it opens the share sheet).
- **Download report:** one self-contained `.html` file of the week you are viewing. It opens in any browser with no upload, so you can send it to people directly.
- **Save PDF:** prints every insight tab as a PDF.
- **Upload sheet** on the site shows a file only on your own device; nothing is uploaded. Use **Download report** to share that view.

## One-time setup

Settings → Pages → *Build and deployment* → Source: **GitHub Actions**. Then run the action once (Actions → *Convert sheet and publish dashboard* → Run workflow) or upload a sheet.

## Files

- `index.html`: the whole dashboard
- `uploads/`: weekly sheets go here
- `scripts/fund_targets.py`, `scripts/fund_merge.py`: fundamentals from StockScans into `data/fund/` (run by the evening Claude task)
- `scripts/flow.py`: scores liquidity flow from NSE delivery data into `data/flow/`
- `scripts/convert.py`: turns a sheet into `data/weeks/<date>.json` and rebuilds `data/index.json` (same scoring as the page)
- `.github/workflows/publish.yml`: runs the converter and publishes to GitHub Pages

Price-momentum screen for education, not investment advice.
