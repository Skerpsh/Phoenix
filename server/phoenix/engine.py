"""The switch itself: check-ins, reminders, escalation, panic, delivery and after-trigger actions.

Timeline after a missed check-in (all values configurable with /set):
    deadline                    reminders every `reminder_every`
    deadline + alarm_after      ALARM, reminders every `alarm_every`
    deadline + trigger_after    delivery — but only after the alarm phase has
                                actually run for `alarm_min`, so a server that
                                was down for weeks never fires without warning.

The deadline is `checkin_interval` after your last check-in or Telegram activity,
but never more than `button_every` after your last explicit check-in.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import date

from . import duress, state
from .config import Config
from .crypto import Crypto
from .db import Store
from .delivery import HORIZON, Result, Run, Stopped
from .durations import fmt
from .packages import ACCOUNT_FILE, Loaded, human_size, load_all, package_dirs, signature

log = logging.getLogger(__name__)

TICK = 60
RETRY_DELAY = 30 * 60
WATCH_INTERVAL = 10 * 60
HEALTH_EVERY = 6 * 3600
REQUEST_POLL = 1
ACTIVITY_THROTTLE = 5 * 60
REVIEW_REPEAT = 7 * 86400

Notify = Callable[..., Awaitable[None]]


class Engine:
    def __init__(self, cfg: Config, store: Store, account, crypto: Crypto, notify: Notify):
        self.cfg = cfg
        self.store = store
        self.account = account
        self.crypto = crypto
        self._notify = notify  # notify(text, keyboard=None | "checkin" | "review")
        self._task: asyncio.Task | None = None
        self._stop = False
        self._loaded: Loaded | None = None
        self._loaded_sig: str | None = None
        self._requests: asyncio.Task | None = None

    async def notify(self, text: str, keyboard: str | None = None) -> None:
        """Message the owner, except during a silent alarm: then the bot must look as if nothing happened."""
        if state.silent(self.store):
            log.info("silent alarm, not sent: %s", text.splitlines()[0][:80])
            return
        await self._notify(text, keyboard=keyboard)

    # ------------------------------------------------------------------ views
    @property
    def phase(self) -> str:
        return self.store.get("phase", "armed")

    @property
    def delivering(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> str:
        return state.status_text(self.store, len(package_dirs(self.cfg.packages_dir)))

    def _load(self) -> Loaded:
        sig = signature(self.cfg.packages_dir)
        if self._loaded is None or sig != self._loaded_sig:
            self._loaded, self._loaded_sig = load_all(self.cfg.packages_dir, self.crypto), sig
        return self._loaded

    async def loaded(self) -> Loaded:
        return await asyncio.to_thread(self._load)

    # ---------------------------------------------------------- owner actions
    def checkin(self) -> bool:
        """Explicit proof of life. Returns True if a missed check-in was cleared."""
        s = self.store
        was_late = self.phase in ("overdue", "alarm")
        s.set("last_checkin", time.time())
        if was_late:
            s.set("phase", "armed")
            s.log("checkin", "late check-in, escalation reset")
        s.delete("alarm_since")
        s.delete("last_reminder")
        return was_late

    def on_activity(self) -> None:
        """Called for every message you send from any of your devices."""
        s = self.store
        if not state.activity_enabled(s) or self.phase not in ("armed", "overdue", "alarm") or self.delivering:
            return
        now = time.time()
        if now - s.get("last_activity", 0) >= ACTIVITY_THROTTLE:
            s.set("last_activity", now)

    def set_activity(self, enabled: bool) -> None:
        self.store.set("activity", enabled)
        self.store.log("settings", f"activity check-in {'on' if enabled else 'off'}")

    def review_ack(self) -> None:
        self.store.set("review_ack", time.time())

    def pause(self, seconds: int) -> None:
        self.checkin()
        self.store.set("pause_until", time.time() + seconds)
        self.store.log("pause", f"paused for {fmt(seconds)}")

    def resume(self) -> None:
        self.store.delete("pause_until")
        self.checkin()
        self.store.log("pause", "resumed")

    def panic(self) -> bool:
        if self.phase in ("triggered", "done"):
            return False
        self.store.set("panic_at", time.time())
        self.store.delete("panic_due")
        self.store.log("panic", "panic button pressed")
        return True

    def duress(self) -> None:
        """The duress code was sent: start the panic delivery quietly, after the duress delay."""
        s, now = self.store, time.time()
        if state.silent(s):
            return
        s.set("silent_since", now)
        if self.phase not in ("triggered", "done"):
            s.set("panic_at", now)
            s.set("panic_due", now + duress.delay(s))
        s.log("duress", f"silent alarm: delivery in {fmt(duress.delay(s))}")

    def cancel_panic(self) -> bool:
        if self.store.get("panic_at") is None and not state.silent(self.store):
            return False
        for key in ("panic_at", "panic_due", "silent_since"):
            self.store.delete(key)
        self.store.log("panic", "panic cancelled")
        return True

    async def abort(self) -> str | None:
        """Stop a running test, or undo a live trigger (scheduled messages and bio included)."""
        if self.phase == "triggered":
            problems = await self._reset_live()
            self.store.log("abort", "live delivery aborted by owner")
            text = "⏹ Delivery aborted. Scheduled messages were cancelled and Phoenix is armed again."
            return text + "".join(f"\n⚠️ {p}" for p in problems)
        if self.delivering:
            self._stop = True
            return "⏹ Stopping the test."
        return None

    async def rearm(self) -> str | None:
        if self.phase != "done":
            return None
        problems = await self._reset_live()
        self.store.log("armed", "re-armed by owner")
        return "🟢 Re-armed. Pending scheduled messages were cancelled." + "".join(f"\n⚠️ {p}" for p in problems)

    def start_test(self) -> bool:
        if self.phase in ("triggered", "done"):
            return False
        return self._start("test")

    async def verify(self) -> str:
        loaded = await self.loaded()
        if not loaded.packages and not loaded.actions and not loaded.errors:
            return "No packages uploaded yet (on your computer: phoenix → Upload changes to the server)."
        now, tz, lines = time.time(), self.cfg.tz, []
        for p in loaded.packages:
            ok, label = await self._resolve(p.hid, p.telegram)
            if not ok:
                lines.append(f"❌ {p.name}: cannot find {p.telegram} in Telegram ({label})")
                continue
            lines.append(f"✅ {p.name} → {label} · {len(p.items)} item(s), {human_size(p.size)}")
            if tuple(p.on) != ("silence", "panic"):
                lines.append(f"    only on: {', '.join(p.on)}")
            later = sum(1 for i in p.items if i.after or i.date)
            if p.delay or later:
                lines.append(f"    starts {fmt(p.delay) + ' after trigger' if p.delay else 'at trigger'}"
                             f"{f', {later} item(s) scheduled later' if later else ''}")
            latest = p.latest_offset(now, tz)
            if latest > HORIZON:
                lines.append(f"    ⚠️ the last item is {fmt(latest)} after trigger: the server must stay alive "
                             f"and paid for {fmt(latest - HORIZON)} after the trigger")
            if p.backup:
                ok, blabel = await self._resolve(p.backup_key, p.backup)
                lines.append(f"    {'↪' if ok else '❌'} backup {blabel if ok else p.backup + ' not found'}"
                             f" if unread for {fmt(p.backup_after)}")
        a = loaded.actions
        if a:
            parts = [name for name, value in (("auto-reply", a.autoreply), ("bio", a.about)) if value]
            parts += [f"{len(a.posts)} post(s)"] if a.posts else []
            lines.append(f"⚙️ Account actions on {', '.join(a.on)}: {', '.join(parts) or 'none'}")
            for p in a.posts:
                ok, label = await self._resolve(p.hid, p.telegram)
                lines.append(f"    {'✅' if ok else '❌'} post to {label if ok else p.telegram + ' not found'}")
        lines += [f"❌ {e}" for e in loaded.errors]
        return "\n".join(lines)

    async def _resolve(self, key: str, ref: str) -> tuple[bool, str]:
        try:
            user_id, label = await self.account.resolve(ref)
            self.store.set_target(key, user_id, label)
            return True, label
        except Exception as e:
            return False, str(e)

    async def autoreply(self, user_id: int, sender) -> None:
        """Called for private messages people send you."""
        s = self.store
        if self.phase not in ("triggered", "done"):
            return
        a = (await self.loaded()).actions
        if not a or not a.autoreply or s.get("trigger_kind") not in a.on:
            return
        if user_id in s.target_ids() or s.autoreplied(user_id):
            return
        s.mark_autoreplied(user_id)
        try:
            await self.account.send(sender, text=a.autoreply)
        except Exception as e:
            log.warning("auto-reply to %s failed: %s", user_id, e)

    # ------------------------------------------------------- requests from the CLI
    async def _serve_requests(self) -> None:
        """Actions the CLI asks for over SSH (`phoenix.ctl request ...`) that need the Telegram connection."""
        while True:
            for key in self.store.keys("request:"):
                cmd = self.store.get(key)
                self.store.delete(key)
                try:
                    text = await self.handle_request(cmd)
                except Exception as e:
                    log.exception("request %s failed", cmd)
                    text = f"❌ {type(e).__name__}: {e}"
                self.store.set("response:" + key.removeprefix("request:"), text)
            await asyncio.sleep(REQUEST_POLL)

    async def handle_request(self, cmd: str) -> str:
        if cmd == "verify":
            return await self.verify()
        if cmd == "test":
            if self.start_test():
                return "🧪 Rehearsal started: every package is going to your Saved Messages in Telegram."
            return "Not now: a delivery is running or Phoenix has already been triggered."
        if cmd == "abort":
            return await self.abort() or "Nothing is being delivered."
        if cmd == "rearm":
            return await self.rearm() or "Phoenix is already armed."
        if cmd == "health":
            await self._check_health(force=True)
            return f"Telegram account: {'✅' if self.store.get('health_ok') else '⚠️'} {self.store.get('health_text')}"
        return f"Unknown request: {cmd}"

    # ------------------------------------------------------------------- loop
    async def run(self) -> None:
        s = self.store
        if s.get("last_checkin") is None:
            s.set("last_checkin", time.time())
            s.set("phase", "armed")
            s.log("armed", "first start")
            await self.notify("🔥 Phoenix is armed.\n\n" + self.status(), keyboard="checkin")
        else:
            await self.notify("🔄 Phoenix restarted.\n\n" + self.status())
        self._requests = asyncio.create_task(self._serve_requests())
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(TICK)

    async def tick(self) -> None:
        await self._heartbeat()
        await self._check_health()
        await self._check_packages()
        await self._check_billing()
        await self._check_review()
        await self._evaluate()

    async def _evaluate(self) -> None:
        s = self.store
        now = time.time()
        phase = self.phase

        if phase == "done":
            return
        if phase == "triggered":
            if not self.delivering and now >= s.get("next_run", 0):
                self._start("live")
            return

        panic_due = state.panic_due(s)
        if panic_due is not None:
            if now >= panic_due:
                s.delete("panic_at")
                s.delete("panic_due")
                await self._trigger("panic", "duress code" if state.silent(s) else "panic button")
            return

        pause = s.get("pause_until")
        if pause:
            if now < pause:
                return
            s.delete("pause_until")
            s.set("last_checkin", max(s.get("last_checkin", 0), pause))
            s.log("pause", "pause ended")
            await self.notify(
                f"▶️ Pause ended. Next check-in due in {fmt(s.setting('checkin_interval'))}.", keyboard="checkin"
            )
            return

        due = state.deadline(s, now)
        late = now - due
        if late < 0:
            if phase in ("overdue", "alarm"):  # cleared by activity
                s.set("phase", "armed")
                s.delete("alarm_since")
                s.delete("last_reminder")
                s.log("checkin", "activity detected, escalation reset")
                await self.notify("✅ Activity detected — alarm cleared.")
            return

        last_reminder = s.get("last_reminder", 0)
        if late >= s.setting("alarm_after"):
            alarm_since = s.get("alarm_since")
            if alarm_since is None:
                s.set("alarm_since", now)
                s.set("phase", "alarm")
                s.log("alarm", "alarm phase started")
                await self._remind(now)
                return
            trigger_at = max(due + s.setting("trigger_after"), alarm_since + s.setting("alarm_min"))
            if now >= trigger_at:
                await self._trigger("silence", "no check-in")
            elif now - last_reminder >= s.setting("alarm_every"):
                await self._remind(now)
        elif phase != "overdue":
            s.set("phase", "overdue")
            s.log("overdue", "check-in missed")
            await self._remind(now)
        elif now - last_reminder >= s.setting("reminder_every"):
            await self._remind(now)

    async def _remind(self, now: float) -> None:
        s = self.store
        s.set("last_reminder", now)
        late = now - state.deadline(s, now)
        eta = state.trigger_eta(s, now)
        if self.phase == "alarm":
            text = (
                f"🚨 ALARM: check-in overdue by {fmt(late)}.\n"
                f"Your packages will be DELIVERED in {fmt(eta - now)} unless you check in."
            )
        else:
            text = (
                f"⏰ Check-in overdue by {fmt(late)}.\n"
                f"Tap the button to confirm you're OK. Delivery in {fmt(eta - now)} if you stay silent."
            )
        if state.button_required(s, now):
            text += f"\n(You've been active, but a button check-in is needed every {fmt(s.setting('button_every'))}.)"
        await self.notify(text, keyboard="checkin")

    async def _trigger(self, kind: str, reason: str) -> None:
        s = self.store
        s.set("phase", "triggered")
        s.set("trigger_kind", kind)
        s.set("triggered_at", time.time())
        for key in ("next_run", "waiting", "progress_notified", "last_failure_report"):
            s.delete(key)
        s.clear_deliveries("live")
        s.delete_prefix("backup:")
        s.delete_prefix("hold:")
        s.clear_autoreplied()
        s.log("trigger", f"{kind}: {reason}")
        await self.notify(
            f"🔥 TRIGGERED ({reason}). Delivering packages now.\nIf this is a mistake, send /abort immediately."
        )
        await self._apply_profile(kind)
        self._start("live")

    async def _apply_profile(self, kind: str) -> None:
        a = (await self.loaded()).actions
        if not a or kind not in a.on or a.about is None:
            return
        try:
            previous = await self.account.set_about(a.about)
            if self.store.get("about_before") is None:
                self.store.set("about_before", previous)
            self.store.log("profile", "bio updated")
        except Exception as e:
            log.exception("bio update failed")
            await self.notify(f"⚠️ Could not update your bio: {e}")

    async def _reset_live(self) -> list[str]:
        """Undo a live trigger: stop sending, cancel scheduled messages, restore the bio."""
        s, problems = self.store, []
        self._stop = True
        if self.delivering:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=900)
            except Exception:
                pass
        for peer, ids in s.scheduled_messages("live", time.time()).items():
            try:
                await self.account.delete_scheduled(peer, ids)
            except Exception as e:
                problems.append(f"could not cancel scheduled messages for user {peer}: {e}")
        previous = s.get("about_before")
        if previous is not None:
            try:
                await self.account.set_about(previous)
                s.delete("about_before")
            except Exception as e:
                problems.append(f"could not restore your bio: {e}")
        s.clear_deliveries("live")
        s.delete_prefix("backup:")
        s.delete_prefix("hold:")
        s.clear_autoreplied()
        for key in ("next_run", "waiting", "progress_notified", "last_failure_report", "trigger_kind", "triggered_at",
                    "silent_since", "panic_at", "panic_due"):
            s.delete(key)
        s.set("phase", "armed")
        self.checkin()
        return problems

    # --------------------------------------------------------------- delivery
    def _start(self, mode: str) -> bool:
        if self.delivering:
            return False
        self._stop = False
        self._task = asyncio.create_task(self._run_delivery(mode))
        return True

    async def _run_delivery(self, mode: str) -> None:
        s = self.store
        packages, loaded = [], None
        try:
            loaded = await self.loaded()
            run = Run(
                mode=mode, account=self.account, crypto=self.crypto, store=s, tmp_dir=self.cfg.tmp_dir,
                tz=self.cfg.tz, trigger_ts=s.get("triggered_at") or time.time(), stop=lambda: self._stop,
            )
            if mode == "test":
                s.clear_deliveries("test")
                run.trigger_ts = time.time()
                packages = loaded.packages + (loaded.actions.posts if loaded.actions else [])
                result = await run.deliver(packages)
                await self._test_account_actions(loaded)
            else:
                packages = loaded.active(s.get("trigger_kind", "silence"))
                await self._backup_checks(packages)
                result = await run.deliver(packages)
        except Stopped:
            await self.notify("⏹ Delivery stopped.")
            return
        except Exception as e:
            log.exception("delivery crashed")
            result = Result(failures=[f"unexpected error: {e}"])

        failures = (loaded.errors if loaded else []) + result.failures
        report = "\n".join(f"• {f}" for f in failures)
        if mode == "test":
            if failures:
                await self.notify(f"🧪 Test finished with problems:\n{report}")
            else:
                await self.notify(f"🧪 Test finished: {len(packages)} package(s) sent to your Saved Messages.")
            return

        if self.phase != "triggered":  # aborted meanwhile
            return
        now = time.time()
        s.set("waiting", result.waiting)
        open_backups = [p for p in packages if p.backup and s.get(f"backup:{p.hid}") is None]
        if failures:
            s.set("next_run", now + RETRY_DELAY)
            if report != s.get("last_failure_report"):
                s.set("last_failure_report", report)
                await self.notify(f"⚠️ Some deliveries failed, retrying every {fmt(RETRY_DELAY)}:\n{report}")
        elif result.waiting or open_backups:
            s.set("next_run", now + WATCH_INTERVAL)
            if not s.get("progress_notified"):
                s.set("progress_notified", True)
                await self.notify(
                    "✅ Everything due now is delivered or scheduled in Telegram.\n"
                    f"Still watching: {result.waiting} item(s) held by the server, "
                    f"{len(open_backups)} backup check(s)."
                )
        else:
            s.set("phase", "done")
            s.log("done", f"{len(packages)} package(s) delivered")
            await self.notify(f"✅ All {len(packages)} package(s) delivered. Send /rearm to arm Phoenix again.")

    async def _backup_checks(self, packages) -> None:
        """Release a package to its backup recipient if the main one hasn't read it in time."""
        s, now = self.store, time.time()
        trigger_ts = s.get("triggered_at") or now
        for p in packages:
            if not p.backup or s.get(f"backup:{p.hid}") is not None:
                continue
            start = p.start(trigger_ts)
            first_due = min((i.due(start, self.cfg.tz) for i in p.items), default=start)
            if now < first_due + p.backup_after:
                continue
            read = False
            user_id = s.get_target(p.hid)
            if user_id is not None:
                try:
                    read = await self.account.was_read(user_id, first_due - 60)
                except Exception as e:
                    log.warning("read check for %s failed: %s", p.name, e)
            s.set(f"backup:{p.hid}", "read" if read else "released")
            s.log("backup", f"{p.name}: {'read' if read else 'NOT read — sending to backup ' + p.backup}")

    async def _test_account_actions(self, loaded: Loaded) -> None:
        a = loaded.actions
        if not a:
            return
        lines = [f"🧪 Account actions on trigger ({', '.join(a.on)}):"]
        if a.about is not None:
            lines.append(f"\nYour bio becomes:\n{a.about}")
        if a.autoreply:
            lines.append(f"\nAuto-reply (once per person, private chats, not to recipients):\n{a.autoreply}")
        if a.posts:
            lines.append(f"\nPosts: {', '.join(p.telegram for p in a.posts)} (shown above)")
        await self.account.send("me", text="\n".join(lines))

    # ------------------------------------------------------------ maintenance
    async def _heartbeat(self) -> None:
        if not self.cfg.heartbeat_url:
            return
        import aiohttp

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
                async with http.get(self.cfg.heartbeat_url):
                    pass
        except Exception as e:
            log.warning("heartbeat ping failed: %s", e)

    async def _check_health(self, force: bool = False) -> None:
        s = self.store
        now = time.time()
        if not force and now - s.get("health_at", 0) < HEALTH_EVERY:
            return
        ok, text = await self.account.health()
        was_ok = s.get("health_ok")
        s.set("health_at", now)
        s.set("health_ok", ok)
        s.set("health_text", text)
        if not ok:
            s.log("health", text)
            await self.notify(
                f"⚠️ Telegram account problem: {text}\n"
                "Packages CANNOT be delivered until this is fixed. On your computer: phoenix → Server → Log in to Telegram again"
            )
        elif was_ok is False:
            await self.notify("✅ Telegram account is working again.")

    async def _check_packages(self) -> None:
        sig = await asyncio.to_thread(signature, self.cfg.packages_dir)
        if sig == self.store.get("pkg_signature"):
            return
        self.store.set("pkg_signature", sig)
        if not package_dirs(self.cfg.packages_dir) and not (self.cfg.packages_dir / ACCOUNT_FILE).exists():
            return
        self.store.set("pkg_updated_at", time.time())
        self.store.log("packages", "packages updated")
        await self.notify("📦 Packages updated:\n" + await self.verify())

    async def _check_billing(self) -> None:
        s = self.store
        paid = s.get("paid_until")
        today = date.today()
        if not paid or s.get("billing_notified") == today.isoformat():
            return
        left = (date.fromisoformat(paid) - today).days
        if left in (30, 14) or left <= 7:
            s.set("billing_notified", today.isoformat())
            if left < 0:
                text = f"💳 Hosting payment EXPIRED on {paid}! Renew it now, then /paiduntil YYYY-MM-DD."
            else:
                text = f"💳 Hosting is paid until {paid} ({left} day(s) left). Renew it, then /paiduntil YYYY-MM-DD."
            await self.notify(text)

    async def _check_review(self) -> None:
        s = self.store
        updated = s.get("pkg_updated_at")
        if not updated or self.phase not in ("armed", "overdue", "alarm"):
            return
        now = time.time()
        age = now - max(updated, s.get("review_ack", 0))
        if age < s.setting("review_every") or now - s.get("review_notified", 0) < REVIEW_REPEAT:
            return
        s.set("review_notified", now)
        await self.notify(
            f"📝 Your packages were last updated {fmt(now - updated)} ago.\n"
            "Passwords change, people change — is everything still up to date?\n"
            "To change something, run phoenix on your computer.",
            keyboard="review",
        )
