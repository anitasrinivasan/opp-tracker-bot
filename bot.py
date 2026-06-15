"""Telegram bot: handlers, message routing, album buffering, edit flow.

Async long-polling (no webhook). Single-user — locked to an owner allowlist.
Write rows immediately, confirm after, allow lightweight correction.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import get_args

from anthropic import AsyncAnthropic
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

import sources
import store
from config import Config, get_config
from extract import extract
from models import Category, EDITABLE_FIELDS, Opportunity, Status

logger = logging.getLogger(__name__)

ALBUM_DEBOUNCE = 2.0  # seconds to wait after the last photo of an album
CATEGORIES = set(get_args(Category))
STATUSES = set(get_args(Status))
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_CONTINUATION = {"+", "same"}

EDIT_HELP = (
    "What should I change? Reply like `deadline 2026-07-01` or `status applied`.\n"
    "Editable: title, deadline, url, description, category, status."
)


# --- Pure helpers (unit-tested) -------------------------------------------


def extract_urls(text: str, entities=None) -> list[str]:
    """URLs from Telegram entities (preferred) or a regex fallback. Pure."""
    urls: list[str] = []
    text = text or ""
    for ent in entities or []:
        etype = getattr(ent, "type", None)
        if etype == "url":
            off, length = ent.offset, ent.length
            urls.append(text[off : off + length])
        elif etype == "text_link":
            url = getattr(ent, "url", None)
            if url:
                urls.append(url)
    if not urls:
        urls = _URL_RE.findall(text)
    # de-dupe preserving order, strip trailing punctuation
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        u = u.rstrip(").,;]'\"")
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def strip_urls(text: str, urls: list[str]) -> str:
    """Remove URLs from text, returning the prose remainder (or "" if trivial). Pure."""
    out = text or ""
    for u in urls:
        out = out.replace(u, " ")
    out = re.sub(r"\s+", " ", out).strip()
    return out if len(out) >= 3 else ""


def is_continuation_caption(caption: str | None) -> bool:
    """True if a photo caption signals 'merge into the last entry'. Pure."""
    return (caption or "").strip().lower() in _CONTINUATION


def parse_edit_command(text: str) -> tuple[str, str] | None:
    """Parse `<field> <value>` into a validated (field, value), else None. Pure.

    deadline must be YYYY-MM-DD (or none/null to clear); category/status must be
    in their enums. Returns None if it isn't a recognizable, valid edit command.
    """
    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    field_name, value = parts[0].lower(), parts[1].strip()
    if field_name not in EDITABLE_FIELDS:
        return None
    if field_name == "deadline":
        if value.lower() in ("none", "null", "-", "clear"):
            return (field_name, "")
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None
    elif field_name == "category":
        if value.lower() not in CATEGORIES:
            return None
        value = value.lower()
    elif field_name == "status":
        if value.lower() not in STATUSES:
            return None
        value = value.lower()
    return (field_name, value)


def added_reply(opps: list[Opportunity]) -> str:
    """Build the success confirmation. Pure."""
    lines = [f"✅ Added: {o.title} — deadline {o.deadline or '—'}" for o in opps]
    return "\n".join(lines) + '\n\nReply "edit" to correct the last entry.'


# --- Per-chat state --------------------------------------------------------


@dataclass
class ChatState:
    last_row: int | None = None
    last_source_images: list = field(default_factory=list)
    last_source_type: str | None = None
    last_override_url: str | None = None
    awaiting_edit_field: bool = False


def _state(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> ChatState:
    return context.bot_data["chat_state"].setdefault(chat_id, ChatState())


def _today_iso(message) -> str:
    d = getattr(message, "date", None)
    return d.date().isoformat() if d else date.today().isoformat()


# --- Core extract + persist ------------------------------------------------


async def _extract_and_save(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    source_type: str,
    text: str | None = None,
    image_blocks: list[dict] | None = None,
    source_images: list[dict] | None = None,
    override_url: str | None = None,
    today_iso: str | None = None,
) -> None:
    cfg: Config = context.bot_data["cfg"]
    client: AsyncAnthropic = context.bot_data["anthropic"]
    ws = context.bot_data["ws"]
    today_iso = today_iso or date.today().isoformat()

    opps = await extract(client, cfg.model, today_iso, text=text, image_blocks=image_blocks)
    if not opps:
        await context.bot.send_message(
            chat_id,
            "🤔 I couldn't find an opportunity in that. Try pasting the text or a screenshot.",
        )
        return

    last = await store.append_opportunities(ws, opps, source_type, override_url)
    state = _state(context, chat_id)
    state.last_row = last
    state.last_source_type = source_type
    state.last_source_images = source_images or []
    state.last_override_url = override_url
    state.awaiting_edit_field = False
    await context.bot.send_message(chat_id, added_reply(opps))


async def _save_url_only(context, chat_id: int, url: str, reply: str) -> None:
    ws = context.bot_data["ws"]
    row = await store.append_url_only(ws, url, sources.host_label(url))
    state = _state(context, chat_id)
    state.last_row = row
    state.last_source_type = "url"
    state.last_source_images = []
    state.last_override_url = url
    state.awaiting_edit_field = False
    await context.bot.send_message(chat_id, reply)


# --- Handlers --------------------------------------------------------------


async def owner_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global gate: silently ignore anyone not on the allowlist."""
    cfg: Config = context.bot_data["cfg"]
    user = update.effective_user
    if user is None or user.id not in cfg.allowed_user_ids:
        raise ApplicationHandlerStop


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "📌 Opportunity Tracker\n"
        "Send me a job/grant/CFP/fellowship as text, a link, or a screenshot — "
        "I'll parse it and add a row to your sheet.\n"
        "• Multiple screenshots of one listing: send them as an album, "
        "or caption a follow-up photo `+` to merge it.\n"
        '• Reply "edit" to correct the last entry.'
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = (msg.text or "").strip()
    chat_id = update.effective_chat.id
    state = _state(context, chat_id)
    cfg: Config = context.bot_data["cfg"]

    # --- edit flow ---
    if text.lower() == "edit":
        if state.last_row is None:
            await msg.reply_text("Nothing to edit yet — add an opportunity first.")
        else:
            state.awaiting_edit_field = True
            await msg.reply_text(EDIT_HELP)
        return

    edit_cmd = parse_edit_command(text)
    if edit_cmd and (state.awaiting_edit_field or state.last_row is not None):
        if state.last_row is None:
            await msg.reply_text("Nothing to edit yet — add an opportunity first.")
            return
        field_name, value = edit_cmd
        await store.update_field(context.bot_data["ws"], state.last_row, field_name, value)
        state.awaiting_edit_field = False
        await msg.reply_text(f"✏️ Updated {field_name} → {value or '(cleared)'}")
        return

    if state.awaiting_edit_field:
        state.awaiting_edit_field = False
        await msg.reply_text("Couldn't parse that edit. " + EDIT_HELP)
        return

    # --- URL vs plain text ---
    urls = extract_urls(text, msg.entities)
    today_iso = _today_iso(msg)
    if not urls:
        await _extract_and_save(context, chat_id, text=text, source_type="text", today_iso=today_iso)
        return

    url, extras = urls[0], urls[1:]
    note = strip_urls(text, urls)
    kind = sources.classify_url(url)

    if kind == "walled":
        await _save_url_only(
            context,
            chat_id,
            url,
            f"🔒 {sources.host_label(url)} links can't be read directly — saved the link only. "
            "Send a screenshot to fill in details.",
        )
        return

    if kind == "x":
        content = await sources.fetch_x(url, cfg)
    else:
        content = await sources.fetch_generic(url, cfg.user_agent)

    if sources.is_soft_fail(content):
        await _save_url_only(
            context,
            chat_id,
            url,
            "⚠️ Couldn't read that page — saved the link only. Send a screenshot to fill in details.",
        )
        return

    combined = f"User note: {note}\n\n{content}" if note else content
    await _extract_and_save(
        context, chat_id, text=combined, source_type="url", override_url=url, today_iso=today_iso
    )
    if extras:
        await context.bot.send_message(
            chat_id, f"(Ignored {len(extras)} other link(s) — send them separately to capture each.)"
        )


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat_id = update.effective_chat.id
    image_block = await sources.download_photo_as_image_block(msg, context.bot)
    caption = msg.caption or ""

    # Single photo (no album)
    if msg.media_group_id is None:
        if is_continuation_caption(caption):
            await _handle_continuation(context, chat_id, image_block)
            return
        note = caption if not is_continuation_caption(caption) else None
        await _extract_and_save(
            context,
            chat_id,
            image_blocks=[image_block],
            source_images=[image_block],
            source_type="screenshot",
            text=note,
            today_iso=_today_iso(msg),
        )
        return

    # Album: buffer by media_group_id, (re)schedule a debounced flush
    mgid = msg.media_group_id
    buffers = context.bot_data["album_buffers"]
    buf = buffers.setdefault(mgid, {"chat_id": chat_id, "images": [], "date": msg.date})
    buf["images"].append(image_block)

    name = f"album:{mgid}"
    for old in context.job_queue.get_jobs_by_name(name):
        old.schedule_removal()
    context.job_queue.run_once(
        flush_album, ALBUM_DEBOUNCE, name=name, data={"mgid": mgid, "chat_id": chat_id}
    )


async def flush_album(context: ContextTypes.DEFAULT_TYPE) -> None:
    mgid = context.job.data["mgid"]
    chat_id = context.job.data["chat_id"]
    buf = context.bot_data["album_buffers"].pop(mgid, None)  # pop = idempotent dedupe
    if not buf or not buf["images"]:
        return
    when = buf.get("date")
    today_iso = when.date().isoformat() if when else date.today().isoformat()
    await _extract_and_save(
        context,
        chat_id,
        image_blocks=buf["images"],
        source_images=buf["images"],
        source_type="screenshot",
        today_iso=today_iso,
    )


async def _handle_continuation(context, chat_id: int, image_block: dict) -> None:
    state = _state(context, chat_id)
    if state.last_row is None:
        # nothing to merge into — treat as a fresh single photo
        await _extract_and_save(
            context,
            chat_id,
            image_blocks=[image_block],
            source_images=[image_block],
            source_type="screenshot",
        )
        return

    cfg: Config = context.bot_data["cfg"]
    client: AsyncAnthropic = context.bot_data["anthropic"]
    ws = context.bot_data["ws"]
    images = list(state.last_source_images) + [image_block]
    opps = await extract(client, cfg.model, date.today().isoformat(), image_blocks=images)
    if not opps:
        await context.bot.send_message(
            chat_id, "🤔 Couldn't read that screenshot. The previous entry is unchanged."
        )
        return
    primary = opps[0]
    await store.overwrite_row(ws, state.last_row, primary, override_url=state.last_override_url)
    state.last_source_images = images
    await context.bot.send_message(
        chat_id,
        f"🔄 Updated last entry with the extra screenshot: {primary.title} "
        f"— deadline {primary.deadline or '—'}",
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Handler error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id, "⚠️ Something went wrong handling that. Please try again."
            )
        except Exception:  # noqa: BLE001
            pass


# --- Wiring ----------------------------------------------------------------


def build_app(cfg: Config, ws) -> Application:
    app = ApplicationBuilder().token(cfg.telegram_token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["ws"] = ws
    app.bot_data["anthropic"] = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    app.bot_data["chat_state"] = {}
    app.bot_data["album_buffers"] = {}

    app.add_handler(TypeHandler(Update, owner_guard), group=-1)  # global owner gate
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = get_config()
    ws = store.open_worksheet(cfg)
    store.ensure_header_row(ws)
    app = build_app(cfg, ws)
    logger.info("Opportunity Tracker bot starting (model=%s)…", cfg.model)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
