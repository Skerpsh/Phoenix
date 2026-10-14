"""Hands package items to Telegram, item by item.

Every item has a due time (trigger + package delay + item offset, or a fixed date):
  - due now                         → sent immediately;
  - due within HORIZON (~1 year)    → handed to Telegram's own scheduler, so it arrives
                                      even if this server is gone by then;
  - due later                       → kept here and handed over once it is within HORIZON.
Progress is stored, so an interrupted run resumes where it stopped and nothing is sent twice.
"""

import asyncio
import logging
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import tzinfo
from pathlib import Path

from .account import ScheduleRejected
from .crypto import Crypto
from .db import Store
from .durations import fmt
from .packages import Item, Package

log = logging.getLogger(__name__)

HORIZON = 364 * 86400  # Telegram holds scheduled messages for up to a year
MIN_SCHEDULE = 90  # closer than this: just send now

DEFAULT_BACKUP_NOTE = (
    "This was meant for {name}, but they could not be reached, so it is being sent to you instead."
)


class Stopped(Exception):
    pass


@dataclass
class Result:
    failures: list[str] = field(default_factory=list)
    waiting: int = 0  # items still held by this server (too far ahead, or Telegram refused to schedule)


@dataclass
class Run:
    mode: str  # "live" (real recipients) or "test" (everything to your Saved Messages, right away)
    account: object
    crypto: Crypto
    store: Store
    tmp_dir: Path
    tz: tzinfo
    trigger_ts: float
    stop: Callable[[], bool]

    @property
    def test(self) -> bool:
        return self.mode == "test"

    async def deliver(self, packages: list[Package]) -> Result:
        result = Result()
        for pkg in packages:
            targets = [(pkg.hid, pkg.telegram, None)]
            if not self.test and pkg.backup and self.store.get(f"backup:{pkg.hid}") == "released":
                note = pkg.backup_note or DEFAULT_BACKUP_NOTE.format(name=pkg.name)
                targets.append((pkg.backup_key, pkg.backup, note))
            for key, ref, note in targets:
                try:
                    result.waiting += await self._deliver_to(pkg, key, ref, note)
                except Stopped:
                    raise
                except Exception as e:
                    log.exception("delivery of %s to %s failed", pkg.name, ref)
                    self.store.log("delivery_error", f"[{self.mode}] {pkg.name} → {ref}: {e}")
                    result.failures.append(f"{pkg.name} → {ref}: {type(e).__name__}: {e}")
        return result

    async def _peer(self, key: str, ref: str):
        if self.test:
            return "me", None  # your own Saved Messages
        user_id = self.store.get_target(key)
        if user_id is not None:
            try:
                return await self.account.input_peer(user_id), user_id
            except (ValueError, TypeError):
                pass
        user_id, label = await self.account.resolve(ref)
        self.store.set_target(key, user_id, label)
        return await self.account.input_peer(user_id), user_id

    async def _deliver_to(self, pkg: Package, key: str, ref: str, note: str | None) -> int:
        s, mode = self.store, self.mode
        pending = [i for i in pkg.items if not s.is_delivered(mode, key, i.id)]
        if not pending:
            return 0
        peer, peer_id = await self._peer(key, ref)
        start = pkg.start(self.trigger_ts)
        now = time.time()

        if self.test and not s.is_delivered(mode, key, "_header"):
            await self.account.send(peer, text=self._test_header(pkg))
            s.mark_delivered(mode, key, "_header")
        if note and not s.is_delivered(mode, key, "_note"):
            await self.account.send(peer, text=note)
            s.mark_delivered(mode, key, "_note", peer=peer_id, due=now)

        waiting, hold, last_when = 0, s.get(f"hold:{key}", False), None
        for item in pending:
            if self.stop():
                raise Stopped
            due = item.due(start, self.tz)
            schedule = None
            if self.test:
                when = item.when(pkg.delay)
                if when != "right away" and when != last_when:
                    await self.account.send(peer, text=f"⏰ The next item(s) will arrive {when}.")
                last_when = when
            elif due - now > HORIZON:
                waiting += 1
                continue
            elif due - now > MIN_SCHEDULE:
                if hold:
                    waiting += 1
                    continue
                schedule = due
            try:
                ids = await self._send(peer, item, schedule)
            except ScheduleRejected as e:
                log.warning("Telegram refused to schedule for %s (%s); the server will send at due time", ref, e)
                s.set(f"hold:{key}", True)
                hold = True
                waiting += 1
                continue
            s.mark_delivered(mode, key, item.id, peer=peer_id, due=due, scheduled=schedule is not None, msg_ids=ids)
        s.log("delivered", f"[{mode}] {pkg.name} → {ref}: {len(pending) - waiting} item(s), {waiting} waiting")
        return waiting

    async def _send(self, peer, item: Item, schedule: float | None) -> list[int]:
        if item.text is not None:
            return await self.account.send(peer, text=item.text, schedule=schedule)
        if item.kind == "text":
            data = await asyncio.to_thread(self.crypto.decrypt_bytes, item.blob)
            text = data.decode("utf-8", errors="replace")
            return await self.account.send(peer, text=text, schedule=schedule) if text.strip() else []
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.tmp_dir) as tmp:
            path = Path(tmp) / Path(item.name).name
            await asyncio.to_thread(self.crypto.decrypt_to, item.blob, path)
            return await self.account.send(peer, path=path, kind=item.kind, schedule=schedule)

    @staticmethod
    def _test_header(pkg: Package) -> str:
        lines = [
            "🧪 PHOENIX TEST",
            f"Recipient: {pkg.name} ({pkg.telegram})",
            f"Sent on: {' or '.join(pkg.on)}",
        ]
        if pkg.delay:
            lines.append(f"Starts {fmt(pkg.delay)} after the trigger")
        if pkg.backup:
            lines.append(f"Backup: {pkg.backup}, if this is not read within {fmt(pkg.backup_after)}")
        lines.append("Everything below is exactly what they will receive.")
        return "\n".join(lines)
