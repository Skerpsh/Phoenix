"""Entry point: `phoenix` opens the menu; a few subcommands remain for scripts and power users."""

import argparse
import os
import random
import signal
import sys

from . import __version__, art, core, ui
from . import packages as pk
from .core import Failed
from .screens import App, Restart


def on_hangup(signum, frame) -> None:
    """Terminal closed: exit through the normal path so the vault gets locked."""
    sys.stdout = sys.stderr = open(os.devnull, "w")
    raise SystemExit(1)


def menu(a) -> None:
    core.need(*core.REQUIRED_TOOLS)
    if not ui.ensure_size():
        return
    moved = core.migrate_vault()
    ui.splash()
    if moved:
        ui.note(moved)
    app = App(core.load_config())
    restart = False
    try:
        if not app.setup_complete() and not app.setup():
            return
        print("Connecting to your server…")
        app.main(getattr(a, "start", None))
    except Restart:
        restart = True
    finally:
        app.close()
    if restart:
        os.execv(sys.executable, [sys.executable, str(core.ROOT / "cli" / "phoenix")])
    locked = "\n🔒 Your vault is locked." if core.vault_enabled() else ""
    ui.farewell(f"{random.choice(art.FAREWELLS)}{locked}")


def push(a) -> None:
    cfg = core.require_server(core.load_config())
    with core.packages_root(cfg) as root:
        pk.migrate(root)
        pk.push_from(cfg, root)


def status(a) -> None:
    print(core.ctl(core.require_server(core.load_config()), "status"))


def log(a) -> None:
    print(core.ctl(core.require_server(core.load_config()), "log"))


def checkin(a) -> None:
    print(core.ctl(core.require_server(core.load_config()), "checkin"))


def update(a) -> None:
    cfg = core.require_server(core.load_config())
    core.update_code()
    core.deploy(cfg)
    print("✅ Phoenix is up to date, here and on the server.")


def logs(a) -> None:
    core.follow_logs(core.require_server(core.load_config()))


def lock(a) -> None:
    print("🔒 Vault locked." if core.lock() else "The vault is not open.")


def main() -> None:
    p = argparse.ArgumentParser(prog="phoenix", description="Run without arguments to open the menu: setup, recipients, "
                                "check-ins, tests, timers, server — everything is there.")
    p.add_argument("--version", action="version", version=f"Phoenix {__version__}")
    p.set_defaults(func=menu)
    sub = p.add_subparsers(title="shortcuts", metavar="")
    for name, func, text in [
        ("checkin", checkin, "I'm OK: check in"),
        ("status", status, "show the switch state"),
        ("push", push, "upload your packages"),
        ("log", log, "recent events"),
        ("logs", logs, "follow the server logs"),
        ("update", update, "download the latest Phoenix and update the server"),
        ("lock", lock, "lock the vault if it stayed open"),
    ]:
        sub.add_parser(name, help=text).set_defaults(func=func)
    for name, start in (("new", "new"), ("account", "account"), ("edit", None), ("deploy", None)):
        sub.add_parser(name).set_defaults(func=update if name == "deploy" else menu, start=start)

    a = p.parse_args()
    for sig in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(sig, on_hangup)
    try:
        a.func(a)
    except Failed as e:
        sys.exit(f"❌ {e}")
    except (KeyboardInterrupt, EOFError):
        sys.exit(130)
