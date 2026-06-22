# Opportunity Tracker Bot

A personal Telegram bot that captures opportunities (jobs, grants, CFPs, fellowships) you come
across, parses them with Claude, and appends structured records to an Airtable table for deadline
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
   Append record(s) → Airtable  → reply "✅ Added: <title> — deadline <date>"
```

### Fields

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

### 3. Connect Airtable (free — no credit card, no cloud project)

1. **Create the base and table.**
   - Sign in at [airtable.com](https://airtable.com) (free).
   - Create a **base**, and inside it a **table** named `Opportunities` (or set `AIRTABLE_TABLE_NAME`
     to whatever you name it).
   - Give the table these **fields, named exactly** (case-sensitive). Easiest: make them all
     **Single line text**. (Optional: make `deadline` a **Date** field for Airtable's date UI —
     the bot sends `YYYY-MM-DD` with typecast, so either type works.)

     `title` · `deadline` · `url` · `description` · `category` · `status` · `added_at` · `source_type`

     Delete Airtable's default `Notes`/`Assignee`/`Status` starter fields if they get in the way
     (or just leave them — the bot only writes the fields above).

2. **Find the base ID.**
   - Open the base, click **Help → API documentation** (or visit
     [airtable.com/api](https://airtable.com/api) and pick the base). The page shows the base ID,
     which looks like `appXXXXXXXXXXXXXX` → put it in `AIRTABLE_BASE_ID`.

3. **Create a Personal Access Token (this is the connection).**
   - Go to [airtable.com/create/tokens](https://airtable.com/create/tokens) → **Create token**.
   - **Scopes:** add `data.records:read` and `data.records:write`.
   - **Access:** add the base you created above.
   - Create it, copy the token (starts with `pat…`) → put it in `AIRTABLE_TOKEN`.
   - The bot checks access on startup and prints a clear error if the token, base ID, or fields are
     wrong — so you'll know immediately if something's off.

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
| `store.py` | Airtable append/update (via `asyncio.to_thread`) |
| `models.py` | Pydantic `Opportunity` + fixed column order |
| `config.py` | `.env` loading |

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

Covers the pure logic with no secrets or network: URL routing, soft-fail detection, X-CLI output
parsing, extraction prompt building + JSON parse (skip-bad-keep-good), date/enum validation, text
routing, edit-command parsing, and the Airtable field builder. (HTTP is mocked with `responses` for
the URL-fetch tests.)

## Notes & limits (v1)

- **Owner-locked** to `ALLOWED_USER_IDS`; everyone else is silently ignored.
- **No duplicate detection** — the same link sent twice appends twice.
- **No deadline reminders** yet.
- **Stragglers in an album** that arrive >~2s after the rest become a separate opportunity; use the
  `+` / `same` caption to merge.
- **JS-rendered pages:** no headless browser (Playwright is out of scope), but the URL fetch reads
  embedded **JSON-LD / OpenGraph** metadata, so many JS job boards (Ashby, Greenhouse, Lever,
  Workday, …) still parse from the link. Pages with no embedded metadata fall back to the
  screenshot path.
- **Out of scope:** full headless-browser scraping, dedup, reminder DMs, multi-user support.
  `.env` is gitignored — never commit secrets.
