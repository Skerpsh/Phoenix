import logging
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_id: int
    api_id: int
    api_hash: str
    data_dir: Path
    heartbeat_url: str
    timezone: str

    @property
    def tz(self) -> ZoneInfo:
        """Your time zone; an unknown name falls back to UTC, so a typo can never stop a delivery."""
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            log.warning("unknown TIMEZONE %r, using UTC", self.timezone)
            return ZoneInfo("UTC")

    @property
    def timezone_problem(self) -> str | None:
        try:
            ZoneInfo(self.timezone)
            return None
        except (ZoneInfoNotFoundError, ValueError):
            return (f"Unknown time zone {self.timezone!r}: dated letters use UTC instead. On your computer: "
                    "phoenix → Server → Time zone.")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "phoenix.db"

    @property
    def session_path(self) -> Path:
        # Telethon appends ".session" itself.
        return self.data_dir / "account"

    @property
    def identity_path(self) -> Path:
        return self.data_dir / "keys" / "identity.txt"

    @property
    def packages_dir(self) -> Path:
        return self.data_dir / "packages"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def require(self, *names: str) -> None:
        missing = [n.upper() for n in names if not getattr(self, n)]
        if missing:
            raise SystemExit(f"Missing settings in .env: {', '.join(missing)} (on your computer: phoenix → Server → Change the bot token or Telegram API keys)")


def load() -> Config:
    return Config(
        bot_token=os.environ.get("BOT_TOKEN", ""),
        owner_id=int(os.environ.get("OWNER_ID") or 0),
        api_id=int(os.environ.get("API_ID") or 0),
        api_hash=os.environ.get("API_HASH", ""),
        data_dir=Path(os.environ.get("DATA_DIR", "/data")),
        heartbeat_url=os.environ.get("HEARTBEAT_URL", ""),
        timezone=os.environ.get("TIMEZONE") or "Europe/Kyiv",
    )
