"""Hugging Face design options for Prefab review builds."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal, get_args

HFDesign = Literal["hub-classic", "spaces-gradient", "dataset-studio"]
HF_DESIGNS = get_args(HFDesign)

HF_FONT_STYLESHEET = (
    "https://fonts.googleapis.com/css2?"
    "family=IBM+Plex+Mono:wght@400;600&"
    "family=Source+Sans+3:wght@400;600;700&display=swap"
)
HF_RESOURCE_DOMAINS = (
    "https://fonts.googleapis.com",
    "https://fonts.gstatic.com",
)

_LOGO = Path(__file__).with_name("assets") / "huggingface-logo.svg"
HF_LOGO_DATA_URI = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(_LOGO.read_bytes()).decode("ascii")
)

HF_DESIGN_CSS = """
.hf-design {
  --hf-yellow: #ffd21e;
  --hf-amber: #f59e0b;
  --hf-orange: #ff9d0b;
  --hf-blue: #3b82f6;
  --hf-violet: #7c3aed;
  --hf-gray-50: #f9fafb;
  --hf-gray-100: #f3f4f6;
  --hf-gray-200: #e5e7eb;
  --hf-gray-300: #d1d5db;
  --hf-gray-400: #9ca3af;
  --hf-gray-500: #6b7280;
  --hf-gray-700: #374151;
  --hf-gray-850: #141c2e;
  --hf-gray-925: #101623;
  --hf-gray-950: #0b0f19;
  --hf-canvas: var(--hf-gray-50);
  --hf-surface: #fff;
  --hf-surface-soft: var(--hf-gray-50);
  --hf-line: var(--hf-gray-200);
  --hf-text: #111827;
  --hf-muted: var(--hf-gray-500);
  --dispatch-accent: #b45309;
  --dispatch-live: #10b981;
  --dispatch-panel: var(--hf-surface-soft);
  min-height: 800px;
  padding: 24px;
  background: var(--hf-canvas);
  color: var(--hf-text);
  font-family: "Source Sans 3", "Source Sans Pro", ui-sans-serif, system-ui, sans-serif;
}
.dark .hf-design {
  --hf-canvas: var(--hf-gray-950);
  --hf-surface: var(--hf-gray-925);
  --hf-surface-soft: var(--hf-gray-850);
  --hf-line: #263044;
  --hf-text: #e5e7eb;
  --hf-muted: #9ca3af;
  --dispatch-accent: #fbbf24;
  --dispatch-live: #34d399;
}
.hf-design .dispatch-sheet {
  width: min(100%, 920px);
  height: 800px;
  border-color: var(--hf-line);
  border-radius: 14px;
  background: var(--hf-surface);
  box-shadow: 0 1px 2px rgb(15 23 42 / .04), 0 10px 32px rgb(15 23 42 / .08);
}
.dark .hf-design .dispatch-sheet {
  box-shadow: 0 18px 50px rgb(0 0 0 / .28);
}
.hf-design .dispatch-header {
  padding: 22px 30px 18px;
}
.hf-design .dispatch-body {
  padding: 0 30px;
}
.hf-design .dispatch-footer-log {
  padding-right: 30px;
  padding-left: 30px;
}
.hf-design .dispatch-session {
  padding-right: 30px;
  padding-left: 30px;
}
.hf-design .dispatch-kicker,
.hf-design .dispatch-section-label,
.hf-design .dispatch-time,
.hf-design .dispatch-source,
.hf-design .dispatch-meta,
.hf-design .dispatch-log-line,
.hf-design .dispatch-query-toggle,
.hf-design .dispatch-status,
.hf-design .dispatch-stat,
.hf-design .dispatch-trace,
.hf-design .dispatch-log-toggle-button {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
.hf-brand {
  min-width: 0;
  flex: none;
  align-items: center;
}
.hf-brand-logo {
  width: 32px;
  height: 30px;
  flex: none;
  object-fit: contain;
}
.hf-brand-copy {
  min-width: 0;
}
.hf-brand-name {
  color: var(--hf-text);
  font-size: 16px;
  font-weight: 700;
  line-height: 1;
}
.hf-brand-product {
  margin-top: 4px;
  color: var(--hf-muted);
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 9px;
  letter-spacing: .09em;
  line-height: 1;
  text-transform: uppercase;
}
.hf-design .dispatch-controls {
  gap: 10px;
}
.hf-design .dispatch-stat {
  color: var(--hf-muted);
  font-size: 10px;
  letter-spacing: 0;
  text-transform: none;
}
.hf-design .dispatch-control-divider {
  background: var(--hf-line);
}
.hf-design .dispatch-status {
  min-height: 26px;
  border: 1px solid transparent;
  border-radius: 7px;
  font-weight: 600;
  letter-spacing: 0;
}
.hf-design .dispatch-status-running {
  border-color: #fde68a;
  background: #fffbeb;
  color: #92400e;
}
.dark .hf-design .dispatch-status-running {
  border-color: rgb(245 158 11 / .28);
  background: rgb(245 158 11 / .12);
  color: #fbbf24;
}
.hf-design .dispatch-status-complete {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #047857;
}
.dark .hf-design .dispatch-status-complete {
  border-color: rgb(16 185 129 / .28);
  background: rgb(16 185 129 / .12);
  color: #34d399;
}
.hf-design .dispatch-status-failed {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}
.dark .hf-design .dispatch-status-failed {
  border-color: rgb(239 68 68 / .28);
  background: rgb(239 68 68 / .12);
  color: #fca5a5;
}
.hf-design .dispatch-header-separator,
.hf-design .dispatch-event,
.hf-design .dispatch-footer {
  border-color: var(--hf-line);
}
.hf-design .dispatch-section-label {
  color: var(--hf-muted);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .08em;
}
.hf-design .dispatch-headline,
.hf-design .dispatch-query,
.hf-design .dispatch-report-card-title,
.hf-design .dispatch-report-card-copy,
.hf-design .dispatch-current-copy,
.hf-design .dispatch-event-message {
  font-family: "Source Sans 3", "Source Sans Pro", ui-sans-serif, system-ui, sans-serif;
}
.hf-design .dispatch-headline {
  color: var(--hf-text);
  font-size: clamp(26px, 4vw, 34px);
  font-weight: 700;
  letter-spacing: -.025em;
}
.hf-design .dispatch-query {
  color: var(--hf-muted);
  font-size: 14px;
}
.hf-design .dispatch-report-card,
.hf-design .dispatch-markdown-report,
.hf-design .dispatch-log {
  border-color: var(--hf-line);
  background: var(--hf-surface-soft);
}
.hf-design .dispatch-report-card {
  border-radius: 11px;
}
.hf-design .dispatch-report-card-title {
  color: var(--hf-text);
  font-weight: 600;
}
.hf-design .dispatch-report-card-copy,
.hf-design .dispatch-time,
.hf-design .dispatch-log-line,
.hf-design .dispatch-trace,
.hf-design .dispatch-meta {
  color: var(--hf-muted);
}
.hf-design .dispatch-current-copy {
  color: var(--hf-text);
  font-size: 20px;
  font-weight: 400;
}
.hf-design .dispatch-event-message {
  color: var(--hf-text);
}
.hf-design .dispatch-source {
  font-weight: 600;
}
.hf-design .dispatch-rule {
  background: var(--hf-line);
}
.hf-design .dispatch-footer {
  background: var(--hf-surface);
}
.hf-design .dispatch-log-toggle-button {
  color: var(--hf-muted);
}

/* Option A: closest to the neutral Hub list and profile surfaces. */
.hf-hub-classic {
  background:
    linear-gradient(180deg, var(--hf-surface) 0 68px, var(--hf-canvas) 68px);
}
.hf-hub-classic .dispatch-sheet {
  border-radius: 12px;
}
.hf-hub-classic .dispatch-header {
  border-top: 3px solid var(--hf-yellow);
}
.hf-hub-classic .dispatch-current-block {
  margin-top: 20px;
  padding: 18px;
  border: 1px solid var(--hf-line);
  border-radius: 11px;
  background: var(--hf-surface);
  box-shadow: 0 1px 3px rgb(15 23 42 / .05);
}
.hf-hub-classic .dispatch-history {
  margin-top: 18px;
}
.hf-hub-classic .dispatch-report-card {
  background: linear-gradient(135deg, var(--hf-surface), var(--hf-surface-soft));
  box-shadow: 0 1px 3px rgb(15 23 42 / .04);
}
.hf-hub-classic .dispatch-report-action {
  border-color: var(--hf-line);
  background: var(--hf-surface);
  color: var(--hf-text);
}

/* Option B: borrows the colorful featured-card language from Spaces. */
.hf-spaces-gradient {
  --dispatch-accent: #7c3aed;
  background:
    radial-gradient(circle at 15% 15%, rgb(255 210 30 / .14), transparent 28%),
    radial-gradient(circle at 85% 5%, rgb(99 102 241 / .16), transparent 30%),
    var(--hf-canvas);
}
.dark .hf-spaces-gradient {
  --dispatch-accent: #c4b5fd;
}
.hf-spaces-gradient .dispatch-sheet {
  overflow: hidden;
  border-color: rgb(99 102 241 / .22);
  border-radius: 20px;
}
.hf-spaces-gradient .dispatch-header {
  position: relative;
  background:
    linear-gradient(135deg, rgb(255 210 30 / .12), rgb(99 102 241 / .10) 55%, rgb(236 72 153 / .08));
}
.dark .hf-spaces-gradient .dispatch-header {
  background:
    linear-gradient(135deg, rgb(245 158 11 / .12), rgb(79 70 229 / .18) 55%, rgb(190 24 93 / .12));
}
.hf-spaces-gradient .dispatch-header::after {
  content: "";
  position: absolute;
  right: -50px;
  bottom: -80px;
  width: 180px;
  height: 180px;
  border: 28px solid rgb(255 210 30 / .16);
  border-radius: 999px;
  pointer-events: none;
}
.hf-spaces-gradient .dispatch-current-block {
  margin-top: 22px;
  padding: 22px;
  overflow: hidden;
  border-radius: 15px;
  background: linear-gradient(135deg, #34469b, #4f46e5 52%, #7c3aed);
  box-shadow: 0 12px 28px rgb(79 70 229 / .22);
}
.hf-spaces-gradient .dispatch-current-block .dispatch-time,
.hf-spaces-gradient .dispatch-current-block .dispatch-source,
.hf-spaces-gradient .dispatch-current-block .dispatch-current-copy {
  color: #fff;
}
.hf-spaces-gradient .dispatch-current-block .dispatch-time {
  opacity: .7;
}
.hf-spaces-gradient .dispatch-current-block .dispatch-live-dot {
  background: var(--hf-yellow);
}
.hf-spaces-gradient .dispatch-current-block .dispatch-rule {
  background: rgb(255 255 255 / .25);
}
.hf-spaces-gradient .dispatch-current-block .dispatch-rule-running::after,
.hf-spaces-gradient .dispatch-current-block .dispatch-rule-completed {
  background: var(--hf-yellow);
}
.hf-spaces-gradient .dispatch-report-card {
  border: 0;
  background: linear-gradient(145deg, #34469b, #4f46e5);
  color: #fff;
  box-shadow: 0 8px 20px rgb(59 70 155 / .18);
}
.hf-spaces-gradient .dispatch-report-card:nth-child(2) {
  background: linear-gradient(145deg, #6634b8, #c02675);
}
.hf-spaces-gradient .dispatch-report-card .dispatch-section-label,
.hf-spaces-gradient .dispatch-report-card-title,
.hf-spaces-gradient .dispatch-report-card-copy {
  color: #fff;
}
.hf-spaces-gradient .dispatch-report-card .dispatch-section-label,
.hf-spaces-gradient .dispatch-report-card-copy {
  opacity: .78;
}
.hf-spaces-gradient .dispatch-report-action {
  border-color: rgb(255 255 255 / .32);
  background: rgb(255 255 255 / .10);
  color: #fff;
}

/* Option C: a compact, structured workspace inspired by dataset browsing. */
.hf-dataset-studio {
  --dispatch-accent: #2563eb;
  padding: 0;
  background: var(--hf-surface);
}
.dark .hf-dataset-studio {
  --dispatch-accent: #60a5fa;
}
.hf-dataset-studio .dispatch-sheet {
  width: min(100%, 1040px);
  height: 820px;
  border-radius: 0;
  box-shadow: none;
}
.hf-dataset-studio .dispatch-header {
  padding: 20px 28px 16px;
  border-bottom: 1px solid var(--hf-line);
  background: var(--hf-surface);
}
.hf-dataset-studio .dispatch-header-separator {
  display: none;
}
.hf-dataset-studio .dispatch-query-wrap {
  margin-top: 18px;
  padding: 18px 20px;
  border: 1px solid var(--hf-line);
  border-radius: 10px;
  background: var(--hf-surface-soft);
}
.hf-dataset-studio .dispatch-headline {
  font-size: clamp(23px, 3vw, 29px);
}
.hf-dataset-studio .dispatch-body {
  padding: 18px 28px;
  background:
    linear-gradient(90deg, var(--hf-surface-soft) 0 4px, transparent 4px);
}
.hf-dataset-studio .dispatch-report-grid {
  margin-top: 0;
}
.hf-dataset-studio .dispatch-report-card {
  border-radius: 8px;
  background: var(--hf-surface);
  box-shadow: 0 1px 3px rgb(15 23 42 / .05);
}
.hf-dataset-studio .dispatch-current-block {
  margin-top: 0;
  padding: 18px 18px 20px;
  border: 1px solid var(--hf-line);
  border-radius: 9px;
  background: var(--hf-surface);
}
.hf-dataset-studio .dispatch-current-meta {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--hf-line);
}
.hf-dataset-studio .dispatch-current {
  margin-top: 14px;
}
.hf-dataset-studio .dispatch-history {
  margin-top: 18px;
  padding: 16px 18px;
  border: 1px solid var(--hf-line);
  border-radius: 9px;
  background: var(--hf-surface);
}
.hf-dataset-studio .dispatch-event {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid var(--hf-line);
  border-radius: 7px;
  background: var(--hf-surface-soft);
  opacity: 1;
}
.hf-dataset-studio .dispatch-event + .dispatch-event {
  margin-top: 8px;
}
.hf-dataset-studio .dispatch-footer {
  background: var(--hf-surface-soft);
}

@media (max-width: 720px) {
  .hf-design {
    min-height: 800px;
    padding: 0;
  }
  .hf-design .dispatch-sheet {
    height: 800px;
    border-radius: 0;
  }
  .hf-design .dispatch-header {
    padding: 18px 18px 16px;
  }
  .hf-design .dispatch-body {
    padding-right: 18px;
    padding-left: 18px;
  }
  .hf-design .dispatch-footer-log,
  .hf-design .dispatch-session {
    padding-right: 18px;
    padding-left: 18px;
  }
  .hf-brand-name {
    font-size: 15px;
  }
  .hf-spaces-gradient .dispatch-current-block,
  .hf-hub-classic .dispatch-current-block {
    padding: 17px;
  }
  .hf-dataset-studio .dispatch-query-wrap {
    padding: 14px;
  }
}
"""


def design_css_class(design: HFDesign) -> str:
    return f"dispatch-app hf-design hf-{design}"


def validate_design(design: str) -> HFDesign:
    if design not in HF_DESIGNS:
        choices = ", ".join(HF_DESIGNS)
        raise ValueError(f"Unknown design {design!r}; expected one of: {choices}")
    return design  # type: ignore[return-value]
