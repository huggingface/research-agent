# Recipe: Module explainer

Use when explaining how a code module, subsystem, package, or runtime path works.

## Required source checks

- Inspect source files before writing the mental model.
- Identify entry points, core types/functions, data flow, control flow, side effects, and tests.
- Note boundaries with other modules, configuration, persistence, network calls, or queues.
- Mark inferred behavior as inferred when source evidence is indirect.

## Recommended structure

1. Mental model in plain language.
2. Runtime path from entry point to output or side effect.
3. Compact SVG overview for pipelines/request paths when it clarifies the flow.
4. File tour in reading order.
5. Boundaries and contracts.
6. Gotchas, tests as evidence, and where to change common behavior.

## Birch primitives to use

- Prefer `.section-rail`, `.reference-panel`, stacked `.card` groups, or
  `.auto-grid` for explanation plus file notes. Use `.split` only for very
  short, balanced columns with no paired long headings; it commonly creates
  mobile alignment warnings when dense prose or headings appear in both columns.
- `.flow-list` for request/data/control path.
- `.panel.chart-panel` with inline SVG `.flow-node` / `.flow-edge` for a compact
  "from input to output" overview when explaining a pipeline, checker, request
  lifecycle, or data transformation.
- `.code-block` for short source excerpts.
- `.card` for files, concepts, or responsibilities.

For metric rows in narrow reference panels, keep value labels very short or set compact variables such as `style="--metric-label: 116px; --metric-value: 52px"` on the `.metric-list`.

## Runtime overview pattern

When the source describes a pipeline, render the mental model as:

```html
<section class="section stack" data-gap="lg">
  <div class="section-head">
    <span class="eyebrow">Runtime path</span>
  </div>
  <div class="stack" data-gap="md">
    <h2>From input files to report and contact sheet.</h2>
    <p class="muted">One sentence naming optional branches and runtime dependencies.</p>
    <div class="panel chart-panel stack" data-gap="sm">
      <svg class="chart-svg" viewBox="0 0 880 360" role="img" aria-label="Runtime flow">
        <path class="flow-edge" d="M120,80 L120,140"></path>
        <g class="flow-node">
          <rect x="40" y="40" width="160" height="52"></rect>
          <text x="120" y="64" text-anchor="middle">CLI input</text>
          <text x="120" y="80" text-anchor="middle" class="sub">parse_args()</text>
        </g>
      </svg>
      <p class="chart-caption">Source: cite concrete files/functions here.</p>
    </div>
  </div>
</section>
```

Keep SVG labels short. Put exact function names, caveats, and longer explanation
in the caption or the following `.flow-list` file tour.

## Avoid

- Explaining architecture from names alone without reading code.
- Treating tests as implementation unless that is the only source available.
- Large unwrapped code dumps.
- Hiding gotchas after unrelated background.

## Validation checklist

- The explanation cites concrete files/functions or source excerpts.
- Runtime path is ordered and complete enough to follow.
- Boundaries and side effects are explicit.
- Tests or examples are used as evidence where available.
- Unknowns and inferred behavior are labeled.
