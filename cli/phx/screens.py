"""The menus behind `phoenix`: first-time setup, then everything else."""

import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import date
from pathlib import Path

from phoenix import PROTOCOL
from phoenix.durations import fmt

from . import core, ui
from . import packages as pk
from .core import Failed
from .ui import BOLD, DIM, ON_LABELS, RESET

STEPS = [
    ("server", "Connect to your server"),
    ("bootstrap", "Prepare the server: updates, Docker, firewall"),
    ("deploy", "Install Phoenix on the server"),
    ("keys", "Connect your control bot and Telegram API keys"),
    ("login", "Log the server into your Telegram account"),
    ("vault", "Password-protect your packages on this computer"),
    ("start", "Say hello to your bot"),
]

TIMERS = [
    ("checkin_interval", "Check in at least every"),
    ("button_every", "Press “I'm OK” at least every"),
    ("reminder_every", "After a missed check-in, remind me every"),
    ("alarm_after", "Alarm starts this long after a missed check-in"),
    ("alarm_every", "During the alarm, remind me every"),
    ("trigger_after", "Delivery this long after a missed check-in"),
    ("alarm_min", "The alarm always lasts at least"),
    ("panic_delay", "Time to cancel after the panic button"),
    ("review_every", "Ask me to review my packages every"),
]

KIND_ICONS = {"text": "💬", "voice": "🎤", "round": "⭕", "file": "📎"}
TELEGRAM_QUESTION = "Their Telegram (@username, a t.me link, or +phone saved in your contacts)"


def local_timezone() -> str:
    with contextlib.suppress(OSError):
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    return "Europe/Kyiv"


class Restart(Exception):
    """Phoenix on this computer was updated: start the menu again with the new code."""


def open_folder(path: Path) -> None:
    core.open_path(path)
    ui.note(f"📂 Opened {path} in your file manager.")


def open_editor(path: Path) -> None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or shutil.which("nano") or shutil.which("vi")
    if not editor:
        core.open_path(path)
        input("Edit the file in the window that opened, save it, then press Enter… ")
        return
    if Path(shlex.split(editor)[0]).name == "nano":
        print("nano: save with Ctrl+O then Enter, exit with Ctrl+X")
    subprocess.run([*shlex.split(editor), str(path)])


def when_label(rel: str) -> str:
    sched = pk.item_schedule(rel, [], "")
    if "after" in sched:
        return f"⏰ {pk.dur_str(sched['after'])} after the rest"
    if "date" in sched:
        return f"⏰ on {sched['date'].replace('T', ' at ')}"
    return ""


def item_label(d: Path, p: Path) -> str:
    kind = pk.item_kind(p)
    if kind == "text":
        try:
            first = next((ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()), "")
        except UnicodeDecodeError:
            first = "(not UTF-8 text)"
        text = f'"{first[:50]}{"…" if len(first) > 50 else ""}"'
    else:
        text = f"{p.name} ({core.human(p.stat().st_size)})"
    return f"{KIND_ICONS[kind]} {text}  {when_label(p.relative_to(d).as_posix())}".rstrip()


def recipient_line(d: Path) -> str:
    meta, files = pk.load_meta(d), pk.package_files(d)
    size = sum(p.stat().st_size for p in files)
    line = f"{meta['name']} → {meta['telegram'] or '(Telegram not set)'} · {len(files)} item(s), {core.human(size)}"
    return line + ("  ⚠️" if pk.read_package(d)[2] else "")


def short(text: str, n: int = 50) -> str:
    text = " ".join(text.split())
    return f'"{text[:n]}{"…" if len(text) > n else ""}"'


class App:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._stack = contextlib.ExitStack()
        self._root: Path | None = None
        self.summary: dict | None = None
        self.summary_error = ""

    # ------------------------------------------------------------------ helpers
    def root(self) -> Path:
        """The packages folder; unlocks the vault the first time it's needed and keeps it open until quit."""
        if self._root is None:
            self._root = self._stack.enter_context(core.packages_root(self.cfg, lock_existing=True))
            pk.migrate(self._root)
        return self._root

    def close(self) -> None:
        self._stack.close()
        self._stack = contextlib.ExitStack()
        self._root = None

    def ctl(self, *args: str) -> str:
        return core.ctl(self.cfg, *args)

    def run(self, action) -> None:
        try:
            action()
        except Restart:
            raise
        except Failed as e:
            print(f"\n❌ {e}")
            ui.pause()
        except KeyboardInterrupt:
            ui.note("(cancelled)")

    def refresh(self) -> None:
        try:
            self.summary = json.loads(self.ctl("summary"))
            self.summary_error = ""
            if self.summary.get("protocol") != PROTOCOL:
                self.summary_error = "The server runs another Phoenix version: choose Server → Update Phoenix."
        except Failed as e:
            self.summary = None
            self.summary_error = str(e)
            if "unknown command" in self.summary_error:
                self.summary_error = "The server runs an older Phoenix: choose Server → Update Phoenix."
        except json.JSONDecodeError:
            self.summary, self.summary_error = None, "The server sent an unexpected answer (Server → Update Phoenix)."

    def header(self) -> str:
        lines = [f"{BOLD}🔥 Phoenix{RESET}  {DIM}{self.cfg.get('server', '')}{RESET}"]
        s = self.summary
        if self.summary_error:
            lines.append(f"⚠️ {self.summary_error}")
        if s:
            state = s["phase_label"]
            if s["paused_for"]:
                state += f" · ⏸ paused for another {fmt(s['paused_for'])}"
            elif s["due_in"] is not None:
                due = s["due_in"]
                state += f" · next check-in in {fmt(due)}" if due > 0 else f" · ⚠️ check-in overdue by {fmt(-due)}"
            lines.append(state)
            if s["panic_pending"]:
                lines.append(f"🚨 Panic pending: delivery in {fmt(s['eta_in'])}")
            elif s["eta_in"] is not None:
                lines.append(f"{DIM}If you stay silent, delivery starts in {fmt(s['eta_in'])}{RESET}")
            health = {True: "✅", False: "⚠️"}.get(s["health_ok"], "…")
            lines.append(f"Telegram: {health} {s['health_text'] or 'not checked yet'}")
            lines.append(f"Packages on the server: {s['packages']}")
            if not s["paid_until"]:
                lines.append(f"{DIM}💳 Tip: set the hosting paid-until date in Server, to get reminders{RESET}")
        if self._root is not None and pk.recipient_dirs(self._root) and not pk.is_uploaded(self._root):
            lines.append("⬆️ You have changes that are not on the server yet")
        return "\n".join(lines)

    # --------------------------------------------------------------------- setup
    def setup_complete(self) -> bool:
        if "setup" not in self.cfg and self.cfg.get("public_key"):  # set up before the menu existed
            self.cfg["setup"] = [key for key, _ in STEPS]
            core.save_config(self.cfg)
        return all(key in self.cfg.get("setup", []) for key, _ in STEPS)

    def setup(self) -> bool:
        while True:
            done = self.cfg.setdefault("setup", [])
            todo = [key for key, _ in STEPS if key not in done]
            if not todo:
                return True
            lines = [f"{BOLD}🔥 Phoenix setup{RESET}", "Step by step; you can quit any time and continue later.", ""]
            for i, (key, title) in enumerate(STEPS, 1):
                mark = "✅" if key in done else ("➜ " if key == todo[0] else "  ")
                lines.append(f" {mark} {i}. {title}")
            title = dict(STEPS)[todo[0]]
            if ui.select(f"Next: {title}", ["▶ Continue"], header="\n".join(lines), back="Quit for now") is None:
                return False
            print(f"{BOLD}{title}{RESET}\n")
            try:
                getattr(self, f"step_{todo[0]}")()
                done.append(todo[0])
                core.save_config(self.cfg)
            except Failed as e:
                print(f"\n❌ {e}")
                ui.pause()
            except KeyboardInterrupt:
                ui.note("(cancelled)")

    def step_server(self) -> None:
        cfg = self.cfg
        ui.explain("Phoenix runs on a small rented server (VPS) with Ubuntu 24.04+ or Debian 12+.\n"
                   "Its IP address is in your hosting control panel or in the email from your host.")
        ui.explain("Most hosts give you the user root. Some (e.g. OVH, AWS) use another user such as ubuntu:\n"
                   "then type it as ubuntu@203.0.113.7.")
        host = ui.ask("Server IP address", cfg.get("server", "").removeprefix("root@"))
        if not host:
            raise Failed("no address entered")
        cfg["server"] = host if "@" in host else f"root@{host}"
        cfg.setdefault("remote_dir", "/opt/phoenix")
        cfg.setdefault("packages_dir", str(core.DEFAULT_PACKAGES))
        core.save_config(cfg)
        print("Checking the connection…")
        if not core.key_login_works(cfg):
            self.install_ssh_key()
        core.check_admin(cfg)
        core.save_config(cfg)
        print(f"✅ Connected{' (using sudo)' if cfg['sudo'] else ''}.")

    def install_ssh_key(self) -> None:
        cfg = self.cfg
        key = core.public_ssh_key()
        if key is None:
            print("\nThis computer has no SSH key yet; creating one.")
            ui.explain("It may ask for a passphrase to protect the key: type one, or just press Enter twice.")
            core.sh("ssh-keygen", "-t", "ed25519", "-f", str(Path.home() / ".ssh" / "id_ed25519"))
            key = core.public_ssh_key()
        print(f"\nCopying your key to the server. When asked, type the PASSWORD of {cfg['server']}")
        ui.explain("(from your hosting panel or email; typing is invisible). After this, the password is no longer needed.")
        core.sh("ssh-copy-id", "-i", str(key), *core.ssh_opts(shared=False), cfg["server"])
        if not core.key_login_works(cfg):
            raise Failed("the server still doesn't accept the key; check the IP address and try again")

    def step_bootstrap(self) -> None:
        ui.explain("Installs updates, Docker and a firewall, and turns off password login (your key is used instead).\n"
                   "Existing firewall rules are kept. This takes a few minutes.\n")
        core.bootstrap(self.cfg)

    def step_deploy(self) -> None:
        core.deploy(self.cfg)
        print("✅ Installed.")

    def step_keys(self, *, restart: bool = False) -> None:
        old = core.read_env(self.cfg)
        print(f"{BOLD}1/4 · Your control bot{RESET}: Phoenix uses it to talk to you.")
        ui.explain("  In Telegram open @BotFather → /newbot → pick any name, then a username ending in “bot”.\n"
                   "  BotFather answers with a token like 123456789:AAHk3…")
        while True:
            token = ui.ask_secret("Bot token", keep=bool(old.get("BOT_TOKEN"))) or old.get("BOT_TOKEN", "")
            if re.fullmatch(r"\d+:[\w-]{30,}", token):
                break
            print("  That's not a bot token. It looks like 123456789:AAHk3… (copy it whole from BotFather).")
        print(f"\n{BOLD}2/4 · Your Telegram user id{RESET}: the bot obeys only you.")
        ui.explain("  Open @userinfobot in Telegram and press Start: it shows your Id (a number).")
        while not (owner := ui.ask("Your user id", old.get("OWNER_ID", ""))).isdigit():
            print("  It's a number, like 123456789.")
        print(f"\n{BOLD}3/4 · API keys{RESET}: let the server send messages from your account.")
        ui.explain("  Open https://my.telegram.org → log in with your phone → “API development tools”.\n"
                   "  Create an app: any title and short name, platform “Desktop”. You get api_id and api_hash.")
        while not (api_id := ui.ask("api_id", old.get("API_ID", ""))).isdigit():
            print("  api_id is a number.")
        while True:
            api_hash = ui.ask_secret("api_hash", keep=bool(old.get("API_HASH"))) or old.get("API_HASH", "")
            if re.fullmatch(r"[0-9a-f]{32}", api_hash):
                break
            print("  api_hash is 32 characters of 0-9 and a-f.")
        print(f"\n{BOLD}4/4 · Your time zone{RESET}: for letters sent on a date.")
        tz = ui.ask("Time zone", old.get("TIMEZONE") or local_timezone())
        ui.explain("\nOptional: a free check at https://healthchecks.io (period 5 minutes) emails you if the server\n"
                   "goes down. Paste its ping URL, or press Enter to skip.")
        heartbeat = ui.ask("Heartbeat URL", old.get("HEARTBEAT_URL", ""), clearable=True)
        core.write_env(self.cfg, {
            "BOT_TOKEN": token, "OWNER_ID": owner, "API_ID": api_id, "API_HASH": api_hash,
            "TIMEZONE": tz, "HEARTBEAT_URL": heartbeat,
        })
        if restart:
            core.restart(self.cfg)
        print("✅ Saved on the server (readable only by root).")

    def step_login(self) -> None:
        ui.explain("The server logs into YOUR MAIN Telegram account, like a new device, so it can send messages as you.\n"
                   "  • Phone number in international format: +380…\n"
                   "  • Telegram sends the code to your Telegram app (not SMS).\n"
                   "  • If you have a cloud password (two-step verification), it asks for it too.\n")
        core.login(self.cfg)
        print("✅ Logged in.")

    def step_vault(self) -> None:
        if core.vault_enabled():
            print("✅ Already protected.")
            return
        ui.explain("Your packages hold passwords and private letters. The vault keeps them encrypted on this computer;\n"
                   "they open only with your password, while this menu is running.")
        while core.missing("gocryptfs"):
            choice = ui.select(f"The vault needs gocryptfs, which isn't installed. In another terminal run:\n"
                               f"  {core.install_hint(['gocryptfs'])}",
                               ["I've installed it, check again", "Skip: keep packages unencrypted on this computer"],
                               back=None)
            if choice == 1:
                return
        if ui.confirm("Protect your packages with a password?", yes="Yes (recommended)", no="No, skip", default=True):
            self.close()
            core.vault_init(self.cfg)
            ui.pause()

    def step_start(self) -> None:
        print("Open your bot in Telegram and press Start. It answers “🔥 Phoenix is armed”.")
        ui.explain("(A bot can't write to you before you press Start.)\n")
        input("Press Enter once the bot has answered… ")
        paid = ui.ask("\nOptional: until what date is your server paid? (YYYY-MM-DD, Enter to skip)")
        if paid:
            try:
                print(self.ctl("paiduntil", date.fromisoformat(paid).isoformat()))
            except (ValueError, Failed) as e:
                print(f"⚠️ Not saved ({e}); you can set it later in Server.")
        print(f"\n{BOLD}Recommended{RESET}: Telegram → Settings → Privacy and Security → “If away for” → the longest period.")
        print("\n🎉 Setup done. Next: add your recipients and what they should receive.")
        ui.pause()

    # ---------------------------------------------------------------- main menu
    def main(self, start: str | None = None) -> None:
        if start == "new":
            self.run(lambda: self.open_recipient(self.new_recipient()))
        elif start == "account":
            self.run(self.account)
        while True:
            self.refresh()
            s = self.summary or {}
            items = [
                ("✅ I'm OK: check in", self.checkin),
                ("📦 Recipients and what they receive", self.recipients),
                ("👤 Your account after the trigger: auto-reply, bio, posts", self.account),
                ("⬆️ Upload changes to the server", self.upload),
                ("🧪 Rehearsal: send everything to my Saved Messages", self.test),
                ("🔎 Check that every recipient can be found", self.verify),
                ("▶️ End the pause", self.resume) if s.get("paused_for") else ("⏸ Pause: going offline for a while", self.pause),
                ("⏱ Timers and reminders", self.timers),
            ]
            phase = s.get("phase")
            if phase == "triggered":
                items.append(("⏹ Stop the delivery and cancel scheduled messages", self.abort))
            elif phase == "done":
                items.append(("🔁 Arm Phoenix again", self.rearm))
            elif s.get("panic_pending"):
                items.append(("✋ Cancel the panic", self.cancel_panic))
            else:
                items.append(("🚨 Panic button", self.panic))
            items += [
                ("📜 History", self.history),
                ("🖥 Server", self.server),
                ("🔐 Vault on this computer", self.vault),
            ]
            try:
                idx = ui.select("What do you want to do?", [label for label, _ in items], header=self.header(), back="Quit")
            except (KeyboardInterrupt, EOFError):
                return
            if idx is None:
                if self.quit():
                    return
                continue
            self.run(items[idx][1])

    def quit(self) -> bool:
        if self._root is None or not pk.recipient_dirs(self._root) or pk.is_uploaded(self._root):
            return True
        c = ui.select("Your latest changes aren't on the server yet.",
                      ["⬆️ Upload, then quit", "Quit without uploading"], back="Stay")
        if c is None:
            return False
        if c == 0:
            try:
                pk.push_from(self.cfg, self._root)
            except Failed as e:
                print(f"\n❌ {e}")
                ui.pause()
                return False
        return True

    # ------------------------------------------------------------ switch actions
    def checkin(self) -> None:
        ui.note(self.ctl("checkin"))

    def upload(self) -> None:
        pk.push_from(self.cfg, self.root())
        ui.pause()

    def test(self) -> None:
        root = self.root()
        if not pk.is_uploaded(root) and ui.confirm(
            "Your latest changes aren't on the server yet. Upload them first?", yes="Upload first", no="Test what's there",
            default=True,
        ):
            pk.push_from(self.cfg, root)
        print("\n🧪 Starting the rehearsal…")
        print(self.ctl("request", "test"))
        print("Open Telegram → Saved Messages: you'll see exactly what each person will receive.")
        ui.pause()

    def verify(self) -> None:
        print("🔎 Checking every recipient on Telegram…\n")
        print(self.ctl("request", "verify"))
        ui.pause()

    def pause(self) -> None:
        ui.explain("Going on a trip, to hospital, somewhere without internet? While paused, nothing is sent.")
        seconds = ui.ask_duration("Pause for how long? (e.g. 2w, 30d)", required=True)
        ui.note(self.ctl("pause", pk.dur_str(seconds)))

    def resume(self) -> None:
        ui.note(self.ctl("resume"))

    def panic(self) -> None:
        delay = json.loads(self.ctl("settings"))["settings"]["panic_delay"]["value"]
        if ui.confirm(f"Start delivery now? Your packages go out in {fmt(delay)}; until then you can cancel it here or in the bot.",
                      yes="🚨 Yes, start delivery", no="No"):
            ui.note(self.ctl("panic"))

    def cancel_panic(self) -> None:
        ui.note(self.ctl("cancel"))

    def abort(self) -> None:
        if ui.confirm("Stop the delivery, cancel messages already scheduled in Telegram and restore your bio?",
                      yes="⏹ Yes, stop it", no="No"):
            ui.note(self.ctl("request", "abort"))

    def rearm(self) -> None:
        if ui.confirm("Arm Phoenix again? Messages still scheduled in Telegram are cancelled.", yes="🔁 Yes", no="No"):
            ui.note(self.ctl("request", "rearm"))

    def history(self) -> None:
        print(self.ctl("log"))
        ui.pause()

    def timers(self) -> None:
        while True:
            data = json.loads(self.ctl("settings"))
            st = {name: item["value"] for name, item in data["settings"].items()}
            header = (
                f"{BOLD}How it works{RESET}\n"
                f"Check in at least every {fmt(st['checkin_interval'])} (the button, any message to the bot,"
                f"{' or any message you send in Telegram' if data['activity'] else ''}).\n"
                f"Miss it, and Phoenix reminds you every {fmt(st['reminder_every'])};"
                f" {fmt(st['alarm_after'])} later it raises the alarm (every {fmt(st['alarm_every'])});\n"
                f"{fmt(st['trigger_after'])} after the missed check-in it delivers your packages."
            )
            options = [f"{label}: {fmt(st[name])}" for name, label in TIMERS]
            options.append(f"Messages you send anywhere in Telegram count as a check-in: {'yes' if data['activity'] else 'no'}")
            idx = ui.select("Timers and reminders", options, header=header)
            if idx is None:
                return
            try:
                if idx == len(TIMERS):
                    ui.note(self.ctl("activity", "off" if data["activity"] else "on"))
                    continue
                name, label = TIMERS[idx]
                ui.explain(data["settings"][name]["help"].capitalize() + ".")
                seconds = ui.ask_duration(label, st[name], required=True)
                ui.note(self.ctl("set", name, pk.dur_str(seconds)))
            except Failed as e:
                ui.note(f"❌ {e}")

    # ---------------------------------------------------------------- recipients
    def recipients(self) -> None:
        root = self.root()
        while True:
            dirs = pk.recipient_dirs(root)
            header = f"{BOLD}📦 Recipients{RESET}\nEach person gets only what you prepare for them, from your own Telegram account."
            idx = ui.select("Choose someone, or add a new person", [recipient_line(d) for d in dirs] + ["➕ Add a recipient"],
                            header=header)
            if idx is None:
                return
            pick = None if idx == len(dirs) else dirs[idx]
            self.run(lambda pick=pick: self.open_recipient(pick or self.new_recipient()))

    def new_recipient(self) -> Path:
        root = self.root()
        print(f"{BOLD}➕ New recipient{RESET}\n")
        while not (name := ui.ask("Their name (only you see it)")):
            pass
        meta = {"name": name, "telegram": ui.ask_telegram(TELEGRAM_QUESTION), "on": list(pk.TRIGGERS), "delay": 0,
                "backup": "", "backup_after": 7 * pk.D, "backup_note": ""}
        d = pk.folder_for(root, name)
        d.mkdir(parents=True)
        pk.save_meta(d, meta)
        ui.note(f"✔ Added {name}. Now add what they should receive.")
        return d

    def open_recipient(self, d: Path) -> None:
        actions = [
            ("✍️ Write a message", self.write_message),
            ("📎 Add files: photos, videos, voice messages, documents", self.add_files),
            ("📝 Edit a message", self.edit_message),
            ("🗑 Remove something from the list", self.remove_item),
            ("⚙️ Settings: name, Telegram, when to send, backup person", self.recipient_settings),
            ("📂 Open their folder", lambda d: open_folder(d)),
            ("❌ Delete this recipient", self.delete_recipient),
        ]
        while d.exists():
            meta, files = pk.load_meta(d), pk.package_files(d)
            lines = [f"{BOLD}👤 {meta['name']}{RESET} → {meta['telegram'] or '(Telegram not set)'}",
                     f"Sent {ON_LABELS[tuple(meta['on'])]}"
                     + (f", {pk.dur_str(meta['delay'])} after the trigger" if meta["delay"] else "")]
            if meta["backup"]:
                lines.append(f"Backup person: {meta['backup']}, if it isn't read within {pk.dur_str(meta['backup_after'])}")
            lines += ["", "What they receive, in this order:"]
            lines += [f"  {i}. {item_label(d, p)}" for i, p in enumerate(files, 1)] or ["  (nothing yet)"]
            lines += [f"⚠️ {problem}" for problem in pk.read_package(d)[2]]
            idx = ui.select("What next?", [label for label, _ in actions], header="\n".join(lines))
            if idx is None:
                return
            self.run(lambda action=actions[idx][1]: action(d))

    def write_message(self, d: Path) -> None:
        text = ui.ask_text(f"{BOLD}✍️ Write the message{RESET}")
        if not text:
            ui.note("Nothing written.")
            return
        sub = ui.ask_when()
        dest = d / sub if sub else d
        dest.mkdir(exist_ok=True)
        (dest / f"{pk.next_number(d):02d}-message.txt").write_text(text + "\n")
        ui.note("✔ Message saved.")

    def add_files(self, d: Path) -> None:
        print(f"{BOLD}📎 Add files{RESET}")
        ui.explain("Drag files or folders from your file manager into this window (or paste their paths), then press Enter.\n"
                   ".ogg/.opus files become voice messages; everything else arrives as a file in original quality.")
        chosen = []
        for p in ui.ask_paths("Files"):
            if p.stat().st_size > pk.TG_FILE_LIMIT:
                print(f"  ⚠️ skipped {p.name}: {core.human(p.stat().st_size)} is over Telegram's 2 GB limit")
                continue
            name = p.name
            if name.lower().endswith(".mp4") and not name.lower().endswith(pk.ROUND_SUFFIX):
                if ui.confirm(f"Send {name} as a round video message (a circle; square video up to 60 s)?",
                              yes="Yes, as a circle", no="No, as a normal video"):
                    name = name[:-4] + pk.ROUND_SUFFIX
            chosen.append((p, name))
        if not chosen:
            ui.note("No files added.")
            return
        sub = ui.ask_when()
        dest = d / sub if sub else d
        dest.mkdir(exist_ok=True)
        n = pk.next_number(d)
        for i, (p, name) in enumerate(chosen):
            print(f"  copying {p.name} ({core.human(p.stat().st_size)})")
            shutil.copy2(p, dest / f"{n + i:02d}-{name}")
        ui.note(f"✔ Added {len(chosen)} file(s).")

    def edit_message(self, d: Path) -> None:
        texts = [p for p in pk.package_files(d) if pk.item_kind(p) == "text"]
        if not texts:
            ui.note("There are no messages yet.")
            return
        idx = ui.select("Which message?", [item_label(d, p) for p in texts])
        if idx is not None:
            open_editor(texts[idx])
            ui.note("✔ Saved.")

    def remove_item(self, d: Path) -> None:
        files = pk.package_files(d)
        idx = ui.select("Remove which one?", [item_label(d, p) for p in files])
        if idx is None or not ui.confirm(f"Remove {files[idx].name}?", yes="🗑 Remove"):
            return
        p = files[idx]
        p.unlink()
        parent = p.parent
        while parent != d and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
        ui.note("✔ Removed.")

    def recipient_settings(self, d: Path) -> None:
        meta = pk.load_meta(d)
        print(f"{BOLD}⚙️ Settings{RESET} {DIM}(Enter keeps the value in [brackets]){RESET}\n")
        meta["name"] = ui.ask("Their name (only you see it)", meta["name"])
        meta["telegram"] = ui.ask_telegram(TELEGRAM_QUESTION, meta["telegram"])
        meta["on"] = ui.ask_on("When should this be sent?", meta["on"])
        meta["delay"] = ui.ask_duration("Wait after the trigger before sending? (e.g. 3d, 2w; Enter = no wait)", meta["delay"])
        ui.explain("\nBackup person: if they don't read it in time (or can't be found), the same goes to someone else.")
        meta["backup"] = ui.ask_telegram("Backup person's Telegram (Enter = nobody)", meta["backup"], optional=True)
        if meta["backup"]:
            meta["backup_after"] = ui.ask_duration("How long to wait for them to read it?", meta["backup_after"]) or 7 * pk.D
            meta["backup_note"] = ui.ask("Note sent to the backup person first (Enter = a standard note)",
                                         meta["backup_note"], clearable=True)
        pk.save_meta(d, meta)
        ui.note("✔ Settings saved.")

    def delete_recipient(self, d: Path) -> None:
        name = pk.load_meta(d)["name"]
        if ui.confirm(f"Delete {name} and everything prepared for them?", yes="❌ Delete"):
            shutil.rmtree(d)
            ui.note(f"✔ Deleted {name}.")

    # ----------------------------------------------------------- account actions
    def account(self) -> None:
        root = self.root()
        while True:
            acc = pk.load_account(root)
            lines = [f"{BOLD}👤 Your account after the trigger{RESET} (all optional)",
                     f"Runs {ON_LABELS[tuple(acc['on'])]}",
                     f"Auto-reply to people who write to you: {short(acc['autoreply']) if acc['autoreply'] else 'off'}",
                     f"New profile bio: {short(acc['about']) if acc['about'] else 'unchanged'}",
                     "Posts:" + ("" if acc["posts"] else " none")]
            for i, post in enumerate(acc["posts"], 1):
                later = f", {pk.dur_str(post['delay'])} after the trigger" if post["delay"] else ""
                lines.append(f"  {i}. → {post['chat']}{later}: {short(post['text'], 40)}")
            idx = ui.select("What next?", [
                "💬 Set the auto-reply (once per person; never to your recipients, bots or groups)",
                "🪪 Set the new bio",
                "📣 Add a post to a group, channel or person",
                "🗑 Remove a post",
                "⏱ When to run",
            ], header="\n".join(lines))
            if idx is None:
                return
            try:
                if idx == 0:
                    acc["autoreply"] = ui.ask_text("Auto-reply text (leave empty to turn it off).")
                elif idx == 1:
                    acc["about"] = ui.ask("New bio, up to 70 characters", acc["about"], clearable=True)
                    if len(acc["about"]) > 70:
                        print("⚠️ Over 70 characters: only Telegram Premium allows up to 140.")
                        ui.pause()
                elif idx == 2:
                    chat = ui.ask_telegram("Where to post (@group, @channel or @person; you must be able to write there)")
                    text = ui.ask_text("Post text.")
                    if not text:
                        continue
                    delay = ui.ask_duration("How long after the trigger? (Enter = right away)")
                    acc["posts"].append({"chat": chat, "text": text, "delay": delay})
                elif idx == 3:
                    if not acc["posts"]:
                        continue
                    i = ui.select("Remove which post?", [f"→ {p['chat']}: {short(p['text'], 40)}" for p in acc["posts"]])
                    if i is None:
                        continue
                    acc["posts"].pop(i)
                else:
                    acc["on"] = ui.ask_on("When should this run?", acc["on"])
            except KeyboardInterrupt:
                ui.note("(cancelled)")
                continue
            pk.save_account(root, acc)
            ui.note("✔ Saved.")

    # -------------------------------------------------------------------- server
    def server(self) -> None:
        actions = [
            ("📋 Full status", self.full_status),
            ("⬆️ Update Phoenix on the server (after downloading a new version)", self.update),
            ("🔄 Restart Phoenix", self.restart),
            ("📜 Live server logs (Ctrl+C to stop)", lambda: core.follow_logs(self.cfg)),
            ("💳 Hosting paid until…", self.paid_until),
            ("🔑 Change the bot token or Telegram API keys", lambda: self.step_keys(restart=True) or ui.pause()),
            ("📱 Log in to Telegram again", self.relogin),
            ("🛠 Prepare the server again (updates, firewall)", lambda: core.bootstrap(self.cfg) or ui.pause()),
            ("🚚 Move Phoenix to another server", self.move),
            ("🧹 Remove Phoenix from this server", self.uninstall),
        ]
        while True:
            idx = ui.select("Server", [label for label, _ in actions], header=self.header())
            if idx is None:
                return
            self.run(actions[idx][1])
            self.refresh()

    def full_status(self) -> None:
        print(self.ctl("status"))
        ui.pause()

    def update(self) -> None:
        print("Downloading the latest Phoenix…")
        changed = core.update_code()
        print("Updating the server…")
        running = core.deploy(self.cfg)
        ui.note("✅ Phoenix is up to date." if running else "Code uploaded; finish the setup to start it.")
        if changed:
            raise Restart

    def restart(self) -> None:
        core.restart(self.cfg)
        ui.note("🔄 Restarted. Your bot says “Phoenix restarted”.")

    def relogin(self) -> None:
        self.step_login()
        ui.pause()

    def paid_until(self) -> None:
        ui.explain("Your bot reminds you 30, 14 and 7 days before this date, so the server never stops by accident.")
        raw = ui.ask("Paid until (YYYY-MM-DD)")
        try:
            paid = date.fromisoformat(raw)
        except ValueError:
            raise Failed("use the format 2027-10-01") from None
        ui.note(self.ctl("paiduntil", paid.isoformat()))

    def move(self) -> None:
        if not ui.confirm("Set Phoenix up on a new server? The old server keeps running until you cancel it at your host.",
                          yes="🚚 Yes, set up a new server"):
            return
        self.cfg["setup"] = []
        self.cfg.pop("public_key", None)
        core.save_config(self.cfg)
        if self.setup():
            print("Uploading your packages to the new server…")
            pk.push_from(self.cfg, self.root())
            ui.pause()

    def uninstall(self) -> None:
        if not ui.confirm(f"Remove Phoenix from {self.cfg['server']}? It logs out of your Telegram account and deletes "
                          "the packages, keys and settings on the server. Nothing will be delivered any more.",
                          yes="🧹 Yes, remove it", no="No"):
            return
        if not ui.confirm("Are you sure? This can't be undone.", yes="Yes, I'm sure", no="No"):
            return
        core.uninstall(self.cfg)
        self.cfg["setup"] = []
        self.cfg.pop("public_key", None)
        core.save_config(self.cfg)
        print("\n✅ Removed. Your packages on this computer are kept.\n"
              "Also delete the control bot in @BotFather (/deletebot) if you don't need it any more.")
        ui.pause()
        raise Restart

    # --------------------------------------------------------------------- vault
    def vault(self) -> None:
        while True:
            if core.vault_enabled():
                state = "🔓 open (locks when you quit)" if self._root is not None else "🔒 locked"
                header = (f"{BOLD}🔐 Vault{RESET}: {state}\nYour packages are stored encrypted in {core.VAULT}.\n"
                          "You can back up that folder anywhere: without your password it's useless.")
                options = [("🔒 Lock now", self.lock), ("📂 Open the packages folder", lambda: open_folder(self.root()))]
            else:
                header = (f"{BOLD}🔐 Vault{RESET}: off\n"
                          "Your packages are stored on this computer unencrypted: anyone with access to it can read them.")
                options = [("🔐 Protect them with a password", self.create_vault),
                           ("📂 Open the packages folder", lambda: open_folder(self.root()))]
            idx = ui.select("What next?", [label for label, _ in options], header=header)
            if idx is None:
                return
            self.run(options[idx][1])

    def lock(self) -> None:
        self.close()
        core.lock()
        ui.note("🔒 Locked.")

    def create_vault(self) -> None:
        self.close()
        core.vault_init(self.cfg)
        ui.pause()
