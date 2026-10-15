"""Server-side commands for the CLI, run over SSH: `python -m phoenix.ctl <command> [args]`.

Simple actions change the database directly (the running service reads it every minute).
Actions that need the Telegram connection are queued for the running service (`request ...`).
"""

import json
import sys
import time
import uuid
from datetime import date

from . import PROTOCOL, config, durations
from .db import DEFAULT_SETTINGS, SETTING_HELP, Store, settings_error
from .durations import fmt
from .engine import Engine
from .packages import package_dirs
from .state import PHASES, activity_enabled, deadline, events_text, status_text, trigger_eta

REQUEST_TIMEOUT = 180


def summary(store: Store, packages: int) -> dict:
    now = time.time()
    phase = store.get("phase", "armed")
    pause = store.get("pause_until")
    eta = trigger_eta(store, now)
    watching = phase in ("armed", "overdue", "alarm") and store.get("last_checkin") is not None
    return {
        "protocol": PROTOCOL,
        "phase": phase,
        "phase_label": PHASES.get(phase, phase),
        "paused_for": pause - now if pause and pause > now else None,
        "due_in": deadline(store, now) - now if watching else None,
        "eta_in": eta - now if eta is not None else None,
        "panic_pending": store.get("panic_at") is not None,
        "activity": activity_enabled(store),
        "packages": packages,
        "health_ok": store.get("health_ok"),
        "health_text": store.get("health_text", ""),
        "paid_until": store.get("paid_until"),
        "pkg_updated_ago": now - store.get("pkg_updated_at") if store.get("pkg_updated_at") else None,
    }


def request(store: Store, cmd: str) -> str:
    rid = uuid.uuid4().hex
    store.set(f"request:{rid}", cmd)
    deadline_ts = time.time() + REQUEST_TIMEOUT
    while time.time() < deadline_ts:
        answer = store.get(f"response:{rid}")
        if answer is not None:
            store.delete(f"response:{rid}")
            return answer
        time.sleep(0.5)
    store.delete(f"request:{rid}")
    raise SystemExit("Phoenix did not answer in time. Is it running? (Server → Restart Phoenix)")


def main() -> None:
    cfg = config.load()
    store = Store(cfg.db_path)
    engine = Engine(cfg, store, account=None, crypto=None, notify=None)  # only its database actions are used
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("status", [])
    packages = len(package_dirs(cfg.packages_dir))

    if cmd == "status":
        print(status_text(store, packages))
    elif cmd == "summary":
        print(json.dumps(summary(store, packages)))
    elif cmd == "log":
        print(events_text(store, 50))
    elif cmd == "settings":
        print(json.dumps({
            "settings": {name: {"value": value, "help": SETTING_HELP[name]} for name, value in store.settings().items()},
            "activity": activity_enabled(store),
            "paid_until": store.get("paid_until"),
        }))
    elif cmd == "set" and len(args) == 2 and args[0] in DEFAULT_SETTINGS:
        name, seconds = args[0], durations.parse(args[1])
        error = settings_error({**store.settings(), name: seconds})
        if error:
            raise SystemExit(error)
        store.set_setting(name, seconds)
        store.log("settings", f"{name} = {fmt(seconds)} (from the CLI)")
        print(f"✅ Saved: {fmt(seconds)}")
    elif cmd == "checkin":
        engine.checkin()
        store.log("checkin", "check-in from the CLI")
        print(f"✅ Check-in recorded. Next one due in {fmt(store.setting('checkin_interval'))}.")
    elif cmd == "pause" and len(args) == 1:
        seconds = durations.parse(args[0])
        engine.pause(seconds)
        print(f"⏸ Paused for {fmt(seconds)}. The timer starts again when the pause ends.")
    elif cmd == "resume":
        engine.resume()
        print("▶️ Pause ended, check-in recorded.")
    elif cmd == "activity" and args in (["on"], ["off"]):
        engine.set_activity(args[0] == "on")
        print("✅ Saved.")
    elif cmd == "paiduntil" and len(args) == 1:
        paid = date.fromisoformat(args[0])
        store.set("paid_until", paid.isoformat())
        store.delete("billing_notified")
        print(f"💳 Saved: paid until {paid}. Your bot reminds you 30, 14 and 7 days before.")
    elif cmd == "panic":
        if not engine.panic():
            raise SystemExit("Phoenix is already delivering or has delivered.")
        print(f"🚨 Panic armed. Delivery starts in {fmt(store.setting('panic_delay'))} unless you cancel it.")
    elif cmd == "cancel":
        print("✅ Panic cancelled." if engine.cancel_panic() else "No panic is pending.")
    elif cmd == "request" and len(args) == 1:
        print(request(store, args[0]))
    else:
        raise SystemExit(f"unknown command: {' '.join(sys.argv[1:])}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        raise SystemExit(str(e)) from None
