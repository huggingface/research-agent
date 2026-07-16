#!/usr/bin/env python3
"""Inject canonical Birch CSS into generated HTML artifacts.

Usage:
    python3 birch-html/scripts/finish_birch_html.py path/to/artifact.html

The script replaces __BIRCH_SYSTEM_CSS__ or any existing
<style data-birch-system>...</style> block with the bundled canonical stylesheet.
It also removes local Birch stylesheet links so the result is standalone.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

MARKER = "__BIRCH_SYSTEM_CSS__"
STYLE_RE = re.compile(r"<style\b(?=[^>]*\bdata-birch-system\b)[^>]*>.*?</style>", re.I | re.S)
LINK_RE = re.compile(
    r"\s*<link\b(?=[^>]*\brel=[\"']stylesheet[\"'])(?=[^>]*\bhref=[\"'](?:assets/|(?:\.\./\.\./)?styles/)birch-system\.css[\"'])[^>]*>\s*",
    re.I,
)


def default_css_path() -> Path:
    script = Path(__file__).resolve()
    bundled = script.parents[1] / "assets" / "birch-system.css"
    if bundled.exists():
        return bundled
    repo = script.parents[2] / "styles" / "birch-system.css"
    if repo.exists():
        return repo
    raise SystemExit("Could not find Birch CSS beside the skill or at styles/birch-system.css")


def inject(html: str, css: str) -> str:
    html = LINK_RE.sub("\n", html)
    if MARKER in html:
        html = html.replace(MARKER, css.strip())
    elif STYLE_RE.search(html):
        html = STYLE_RE.sub(f"<style data-birch-system>\n{css.strip()}\n</style>", html, count=1)
    else:
        html = re.sub(
            r"</head>",
            f"<style data-birch-system>\n{css.strip()}\n</style>\n</head>",
            html,
            count=1,
            flags=re.I,
        )
    if MARKER in html:
        raise SystemExit(f"Unreplaced {MARKER} marker remains")
    if not re.search(r"<style\b(?=[^>]*\bdata-birch-system\b)", html, flags=re.I):
        raise SystemExit("Missing style[data-birch-system] after injection")
    return html.rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path, help="HTML artifact to finish in place")
    parser.add_argument("--css", type=Path, default=default_css_path(), help="Canonical Birch CSS path")
    args = parser.parse_args()

    html_path = args.html
    css_path = args.css
    html = html_path.read_text(encoding="utf-8")
    css = css_path.read_text(encoding="utf-8")
    html_path.write_text(inject(html, css), encoding="utf-8")
    print(html_path)


if __name__ == "__main__":
    main()
