"""Log the server out of your Telegram account (used when removing Phoenix from a server)."""

import asyncio

from telethon import TelegramClient

from . import config


async def main() -> None:
    cfg = config.load()
    if not cfg.session_path.with_suffix(".session").exists():
        print("Not logged in.")
        return
    client = TelegramClient(str(cfg.session_path), cfg.api_id, cfg.api_hash)
    await client.connect()
    if await client.is_user_authorized():
        await client.log_out()
        print("Logged out of Telegram.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
