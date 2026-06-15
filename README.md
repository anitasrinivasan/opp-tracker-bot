# Opportunity Tracker Bot

A personal Telegram bot that captures opportunities (jobs, grants, CFPs, fellowships) you come
across, parses them with Claude, and appends structured rows to a Google Sheet for deadline
tracking. Input arrives as **text**, a **URL**, or a **screenshot** — all three normalize into one
extraction step that outputs the same schema.

Single-user, personal use. Optimized for low friction: rows are written immediately, with a
lightweight correction flow afterward.

## What it does

```
Telegram message
   ├─ text       → use as-is
   ├─ URL        → fetch + extract readable content → text   (walled sites & failures → save link, nudge to screenshot)
   └─ photo(s)   → download → Claude vision (OCR + parse)
        ↓
   Claude extraction → JSON array of opportunities
        ↓
   Pydantic validation (dates normalized; bad items skipped, not fatal)
        ↓
   Append row(s) → Google Sheet  → reply "✅ Added: <title> — deadline <date>"
```

### Sheet columns

`title` · `deadline` (YYYY-MM-DD, blank if none) · `url` · `description` · `category`
(job/grant/cfp/fellowship/other) · `status` (interested/applied/passed) · `added_at` · `source_type`
(text/url/screenshot)

## Setup

### 1. Install

```bash
cd opp-tracker-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # or requirements-dev.txt to run the tests
cp .env.example .env                      # then fill in the values below
```

### 2. Create the Telegram bot

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the token into
   `TELEGRAM_BOT_TOKEN` in `.env`.
2. Message **@userinfobot** to get **your** numeric user ID → put it in `ALLOWED_USER_IDS`
   (comma-separated if more than one). **This is the security lock** — the bot ignores everyone
   whose ID isn't listed.

### 3. Connect the Google Sheet

The bot writes to a sheet **you own**. Three things must line up — none are hardcoded:

1. **Create a service account (the bot's robot identity).**
   - Go to [console.cloud.google.com](https://console.cloud.google.com) → create/select a project.
   - **APIs & Services → Library** → enable **Google Sheets API** and **Google Drive API**.
   - **APIs & Services → Credentials → Create credentials → Service account** → create it.
   - Open the service account → **Keys → Add key → JSON** → download it, save as
     `service_account.json` in this folder. (It's gitignored — never commit it.)
   - Note the service account's email, e.g. `opp-tracker@<project>.iam.gserviceaccount.com`.

2. **Create the Sheet (you own it).**
   - Make a blank Google Sheet in your normal Drive.
   - Copy its ID from the URL: `https://docs.google.com/spreadsheets/d/`**`<THIS_IS_THE_ID>`**`/edit`
     → put it in `GOOGLE_SHEET_ID`.
   - `GOOGLE_WORKSHEET_NAME` defaults to `Opportunities` — rename the tab to match, or change the
     env var. The bot writes the header row automatically on first run.

3. **Share the Sheet with the robot (this is the connection).**
   - In the Sheet, click **Share**, paste the service account's email, give it **Editor**, send.
   - Skipping this is the #1 mistake: the bot authenticates fine but gets a `403 PermissionError`
     on its first write.

### 4. (Optional) X / Twitter links

x.com / twitter.com links are read via the `twitter` CLI (`twitter-cli`, installed with the deps).
It needs your logged-in cookies:

- Log into x.com in a browser → DevTools → **Application → Cookies → https://x.com**.
- Copy `auth_token` → `TWITTER_AUTH_TOKEN`; copy `ct0` → `TWITTER_CT0`.

If these are missing or the CLI fails, X links fall back to the "saved the link — send a screenshot"
path, so this is optional.

### 5. Run

```bash
python bot.py
```

Then DM your bot.

## Using it

- **Text** — paste a listing; get `✅ Added: <title> — deadline <date>`.
- **Link** — send a URL. Grant/CFP/foundation/gov pages are read directly. LinkedIn/Instagram/
  Facebook can't be read (`🔒` reply) — the link is saved and you send a screenshot. Any page that
  fails to read is saved link-only with a nudge.
- **Screenshot** — send a photo; Claude reads it. Add a caption to give context (e.g. "deadline is
  Sept 1").
- **Listing split across several screenshots** — send them as **one album** (select all, send
  together) → one extraction across all images → one row. Or, after the fact, send a follow-up photo
  captioned **`+`** or **`same`** to merge it into the last entry and re-extract.
- **Correct the last entry** — reply `edit` for the field list, or directly send e.g.
  `deadline 2026-07-01`, `status applied`, `category grant`, `title New Title`. `deadline none`
  clears it. (Edit state is in memory, so it resets if the bot restarts.)

## Project layout

| File | Responsibility |
|---|---|
| `bot.py` | Telegram handlers, routing, owner guard, album buffering, edit flow |
| `extract.py` | Claude extraction call, prompt, JSON parse + per-item validation |
| `sources.py` | URL domain routing, generic fetch, X CLI, screenshot → image block |
| `store.py` | Google Sheets append/update (via `asyncio.to_thread`) |
| `models.py` | Pydantic `Opportunity` + fixed column order |
| `config.py` | `.env` loading |

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

Covers the pure logic with no secrets or network: URL routing, soft-fail detection, X-CLI output
parsing, extraction prompt building + JSON parse (skip-bad-keep-good), date/enum validation, text
routing, edit-command parsing, and the Sheets row/range helpers (HTTP mocked with `responses`).

## Notes & limits (v1)

- **Owner-locked** to `ALLOWED_USER_IDS`; everyone else is silently ignored.
- **No duplicate detection** — the same link sent twice appends twice.
- **No deadline reminders** yet.
- **Stragglers in an album** that arrive >~2s after the rest become a separate opportunity; use the
  `+` / `same` caption to merge.
- **Out of scope:** JS-rendered scraping (Playwright), dedup, reminder DMs, multi-user support.
  `.env` and `service_account.json` are gitignored — never commit secrets.
