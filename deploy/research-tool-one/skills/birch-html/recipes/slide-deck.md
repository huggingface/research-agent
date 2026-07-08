# Recipe: Slide-style narrative

Use when the user asks for a presentation-like artifact, executive narrative, or section-by-section walkthrough.

## Required source checks

- Identify audience, decision, core claims, and supporting evidence.
- Put one claim per section and make the evidence for that claim visible.
- Preserve caveats and unknowns rather than smoothing them away.
- Confirm whether the output should be read on screen, exported, or used as speaker notes.

## Recommended structure

1. Title section with audience, purpose, and takeaway.
2. Repeated `.section.panel` blocks, each with one claim and supporting bullets or evidence.
3. Optional summary section with decision, next step, or ask.
4. Appendix/source notes only when useful.

## Birch primitives to use

- `.page[data-size="wide"]` for presentation-style width.
- `.section.panel` for each scrollable section.
- `.stack`, `.cluster`, `.grid`, `.auto-grid`, `.card` for layout.
- `.stat-card`, `.numeric-table`, `.code-block`, or `.callout` when the claim needs evidence.

## Avoid

- Custom presentation CSS unless the artifact truly needs it.
- Multiple unrelated claims in one section.
- Tiny text, dense tables, or decorative-only visuals.
- Unsupported presentation-specific class names.

## Validation checklist

- Each section has one clear claim.
- Whitespace and type scale remain generous.
- Evidence is close to the claim.
- The artifact scrolls naturally and remains readable on mobile.
