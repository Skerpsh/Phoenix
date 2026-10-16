"""Entry point. The switch (timer and delivery) runs on its own; the control bot is attached separately,
so a broken bot token or an unreachable Bot API can never stop Phoenix from watching and delivering."""

import asyncio
import logging
import shutil
import signal
import time

from aiogram import Bot, Dispatcher

from . import config
from .account import Account, split_text
from .bot import COMMANDS, KEYBOARDS, build_router
from .crypto import Crypto
from .db import Store
from .engine import Engine

log = logging.getLogger("phoenix")

BOT_RETRY = 60
CONFLICT_NOTICE_EVERY = 6 * 3600
CONFLICT_TEXT = (
    "⚠️ Another program is reading your Phoenix bot, probably Phoenix on an old server.\n"
    "While both run, your check-ins may reach only one of them, and the other may deliver by mistake.\n"
    "Remove the old one: on your computer, phoenix → Server → Remove Phoenix from this server (for that server), "
    "or delete that server at your hosting provider."
)


class BotWatch(logging.Handler):
    """aiogram only logs polling errors and retries; this notices the ones that matter."""

    def __init__(self, store: Store):
        super().__init__(logging.INFO)
        self.store = store

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if "TelegramConflictError" in text:
            self.store.set("bot_conflict_at", time.time())
        elif "TelegramUnauthorizedError" in text:
            self.store.set("bot_problem", "the control bot's token was revoked or is wrong")
        elif text.startswith("Connection established"):
            self.store.delete("bot_problem")


async def run_bot(bot: Bot, dp: Dispatcher, store: Store) -> None:
    while True:
        try:
            await bot.set_my_commands(COMMANDS)
            store.delete("bot_problem")
            await dp.start_polling(bot, handle_signals=False)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            store.set("bot_problem", f"the control bot can't connect ({type(e).__name__}: {e})")
            log.error("control bot: %s: %s; retrying in %ds", type(e).__name__, e, BOT_RETRY)
        await asyncio.sleep(BOT_RETRY)


async def watch_bot(store: Store, notify) -> None:
    while True:
        try:
            conflict = store.get("bot_conflict_at")
            if conflict and time.time() - conflict < 300 and \
                    time.time() - store.get("bot_conflict_notified", 0) > CONFLICT_NOTICE_EVERY:
                store.set("bot_conflict_notified", time.time())
                store.log("bot", "another program is reading the bot")
                await notify(CONFLICT_TEXT)
        except Exception:
            log.exception("watching the bot failed")
        await asyncio.sleep(60)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)

    cfg = config.load()
    cfg.require("bot_token", "owner_id", "api_id", "api_hash")
    if not cfg.identity_path.exists():
        raise SystemExit("No encryption key yet (on your computer: phoenix → Server → Update Phoenix)")
    cfg.packages_dir.mkdir(parents=True, exist_ok=True)
    # Files are decrypted here only while they're being sent; anything left over is from a crash or a power cut.
    shutil.rmtree(cfg.tmp_dir, ignore_errors=True)
    # `docker compose stop` sends SIGTERM: stop through the normal path, so temporary files get removed.
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)

    store = Store(cfg.db_path)
    account = Account(cfg)
    try:
        await account.connect()
    except Exception as e:  # the health check reconnects later and tells you if it keeps failing
        log.error("cannot reach Telegram yet: %s", e)

    try:
        bot: Bot | None = Bot(cfg.bot_token)
    except Exception as e:
        bot = None
        store.set("bot_problem", f"the control bot's token is invalid ({e})")
        log.error("control bot disabled: %s", e)

    async def notify(text: str, keyboard: str | None = None) -> None:
        if bot is None:
            log.warning("no control bot, not sent: %s", text.splitlines()[0][:80])
            return
        chunks = split_text(text)
        for n, chunk in enumerate(chunks):
            markup = KEYBOARDS[keyboard]() if keyboard and n == len(chunks) - 1 else None
            for attempt in range(3):
                try:
                    await bot.send_message(cfg.owner_id, chunk, reply_markup=markup)
                    break
                except Exception as e:
                    log.warning("cannot message owner (attempt %d): %s", attempt + 1, e)
                    await asyncio.sleep(5)

    engine = Engine(cfg, store, account, Crypto(cfg.identity_path), notify)
    account.on_outgoing(engine.on_activity)
    account.on_private_incoming(engine.autoreply)

    helpers = [asyncio.create_task(watch_bot(store, notify))]
    if bot is not None:
        logging.getLogger("aiogram").addHandler(BotWatch(store))
        dp = Dispatcher()
        dp.include_router(build_router(engine, cfg.owner_id))
        helpers.append(asyncio.create_task(run_bot(bot, dp, store)))
    try:
        await engine.run()
    finally:
        for task in helpers:
            task.cancel()
        await account.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except asyncio.CancelledError:  # SIGTERM
        log.info("stopped")
