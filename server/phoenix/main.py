import asyncio
import logging

from aiogram import Bot, Dispatcher

from . import config
from .account import Account
from .bot import COMMANDS, KEYBOARDS, build_router
from .crypto import Crypto
from .db import Store
from .engine import Engine

log = logging.getLogger("phoenix")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)

    cfg = config.load()
    cfg.require("bot_token", "owner_id", "api_id", "api_hash")
    if not cfg.identity_path.exists():
        raise SystemExit("No encryption key yet (on your computer: phoenix → Server → Update Phoenix)")
    cfg.packages_dir.mkdir(parents=True, exist_ok=True)

    store = Store(cfg.db_path)
    account = Account(cfg)
    await account.connect()
    bot = Bot(cfg.bot_token)

    async def notify(text: str, keyboard: str | None = None) -> None:
        markup = KEYBOARDS[keyboard]() if keyboard else None
        for attempt in range(3):
            try:
                await bot.send_message(cfg.owner_id, text, reply_markup=markup)
                return
            except Exception as e:
                log.warning("cannot message owner (attempt %d): %s", attempt + 1, e)
                await asyncio.sleep(5)

    engine = Engine(cfg, store, account, Crypto(cfg.identity_path), notify)
    account.on_outgoing(engine.on_activity)
    account.on_private_incoming(engine.autoreply)
    dp = Dispatcher()
    dp.include_router(build_router(engine, cfg.owner_id))
    await bot.set_my_commands(COMMANDS)

    engine_task = asyncio.create_task(engine.run())
    try:
        await dp.start_polling(bot)
    finally:
        engine_task.cancel()
        await account.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
