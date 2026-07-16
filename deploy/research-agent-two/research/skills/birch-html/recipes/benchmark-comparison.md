# Recipe: Benchmark comparison / evaluation report

Use when the artifact compares model runs, seed runs, GEPA candidates, migration
baselines, checker outputs, token/time/cost profiles, or quality-vs-latency /
cost-vs-compliance tradeoffs.

This recipe helps with evaluation and optimization reports.

This recipe is not a generic numeric dashboard. The output should read like an
evaluation artifact: what passed, what failed, what changed, how trustworthy the
measurement is, and what experiment should happen next.

## Required source checks

- Identify run provenance: model/provider, prompt/eval set, skill/docs version,
  candidate id, command, timestamp, viewport, hardware/runtime context, and
  relevant input/output paths.
- Read the scoring formula and checker side-info before interpreting scores.
- Separate generation failures, checker failures, warnings, hygiene issues,
  content-quality judgments, and runtime/cost metrics.
- Preserve exact pass/fail counts, warning/failure counts, wall time, token
  totals, cost estimates, score components, and per-eval values used in claims.
- State comparability caveats: provider token schemas differ, cached/effective
  tokens may not be apples-to-apples, checker warnings are mechanical rather
  than full quality scores, and same:same screenshot pairs mostly validate
  contracts and geometry.
- Note missing data explicitly instead of normalizing away incomplete runs.

## Recommended structure

1. Header that states the decision/result, not just the dataset:
   "GPT-5.5 passed; Opus failed", "Candidate B improved checker score but
   increased latency", or "GEPA best improves mobile but regresses wrapping".
2. First viewport: compact result callout plus 3-5 `.stat-card` KPIs for
   pass/fail, score, checker failures/warnings, wall time, token/cost totals, or
   candidate count.
3. Tradeoff visual: grouped bars, slope/delta plot, scatterplot, or small
   multiples for the primary comparison.
4. Exact values table using the same run/eval ordering as the visual.
5. Findings narrative: what passed, what failed, what regressed, what improved,
   and whether the result is good seed data for GEPA or the next evaluation.
6. Caveats and reproducibility: scoring formula, commands, source files, report
   paths, and known measurement limitations.

## Birch primitives to use

- `.callout` for the result, recommendation, or comparability caveat.
- `.stat-card`, `.stat-value` for pass/fail counts, scores, warnings, time,
  tokens, and cost.
- `.chart-panel`, `.chart-svg`, `.chart-caption` for the primary tradeoff chart.
- `.numeric-table-wrap`, `.numeric-table`, and `.metric` cells for exact values.
- `.section-rail` or `.reference-panel` for scoring formula, provenance, or
  reproducibility commands.
- `.code-block[data-wrap="true"]` for commands, labels, report paths, and score
  formulas that may wrap on mobile.
- `.timeline` or `.flow-list` only when explaining an experiment sequence or
  candidate-selection process.

Keep benchmark visuals Birch-native: flat token surfaces, borders, restrained
accent strokes, and Matplotlib/inline SVG marks. Do not use gradient cards,
gradient chart backgrounds, glass panels, glow effects, or decorative
background images.

Use Matplotlib-generated inline SVG via `scripts/birch_mpl.py` for the primary
visual when comparing more than a few values. Good defaults:

- grouped bars for per-eval latency, tokens, warnings, failures, or costs;
- slope/delta plots for before/after migrations or candidate-vs-seed changes;
- scatterplots for quality vs cost/time or compliance vs latency;
- small multiples for suites with several models and several metrics.

Pair every chart with exact values in a `.numeric-table`; do not make the SVG the
only place where a score, token count, warning count, or cost appears.

## Interpretation guidance

- Lead with the decision the reader can act on.
- Distinguish "mechanically valid" from "high quality"; checker pass/fail is not
  a full content-quality judgment unless the rubric says so.
- Call out regressions even when the aggregate score improves.
- Explain whether improvements are material, noisy, or blocked by missing data.
- Name the next experiment: rerun, broaden model suite, inspect artifacts,
  tighten checker, optimize skill text, or promote a candidate.

## Avoid

- Generic dashboards that show metrics without a decision.
- Ranking models or candidates without explaining provenance and caveats.
- Combining incompatible token fields as if they were identical.
- Treating warnings, failures, and human-quality findings as the same class of
  evidence.
- Hand-coded primary charts when axes, grouped categories, or multiple metrics
  are needed.
- Gradient panels or custom dashboard skins that do not match Birch's flat
  ivory/white/oat surface language.
- Hiding scoring formulas or commands in prose with no reproducibility trail.

## Validation checklist

- First viewport states the result or recommendation.
- Run provenance and scoring formula are present.
- Exact values appear near every visual claim.
- Pass/fail, warnings, latency, tokens, and cost are labeled with units/schema.
- Caveats explain comparability limits.
- Reproducibility commands or source/report paths are included.
- Next optimization or experiment is explicit.
