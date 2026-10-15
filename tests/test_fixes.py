"""Regression tests for the problems found in the October 2026 audit, one per finding."""

import asyncio
import json
import logging
import subprocess
import time

import pytest

from helpers import push_locally, write_meta
from phoenix import config
from phoenix.account import split_text, utf16_len
from phoenix.db import MAX_SETTINGS, Store, settings_error
from phoenix.engine import Engine
from phx import core
from phx import packages as pk

D = 86400


# 1. Moving to another server stops the old one first, and offers to remove it afterwards.
def test_move_stops_the_old_server_first(monkeypatch):
    from phx import screens, ui

    calls = []
    app = screens.App({"server": "root@old", "remote_dir": "/opt/phoenix", "setup": [], "public_key": "age1old"})
    monkeypatch.setattr(core, "save_config", lambda cfg: None)
    monkeypatch.setattr(core, "stop", lambda cfg: calls.append(("stop", cfg["server"])) or True)
    monkeypatch.setattr(core, "uninstall", lambda cfg: calls.append(("uninstall", cfg["server"])))
    monkeypatch.setattr(ui, "confirm", lambda *a, **kw: True)
    monkeypatch.setattr(ui, "pause", lambda: None)
    monkeypatch.setattr(pk, "push_from", lambda cfg, root: calls.append(("push", cfg["server"])))
    monkeypatch.setattr(app, "root", lambda: None)

    def setup():
        calls.append(("setup", app.cfg.get("server")))
        app.cfg["server"] = "root@new"
        return True

    monkeypatch.setattr(app, "setup", setup)
    app.move()
    assert calls == [("stop", "root@old"), ("setup", "root@old"), ("push", "root@new"), ("uninstall", "root@old")]


# 2. A mistyped time zone can never stop a delivery, and it's reported.
def test_bad_time_zone_falls_back_to_utc(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Kiev2")
    cfg = config.load()
    assert str(cfg.tz) == "UTC" and "Europe/Kiev2" in cfg.timezone_problem
    monkeypatch.setenv("TIMEZONE", "Europe/Kyiv")
    assert config.load().timezone_problem is None


# 4. From the bot, delaying timers can only get shorter; everything has an upper limit; late stops are refused.
def test_bot_cannot_quietly_switch_phoenix_off(server, monkeypatch):
    from phoenix import bot

    cfg, _, _ = server
    store = Store(cfg.db_path)
    assert "only be made shorter" in bot.bot_set_error(store, "trigger_after", 100 * D)
    assert bot.bot_set_error(store, "trigger_after", 10 * D) is None
    assert bot.bot_set_error(store, "reminder_every", 6 * 3600) is None
    assert "at most" in settings_error({**store.settings(), "trigger_after": 10 * 365 * D})
    assert all(MAX_SETTINGS[name] >= value for name, value in store.settings().items())

    engine = Engine(cfg, store, account=None, crypto=None, notify=None)
    store.set("phase", "triggered")
    store.set("triggered_at", time.time() - 3600)
    assert not bot.too_late_for_bot(engine)
    store.set("triggered_at", time.time() - 3 * D)
    assert bot.too_late_for_bot(engine)


# 5. The switch keeps ticking even if Telegram makes a maintenance call wait for hours.
def test_switch_runs_while_maintenance_hangs(server, monkeypatch):
    import phoenix.engine as engine_mod

    cfg, _, _ = server
    store = Store(cfg.db_path)

    class StuckAccount:
        async def health(self):
            await asyncio.sleep(3600)  # like a 1-hour flood wait

    async def notify(text, keyboard=None):
        pass

    engine = Engine(cfg, store, StuckAccount(), crypto=None, notify=notify)
    store.set("last_checkin", time.time() - 8 * D)  # check-in missed a day ago
    store.set("phase", "armed")
    monkeypatch.setattr(engine_mod, "TICK", 0.01)

    async def scenario():
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.3)
        task.cancel()

    asyncio.run(scenario())
    assert store.get("phase") == "overdue", "the switch must not wait for the stuck health check"


# 6. A broken bot never stops the switch, and its problems are noticed.
def test_bot_problems_are_noticed(server):
    from phoenix.main import BotWatch, run_bot

    cfg, _, _ = server
    store = Store(cfg.db_path)
    watch = BotWatch(store)
    log = logging.getLogger("aiogram.test")
    log.addHandler(watch)
    log.setLevel(logging.INFO)
    log.error("Failed to fetch updates - %s: %s", "TelegramConflictError", "terminated by other getUpdates request")
    assert time.time() - store.get("bot_conflict_at") < 5
    log.error("Failed to fetch updates - %s: %s", "TelegramUnauthorizedError", "Unauthorized")
    assert "revoked" in store.get("bot_problem")
    log.info("Connection established (tryings = %d, bot id = %d)", 1, 1)
    assert store.get("bot_problem") is None

    class BrokenBot:
        async def set_my_commands(self, commands):
            raise RuntimeError("Bot API unreachable")

    async def scenario():
        task = asyncio.create_task(run_bot(BrokenBot(), dp=None, store=store))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(scenario())
    assert "can't connect" in store.get("bot_problem")


# 7. The server setup script runs from a file, so a command reading stdin can't swallow the rest of it.
def test_bootstrap_script_is_not_read_from_stdin(monkeypatch, tmp_path):
    ran, real_run = {}, subprocess.run

    def fake_run(args, input=None, text=None):
        remote = args[-1]
        script = 'read -r line; echo "swallowed: $line"\necho "second step ran"\n'
        ran["out"] = real_run(["sh", "-c", remote.replace("/opt/phoenix", str(tmp_path))],
                                    input=script, text=True, capture_output=True).stdout
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    core.bootstrap({"server": "root@test", "remote_dir": "/opt/phoenix"})
    assert "second step ran" in ran["out"] and "swallowed: echo" not in ran["out"]


# 9. Names on the server are salted hashes, and the local cache keeps no names.
def test_no_names_leak(server, tmp_path):
    _, public_key, data = server
    packages = tmp_path / "packages"
    write_meta(packages / "mom", name="Mom", telegram="@mom")
    (packages / "mom" / "01-passwords.txt").write_text("bank: 1234")
    push_locally(packages, public_key, data)
    unsalted = pk.h16("package:mom")
    assert not (data / "packages" / unsalted).exists()
    cache = (pk.STAGING.parent / "cache.json").read_text()
    assert "mom" not in cache and "passwords" not in cache
    assert all(len(key) == 16 for key in json.loads(cache))


# 10. Items keep their order past 99.
def test_item_order_past_99(tmp_path):
    d = tmp_path / "mom"
    write_meta(d, name="Mom", telegram="@mom")
    for name in ("100-c.txt", "11-b.txt", "02-a.txt"):
        (d / name).write_text("x")
    assert [p.name for p in pk.package_files(d)] == ["02-a.txt", "11-b.txt", "100-c.txt"]


# 11. Long messages are split by Telegram's own measure (UTF-16), so emoji never make one too long.
@pytest.mark.parametrize("text", ["🔥" * 3000, "word " * 2000, "Hi\n\n" + "🙂 x" * 1500, "a" * 9000])
def test_split_text_fits_telegram(text):
    parts = split_text(text)
    assert all(utf16_len(p) <= 4000 for p in parts)
    assert "".join(parts).replace(" ", "").replace("\n", "") == text.replace(" ", "").replace("\n", "")


# 13. Two Phoenix windows: only the last one to close locks the vault.
def test_only_the_last_window_locks_the_vault():
    with core._vault_user() as first:
        with core._vault_user():
            assert not core._last_user(first)
        assert core._last_user(first)


# 14. Removing Phoenix from a server never deletes anything but its own folder.
@pytest.mark.parametrize("path, ok", [("/opt/phoenix", True), ("/", False), ("/opt", False), ("/home/user", False),
                                      ("opt/phoenix", False), ("/opt/../phoenix", False)])
def test_uninstall_only_deletes_phoenix(path, ok):
    assert core.safe_remote_dir(path) is ok


# The time zone can be changed on its own, found by city, and a failed read never wipes the server's keys.
@pytest.mark.parametrize("typed, expected", [("kyiv", ["Europe/Kyiv"]), ("New York", ["America/New_York"]),
                                             ("europe/berlin", ["Europe/Berlin"]), ("atlantis", [])])
def test_find_time_zones(typed, expected):
    from phx.screens import find_time_zones

    assert find_time_zones(typed) == expected


def test_env_edits_never_wipe_the_keys(monkeypatch):
    written = {}
    monkeypatch.setattr(core, "write_env", lambda cfg, values: written.update(values))
    monkeypatch.setattr(core, "read_env", lambda cfg: {})
    with pytest.raises(core.Failed):
        core.set_env_value({"server": "x"}, "TIMEZONE", "Europe/Kyiv")
    assert written == {}
    monkeypatch.setattr(core, "read_env", lambda cfg: {"BOT_TOKEN": "1:abc", "API_HASH": "h", "TIMEZONE": "UTC"})
    core.set_env_value({"server": "x"}, "TIMEZONE", "Europe/Kyiv")
    assert written == {"BOT_TOKEN": "1:abc", "API_HASH": "h", "TIMEZONE": "Europe/Kyiv"}

    class Unreachable:
        returncode, stdout = 255, ""
    monkeypatch.undo()
    monkeypatch.setattr(core, "ssh", lambda *a, **kw: Unreachable())
    with pytest.raises(core.Failed):
        core.read_env({"server": "root@down"})


def test_time_zone_screen(monkeypatch):
    from phx import screens, ui

    app = screens.App({"server": "root@x", "remote_dir": "/opt/phoenix"})
    changes = []
    monkeypatch.setattr(core, "read_env", lambda cfg: {"BOT_TOKEN": "1:abc", "TIMEZONE": "UTC"})
    monkeypatch.setattr(core, "set_env_value", lambda cfg, k, v: changes.append((k, v)))
    monkeypatch.setattr(core, "restart", lambda cfg: changes.append(("restart",)))
    monkeypatch.setattr(screens, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(ui, "select", lambda title, options, **kw: options.index("Search by city or name…"))
    monkeypatch.setattr(ui, "ask", lambda *a, **kw: "kyiv")
    app.time_zone()
    assert changes == [("TIMEZONE", "Europe/Kyiv"), ("restart",)]


# Second review: junk files, the duress delay, the time zone search, ssh targets, robustness.
def test_junk_files_are_never_sent(tmp_path):
    d = tmp_path / "mom"
    write_meta(d, name="Mom", telegram="@mom")
    for name in ("01-message.txt", "01-message.txt~", "Thumbs.db", "desktop.ini", "02-photo.jpg.part", ".DS_Store"):
        (d / name).write_text("x")
    assert [p.name for p in pk.package_files(d)] == ["01-message.txt"]


def test_duress_delay_has_limits(server, monkeypatch, capsys):
    import sys

    from phoenix import ctl, duress

    monkeypatch.setattr(sys, "argv", ["ctl", "duress-delay", "100y"])
    with pytest.raises(SystemExit, match="Choose between"):
        ctl.main()
    monkeypatch.setattr(sys, "argv", ["ctl", "duress-delay", "2h"])
    ctl.main()
    assert duress.delay(Store(config.load().db_path)) == 7200


def test_ssh_target(tmp_path, monkeypatch):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "config").write_text("Host myvps\n  HostName 203.0.113.7\n  Port 2222\n  User ubuntu\n")
    cfg = ssh_dir / "config"
    assert core.ssh_target("ubuntu@203.0.113.7", config=cfg) == "ubuntu@203.0.113.7"
    assert core.ssh_target("203.0.113.7", config=cfg) == "root@203.0.113.7"
    assert core.ssh_target("myvps", config=cfg) == "myvps"


def test_an_unexpected_error_does_not_kill_the_menu(monkeypatch, capsys):
    from phx import screens, ui

    monkeypatch.setattr(ui, "pause", lambda: None)
    app = screens.App({"server": "x"})
    app.run(lambda: open("/definitely/not/here"))
    assert "Unexpected error: FileNotFoundError" in capsys.readouterr().out


def test_interrupted_move_can_go_back(monkeypatch):
    from phx import screens, ui

    calls = []
    app = screens.App({"server": "root@old", "remote_dir": "/opt/phoenix", "setup": ["server"], "public_key": "age1old"})
    monkeypatch.setattr(core, "save_config", lambda cfg: None)
    monkeypatch.setattr(core, "stop", lambda cfg: True)
    monkeypatch.setattr(core, "restart", lambda cfg: calls.append(("restart", cfg["server"])))
    monkeypatch.setattr(ui, "confirm", lambda *a, **kw: True)
    monkeypatch.setattr(app, "setup", lambda: app.cfg.update(server="root@new") or False)
    app.move()
    assert calls == [("restart", "root@old")]
    assert app.cfg["server"] == "root@old" and app.cfg["public_key"] == "age1old"
