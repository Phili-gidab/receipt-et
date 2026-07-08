"""Receipt Telegram bot — issue MoR-registered fiscal receipts from chat.

A merchant channel mirroring the web POS: link your business once (phone +
OTP, same dev stub as /app/login), then type a sale and get the registered
receipt back — QR, IRN/RRN, and the public share link a customer can open.

    2 Macchiato 80
    1 Croissant 120

Runs as its own process (``python -m app.telegram_bot``) next to uvicorn,
sharing the same database and :mod:`app.pos` / :mod:`app.registration` code
path as the web POS. Uses **long polling** — no public HTTPS endpoint or
webhook cert needed, which suits the 2 Mbps Ethio Telecom host and local dev.

Config (env):
    TELEGRAM_BOT_TOKEN   — required; from @BotFather.
    PUBLIC_BASE_URL      — base for share links (default http://localhost:8000).

Handlers are async (python-telegram-bot v21+); all DB/MoR work is sync by
design (byte-exact requests parity), so it runs in a worker thread via
``asyncio.to_thread`` and returns plain dicts — never live ORM objects.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
from datetime import datetime

from sqlalchemy import select
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app import pos, reports
from app.db import SessionLocal, engine
from app.models import Document, FiscalStatus, Merchant, TelegramAccount
from app.webapp import _find_merchant_by_phone, share_token

logger = logging.getLogger("receipt.telegram")

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# Conversation states.
LINK_PHONE, LINK_CODE = range(2)
SALE_ITEMS, SALE_PAYMENT, SALE_BUYER, SALE_CONFIRM = range(2, 6)

MENU_KEYBOARD = ReplyKeyboardMarkup(
    [["🧾 New sale", "📊 Z-report"], ["🗂 Receipts", "❓ Help"]],
    resize_keyboard=True,
)

STATUS_EMOJI = {
    FiscalStatus.REGISTERED.value: "✅",
    FiscalStatus.FAILED.value: "❌",
    FiscalStatus.PENDING.value: "⏳",
    FiscalStatus.CANCELLED.value: "🚫",
    FiscalStatus.NOT_REGISTERED.value: "▫️",
}

HELP_TEXT = (
    "*Receipt — fiscal receipts from Telegram*\n\n"
    "Send a sale as one item per line:\n"
    "`2 Macchiato 80`\n"
    "`1 Croissant 120`\n"
    "(quantity is optional — `Macchiato 80` sells one)\n\n"
    "I register it with MoR and send back the QR receipt "
    "with its IRN and a share link for your customer.\n\n"
    "/sale — start a sale\n"
    "/receipts — recent documents\n"
    "/zreport — today's day-close summary (or `/zreport 2026-07-06`)\n"
    "/unlink — disconnect this Telegram account\n"
    "/cancel — abort the current flow"
)


# --------------------------------------------------------------------------- #
# Sale-line parsing (pure — unit-tested in tests/test_telegram_bot.py)
# --------------------------------------------------------------------------- #
# "2 Macchiato 80" / "2x Macchiato 80" / "Macchiato 80" / "Suit dry-clean 1,500.50"
_LINE_RE = re.compile(
    r"^\s*(?:(?P<qty>\d+(?:\.\d+)?)\s*[x×]?\s+)?(?P<name>.+?)\s+(?P<price>\d[\d,]*(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


def parse_sale_lines(text: str) -> list[dict]:
    """Parse chat text into cart lines for :func:`app.pos.checkout_sale`.

    Raises ``ValueError`` naming the first line that doesn't parse.
    """
    lines = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = _LINE_RE.match(raw)
        if not m:
            raise ValueError(raw)
        name = m.group("name").strip(" -–·")
        price = float(m.group("price").replace(",", ""))
        qty = float(m.group("qty")) if m.group("qty") else 1.0
        if not name or price <= 0 or qty <= 0:
            raise ValueError(raw)
        lines.append({"name": name, "price": price, "qty": qty})
    if not lines:
        raise ValueError("(empty)")
    return lines


def fmt_etb(x: float) -> str:
    return f"{x:,.2f}"


def md_escape(s: str) -> str:
    """Escape user-supplied text for legacy-Markdown messages."""
    for ch in ("\\", "_", "*", "`", "["):
        s = s.replace(ch, f"\\{ch}")
    return s


def cart_summary(lines: list[dict]) -> str:
    rows = [
        f"• {li['qty']:g} × {md_escape(li['name'])} @ {fmt_etb(li['price'])}"
        for li in lines
    ]
    total = sum(li["price"] * li["qty"] for li in lines)
    return "\n".join(rows) + f"\n\n*Total: {fmt_etb(total)} ETB*"


def share_url(doc_id: int) -> str:
    return f"{PUBLIC_BASE_URL}/r/{doc_id}/{share_token(doc_id)}"


# --------------------------------------------------------------------------- #
# Sync DB workers (run via asyncio.to_thread) — return plain dicts only
# --------------------------------------------------------------------------- #
def _db_get_link(tg_user_id: int) -> dict | None:
    with SessionLocal() as db:
        acct = db.get(TelegramAccount, tg_user_id)
        if acct is None:
            return None
        merchant = db.get(Merchant, acct.merchant_id)
        if merchant is None:
            return None
        return {"merchant_id": merchant.id, "legal_name": merchant.legal_name, "tin": merchant.tin}


def _db_find_merchant(ident: str) -> dict | None:
    with SessionLocal() as db:
        m = _find_merchant_by_phone(db, ident)
        if m is None:
            return None
        return {"merchant_id": m.id, "legal_name": m.legal_name, "tin": m.tin}


def _db_link(tg_user_id: int, chat_id: int, merchant_id: int, display_name: str) -> None:
    with SessionLocal() as db:
        acct = db.get(TelegramAccount, tg_user_id)
        if acct is None:
            acct = TelegramAccount(telegram_user_id=tg_user_id)
            db.add(acct)
        acct.merchant_id = merchant_id
        acct.chat_id = chat_id
        acct.display_name = display_name[:255] if display_name else None
        db.commit()


def _db_unlink(tg_user_id: int) -> bool:
    with SessionLocal() as db:
        acct = db.get(TelegramAccount, tg_user_id)
        if acct is None:
            return False
        db.delete(acct)
        db.commit()
        return True


def _db_checkout(merchant_id: int, lines: list[dict], payment_method: str, buyer_tin: str) -> dict:
    """Register the sale (invoice + best-effort receipt); summarize for chat."""
    with SessionLocal() as db:
        merchant = db.get(Merchant, merchant_id)
        if merchant is None:
            return {"ok": False, "error": "Business no longer exists — /unlink and link again."}
        try:
            doc = pos.checkout_sale(
                db, merchant, lines,
                payment_method=payment_method, buyer_tin=buyer_tin, ref_prefix="TG",
            )
        except Exception as exc:  # RegistrationError, missing secrets, transport, …
            return {"ok": False, "error": str(exc)[:400]}

        rcp = db.execute(
            select(Document).where(
                Document.merchant_id == merchant.id,
                Document.transaction_ref == f"RCP-{doc.transaction_ref}",
            )
        ).scalar_one_or_none()

        # Report what MoR actually registered (wire payload), not our estimate.
        try:
            vals = (json.loads(doc.payload_json or "{}").get("ValueDetails")) or {}
        except Exception:
            vals = {}
        return {
            "ok": doc.fiscal_status == FiscalStatus.REGISTERED and bool(doc.irn),
            "error": (doc.error or "registration failed")[:400],
            "doc_id": doc.id,
            "doc_no": doc.document_number,
            "irn": doc.irn,
            "rrn": (rcp.rrn if rcp is not None and rcp.fiscal_status == FiscalStatus.REGISTERED else None),
            "total": float(vals.get("TotalValue") or doc.amount or 0),
            "vat": float(vals.get("TaxValue") or 0),
            "qr_b64": doc.qr_b64,
            "merchant_name": merchant.legal_name,
        }


def _db_recent_docs(merchant_id: int, limit: int = 8) -> list[dict]:
    with SessionLocal() as db:
        docs = db.execute(
            select(Document).where(Document.merchant_id == merchant_id)
            .order_by(Document.created_at.desc()).limit(limit)
        ).scalars()
        return [{
            "id": d.id,
            "doc_type": d.doc_type,
            "doc_no": d.document_number,
            "status": d.fiscal_status.value,
            "amount": float(d.amount or 0),
            "created_at": (d.created_at.astimezone(reports.ADDIS_TZ).strftime("%d %b %H:%M")
                           if d.created_at else ""),
            "registered": d.fiscal_status == FiscalStatus.REGISTERED,
        } for d in docs]


def _db_zreport(merchant_id: int, day_iso: str | None) -> dict | None:
    with SessionLocal() as db:
        merchant = db.get(Merchant, merchant_id)
        if merchant is None:
            return None
        day = None
        if day_iso:
            try:
                day = datetime.strptime(day_iso, "%Y-%m-%d").date()
            except ValueError:
                day = None
        z = reports.zreport_for_day(db, merchant, day)
        return {
            "day": z.day.strftime("%d %b %Y"),
            "inv_count": z.inv_count, "gross": z.gross, "refunds": z.refunds,
            "net": z.net, "vat_out": z.vat_out, "rcp_count": z.rcp_count,
            "voided": z.voided_count, "failed": z.failed_count,
            "legal_name": merchant.legal_name,
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _link_of(update: Update) -> dict | None:
    return await asyncio.to_thread(_db_get_link, update.effective_user.id)


async def _require_link(update: Update) -> dict | None:
    link = await _link_of(update)
    if link is None:
        await update.effective_message.reply_text(
            "This Telegram account isn't linked to a business yet — send /start to link it."
        )
    return link


# --------------------------------------------------------------------------- #
# Linking conversation (/start → phone → OTP)
# --------------------------------------------------------------------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link = await _link_of(update)
    if link is not None:
        await update.message.reply_text(
            f"Linked to *{md_escape(link['legal_name'])}* (TIN {link['tin']}).\n"
            "Type a sale (one item per line, e.g. `2 Macchiato 80`) or use the menu.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MENU_KEYBOARD,
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "Welcome to *Receipt* — MoR e-receipts from Telegram.\n\n"
        "Let's link your business: what's the *phone number* (or 10-digit TIN) "
        "it is registered with?",
        parse_mode=ParseMode.MARKDOWN,
    )
    return LINK_PHONE


async def link_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ident = (update.message.text or "").strip()
    found = await asyncio.to_thread(_db_find_merchant, ident)
    if found is None:
        await update.message.reply_text(
            "No business found for that number. Try again, or sign up first at "
            f"{PUBLIC_BASE_URL}/app/signup — then come back and /start."
        )
        return LINK_PHONE
    context.user_data["pending_link"] = found
    # DEV STUB: parity with the web login — a real build texts a random code.
    # TIN is masked pre-OTP so phone-number probing can't harvest identities.
    await update.message.reply_text(
        f"Found *{md_escape(found['legal_name'])}* (TIN ••••••{found['tin'][-4:]}).\n"
        "Enter the 6-digit verification code.\n_(sandbox build: use 000000)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return LINK_CODE


async def link_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = (update.message.text or "").strip()
    pending = context.user_data.get("pending_link")
    if pending is None:
        await update.message.reply_text("Session lost — send /start to begin again.")
        return ConversationHandler.END
    # DEV STUB: accept any 6 digits (same rule as the web /app/verify).
    if not (code.isdigit() and len(code) == 6):
        await update.message.reply_text("That doesn't look like a 6-digit code — try again.")
        return LINK_CODE
    user = update.effective_user
    await asyncio.to_thread(
        _db_link, user.id, update.effective_chat.id, pending["merchant_id"], user.full_name or ""
    )
    context.user_data.pop("pending_link", None)
    await update.message.reply_text(
        f"✅ Linked to *{md_escape(pending['legal_name'])}*.\n\n"
        "Type a sale to issue a fiscal receipt — one item per line:\n"
        "`2 Macchiato 80`\n`1 Croissant 120`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MENU_KEYBOARD,
    )
    return ConversationHandler.END


async def unlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    removed = await asyncio.to_thread(_db_unlink, update.effective_user.id)
    await update.message.reply_text(
        "Unlinked — this Telegram account can no longer issue receipts. /start to relink."
        if removed else "This account wasn't linked. /start to link it."
    )


# --------------------------------------------------------------------------- #
# Sale conversation (items → payment → buyer TIN → confirm → register)
# --------------------------------------------------------------------------- #
def _payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💵 Cash", callback_data="pay:CASH"),
        InlineKeyboardButton("📱 Telebirr", callback_data="pay:TELEBIRR"),
        InlineKeyboardButton("💳 Credit", callback_data="pay:CREDIT"),
    ]])


async def _ask_payment(message, lines: list[dict]) -> None:
    await message.reply_text(
        cart_summary(lines) + "\n\nHow is the customer paying?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_payment_keyboard(),
    )


async def sale_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry: /sale, the menu button, or any text that parses as sale lines."""
    if await _require_link(update) is None:
        return ConversationHandler.END
    text = update.message.text or ""
    if not text.startswith("/") and text != "🧾 New sale":
        # Fast path: the message itself is the cart.
        try:
            lines = parse_sale_lines(text)
        except ValueError:
            await update.message.reply_text(
                "I didn't understand that. Send a sale as one item per line, e.g.\n"
                "`2 Macchiato 80`\n`1 Croissant 120`\n\nor use /help.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ConversationHandler.END
        context.user_data["sale_lines"] = lines
        await _ask_payment(update.message, lines)
        return SALE_PAYMENT
    await update.message.reply_text(
        "New sale — send the items, one per line:\n`2 Macchiato 80`\n`1 Croissant 120`",
        parse_mode=ParseMode.MARKDOWN,
    )
    return SALE_ITEMS


async def sale_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        lines = parse_sale_lines(update.message.text or "")
    except ValueError as exc:
        bad = str(exc).replace("`", "'")  # a stray backtick must not break the reply's markdown
        await update.message.reply_text(
            f"Couldn't read this line: `{bad}`\n"
            "Format: `[qty] item name price` — try again or /cancel.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return SALE_ITEMS
    context.user_data["sale_lines"] = lines
    await _ask_payment(update.message, lines)
    return SALE_PAYMENT


async def sale_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data["sale_payment"] = q.data.split(":", 1)[1]
    await q.message.reply_text(
        "Buyer TIN for a B2B invoice? Send the 10-digit TIN, or skip for a walk-in customer.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Skip →", callback_data="buyer:skip")]]),
    )
    return SALE_BUYER


async def _confirm(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    lines = context.user_data["sale_lines"]
    pay = context.user_data["sale_payment"]
    buyer = context.user_data.get("sale_buyer_tin") or "walk-in"
    await message.reply_text(
        f"{cart_summary(lines)}\nPayment: {pay} · Buyer: {buyer}\n\n"
        "Register this sale with MoR?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Register", callback_data="confirm:yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="confirm:no"),
        ]]),
    )
    return SALE_CONFIRM


async def sale_buyer_tin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tin = "".join(ch for ch in (update.message.text or "") if ch.isdigit())
    if len(tin) != 10:
        await update.message.reply_text(
            "A TIN is 10 digits — try again, or tap Skip above for a walk-in sale."
        )
        return SALE_BUYER
    context.user_data["sale_buyer_tin"] = tin
    return await _confirm(update.message, context)


async def sale_buyer_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data["sale_buyer_tin"] = ""
    return await _confirm(q.message, context)


async def sale_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data == "confirm:no":
        context.user_data.pop("sale_lines", None)
        await q.message.reply_text("Cancelled — nothing was registered.", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END

    link = await _link_of(update)
    if link is None:
        await q.message.reply_text("Not linked — /start first.")
        return ConversationHandler.END

    try:
        await q.edit_message_reply_markup(reply_markup=None)  # freeze the buttons
    except Exception:
        pass  # message too old / already edited — registration still proceeds
    progress = await q.message.reply_text("⏳ Registering with MoR…")
    res = await asyncio.to_thread(
        _db_checkout,
        link["merchant_id"],
        context.user_data.get("sale_lines") or [],
        context.user_data.get("sale_payment") or "CASH",
        context.user_data.get("sale_buyer_tin") or "",
    )
    for k in ("sale_lines", "sale_payment", "sale_buyer_tin"):
        context.user_data.pop(k, None)

    if not res.get("ok"):
        await progress.edit_text(f"❌ MoR rejected the sale:\n{res.get('error')}")
        return ConversationHandler.END

    caption = (
        f"✅ *Registered with MoR*\n"
        f"{md_escape(res['merchant_name'])}\n"
        f"INV #{res['doc_no']} · {fmt_etb(res['total'])} ETB (VAT {fmt_etb(res['vat'])})\n"
        f"IRN: `{res['irn']}`\n"
        + (f"RRN: `{res['rrn']}`\n" if res.get("rrn") else "")
        + f"\nCustomer receipt:\n{share_url(res['doc_id'])}"
    )
    # The sale IS registered at this point — every path below must end in the
    # merchant seeing the ✅, never an error (an error invites a re-send, and a
    # fresh transaction_ref would register a REAL duplicate on the MoR chain).
    sent = False
    if res.get("qr_b64"):
        try:
            png = base64.b64decode(res["qr_b64"])
            await q.message.reply_photo(
                photo=io.BytesIO(png), caption=caption,
                parse_mode=ParseMode.MARKDOWN, reply_markup=MENU_KEYBOARD,
            )
            sent = True
            await progress.delete()  # only after the photo is delivered
        except Exception:
            if sent:  # photo delivered; only the cleanup delete failed
                return ConversationHandler.END
            logger.exception("failed to send QR photo for doc %s", res.get("doc_id"))
    if not sent:
        try:
            await progress.edit_text(caption, parse_mode=ParseMode.MARKDOWN)
        except Exception:  # markdown edge case — deliver plain rather than fail
            logger.exception("markdown caption failed for doc %s", res.get("doc_id"))
            await progress.edit_text(caption.replace("*", "").replace("`", ""))
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for k in ("sale_lines", "sale_payment", "sale_buyer_tin", "pending_link"):
        context.user_data.pop(k, None)
    await update.message.reply_text("Cancelled.", reply_markup=MENU_KEYBOARD)
    return ConversationHandler.END


async def nudge_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Text arrived where a button tap was expected — say so instead of silence."""
    await update.message.reply_text(
        "Tap one of the buttons above to continue — or /cancel to abort this sale."
    )
    return None  # stay in the current state


async def stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Buttons from before a restart (or an ended flow) — stop the spinner."""
    q = update.callback_query
    await q.answer("This session has expired.")
    if update.effective_chat is not None:
        await context.bot.send_message(
            update.effective_chat.id,
            "That button is from an old session — send the sale again to restart.",
            reply_markup=MENU_KEYBOARD,
        )


# --------------------------------------------------------------------------- #
# Reports & history
# --------------------------------------------------------------------------- #
async def receipts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    link = await _require_link(update)
    if link is None:
        return
    docs = await asyncio.to_thread(_db_recent_docs, link["merchant_id"])
    if not docs:
        await update.message.reply_text("No documents yet — type a sale to issue the first one.")
        return
    rows = []
    for d in docs:
        line = (
            f"{STATUS_EMOJI.get(d['status'], '▫️')} {d['doc_type']}"
            f"{(' #' + d['doc_no']) if d['doc_no'] else ''}"
            f" · {fmt_etb(d['amount'])} ETB · {d['created_at']}"
        )
        if d["registered"]:
            line += f"\n{share_url(d['id'])}"
        rows.append(line)
    await update.message.reply_text("🗂 Recent documents\n\n" + "\n\n".join(rows))


async def zreport_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    link = await _require_link(update)
    if link is None:
        return
    day_arg = context.args[0] if context.args else None
    z = await asyncio.to_thread(_db_zreport, link["merchant_id"], day_arg)
    if z is None:
        await update.message.reply_text("Business not found — /unlink and link again.")
        return
    await update.message.reply_text(
        f"📊 *Z-report — {z['day']}*\n"
        f"{md_escape(z['legal_name'])}\n\n"
        f"Sales (registered): {z['inv_count']} · {fmt_etb(z['gross'])} ETB\n"
        f"Refunds: {fmt_etb(z['refunds'])} ETB\n"
        f"*Net: {fmt_etb(z['net'])} ETB*\n"
        f"VAT out: {fmt_etb(z['vat_out'])} ETB\n"
        f"Payment receipts: {z['rcp_count']}\n"
        f"Voided: {z['voided']} · Failed: {z['failed']}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN, reply_markup=MENU_KEYBOARD)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("bot error handling update: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Something went wrong — try again or /cancel.")
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #
async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        ("start", "Link your business / show menu"),
        ("sale", "Issue a fiscal receipt"),
        ("receipts", "Recent documents"),
        ("zreport", "Day-close summary"),
        ("unlink", "Disconnect this Telegram account"),
        ("cancel", "Abort the current flow"),
        ("help", "How to use the bot"),
    ])
    logger.info("receipt telegram bot up (base url %s)", PUBLIC_BASE_URL)


def build_application(token: str) -> Application:
    application = Application.builder().token(token).post_init(_post_init).build()

    link_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LINK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, link_phone)],
            LINK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, link_code)],
        },
        # /start mid-flow restarts the flow instead of being silently ignored.
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )

    sale_conv = ConversationHandler(
        entry_points=[
            CommandHandler("sale", sale_entry),
            MessageHandler(filters.Regex(r"^🧾 New sale$"), sale_entry),
            # Any other text: try to read it as a cart (fast path for regulars).
            MessageHandler(filters.TEXT & ~filters.COMMAND, sale_entry),
        ],
        states={
            SALE_ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_items)],
            SALE_PAYMENT: [
                CallbackQueryHandler(sale_payment, pattern=r"^pay:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, nudge_buttons),
            ],
            SALE_BUYER: [
                CallbackQueryHandler(sale_buyer_skip, pattern=r"^buyer:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, sale_buyer_tin),
            ],
            SALE_CONFIRM: [
                CallbackQueryHandler(sale_confirm, pattern=r"^confirm:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, nudge_buttons),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            CommandHandler("sale", sale_entry),  # /sale mid-flow restarts the sale
        ],
    )

    # Menu buttons match their exact labels so ordinary sale lines never
    # collide with them (they are checked before the sale catch-all).
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(MessageHandler(filters.Regex(r"^❓ Help$"), help_cmd))
    application.add_handler(CommandHandler("receipts", receipts_cmd))
    application.add_handler(MessageHandler(filters.Regex(r"^🗂 Receipts$"), receipts_cmd))
    application.add_handler(CommandHandler("zreport", zreport_cmd))
    application.add_handler(MessageHandler(filters.Regex(r"^📊 Z-report$"), zreport_cmd))
    application.add_handler(CommandHandler("unlink", unlink))
    application.add_handler(link_conv)
    application.add_handler(sale_conv)
    # After the conversations: /cancel outside any flow still answers (inside a
    # flow the conversation's own fallback wins), and button taps that no
    # conversation claims (pre-restart messages, ended flows) stop spinning.
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(stale_callback))
    application.add_error_handler(on_error)
    return application


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and put the "
            "token in fiscal-core/.env (see .env.example)."
        )
    if os.environ.get("SESSION_SECRET", "dev-only-change-me") == "dev-only-change-me":
        logger.warning(
            "SESSION_SECRET is the built-in default — share links are guessable "
            "and won't match a web app configured with a real secret. Set it in .env."
        )
    # Idempotent — only creates missing tables (telegram_accounts on first run).
    from app.db import Base
    from app import models  # noqa: F401  (register all tables on Base)
    Base.metadata.create_all(engine)

    # Only what the handlers actually consume — in particular NO edited_message
    # (handlers read update.message, which is None on edits and would crash).
    build_application(token).run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
