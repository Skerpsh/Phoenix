"""Time capsules, the weekly self-check, the account deletion warning, the timeline, the letter guide
and the vault backup."""

import asyncio
import time
from datetime import datetime, timedelta

from helpers import push_locally, write_meta
from phoenix.crypto import Crypto
from phoenix.db import Store
from phoenix.engine import Engine
from phx import core
from phx import packages as pk

D = 86400


class Account:
    def __init__(self):
        self.sent, self.known, self.ttl_days = [], {"@mom": 1, "me": 99}, 730

    async def health(self):
        return True, "ok"

    async def resolve(self, ref):
        if ref not in self.known:
            raise ValueError("No user has this username")
        return self.known[ref], ref

    async def input_peer(self, user_id):
        return user_id

    async def send(self, peer, *, text=None, path=None, kind="file", schedule=None):
        self.sent.append((peer, text or path.name))
        return [len(self.sent)]


def make_engine(cfg, account, monkeypatch, clock):
    notes = []

    async def notify(text, keyboard=None):
        notes.append(text)

    monkeypatch.setattr(time, "time", lambda: clock[0])
    store = Store(cfg.db_path)
    store.set("last_checkin", clock[0])
    store.set("phase", "armed")
    return Engine(cfg, store, account, Crypto(cfg.identity_path), notify), store, notes


def add_capsule(root, name, telegram, when: datetime, text="Hello from the past"):
    d = root / pk.CAPSULES_DIR / name
    d.mkdir(parents=True)
    pk.save_capsule(d, {"name": name, "telegram": telegram, "date": when.isoformat(timespec="minutes")})
    (d / "01-message.txt").write_text(text)
    return d


# ------------------------------------------------------------------- time capsules
def test_capsule_goes_out_on_its_date_and_is_not_a_sign_of_life(server, tmp_path, monkeypatch):
    cfg, public_key, data = server
    root = tmp_path / "packages"
    write_meta(root / "mom", name="Mom", telegram="@mom")
    (root / "mom" / "01.txt").write_text("for mom")
    when = datetime.now().replace(second=0, microsecond=0) + timedelta(days=2)
    add_capsule(root, "future-me", "me", when)
    push_locally(root, public_key, data)

    clock, account = [time.time()], Account()
    engine, store, notes = make_engine(cfg, account, monkeypatch, clock)
    engine.on_outgoing = None

    async def scenario():
        await engine._check_capsules()
        assert account.sent == [], "not before its date"
        clock[0] += 2 * D + 120
        activity_before = store.get("last_activity")
        original_send = account.send

        async def send_and_echo(peer, **kw):  # Telegram reports our own outgoing message back as activity
            ids = await original_send(peer, **kw)
            engine.on_activity()
            return ids

        account.send = send_and_echo
        await engine._check_capsules()
        assert account.sent == [(99, "Hello from the past")]
        assert store.get("last_activity") == activity_before, "a capsule is not a check-in"
        assert any("Time capsule “future-me” delivered" in n for n in notes)
        await engine._check_capsules()
        assert len(account.sent) == 1, "sent once"

    asyncio.run(scenario())


def test_capsules_are_in_the_rehearsal_and_the_check(server, tmp_path, monkeypatch):
    cfg, public_key, data = server
    root = tmp_path / "packages"
    add_capsule(root, "anna-18", "@mom", datetime(2099, 5, 12, 9, 0))
    push_locally(root, public_key, data)
    engine, store, notes = make_engine(cfg, Account(), monkeypatch, [time.time()])

    async def scenario():
        report = await engine.verify()
        assert "time capsule “anna-18”" in report and "2099-05-12 09:00" in report
        engine.start_test()
        await engine._task
        texts = [t for _, t in engine.account.sent]
        assert any("Time capsule “anna-18”" in t and "whatever happens" in t for t in texts)
        assert "Hello from the past" in texts

    asyncio.run(scenario())


# ------------------------------------------------------------------ self-check, TTL
def test_weekly_self_check(server, tmp_path, monkeypatch):
    cfg, public_key, data = server
    root = tmp_path / "packages"
    write_meta(root / "mom", name="Mom", telegram="@mom")
    (root / "mom" / "01.txt").write_text("hi")
    push_locally(root, public_key, data)
    clock, account = [time.time()], Account()
    engine, store, notes = make_engine(cfg, account, monkeypatch, clock)

    async def scenario():
        assert await engine._self_check() == [] and notes == []
        account.known.pop("@mom")  # she deleted her account, or changed her username
        blob = next((data / "packages").glob("*/[!m]*.age"))
        blob.write_bytes(b"broken")
        clock[0] += 7 * D + 1
        problems = await engine._self_check()
        assert any("can't be found" in p for p in problems) and any("can't be decrypted" in p for p in problems)
        assert len(notes) == 1 and "self-check found problems" in notes[0]
        clock[0] += 7 * D + 1
        await engine._self_check()
        assert len(notes) == 1, "the same problems are reported once"
        account.known["@mom"] = 1
        blob.unlink()
        push_locally(root, public_key, data)
        engine._loaded = None
        clock[0] += 7 * D + 1
        assert await engine._self_check() == []
        assert "everything is fine again" in notes[-1]

    asyncio.run(scenario())


def test_account_deletion_period_warning(server, monkeypatch):
    cfg, _, _ = server
    account = Account()
    engine, store, notes = make_engine(cfg, account, monkeypatch, [time.time()])

    async def scenario():
        account.ttl_days = 180
        await engine._check_account_ttl()
        await engine._check_account_ttl()
        assert len(notes) == 1 and "after 180 days" in notes[0]
        account.ttl_days = 730
        await engine._check_account_ttl()
        assert len(notes) == 1 and store.get("ttl_warned") is None

    asyncio.run(scenario())


# ------------------------------------------------------------------ menu helpers
def test_timeline(tmp_path):
    from phx.screens import timeline

    root = tmp_path / "packages"
    write_meta(root / "mom", name="Mom", telegram="@mom", backup="@dad")
    (root / "mom" / "01.txt").write_text("a")
    (root / "mom" / "02.jpg").write_bytes(b"b")
    (root / "mom" / "@+1y").mkdir()
    (root / "mom" / "@+1y" / "03.txt").write_text("c")
    write_meta(root / "friend", name="Friend", telegram="@friend", on=["panic"], delay=3 * D)
    (root / "friend" / "01.txt").write_text("d")
    pk.save_account(root, {"on": ["silence"], "autoreply": "bye", "about": "", "posts": [
        {"chat": "@group", "text": "x", "delay": D}]})

    silence = [(label, what) for _, label, what in timeline(root, "silence")]
    assert silence == [
        ("right away", "Auto-reply turns on for people who write to you"),
        ("right away", "Mom: 1 message, 1 file"),
        ("after 1d", "Post to @group"),
        ("after 7d", "Mom: if it isn't read by then, the same goes to @dad (backup)"),
        ("after 1y", "Mom: 1 message"),
    ]
    panic = [(label, what) for _, label, what in timeline(root, "panic")]
    assert ("after 3d", "Friend: 1 message") in panic and not any("Auto-reply" in w for _, w in panic)


def test_letter_guide_keeps_only_the_answers(monkeypatch):
    from phx import screens, ui

    answers = iter(["Якщо ти це читаєш…", "", "Подзвони Олегу", "", "", "Обіймаю"])
    monkeypatch.setattr(ui, "ask_text", lambda prompt: next(answers))
    letter = screens.guided_letter()
    assert letter == "Якщо ти це читаєш…\n\nПодзвони Олегу\n\nОбіймаю"
    assert not any(title in letter for title, _ in screens.LETTER_GUIDE)


def test_vault_backup(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "abc").mkdir(parents=True)
    (vault / "gocryptfs.conf").write_text("{}")
    (vault / "abc" / "encrypted").write_bytes(b"\x00" * 100)
    monkeypatch.setattr(core, "VAULT", vault)
    usb = tmp_path / "usb"
    usb.mkdir()
    copy = core.backup_vault(usb)
    assert (copy / "vault" / "abc" / "encrypted").read_bytes() == b"\x00" * 100
    assert "master key" in (copy / "HOW-TO-RESTORE.txt").read_text()
