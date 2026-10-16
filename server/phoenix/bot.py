"""Owner control bot. It ignores everyone except OWNER_ID; any message from you counts as a check-in."""

import time
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import durations, duress
from .db import (
    BOT_ABORT_WINDOW,
    DEFAULT_SETTINGS,
    DELAYING_SETTINGS,
    MAX_PAUSE_BOT,
    SETTING_HELP,
    settings_error,
)
from .durations import fmt
from .engine import Engine
from .state import events_text, silent

COMMANDS = [
    BotCommand(command="checkin", description="I'm OK — reset the timer"),
    BotCommand(command="status", description="Current state"),
    BotCommand(command="pause", description="Pause, e.g. /pause 30d"),
    BotCommand(command="resume", description="End the pause"),
    BotCommand(command="activity", description="Count your Telegram activity as check-in: on/off"),
    BotCommand(command="settings", description="Show timer settings"),
    BotCommand(command="set", description="Change a setting, e.g. /set checkin_interval 5d"),
    BotCommand(command="verify", description="Check recipients and packages"),
    BotCommand(command="test", description="Send all packages to your Saved Messages"),
    BotCommand(command="panic", description="Trigger delivery now"),
    BotCommand(command="cancel", description="Cancel a pending panic"),
    BotCommand(command="abort", description="Stop a running delivery"),
    BotCommand(command="rearm", description="Arm again after delivery"),
    BotCommand(command="paiduntil", description="Hosting paid until, e.g. /paiduntil 2027-10-01"),
    BotCommand(command="log", description="Recent events"),
    BotCommand(command="help", description="How it works"),
]

HELP = """🔥 Phoenix — dead man's switch

Check in by tapping "✅ I'm OK" or sending any message to this bot. Messages you write anywhere in Telegram count too, but the button is still needed every 30 days. If you stay silent, Phoenix reminds you, escalates to an alarm, and finally delivers each package from your Telegram account to its recipient.

/status — current state and time left
/pause 30d — going offline (trip, hospital), up to 30 days at a time; /resume to end early
/activity on|off — count your Telegram activity as a check-in
/settings, /set <name> <duration> — change timings (durations: 30m, 12h, 7d, 2w, 1y, 1d12h); from here they can only be made shorter
/verify — check that every recipient can be found
/test — send everything to your own Saved Messages, exactly as recipients would see it
/panic — trigger delivery now (with a cancel window); /cancel to stop it
/abort — stop a delivery and cancel messages already scheduled in Telegram
/paiduntil YYYY-MM-DD — get reminded before hosting expires
/log — recent events"""


def checkin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ I'm OK", callback_data="checkin")]])


def review_keyboard() -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(text="👍 Still up to date", callback_data="reviewed")
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


KEYBOARDS = {"checkin": checkin_keyboard, "review": review_keyboard}


LATE_STOP = (
    f"This delivery started more than {fmt(BOT_ABORT_WINDOW)} ago, so it can only be stopped from the menu on your "
    "computer (phoenix → ⏹ Stop the delivery). This protects your letters if someone else has your phone."
)


def too_late_for_bot(engine: Engine) -> bool:
    """A live delivery older than the bot's window can be stopped only from the computer."""
    started = engine.store.get("triggered_at")
    return (engine.phase in ("triggered", "done") and started is not None
            and time.time() - started > BOT_ABORT_WINDOW)


def bot_set_error(store, name: str, seconds: int) -> str | None:
    """Why /set may not change this (from a phone someone else might hold), or None."""
    if name in DELAYING_SETTINGS and seconds > store.setting(name):
        return (f"From the bot, {name} can only be made shorter. To make it longer, use the menu on your "
                "computer: phoenix → ⏱ Timers and reminders.")
    return settings_error({**store.settings(), name: seconds})


def next_due_text(engine: Engine) -> str:
    return f"Next check-in due in {fmt(engine.store.setting('checkin_interval'))}."


def owner_gate(engine: Engine, owner_id: int):
    """Middleware: ignore everyone but the owner; any owner message is a check-in; the duress code is caught here."""

    async def owner_only(handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None or user.id != owner_id:
            return None
        if duress.is_code(engine.store, getattr(event, "text", None)):
            # Answer exactly like an ordinary message to the bot, so whoever is watching sees nothing unusual.
            was_late = engine.checkin()
            engine.duress()
            if was_late:
                await event.answer("✅ Check-in recorded, alarm cleared.")
            await event.answer(f"✅ Check-in recorded. {next_due_text(engine)}\n/help for commands.")
            return None
        if engine.checkin():
            await engine.notify("✅ Check-in recorded, alarm cleared.")
        return await handler(event, data)

    return owner_only


def build_router(engine: Engine, owner_id: int) -> Router:
    r = Router()

    r.message.outer_middleware(owner_gate(engine, owner_id))
    r.callback_query.outer_middleware(owner_gate(engine, owner_id))

    def next_due() -> str:
        return next_due_text(engine)

    @r.message(Command("start", "help"))
    async def help_(m: Message):
        await m.answer(HELP, reply_markup=checkin_keyboard())

    @r.message(Command("checkin"))
    async def checkin(m: Message):
        await m.answer(f"✅ Got it. {next_due()}")

    @r.callback_query(F.data == "checkin")
    async def checkin_button(q: CallbackQuery):
        await q.answer("Check-in recorded")
        await q.message.answer(f"✅ Got it. {next_due()}")

    @r.message(Command("status"))
    async def status(m: Message):
        await m.answer(engine.status(), reply_markup=checkin_keyboard())

    @r.message(Command("settings"))
    async def settings(m: Message):
        lines = [f"{name} = {fmt(value)}\n   {SETTING_HELP[name]}" for name, value in engine.store.settings().items()]
        await m.answer("\n".join(lines) + "\n\nChange with: /set <name> <duration>")

    @r.message(Command("set"))
    async def set_(m: Message, command: CommandObject):
        parts = (command.args or "").split()
        if len(parts) != 2 or parts[0] not in DEFAULT_SETTINGS:
            await m.answer("Usage: /set <name> <duration>\nNames: " + ", ".join(DEFAULT_SETTINGS))
            return
        name, raw = parts
        try:
            seconds = durations.parse(raw)
        except ValueError as e:
            await m.answer(str(e))
            return
        s = engine.store
        error = bot_set_error(s, name, seconds)
        if error:
            await m.answer(error)
            return
        s.set_setting(name, seconds)
        s.log("settings", f"{name} = {fmt(seconds)}")
        await m.answer(f"✅ {name} = {fmt(seconds)}\n\n{engine.status()}")

    @r.message(Command("pause"))
    async def pause(m: Message, command: CommandObject):
        try:
            seconds = durations.parse(command.args or "")
        except ValueError as e:
            await m.answer(f"Usage: /pause 30d\n{e}")
            return
        if seconds > MAX_PAUSE_BOT:
            await m.answer(f"From the bot you can pause for up to {fmt(MAX_PAUSE_BOT)} at a time (send it again to "
                           "extend). Longer pauses: the menu on your computer, phoenix → ⏸ Pause.")
            return
        engine.pause(seconds)
        await m.answer(f"⏸ Paused for {fmt(seconds)}. The timer restarts when the pause ends. /resume to end early.")

    @r.message(Command("resume"))
    async def resume(m: Message):
        engine.resume()
        await m.answer(f"▶️ Resumed. {next_due()}")

    @r.message(Command("activity"))
    async def activity(m: Message, command: CommandObject):
        arg = (command.args or "").strip().lower()
        if arg not in ("on", "off"):
            await m.answer("Usage: /activity on  or  /activity off")
            return
        engine.set_activity(arg == "on")
        if arg == "on":
            every = fmt(engine.store.setting("button_every"))
            await m.answer(f"✅ Messages you send anywhere in Telegram now count as check-ins (button still needed every {every}).")
        else:
            await m.answer("✅ Only the button and messages to this bot count as check-ins now.")

    @r.callback_query(F.data == "reviewed")
    async def reviewed(q: CallbackQuery):
        engine.review_ack()
        await q.answer("Noted")
        await q.message.edit_reply_markup(reply_markup=None)
        await q.message.answer(f"👍 Got it. Next reminder in {fmt(engine.store.setting('review_every'))}.")

    @r.message(Command("verify"))
    async def verify(m: Message):
        await m.answer("🔎 Checking packages and recipients…")
        await m.answer(await engine.verify())

    @r.message(Command("test"))
    async def test(m: Message):
        if silent(engine.store):
            await m.answer("🧪 Test started: every package goes to your Saved Messages. /abort to stop.")
        elif engine.start_test():
            await m.answer("🧪 Test started: every package goes to your Saved Messages. /abort to stop.")
        else:
            await m.answer("Not now: a delivery is running or Phoenix has already been triggered.")

    @r.message(Command("panic"))
    async def panic(m: Message):
        delay = fmt(engine.store.setting("panic_delay"))
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚨 Yes, trigger", callback_data="panic_yes")],
                [InlineKeyboardButton(text="No", callback_data="panic_no")],
            ]
        )
        await m.answer(f"Trigger delivery? You'll have {delay} to cancel.", reply_markup=kb)

    @r.callback_query(F.data == "panic_yes")
    async def panic_yes(q: CallbackQuery):
        await q.answer()
        await q.message.edit_reply_markup(reply_markup=None)
        if silent(engine.store):
            delay = fmt(engine.store.setting("panic_delay"))
            await q.message.answer(f"🚨 Panic armed. Delivery starts in {delay}. Send /cancel to stop it.")
        elif engine.panic():
            delay = fmt(engine.store.setting("panic_delay"))
            await q.message.answer(f"🚨 Panic armed. Delivery starts in {delay}. Send /cancel to stop it.")
        else:
            await q.message.answer("Already delivering or delivered.")

    @r.callback_query(F.data == "panic_no")
    async def panic_no(q: CallbackQuery):
        await q.answer("Cancelled")
        await q.message.edit_reply_markup(reply_markup=None)

    @r.message(Command("cancel"))
    async def cancel(m: Message):
        if silent(engine.store):  # under duress: pretend there is nothing to cancel
            await m.answer("No panic is pending.")
            return
        await m.answer("✅ Panic cancelled." if engine.cancel_panic() else "No panic is pending.")

    @r.message(Command("abort"))
    async def abort(m: Message):
        if silent(engine.store):
            await m.answer("Nothing is being delivered.")
            return
        if too_late_for_bot(engine):
            await m.answer(LATE_STOP)
            return
        await m.answer(await engine.abort() or "Nothing is being delivered.")

    @r.message(Command("rearm"))
    async def rearm(m: Message):
        if silent(engine.store):
            await m.answer("Phoenix is already armed.")
            return
        if too_late_for_bot(engine):
            await m.answer(LATE_STOP)
            return
        await m.answer(await engine.rearm() or "Phoenix is already armed.")

    @r.message(Command("paiduntil"))
    async def paid_until(m: Message, command: CommandObject):
        try:
            paid = date.fromisoformat((command.args or "").strip())
        except ValueError:
            await m.answer("Usage: /paiduntil 2027-10-01")
            return
        engine.store.set("paid_until", paid.isoformat())
        engine.store.delete("billing_notified")
        await m.answer(f"💳 Hosting paid until {paid}. You'll be reminded 30, 14 and 7 days before.")

    @r.message(Command("log"))
    async def log_(m: Message):
        await m.answer(events_text(engine.store, tz=engine.cfg.tz))

    @r.message()
    async def anything(m: Message):
        await m.answer(f"✅ Check-in recorded. {next_due()}\n/help for commands.")

    return r
