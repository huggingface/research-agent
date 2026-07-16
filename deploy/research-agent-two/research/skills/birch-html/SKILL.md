---
name: birch-html
description: >
  Use this skill when the user wants a polished, shareable, source-grounded,
  self-contained HTML artifact in the Birch visual system for engineering,
  product, planning, review, status, incident, process, codebase, data, or
  benchmark communication. Trigger for one-pagers, visual summaries, reports,
  dashboards, module/process explainers, implementation plans, design-direction
  comparisons, PR/change writeups, findings-first code reviews, incident/status
  reports, briefing decks, flow diagrams, numeric/data briefs, model/run/token/
  time/cost reports, and design-system references. Do not use it for editing
  production web apps, React/Vue components, or ordinary chat answers.
---

# Birch HTML

Create one complete, locally opening Birch HTML artifact. Optimize for complete
HTML, preserved Birch CSS placeholder, source-grounded claims, 390px mobile
safety, strict component contracts, and minimal page-local CSS.

## Output contract

- Return a full HTML document only: no prose, Markdown fences, or partial HTML.
- If writing to disk, validate and return only the artifact path.
- Keep the placeholder exactly until postprocessing:
  `<style data-birch-system>__BIRCH_SYSTEM_CSS__</style>`.
- Do not paste bundled Birch CSS or modify canonical CSS/scripts/resources.
- No network assets: no remote URLs, CDNs, fonts, iframes, images, scripts, or styles.
- Use `<main class="page stack" data-gap="lg">` as the outer visible shell.
- Do not replace the Birch shell with a custom app/dashboard shell. Do not make
  `body`, `.container`, `.report`, or `.dashboard` the visible page shell.
- Do not invent Birch classes/CSS variables or use Birchline-only classes. In
  particular, avoid custom path/helper classes such as `.file-path` and avoid
  variables such as `--color-*`, `--size-*`, `--s-*`, `--bg-alt`, or
  `--fg-muted` unless they are already defined by Birch.
- Use flat token surfaces only: no gradients, glassmorphism, glow backgrounds,
  decorative background images, or custom dashboard skins.
- Birch style forbids gradients for card, panel, page, and callout backgrounds
  and for body/page backgrounds (for example `linear-gradient`,
  `radial-gradient`, or `conic-gradient`). Use flat Birch token surfaces instead.
- For diffs, never paste raw unified-diff text into `<pre>` or code blocks.
  Represent patch lines with `.diff-row`; the only literal `+`/`-` marker should
  be inside `<span class="mark">`.

## Workflow

1. Read sources first: files, diffs, data, logs, commands, screenshots, session
   notes, and local links before writing claims.
2. Make a terse brief: audience, purpose, exact paths/values, caveats, unknowns,
   sections, and chart intent.
3. Ask only if missing audience, scope, sources, or output path would materially
   change the result; otherwise proceed and label assumptions.
4. Load only needed recipes: `numeric-data`, `code-review`, `pr-change-writeup`,
   `implementation-plan`, `module-explainer`, `process-explainer`,
   `design-directions`, `status-incident-report`, `flow-diagram`, `slide-deck`,
   `benchmark-comparison`, or `design-system-reference`.
5. If no path is specified and filesystem access exists, write a descriptive
   kebab-case `.html` file in the current directory.
6. Prefer copying `skill/resources/template.html`; replace body content only.
   Then run `uv run skill/scripts/finish_birch_html.py <output.html>`.
7. Validate before returning: doctype, html/head/body, viewport, title, `.page`,
   Birch CSS placeholder/embedded CSS, closing `</html>`, no network assets, no
   unknown classes/variables, strict children, wrapped long content, no 390px
   overflow, and no raw patch marker lines. If available run:
   `uv run --with pillow python skill/scripts/check_birch_renderings.py --artifact <output.html>`.

## Required shell

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Clear artifact title</title>
  <style data-birch-system>__BIRCH_SYSTEM_CSS__</style>
  <style>/* Optional tiny wrapping/SVG fixes only. Prefer deleted. */</style>
</head>
<body>
  <main class="page stack" data-gap="lg">
    <header class="stack" data-gap="sm">
      <div class="eyebrow">Review artifact</div>
      <h1>Clear artifact title</h1>
      <p class="lede">One or two source-grounded sentences.</p>
    </header>
    <section class="section stack" data-gap="lg">...</section>
  </main>
</body>
</html>
```

## Grounding

- Put exact values, file paths, commands, caveats, and verification evidence near
  the claim they support.
- Use neutral uncertainty language: “observed”, “suggests”, “not verified”,
  “source not present”.
- Do not claim performance, risk, ownership, intent, or causality without source
  support. Label assumptions.
- Prefer captions citing paths/functions over broad narrative.

## Birch primitives and local CSS

Build with primitives, not custom boxes: `.section`, `.section-head`, `.stack`,
`.cluster`, `.card`, `.panel`, `.auto-grid`, `.section-rail`,
`.reference-panel`, `.chart-panel`, `.chart-svg`, `.chart-caption`,
`.stat-card`, `.stat-value`, `.metric-list`, `.metric-row`,
`.numeric-table-wrap`, `.numeric-table`, `.flow-list`, `.flow-step`,
`.code-block`, `.diff`, `.checklist`, `.plain-list`, `.insight-list`,
`.takeaway-list`, `.chip`, `.caption`, `.lede`, `.scroll-x`.
Use semantic primitives in every artifact: sections plus cards, lists, tables,
flow steps, diff rows, metric lists, or chart panels as relevant.

Page-local CSS: ideally none; hard target under 30 lines / 1.5 KB. Use it only
for page-specific SVG sizing, chart sizing, tiny gaps, or wrapping. Do not
recreate shells/cards/grids/rails/tables/typography/badges/meters, redefine
Birch primitives, or use `linear-gradient`, `radial-gradient`, or
`conic-gradient`. Put local CSS after the Birch placeholder/link. Use only
Birch variables (`--bg`, `--surface`, `--text`, `--border-color`, `--accent`,
`--success`, `--danger`, `--info`, `--space-1`…`--space-8`, and documented
color tokens).

## Mobile safety

Design for 390px. Rows, chips, stat values, code, tables, and SVGs must wrap or
scroll inside their own container without page-level horizontal overflow.

- If prose/list text wraps to one or two words per line in a wide card, remove
  custom grid/flex and stack it.
- Long paths, commands, hashes, identifiers, URLs, diff lines, numeric notes, and
  symbols must wrap or live inside `.scroll-x`.
- Use `data-wrap="true"` on every long `.code-block` and `.diff`.
- Do not use long paths/identifiers as headings; put them in captions, prose,
  `<code>`, wrapped blocks, or short chips.
- Keep chips and `<h1>` short; move long nouns to lede/captions.
- Numeric tables always use
  `<div class="numeric-table-wrap"><table class="numeric-table">...</table></div>`.
- Keep numeric tables to 3–5 columns. Split wide data into smaller tables plus
  KPI cards. Avoid all-in-one tables with long prose cells.
- If table cells contain paths, notes, code, commands, or long labels, add:
  `.numeric-table code, .numeric-table .note { white-space: normal; overflow-wrap: anywhere; word-break: break-word; }`
- Never put long paths, excerpts, or prose-heavy evidence in narrow table
  columns unless the table is wrapped and those cells can break anywhere; prefer
  stacked cards, lists, or `.code-block data-wrap="true"` for code-review
  evidence.
- Use `.scroll-x` only for truly wide comparisons; otherwise reduce columns.
- In side rails, avoid long `.metric-row` values; prefer KPI cards, lists, or
  compact metric CSS vars.

## Layout rules

- Prefer `.section-rail`: main content first, then `<aside class="reference-panel">`.
- Avoid `.split` for plans, source-vs-assumption blocks, or columns with headings
  on both sides; use `.section-rail` or stacked cards.
- KPI strips use `.auto-grid` with `style="--grid-min: 160px"`.
- Keep side rails short: caveats, sources, compact KPIs only.
- Numeric/data artifacts must show evidence in the first desktop viewport:
  compact hero, KPI strip, and chart/ranking/table start.
- Numeric/data and benchmark pages need KPI cards or valid metric rows, a chart
  or ranking, a numeric table, and source/caveat captions.

## Strict components

### Diff rows

Never put raw patch text directly in HTML source or code blocks. No generated
source line may begin with `+`, `-`, or `@@` to represent a patch. Use
`.diff-row` with exactly three direct children: `.ln`, `.mark`, `.code`; mark
text is `+`, `-`, or one space; added rows use `.add`/`data-kind="add"`,
deleted rows use `.del`/`data-kind="del"`.

```html
<div class="diff" data-wrap="true">
  <div class="diff-row add"><span class="ln">12</span><span class="mark">+</span><span class="code">added code</span></div>
</div>
```

### Flow steps

Every `.flow-step` has exactly two direct children: `.flow-num`, then one
content wrapper. Put titles, paragraphs, lists, and code inside the wrapper.

```html
<li class="flow-step"><span class="flow-num">1</span><div class="stack" data-gap="sm"><h3 class="flow-title">Read inputs</h3><p class="flow-detail">Detail.</p></div></li>
```

### Metric rows

Use `.metric-row` only for label + meter + short value; not for metadata,
timelines, work items, prose, or key/value rows. It has exactly three direct
children: `.caption`, `.meter`, `code`. Do not add extra children or `.metric`
inside `.metric-row`. Long labels/values belong in cards, lists, or tables.

```html
<div class="metric-row"><span class="caption">Pass rate</span><div class="meter"><span style="--value: 98%"></span></div><code>0.98</code></div>
```

### Lists and tables

- `.checklist`: pass/done/validated items only; `.plain-list`: neutral bullets;
  `.insight-list`/`.takeaway-list`: key observations.
- In insight/takeaway lists, each `<li>` has exactly one direct wrapper child.
- Numeric `<th>` and `<td>` cells need `class="metric"` so headers and values align.
- Use short table headers; explain long meanings in captions.

## SVG, charts, and reports

- Put inline SVG inside `.panel.chart-panel.stack`; usually wrap the SVG with
  `.chart-svg` and add `.chart-caption`.
- Keep SVG text short, away from right edges; leave viewBox margin or move labels
  to captions/lists.
- Tiny hand-written SVG: 5–8 nodes max. Every data `path`/`polyline` sets
  `fill="none"`, a Birch-colored `stroke`, and restrained `stroke-width`.
- If SVG labels risk 390px overflow, stack vertically or use numbered nodes plus
  a following `.flow-list`.
- For real plotted data, prefer Python-generated inline SVG using
  `scripts/birch_mpl.py`; run a temporary driver as needed, inline SVG in a
  chart panel, and pair with exact values in narrow `.numeric-table`s.

## Artifact patterns

Module/runtime explainers: short transformation title, caveat paragraph, SVG
flow of 5–8 nodes, caption citing source files/functions, then ordered
`.flow-list` file tour or runtime walkthrough. Prefer flow steps, cards, and
captions over dense tables.

Numeric/benchmark reports: inspect schema and rows; use KPI cards for headline
counts/totals/best/worst/pass/fail/cost/time; use valid `.metric-list` only for
true progress/ranking values; include charts when they clarify tradeoffs; pair
charts with exact values and source/caveat captions.
