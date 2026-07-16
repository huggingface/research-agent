# Recipe: Numeric data

Use when the source contains CSVs, measurements, counts, rates, rankings, comparisons, or trend data.

## Required source checks

- Inspect row count, column names, data types, missing values, and obvious outliers before choosing a chart.
- Identify measures, dimensions, grouping fields, ordering fields, denominators, units, and time grain.
- Confirm whether values are absolute counts, percentages, rates, currency, durations, or indexed scores.
- Preserve exact source values for the claims you highlight.
- State caveats for partial data, missing denominators, changed definitions, or small samples.

## Recommended structure

1. Header with the question answered and a concise lede.
2. First viewport: 2-4 `.stat-card` elements plus the primary chart or a short `.callout` that introduces it. If KPIs sit beside a chart in a narrow rail, stack them or use `.auto-grid` with a minimum card width; never force four KPI cards into a narrow side column.
3. Evidence section: chart panel plus exact-value table using the same groups/order.
4. Interpretation section: what changed, what is stable, and what needs follow-up.
5. Caveats and source notes.

## Birch primitives to use

- `.stat-card`, `.stat-value` for headline metrics.
- `.metric-list`, `.metric-row`, `.meter` for ranked comparisons with real values.
- `.chart-panel`, `.chart-svg`, `.chart-caption` for plotted data.
- `.numeric-table-wrap`, `.numeric-table` with `.metric` numeric cells for exact values.
- `.callout` for caveats, source limitations, or the decision implication.
- Use enough semantic Birch components that the report is visibly Birch rather than
  bespoke CSS: combine `.card`, `.panel`, `.stat-card`, `.badge`, `.chip`,
  `.callout`, `.metric-list`, `.metric-row`, and `.chart-panel` where useful.

Use Matplotlib-generated inline SVG via `scripts/birch_mpl.py` for real plotted data. Pair every chart with a `.numeric-table` containing exact values.

For benchmark, token, latency, cost, model-comparison, or eval-summary reports,
make Matplotlib the default for the primary visual. Good defaults:

- grouped bars for per-task latency, tokens, cost, or artifact size;
- slope/delta plots for before/after or model A vs model B changes;
- scatter/tradeoff plots for cost vs quality or latency vs failures;
- small multiples when there are several comparable metrics.

Only hand-code inline SVG for tiny decorative marks, one-off meters, or very
small charts with fewer than three values. Do not hand-code the main comparison
chart when axes, grouped categories, labels, or multiple measures are needed.

## Avoid

- Decorative dashboards that do not answer the user's question.
- Four-column KPI strips inside narrow chart side rails; they squeeze numbers and labels on desktop.
- Charts chosen before inspecting data shape.
- Hand-coded primary charts for benchmark/model comparisons that need axes,
  grouped categories, or several measures.
- Percentages without denominators.
- Ranking bars or meters without exact values.
- Hiding important numbers only in SVG text.

## Validation checklist

- Measures, dimensions, groups, units, and denominators are clear.
- First desktop viewport contains evidence, not just decoration.
- Each chart has exact values nearby.
- Numeric table headers and cells use `.metric` where appropriate.
- Caveats are explicit when data is incomplete or ambiguous.
