from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

H, D = 3600, 86400

DEFAULT_SETTINGS = {
    "checkin_interval": 7 * D,
    "button_every": 30 * D,
    "reminder_every": 12 * H,
    "alarm_after": 7 * D,
    "alarm_every": 2 * H,
    "trigger_after": 14 * D,
    "alarm_min": 1 * D,
    "panic_delay": 1 * H,
    "review_every": 90 * D,
}

SETTING_HELP = {
    "checkin_interval": "how often you must check in (your Telegram activity counts too)",
    "button_every": "how often an explicit check-in is required even if you are active",
    "reminder_every": "reminder frequency after a missed check-in",
    "alarm_after": "time after a missed check-in until the alarm phase",
    "alarm_every": "reminder frequency during the alarm phase",
    "trigger_after": "time after a missed check-in until delivery",
    "alarm_min": "minimum alarm phase length before delivery (protects against server downtime)",
    "panic_delay": "cancel window after the panic button",
    "review_every": "remind you to review your packages after this long without changes",
}


MAX_SETTINGS = {  # sane upper limits, so no setting can quietly switch Phoenix off
    "checkin_interval": 60 * D,
    "button_every": 180 * D,
    "reminder_every": 7 * D,
    "alarm_after": 60 * D,
    "alarm_every": 1 * D,
    "trigger_after": 90 * D,
    "alarm_min": 14 * D,
    "panic_delay": 1 * D,
    "review_every": 365 * D,
}
# Longer values delay delivery: from the bot (a phone someone else may hold) these can only be made shorter.
DELAYING_SETTINGS = {"checkin_interval", "button_every", "alarm_after", "trigger_after", "alarm_min"}
MAX_PAUSE_BOT = 30 * D
MAX_PAUSE = 365 * D
BOT_ABORT_WINDOW = 2 * D  # after this long, a delivery can be stopped only from the computer


def settings_error(values: dict[str, int]) -> str | None:
    """Why this combination of settings makes no sense, or None."""
    from .durations import fmt

    if any(v < 60 for v in values.values()):
        return "The minimum is 1 minute."
    for name, value in values.items():
        if value > MAX_SETTINGS.get(name, value):
            return f"{name} can be at most {fmt(MAX_SETTINGS[name])}."
    if values["trigger_after"] <= values["alarm_after"]:
        return "Delivery (trigger_after) must come later than the alarm (alarm_after)."
    if values["button_every"] < values["checkin_interval"]:
        return "The button interval (button_every) can't be shorter than the check-in interval (checkin_interval)."
    return None


class Store:
    """Small key-value store, delivery log and event log on top of SQLite."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries (
                mode TEXT NOT NULL, package TEXT NOT NULL, item TEXT NOT NULL,
                peer INTEGER, due REAL, scheduled INTEGER NOT NULL DEFAULT 0,
                msg_ids TEXT NOT NULL DEFAULT '[]', handed_at REAL NOT NULL,
                PRIMARY KEY (mode, package, item)
            );
            CREATE TABLE IF NOT EXISTS targets (
                package TEXT PRIMARY KEY, user_id INTEGER NOT NULL, label TEXT NOT NULL, checked_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS autoreplied (user_id INTEGER PRIMARY KEY, ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events (ts REAL NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL);
            """
        )

    # --- key-value ---
    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value) -> None:
        self.db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def delete(self, key: str) -> None:
        self.db.execute("DELETE FROM kv WHERE key = ?", (key,))

    def keys(self, prefix: str) -> list[str]:
        rows = self.db.execute("SELECT key FROM kv WHERE substr(key, 1, ?) = ? ORDER BY key", (len(prefix), prefix))
        return [row[0] for row in rows]

    def delete_prefix(self, prefix: str) -> None:
        self.db.execute("DELETE FROM kv WHERE substr(key, 1, ?) = ?", (len(prefix), prefix))

    # --- settings ---
    def setting(self, name: str) -> int:
        return self.get(f"setting:{name}", DEFAULT_SETTINGS[name])

    def set_setting(self, name: str, seconds: int) -> None:
        self.set(f"setting:{name}", seconds)

    def settings(self) -> dict[str, int]:
        return {name: self.setting(name) for name in DEFAULT_SETTINGS}

    # --- event log ---
    def log(self, kind: str, text: str) -> None:
        self.db.execute("INSERT INTO events (ts, kind, text) VALUES (?, ?, ?)", (time.time(), kind, text))

    def recent_events(self, limit: int = 20) -> list[tuple[float, str, str]]:
        rows = self.db.execute("SELECT ts, kind, text FROM events ORDER BY ts DESC LIMIT ?", (limit,))
        return list(rows)[::-1]

    # --- deliveries ---
    def is_delivered(self, mode: str, package: str, item: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM deliveries WHERE mode = ? AND package = ? AND item = ?", (mode, package, item)
        ).fetchone()
        return row is not None

    def mark_delivered(
        self,
        mode: str,
        package: str,
        item: str,
        *,
        peer: int | None = None,
        due: float | None = None,
        scheduled: bool = False,
        msg_ids: list[int] = (),
    ) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO deliveries (mode, package, item, peer, due, scheduled, msg_ids, handed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (mode, package, item, peer, due, int(scheduled), json.dumps(list(msg_ids)), time.time()),
        )

    def clear_deliveries(self, mode: str) -> None:
        self.db.execute("DELETE FROM deliveries WHERE mode = ?", (mode,))

    def delivered_count(self, mode: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM deliveries WHERE mode = ?", (mode,)).fetchone()[0]

    def scheduled_messages(self, mode: str, after: float) -> dict[int, list[int]]:
        """Messages handed to Telegram's scheduler that haven't been sent yet, grouped by peer."""
        out: dict[int, list[int]] = {}
        rows = self.db.execute(
            "SELECT peer, msg_ids FROM deliveries WHERE mode = ? AND scheduled = 1 AND due > ? AND peer IS NOT NULL",
            (mode, after),
        )
        for peer, ids in rows:
            out.setdefault(peer, []).extend(json.loads(ids))
        return out

    # --- resolved Telegram recipients ---
    def set_target(self, package: str, user_id: int, label: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO targets (package, user_id, label, checked_at) VALUES (?, ?, ?, ?)",
            (package, user_id, label, time.time()),
        )

    def get_target(self, package: str) -> int | None:
        row = self.db.execute("SELECT user_id FROM targets WHERE package = ?", (package,)).fetchone()
        return row[0] if row else None

    def target_ids(self) -> set[int]:
        return {row[0] for row in self.db.execute("SELECT user_id FROM targets")}

    # --- auto-reply bookkeeping ---
    def autoreplied(self, user_id: int) -> bool:
        return self.db.execute("SELECT 1 FROM autoreplied WHERE user_id = ?", (user_id,)).fetchone() is not None

    def mark_autoreplied(self, user_id: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO autoreplied (user_id, ts) VALUES (?, ?)", (user_id, time.time()))

    def clear_autoreplied(self) -> None:
        self.db.execute("DELETE FROM autoreplied")
