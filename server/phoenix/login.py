"""Interactive login to your Telegram account. Run with the main service stopped."""

import asyncio

from telethon import TelegramClient

from . import config
from .account import display_name


async def main() -> None:
    cfg = config.load()
    cfg.require("api_id", "api_hash")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(cfg.session_path), cfg.api_id, cfg.api_hash)
    print("Log in with your MAIN Telegram account (phone number, then the code Telegram sends you).")
    await client.start()
    me = await client.get_me()
    print(f"Logged in as {display_name(me)}")
    print("Loading your chats so recipients can be found…")
    await client.get_dialogs()
    await client.disconnect()
    cfg.session_path.with_suffix(".session").chmod(0o600)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
