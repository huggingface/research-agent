#!/usr/bin/env python3
"""Check Birch HTML artifacts for contract and visual smoke failures.

This is a project-local checker, inspired by the neighboring Birchline tooling
but intentionally simpler and deterministic-first:

- static HTML/CSS contract checks,
- optional original-vs-candidate structure/text/component deltas,
- optional Chrome screenshots,
- optional Pillow-based screenshot distance/palette metrics.

Generated eval artifacts normally run in candidate-only ``--artifact`` mode.
That mode does not self-compare screenshots; it captures rendered evidence and
flags egregious visible breakage that static parsing cannot see. True
``--pair`` mode remains available when a meaningful reference exists.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_CSS = ROOT / "styles" / "birch-system.css"
BIRCH_STYLE_RE = re.compile(r"<style\b(?=[^>]*\bdata-birch-system\b)[^>]*>.*?</style>", re.I | re.S)

DEFAULT_PAIRS = (
    ("05-design-system.html", "05-design-system-birch.html"),
    ("06-component-variants.html", "06-component-variants-birch.html"),
)

BIRCH_CLASSES = {
    "page",
    "section",
    "stack",
    "cluster",
    "grid",
    "auto-grid",
    "split",
    "sidebar-layout",
    "panel",
    "card",
    "toolbar",
    "chip",
    "badge",
    "button",
    "btn",
    "input",
    "avatar",
    "code-block",
    "diff",
    "diff-row",
    "timeline",
    "timeline-item",
    "flow-node",
    "flow-edge",
}

LAYOUT_CLASSES = {
    "page",
    "section",
    "stack",
    "cluster",
    "grid",
    "auto-grid",
    "split",
    "sidebar-layout",
    "panel",
    "scroll-x",
    "sticky",
}

SEMANTIC_CLASSES = {
    "card",
    "chip",
    "badge",
    "button",
    "btn",
    "input",
    "avatar",
    "toolbar",
    "diff",
    "diff-row",
    "timeline",
    "timeline-item",
    "flow-node",
    "flow-edge",
}

PALETTE = {
    "ivory": (250, 249, 245),
    "slate": (20, 20, 19),
    "clay": (217, 119, 87),
    "oat": (227, 218, 204),
    "olive": (120, 140, 93),
    "rust": (176, 74, 63),
    "sky": (106, 140, 175),
    "white": (255, 255, 255),
    "gray100": (240, 238, 230),
    "gray300": (209, 207, 197),
    "gray500": (135, 134, 127),
    "gray700": (61, 61, 58),
}


@dataclass
class Finding:
    level: str
    name: str
    evidence: str


@dataclass
class PageStats:
    path: str
    bytes: int
    title: str
    doctype: bool
    viewport: bool
    stylesheet_links: list[str]
    birch_css_embedded: bool
    style_blocks: int
    style_bytes: int
    script_blocks: int
    tag_counts: dict[str, int]
    class_counts: dict[str, int]
    data_attrs: dict[str, int]
    text_words: int
    unique_words: int
    css_vars_used: list[str]
    css_vars_defined: list[str]
    hex_colors: list[str]


class StatsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.in_title = False
        self.skip_depth = 0
        self.text: list[str] = []
        self.tags: Counter[str] = Counter()
        self.classes: Counter[str] = Counter()
        self.data_attrs: Counter[str] = Counter()
        self.links: list[str] = []
        self.inline_styles: list[str] = []
        self.scripts = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        self.tags[tag] += 1
        if tag == "title":
            self.in_title = True
        if tag in {"style", "script"}:
            self.skip_depth += 1
        if tag == "script":
            self.scripts += 1
        if tag == "link" and attrs_dict.get("rel", "").lower() == "stylesheet":
            self.links.append(attrs_dict.get("href", ""))
        if "style" in attrs_dict:
            self.inline_styles.append(attrs_dict["style"])
        if "class" in attrs_dict:
            for cls in attrs_dict["class"].split():
                self.classes[cls] += 1
        for key in attrs_dict:
            if key.startswith("data-"):
                self.data_attrs[key] += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if tag in {"style", "script"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        elif self.skip_depth == 0:
            self.text.append(data)


class GridListParser(HTMLParser):
    """Find list items that will become accidental extra grid children."""

    GRID_LIST_CLASSES = {"insight-list", "takeaway-list"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.list_stack: list[bool] = []
        self.li_stack: list[dict[str, object]] = []
        self.bad_items: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        if tag in {"ul", "ol"}:
            classes = set(attrs_dict.get("class", "").split())
            self.list_stack.append(bool(classes & self.GRID_LIST_CLASSES))
        elif tag == "li" and self.list_stack and self.list_stack[-1]:
            self.li_stack.append({"depth": 0, "chunks": 0, "preview": ""})
        elif self.li_stack:
            self.li_stack[-1]["depth"] = int(self.li_stack[-1]["depth"]) + 1
            if int(self.li_stack[-1]["depth"]) == 1:
                self.li_stack[-1]["chunks"] = int(self.li_stack[-1]["chunks"]) + 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"ul", "ol"} and self.list_stack:
            self.list_stack.pop()
        elif tag == "li" and self.li_stack:
            item = self.li_stack.pop()
            if int(item["chunks"]) > 1:
                self.bad_items.append(str(item["preview"]).strip()[:90])
        elif self.li_stack and int(self.li_stack[-1]["depth"]) > 0:
            self.li_stack[-1]["depth"] = int(self.li_stack[-1]["depth"]) - 1

    def handle_data(self, data: str) -> None:
        if not self.li_stack or not data.strip():
            return
        item = self.li_stack[-1]
        if int(item["depth"]) == 0:
            item["chunks"] = int(item["chunks"]) + 1
        if len(str(item["preview"])) < 120:
            item["preview"] = f"{item['preview']} {data.strip()}".strip()



class ChecklistParser(HTMLParser):
    """Detect checklist items whose inline markup can become accidental layout columns."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.list_stack: list[bool] = []
        self.li_stack: list[dict[str, object]] = []
        self.bad_items: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        if tag in {"ul", "ol"}:
            classes = set(attrs_dict.get("class", "").split())
            self.list_stack.append("checklist" in classes)
        elif tag == "li" and self.list_stack and self.list_stack[-1]:
            self.li_stack.append({"direct_elements": 0, "preview": ""})
        elif self.li_stack:
            self.li_stack[-1]["direct_elements"] = int(self.li_stack[-1]["direct_elements"]) + 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"ul", "ol"} and self.list_stack:
            self.list_stack.pop()
        elif tag == "li" and self.li_stack:
            item = self.li_stack.pop()
            if int(item["direct_elements"]) > 1:
                self.bad_items.append(str(item["preview"]).strip()[:90])

    def handle_data(self, data: str) -> None:
        if self.li_stack and len(str(self.li_stack[-1]["preview"])) < 120:
            self.li_stack[-1]["preview"] = str(self.li_stack[-1]["preview"]) + data

class MetricRowParser(HTMLParser):
    """Validate the Birch metric-row child contract."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_metric_row = False
        self.depth = 0
        self.children: list[tuple[str, set[str]]] = []
        self.preview = ""
        self.bad_rows: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        classes = set(attrs_dict.get("class", "").split())
        if "metric-row" in classes:
            self.in_metric_row = True
            self.depth = 0
            self.children = []
            self.preview = ""
            return
        if not self.in_metric_row:
            return
        self.depth += 1
        if self.depth == 1:
            self.children.append((tag.lower(), classes))

    def handle_endtag(self, tag: str) -> None:
        if not self.in_metric_row:
            return
        if tag.lower() == "div" and self.depth == 0:
            tags = [tag for tag, _classes in self.children]
            classes = [classes for _tag, classes in self.children]
            valid = (
                len(self.children) == 3
                and "caption" in classes[0]
                and "meter" in classes[1]
                and tags[2] == "code"
            )
            if not valid:
                self.bad_rows.append(self.preview.strip()[:90])
            self.in_metric_row = False
            return
        if self.depth > 0:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_metric_row and data.strip() and len(self.preview) < 120:
            self.preview = f"{self.preview} {data.strip()}".strip()


class DiffRowParser(HTMLParser):
    """Validate the Birch diff-row child contract.

    .diff-row is a three-column grid. Loose text becomes an anonymous grid item
    in the narrow line-number column, which renders as the "one word/character
    per line" underfilled block this checker is meant to catch.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_diff_row = False
        self.row_tag = ""
        self.depth = 0
        self.children: list[tuple[str, set[str]]] = []
        self.preview = ""
        self.bad_rows: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        classes = set(attrs_dict.get("class", "").split())
        if "diff-row" in classes:
            self.in_diff_row = True
            self.row_tag = tag.lower()
            self.depth = 0
            self.children = []
            self.preview = ""
            return
        if not self.in_diff_row:
            return
        self.depth += 1
        if self.depth == 1:
            self.children.append((tag.lower(), classes))

    def handle_endtag(self, tag: str) -> None:
        if not self.in_diff_row:
            return
        if tag.lower() == self.row_tag and self.depth == 0:
            classes = [classes for _tag, classes in self.children]
            valid = (
                len(self.children) == 3
                and "ln" in classes[0]
                and "mark" in classes[1]
                and "code" in classes[2]
            )
            if not valid:
                self.bad_rows.append(self.preview.strip()[:90])
            self.in_diff_row = False
            return
        if self.depth > 0:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_diff_row and data.strip() and len(self.preview) < 120:
            self.preview = f"{self.preview} {data.strip()}".strip()


class DiffPolarityParser(HTMLParser):
    """Find added/deleted diff rows that omit their visual polarity metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_diff_row = False
        self.row_tag = ""
        self.depth = 0
        self.row_classes: set[str] = set()
        self.row_kind = ""
        self.in_mark = False
        self.mark = ""
        self.preview = ""
        self.bad_rows: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        classes = set(attrs_dict.get("class", "").split())
        if "diff-row" in classes:
            self.in_diff_row = True
            self.row_tag = tag.lower()
            self.depth = 0
            self.row_classes = classes
            self.row_kind = attrs_dict.get("data-kind", "").lower()
            self.in_mark = False
            self.mark = ""
            self.preview = ""
            return
        if not self.in_diff_row:
            return
        self.depth += 1
        if self.depth == 1 and "mark" in classes:
            self.in_mark = True

    def handle_endtag(self, tag: str) -> None:
        if not self.in_diff_row:
            return
        if self.in_mark and self.depth == 1:
            self.in_mark = False
        if tag.lower() == self.row_tag and self.depth == 0:
            mark = self.mark.strip()
            expected = "add" if mark == "+" else "del" if mark == "-" else ""
            if expected and expected not in self.row_classes and self.row_kind != expected:
                self.bad_rows.append(f"{mark} {self.preview.strip()[:80]}".strip())
            self.in_diff_row = False
            return
        if self.depth > 0:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.in_diff_row:
            return
        if self.in_mark:
            self.mark += data
        elif data.strip() and len(self.preview) < 120:
            self.preview = f"{self.preview} {data.strip()}".strip()


class FlowStepParser(HTMLParser):
    """Validate the Birch flow-step child contract.

    .flow-step is a two-column grid. Content must be wrapped in one direct child
    after .flow-num; otherwise prose can be auto-placed into the narrow number
    column and wrap as one or two characters per line.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_flow_step = False
        self.step_tag = ""
        self.depth = 0
        self.children: list[tuple[str, set[str]]] = []
        self.preview = ""
        self.bad_steps: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        classes = set(attrs_dict.get("class", "").split())
        if "flow-step" in classes:
            self.in_flow_step = True
            self.step_tag = tag.lower()
            self.depth = 0
            self.children = []
            self.preview = ""
            return
        if not self.in_flow_step:
            return
        self.depth += 1
        if self.depth == 1:
            self.children.append((tag.lower(), classes))

    def handle_endtag(self, tag: str) -> None:
        if not self.in_flow_step:
            return
        if tag.lower() == self.step_tag and self.depth == 0:
            valid = (
                len(self.children) == 2
                and "flow-num" in self.children[0][1]
                and "flow-num" not in self.children[1][1]
            )
            if not valid:
                self.bad_steps.append(self.preview.strip()[:90])
            self.in_flow_step = False
            return
        if self.depth > 0:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_flow_step and data.strip() and len(self.preview) < 120:
            self.preview = f"{self.preview} {data.strip()}".strip()


class TimelineParser(HTMLParser):
    """Validate timeline item structure before browser geometry runs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.element_stack: list[tuple[str, set[str]]] = []
        self.timeline_stack: list[set[str]] = []
        self.item_stack: list[dict[str, object]] = []
        self.bad_items: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        classes = set(attrs_dict.get("class", "").split())
        if self.timeline_stack and classes & {"timeline-item", "tl-entry"}:
            self.item_stack.append({"timeline": set(self.timeline_stack[-1]), "depth": 0, "children": [], "preview": ""})
        elif self.item_stack:
            item = self.item_stack[-1]
            item["depth"] = int(item["depth"]) + 1
            if int(item["depth"]) == 1:
                children = item["children"]
                assert isinstance(children, list)
                children.append(classes)
        if "timeline" in classes:
            self.timeline_stack.append(classes)
        self.element_stack.append((tag.lower(), classes))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        classes: set[str] = set()
        if self.element_stack:
            _tag, classes = self.element_stack.pop()
        if classes & {"timeline-item", "tl-entry"} and self.item_stack:
            item = self.item_stack.pop()
            children = item["children"]
            timeline_classes = item["timeline"]
            assert isinstance(children, list)
            assert isinstance(timeline_classes, set)
            has_time = any({"timeline-time", "tl-time"} & child for child in children)
            has_body = any({"timeline-body", "tl-body"} & child for child in children)
            is_custom = len(timeline_classes - {"timeline"}) > 0
            if not ((has_time and has_body) or is_custom):
                self.bad_items.append(str(item["preview"]).strip()[:90])
        elif self.item_stack and int(self.item_stack[-1]["depth"]) > 0:
            self.item_stack[-1]["depth"] = int(self.item_stack[-1]["depth"]) - 1
        if "timeline" in classes and self.timeline_stack:
            self.timeline_stack.pop()

    def handle_data(self, data: str) -> None:
        if self.item_stack and data.strip() and len(str(self.item_stack[-1]["preview"])) < 120:
            item = self.item_stack[-1]
            item["preview"] = f"{item['preview']} {data.strip()}".strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pair",
        action="append",
        help="reference:candidate pair. Can be repeated. Use only when the reference is meaningful.",
    )
    parser.add_argument(
        "--artifact",
        action="append",
        help="candidate-only artifact path. Can be repeated. Preferred for generated eval outputs.",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "birch-rendering-check.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "reports" / "birch-rendering-check.md")
    parser.add_argument("--screenshots-dir", type=Path, default=ROOT / "reports" / "birch-screenshots")
    parser.add_argument("--capture", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--viewport", default="desktop:1365x900")
    parser.add_argument("--delay-ms", type=int, default=140)
    parser.add_argument("--fail-on-warn", action="store_true")
    args = parser.parse_args()

    artifacts = parse_artifacts(args.artifact)
    pairs = parse_pairs(args.pair)
    if artifacts and args.pair:
        raise SystemExit("use either --artifact or --pair, not both")
    system_css = SYSTEM_CSS.read_text(encoding="utf-8") if SYSTEM_CSS.exists() else ""
    defined_vars = css_defined_vars(system_css)

    reports = []
    all_findings: list[Finding] = []
    browser = find_chrome() if args.capture else None
    viewport_name, width, height = parse_viewport(args.viewport)
    args.screenshots_dir.mkdir(parents=True, exist_ok=True)

    if artifacts:
        for artifact in artifacts:
            artifact_path = (ROOT / artifact).resolve()
            artifact_report = check_artifact(
                artifact_path,
                system_defined_vars=defined_vars,
                browser=browser,
                screenshots_dir=args.screenshots_dir,
                viewport=(viewport_name, width, height),
                delay_ms=args.delay_ms,
            )
            reports.append(artifact_report)
            all_findings.extend(Finding(**item) for item in artifact_report["findings"])
    else:
        for original, candidate in pairs:
            original_path = (ROOT / original).resolve()
            candidate_path = (ROOT / candidate).resolve()
            pair_report = compare_pair(
                original_path,
                candidate_path,
                system_defined_vars=defined_vars,
                browser=browser,
                screenshots_dir=args.screenshots_dir,
                viewport=(viewport_name, width, height),
                delay_ms=args.delay_ms,
            )
            reports.append(pair_report)
            all_findings.extend(Finding(**item) for item in pair_report["findings"])

    mode = "artifact" if artifacts else "pair"

    payload = {
        "mode": mode,
        "artifacts": reports if artifacts else [],
        "pairs": [] if artifacts else reports,
        "summary": {
            "artifacts": len(reports) if artifacts else 0,
            # Back-compat for GEPA/summary scripts that use this as the checker
            # item denominator. In artifact mode these are checked artifacts.
            "pairs": len(reports),
            "failures": sum(1 for f in all_findings if f.level == "fail"),
            "warnings": sum(1 for f in all_findings if f.level == "warn"),
            "notes": sum(1 for f in all_findings if f.level == "note"),
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.markdown.write_text(render_markdown(payload), encoding="utf-8")

    print(args.markdown)
    print(args.out)
    failures = payload["summary"]["failures"]
    warnings = payload["summary"]["warnings"]
    if failures or (args.fail_on_warn and warnings):
        raise SystemExit(1)


def parse_pairs(items: list[str] | None) -> list[tuple[str, str]]:
    if not items:
        return list(DEFAULT_PAIRS)
    out = []
    for item in items:
        if ":" not in item:
            raise SystemExit(f"--pair must be original:candidate, got {item!r}")
        left, right = item.split(":", 1)
        out.append((left, right))
    return out


def parse_artifacts(items: list[str] | None) -> list[str]:
    return list(items or [])


def parse_viewport(value: str) -> tuple[str, int, int]:
    name, size = value.split(":", 1)
    width, height = size.lower().split("x", 1)
    return name, int(width), int(height)


def display_path(path: Path) -> str:
    path = path.resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def compare_pair(
    original: Path,
    candidate: Path,
    *,
    system_defined_vars: set[str],
    browser: str | None,
    screenshots_dir: Path,
    viewport: tuple[str, int, int],
    delay_ms: int,
) -> dict[str, object]:
    findings: list[Finding] = []
    if not original.exists():
        findings.append(Finding("fail", "original_exists", f"missing {original}"))
    if not candidate.exists():
        findings.append(Finding("fail", "candidate_exists", f"missing {candidate}"))
    if findings:
        return {"original": str(original), "candidate": str(candidate), "findings": [asdict(f) for f in findings]}

    original_stats = page_stats(original)
    candidate_stats = page_stats(candidate)
    findings.extend(contract_findings(candidate, candidate_stats, system_defined_vars))
    findings.extend(compare_stats(original_stats, candidate_stats))

    screenshot = None
    if browser:
        viewport_name, width, height = viewport
        original_png = screenshots_dir / f"{original.stem}-{viewport_name}.png"
        candidate_png = screenshots_dir / f"{candidate.stem}-{viewport_name}.png"
        capture(browser, original, original_png, width=width, height=height, delay_ms=delay_ms)
        capture(browser, candidate, candidate_png, width=width, height=height, delay_ms=delay_ms)
        screenshot = screenshot_metrics(original_png, candidate_png)
        findings.extend(screenshot_findings(screenshot))
        geometry = geometry_audit(browser, candidate, width=width, height=height)
        findings.extend(geometry_findings(geometry))
    else:
        geometry = None

    return {
        "original": display_path(original),
        "candidate": display_path(candidate),
        "original_stats": asdict(original_stats),
        "candidate_stats": asdict(candidate_stats),
        "deltas": deltas(original_stats, candidate_stats),
        "screenshot": screenshot,
        "geometry": geometry,
        "findings": [asdict(f) for f in findings],
    }


def check_artifact(
    artifact: Path,
    *,
    system_defined_vars: set[str],
    browser: str | None,
    screenshots_dir: Path,
    viewport: tuple[str, int, int],
    delay_ms: int,
) -> dict[str, object]:
    findings: list[Finding] = []
    if not artifact.exists():
        findings.append(Finding("fail", "artifact_exists", f"missing {artifact}"))
        return {"artifact": str(artifact), "findings": [asdict(f) for f in findings]}

    stats = page_stats(artifact)
    findings.extend(contract_findings(artifact, stats, system_defined_vars))

    screenshot = None
    if browser:
        viewport_name, width, height = viewport
        artifact_png = screenshots_dir / f"{artifact.stem}-{viewport_name}.png"
        capture(browser, artifact, artifact_png, width=width, height=height, delay_ms=delay_ms)
        screenshot = artifact_screenshot_metrics(artifact_png)
        findings.extend(artifact_screenshot_findings(screenshot))
        geometry = geometry_audit(browser, artifact, width=width, height=height)
        findings.extend(geometry_findings(geometry))
    else:
        geometry = None
        findings.append(Finding("note", "screenshot_capture", "browser unavailable; visual smoke checks skipped"))

    return {
        "artifact": display_path(artifact),
        "stats": asdict(stats),
        "screenshot": screenshot,
        "geometry": geometry,
        "findings": [asdict(f) for f in findings],
    }


def page_stats(path: Path) -> PageStats:
    html = path.read_text(encoding="utf-8")
    birch_css_embedded = bool(BIRCH_STYLE_RE.search(html))
    html_without_birch_css = BIRCH_STYLE_RE.sub("", html)
    parser = StatsParser()
    parser.feed(html)
    text = " ".join(parser.text)
    words = [w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text)]
    styles = extract_style_blocks(html_without_birch_css)
    css = "\n".join(styles)
    css_with_inline = css + "\n" + "\n".join(parser.inline_styles)
    return PageStats(
        path=display_path(path),
        bytes=len(html.encode("utf-8")),
        title=" ".join(parser.title.split()),
        doctype="<!doctype" in html.lower(),
        viewport=bool(re.search(r"<meta[^>]+name=[\"']viewport[\"']", html, flags=re.I)),
        stylesheet_links=parser.links,
        birch_css_embedded=birch_css_embedded,
        style_blocks=len(styles),
        style_bytes=sum(len(s) for s in styles),
        script_blocks=parser.scripts,
        tag_counts=dict(parser.tags),
        class_counts=dict(parser.classes),
        data_attrs=dict(parser.data_attrs),
        text_words=len(words),
        unique_words=len(set(words)),
        css_vars_used=sorted(css_used_vars(html_without_birch_css)),
        css_vars_defined=sorted(css_defined_vars(css_with_inline)),
        hex_colors=sorted(set(re.findall(r"#[0-9a-fA-F]{3,8}\b", css))),
    )


def extract_style_blocks(html: str) -> list[str]:
    return re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.I | re.S)


def css_used_vars(text: str) -> set[str]:
    return set(re.findall(r"var\(\s*(--[-_a-zA-Z0-9]+)", text))


def css_defined_vars(css: str) -> set[str]:
    return set(re.findall(r"(--[-_a-zA-Z0-9]+)\s*:", css))


def contract_findings(candidate: Path, stats: PageStats, system_defined_vars: set[str]) -> list[Finding]:
    html = candidate.read_text(encoding="utf-8")
    local_defined = set(stats.css_vars_defined)
    available_vars = system_defined_vars | local_defined
    unknown = sorted(set(stats.css_vars_used) - available_vars)
    findings = [
        check("doctype", stats.doctype, "doctype present", "missing doctype"),
        check("viewport", stats.viewport, "viewport meta present", "missing viewport meta"),
        check(
            "uses_birch_system_css",
            stats.birch_css_embedded or "styles/birch-system.css" in stats.stylesheet_links,
            "embeds or links Birch system CSS",
            f"stylesheet links: {stats.stylesheet_links}; embedded={stats.birch_css_embedded}",
        ),
        check(
            "has_page_shell",
            stats.class_counts.get("page", 0) >= 1,
            ".page found",
            "candidate should use .page as the outer shell",
        ),
        check(
            "uses_layout_primitives",
            sum(stats.class_counts.get(cls, 0) for cls in LAYOUT_CLASSES) >= 8,
            "layout primitive count is healthy",
            "too few Birch layout primitives; LLM layout may be brittle",
            warn=True,
        ),
        check(
            "uses_semantic_components",
            sum(stats.class_counts.get(cls, 0) for cls in SEMANTIC_CLASSES) >= 8,
            "semantic component count is healthy",
            "too few semantic components; likely still page-specific CSS",
            warn=True,
        ),
        check(
            "no_unknown_css_vars",
            not unknown,
            "all CSS variables are defined in Birch system or local CSS",
            "undefined CSS vars: " + ", ".join(unknown[:8]),
        ),
        check(
            "no_patch_markers",
            not any(line.startswith("+") for line in html.splitlines()),
            "no accidental patch marker lines",
            "found line beginning with +",
        ),
    ]
    if stats.style_bytes > 2500:
        findings.append(
            Finding(
                "warn",
                "local_css_size",
                f"{stats.style_bytes} bytes of local CSS; consider moving recurring patterns into birch-system.css",
            )
        )
    local_css = "\n".join(extract_style_blocks(BIRCH_STYLE_RE.sub("", html)))
    if re.search(r"\b(?:linear|radial|conic)-gradient\s*\(", local_css, flags=re.I):
        findings.append(
            Finding(
                "fail",
                "no_birch_gradients",
                "Birch artifacts use flat token surfaces; page-local gradient backgrounds are not allowed",
            )
        )
    hard_colors = [
        c for c in stats.hex_colors if c.lower() not in {"#fff", "#ffffff"} and not is_palette_hex(c)
    ]
    if hard_colors:
        findings.append(
            Finding(
                "note",
                "local_literal_colors",
                "literal colors outside canonical palette: " + ", ".join(hard_colors[:8]),
            )
        )
    findings.extend(svg_visual_findings(html))
    grid_list_parser = GridListParser()
    grid_list_parser.feed(html)
    if grid_list_parser.bad_items:
        findings.append(
            Finding(
                "fail",
                "grid_list_item_children",
                "grid-based insight/takeaway list items should wrap content in one child; examples: "
                + " | ".join(item or "<empty>" for item in grid_list_parser.bad_items[:4]),
            )
        )
    checklist_parser = ChecklistParser()
    checklist_parser.feed(html)
    if checklist_parser.bad_items and re.search(r"\.checklist\s+li\s*\{[^}]*display\s*:\s*flex", html, flags=re.I | re.S):
        findings.append(
            Finding(
                "fail",
                "checklist_inline_layout",
                "checklist rows with inline elements must preserve normal text flow; examples: "
                + " | ".join(item or "<empty>" for item in checklist_parser.bad_items[:4]),
            )
        )

    metric_row_parser = MetricRowParser()
    metric_row_parser.feed(html)
    if metric_row_parser.bad_rows:
        findings.append(
            Finding(
                "fail",
                "metric_row_contract",
                ".metric-row must be caption + .meter + code; examples: "
                + " | ".join(item or "<empty>" for item in metric_row_parser.bad_rows[:4]),
            )
        )
    diff_row_parser = DiffRowParser()
    diff_row_parser.feed(html)
    if diff_row_parser.bad_rows:
        findings.append(
            Finding(
                "fail",
                "diff_row_contract",
                ".diff-row must contain span.ln + span.mark + span.code; loose text wraps in the narrow grid column; examples: "
                + " | ".join(item or "<empty>" for item in diff_row_parser.bad_rows[:4]),
            )
        )
    diff_polarity_parser = DiffPolarityParser()
    diff_polarity_parser.feed(html)
    if diff_polarity_parser.bad_rows:
        findings.append(
            Finding(
                "fail",
                "diff_row_polarity",
                "+/- diff rows must use .add/.del or data-kind=add/del so Birch colors them green/red; examples: "
                + " | ".join(item or "<empty>" for item in diff_polarity_parser.bad_rows[:6]),
            )
        )
    flow_step_parser = FlowStepParser()
    flow_step_parser.feed(html)
    if flow_step_parser.bad_steps:
        findings.append(
            Finding(
                "fail",
                "flow_step_contract",
                ".flow-step must contain .flow-num plus one content wrapper; loose title/detail children can wrap in the narrow number column; examples: "
                + " | ".join(item or "<empty>" for item in flow_step_parser.bad_steps[:4]),
            )
        )
    timeline_parser = TimelineParser()
    timeline_parser.feed(html)
    if timeline_parser.bad_items:
        findings.append(
            Finding(
                "fail",
                "timeline_item_contract",
                ".timeline-item must use timeline-time + timeline-body, or a custom scoped timeline class; examples: "
                + " | ".join(item or "<empty>" for item in timeline_parser.bad_items[:4]),
            )
        )
    chart_expected = (
        "numeric-data" in stats.path
        or "benchmark-comparison" in stats.path
        or stats.class_counts.get("chart-caption", 0) > 0
    )
    numeric_rich = (
        chart_expected
        and stats.class_counts.get("numeric-table", 0) > 0
        and (
            stats.class_counts.get("stat-value", 0) >= 3
            or stats.class_counts.get("metric", 0) >= 12
        )
    )
    chart_count = (
        stats.class_counts.get("chart-panel", 0)
        + stats.class_counts.get("chart-svg", 0)
        + stats.tag_counts.get("svg", 0)
    )
    if numeric_rich and chart_count == 0:
        findings.append(
            Finding(
                "fail",
                "missing_data_visualization",
                "numeric-rich report has KPI/table data but no chart-panel, chart-svg, or inline SVG",
            )
        )
    return findings


def svg_visual_findings(html: str) -> list[Finding]:
    """Catch obvious SVG presentation omissions that render as visual defects.

    This is intentionally narrow. A common LLM failure is hand-writing a chart
    ``<polyline>`` and relying on SVG defaults; browsers fill it black, producing
    a large wedge instead of a line chart. That is a visual aberration, not a
    semantic HTML issue, but it is cheap to detect deterministically.
    """

    css = "\n".join(extract_style_blocks(html))
    css_fill_none_classes = set(
        re.findall(r"\.([A-Za-z0-9_-]+)\s*\{[^}]*\bfill\s*:\s*none\b", css, flags=re.I | re.S)
    )
    bad: list[str] = []
    for match in re.finditer(r"<(polyline|path)\b([^>]*)>", html, flags=re.I):
        tag, attrs = match.group(1).lower(), match.group(2)
        attrs_dict = {k.lower(): v for k, v in re.findall(r"([:\w-]+)\s*=\s*[\"']([^\"']*)[\"']", attrs)}
        classes = set(attrs_dict.get("class", "").split())
        style = attrs_dict.get("style", "")
        has_fill_none = (
            attrs_dict.get("fill", "").lower() == "none"
            or bool(re.search(r"\bfill\s*:\s*none\b", style, flags=re.I))
            or bool(classes & css_fill_none_classes)
        )
        has_stroke = (
            "stroke" in attrs_dict
            or bool(re.search(r"\bstroke\s*:", style, flags=re.I))
            or (
                bool(re.search(r"\.(" + "|".join(map(re.escape, classes)) + r")\s*\{[^}]*\bstroke\s*:", css, flags=re.I | re.S))
                if classes
                else False
            )
        )
        chartish = tag == "polyline" or classes & {"chart-line", "line-pass", "line-vision", "trend-line"}
        if chartish and not has_fill_none:
            label = "." + ".".join(sorted(classes)) if classes else tag
            bad.append(f"{label} lacks fill=none")
        elif chartish and not has_stroke:
            label = "." + ".".join(sorted(classes)) if classes else tag
            bad.append(f"{label} lacks explicit stroke")
    if not bad:
        return []
    return [
        Finding(
            "fail",
            "svg_chart_mark_presentation",
            "chart SVG line/path marks must explicitly avoid default black fill and define a stroke; examples: "
            + " | ".join(bad[:6]),
        )
    ]


def compare_stats(original: PageStats, candidate: PageStats) -> list[Finding]:
    findings: list[Finding] = []
    original_words = original.unique_words
    candidate_words = candidate.unique_words
    if original_words and candidate_words / original_words < 0.45:
        findings.append(
            Finding(
                "warn",
                "text_coverage",
                f"candidate has {candidate_words} unique words vs source {original_words}; may be too compressed",
            )
        )

    original_sections = original.tag_counts.get("section", 0)
    candidate_sections = candidate.tag_counts.get("section", 0)
    if original_sections and candidate_sections < max(2, math.floor(original_sections * 0.65)):
        findings.append(
            Finding(
                "warn",
                "section_count_drift",
                f"candidate sections {candidate_sections}, source sections {original_sections}",
            )
        )

    orig_cards = original.class_counts.get("card", 0) + original.class_counts.get("component", 0)
    cand_cards = candidate.class_counts.get("card", 0) + candidate.class_counts.get("panel", 0)
    if orig_cards and cand_cards < orig_cards * 0.6:
        findings.append(
            Finding("warn", "component_density_drop", f"candidate card/panel count {cand_cards}, source rough count {orig_cards}")
        )

    source_birch_classes = sum(original.class_counts.get(cls, 0) for cls in BIRCH_CLASSES)
    candidate_birch_classes = sum(candidate.class_counts.get(cls, 0) for cls in BIRCH_CLASSES)
    findings.append(
        Finding(
            "note",
            "birch_class_delta",
            f"source Birch-contract class uses {source_birch_classes}; candidate {candidate_birch_classes}",
        )
    )
    return findings


def check(name: str, passed: bool, ok: str, bad: str, *, warn: bool = False) -> Finding:
    return Finding("pass" if passed else ("warn" if warn else "fail"), name, ok if passed else bad)


def deltas(original: PageStats, candidate: PageStats) -> dict[str, object]:
    watched = sorted(BIRCH_CLASSES)
    return {
        "bytes": candidate.bytes - original.bytes,
        "style_bytes": candidate.style_bytes - original.style_bytes,
        "text_words": candidate.text_words - original.text_words,
        "unique_words": candidate.unique_words - original.unique_words,
        "sections": candidate.tag_counts.get("section", 0) - original.tag_counts.get("section", 0),
        "scripts": candidate.script_blocks - original.script_blocks,
        "class_counts": {
            cls: candidate.class_counts.get(cls, 0) - original.class_counts.get(cls, 0)
            for cls in watched
            if candidate.class_counts.get(cls, 0) or original.class_counts.get(cls, 0)
        },
    }


def is_palette_hex(value: str, *, tolerance: int = 3) -> bool:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) < 6:
        return False
    rgb = tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    return any(sum(abs(rgb[i] - color[i]) for i in range(3)) <= tolerance for color in PALETTE.values())


def find_chrome() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def capture(browser: str, html: Path, out: Path, *, width: int, height: int, delay_ms: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    # Use the real file URI so relative links like styles/birch-system.css load.
    # The Birchline helper copies single-file standalone artifacts to a temp dir;
    # these Birch candidates intentionally depend on a shared stylesheet.
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--window-size={width},{height}",
        f"--screenshot={out.resolve()}",
        f"--virtual-time-budget={delay_ms}",
        html.resolve().as_uri(),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=False)


def screenshot_metrics(original: Path, candidate: Path) -> dict[str, object] | None:
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageStat
    except Exception:
        return None
    if not original.exists() or not candidate.exists():
        return None
    a = Image.open(original).convert("RGB")
    b = Image.open(candidate).convert("RGB")
    size = (min(a.width, b.width), min(a.height, b.height))
    a = a.crop((0, 0, *size))
    b = b.crop((0, 0, *size))
    diff = ImageChops.difference(a, b)
    stat = ImageStat.Stat(diff)
    mean_abs = sum(stat.mean) / 3.0
    rms = math.sqrt(sum(v * v for v in stat.rms) / 3.0)
    diff_png = candidate.with_name(f"{original.stem}__vs__{candidate.stem}-diff.png")
    contact_png = candidate.with_name(f"{original.stem}__vs__{candidate.stem}-contact.png")
    amplified = ImageEnhance.Brightness(diff).enhance(4.0)
    amplified.save(diff_png)
    make_contact_sheet(a, b, amplified, contact_png)
    return {
        "original_png": display_path(original),
        "candidate_png": display_path(candidate),
        "diff_png": display_path(diff_png),
        "contact_png": display_path(contact_png),
        "size": list(size),
        "mean_abs_rgb_delta": round(mean_abs, 2),
        "rms_rgb_delta": round(rms, 2),
        "original_palette": palette_metrics(a),
        "candidate_palette": palette_metrics(b),
    }


def artifact_screenshot_metrics(png: Path) -> dict[str, object] | None:
    try:
        from PIL import Image, ImageStat
    except Exception:
        return None
    if not png.exists():
        return None
    image = Image.open(png).convert("RGB")
    stat = ImageStat.Stat(image)
    bg = PALETTE["ivory"]
    sampled = image.resize((max(1, image.width // 4), max(1, image.height // 4)))
    pixels = sampled.get_flattened_data() if hasattr(sampled, "get_flattened_data") else sampled.getdata()
    total = 0
    bg_close = 0
    dark = 0
    for r, g, b in pixels:
        total += 1
        if sum(abs((r, g, b)[i] - bg[i]) for i in range(3)) <= 26:
            bg_close += 1
        if r < 12 and g < 12 and b < 12:
            dark += 1
    background_fraction = bg_close / total if total else 1.0
    return {
        "png": display_path(png),
        "size": [image.width, image.height],
        "mean_rgb": [round(v, 2) for v in stat.mean],
        "palette": palette_metrics(image),
        "background_fraction": round(background_fraction, 4),
        "non_background_fraction": round(1.0 - background_fraction, 4),
        "blackish_fraction": round(dark / total, 4) if total else 0.0,
        "file_bytes": png.stat().st_size,
    }


def artifact_screenshot_findings(metrics: dict[str, object] | None) -> list[Finding]:
    if metrics is None:
        return [Finding("fail", "screenshot_capture", "browser/Pillow screenshot capture unavailable")]
    out = [Finding("note", "screenshot_capture", f"captured {metrics['png']} at {metrics['size']}")]
    if int(metrics["file_bytes"]) < 2048:
        out.append(Finding("fail", "blank_render", f"screenshot file is unexpectedly small: {metrics['file_bytes']} bytes"))
    if float(metrics["non_background_fraction"]) < 0.025:
        out.append(
            Finding(
                "fail",
                "blank_render",
                f"non-background fraction {metrics['non_background_fraction']} is too low",
            )
        )
    palette = metrics["palette"]
    assert isinstance(palette, dict)
    if float(palette["palette_close_fraction"]) < 0.40:
        out.append(
            Finding(
                "warn",
                "palette_drift",
                f"palette-close fraction {palette['palette_close_fraction']} is low",
            )
        )
    if float(metrics["blackish_fraction"]) > 0.08:
        out.append(
            Finding(
                "warn",
                "black_pixel_fraction",
                f"blackish fraction {metrics['blackish_fraction']} may indicate unstyled SVG/code blocks",
            )
        )
    return out


def make_contact_sheet(original, candidate, diff, out: Path) -> None:
    from PIL import Image, ImageDraw

    label_h = 28
    gutter = 12
    thumb_w = min(430, original.width)
    scale = thumb_w / original.width
    thumb_h = int(original.height * scale)

    def thumb(img):
        return img.resize((thumb_w, thumb_h))

    tiles = [thumb(original), thumb(candidate), thumb(diff)]
    sheet = Image.new("RGB", (thumb_w * 3 + gutter * 2, thumb_h + label_h), (250, 249, 245))
    draw = ImageDraw.Draw(sheet)
    labels = ["source", "birch candidate", "amplified diff"]
    for i, tile in enumerate(tiles):
        x = i * (thumb_w + gutter)
        sheet.paste(tile, (x, label_h))
        draw.text((x + 8, 8), labels[i], fill=(61, 61, 58))
    sheet.save(out)


def palette_metrics(image) -> dict[str, float]:
    resized = image.resize((max(1, image.width // 4), max(1, image.height // 4)))
    pixels = resized.get_flattened_data() if hasattr(resized, "get_flattened_data") else resized.getdata()
    total = 0
    close = 0
    ivory = 0
    blackish = 0
    for r, g, b in pixels:
        total += 1
        if min(sum(abs((r, g, b)[i] - color[i]) for i in range(3)) for color in PALETTE.values()) <= 34:
            close += 1
        if sum(abs((r, g, b)[i] - PALETTE["ivory"][i]) for i in range(3)) <= 18:
            ivory += 1
        if r < 12 and g < 12 and b < 12:
            blackish += 1
    return {
        "palette_close_fraction": round(close / total, 4) if total else 0.0,
        "ivory_fraction": round(ivory / total, 4) if total else 0.0,
        "blackish_fraction": round(blackish / total, 4) if total else 0.0,
    }


def screenshot_findings(metrics: dict[str, object] | None) -> list[Finding]:
    if metrics is None:
        return [Finding("note", "screenshot_compare", "Pillow/browser screenshot metrics unavailable")]
    out = [
        Finding(
            "note",
            "screenshot_distance",
            f"mean RGB delta {metrics['mean_abs_rgb_delta']}, RMS {metrics['rms_rgb_delta']}",
        )
    ]
    cand = metrics["candidate_palette"]
    assert isinstance(cand, dict)
    if float(cand["palette_close_fraction"]) < 0.55:
        out.append(
            Finding(
                "warn",
                "palette_drift",
                f"candidate palette-close fraction {cand['palette_close_fraction']} is low",
            )
        )
    if float(cand["blackish_fraction"]) > 0.05:
        out.append(
            Finding(
                "warn",
                "black_pixel_fraction",
                f"candidate blackish fraction {cand['blackish_fraction']} may indicate unstyled SVG/code blocks",
            )
        )
    return out


def geometry_audit(browser: str, html: Path, *, width: int, height: int) -> dict[str, object] | None:
    """Run a small in-browser layout audit and return geometry symptoms.

    This catches classes of problems a static parser cannot see:
    - text/content overflowing its box,
    - metric bars not sharing the same relative x-position inside comparable cards,
    - split side-rail headings aligning to section chrome instead of content headings,
    - numeric table headers not matching their column alignment.
    """
    audit_js = r"""
<script>
window.addEventListener('load', function () {
  function path(el) {
    var parts = [];
    while (el && el.nodeType === 1 && parts.length < 5) {
      var part = el.tagName.toLowerCase();
      if (el.id) part += '#' + el.id;
      if (el.className && typeof el.className === 'string') {
        var cls = el.className.trim().split(/\s+/).slice(0, 3).join('.');
        if (cls) part += '.' + cls;
      }
      parts.unshift(part);
      el = el.parentElement;
    }
    return parts.join(' > ');
  }
  function text(el) {
    return (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  }
  var viewportWidth = document.documentElement.clientWidth;
  var overflow = [];
  document.querySelectorAll('p, li, h1, h2, h3, code, pre, .chip, .badge, .button, .btn, .caption, .muted, .stat-value').forEach(function (el) {
    var cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    var r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    var overX = el.scrollWidth - el.clientWidth;
    var overY = el.scrollHeight - el.clientHeight;
    var offRight = r.right - viewportWidth;
    var offLeft = -r.left;
    if (el.classList && el.classList.contains('flow-step') && overX <= 2 && offRight <= 2 && offLeft <= 2) return;
    if (overX > 2 || overY > 2 || offRight > 2 || offLeft > 2) {
      overflow.push({
        selector: path(el),
        text: text(el),
        overX: Math.round(overX),
        overY: Math.round(overY),
        offRight: Math.round(Math.max(0, offRight)),
        offLeft: Math.round(Math.max(0, offLeft))
      });
    }
  });

  var containerOverflow = [];
  document.querySelectorAll('.card p, .card code, .card .caption, .card .muted, .card .stat-value, .panel p, .panel code, .panel .caption, .panel .muted, .reference-panel p, .reference-panel code, .reference-panel .caption, .reference-panel .muted, .metric-row > *').forEach(function (el) {
    var cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    var r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    var container = el.closest('.metric-row, .stat-card, .card, .panel, .reference-panel, .callout');
    if (!container || container === el) return;
    var cr = container.getBoundingClientRect();
    if (cr.width < 1 || cr.height < 1) return;
    var overRight = r.right - cr.right;
    var overLeft = cr.left - r.left;
    var scrollX = el.scrollWidth - el.clientWidth;
    if (overRight > 2 || overLeft > 2 || scrollX > 2) {
      containerOverflow.push({
        selector: path(el),
        container: path(container),
        text: text(el),
        overRight: Math.round(Math.max(0, overRight)),
        overLeft: Math.round(Math.max(0, overLeft)),
        scrollX: Math.round(Math.max(0, scrollX)),
        elementWidth: Math.round(r.width),
        containerWidth: Math.round(cr.width)
      });
    }
  });

  var statCardSqueeze = [];
  document.querySelectorAll('.stat-card').forEach(function (card) {
    var r = card.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    var value = card.querySelector('.stat-value');
    if (!value) return;
    var stats = rectStatsForText(value);
    var valueWidth = stats ? stats.maxWidth : Math.round(value.getBoundingClientRect().width);
    if (r.width < 150 || value.getBoundingClientRect().right > r.right + 2) {
      statCardSqueeze.push({
        selector: path(card),
        text: text(card),
        width: Math.round(r.width),
        valueWidth: valueWidth
      });
    }
  });

  var sectionRailOrder = [];
  document.querySelectorAll('.section-rail').forEach(function (rail) {
    var children = Array.prototype.filter.call(rail.children, function (el) {
      if (el.classList.contains('section-head')) return false;
      var r = el.getBoundingClientRect();
      return r.width > 1 && r.height > 1;
    });
    if (children.length < 2) return;
    var first = children[0];
    var second = children[1];
    var firstIsRail = first.matches('aside, .reference-panel');
    var secondHasContentCards = !!second.querySelector('.card, .flow-step, .timeline, .numeric-table, .chart-panel');
    var firstRect = first.getBoundingClientRect();
    var secondRect = second.getBoundingClientRect();
    if (firstIsRail && secondHasContentCards && firstRect.left < secondRect.left) {
      sectionRailOrder.push({
        selector: path(rail),
        first: path(first),
        second: path(second),
        firstWidth: Math.round(firstRect.width),
        secondWidth: Math.round(secondRect.width)
      });
    }
  });

  var timelineProblems = [];
  document.querySelectorAll('.timeline').forEach(function (timeline) {
    var timelineRect = timeline.getBoundingClientRect();
    var line = timeline.querySelector('.timeline-item, .tl-entry');
    timeline.querySelectorAll('.timeline-body, .tl-body, .timeline-item p, .timeline-item li, .timeline-item .badge').forEach(function (el) {
      var r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return;
      var offRight = r.right - viewportWidth;
      var overX = el.scrollWidth - el.clientWidth;
      if (offRight > 2 || overX > 2) {
        timelineProblems.push({
          selector: path(el),
          text: text(el),
          offRight: Math.round(Math.max(0, offRight)),
          overX: Math.round(Math.max(0, overX))
        });
      }
    });
    timeline.querySelectorAll('.timeline-item, .tl-entry').forEach(function (item) {
      var dotStyle = getComputedStyle(item, '::before');
      var dotLeft = parseFloat(dotStyle.left);
      if (!isFinite(dotLeft)) return;
      var itemRect = item.getBoundingClientRect();
      var dotCenter = itemRect.left + dotLeft + 5.5;
      var expected = timelineRect.left + 9.75;
      var delta = Math.round((dotCenter - expected) * 10) / 10;
      if (Math.abs(delta) > 2.5) {
        timelineProblems.push({
          selector: path(item),
          text: text(item),
          markerDelta: delta
        });
      }
    });
  });

  var metricGroups = [];
  var metricRowSqueeze = [];
  document.querySelectorAll('.metric-list').forEach(function (list) {
    var owner = list.closest('.panel, .card, section, main') || list;
    var ownerRect = owner.getBoundingClientRect();
    var xs = [];
    list.querySelectorAll('.metric-row .meter').forEach(function (meter) {
      xs.push(Math.round(meter.getBoundingClientRect().left - ownerRect.left));
    });
    if (xs.length > 1) {
      var min = Math.min.apply(Math, xs);
      var max = Math.max.apply(Math, xs);
      metricGroups.push({ owner: path(owner), meterXs: xs, spread: max - min });
    }
    list.querySelectorAll('.metric-row').forEach(function (row) {
      var rowRect = row.getBoundingClientRect();
      var children = Array.prototype.filter.call(row.children, function (el) {
        var r = el.getBoundingClientRect();
        return r.width > 1 && r.height > 1;
      });
      if (children.length < 3) return;
      var firstRect = children[0].getBoundingClientRect();
      var meterRect = children[1].getBoundingClientRect();
      var lastRect = children[2].getBoundingClientRect();
      var stats = rectStatsForText(children[2]);
      var lastTextWidth = stats ? stats.maxWidth : Math.round(lastRect.width);
      var ownerOverRight = lastRect.right - ownerRect.right;
      var rowOverRight = lastRect.right - rowRect.right;
      var tightMeter = meterRect.width < 96 && rowRect.width < 380;
      var clippedValue = lastTextWidth > lastRect.width + 2 || ownerOverRight > 2 || rowOverRight > 2;
      if (tightMeter || clippedValue) {
        metricRowSqueeze.push({
          owner: path(owner),
          row: path(row),
          text: text(row),
          rowWidth: Math.round(rowRect.width),
          meterWidth: Math.round(meterRect.width),
          valueWidth: Math.round(lastRect.width),
          valueTextWidth: lastTextWidth,
          ownerOverRight: Math.round(Math.max(0, ownerOverRight)),
          rowOverRight: Math.round(Math.max(0, rowOverRight))
        });
      }
    });
  });

  var splitRailGroups = [];
  document.querySelectorAll('.split').forEach(function (split) {
    var children = Array.prototype.filter.call(split.children, function (el) {
      var r = el.getBoundingClientRect();
      return r.width > 1 && r.height > 1;
    });
    if (children.length < 2) return;
    var leftHeading = children[0].querySelector('h1, h2, h3');
    var rightHeading = children[1].querySelector('h1, h2, h3');
    if (!leftHeading || !rightHeading) return;
    var leftRect = leftHeading.getBoundingClientRect();
    var rightRect = rightHeading.getBoundingClientRect();
    if (Math.abs(leftRect.left - rightRect.left) < 8) return; // stacked mobile layout
    splitRailGroups.push({
      owner: path(split),
      leftHeading: text(leftHeading),
      rightHeading: text(rightHeading),
      delta: Math.round((rightRect.top - leftRect.top) * 10) / 10
    });
  });

  var numericHeaderGroups = [];
  document.querySelectorAll('.numeric-table').forEach(function (table) {
    var headers = table.querySelectorAll('thead th');
    var firstRow = table.querySelector('tbody tr');
    if (!headers.length || !firstRow) return;
    Array.prototype.forEach.call(headers, function (th, index) {
      var td = firstRow.children[index];
      if (!td) return;
      var thStyle = getComputedStyle(th);
      var tdStyle = getComputedStyle(td);
      if (thStyle.display === 'none' || tdStyle.display === 'none') return;
      var thAlign = thStyle.textAlign;
      var tdAlign = tdStyle.textAlign;
      if (tdAlign === 'right' && thAlign !== 'right') {
        numericHeaderGroups.push({
          table: path(table),
          header: text(th),
          column: index + 1,
          headerAlign: thAlign,
          bodyAlign: tdAlign
        });
      }
    });
  });

  function rectStatsForText(el) {
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    var rawRects = [];
    var node;
    while ((node = walker.nextNode())) {
      if (!node.nodeValue || !node.nodeValue.trim()) continue;
      var range = document.createRange();
      range.selectNodeContents(node);
      Array.prototype.forEach.call(range.getClientRects(), function (r) {
        if (r.width > 1 && r.height > 1) rawRects.push(r);
      });
      range.detach();
    }
    if (!rawRects.length) return null;
    rawRects.sort(function (a, b) {
      return Math.abs(a.top - b.top) > 2 ? a.top - b.top : a.left - b.left;
    });
    var lines = [];
    rawRects.forEach(function (r) {
      var line = lines.length ? lines[lines.length - 1] : null;
      if (!line || Math.abs(line.top - r.top) > 2) {
        lines.push({ top: r.top, left: r.left, right: r.right });
      } else {
        line.left = Math.min(line.left, r.left);
        line.right = Math.max(line.right, r.right);
      }
    });
    var widths = lines.map(function (line) { return line.right - line.left; }).sort(function (a, b) { return a - b; });
    return {
      lines: lines.length,
      maxWidth: Math.round(widths[widths.length - 1]),
      medianWidth: Math.round(widths[Math.floor(widths.length / 2)])
    };
  }

  var codeWrapProblems = [];
  document.querySelectorAll('.code-block[data-wrap="true"], .code-block[data-kind="command"], .command-block').forEach(function (el) {
    var cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    var r = el.getBoundingClientRect();
    if (r.width < 300 || r.height < 1) return;
    var raw = el.textContent || '';
    var compact = raw.replace(/\s+/g, ' ').trim();
    if (compact.length < 120) return;
    var stats = rectStatsForText(el);
    if (!stats) return;
    var logicalLines = Math.max(1, raw.split(/\r?\n/).length);
    var charsPerVisualLine = compact.length / Math.max(1, stats.lines);
    var tinyLines = stats.lines >= logicalLines * 3 && charsPerVisualLine < 18;
    var underfilled = stats.maxWidth < r.width * 0.45 && stats.lines >= logicalLines * 2;
    if (tinyLines || underfilled) {
      codeWrapProblems.push({
        selector: path(el),
        text: text(el),
        blockWidth: Math.round(r.width),
        visualLines: stats.lines,
        logicalLines: logicalLines,
        charsPerVisualLine: Math.round(charsPerVisualLine * 10) / 10,
        maxLineWidth: stats.maxWidth,
        medianLineWidth: stats.medianWidth
      });
    }
  });

  var textWrapProblems = [];
  document.querySelectorAll('.card p, .card li, .panel p, .panel li, .callout p, .callout li, .reference-panel p, .reference-panel li').forEach(function (el) {
    var cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    var r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 1) return;
    var raw = el.textContent || '';
    var compact = raw.replace(/\s+/g, ' ').trim();
    if (compact.length < 60) return;
    var stats = rectStatsForText(el);
    if (!stats || stats.lines < 4) return;
    var charsPerVisualLine = compact.length / Math.max(1, stats.lines);
    var narrowLine = stats.medianWidth < Math.min(80, r.width * 0.32);
    var pathological = charsPerVisualLine < 14 && narrowLine;
    if (pathological) {
      textWrapProblems.push({
        selector: path(el),
        text: text(el),
        blockWidth: Math.round(r.width),
        visualLines: stats.lines,
        charsPerVisualLine: Math.round(charsPerVisualLine * 10) / 10,
        maxLineWidth: stats.maxWidth,
        medianLineWidth: stats.medianWidth
      });
    }
  });

  document.body.setAttribute('data-birch-audit', JSON.stringify({
    overflow: overflow,
    containerOverflow: containerOverflow,
    statCardSqueeze: statCardSqueeze,
    sectionRailOrder: sectionRailOrder,
    pageOverflowX: Math.round(document.documentElement.scrollWidth - document.documentElement.clientWidth),
    timelineProblems: timelineProblems,
    metricGroups: metricGroups,
    metricRowSqueeze: metricRowSqueeze,
    splitRailGroups: splitRailGroups,
    numericHeaderGroups: numericHeaderGroups,
    codeWrapProblems: codeWrapProblems,
    textWrapProblems: textWrapProblems
  }));
});
</script>
"""
    source = html.read_text(encoding="utf-8")
    base = f'<base href="{ROOT.resolve().as_uri()}/">'
    if re.search(r"<head(?:\s[^>]*)?>", source, flags=re.I):
        # The base element must appear before relative stylesheet/script links.
        # Otherwise the temp-file audit silently loses shared CSS and geometry
        # checks run against unstyled HTML.
        source = re.sub(r"(<head(?:\s[^>]*)?>)", lambda m: m.group(1) + base, source, count=1, flags=re.I)
        source = re.sub(r"</head>", lambda _m: audit_js + "</head>", source, count=1, flags=re.I)
    else:
        source = base + audit_js + source
    with tempfile.TemporaryDirectory(prefix="birch-audit-") as tmp:
        temp = Path(tmp) / html.name
        temp.write_text(source, encoding="utf-8")
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--window-size={width},{height}",
            "--virtual-time-budget=800",
            "--dump-dom",
            temp.resolve().as_uri(),
        ]
        completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=45, check=False)
    match = re.search(r'data-birch-audit="([^"]+)"', completed.stdout)
    if not match:
        return None
    import html as html_lib

    try:
        return json.loads(html_lib.unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def geometry_findings(audit: dict[str, object] | None) -> list[Finding]:
    if audit is None:
        return [Finding("note", "geometry_audit", "browser geometry audit unavailable")]
    findings: list[Finding] = []
    overflow = audit.get("overflow") or []
    container_overflow = audit.get("containerOverflow") or []
    stat_card_squeeze = audit.get("statCardSqueeze") or []
    section_rail_order = audit.get("sectionRailOrder") or []
    page_overflow_x = int(audit.get("pageOverflowX") or 0)
    timeline_problems = audit.get("timelineProblems") or []
    metric_groups = audit.get("metricGroups") or []
    metric_row_squeeze = audit.get("metricRowSqueeze") or []
    split_rail_groups = audit.get("splitRailGroups") or []
    numeric_header_groups = audit.get("numericHeaderGroups") or []
    code_wrap_problems = audit.get("codeWrapProblems") or []
    text_wrap_problems = audit.get("textWrapProblems") or []
    if isinstance(overflow, list) and overflow:
        worst = overflow[:5]
        findings.append(
            Finding(
                "fail",
                "layout_overflow",
                "; ".join(
                    f"{item.get('selector')} overX={item.get('overX')} overY={item.get('overY')} offRight={item.get('offRight', 0)}"
                    for item in worst
                    if isinstance(item, dict)
                ),
            )
        )
    elif page_overflow_x > 2:
        findings.append(Finding("fail", "layout_overflow", f"document overflows viewport horizontally by {page_overflow_x}px"))
    else:
        findings.append(Finding("pass", "layout_overflow", "no visible text/content overflow detected"))

    if isinstance(container_overflow, list) and container_overflow:
        findings.append(
            Finding(
                "fail",
                "container_text_overflow",
                "; ".join(
                    f"{item.get('selector')} spills within {item.get('container')} "
                    f"right={item.get('overRight')}px left={item.get('overLeft')}px scrollX={item.get('scrollX')}px "
                    f"({item.get('elementWidth')}/{item.get('containerWidth')}px)"
                    for item in container_overflow[:6]
                    if isinstance(item, dict)
                ),
            )
        )
    elif audit.get("containerOverflow") is not None:
        findings.append(Finding("pass", "container_text_overflow", "text stays within its card/panel containers"))

    if isinstance(stat_card_squeeze, list) and stat_card_squeeze:
        findings.append(
            Finding(
                "fail",
                "stat_card_squeeze",
                "; ".join(
                    f"{item.get('selector')} width={item.get('width')}px valueWidth={item.get('valueWidth')}px text={item.get('text')}"
                    for item in stat_card_squeeze[:6]
                    if isinstance(item, dict)
                ),
            )
        )
    elif audit.get("statCardSqueeze") is not None:
        findings.append(Finding("pass", "stat_card_squeeze", "KPI/stat cards have enough horizontal space"))

    if isinstance(section_rail_order, list) and section_rail_order:
        findings.append(
            Finding(
                "warn",
                "section_rail_order",
                "; ".join(
                    f"{item.get('selector')} appears to put the aside/reference rail before main content "
                    f"({item.get('firstWidth')}px left, {item.get('secondWidth')}px right)"
                    for item in section_rail_order[:4]
                    if isinstance(item, dict)
                ),
            )
        )

    if isinstance(timeline_problems, list) and timeline_problems:
        findings.append(
            Finding(
                "fail",
                "timeline_geometry",
                "; ".join(
                    (
                        f"{item.get('selector')} markerDelta={item.get('markerDelta')}px"
                        if "markerDelta" in item
                        else f"{item.get('selector')} offRight={item.get('offRight', 0)} overX={item.get('overX', 0)}"
                    )
                    for item in timeline_problems[:6]
                    if isinstance(item, dict)
                ),
            )
        )
    elif audit.get("timelineProblems") is not None:
        findings.append(Finding("pass", "timeline_geometry", "timeline markers/content stay within expected geometry"))

    bad_metrics = [
        g for g in metric_groups
        if isinstance(g, dict) and int(g.get("spread", 0)) > 2
    ]
    if bad_metrics:
        findings.append(
            Finding(
                "warn",
                "metric_alignment",
                "; ".join(f"{g.get('owner')} spread={g.get('spread')}px" for g in bad_metrics[:4]),
            )
        )
    elif metric_groups:
        findings.append(Finding("pass", "metric_alignment", "metric meters align within each metric-list"))

    if isinstance(metric_row_squeeze, list) and metric_row_squeeze:
        findings.append(
            Finding(
                "warn",
                "metric_row_squeeze",
                "; ".join(
                    f"{g.get('row')} row={g.get('rowWidth')}px meter={g.get('meterWidth')}px "
                    f"value={g.get('valueWidth')}/{g.get('valueTextWidth')}px overRight={g.get('ownerOverRight')}px"
                    for g in metric_row_squeeze[:6]
                    if isinstance(g, dict)
                ),
            )
        )

    bad_split_rails = [
        g for g in split_rail_groups
        if isinstance(g, dict) and abs(float(g.get("delta", 0))) > 3
    ]
    if bad_split_rails:
        findings.append(
            Finding(
                "warn",
                "split_rail_heading_alignment",
                "; ".join(
                    f"{g.get('leftHeading')} ↔ {g.get('rightHeading')} delta={g.get('delta')}px"
                    for g in bad_split_rails[:4]
                ),
            )
        )
    elif split_rail_groups:
        findings.append(Finding("pass", "split_rail_heading_alignment", "split rail headings align with content headings"))

    if numeric_header_groups:
        findings.append(
            Finding(
                "warn",
                "numeric_header_alignment",
                "; ".join(
                    f"{g.get('header')} column {g.get('column')} header={g.get('headerAlign')} body={g.get('bodyAlign')}"
                    for g in numeric_header_groups[:6]
                ),
            )
        )
    else:
        findings.append(Finding("pass", "numeric_header_alignment", "numeric table headers align with right-aligned numeric columns"))

    if code_wrap_problems:
        findings.append(
            Finding(
                "fail",
                "code_wrap_underfill",
                "; ".join(
                    f"{g.get('selector')} width={g.get('blockWidth')}px visualLines={g.get('visualLines')} "
                    f"logicalLines={g.get('logicalLines')} charsPerLine={g.get('charsPerVisualLine')} "
                    f"maxLineWidth={g.get('maxLineWidth')}px"
                    for g in code_wrap_problems[:5]
                    if isinstance(g, dict)
                ),
            )
        )
    elif audit.get("codeWrapProblems") is not None:
        findings.append(Finding("pass", "code_wrap_underfill", "wrapped code/diff blocks use available container width"))

    if text_wrap_problems:
        findings.append(
            Finding(
                "fail",
                "pathological_text_wrapping",
                "; ".join(
                    f"{g.get('selector')} width={g.get('blockWidth')}px visualLines={g.get('visualLines')} "
                    f"charsPerLine={g.get('charsPerVisualLine')} medianLineWidth={g.get('medianLineWidth')}px "
                    f"text={g.get('text')}"
                    for g in text_wrap_problems[:5]
                    if isinstance(g, dict)
                ),
            )
        )
    elif audit.get("textWrapProblems") is not None:
        findings.append(Finding("pass", "pathological_text_wrapping", "prose/list text uses available container width"))
    return findings


def render_markdown(payload: dict[str, object]) -> str:
    mode = payload.get("mode", "pair")
    lines = [
        "# Birch rendering check",
        "",
        (
            "Checks rendered Birch artifacts for contract and visual smoke failures."
            if mode == "artifact"
            else "Compares reference HTML with Birch-system candidates."
        ),
        "",
        "## Summary",
        "",
    ]
    summary = payload["summary"]
    assert isinstance(summary, dict)
    lines.extend(
        [
            f"- Mode: **{mode}**",
            f"- Artifacts: **{summary.get('artifacts', 0)}**",
            f"- Pairs/checks: **{summary['pairs']}**",
            f"- Failures: **{summary['failures']}**",
            f"- Warnings: **{summary['warnings']}**",
            f"- Notes: **{summary['notes']}**",
            "",
        ]
    )
    items = payload.get("artifacts") if mode == "artifact" else payload.get("pairs")
    assert isinstance(items, list)
    for pair in items:
        assert isinstance(pair, dict)
        if mode == "artifact":
            lines.extend([f"## `{pair['artifact']}`", ""])
        else:
            lines.extend([f"## `{pair['original']}` → `{pair['candidate']}`", ""])
        screenshot = pair.get("screenshot")
        if screenshot:
            if mode == "artifact":
                lines.extend(
                    [
                        "### Screenshot metrics",
                        "",
                        f"- Screenshot: `{screenshot['png']}`",
                        f"- Size: `{screenshot['size']}`",
                        f"- Palette close fraction: `{screenshot['palette']['palette_close_fraction']}`",
                        f"- Background fraction: `{screenshot['background_fraction']}`",
                        f"- Non-background fraction: `{screenshot['non_background_fraction']}`",
                        f"- Blackish fraction: `{screenshot['blackish_fraction']}`",
                        "",
                    ]
                )
            else:
                lines.extend(
                    [
                        "### Screenshot metrics",
                        "",
                        f"- Source: `{screenshot['original_png']}`",
                        f"- Candidate: `{screenshot['candidate_png']}`",
                        f"- Contact sheet: `{screenshot['contact_png']}`",
                        f"- Amplified diff: `{screenshot['diff_png']}`",
                        f"- Mean RGB delta: `{screenshot['mean_abs_rgb_delta']}`",
                        f"- RMS RGB delta: `{screenshot['rms_rgb_delta']}`",
                        f"- Candidate palette close fraction: `{screenshot['candidate_palette']['palette_close_fraction']}`",
                        f"- Candidate ivory fraction: `{screenshot['candidate_palette']['ivory_fraction']}`",
                        "",
                    ]
                )
        if mode != "artifact":
            lines.extend(["### Deltas", "", "```json", json.dumps(pair.get("deltas", {}), indent=2), "```", ""])
        lines.extend(["### Findings", "", "| level | check | evidence |", "|---|---|---|"])
        for finding in pair.get("findings", []):
            lines.append(f"| {finding['level']} | `{finding['name']}` | {finding['evidence']} |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
