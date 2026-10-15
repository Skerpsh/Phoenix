"""Terminal widgets: arrow-key menus, simple questions, the splash and farewell screens.

Without a terminal (piped input, tests) menus fall back to numbered lists read line by line.
"""

import os
import re
import select as _select
import shlex
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from phoenix import durations

from . import art
from .packages import TRIGGERS, dur_str

INTERACTIVE = sys.stdin.isatty() and sys.stdout.isatty()
COLOR = INTERACTIVE and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"


def fg(code: int) -> str:
    return f"\033[38;5;{code}m" if COLOR else ""


BOLD, DIM, RESET = ("\033[1m", "\033[2m", "\033[0m") if COLOR else ("",) * 3
FLAME, GREEN, YELLOW, RED = fg(208), fg(71), fg(220), fg(196)

# Smallest terminal everything is designed for: the splash (logo + wordmark) needs 23 rows; menus scroll.
MIN_COLS, MIN_ROWS = 80, 24

ON_LABELS = {
    ("silence", "panic"): "if you stop checking in, or on the panic button",
    ("silence",): "only if you stop checking in",
    ("panic",): "only on the panic button",
}
USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")
_ANSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")

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


# ------------------------------------------------------------------ text measuring
def _char_cells(ch: str, previous: int) -> int:
    if ch == "\ufe0f":  # emoji presentation: the previous symbol becomes two cells wide
        return 1 if previous == 1 else 0
    if unicodedata.combining(ch) or ch in "\u200d\ufe0e":
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def cells(text: str) -> int:
    """How many terminal columns `text` takes (colors ignored, wide emoji count as two)."""
    total, last = 0, 1
    for ch in _ANSI.sub("", text):
        last = _char_cells(ch, last)
        total += last
    return total


def fit(text: str, width: int) -> str:
    """Cut `text` to `width` columns, keeping colors intact and ending with … if cut."""
    if cells(text) <= width:
        return text
    out, used, last, pos = [], 0, 1, 0
    while pos < len(text):
        m = _ANSI.match(text, pos)
        if m:
            out.append(m.group())
            pos = m.end()
            continue
        w = _char_cells(text[pos], last)
        if used + w > width - 1:
            break
        out.append(text[pos])
        used, last, pos = used + w, w, pos + 1
    return "".join(out) + "…" + RESET


def wrap(text: str, width: int) -> list[str]:
    """Wrap a line by words to `width` columns; colors carry over to the continuation lines."""
    if cells(text) <= width:
        return [text]
    lines, line, active = [], "", ""
    for word in text.split(" "):
        candidate = f"{line} {word}" if line else word
        if line and cells(candidate) > width:
            lines.append(line + (RESET if active else ""))
            candidate = active + word
        line = candidate
        for code in _ANSI.findall(word):
            active = "" if code == RESET else active + code
    lines.append(line)
    return [fit(x, width) for x in lines]


def term_size() -> tuple[int, int]:
    size = shutil.get_terminal_size((MIN_COLS, MIN_ROWS))
    return size.columns, size.lines


def paint(rows: list[str], colors: list[int] = art.FIRE) -> list[str]:
    """Color rows top to bottom with a gradient."""
    if not COLOR:
        return list(rows)
    return [f"{fg(colors[min(len(colors) - 1, i * len(colors) // max(1, len(rows)))])}{r}{RESET}"
            for i, r in enumerate(rows)]


# ----------------------------------------------------------------------- keyboard
class _Keys:
    """Raw single-key input while a screen is shown; restores the terminal afterwards."""

    def __enter__(self):
        import termios
        import tty

        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\033[?25l")
        return self

    def __exit__(self, *exc):
        import termios

        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def read(self, timeout: float | None = None) -> str | None:
        """The next key, or None if nothing was pressed within `timeout` seconds."""
        if timeout is not None and not _select.select([self.fd], [], [], timeout)[0]:
            return None
        return _read_key(self.fd)


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
        return {b"A": "up", b"B": "down", b"C": "enter", b"D": "back", b"H": "home", b"F": "end",
                b"5~": "pgup", b"6~": "pgdn"}.get(seq[-1:] if not seq.endswith(b"~") else seq, "")
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b"\x7f":
        return "back"
    return ch.decode(errors="ignore").lower()


# ------------------------------------------------------------------- whole screens
def _draw(lines: list[str], *, top: int = 0) -> None:
    sys.stdout.write("\033[H\033[2J\033[3J" + "\n" * top + "\n".join(lines))
    sys.stdout.flush()


def _centered(blocks: list[list[str]], cols: int, rows: int) -> tuple[list[str], int]:
    """Center blocks of (colored) lines horizontally; return them and the top padding."""
    lines: list[str] = []
    for block in blocks:
        width = max((cells(line) for line in block), default=0)
        pad = " " * max(0, (cols - width) // 2)
        lines += [pad + line for line in block] + [""]
    lines = lines[:-1]
    return lines, max(0, (rows - len(lines)) // 2)


def too_small() -> bool:
    cols, rows = term_size()
    return cols < MIN_COLS or rows < MIN_ROWS


def _size_warning(cols: int, rows: int) -> None:
    def value(now: int, need: int) -> str:
        return f"{GREEN if now >= need else RED}{now}{RESET}"

    lines, top = _centered([[
        f"{BOLD}Terminal size too small:{RESET}",
        f" Width = {value(cols, MIN_COLS)} Height = {value(rows, MIN_ROWS)}",
        "",
        f"{BOLD}Needed for Phoenix:{RESET}",
        f" Width = {MIN_COLS} Height = {MIN_ROWS}",
        "",
        f"{DIM}Make the window bigger (or the font smaller) · q quits{RESET}",
    ]], cols, rows)
    _draw(lines, top=top)


def wait_for_size(keys: _Keys) -> bool:
    """Like btop: while the terminal is too small, show its size live. False if the user quits."""
    shown = None
    while too_small():
        if term_size() != shown:
            shown = term_size()
            _size_warning(*shown)
        if keys.read(0.2) in ("q", "back"):
            return False
    return True


def ensure_size() -> bool:
    if not INTERACTIVE or not too_small():
        return True
    with _Keys() as keys:
        ok = wait_for_size(keys)
    clear()
    return ok


def splash(seconds: float = 2.0) -> None:
    """The logo and the wordmark in the middle of the screen; the flame rises, then holds. Any key skips."""
    if not INTERACTIVE or too_small():
        return
    logo, word = paint(art.LOGO), paint(art.WORDMARK, [208, 202, 196, 160])
    cols, rows = term_size()
    with _Keys() as keys:
        lines, top = _centered([logo, word], cols, rows)
        n = len(logo)
        for shown in range(1, n + 1):  # reveal from the tail up, like a flame
            frame = [line if i >= n - shown or i > n else "" for i, line in enumerate(lines)]
            _draw(frame, top=top)
            if keys.read(0.6 / n) is not None:
                break
        else:
            _draw(lines, top=top)
            keys.read(seconds)
    clear()


def farewell(message: str, seconds: float = 2.0) -> None:
    """The logo once more on the way out, for a moment (any key skips); then the terminal is wiped clean."""
    if not INTERACTIVE:
        print(message)
        return
    cols, rows = term_size()
    text = [f"{BOLD}{FLAME}{line}{RESET}" if i == 0 else f"{DIM}{line}{RESET}"
            for i, line in enumerate(message.splitlines())]
    with _Keys() as keys:
        if too_small():
            _draw(text)
        else:
            lines, top = _centered([paint(art.LOGO), text], cols, rows)
            _draw(lines, top=top)
        keys.read(seconds)
    sys.stdout.write("\033[H\033[2J\033[3J")  # screen and scrollback
    sys.stdout.flush()


# --------------------------------------------------------------------------- menus
def select(title: str, options: list[str], *, header: str = "", back: str | None = "Back", default: int = 0) -> int | None:
    """Arrow-key menu. Returns the chosen index, or None for the back option, Esc or ←.

    Long lists scroll, long lines are cut to the window, and resizing the window redraws it.
    """
    items = [*options, f"← {back}"] if back else list(options)
    notes, _notes[:] = _notes[:], []
    idx = min(default, len(items) - 1)
    if not INTERACTIVE:
        idx = _select_plain(title, items, header, notes, back)
        return None if back and idx == len(items) - 1 else idx

    head = (header.rstrip().splitlines() + [""] if header else []) + notes + ([""] if notes else [])
    titles = title.splitlines() or [""]
    scroll, size = 0, None
    try:
        with _Keys() as keys:
            while True:
                if too_small() and not wait_for_size(keys):
                    raise KeyboardInterrupt
                cols, rows = size = term_size()
                title_lines = [w for t in titles for w in wrap(t, cols)]
                wrapped = [w for line in head for w in (wrap(line, cols) if line else [""])]
                room = rows - len(title_lines) - 2  # the hint line and the blank line before it
                top = wrapped[: max(0, room - min(len(items), 5))]  # keep at least five items visible
                visible = max(1, room - len(top))
                scroll = min(max(scroll, idx - visible + 1), idx)
                scroll = max(0, min(scroll, len(items) - visible))
                out = top
                out += [f"{BOLD}{t}{RESET}" for t in title_lines]
                for i in range(scroll, min(len(items), scroll + visible)):
                    more = "↑" if i == scroll and scroll > 0 else "↓" if i == scroll + visible - 1 < len(items) - 1 else " "
                    if i == idx:
                        out.append(fit(f"{FLAME}❯{RESET} {FLAME}{BOLD}{items[i]}{RESET}", cols - 2) + f" {DIM}{more}{RESET}")
                    else:
                        out.append(fit(f"  {items[i]}", cols - 2) + f" {DIM}{more}{RESET}")
                out += ["", fit(f"{DIM}↑/↓ move · Enter choose · Esc back{RESET}", cols)]
                _draw(out)
                key = keys.read(0.25)
                while key is None:  # nothing pressed: redraw only if the window changed
                    if term_size() != size:
                        break
                    key = keys.read(0.25)
                if key is None:
                    continue
                if key in ("up", "k"):
                    idx = (idx - 1) % len(items)
                elif key in ("down", "j"):
                    idx = (idx + 1) % len(items)
                elif key in ("home", "pgup"):
                    idx = 0
                elif key in ("end", "pgdn"):
                    idx = len(items) - 1
                elif key == "enter":
                    break
                elif key in ("back", "q") and back:
                    idx = len(items) - 1
                    break
                elif key.isdigit() and 1 <= int(key) <= min(9, len(items)):
                    idx = int(key) - 1
                    break
    finally:
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

    if not INTERACTIVE:  # piped input (scripts, tests): read it like any other answer
        return input(f"{question}: ").strip()
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
