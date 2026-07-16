#!/usr/bin/env python3
"""Render the real Prefab app with static state and optionally screenshot it."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from design.preview_states import TOPIC, preview_snapshot  # noqa: E402
from research.app_ui import build_research_ui  # noqa: E402

DEFAULT_OUTPUT = ROOT / ".artifacts" / "app-preview"
STATES = ("running", "completed", "failed", "cancelled")


def render_state(
    state: str,
    *,
    output_dir: Path,
    screenshot: bool,
    width: int,
    height: int,
    mode: str | None = None,
) -> tuple[Path, Path | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    app = build_research_ui(TOPIC, preview_snapshot(state), live=False)
    app.mode = mode
    suffix = f"-{mode}" if mode else ""
    html_path = output_dir / f"{state}{suffix}.html"
    html_path.write_text(app.html(renderer_mode="bundled", pretty=True))

    png_path = output_dir / f"{state}{suffix}.png"
    if not screenshot:
        return html_path, None

    chrome = _find_chrome()
    if chrome is None:
        raise RuntimeError("Chrome/Chromium was not found; use --no-screenshot")

    with tempfile.TemporaryDirectory(prefix="research-app-preview-") as profile:
        subprocess.run(
            [
                chrome,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                "--hide-scrollbars",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=1500",
                f"--user-data-dir={profile}",
                f"--window-size={width},{height}",
                f"--screenshot={png_path}",
                html_path.resolve().as_uri(),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    return html_path, png_path


def _find_chrome() -> str | None:
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        if path := shutil.which(name):
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=(*STATES, "all"), default="running")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-screenshot", action="store_true")
    parser.add_argument("--width", type=int, default=1000)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--mode", choices=("light", "dark"))
    args = parser.parse_args()

    states = STATES if args.state == "all" else (args.state,)
    for state in states:
        html_path, png_path = render_state(
            state,
            output_dir=args.output_dir,
            screenshot=not args.no_screenshot,
            width=args.width,
            height=args.height,
            mode=args.mode,
        )
        print(f"{state}: {html_path}")
        if png_path is not None:
            print(f"{state}: {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
