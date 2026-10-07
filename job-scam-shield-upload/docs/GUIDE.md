# Job Scam Shield: full guide

Everything beyond the quick start in the [README](../README.md).

- [Setup and running](#setup-and-running)
- [The web app](#the-web-app)
- [How the score works](#how-the-score-works)
- [Chat stage tracker](#chat-stage-tracker)
- [Offer letter forgery check](#offer-letter-forgery-check)
- [College threat-intel network](#college-threat-intel-network)
- [Browser extension and bookmarklet](#browser-extension-and-bookmarklet)
- [Telegram bot](#telegram-bot)
- [Optional AI mode (Claude API)](#optional-ai-mode-claude-api)
- [API reference](#api-reference)
- [Configuration](#configuration)
- [Testing and samples](#testing-and-samples)
- [Project structure](#project-structure)
- [Privacy and security](#privacy-and-security)

## Setup and running

1. Install **Python 3.11 or newer** from https://www.python.org/downloads/.
   On Windows, tick **"Add python.exe to PATH"** in the installer.
2. In the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

If PowerShell blocks `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

Open http://127.0.0.1:8000.

## The web app

The home page links to every feature, each on its own page:

| Page | Address | What it does |
|------|---------|--------------|
| Home | `/` | Quick-check box, a card for every feature, scam red flags |
| Check a message | `/check` | Email/SMS/job post check with one-click examples and "report this" buttons |
| Check a chat | `/chat` | Drag-and-drop WhatsApp export, scam-stage progress bar, message timeline |
| Check an offer letter | `/offer-letter` | Drag-and-drop PDF, sample letters to try, letter details |
| Report a scammer | `/report` | 3-step form with a live "already reported?" lookup |
| Browser & Telegram | `/tools` | Bookmarklet, extension install guide, Telegram bot setup |
| Placement cell | `/dashboard` | Officer login, review, stats, network feed |
| API docs | `/docs` | Interactive documentation for every endpoint |

**Demo links** that run an example automatically:
`/chat#example=1` · `/offer-letter#sample=fake_offer_brightwave.pdf` · `/check#text=<your text>`

## How the score works

Each check returns **signals**: points plus a plain-language reason (negative points are good
signs). The total is clamped to 0–100: **60+ high risk**, **30–59 suspicious**, below 30 low.

**Recruiter identity**
- Free email (Gmail, Yahoo…) used by someone claiming to be a company
- Lookalike domains (`infosys-careers.co`, `lnfosys.com`) and punycode tricks
- Domain doesn't match the claimed company's official domain
- Online: domain age (RDAP), missing MX / SPF / DMARC records, domain doesn't exist
- Reported senders/domains from the college network

**Payment flagger**
- UPI IDs, `upi://pay` links, Razorpay/Paytm/Instamojo links, bank account + IFSC
- Fee language: registration fee, refundable deposit, training kit, verification fee, Hinglish ("fees bharni hogi")
- "Task job" language: earn ₹X per day, like videos, rate hotels, VIP/prepaid tasks
- Requests for Aadhaar, PAN, passbook, selfie with ID; OTP/PIN/CVV
- Urgency tactics, shortened links, "move to Telegram/WhatsApp"
- Disclaimers are understood: "we never charge any fee" is not a fee demand
- Reported UPI IDs and phone numbers from the college network

## Chat stage tracker

Task scams follow a script. Each message is labelled with the stage it shows:

| Stage | Example |
|-------|---------|
| 1. Hook | "Found your profile, earn ₹3000/day part time" |
| 2. Off-platform | "Contact my mentor on Telegram" |
| 3. Trust task | "You completed 3 tasks and received ₹150" |
| 4. Money ask | "Deposit ₹2,000 for the VIP/merchant task" |
| 5. Pressure | "Account frozen, pay ₹5,000 tax to withdraw" |

Reaching stage 4–5, or moving through 3+ stages in order, raises the risk score. Supported inputs:
WhatsApp exports (Android and iPhone formats) and pasted `Name: message` chats. Give your own name
(`user_name`) so your replies like "how do I withdraw?" aren't counted.

Try it with [samples/whatsapp_task_scam.txt](../samples/whatsapp_task_scam.txt).

## Offer letter forgery check

Upload a PDF on `/offer-letter`, send it to the Telegram bot, or `POST /api/check/offer-letter`
(multipart: `file`, optional `claimed_company`, `use_llm`, `online`).

| Area | Red flags |
|------|-----------|
| How the file was made | Made in Canva or an online PDF editor (iLovePDF, Smallpdf, Sejda…), modified days after creation, edits layered on after the first save |
| Company identifiers | CIN with an impossible format, state code or year; GSTIN failing its mod-36 checksum; GSTIN belonging to an individual instead of a company |
| Contacts and links | Free-email "HR", lookalike company websites (text or clickable links), WhatsApp-only contact |
| Wording | Fees and deposits, "Dear Candidate" instead of your name |

A valid CIN/GSTIN *format* doesn't prove a letter is real, because forgers copy real companies'
numbers. Scanned letters have no text; enable AI mode to let Claude read the page images.

Demo letters (fictional companies) are in [samples/letters](../samples/letters). Regenerate them
with `python scripts/make_sample_letters.py`.

## College threat-intel network

Students report scammers; their college's placement officer verifies or rejects each report;
verified identifiers protect students at **every** college in the network.

| Who | Can do |
|-----|--------|
| Student (no account) | Report a UPI ID, phone, website or email with the scam type, their college and an optional note |
| Placement officer | `/dashboard`: review their college's pending reports, see stats, see and export the network feed |
| Admin | Same as an officer, across all colleges |

**Effect on scam checks:** a *pending* report adds +15 ("reported, not yet verified"); a *verified*
report adds +50 and says how many colleges confirmed it; rejected reports are ignored. One false
or malicious report can't brand a genuine recruiter as a scammer.

**Demo data (local only):**

```powershell
.\.venv\Scripts\python.exe scripts\seed_demo.py
```

Then log in at `/dashboard` with a demo account from [scripts/seed_demo.py](../scripts/seed_demo.py).
Those passwords are public: never seed a real server.

**Real accounts.** There is no sign-up page; the admin manages accounts from the command line:

```powershell
python -m app.admin add-college "Your College Name" YCN
python -m app.admin add-officer --college YCN --name "Officer Name" --email officer@college.edu
python -m app.admin add-officer --admin --name "Network Admin" --email admin@example.org
python -m app.admin reset-password --email officer@college.edu
python -m app.admin list
```

## Browser extension and bookmarklet

The [extension](../extension) adds **right-click → Check for job scam** on every site, a toolbar
popup, and optional warning banners in Gmail. It calls the server, so keep it running.

| Browser | Install (developer mode) |
|---------|--------------------------|
| Chrome / Brave / Edge / Opera / Vivaldi | `chrome://extensions` (or `brave://`, `edge://`…) → **Developer mode** → **Load unpacked** → choose the `extension` folder |
| Firefox 121+ | `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on** → `extension/manifest.json` (removed on restart unless signed as an unlisted add-on on addons.mozilla.org) |

Chromium browsers may warn about the `browser_specific_settings` key; it's for Firefox and safe to ignore.

- **Gmail (opt-in):** popup → Settings → *Scan emails I open in Gmail*. Suspicious emails get a banner; low-risk ones get nothing.
- **Server address:** defaults to `http://127.0.0.1:8000`; for a hosted server, enter its address and the browser asks for permission.
- Gmail's markup isn't a public API. If banners stop appearing, update the selectors in `extension/content-gmail.js`.

**Bookmarklet (any browser, no install).** On `/tools`, drag **🛡️ Check for job scam** to the
bookmarks bar. Select a message on any site and click it (select nothing to check the whole page).
The text travels in the URL fragment (`#…`), which browsers never send to servers.

## Telegram bot

1. On Telegram, message **@BotFather** → `/newbot`. Copy the token and keep it secret: anyone
   with it controls your bot. If it ever leaks, send `/revoke` to @BotFather for a new one.
2. Copy `.env.example` to `.env` and put the token in it (`.env` is git-ignored, never upload it):

```
TELEGRAM_BOT_TOKEN=123456789:your-token
```

3. Run the bot (separate from the web server; it keeps running until you press Ctrl+C):

```powershell
python -m app.bot
```

4. Send `/start` to your bot. The "/" menu shows `/check`, `/clear` and `/help`. Students can paste
   a message, forward several messages then send `/check`, or send a WhatsApp export
   (`.txt`/`.zip`) or an offer letter PDF.

The bot only answers while `python -m app.bot` is running on your computer. To keep it online
24/7, run it on a server (any small VPS or cloud VM).

Forwarded messages are held in memory only until `/check` (or 30 minutes) and never saved.

## Optional AI mode (Claude API)

Rules miss creative wording and can't read scanned PDFs. With AI mode on (checkbox on the web
pages, `use_llm: true` in the API, or `SHIELD_USE_LLM=1` for the bot), Claude also labels chat
messages and reviews offer letters, using structured outputs.

```powershell
$env:ANTHROPIC_API_KEY = "your-key"   # from https://console.anthropic.com
```

Without a key, or if a call fails, it quietly falls back to the rules. AI mode sends content to
Anthropic, so it's opt-in and labelled as such everywhere.

## API reference

Interactive docs at `/docs`.

| Method | Path | What it does |
|--------|------|--------------|
| POST | `/api/analyze` | All checks on `text` (+ optional `sender_email`, `claimed_company`, `user_name`, `use_llm`, `online`). Chats also get the stage tracker |
| POST | `/api/check/chat` | Chat stage tracker only |
| POST | `/api/check/offer-letter` | Offer letter PDF check (multipart upload) |
| POST | `/api/check/recruiter` | Recruiter email check only |
| POST | `/api/check/payment` | Payment/fee check only |
| GET | `/api/colleges` | Colleges students can pick when reporting |
| POST | `/api/reports` | Report a `upi` / `phone` / `domain` / `email` (starts as pending) |
| GET | `/api/reports/{kind}/{value}` | Verified and pending report counts |
| POST | `/api/auth/login` · `/api/auth/logout` · GET `/api/auth/me` | Officer login (Bearer token) |
| GET | `/api/officer/reports?state=pending\|verified\|rejected\|all` | Reports for the officer's college |
| POST | `/api/officer/reports/{id}/review` | `{"decision": "verified"}` or `"rejected"` |
| GET | `/api/officer/stats` | Counts and breakdowns for the dashboard |
| GET | `/api/network/feed` · `/api/network/feed.csv` | Verified scams across all colleges |

```json
POST /api/analyze
{
  "text": "Selected for internship at TCS. Pay registration fee Rs 999 to tcs.hr@ybl",
  "sender_email": "tcs.recruit@gmail.com",
  "claimed_company": "TCS"
}
```

## Configuration

Put these in a `.env` file in the project folder (copy [`.env.example`](../.env.example)), or set
them as environment variables. `.env` is git-ignored: never upload it.

| Variable | Default | Purpose |
|----------|---------|---------|
| `SHIELD_DB_PATH` | `data/shield.db` | SQLite database location |
| `ANTHROPIC_API_KEY` | – | Enables AI mode |
| `SHIELD_LLM_MODEL` | `claude-opus-5-5` | Claude model for AI mode |
| `TELEGRAM_BOT_TOKEN` | – | Telegram bot token |
| `SHIELD_USE_LLM` | – | `1` = the bot uses AI mode |

**Known companies.** [app/data/companies.json](../app/data/companies.json) drives impersonation
detection. Add companies that recruit at your college: `name`, `aliases` (what people type),
`keywords` (used to spot lookalike domains) and official `domains`.

## Testing and samples

```powershell
pytest                                   # 91 tests, all offline
python scripts/run_samples.py            # sample messages vs expected verdicts
python scripts/run_samples.py samples/known_gaps.json   # cases the rules don't catch yet
python scripts/take_screenshots.py       # regenerate README screenshots (server running)
```

## Project structure

```
app/
  main.py              FastAPI app: pages and check endpoints
  network.py           College network API: reports, review, stats, feed
  auth.py              Password hashing, sessions, rate limits
  admin.py             CLI for colleges and officer accounts
  bot.py               Telegram bot
  db.py                SQLite schema and queries (auto-migrates)
  schemas.py           Request/response models
  scoring.py           Combines signals into a 0-100 score
  checks/
    chat.py            Chat parsing + scam stage tracker
    recruiter.py       Recruiter identity check
    offer_letter.py    Offer letter PDF forensics
    payment.py         Payment request flagger
    community.py       Signals from network reports
    llm.py             Optional Claude API reviews
  data/companies.json  Known companies and official domains
  static/              Web pages, css/style.css, js/common.js
extension/             Browser extension (Manifest V3, Chromium + Firefox)
samples/               Test messages, known gaps, WhatsApp export, demo letters
scripts/               Sample runner, demo seeding, screenshots, icon/letter generators
tests/                 pytest suite
docs/                  This guide and screenshots
```

## Privacy and security

- Messages, chats and letters are analysed in memory and **not stored**. Only explicit reports are saved, and only the reported identifier.
- Report notes stay inside the reporting college; the network feed shares only the identifier, scam type and counts.
- Passwords: scrypt. Session tokens: random, stored only as SHA-256 hashes, 12-hour expiry.
- Rate limits: 10 logins per 15 minutes and 20 reports per hour per IP (in-memory: run one process, or move to Redis to scale).
- Officers only see their own college's reports; there's no public sign-up.
- CSV export guards against spreadsheet formula injection.
- AI mode is opt-in because it sends content to a third party.
- Designed with India's DPDP Act in mind: collect the minimum, keep it briefly.
