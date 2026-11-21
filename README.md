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

## Each week (about 1 minute, works from a phone browser)

1. Open this repo on github.com and go to the **uploads** folder.
2. **Add file → Upload files**, drop in the new `.xlsx`, and click **Commit changes**.
3. Wait about a minute. The action converts the sheet and republishes the site. Your link now shows the new week, and the **Since last upload** tab shows what changed.

The week is taken from the date in the file name (`..._21_11_2026_...`) or from "Data as of" inside the sheet. Re-uploading a week replaces that week.

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
- `scripts/convert.py`: turns a sheet into `data/weeks/<date>.json` and rebuilds `data/index.json` (same scoring as the page)
- `.github/workflows/publish.yml`: runs the converter and publishes to GitHub Pages

Price-momentum screen for education, not investment advice.
