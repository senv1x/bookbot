# BookBot

**An AI front desk for small service businesses (dentists, garages, salons, driving schools, vets).**
A business enters its website URL. BookBot reads the site (services, prices, opening hours, FAQs, contact details) and gives it
a working chat assistant plus a public demo link in about 30 seconds. The assistant answers customer questions from that data and
captures booking requests (name, phone, service, preferred time) after hours. The owner gets an email for every request and
sees them all in a private dashboard. The widget goes on any website with one `<script>` line.

Built by Shipfast Labs. It grew out of [ai-chat-widget](https://github.com/senv1x/ai-chat-widget).

## Features

| | |
|---|---|
| Landing page | `/`, with headline, how it works, pricing (Starter $29/mo, Pro $59/mo, Done-for-you setup $299) and a "Request setup" form |
| Onboarding | `POST /api/onboard {url}` scrapes up to 8 pages of the site (JSON-LD, tel/mailto links, hours tables, price lines, FAQ blocks, services pages). It always creates an assistant: if the scrape fails, the owner fills a manual form |
| Public demo | `/demo/<slug>` shows what the assistant learned and opens the chat widget |
| Widget | `<script src="https://YOUR-DOMAIN/widget.js" data-bot="<slug>" defer></script>`. It runs in a Shadow DOM (no CSS clashes), works cross-origin and includes the booking form |
| Answers | With `OPENAI_API_KEY`: OpenAI (default `gpt-4o-mini`), grounded only on the scraped data. Without a key, or if the API fails: rule-based intents (hours, prices, services, contact, address, booking) plus FAQ matching plus BM25 retrieval over the site text |
| Dashboard | `/dashboard/<slug>?key=<secret>` lists booking requests, the embed snippet and email status. `/edit/<slug>?key=` is the manual edit form |
| Notifications | SMTP via env vars. Without SMTP every email is written to `data/outbox.jsonl` and to the log (mock mode) |
| Payments | Plan buttons use `STRIPE_LINK_*` Payment Links. If none are set, they open the "Request setup" form, which emails `shipfastlabs.dev@gmail.com` |
| Admin | `/admin?token=ADMIN_TOKEN` shows all assistants and setup requests |
| Seeded demos | `seed/demos/*.json` is loaded at every boot, so demo links survive restarts on hosts with ephemeral disks |

Stack: Python 3.10+ standard-library HTTP server with SQLite. `requests` and `beautifulsoup4` handle scraping. No build step and no framework.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env        # optional, everything works with no env vars
python server.py            # http://localhost:8090
```

Open http://localhost:8090, enter a business website, open the demo, chat and send a booking request, then open the dashboard link.

## Environment variables

See `.env.example` for the full list. The main ones:

| Variable | Purpose |
|---|---|
| `PUBLIC_BASE_URL` | Public URL used in links and the embed snippet (e.g. `https://bookbot.onrender.com`) |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` | AI answers. Leave empty for rule-based answers |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Email alerts. Gmail: `smtp.gmail.com`, port 465, plus an App Password |
| `SETUP_REQUEST_TO` | Where "Request setup" goes (default `shipfastlabs.dev@gmail.com`) |
| `STRIPE_LINK_STARTER`, `STRIPE_LINK_PRO`, `STRIPE_LINK_SETUP` | Stripe Payment Link URLs for the pricing buttons |
| `ADMIN_TOKEN` | Protects `/admin` |
| `SEED_ADMIN_SECRET` | Dashboard key for a seeded demo = `HMAC_SHA256(secret, slug)[:32]` |
| `DATABASE_PATH` / `DATA_DIR` | SQLite location (default `data/bookbot.db`) |

## Deploy

**Render (free plan, one click):** push this repo to GitHub, then in the Render dashboard go to New, then Blueprint, pick the repo, and Apply.
`render.yaml` sets up a free Python web service with `/healthz`. Then set `PUBLIC_BASE_URL`, plus SMTP, Stripe and OpenAI if you have them.
Free-plan limits: the service sleeps after about 15 minutes idle (the first request takes 30-60 s), and the disk is ephemeral, so assistants created
from the landing page and their bookings reset on restart. Seeded demos reload every boot, and every booking is also emailed once SMTP is set.
For paying clients, use a paid instance with a persistent disk (`DATABASE_PATH=/var/data/bookbot.db`).

**Docker / any VPS:**
```bash
docker build -t bookbot . && docker run -d -p 80:8090 --env-file .env -v bookbot-data:/app/data bookbot
```

## Demo assistants for a prospect list

```bash
python scripts/make_demos.py prospects.csv --out /tmp/raw.csv          # CSV needs columns: business, site
python server.py &                                                        # (restart so new seeds load)
python scripts/verify_demos.py --sales prospects.csv --out demo-links.csv --base https://YOUR-DOMAIN
```
`seed/overrides.json` holds hand-curated corrections (cleaner services list, single-location hours/phone, or `hours_note` when a site lists no hours), using only facts from each business's own site. Rows whose outreach `status` says bounced or skipped are left out. Demos removed from `seed/demos/` disappear on the next boot.
The demo pages state that they were generated from the business's public website and are not installed on it.

## Tests

```bash
python tests/test_e2e.py            # fixture site -> onboarding -> chat -> booking -> dashboard -> SMTP (local sink) -> setup request -> manual edit
python tests/test_openai_mock.py    # OpenAI code path against a local mock + fallback to rules
python tests/browser_test.py http://localhost:8090 https://some-business.com   # real Chrome via Playwright (optional)
```

## Security notes

- Dashboard and edit links contain a random per-business secret. Demo pages never include it.
- The scraper refuses private, loopback and link-local addresses (SSRF guard). It caps size, pages and time.
- Rate limits apply per IP on onboarding, chat, booking and setup requests. Honeypot fields are on the public forms.
- No secrets are in the repo. Use env vars or `.env` (git-ignored).

## License

MIT
