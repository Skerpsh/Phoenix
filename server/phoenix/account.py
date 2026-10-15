"""Your personal Telegram account (via Telethon) — used to deliver packages."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from telethon import TelegramClient, errors, events, functions, types

from .config import Config

MESSAGE_LIMIT = 4000
TELEGRAM_SERVICE_ID = 777000  # the official "Telegram" account (login codes, notices)


class ScheduleRejected(Exception):
    """Telegram refused to hold the message (too many scheduled in a chat, or too far ahead)."""


def display_name(entity) -> str:
    name = " ".join(filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]))
    name = name or getattr(entity, "title", None) or str(entity.id)
    username = getattr(entity, "username", None)
    return f"{name} (@{username})" if username else name


def utf16_len(text: str) -> int:
    """Telegram measures message length in UTF-16 code units (most emoji count as two)."""
    return len(text.encode("utf-16-le")) // 2


def _fitting_chars(text: str, limit: int) -> int:
    units = 0
    for i, ch in enumerate(text):
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > limit:
            return i
    return len(text)


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Split into messages Telegram accepts, preferably at paragraph, line or word breaks."""
    chunks, rest = [], text.strip()
    while utf16_len(rest) > limit:
        window = rest[: _fitting_chars(rest, limit)]
        cut = next((c for c in (window.rfind("\n\n"), window.rfind("\n"), window.rfind(" ")) if c > 0), len(window))
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        chunks.append(rest)
    return chunks


class Account:
    def __init__(self, cfg: Config):
        self.client = TelegramClient(str(cfg.session_path), cfg.api_id, cfg.api_hash)
        # Always wait out flood limits instead of failing a delivery.
        self.client.flood_sleep_threshold = 24 * 3600
        self.ttl_days: int | None = None  # "delete my account if away for", from the last health check

    async def connect(self) -> None:
        await self.client.connect()
        if await self.client.is_user_authorized():
            await self.client.get_me()  # starts the update stream

    async def disconnect(self) -> None:
        await self.client.disconnect()

    async def health(self) -> tuple[bool, str]:
        try:
            if not self.client.is_connected():
                await self.client.connect()
            if not await self.client.is_user_authorized():
                return False, "session is not logged in (on your computer: phoenix → Server → Log in to Telegram again)"
            me = await self.client.get_me()
            ttl = await self.client(functions.account.GetAccountTTLRequest())
            self.ttl_days = ttl.days
            return True, f"logged in as {display_name(me)}; account self-destruct after {ttl.days} days offline"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    # ------------------------------------------------------------- recipients
    async def resolve(self, target: str) -> tuple[int, str]:
        """target: @username, +phone (must be in your contacts) or numeric id."""
        t = target.strip()
        entity = await self.client.get_entity(int(t) if t.lstrip("-").isdigit() else t)
        if getattr(entity, "deleted", False):
            raise ValueError("this Telegram account was deleted")
        return entity.id, display_name(entity)

    async def input_peer(self, user_id: int):
        return await self.client.get_input_entity(user_id)

    # ---------------------------------------------------------------- sending
    async def send(
        self, peer, *, text: str | None = None, path: Path | None = None, kind: str = "file",
        schedule: float | None = None,
    ) -> list[int]:
        """Send now, or hand to Telegram's own scheduler when `schedule` (unix time) is given."""
        when = datetime.fromtimestamp(schedule, UTC) if schedule else None
        try:
            if text is not None:
                ids = []
                for chunk in split_text(text):
                    m = await self.client.send_message(peer, chunk, parse_mode=None, link_preview=False, schedule=when)
                    ids.append(m.id)
                return ids
            options = {"voice": {"voice_note": True}, "round": {"video_note": True}}.get(kind, {"force_document": True})
            m = await self.client.send_file(peer, str(path), schedule=when, **options)
            return [m.id]
        except (errors.ScheduleTooMuchError, errors.ScheduleDateTooLateError) as e:
            raise ScheduleRejected(str(e)) from e

    async def delete_scheduled(self, user_id: int, ids: list[int]) -> None:
        peer = await self.client.get_input_entity(user_id)
        await self.client(functions.messages.DeleteScheduledMessagesRequest(peer=peer, id=ids))

    async def was_read(self, user_id: int, since: float) -> bool:
        """Did the recipient read the first message you sent them after `since`?"""
        peer = await self.client.get_input_entity(user_id)
        res = await self.client(functions.messages.GetPeerDialogsRequest(peers=[types.InputDialogPeer(peer=peer)]))
        read_up_to = res.dialogs[0].read_outbox_max_id
        start = datetime.fromtimestamp(since, UTC)
        async for m in self.client.iter_messages(peer, offset_date=start, reverse=True, from_user="me", limit=1):
            return read_up_to >= m.id
        return False

    # ---------------------------------------------------------------- profile
    async def set_about(self, text: str) -> str:
        """Replace your bio; returns the previous one."""
        full = await self.client(functions.users.GetFullUserRequest(types.InputUserSelf()))
        await self.client(functions.account.UpdateProfileRequest(about=text))
        return full.full_user.about or ""

    # ----------------------------------------------------------------- events
    def on_outgoing(self, callback: Callable[[], None]) -> None:
        async def handler(event):
            callback()

        self.client.add_event_handler(handler, events.NewMessage(outgoing=True))

    def on_private_incoming(self, callback: Callable[[int, object], Awaitable[None]]) -> None:
        async def handler(event):
            sender = await event.get_sender()
            if (sender is None or getattr(sender, "bot", False) or getattr(sender, "is_self", False)
                    or getattr(sender, "support", False) or sender.id == TELEGRAM_SERVICE_ID):
                return
            await callback(sender.id, sender)

        self.client.add_event_handler(handler, events.NewMessage(incoming=True, func=lambda e: e.is_private))
