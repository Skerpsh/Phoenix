#!/usr/bin/env python3
"""Draw the terminal logo (cli/phx/art.py) as SVG images for the README: every braille dot becomes a circle.

    python3 scripts/logo_svg.py      # writes docs/assets/logo-dark.svg and logo-light.svg
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))
from phx.art import LOGO  # noqa: E402

CELL_W, CELL_H = 8, 16  # a terminal character is about twice as tall as it is wide
DOT_R = 1.6
# braille dot bits → (column, row) inside a character
DOTS = [(0x01, 0, 0), (0x02, 0, 1), (0x04, 0, 2), (0x40, 0, 3), (0x08, 1, 0), (0x10, 1, 1), (0x20, 1, 2), (0x80, 1, 3)]
THEMES = {
    "dark": ["#ffe14d", "#ffb000", "#ff7a00", "#f03a00", "#c40000"],   # bright, like the terminal
    "light": ["#f0a800", "#f07800", "#e04800", "#c41a00", "#8f0000"],  # deeper, readable on white
}


def svg(colors: list[str]) -> str:
    width, height = max(map(len, LOGO)) * CELL_W, len(LOGO) * CELL_H
    stops = "".join(f'<stop offset="{i / (len(colors) - 1):.2f}" stop-color="{c}"/>' for i, c in enumerate(colors))
    circles = []
    for row, line in enumerate(LOGO):
        for col, ch in enumerate(line):
            code = ord(ch) - 0x2800
            if not 0 < code < 256:
                continue
            for bit, dx, dy in DOTS:
                if code & bit:
                    x = col * CELL_W + CELL_W / 4 + dx * CELL_W / 2
                    y = row * CELL_H + CELL_H / 8 + dy * CELL_H / 4
                    circles.append(f'<circle cx="{x:g}" cy="{y:g}" r="{DOT_R}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="Phoenix logo">'
        f'<defs><linearGradient id="fire" x1="0" y1="0" x2="0" y2="{height}" gradientUnits="userSpaceOnUse">{stops}'
        f'</linearGradient></defs><g fill="url(#fire)">{"".join(circles)}</g></svg>\n'
    )


if __name__ == "__main__":
    out = ROOT / "docs" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    for theme, colors in THEMES.items():
        (out / f"logo-{theme}.svg").write_text(svg(colors))
        print(f"wrote docs/assets/logo-{theme}.svg")
