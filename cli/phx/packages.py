"""Packages on this PC: one folder per recipient, settings in a hidden file, and the encrypted upload."""

import contextlib
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path

from phoenix import durations

from .core import CACHE, Failed, human, need, rsync, save_config, ssh

RECIPIENT_FILE = ".recipient.toml"  # hidden: managed by the menu, not by hand
LEGACY_RECIPIENT_FILE = "recipient.toml"
META_FILES = {RECIPIENT_FILE, LEGACY_RECIPIENT_FILE, ".capsule.toml"}
ACCOUNT_TOML = "_account.toml"
CAPSULES_DIR = "_capsules"  # time capsules: one folder each, sent on their date whatever happens
CAPSULE_FILE = ".capsule.toml"
ACCOUNT_BLOB = "_account.json.age"
STAGING = CACHE / "staging"
PUSHED = CACHE / "pushed"  # fingerprint of the packages as last uploaded
TEXT_SUFFIXES = {".txt", ".md"}
VOICE_SUFFIXES = {".ogg", ".oga", ".opus"}
ROUND_SUFFIX = ".round.mp4"
TRIGGERS = ("silence", "panic")
TG_FILE_LIMIT = 2000 * 1024 * 1024  # Telegram limit for non-Premium accounts
HORIZON = 364 * 86400  # Telegram keeps scheduled messages for up to a year
TEMPLATE_MARK = "PHOENIX-TEMPLATE"  # left in files created by older versions
D = 86400


def h16(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def dur_str(seconds: int) -> str:
    """Exact, re-parseable duration: 90000 → '1d1h'."""
    out, s = "", int(seconds)
    for unit, size in (("y", 365 * D), ("d", D), ("h", 3600), ("m", 60)):
        q, s = divmod(s, size)
        out += f"{q}{unit}" if q else ""
    return out or "0m"


def norm_on(value, default) -> list[str]:
    on = value if isinstance(value, list) and value and all(t in TRIGGERS for t in value) else default
    return [t for t in TRIGGERS if t in on]


def to_seconds(value, default: int = 0) -> int:
    try:
        return durations.parse(str(value)) if value else default
    except ValueError:
        return default


def parse_duration(value, where: str, problems: list[str]) -> int:
    if value is None:
        return 0
    try:
        return durations.parse(str(value))
    except ValueError as e:
        problems.append(f"{where}: {e}")
        return 0


def parse_on(value, where: str, problems: list[str], default) -> list[str]:
    on = value if value is not None else list(default)
    if not isinstance(on, list) or not on or any(t not in TRIGGERS for t in on):
        problems.append(f"{where}: 'on' must be a list with \"silence\" and/or \"panic\"")
        return list(default)
    return on


def item_schedule(rel: str, problems: list[str], where: str) -> dict:
    """The deepest folder named @+<duration> or @<date> decides when an item is sent."""
    for part in reversed(rel.split("/")[:-1]):
        if not part.startswith("@"):
            continue
        spec = part[1:]
        if spec.startswith("+"):
            return {"after": parse_duration(spec[1:], where, problems)}
        try:
            when = datetime.fromisoformat(spec)
        except ValueError:
            problems.append(f"{where}: folder '{part}' must look like @+1y or @2034-05-12 or @2034-05-12T18:30")
            return {}
        if "T" not in spec:
            when = when.replace(hour=9)
        return {"date": when.isoformat(timespec="minutes")}
    return {}


def item_kind(p: Path) -> str:
    name = p.name.lower()
    if name.endswith(ROUND_SUFFIX):
        return "round"
    if p.suffix.lower() in VOICE_SUFFIXES:
        return "voice"
    return "text" if p.suffix.lower() in TEXT_SUFFIXES else "file"


def meta_file(d: Path) -> Path:
    legacy = d / LEGACY_RECIPIENT_FILE
    return legacy if legacy.exists() and not (d / RECIPIENT_FILE).exists() else d / RECIPIENT_FILE


def natural_key(text: str) -> list[tuple[int, int | str]]:
    """Sort numbers by value, so "11-…" comes before "100-…"."""
    return [(0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"(\d+)", text) if part]


JUNK_NAMES = {"thumbs.db", "desktop.ini", "ehthumbs.db"}
JUNK_SUFFIXES = ("~", ".swp", ".swo", ".part", ".crdownload", ".tmp", ".bak")


def is_junk(p: Path) -> bool:
    """Files nobody means to send: hidden files, OS thumbnails, editor backups, half-copied downloads."""
    name = p.name.lower()
    return name.startswith(".") or name in JUNK_NAMES or name.endswith(JUNK_SUFFIXES)


def package_files(d: Path) -> list[Path]:
    """Everything that gets sent, in sending order."""
    return sorted(
        (
            p for p in d.rglob("*")
            if p.is_file()
            and p.relative_to(d).as_posix() not in META_FILES
            and not any(part.startswith(".") for part in p.relative_to(d).parts)
            and not is_junk(p)
        ),
        key=lambda p: natural_key(p.relative_to(d).as_posix()),
    )


def recipient_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def read_package(d: Path) -> tuple[dict, list[dict], list[str]]:
    problems = []
    try:
        meta = tomllib.loads(meta_file(d).read_text())
    except FileNotFoundError:
        return {}, [], [f"{d.name}: who receives it is not set (Recipients → them → Settings)"]
    except tomllib.TOMLDecodeError as e:
        return {}, [], [f"{d.name}: broken settings file ({e}); Recipients → them → Settings"]
    label = str(meta.get("name") or d.name)
    if not str(meta.get("telegram", "")).strip() or meta.get("telegram") == "@username":
        problems.append(f"{label}: their Telegram is not set (Recipients → them → Settings)")
    if meta.get("backup") == "@someone_else":
        problems.append(f"{label}: the backup person's Telegram is not set (Recipients → them → Settings)")
    where = f"{label} settings"
    manifest = {
        "name": label.strip(),
        "telegram": str(meta.get("telegram", "")).strip(),
        "on": parse_on(meta.get("on"), where, problems, TRIGGERS),
        "delay": parse_duration(meta.get("delay"), where, problems),
    }
    if meta.get("backup"):
        manifest["backup"] = str(meta["backup"]).strip()
        manifest["backup_after"] = parse_duration(meta.get("backup_after", "7d"), where, problems)
        if meta.get("backup_note"):
            manifest["backup_note"] = str(meta["backup_note"])

    files = package_files(d)
    if not files:
        problems.append(f"{label}: nothing to send yet (write a message or add files)")
    items = []
    for p in files:
        rel = p.relative_to(d).as_posix()
        kind = item_kind(p)
        if kind == "text":
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                problems.append(f"{label}: {rel} is not UTF-8 text")
                continue
            if TEMPLATE_MARK in text:
                problems.append(f"{label}: {rel} still contains the instructions template (Recipients → them → Edit a message)")
        elif p.stat().st_size > TG_FILE_LIMIT:
            problems.append(f"{label}: {rel} is {human(p.stat().st_size)}, over Telegram's 2 GB limit; split it")
        items.append({"path": p, "rel": rel, "kind": kind, **item_schedule(rel, problems, f"{label}: {rel}")})
    return manifest, items, problems


# ------------------------------------------------------------------ time capsules
def capsule_dirs(root: Path) -> list[Path]:
    base = root / CAPSULES_DIR
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")) if base.exists() else []


def load_capsule(d: Path) -> dict:
    try:
        meta = tomllib.loads((d / CAPSULE_FILE).read_text())
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        meta = {}
    return {"name": str(meta.get("name", "")).strip() or d.name, "telegram": str(meta.get("telegram", "")).strip(),
            "date": str(meta.get("date", "")).strip()}


def save_capsule(d: Path, meta: dict) -> None:
    lines = ["# Managed by `phoenix`: change these in its menu rather than here."]
    lines += [f"{k} = {json.dumps(meta[k], ensure_ascii=False)}" for k in ("name", "telegram", "date") if meta.get(k)]
    (d / CAPSULE_FILE).write_text("\n".join(lines) + "\n")


def read_capsule(d: Path) -> tuple[dict, list[dict], list[str]]:
    """Like read_package, for a time capsule: one date for everything, no triggers, no backup."""
    meta, problems = load_capsule(d), []
    label = f"Time capsule “{meta['name']}”"
    if not meta["telegram"]:
        problems.append(f"{label}: who receives it is not set (Time capsules → it → Settings)")
    try:
        when = datetime.fromisoformat(meta["date"])
    except ValueError:
        when = None
        problems.append(f"{label}: the date is not set (Time capsules → it → Settings)")
    files = package_files(d)
    if not files:
        problems.append(f"{label}: nothing to send yet (write a message or add files)")
    items = []
    for p in files:
        rel = p.relative_to(d).as_posix()
        kind = item_kind(p)
        if kind == "text":
            try:
                p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                problems.append(f"{label}: {rel} is not UTF-8 text")
                continue
        elif p.stat().st_size > TG_FILE_LIMIT:
            problems.append(f"{label}: {rel} is {human(p.stat().st_size)}, over Telegram's 2 GB limit; split it")
        items.append({"path": p, "rel": rel, "kind": kind})
    manifest = {"name": meta["name"], "telegram": meta["telegram"], "on": [], "delay": 0,
                "capsule_date": when.isoformat(timespec="minutes") if when else ""}
    return manifest, items, problems


def read_account(f: Path) -> tuple[dict | None, list[str]]:
    if not f.exists():
        return None, []
    problems, where = [], "Account actions"
    text = f.read_text()
    if TEMPLATE_MARK in text:
        return None, [f"{where}: still an unedited template (open “Your account after the trigger” and change anything)"]
    try:
        meta = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return None, [f"{where}: {e}"]
    out = {"on": parse_on(meta.get("on"), where, problems, ("silence",))}
    if meta.get("autoreply", "").strip():
        out["autoreply"] = meta["autoreply"].strip()
    if "about" in meta:
        out["about"] = str(meta["about"])
        if len(out["about"]) > 140:
            problems.append(f"{where}: the bio is too long (Telegram allows 70 characters, 140 with Premium)")
    out["posts"] = []
    for n, post in enumerate(meta.get("post", []), 1):
        if not post.get("chat") or not str(post.get("text", "")).strip():
            problems.append(f"{where}: post #{n} needs a chat and a text")
            continue
        out["posts"].append({
            "chat": str(post["chat"]).strip(), "text": str(post["text"]).strip(),
            "delay": parse_duration(post.get("delay"), f"{where} post #{n}", problems),
        })
    return out, problems


def load_meta(d: Path) -> dict:
    try:
        meta = tomllib.loads(meta_file(d).read_text())
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        meta = {}
    telegram = str(meta.get("telegram", "")).strip()
    backup = str(meta.get("backup", "")).strip()
    return {
        "name": str(meta.get("name", "")).strip() or d.name,
        "telegram": "" if telegram == "@username" else telegram,
        "on": norm_on(meta.get("on"), TRIGGERS),
        "delay": to_seconds(meta.get("delay")),
        "backup": "" if backup == "@someone_else" else backup,
        "backup_after": to_seconds(meta.get("backup_after"), 7 * D),
        "backup_note": str(meta.get("backup_note", "")).strip(),
    }


def save_meta(d: Path, meta: dict) -> None:
    lines = ["# Managed by `phoenix`: change these in its menu rather than here."]
    values = {
        "name": meta["name"],
        "telegram": meta["telegram"],
        "on": meta["on"],
        "delay": dur_str(meta["delay"]) if meta["delay"] else "",
        "backup": meta["backup"],
        "backup_after": dur_str(meta["backup_after"]) if meta["backup"] else "",
        "backup_note": meta["backup_note"] if meta["backup"] else "",
    }
    lines += [f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in values.items() if v]
    (d / RECIPIENT_FILE).write_text("\n".join(lines) + "\n")
    (d / LEGACY_RECIPIENT_FILE).unlink(missing_ok=True)


def migrate(root: Path) -> None:
    """Hide recipient.toml files from older versions: settings now live in the menu."""
    for d in recipient_dirs(root):
        legacy = d / LEGACY_RECIPIENT_FILE
        if legacy.exists() and not (d / RECIPIENT_FILE).exists():
            with contextlib.suppress(tomllib.TOMLDecodeError):
                tomllib.loads(legacy.read_text())
                save_meta(d, load_meta(d))


def folder_for(root: Path, name: str) -> Path:
    base = re.sub(r"[/\\\x00]", "-", name).strip().lstrip("._@") or "recipient"
    d, n = root / base, 2
    while d.exists():
        d, n = root / f"{base}-{n}", n + 1
    return d


def next_number(d: Path) -> int:
    nums = [int(m.group(1)) for p in package_files(d) if (m := re.match(r"(\d+)-", p.name))]
    return max(nums, default=0) + 1


def load_account(root: Path) -> dict:
    try:
        meta = tomllib.loads((root / ACCOUNT_TOML).read_text())
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        meta = {}
    return {
        "on": norm_on(meta.get("on"), ("silence",)),
        "autoreply": str(meta.get("autoreply", "")).strip(),
        "about": str(meta.get("about", "")).strip(),
        "posts": [
            {"chat": str(p.get("chat", "")), "text": str(p.get("text", "")).strip(), "delay": to_seconds(p.get("delay"))}
            for p in meta.get("post", [])
        ],
    }


def save_account(root: Path, acc: dict) -> None:
    f = root / ACCOUNT_TOML
    if not (acc["autoreply"] or acc["about"] or acc["posts"]):
        f.unlink(missing_ok=True)
        return
    q = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
    lines = ["# Managed by `phoenix`: change these in its menu rather than here.", f"on = {q(acc['on'])}"]
    lines += [f"{k} = {q(acc[k])}" for k in ("autoreply", "about") if acc[k]]
    for post in acc["posts"]:
        lines += ["", "[[post]]", f"chat = {q(post['chat'])}", f"text = {q(post['text'])}"]
        lines += [f"delay = {q(dur_str(post['delay']))}"] if post["delay"] else []
    f.write_text("\n".join(lines) + "\n")


def latest_offset(manifest: dict, items: list[dict]) -> float:
    now = datetime.now()
    offsets = [manifest["delay"] + i.get("after", 0) for i in items]
    offsets += [(datetime.fromisoformat(i["date"]) - now).total_seconds() for i in items if i.get("date")]
    return max(offsets, default=0)


def age_encrypt(public_key: str, dst: Path, *, src: Path | None = None, data: bytes | None = None) -> None:
    part = dst.with_name(dst.name + ".part")
    args = ["age", "-r", public_key, "-o", str(part)] + ([str(src)] if src else [])
    r = subprocess.run(args, input=data, capture_output=True)
    if r.returncode:
        raise Failed(f"encryption failed on {src or dst.name}: {r.stderr.decode().strip()}")
    part.replace(dst)


class Problems(Failed):
    def __init__(self, problems: list[str]):
        super().__init__("fix these first:\n  " + "\n  ".join(problems))
        self.problems = problems


def tree_signature(root: Path) -> str:
    entries = sorted(
        f"{p.relative_to(root).as_posix()}|{st.st_size}|{st.st_mtime_ns}"
        for p in root.rglob("*") if p.is_file() for st in [p.stat()]
    )
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


def is_uploaded(root: Path) -> bool:
    return PUSHED.exists() and PUSHED.read_text() == tree_signature(root)


def push_from(cfg: dict, packages_dir: Path) -> None:
    need("age", "rsync")
    public_key = cfg.get("public_key")
    if not public_key:
        raise Failed("the server's encryption key is unknown: finish the setup first (Server → Update Phoenix)")
    dirs = sorted(p for p in packages_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    capsules = capsule_dirs(packages_dir)
    if not dirs and not capsules:
        raise Problems(["there are no recipients yet (Recipients → Add a recipient)"])

    loaded, problems = [], []
    for d in dirs:
        manifest, items, issues = read_package(d)
        problems += issues
        loaded.append((d, manifest, items, ""))
    for d in capsules:
        manifest, items, issues = read_capsule(d)
        problems += issues
        loaded.append((d, manifest, items, CAPSULES_DIR))
    account, issues = read_account(packages_dir / ACCOUNT_TOML)
    problems += issues
    if problems:
        raise Problems(problems)

    # Names on the server are hashed with a secret that never leaves this computer, so a folder called
    # "mom" can't be recognized by hashing likely names.
    if not cfg.get("name_salt"):
        cfg["name_salt"] = secrets.token_hex(16)
        save_config(cfg)
    salt = cfg["name_salt"]

    STAGING.mkdir(parents=True, exist_ok=True)
    cache_path = STAGING.parent / "cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    new_cache, keep = {}, set()

    keep_capsules = set()
    for d, manifest, items, area in loaded:
        hid = h16(f"{salt}:{area or 'package'}:{d.name}")
        out = STAGING / area / hid if area else STAGING / hid
        out.mkdir(parents=True, exist_ok=True)
        (keep_capsules if area else keep).add(hid)
        entries, keep_blobs = [], {"manifest.json.age"}
        for item in items:
            key = f"{area}/{d.name}/{item['rel']}" if area else f"{d.name}/{item['rel']}"
            iid = h16(f"{salt}:{key}")
            blob = f"{iid}.age"
            st = item["path"].stat()
            stamp = [st.st_size, st.st_mtime_ns, public_key]
            if cache.get(iid) != stamp or not (out / blob).exists():  # the cache holds no names, only hashes
                print(f"  encrypting {key} ({human(st.st_size)})")
                age_encrypt(public_key, out / blob, src=item["path"])
            new_cache[iid] = stamp
            keep_blobs.add(blob)
            entry = {"id": iid, "kind": item["kind"], "name": item["path"].name, "blob": blob, "size": st.st_size}
            entry.update({k: item[k] for k in ("after", "date") if k in item})
            entries.append(entry)
        age_encrypt(public_key, out / "manifest.json.age", data=json.dumps({**manifest, "items": entries}).encode())
        for stale in out.iterdir():
            if stale.name not in keep_blobs:
                stale.unlink()

        total = sum(e["size"] for e in entries)
        if area:
            print(f"✔ time capsule “{manifest['name']}” → {manifest['telegram']}: {len(entries)} item(s), "
                  f"{human(total)}, on {manifest['capsule_date'].replace('T', ' at ')}")
            continue
        extras = []
        if tuple(manifest["on"]) != TRIGGERS:
            extras.append(f"only on {manifest['on'][0]}")
        if manifest["delay"]:
            extras.append(f"starts {durations.fmt(manifest['delay'])} after trigger")
        later = sum(1 for i in items if "after" in i or "date" in i)
        if later:
            extras.append(f"{later} scheduled later")
        if manifest.get("backup"):
            extras.append(f"backup {manifest['backup']}")
        print(f"✔ {manifest['name']} → {manifest['telegram']}: {len(entries)} item(s), {human(total)}"
              + (f" ({', '.join(extras)})" if extras else ""))
        latest = latest_offset(manifest, items)
        if latest > HORIZON:
            print(f"  ⚠️ last item is {durations.fmt(latest)} after trigger: the server must stay alive and paid "
                  f"for {durations.fmt(latest - HORIZON)} after the trigger to hand it to Telegram.")

    account_blob = STAGING / ACCOUNT_BLOB
    if account:
        age_encrypt(public_key, account_blob, data=json.dumps(account).encode())
        keep.add(ACCOUNT_BLOB)
        parts = [n for n in ("autoreply", "about") if n in account] + [f"{len(account['posts'])} post(s)"]
        print(f"✔ account actions on {', '.join(account['on'])}: {', '.join(parts)}")

    if keep_capsules:
        keep.add(CAPSULES_DIR)
        for stale in (STAGING / CAPSULES_DIR).iterdir():
            if stale.name not in keep_capsules:
                shutil.rmtree(stale)
    for stale in STAGING.iterdir():
        if stale.name not in keep:
            shutil.rmtree(stale) if stale.is_dir() else stale.unlink()
    cache_path.write_text(json.dumps(new_cache))

    print("Uploading…")
    if ssh(cfg, "mkdir -p data/packages").returncode:
        raise Failed(f"cannot reach the server {cfg['server']}")
    rsync(cfg, "-a", "--delete", "--info=progress2", f"{STAGING}/", f"{cfg['server']}:{cfg['remote_dir']}/data/packages/")
    PUSHED.write_text(tree_signature(packages_dir))
    print("✅ Uploaded. Within a minute your bot confirms that every recipient was found.")
