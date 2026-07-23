# Design references

This directory contains curated, reviewable inputs for UI design work.

## `baseline/`

Screenshots of the current implementation, captured on 2026-07-23 from the
working tree with `scripts/render_app_preview.py`.

- `desktop/`: 1000 × 900
- `mobile/`: 430 × 900

The four screenshots in each directory cover the running, completed, failed,
and cancelled states. Regenerate previews under `.artifacts/` first, then
replace these PNGs deliberately when establishing a new baseline.

## `handoff/`

The supplied Broadsheet design handoff:

- interactive HTML and its companion document
- reference screenshots for running, complete, error, and cancelled states

These files are source references, not generated application output. Preserve
them while implementing or reviewing the design update.

## Generated previews

`.artifacts/app-preview/` is disposable and ignored by Git. Generate previews
there with:

```bash
uv run --project ../fast-agent --with 'fastmcp[apps]' \
  --with prefab-ui python scripts/render_app_preview.py --state all
```
