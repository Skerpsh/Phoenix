"""Terminal widgets: arrow-key menus and simple questions.

Without a terminal (piped input, tests) menus fall back to numbered lists read line by line.
"""

import os
import re
import select as _select
import shlex
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from phoenix import durations

from .packages import TRIGGERS, dur_str

INTERACTIVE = sys.stdin.isatty() and sys.stdout.isatty()
BOLD, DIM, CYAN, RESET = ("\033[1m", "\033[2m", "\033[36m", "\033[0m") if INTERACTIVE else ("",) * 4

ON_LABELS = {
    ("silence", "panic"): "if you stop checking in, or on the panic button",
    ("silence",): "only if you stop checking in",
    ("panic",): "only on the panic button",
}
USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")

_notes: list[str] = []


def note(text: str) -> None:
    """Shown above the next menu (the screen is cleared before it)."""
    _notes.append(text)


def clear() -> None:
    if INTERACTIVE:
        sys.stdout.write("\033[H\033[2J\033[3J")
        sys.stdout.flush()


def pause() -> None:
    try:
        input(f"\n{DIM}Press Enter to continue…{RESET}")
    except EOFError:
        pass


def _read_key(fd: int) -> str:
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        if not _select.select([fd], [], [], 0.05)[0]:
            return "back"  # a lone Esc
        if os.read(fd, 1) not in (b"[", b"O"):
            return ""
        seq = os.read(fd, 1)  # read exactly one sequence, so fast repeats aren't merged
        while seq[-1:].isdigit() or seq[-1:] == b";":
            seq += os.read(fd, 1)
        return {b"A": "up", b"B": "down", b"C": "enter", b"D": "back"}.get(seq[-1:], "")
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b"\x7f":
        return "back"
    return ch.decode(errors="ignore").lower()


def select(title: str, options: list[str], *, header: str = "", back: str | None = "Back", default: int = 0) -> int | None:
    """Arrow-key menu. Returns the chosen index, or None for the back option, Esc or ←."""
    items = [*options, f"← {back}"] if back else list(options)
    notes, _notes[:] = _notes[:], []
    idx = min(default, len(items) - 1)
    if not INTERACTIVE:
        idx = _select_plain(title, items, header, notes, back)
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                out = ["\033[H\033[2J\033[3J\033[?25l"]
                if header:
                    out.append(header.rstrip() + "\n\n")
                out += [n + "\n" for n in notes] + (["\n"] if notes else [])
                out.append(f"{BOLD}{title}{RESET}\n")
                for i, label in enumerate(items):
                    out.append(f" {CYAN}❯ {BOLD}{label}{RESET}\n" if i == idx else f"   {label}\n")
                out.append(f"\n{DIM}↑/↓ move · Enter choose · Esc back{RESET}")
                sys.stdout.write("".join(out))
                sys.stdout.flush()
                key = _read_key(fd)
                if key in ("up", "k"):
                    idx = (idx - 1) % len(items)
                elif key in ("down", "j"):
                    idx = (idx + 1) % len(items)
                elif key == "enter":
                    break
                elif key in ("back", "q") and back:
                    idx = len(items) - 1
                    break
                elif key.isdigit() and 1 <= int(key) <= len(items):
                    idx = int(key) - 1
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            sys.stdout.write("\033[?25h\n")
            clear()
    return None if back and idx == len(items) - 1 else idx


def _select_plain(title: str, items: list[str], header: str, notes: list[str], back: str | None) -> int:
    print("\n" + header if header else "")
    for n in notes:
        print(n)
    print(title)
    for i, label in enumerate(items, 1):
        print(f"  {i}) {label}")
    while True:
        raw = input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            return int(raw) - 1
        if back and raw in ("", "b", "q"):
            return len(items) - 1


def confirm(question: str, *, yes: str = "Yes", no: str = "No", default: bool = False, header: str = "") -> bool:
    options = [yes, no] if default else [no, yes]
    idx = select(question, options, header=header, back=None)
    return options[idx] == yes


def ask(question: str, current: str = "", *, clearable: bool = False) -> str:
    hint = f" [{current}]" if current else ""
    hint += " (- to remove)" if clearable and current else ""
    answer = input(f"{question}{hint}: ").strip()
    if clearable and answer == "-":
        return ""
    return answer or current


def explain(text: str) -> None:
    print(f"{DIM}{text}{RESET}")


def ask_secret(question: str, *, keep: bool = False) -> str:
    import getpass

    return getpass.getpass(f"{question}{' [Enter keeps the current one]' if keep else ''} (hidden): ").strip()


def ask_text(intro: str) -> str:
    print(f"{intro}\n{DIM}Type or paste the text. To finish, press Enter on two empty lines in a row.{RESET}")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def ask_duration(question: str, current: int = 0, *, required: bool = False) -> int:
    while True:
        raw = ask(question, dur_str(current) if current else "", clearable=not required)
        if raw in ("", "0") and not required:
            return 0
        try:
            return durations.parse(raw)
        except ValueError:
            print("  Use a number and a unit: 30m (minutes), 12h (hours), 3d (days), 2w (weeks), 1y (years).")


def normalize_telegram(raw: str) -> str | None:
    t = re.sub(r"^(https?://)?(t\.me|telegram\.me)/", "", raw.strip()).removeprefix("@").strip("/")
    if USERNAME_RE.fullmatch(t):
        return "@" + t
    phone = re.sub(r"[\s()-]", "", raw)
    if re.fullmatch(r"\+\d{7,15}", phone):
        return phone
    return raw.strip() if raw.strip().isdigit() else None


def ask_telegram(question: str, current: str = "", *, optional: bool = False) -> str:
    while True:
        raw = ask(question, current, clearable=optional)
        if not raw:
            if optional:
                return ""
            continue
        ref = normalize_telegram(raw)
        if ref is None:
            print("  That doesn't look like a Telegram account. Examples: @alice, alice, t.me/alice, +380501234567")
            continue
        if ref.startswith("@"):
            print(f"  ↳ make sure it's the right person: https://t.me/{ref[1:]}")
        elif ref.startswith("+"):
            print("  ↳ this number must be saved in your Telegram contacts")
        return ref


def ask_on(question: str, current: list[str]) -> list[str]:
    options = list(ON_LABELS)
    idx = select(question, [ON_LABELS[o] for o in options], back=None, default=options.index(tuple(current)))
    return [t for t in TRIGGERS if t in options[idx]]


def ask_when() -> str:
    """The folder that schedules an item ('' = together with the rest of the package)."""
    c = select("When should it be sent?", [
        "Together with the rest",
        "Some time later (for example, a year later)",
        "On a specific date (for example, a birthday)",
    ], back=None)
    while c == 1:
        raw = ask("How long after the rest? (e.g. 30d, 26w, 1y, 2y)")
        try:
            return f"@+{dur_str(durations.parse(raw))}"
        except ValueError:
            print("  Use a number and a unit: d (days), w (weeks), y (years). For example 1y.")
    while c == 2:
        raw = ask("Date as YYYY-MM-DD, optionally with a time: YYYY-MM-DD HH:MM (default 09:00)")
        try:
            when = datetime.fromisoformat(raw.replace(" ", "T"))
        except ValueError:
            print("  For example: 2034-05-12 or 2034-05-12 18:30")
            continue
        if (when if ":" in raw else when.replace(hour=9)) <= datetime.now():
            print("  That date has already passed.")
            continue
        return "@" + (when.isoformat(timespec="minutes") if ":" in raw else when.date().isoformat())
    return ""


def ask_paths(question: str) -> list[Path]:
    """Paths typed, pasted or drag-and-dropped into the terminal (folders are expanded)."""
    raw = ask(question)
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    paths = []
    for part in parts:
        p = Path(unquote(part.removeprefix("file://"))).expanduser()
        if p.is_dir():
            paths += sorted(f for f in p.rglob("*") if f.is_file())
        elif p.is_file():
            paths.append(p)
        else:
            print(f"  ⚠️ not found: {p}")
    return paths
