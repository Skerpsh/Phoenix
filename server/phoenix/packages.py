"""Encrypted packages uploaded by the CLI.

Layout on the server (all names are hashes, nothing readable on disk):
    packages/<package-hash>/manifest.json.age
    packages/<package-hash>/<item-hash>.age
    packages/_account.json.age            (optional: what to do with your account on trigger)
    packages/_capsules/<hash>/...         (time capsules: sent on their date, whatever happens)
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path

from .crypto import Crypto
from .durations import fmt

TRIGGERS = ("silence", "panic")
ACCOUNT_FILE = "_account.json.age"
CAPSULES_DIR = "_capsules"
DEFAULT_BACKUP_AFTER = 7 * 86400


@dataclass
class Item:
    id: str
    kind: str  # text | file | voice | round
    name: str
    size: int
    blob: Path | None = None  # encrypted file, or…
    text: str | None = None  # …inline text (account posts)
    after: int = 0  # seconds after the package start
    date: str | None = None  # or a fixed local date-time, ISO format

    def due(self, start: float, tz: tzinfo) -> float:
        if self.date:
            return max(start, datetime.fromisoformat(self.date).replace(tzinfo=tz).timestamp())
        return start + self.after

    def when(self, delay: int) -> str:
        if self.date:
            return f"on {self.date.replace('T', ' ')} (right away if that date has already passed)"
        total = delay + self.after
        return f"{fmt(total)} after the trigger" if total else "right away"


@dataclass
class Package:
    hid: str
    name: str
    telegram: str
    items: list[Item]
    on: tuple[str, ...] = TRIGGERS
    delay: int = 0
    backup: str | None = None
    backup_after: int = DEFAULT_BACKUP_AFTER
    backup_note: str | None = None
    capsule_date: str | None = None  # a time capsule: sent on this local date-time, trigger or not

    @property
    def size(self) -> int:
        return sum(i.size for i in self.items)

    @property
    def backup_key(self) -> str:
        return f"{self.hid}~backup"

    def start(self, trigger_ts: float) -> float:
        return trigger_ts + self.delay

    def capsule_due(self, tz: tzinfo) -> float:
        return datetime.fromisoformat(self.capsule_date).replace(tzinfo=tz).timestamp()

    def latest_offset(self, now: float, tz: tzinfo) -> float:
        """How far after a trigger right now the last item would be sent (in seconds)."""
        return max((i.due(self.start(now), tz) - now for i in self.items), default=0)


@dataclass
class AccountActions:
    on: tuple[str, ...] = ("silence",)
    autoreply: str | None = None
    about: str | None = None
    posts: list[Package] = field(default_factory=list)


@dataclass
class Loaded:
    packages: list[Package]
    actions: AccountActions | None
    errors: list[str]
    capsules: list[Package] = field(default_factory=list)

    def active(self, kind: str) -> list[Package]:
        posts = self.actions.posts if self.actions and kind in self.actions.on else []
        return [p for p in self.packages if kind in p.on] + posts


def package_dirs(packages_dir: Path) -> list[Path]:
    if not packages_dir.exists():
        return []
    return sorted(p for p in packages_dir.iterdir() if p.is_dir() and not p.name.startswith("_"))


def _load_package(d: Path, crypto: Crypto) -> Package:
    m = json.loads(crypto.decrypt_bytes(d / "manifest.json.age"))
    items = [
        Item(
            id=i["id"], kind=i["kind"], name=i["name"], size=i["size"], blob=d / i["blob"],
            after=i.get("after", 0), date=i.get("date"),
        )
        for i in m["items"]
    ]
    missing = [i.name for i in items if not i.blob.exists()]
    if missing:
        raise ValueError(f"missing files: {', '.join(missing)}")
    return Package(
        hid=d.name, name=m["name"], telegram=m["telegram"], items=items,
        on=tuple(m.get("on", TRIGGERS)), delay=m.get("delay", 0),
        backup=m.get("backup"), backup_after=m.get("backup_after", DEFAULT_BACKUP_AFTER),
        backup_note=m.get("backup_note"), capsule_date=m.get("capsule_date"),
    )


def _load_actions(path: Path, crypto: Crypto) -> AccountActions:
    m = json.loads(crypto.decrypt_bytes(path))
    on = tuple(m.get("on", ("silence",)))
    posts = [
        Package(
            hid=f"_post{n}", name=f"Post to {p['chat']}", telegram=p["chat"], on=on, delay=p.get("delay", 0),
            items=[Item(id="text", kind="text", name="post", size=len(p["text"]), text=p["text"])],
        )
        for n, p in enumerate(m.get("posts", []))
    ]
    return AccountActions(on=on, autoreply=m.get("autoreply"), about=m.get("about"), posts=posts)


def load_all(packages_dir: Path, crypto: Crypto) -> Loaded:
    packages, errors, actions = [], [], None
    for d in package_dirs(packages_dir):
        try:
            packages.append(_load_package(d, crypto))
        except Exception as e:
            errors.append(f"package {d.name}: {e}")
    account_file = packages_dir / ACCOUNT_FILE
    if account_file.exists():
        try:
            actions = _load_actions(account_file, crypto)
        except Exception as e:
            errors.append(f"account actions: {e}")
    capsules = []
    for d in package_dirs(packages_dir / CAPSULES_DIR):
        try:
            capsules.append(_load_package(d, crypto))
        except Exception as e:
            errors.append(f"time capsule {d.name}: {e}")
    return Loaded(packages, actions, errors, capsules)


def signature(packages_dir: Path) -> str:
    """Changes whenever the CLI pushes new packages."""
    h = hashlib.sha256()
    dirs = package_dirs(packages_dir) + package_dirs(packages_dir / CAPSULES_DIR)
    files = [d / "manifest.json.age" for d in dirs] + [packages_dir / ACCOUNT_FILE]
    for m in files:
        if m.exists():
            st = m.stat()
            h.update(f"{m.parent.name}/{m.name}:{st.st_mtime_ns}:{st.st_size};".encode())
    return h.hexdigest()


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
