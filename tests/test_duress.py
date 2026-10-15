"""The duress code: answered like a normal check-in, then a quiet panic delivery that the bot hides."""

import asyncio
import time

from helpers import push_locally, write_meta
from phoenix import ctl, duress, state
from phoenix.bot import next_due_text, owner_gate
from phoenix.crypto import Crypto
from phoenix.db import Store
from phoenix.engine import Engine

OWNER = 42


class FakeMessage:
    def __init__(self, text, user_id=OWNER):
        self.text = text
        self.from_user = type("User", (), {"id": user_id})()
        self.answers = []

    async def answer(self, text, **kw):
        self.answers.append(text)


class FakeAccount:
    def __init__(self):
        self.sent = []

    async def health(self):
        return True, "ok"

    async def resolve(self, ref):
        return {"@mom": 1, "@friend": 2}[ref], ref

    async def input_peer(self, user_id):
        return user_id

    async def send(self, peer, *, text=None, path=None, kind="file", schedule=None):
        self.sent.append((peer, text))
        return [len(self.sent)]

    async def delete_scheduled(self, peer, ids):
        pass

    async def set_about(self, text):
        return ""


def test_phrase_matching(server):
    cfg, _, _ = server
    store = Store(cfg.db_path)
    assert not duress.is_code(store, "anything")
    duress.set_code(store, "  All   GOOD ")
    assert duress.is_code(store, "all good") and duress.is_code(store, "ALL GOOD")
    assert not duress.is_code(store, "all good!") and not duress.is_code(store, "") and not duress.is_code(store, None)
    assert "all good" not in str(store.get("duress")).lower(), "only a hash is stored"


def test_silent_alarm(server, tmp_path, monkeypatch):
    cfg, public_key, data = server
    packages = tmp_path / "packages"
    write_meta(packages / "mom", name="Mom", telegram="@mom", on=["silence"])
    (packages / "mom" / "01.txt").write_text("silence only")
    write_meta(packages / "friend", name="Friend", telegram="@friend", on=["panic"])
    (packages / "friend" / "01.txt").write_text("call the police")
    push_locally(packages, public_key, data)

    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    notes, account = [], FakeAccount()

    async def notify(text, keyboard=None):
        notes.append(text)

    store = Store(cfg.db_path)
    engine = Engine(cfg, store, account, Crypto(cfg.identity_path), notify)
    duress.set_code(store, "all good")
    gate = owner_gate(engine, OWNER)
    handled = []

    async def handler(event, data):
        handled.append(event.text)

    async def scenario():
        store.set("last_checkin", clock[0])
        store.set("phase", "armed")
        await engine.tick()
        before = state.status_text(store, 2)
        notes.clear()

        # Strangers are ignored; an ordinary message is a check-in passed on to the handlers.
        await gate(handler, FakeMessage("all good", user_id=7), {})
        await gate(handler, FakeMessage("hello"), {})
        assert handled == ["hello"] and not state.silent(store)

        # The duress code: the same answer as any ordinary message, no handler, a silent alarm.
        msg = FakeMessage("All good")
        await gate(handler, msg, {})
        assert msg.answers == [f"✅ Check-in recorded. {next_due_text(engine)}\n/help for commands."]
        assert handled == ["hello"] and state.silent(store)

        # What the bot shows still looks normal.
        masked = state.status_text(store, 2)
        assert "PANIC" not in masked and "SILENT" not in masked and "armed" in masked
        assert masked.splitlines()[0] == before.splitlines()[0]
        assert "duress" not in state.events_text(store) and "duress" in state.events_text(store, reveal=True)
        assert "SILENT ALARM" in state.status_text(store, 2, reveal=True)

        # After the delay, the panic packages go out, and the owner gets no notification.
        clock[0] += duress.delay(store) - 60
        await engine.tick()
        assert not account.sent
        clock[0] += 120
        await engine.tick()
        await engine._task
        assert [p for p, _ in account.sent] == [2], account.sent
        assert store.get("phase") in ("triggered", "done") and store.get("trigger_kind") == "panic"
        assert notes == [], notes
        assert "armed" in state.status_text(store, 2) and "TRIGGERED" not in state.status_text(store, 2)
        assert ctl.summary(store, 2)["silent"] is True

        # Only the owner's computer can end it: Stop (while delivering) or Arm again (after), both via requests.
        await (engine.abort() if store.get("phase") == "triggered" else engine.rearm())
        assert not state.silent(store) and store.get("phase") == "armed"

    asyncio.run(scenario())


def test_cancel_before_delivery(server):
    cfg, _, _ = server
    store = Store(cfg.db_path)
    engine = Engine(cfg, store, account=None, crypto=None, notify=None)
    store.set("phase", "armed")
    engine.duress()
    assert state.silent(store) and state.panic_due(store) is not None
    assert engine.cancel_panic()
    assert not state.silent(store) and state.panic_due(store) is None
