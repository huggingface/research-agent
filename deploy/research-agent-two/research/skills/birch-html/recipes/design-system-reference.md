# Recipe: Design-system reference / component specimen

Use when the artifact is a reference page, specimen sheet, component inventory,
variant matrix, token catalog, or visual-regression comparison for a design
system or component family.

Good fits include:

- "Create a reference page for this CSS file";
- "Show all supported Birch primitives";
- "Build a component variant matrix";
- "Compare this old design system to this new one";
- "Document the supported classes and data attributes";
- design-system overview pages;
- component variant galleries;
- token/specimen sheets for colors, type, spacing, radius, and chart palette;
- old-vs-new visual-system comparison reports;
- CSS parity or migration reference pages;
- component contract documentation for LLMs or implementers;
- checker/report specimen pages that show supported patterns and common
  violations;
- visual-regression triage pages that explain what changed, what to port, and
  what not to port.

This recipe is for documenting how a visual system works as a reference
artifact. Existing recipes do not cover that shape directly:

- `design-directions.md` is for choosing between options.
- `module-explainer.md` is for explaining code/source behavior.
- `numeric-data.md` is for metrics, charts, and quantitative briefs.

Prefer `design-directions.md` only when the main task is to compare strategic
options and recommend one.

## Important behavior

- Inspect CSS/source first; do not infer support from visual intuition or
  unrelated examples.
- Do not invent components, classes, variables, variants, or `data-*`
  attributes.
- Show real supported primitives from the inspected system, not aspirational
  examples.
- Produce a reference/specimen artifact, not a marketing page or generic
  dashboard.
- Organize for scanning and reference lookup, not narrative persuasion.
- Show both rendered examples and implementation details: class names, variables,
  supported `data-*` attributes, and short snippets.
- Include compact examples that demonstrate the primitive or variant without
  large filler content.
- Include misuse warnings for unsupported classes, invalid variants, fragile
  layout patterns, and common responsive failures.
- Distinguish supported, deprecated, legacy-only, experimental, and unsupported
  patterns.
- Prefer live HTML specimens built from Birch primitives over screenshots when
  possible.
- Keep examples small, composable, and faithful to the canonical system; do not
  invent variants to make the matrix look complete.
- Put misuse warnings next to the relevant primitive or variant.
- Make dense inventories mobile-safe with wrapping grids, wrapped code, and
  responsive tables.

## Required source checks

- Identify the canonical CSS, token files, component docs, example pages, and
  screenshots or legacy pages that define the system.
- Confirm which classes, data attributes, variables, tones, densities, and
  states are actually supported.
- Separate canonical implementation from examples, experimental aliases, and
  deprecated or legacy-only classes.
- Capture visual-regression intent when present: old vs new, ported vs not
  ported, changed semantics, and known gaps.
- Preserve exact class names, `data-*` attributes, token names, and snippet
  markup for implementation references.

## Recommended structure

1. Header that states the reference purpose and scope: "Birch component specimen",
   "Birchline-to-Birch parity map", or "Checker report visual vocabulary".
2. System summary: supported tone, typography, density, layout principles, and
   non-goals.
3. Token specimens: colors, semantic variables, typography, spacing, radius,
   border, elevation, and chart palette when relevant.
4. Component inventory: cards, chips, badges, callouts, buttons, tables,
   code/diff blocks, flow steps, chart panels, and other supported primitives.
5. Variant matrix: tones, states, density, emphasis, and responsive behavior.
6. Implementation reference: canonical class names, supported `data-*`
   attributes, example snippets, and common misuse warnings.
7. Optional visual-regression/comparison section: what changed, what to port,
   what not to port, and remaining verification gaps.

## Birch primitives to use

- `.section`, `.section-head`, `.section-rail`, `.stack`, `.cluster`, `.grid`,
  and `.auto-grid` for the reference layout.
- `.card`, `.panel`, `.callout`, `.chip`, `.badge`, `.button`, `.btn`,
  `.stat-card`, `.reference-panel`, `.code-block`, `.diff`, `.flow-list`,
  `.flow-step`, `.chart-panel`, and `.numeric-table` as live specimens.
- `.numeric-table-wrap` and `.numeric-table` for token or variant matrices.
- `.code-block[data-wrap="true"]` for class names, snippets, and misuse examples.
- `.plain-list` for inventories and caveats; `.checklist` only for validated
  support claims.

Use small page-local CSS only for specimen swatches or demo-only wrappers, and
place it after the canonical Birch CSS. Keep swatch CSS concrete and restrained;
do not define a parallel theme.

## Specimen guidance

- Show tokens as named specimens with the exact variable and semantic purpose.
- Use live component markup where possible instead of screenshots.
- Put implementation snippets next to the rendered specimen they describe.
- Mark unsupported, legacy-only, or intentionally unported patterns clearly.
- Show do/don't examples only when they teach a concrete class, variable, or
  responsive-safety rule.
- Include mobile/wrapping considerations for tables, code, diffs, long paths,
  and dense component grids.

## Visual-regression / migration guidance

When comparing systems or versions:

- state the baseline and candidate source paths;
- separate visual differences from contract violations;
- identify classes or tokens to port, alias, reject, or document;
- cite checker output or screenshot evidence when available;
- avoid implying pixel parity when the goal is system-faithful migration.

## Avoid

- Inventing components, variants, tokens, or `data-*` attributes not present in
  the canonical CSS/docs.
- Treating a reference page as a marketing landing page with little
  implementation detail.
- Copying legacy classes into Birch examples unless they are explicitly supported
  or intentionally shown as "do not port".
- Dense specimen grids that overflow on mobile.
- Using screenshots where live semantic markup would be clearer and more
  inspectable.

## Validation checklist

- Canonical source files and scope are named.
- Token and component specimens use supported classes and variables.
- Variant matrices distinguish supported, deprecated, and unsupported states.
- Snippets are short, exact, and adjacent to their rendered specimens.
- Common misuse warnings are concrete.
- Mobile wrapping/overflow risks are addressed.
