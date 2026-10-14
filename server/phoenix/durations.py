import re

_UNITS = {"y": 365 * 86400, "w": 604800, "d": 86400, "h": 3600, "m": 60}
_PART = re.compile(r"(\d+)([ywdhm])")


def parse(text: str) -> int:
    """Parse '7d', '12h', '1d12h', '30m', '2w', '1y' into seconds."""
    t = text.strip().lower().replace(" ", "")
    if not re.fullmatch(r"(?:\d+[ywdhm])+", t):
        raise ValueError(f"Bad duration {text!r}. Examples: 7d, 12h, 1d12h, 30m, 2w, 1y")
    return sum(int(n) * _UNITS[u] for n, u in _PART.findall(t))


def fmt(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return "<1m"
    parts = []
    for unit in "ydhm":
        q, s = divmod(s, _UNITS[unit])
        if q:
            parts.append(f"{q}{unit}")
    return " ".join(parts[:2])
