# Recipe: Design directions

Use when comparing product, UX, visual, technical, or strategy options and recommending a direction.

## Required source checks

- Identify goals, constraints, audience, success criteria, and known risks.
- Make options meaningfully distinct.
- Define evaluation criteria before scoring or recommending.
- Use actual evidence for scores; otherwise use qualitative labels and caveats.

## Recommended structure

1. Decision frame: goal, constraints, audience.
2. Three or fewer distinct options unless the user asks for more.
3. Criteria comparison table.
4. Recommendation with rationale and trade-offs.
5. Smallest next experiment to reduce uncertainty.

## Birch primitives to use

- `.grid[data-cols="3"]` or `.auto-grid` for option cards.
- `.card` for each direction.
- `.numeric-table` for criteria comparison.
- `.callout[data-tone="info"]` or `.callout[data-tone="warning"]` for recommendation or caveats.
- `.metric-list` only when actual scored evidence exists.

## Avoid

- Near-duplicate options with different names.
- Scoring without evidence.
- Recommendations that ignore constraints.
- Treating the highest-risk option as safest without mitigation.

## Validation checklist

- Criteria are explicit before comparison.
- Options are distinct and comparable.
- Recommendation names trade-offs.
- Next experiment is small, measurable, and tied to uncertainty.
