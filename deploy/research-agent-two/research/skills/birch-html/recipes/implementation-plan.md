# Recipe: Implementation plan

Use when the user asks for a sequenced plan to build, migrate, refactor, or verify a system.

## Required source checks

- Use only facts present in the provided source. Label anything else `Assumption` or `Open question`.
- Extract confirmed requirements, constraints, non-goals, dependencies, interfaces, data contracts, owners, external systems, test data, observability, and rollback needs.
- Separate mandatory order from work that can run in parallel.
- Define measurable entry criteria, exit criteria, and verification for every milestone.

## Required HTML behavior

- Return one complete HTML document only. No prose before/after. No Markdown fences.
- Preserve the canonical Birch CSS placeholder exactly as required by the skill shell; do not replace it with custom framework CSS.
- Use `<main class="page">` as the outer page shell unless the base skill template already supplies it.
- Prefer Birch primitives over page-local CSS. Keep page-local CSS minimal and only for content-specific wrapping/tiny tweaks.
- Do not add external fonts, icons, images, scripts, CDN links, or network assets.
- Do not invent classes, CSS variables, or Birchline-only names.
- Do not use gradients or decorative background effects; Birch implementation
  plans use flat token surfaces, borders, and normal document hierarchy.

## Recommended structure

1. Hero/summary card: goal, scope, source basis, and decision state. Keep the
   title short. Do not add local `.hero h1` typography; if local CSS is required,
   keep heading `line-height >= 1.1`, allow wrapping, and never clip headings.
2. Confirmed vs assumed inputs in a `.callout` group or compact table.
3. Milestone flow with entry criteria, work, exit criteria, verification, rollback, and observability.
4. Interface/data contract table where boundaries matter.
5. Parallel work, risks, mitigations, owner questions, and final validation plan.

## Birch primitives to use

- `.flow-list` for ordered phases and dependencies.
  Each `.flow-step` must contain exactly:
  - one `.flow-num`
  - one content wrapper, usually `<div class="stack" data-gap="sm">...</div>`
  Put all title, purpose, work, exit criteria, lists, tables, and code inside the content wrapper. Never place prose beside or after the wrapper.
- `.timeline` only when calendar chronology matters.
- `.numeric-table` or a regular table for contracts, owners, verification, and status.
- `.callout`, `.checklist`, and `.plain-list` for assumptions, tests, risks, non-goals, and questions.
- Prefer `.section-rail` when the main content comes first and the aside/source rail comes second. Put one full-width `.section-head` before the rail; do not use `.split` for paired headings in implementation plans.
- Use `.code-block[data-wrap="true"]` for long commands, paths, config keys,
  diffs, IDs, URLs, formulas, or source excerpts. For short inline tokens inside
  tables, wrap them in `<code>` and add a tiny local rule only when needed:
  `.numeric-table code { white-space: normal; overflow-wrap: anywhere; word-break: break-word; }`.

## Mobile-safe rules

- Long tokens must wrap: paths, commands, filenames, API names, IDs, code, diff
  lines, URLs, formulas, and numeric expressions go in `.code-block[data-wrap="true"]`
  or inside table cells that explicitly allow wrapping.
- Avoid wide multi-column layouts for dense content. Prefer stacked cards, `.flow-list`, `.section-rail`, and short tables. Avoid `.split` for confirmed-vs-assumed, before-vs-after, risks-vs-questions, or other heading-paired sections.
- Keep table cell text short. If a cell needs long code/path text, prefer moving
  the value to a wrapped `.code-block[data-wrap="true"]`; if it must stay in a
  `.numeric-table`, use short `<code>` plus the wrapping local rule above.
- Do not put long headings or paragraphs inside narrow split/aside columns. For two related lists, use two `.card` elements in `.auto-grid` or stacked `.section` blocks rather than `.split`.
- Do not build custom checklist/list grids with separate icon columns. Use
  Birch `.checklist` as-is, or `.plain-list`. Sentence text must not wrap into a
  skinny vertical strip inside a wide card.
- Avoid fixed widths, absolute positioning, `white-space: nowrap`, and large page-local grids.

## Source-grounding rules

- Mark each important claim as `Confirmed`, `Assumption`, or `Open question`.
- If source material is incomplete, say what is unknown instead of filling gaps.
- Do not create owners, dates, metrics, APIs, or dependencies unless present in source.
- Non-goals must prevent scope creep and must be traceable to source or clearly labeled as assumptions.

## Avoid

- Prose or Markdown instead of a complete HTML artifact.
- Omitting the Birch page shell or CSS placeholder.
- Large page-local CSS blocks or recreated Birch components.
- Gradient cards, custom hero backgrounds, or non-Birch decorative surfaces.
- Presenting guesses as requirements.
- Sequencing everything linearly when tasks can run in parallel.
- Putting an aside/reference panel in the wide first column of `.section-rail`.
- Using `.split` for paired headings; it commonly creates mobile alignment warnings.
- Omitting rollback, test data, observability, or measurable exit criteria for risky changes.
- Malformed `.flow-step` children, nested list/table tags, or bare long `<code>` in tables.

## Validation checklist

- Complete HTML document, canonical Birch shell, no external assets.
- Confirmed facts, assumptions, and open questions are visibly separated.
- Every phase has entry criteria, work, exit criteria, verification, rollback/observability when relevant.
- Mandatory dependencies and parallelizable work are distinguished.
- Interface contracts and dependencies are explicit.
- Long tokens wrap on mobile; no bare long code/path/formula text.
- Normal prose/list text uses the available card width; no one-word/few-character vertical wrapping.
- Risks have mitigations or owner questions.
- Non-goals prevent scope creep.
