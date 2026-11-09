# Day 3 Block 3: Volume Ahead Availability by Direction

## Scope

This report completes the narrow Block 3 scope assigned for this run: describe Volume Ahead (VA) availability for UP and DOWN events before any pooled-result interpretation. It is an availability summary only. No statistical-significance test, outcome comparison, or VA-outcome model was run. Missing VA values were not filled or imputed.

The detailed plan in `11 deadlines/Весь план на 4 дней детальный.md` gives Block 3 a broader scope: VA quintiles and their outcome summaries, hit rate and observed-time summaries, Spearman correlation, and a simple R60 regression with a confidence interval. Those items are not part of this narrow availability run and remain separate unfinished work. The detailed plan was not changed.

## Data and Definition

Source: `outputs/tables/events_analysis.csv`, containing 324 unique event rows. The direction-specific denominator is every event in that direction. VA is counted as available when the persisted `VA` value is present and finite; the `va_missing` and `profile_valid` indicators were checked for consistency. Percentages use all events of that direction as the denominator. Missing-reason percentages use missing-VA events of that direction as the denominator.

## Descriptive Table

| Direction | Events | VA available | Available (%) | VA missing | Missing (%) | Missing reason | Reason count (% of missing) |
|---|---:|---:|---:|---:|---:|---|---:|
| UP | 162 | 140 | 86.4% | 22 | 13.6% | `reference_region_outside_historical_range` | 22 (100.0%) |
| DOWN | 162 | 160 | 98.8% | 2 | 1.2% | `reference_region_outside_historical_range` | 2 (100.0%) |

Machine-readable table: `outputs/tables/day3_block3_va_availability_by_direction.csv`.

## Interpretation and Limits

In this sample, the missing-VA share is higher for UP events than for DOWN events (13.6% versus 1.2%). All 24 missing values are due to the historical typical-price range not covering the full reference region. This describes exposure availability, not VA values or post-breakout outcomes. It does not establish a statistically meaningful direction difference, a cause, or any association between VA and outcomes. The uneven availability should be disclosed when considering any later pooled analysis.

## Explicitly Not Run

The following broader Block 3 work remains unfinished and separate: VA distribution/quintile analysis; target-hit, observed-time, and other outcome summaries by quintile; Spearman correlation; and the simple R60 regression with confidence interval. No Kaplan–Meier curves, Cox model, R60 OLS/HC3, or other primary outcome model was run.

## Checks

- Source rows: 324; event IDs unique: 324.
- Direction totals: UP 162, DOWN 162.
- Available plus missing equals each direction total.
- All missing values have reason `reference_region_outside_historical_range`; missing flags and profile-validity flags agree with VA availability.
- Descriptive CSV values and rounded percentages were independently checked against the source rows.
- Existing focused sample-size tests: 6 passed.

## Completion

The requested narrow-scope Day 3 Block 3 availability assessment is complete. The broader items in the detailed plan are not complete. That plan places Day 3 Block 4 charts next; the deferred Block 3 analyses remain explicitly outstanding and are not represented as completed here.
