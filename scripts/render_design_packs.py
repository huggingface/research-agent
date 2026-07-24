#!/usr/bin/env python3
"""Render compact light/dark Prefab review packs for each design option."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.hf_design import HF_DESIGNS, HFDesign  # noqa: E402
from scripts.render_app_preview import render_state  # noqa: E402

DEFAULT_OUTPUT = ROOT / ".artifacts" / "prefabtest-packs"
DESIGN_NAMES = {
    "hub-classic": "Hub Classic",
    "spaces-gradient": "Spaces Gradient",
    "dataset-studio": "Dataset Studio",
}
DESIGN_NOTES = {
    "hub-classic": (
        "Neutral Hub surfaces, amber accents, compact bordered cards, and the "
        "closest fit to model, dataset, and profile pages."
    ),
    "spaces-gradient": (
        "A more expressive option based on featured Spaces cards, with a "
        "colorful active-work panel and stronger visual hierarchy."
    ),
    "dataset-studio": (
        "A dense workspace inspired by dataset browsing, using structured "
        "panels, compact metadata, and blue task accents."
    ),
}
VIEWPORTS = {
    "desktop": (1000, 900, ("running", "completed", "failed", "cancelled")),
    "embedded": (680, 900, ("running", "completed")),
    "mobile": (430, 900, ("running", "completed")),
}


def build_pack(design: HFDesign, output_root: Path) -> Path:
    pack = output_root / design
    shutil.rmtree(pack, ignore_errors=True)
    images: list[dict[str, str | int]] = []
    for mode in ("light", "dark"):
        for viewport, (width, height, states) in VIEWPORTS.items():
            output_dir = pack / mode / viewport
            for state in states:
                html_path, png_path = render_state(
                    state,
                    output_dir=output_dir,
                    screenshot=True,
                    width=width,
                    height=height,
                    mode=mode,
                    design=design,
                )
                html_path.unlink()
                if png_path is None:
                    raise RuntimeError(f"Screenshot was not created: {state}")
                images.append(
                    {
                        "mode": mode,
                        "viewport": viewport,
                        "state": state,
                        "width": width,
                        "height": height,
                        "path": png_path.relative_to(pack).as_posix(),
                    }
                )

    manifest = {
        "schema_version": 1,
        "design": design,
        "name": DESIGN_NAMES[design],
        "description": DESIGN_NOTES[design],
        "images": images,
    }
    (pack / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (pack / "index.html").write_text(_pack_index(manifest))
    return pack


def _pack_index(manifest: dict[str, object]) -> str:
    cards = []
    for item in manifest["images"]:  # type: ignore[index]
        image = item  # type: ignore[assignment]
        label = f"{image['mode']} · {image['viewport']} · {image['state']}"
        cards.append(
            "<figure>"
            f"<a href=\"{html.escape(str(image['path']))}\">"
            f"<img src=\"{html.escape(str(image['path']))}\" "
            f"alt=\"{html.escape(label)}\"></a>"
            f"<figcaption>{html.escape(label)}</figcaption>"
            "</figure>"
        )
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(str(manifest["name"]))} · Prefab review pack</title>
<style>
  :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
  body {{ max-width: 1500px; margin: auto; padding: 32px; background: #f3f4f6; color: #111827; }}
  h1 {{ margin-bottom: 6px; }}
  p {{ max-width: 70ch; color: #6b7280; }}
  main {{ display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 24px; margin-top: 28px; }}
  figure {{ margin: 0; padding: 12px; border: 1px solid #d1d5db; border-radius: 14px; background: white; }}
  img {{ display: block; width: 100%; height: auto; border-radius: 8px; }}
  figcaption {{ margin-top: 10px; font: 600 12px ui-monospace,monospace; color: #6b7280; text-transform: uppercase; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0b0f19; color: #e5e7eb; }}
    p, figcaption {{ color: #9ca3af; }}
    figure {{ border-color: #263044; background: #101623; }}
  }}
  @media (max-width: 760px) {{ main {{ grid-template-columns: 1fr; }} body {{ padding: 18px; }} }}
</style>
<h1>{html.escape(str(manifest["name"]))}</h1>
<p>{html.escape(str(manifest["description"]))}</p>
<main>{"".join(cards)}</main>
</html>
"""


def _root_index(output_root: Path, designs: tuple[HFDesign, ...]) -> None:
    links = "\n".join(
        f'<li><a href="{design}/index.html">{html.escape(DESIGN_NAMES[design])}</a>'
        f"<p>{html.escape(DESIGN_NOTES[design])}</p></li>"
        for design in designs
    )
    (output_root / "index.html").write_text(
        f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Researcher · Prefab design options</title>
<style>
  :root {{ color-scheme: light dark; font-family: system-ui,sans-serif; }}
  body {{ max-width: 800px; margin: 60px auto; padding: 24px; }}
  li {{ margin: 28px 0; }}
  a {{ color: #d97706; font-size: 24px; font-weight: 700; }}
  p {{ color: #6b7280; }}
</style>
<h1>Researcher design options</h1>
<p>Each pack contains matching light and dark Prefab renders.</p>
<ol>{links}</ol>
</html>
"""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("designs", nargs="*", choices=HF_DESIGNS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    designs: tuple[HFDesign, ...] = tuple(args.designs or HF_DESIGNS)  # type: ignore[assignment]
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    for design in designs:
        pack = build_pack(design, output_root)
        print(f"Built {pack}")
    _root_index(output_root, designs)
    print(f"Review {output_root / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
