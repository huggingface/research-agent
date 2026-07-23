Reference repositories:

fast-agent: ~/source/fast-agent/
prefect fastmcp: ~/source/fastmcp/
model context protocol: ~/

Design:
- Prefab source: `research/app_ui.py`; preview states: `design/preview_states.py`.
- Render production UI: `uv run --project ~/source/fast-agent --with prefab-ui==0.20.2 python scripts/render_app_preview.py --design hub-classic --state all`; inspect `.artifacts/app-preview/` (add `--mode dark` for dark mode).
- References live in `design/references/`; `.artifacts/` is generated.
