# Receipt Telegram bot — merchant channel

Issue MoR-registered fiscal receipts from Telegram. The bot is a thin client
over the same fiscal core as the web POS: same database, same
`app.pos.checkout_sale` → `app.registration` path, same per-merchant chain and
idempotency rules. Code: `fiscal-core/app/telegram_bot.py`.

## What it does

| Flow | How |
|---|---|
| Link a business | `/start` → phone (or TIN) → 6-digit OTP (dev stub `000000`) → durable link (`telegram_accounts` table) |
| Issue a sale | Type items, one per line: `2 Macchiato 80` — or `/sale` / the menu button. Payment buttons (Cash / Telebirr / Credit) → optional buyer TIN (B2B) → confirm → registers invoice **+ paying sales receipt** with MoR → replies with QR photo, IRN/RRN, and the public `/r/{id}/{token}` share link |
| History | `/receipts` — last 8 documents with status + share links |
| Day close | `/zreport` (today, Addis time) or `/zreport 2026-07-06` |
| Disconnect | `/unlink` · abort any flow with `/cancel` |

The sale fast path: any plain text that parses as sale lines starts a sale
immediately — regulars never need a command. Quantity is optional
(`Macchiato 80` sells one); `2x`, `2 ×`, decimals (`0.5 Kilo coffee 800`) and
`1,500.50` prices all parse. Telegram sales carry the `TG-` transaction-ref
prefix (web = `POS-`, landing demo = `DEMO-`).

## Setup

1. Create the bot: talk to **@BotFather** → `/newbot` → copy the token.
2. `fiscal-core/.env`:

   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-...
   PUBLIC_BASE_URL=http://63.185.125.177     # base for customer share links
   ```

3. Run it (its own process next to uvicorn — **long polling**, so no public
   HTTPS/webhook/cert is needed; suits the 2 Mbps Ethio Telecom host):

   ```bash
   # local dev
   cd fiscal-core && python -m app.telegram_bot

   # docker compose (service "bot" is in docker-compose.yml)
   docker compose up -d bot
   ```

   On startup it runs `create_all` — the only new table is
   `telegram_accounts`, so it is safe against the deployed EC2 database
   (no ALTERs of existing tables).

## Before production (deliberate sandbox trade-offs)

- **Real OTP.** The link flow uses the same dev stub as `/app/login` (any 6
  digits). Unlike a web session, a Telegram link is *durable* — with the stub,
  anyone knowing a merchant's phone number can permanently link themselves and
  issue real fiscal documents on that merchant's MoR chain. Wire SMS/Telegram
  OTP before any real merchant onboards. (Pre-OTP, the bot masks the TIN and
  the web's `_find_merchant_by_phone` single-merchant fallback should go.)
- **Rate limiting** on link attempts (phone enumeration) and per-merchant sale
  registration — none today, matching the web POS.
- **`SESSION_SECRET`** must be set (and identical for the web + bot services):
  share-link tokens are HMACs over it; the bot logs a warning when it's the
  default.
- Updates are processed **sequentially** (one MoR round-trip at a time across
  all chats) — fine at pilot scale; revisit `concurrent_updates` with per-chat
  ordering if the bot ever serves many busy merchants.

## Design notes

- **Async handlers, sync core.** python-telegram-bot v21+ is async; the MoR
  transport is deliberately sync (byte-exact parity with the validated Delta
  client). All DB/MoR work runs via `asyncio.to_thread`, one short-lived
  `SessionLocal()` per operation, and returns **plain dicts** — never live ORM
  objects across the thread boundary.
- **Share links** are HMAC-signed with `SESSION_SECRET`. The bot and web
  containers must share the same `SESSION_SECRET` (both read
  `fiscal-core/.env`) or bot-issued links will 404 on the web app.
- **OTP is the same dev stub as `/app/login`** (accepts any 6 digits, hint
  shows `000000`). Before prod: wire a real SMS/Telegram OTP — the bot link is
  *durable*, so this matters more here than on the web.
- Sale-line parsing is unit-tested in `tests/test_telegram_bot.py`; the shared
  checkout semantics in `tests/test_pos.py`.
