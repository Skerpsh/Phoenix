"""Read-only views of the switch state (shared by the engine, the bot and the `ctl` command)."""

import time
from datetime import datetime

from .db import Store
from .durations import fmt

PHASES = {
    "armed": "🟢 armed",
    "overdue": "🟡 check-in overdue",
    "alarm": "🔴 ALARM",
    "triggered": "🔥 TRIGGERED — delivering",
    "done": "⚫ delivered",
}


def activity_enabled(s: Store) -> bool:
    return s.get("activity", True)


def _deadlines(s: Store, now: float) -> tuple[float, float]:
    """(due from inactivity, due from the explicit check-in cap)."""
    last = s.get("last_checkin") or now
    pause = s.get("pause_until")
    if pause and pause > now:
        last = max(last, pause)
    activity = s.get("last_activity", 0) if activity_enabled(s) else 0
    return max(last, activity) + s.setting("checkin_interval"), last + s.setting("button_every")


def deadline(s: Store, now: float) -> float:
    """When the next check-in is due.

    Your Telegram activity moves it forward, but an explicit check-in (button or any
    message to the bot) is still needed at least every `button_every`.
    """
    return min(_deadlines(s, now))


def button_required(s: Store, now: float) -> bool:
    """True if you are active but the explicit check-in cap has run out."""
    inactivity, cap = _deadlines(s, now)
    return cap < inactivity


def silent(s: Store) -> bool:
    """A silent alarm (duress code) is on: what the bot shows must look normal."""
    return s.get("silent_since") is not None


def panic_due(s: Store) -> float | None:
    """When a pending panic fires (the duress code sets its own time)."""
    panic_at = s.get("panic_at")
    if panic_at is None:
        return None
    return s.get("panic_due") or panic_at + s.setting("panic_delay")


def trigger_eta(s: Store, now: float, *, masked: bool = False) -> float | None:
    """When delivery happens if you stay silent from now on (masked: as if no alarm were on)."""
    if s.get("phase", "armed") in ("triggered", "done") and not masked:
        return None
    if panic_due(s) is not None and not masked:
        return panic_due(s)
    due = deadline(s, now)
    alarm_since = None if masked else s.get("alarm_since")
    alarm_start = alarm_since if alarm_since is not None else max(now, due + s.setting("alarm_after"))
    return max(due + s.setting("trigger_after"), alarm_start + s.setting("alarm_min"))


def status_text(s: Store, packages_count: int, *, reveal: bool = False) -> str:
    """The state as text. During a silent alarm it looks normal, unless `reveal` (the owner's own computer)."""
    now = time.time()
    masked = silent(s) and not reveal
    phase = "armed" if masked else s.get("phase", "armed")
    lines = [f"State: {PHASES.get(phase, phase)}"]

    last = s.get("last_checkin")
    if last:
        lines.append(f"Last check-in: {fmt(now - last)} ago")
    if activity_enabled(s):
        seen = s.get("last_activity")
        seen_text = f"last seen {fmt(now - seen)} ago" if seen else "no activity seen yet"
        lines.append(f"Activity check-in: on ({seen_text}; button needed every {fmt(s.setting('button_every'))})")
    else:
        lines.append("Activity check-in: off")

    pause = s.get("pause_until")
    if phase in ("armed", "overdue", "alarm"):
        if pause and pause > now:
            lines.append(f"⏸ Paused for another {fmt(pause - now)}")
        elif last:
            due = deadline(s, now)
            if due > now:
                lines.append(f"Next check-in due in: {fmt(due - now)}")
            else:
                lines.append(f"Check-in overdue by: {fmt(now - due)}")

    if silent(s) and reveal:
        lines.append("🤫 SILENT ALARM (duress code): the bot shows a normal status")
    if s.get("panic_at") is not None and not masked:
        lines.append("🚨 PANIC pending — /cancel to stop")

    eta = trigger_eta(s, now, masked=masked)
    if eta is not None:
        lines.append(f"Delivery if you stay silent: in {fmt(eta - now)}")

    if phase in ("triggered", "done"):
        lines.append(f"Trigger: {s.get('trigger_kind', '?')}, {fmt(now - s.get('triggered_at', now))} ago")
        lines.append(f"Items handed to Telegram: {s.delivered_count('live')}")
        if s.get("waiting"):
            lines.append(f"Items still held by the server: {s.get('waiting')}")

    lines.append(f"Packages: {packages_count}")
    updated = s.get("pkg_updated_at")
    if updated:
        lines.append(f"Packages last updated: {fmt(now - updated)} ago")

    ok = s.get("health_ok")
    if ok is None:
        lines.append("Telegram account: not checked yet")
    else:
        lines.append(f"Telegram account: {'✅' if ok else '⚠️'} {s.get('health_text', '')}")

    checked = s.get("selfcheck_at")
    if checked:
        found = s.get("selfcheck_problems", [])
        result = f"⚠️ {len(found)} problem(s)" if found else "✅ all recipients found, all files readable"
        lines.append(f"Weekly self-check: {result} ({fmt(now - checked)} ago)")

    paid = s.get("paid_until")
    lines.append(f"Hosting paid until: {paid}" if paid else "Hosting paid until: not set (/paiduntil YYYY-MM-DD)")
    return "\n".join(lines)


def events_text(s: Store, limit: int = 20, *, reveal: bool = False) -> str:
    rows = s.recent_events(limit)
    if silent(s) and not reveal:
        rows = [row for row in rows if row[0] < s.get("silent_since")]
    if not rows:
        return "No events yet."
    return "\n".join(f"{datetime.fromtimestamp(ts):%Y-%m-%d %H:%M} [{kind}] {text}" for ts, kind, text in rows)
