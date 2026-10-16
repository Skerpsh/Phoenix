"""Regression tests for the problems found in the second audit (16 October 2026), one per finding."""

import asyncio
import json
import stat
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from helpers import push_locally, write_meta
from phoenix import ctl, duress
from phoenix import engine as engine_module
from phoenix.crypto import Crypto
from phoenix.db import Store
from phoenix.engine import Engine
from phoenix.state import events_text
from phx import core
from phx import packages as pk

D = 86400


class Account:
    def __init__(self, known=None):
        self.known = known if known is not None else {"@alice": 1, "@bob": 2}
        self.sent, self.about, self.hang, self.connected = [], "old bio", False, True
        self.health_checks = 0

    async def health(self):
        self.health_checks += 1
        self.connected = True
        return True, "ok"

    async def resolve(self, ref):
        if ref not in self.known:
            raise ValueError("No user has this username")
        return self.known[ref], ref

    async def input_peer(self, user_id):
        return user_id

    async def send(self, peer, *, text=None, path=None, kind="file", schedule=None):
        if self.hang:
            await asyncio.Event().wait()  # stuck: a huge upload, or Telegram making us wait
        self.sent.append((peer, text or path.name))
        return [len(self.sent)]

    async def delete_scheduled(self, peer, ids):
        pass

    async def set_about(self, text):
        if self.hang:
            await asyncio.Event().wait()
        previous, self.about = self.about, text
        return previous


def make_engine(cfg, account, notes=None):
    async def notify(text, keyboard=None):
        if notes is not None:
            notes.append(text)

    store = Store(cfg.db_path)
    store.set("last_checkin", time.time())
    return Engine(cfg, store, account, Crypto(cfg.identity_path), notify), store


def one_package(tmp_path, telegram="@alice"):
    packages = tmp_path / "packages"
    write_meta(packages / "x", name="X", telegram=telegram)
    (packages / "x" / "01-letter.txt").write_text("secret")
    return packages


# 1. After you change who receives a package, the old person's id is never used again.
def test_changed_recipient_never_gets_the_old_ones_letters(server, tmp_path):
    cfg, public_key, data = server
    packages = one_package(tmp_path)
    push_locally(packages, public_key, data)
    account = Account()
    engine, _ = make_engine(cfg, account)

    async def scenario():
        assert "✅" in await engine.verify()  # remembers @alice = 1
        write_meta(packages / "x", name="X", telegram="@bob_typo")
        push_locally(packages, public_key, data)
        assert "cannot find @bob_typo" in await engine.verify()
        await engine._trigger("silence", "test")
        await engine._task

    asyncio.run(scenario())
    assert account.sent == [], "nothing may go to @alice once the recipient was changed"


def test_same_recipient_keeps_its_id_when_lookups_fail(server, tmp_path):
    """Someone who changed their @username is still reached through the id found earlier."""
    cfg, public_key, data = server
    push_locally(one_package(tmp_path), public_key, data)
    account = Account()
    engine, _ = make_engine(cfg, account)

    async def scenario():
        await engine.verify()
        account.known = {}
        await engine._trigger("silence", "test")
        await engine._task

    asyncio.run(scenario())
    assert account.sent == [(1, "secret")]


def test_old_databases_forget_ids_without_a_recipient(tmp_path):
    import sqlite3

    path = tmp_path / "phoenix.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE targets (package TEXT PRIMARY KEY, user_id INTEGER NOT NULL, label TEXT NOT NULL,"
               " checked_at REAL NOT NULL)")
    db.execute("INSERT INTO targets VALUES ('x', 1, 'Alice', 0)")
    db.commit()
    db.close()
    store = Store(path)
    assert store.get_target("x", "@alice") is None
    store.set_target("x", "@alice", 1, "Alice")
    assert store.get_target("x", "@alice") == 1 and store.get_target("x", "@bob") is None


# 2. Moving to a new server takes your timers, duress code, pause and paid-until date along.
def test_settings_move_to_the_new_server(tmp_path):
    old, new = Store(tmp_path / "old.db"), Store(tmp_path / "new.db")
    old.set_setting("trigger_after", 30 * D)
    old.set_setting("alarm_after", 10 * D)
    old.set("activity", False)
    old.set("paid_until", "2027-10-01")
    old.set("duress_delay", 6 * 3600)
    old.set("pause_until", time.time() + 5 * D)
    duress.set_code(old, "all good, talk later")

    exported = json.loads(json.dumps(ctl.export_state(old)))  # as it travels over SSH
    done = ctl.import_state(new, exported)

    assert new.setting("trigger_after") == 30 * D and new.setting("alarm_after") == 10 * D
    assert duress.is_code(new, "All good,  talk later") and duress.delay(new) == 6 * 3600
    assert new.get("activity") is False and new.get("paid_until") == "2027-10-01"
    assert new.get("pause_until") == old.get("pause_until")
    assert {"timers", "duress code", "paid-until date", "pause"} <= set(done)


def test_broken_settings_are_not_taken_over(tmp_path):
    new = Store(tmp_path / "new.db")
    with pytest.raises(SystemExit):
        ctl.import_state(new, {"settings": {"trigger_after": 60, "alarm_after": 120}})
    assert new.setting("trigger_after") == 14 * D


def test_a_move_finished_later_still_takes_the_settings(monkeypatch):
    from phx import screens

    calls = []
    app = screens.App({"server": "root@new", "setup": [], "moving_state": {"settings": {}}})
    monkeypatch.setattr(core, "save_config", lambda cfg: None)
    monkeypatch.setattr(core, "ctl", lambda cfg, *args, **kw: calls.append((args[0], kw["input"])) or "✅")
    app.take_over_settings()
    assert calls == [("import-state", '{"settings": {}}')] and "moving_state" not in app.cfg


# 4. Stopping a delivery stops it, even when one item is stuck.
def test_abort_cuts_off_a_stuck_item(server, tmp_path, monkeypatch):
    cfg, public_key, data = server
    push_locally(one_package(tmp_path), public_key, data)
    monkeypatch.setattr(engine_module, "ABORT_WAIT", 0.1)
    account = Account()
    engine, store = make_engine(cfg, account)

    async def scenario():
        await engine.verify()
        account.hang = True
        store.set("phase", "triggered")
        store.set("trigger_kind", "silence")
        engine._start("live")
        await asyncio.sleep(0.05)
        return await engine.abort()

    text = asyncio.run(scenario())
    assert "may still have reached" in text
    assert not engine.delivering and store.get("phase") == "armed" and store.delivered_count("live") == 0


# 5. Without a connection to Telegram, Phoenix reconnects at once instead of waiting for the 6-hourly check.
def test_reconnects_when_disconnected(server):
    cfg, _, _ = server
    account = Account()
    engine, store = make_engine(cfg, account)
    store.set("health_at", time.time())
    asyncio.run(engine._check_health())
    assert account.health_checks == 0
    account.connected = False
    asyncio.run(engine._check_health())
    assert account.health_checks == 1


# 6. Removing Phoenix tells you when the server could not log out of Telegram.
def test_uninstall_reports_a_failed_logout(monkeypatch):
    class R:
        def __init__(self, code):
            self.returncode = code

    results = iter([R(1), R(0)])
    monkeypatch.setattr(core, "ssh", lambda cfg, command, **kw: next(results))
    warning = core.uninstall({"server": "root@x", "remote_dir": "/opt/phoenix"})
    assert "Devices" in warning
    results = iter([R(0), R(0)])
    assert core.uninstall({"server": "root@x", "remote_dir": "/opt/phoenix"}) is None


# 7. A slow bio change can't hold up the delivery.
def test_delivery_starts_before_the_bio_changes(server, tmp_path):
    cfg, public_key, data = server
    packages = one_package(tmp_path)
    (packages / "_account.toml").write_text('on=["silence"]\nabout="In memory"\n')
    push_locally(packages, public_key, data)
    account = Account()
    engine, _ = make_engine(cfg, account)

    async def scenario():
        account.hang = True
        bio = asyncio.create_task(engine._trigger("silence", "test"))
        await asyncio.sleep(0.05)
        assert engine.delivering, "the delivery runs while the bio change is still waiting"
        bio.cancel()

    asyncio.run(scenario())


# 8. One failure never stops Phoenix from answering the menu; unclaimed answers don't pile up.
def test_requests_survive_a_failure(server, monkeypatch):
    cfg, _, _ = server
    engine, store = make_engine(cfg, Account())
    store.set("response:old", {"text": "nobody waited", "at": time.time() - 2 * 3600})
    store.set("response:legacy", "plain text from an older version")
    real_keys, failures = store.keys, [1]

    def keys(prefix):
        if failures:
            failures.pop()
            raise RuntimeError("database is locked")
        return real_keys(prefix)

    monkeypatch.setattr(store, "keys", keys)
    monkeypatch.setattr(engine_module, "REQUEST_POLL", 0.01)

    async def scenario():
        serving = asyncio.create_task(engine._serve_requests())
        answer = await asyncio.to_thread(lambda: ctl.request(Store(cfg.db_path), "health"))
        serving.cancel()
        return answer

    assert "ok" in asyncio.run(scenario())
    assert store.get("response:old") is None and store.get("response:legacy") is None


# 10. The history shows your own time zone.
def test_history_in_your_time_zone(tmp_path):
    store = Store(tmp_path / "db")
    store.log("test", "hello")
    ts = store.recent_events()[0][0]
    kyiv = datetime.fromtimestamp(ts, ZoneInfo("Europe/Kyiv")).strftime("%H:%M")
    assert kyiv in events_text(store, tz=ZoneInfo("Europe/Kyiv"))
    assert datetime.fromtimestamp(ts, UTC).strftime("%H:%M") in events_text(store, tz=UTC)


# 11. The settings on this computer are never readable by others, not even for a moment.
def test_config_is_private_from_the_start(monkeypatch, tmp_path):
    path = tmp_path / "phoenix" / "config.json"
    monkeypatch.setattr(core, "CONFIG_PATH", path)
    core.save_config({"name_salt": "s"})
    core.save_config({"name_salt": "t"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and json.loads(path.read_text()) == {"name_salt": "t"}


# 12. The secret that hides names on the server lives with the packages, so a restored vault keeps the names.
def test_name_salt_travels_with_the_packages(monkeypatch, tmp_path):
    monkeypatch.setattr(pk, "save_config", lambda cfg: None)
    root = tmp_path / "packages"
    root.mkdir()
    cfg = {"name_salt": "from-config"}
    assert pk.name_salt(cfg, root) == "from-config"  # existing setups keep their names
    restored = {}  # a new computer: no config.json, the vault restored from a backup
    assert pk.name_salt(restored, root) == "from-config" and restored["name_salt"] == "from-config"
    assert pk.SALT_FILE not in [p.name for p in pk.package_files(root)]


# 13. Phoenix's own messages don't count as a sign of life.
def test_own_messages_are_not_activity(server):
    import dataclasses

    from phoenix import account as account_module

    cfg, _, _ = server
    acc = account_module.Account(dataclasses.replace(cfg, api_id=1, api_hash="0" * 32))
    assert not acc.own_echo()
    acc._sent_at = time.monotonic()
    assert acc.own_echo()
    acc._sent_at = time.monotonic() - account_module.OWN_ECHO - 1
    assert not acc.own_echo()
