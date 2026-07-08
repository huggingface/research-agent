# Recipe: Code review

Use for a diff, patch, PR, or source change review.

## Non-negotiables

- Return one complete HTML document only: `<!doctype html>`, `<html>`, `<head>`, `<body>`.
- Preserve the Birch shell and canonical CSS placeholder exactly as required by `SKILL.md`; do not paste Birch CSS, checker CSS, external assets, or CDN links.
- Inspect the supplied source/diff before writing claims.
- Findings must be source-grounded. If the source does not prove it, label it as a question or residual risk.
- Do not claim tests pass unless the source/user explicitly says so.
- Keep page-local CSS tiny: only page-specific glue; prefer Birch primitives over custom classes.

## Review workflow

1. Identify changed files, touched functions, behavior paths, deleted guards, and tests.
2. Put blocking findings first, ordered by severity.
3. For each finding include: severity, location, impact, evidence, fix.
4. If no blocking findings exist, say so explicitly before notes.
5. End with reviewer checklist and residual risk/open questions.

## Required Birch structure

- Use canonical finding cards:
  `<article class="card stack finding" data-severity="high">`.
  Supported severities: `blocker`, `high`, `medium`, `low`.
- Do not write CSS for `.finding`, `[data-severity]`, `.card[data-tone]`, or
  `.panel[data-tone]`; Birch already provides flat severity borders and badge
  tones. Never use gradients for finding/severity backgrounds.
- Use `.badge` with `data-tone="danger|warning|success|info"` for severity/state.
- Use `.callout` for the top verdict or no-findings statement.
- Use `.plain-list` for evidence, caveats, and open questions.
- Use `.checklist` for reviewer actions.
- Use `.diff[data-wrap="true"]` for diff evidence.
- Use `.code-block[data-wrap="true"]` for long code, paths, stack traces, JSON, or logs.
- Use `.metric-list` / `.metric-row` only for short labels and short values; avoid long paths or sentences inside metric values.
- Avoid prose-heavy evidence tables. They frequently create narrow columns and
  one-character-per-line wrapping. Prefer one card per finding with short
  location captions plus wrapped `.code-block` or strict `.diff-row` evidence.

## Exact child contracts

- Diff markup:
  - Parent: `<div class="diff" data-wrap="true">`
  - Rows must have exactly three direct children:
    `<div class="diff-row add"><span class="ln">12</span><span class="mark">+</span><span class="code">added code</span></div>`.
  - Every added `+` row needs `.add` or `data-kind="add"`.
  - Every deleted `-` row needs `.del` or `data-kind="del"`.
  - Never put loose text directly in `.diff-row`; it renders as extra grid
    children and wraps pathologically.
- Checklist markup:
  - Parent: `<ul class="checklist">`
  - Items: `<li>...</li>` only.
- Plain lists:
  - Parent: `<ul class="plain-list">`
  - Items: `<li>...</li>` only.
- Do not use Birchline-only classes or invented Birch variants.

## Mobile safety

- Wrap all long evidence: use `.diff[data-wrap="true"]` or `.code-block[data-wrap="true"]`.
- Break long paths, identifiers, hashes, URLs, and numbers with `<wbr>` or wrap containers.
- Keep tables rare. If needed, use short cells and the Birch responsive table
  wrapper from `SKILL.md`; do not use tables for long code excerpts or long
  location/prose cells.
- Avoid fixed widths, large grids, absolute positioning, and custom rail layouts.
- Do not put long values in `.metric-row`; use a wrapped code block or list item instead.

## Local CSS limit

- Prefer zero page-local CSS.
- If needed, keep it under ~40 lines and only set spacing or `overflow-wrap:anywhere` on page-specific wrappers.
- Do not restyle Birch primitives, redefine CSS variables, duplicate canonical CSS, or add component systems.
- Do not create local finding/severity/tone systems; use `.finding`,
  `data-severity`, and `.badge[data-tone]`.

## Avoid

- Prose or Markdown fences instead of HTML.
- Burying findings under praise/background.
- Inventing file, function, line, test, or runtime facts.
- Treating style nits as correctness findings.
- Long unwrapped code/diff excerpts.
- Neutral-colored added/deleted diff rows.
- Unsupported classes, network fonts, scripts, images, or relative CSS files.

## Final validation

- Complete HTML document only.
- Birch CSS placeholder/page shell preserved.
- Findings/no-findings statement appears before background.
- Every issue has severity, location, impact, evidence, and fix.
- Evidence cites source-provided file/function/line when available.
- Long code, diffs, paths, and logs wrap on mobile.
- Added/deleted diff rows have polarity classes or `data-kind`.
- Page-local CSS is minimal and no unsupported classes/assets appear.
