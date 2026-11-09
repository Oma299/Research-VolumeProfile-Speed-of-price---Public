# Primary Cox Model — Pilot v0.1

**Run ID:** COX-2026-11-09-03\
**Status:** Optimizer convergence confirmed after 5 iterations. Estimates are finite; prefit design rank was 30/30 including its intercept column, corresponding to 29 fitted Cox regression coefficients (Cox has no separately estimated intercept); coefficient covariance rank was 29/29.\
**Python:** 3.13.17 via `.venv-cox/bin/python`\
**Input:** `outputs/tables/events_analysis.csv`, primary Pilot v0.1 event/outcome table from the 1-minute OHLCV workflow. aggTrades was not used.

## Model

Section 18 Cox proportional hazards model for time to the 1×ATR target, with right censoring at 240 minutes. Exposure: `log1p_VA`. Controls: volatility, ATR-normalized box width, breakout strength, pre-breakout trend, breakout direction, and UTC hour. UTC hour was categorical with all 24 categories included; no hour was removed or merged. Ties among integer-minute event times used Efron's method. `lifelines.CoxPHFitter` semi-parametric model was used with the default Breslow baseline hazard and no penalizer.

Formula: `log1p_VA + volatility + normalized_box_width_atr + breakout_strength + pre_trend + C(breakout_direction) + C(hour_of_day_utc)`.

## Sample and validation

- N = **300** eligible events; **231** target hits; **69** right-censored.
- The current input had 324 rows and 324 unique non-null event IDs, with no duplicates. Required eligible inputs were complete except specification-required null `time_to_target_minutes` for censored observations.
- Hit durations matched `time_to_target_minutes`. Censored rows had null `time_to_target_minutes` and `observed_time_minutes = 240`. Observed duration range: **1–240 minutes**. Incomplete eligible outcomes: **0**.
- Every UTC-hour category from 0 to 23 was present. Formulaic prefit design rank was **30/30 including the intercept** (one intercept plus 29 slope columns). The fitted semiparametric Cox model estimates **29 regression coefficients**; it does not estimate a separate intercept, and the estimated coefficient covariance rank was **29/29**.
- Hour 19: **4 events** (2 hit, 2 censored). Hour 17: **5 events** (3 hit, 2 censored). Both categories were retained.

## Main exposure result

For `log1p_VA`, coefficient **0.5191**, hazard ratio **1.6805**, 95% HR confidence interval **0.5320–5.3087**, SE **0.5869**, p **0.3764**. The interval includes 1 and the estimate is imprecise; this model does not provide clear evidence of an association between `log1p_VA` and target-reaching rate.

## Full model estimates

| Term | Coefficient | Hazard ratio | SE | 95% HR CI | p-value |
|---|---:|---:|---:|---:|---:|
| log1p_VA | 0.519082 | 1.68048 | 0.586883 | 0.53196–5.30872 | 0.37644 |
| volatility | -69.1671 | 9.14343e-31 | 167.706 | 1.62112e-173–5.15706e+112 | 0.680023 |
| normalized_box_width_atr | -0.0298895 | 0.970553 | 0.0769689 | 0.834647–1.12859 | 0.69777 |
| breakout_strength | 0.255058 | 1.29054 | 0.0898306 | 1.0822–1.53898 | 0.00452099 |
| pre_trend | 12.2412 | 207155 | 28.027 | 2.88169e-19–1.48917e+29 | 0.662282 |
| C(breakout_direction)[T.upward] | -0.00979402 | 0.990254 | 0.147148 | 0.742153–1.32129 | 0.946933 |
| C(hour_of_day_utc)[T.1] | 0.0475017 | 1.04865 | 0.655222 | 0.290338–3.78753 | 0.942206 |
| C(hour_of_day_utc)[T.2] | -0.4764 | 0.621015 | 0.579769 | 0.199343–1.93465 | 0.411244 |
| C(hour_of_day_utc)[T.3] | -0.496809 | 0.608469 | 0.580115 | 0.195184–1.89685 | 0.391778 |
| C(hour_of_day_utc)[T.4] | -0.482703 | 0.617113 | 0.559487 | 0.206124–1.84757 | 0.388269 |
| C(hour_of_day_utc)[T.5] | 0.976869 | 2.65613 | 0.613791 | 0.797607–8.84522 | 0.11149 |
| C(hour_of_day_utc)[T.6] | -0.622932 | 0.536369 | 0.548799 | 0.182947–1.57254 | 0.256341 |
| C(hour_of_day_utc)[T.7] | -0.150907 | 0.859928 | 0.548522 | 0.293467–2.51979 | 0.783228 |
| C(hour_of_day_utc)[T.8] | -0.156885 | 0.854802 | 0.503011 | 0.318935–2.29102 | 0.755123 |
| C(hour_of_day_utc)[T.9] | -0.273272 | 0.760886 | 0.473617 | 0.300729–1.92514 | 0.563947 |
| C(hour_of_day_utc)[T.10] | -0.834909 | 0.433914 | 0.523968 | 0.155382–1.21173 | 0.111063 |
| C(hour_of_day_utc)[T.11] | 0.0355367 | 1.03618 | 0.497241 | 0.391004–2.74591 | 0.943026 |
| C(hour_of_day_utc)[T.12] | 0.116909 | 1.12402 | 0.470504 | 0.446971–2.82661 | 0.803765 |
| C(hour_of_day_utc)[T.13] | 0.019621 | 1.01981 | 0.469582 | 0.406268–2.55994 | 0.966671 |
| C(hour_of_day_utc)[T.14] | -0.213639 | 0.80764 | 0.464177 | 0.325169–2.00598 | 0.645334 |
| C(hour_of_day_utc)[T.15] | -0.435566 | 0.646899 | 0.504376 | 0.240719–1.73845 | 0.387822 |
| C(hour_of_day_utc)[T.16] | -0.14124 | 0.868281 | 0.622104 | 0.256522–2.93898 | 0.820396 |
| C(hour_of_day_utc)[T.17] | -0.932273 | 0.393658 | 0.713404 | 0.0972452–1.59356 | 0.191282 |
| C(hour_of_day_utc)[T.18] | -0.0277883 | 0.972594 | 0.650064 | 0.272017–3.4775 | 0.965903 |
| C(hour_of_day_utc)[T.19] | -0.963165 | 0.381683 | 0.819286 | 0.076617–1.90143 | 0.239749 |
| C(hour_of_day_utc)[T.20] | 0.188313 | 1.20721 | 0.535896 | 0.422307–3.45095 | 0.725289 |
| C(hour_of_day_utc)[T.21] | 0.14683 | 1.15816 | 0.585469 | 0.367634–3.64854 | 0.801977 |
| C(hour_of_day_utc)[T.22] | 0.00287457 | 1.00288 | 0.510223 | 0.368932–2.72616 | 0.995505 |
| C(hour_of_day_utc)[T.23] | 0.0680621 | 1.07043 | 0.543866 | 0.368655–3.10812 | 0.900409 |

## Convergence warning and limitations

The optimizer reported convergence success after 5 iterations. Lifelines also emitted a `ConvergenceWarning` that `volatility` and `pre_trend` have very low variance and may harm convergence. The coefficient estimates, standard errors, confidence bounds and covariance were finite/full rank, but the warning and large standard errors for these controls indicate imprecision and should be kept in view. No variable was removed, no penalty was added, and no alternative model was fitted.

## Proportional-hazards diagnostic

Section 18 of the frozen specification requires a Cox proportional-hazards model but does not prescribe a diagnostic method. For this check, the same model was refitted in memory with the same formula, 300 eligible observations, all 24 UTC-hour categories, Efron tie handling, and no penalizer. It converged after 5 iterations and emitted the same low-variance `ConvergenceWarning` for `volatility` and `pre_trend`. No variables or hour categories were removed or combined.

The diagnostic was `lifelines.statistics.proportional_hazard_test` using the rank transform of time (`time_transform="rank"`), i.e. coefficient-level Schoenfeld-residual tests. This method was selected for this run because the frozen specification is silent on PH diagnostics. The p-values below are unadjusted across 29 fitted coefficients; categorical variables are shown by their fitted dummy coefficients, and no joint factor-level omnibus test or multiplicity correction was specified or applied.

The earlier diagnostic console output also printed the arithmetic sum of these 29 test statistics (45.5003) and a chi-square tail probability using 29 degrees of freedom (p=0.026291). That calculation was not validated as a global PH test for these correlated coefficient-level tests, is not treated as an omnibus result, and is not interpreted here. The coefficient-level results are preserved separately in `07 Results/tables/cox_primary_ph_tests_2026-11-09-01.csv`.

| Coefficient | Test statistic | p-value |
|---|---:|---:|
| `log1p_VA` | 0.662598 | 0.415644 |
| `volatility` | 0.019366 | 0.889321 |
| `normalized_box_width_atr` | 0.198337 | 0.656066 |
| `breakout_strength` | 18.971821 | 0.000013 |
| `pre_trend` | 5.940023 | 0.014801 |
| `C(breakout_direction)[T.upward]` | 0.306914 | 0.579580 |
| `C(hour_of_day_utc)[T.1]` | 0.706906 | 0.400473 |
| `C(hour_of_day_utc)[T.2]` | 0.096163 | 0.756484 |
| `C(hour_of_day_utc)[T.3]` | 0.124502 | 0.724202 |
| `C(hour_of_day_utc)[T.4]` | 2.095805 | 0.147704 |
| `C(hour_of_day_utc)[T.5]` | 0.340718 | 0.559415 |
| `C(hour_of_day_utc)[T.6]` | 0.131168 | 0.717224 |
| `C(hour_of_day_utc)[T.7]` | 0.837231 | 0.360190 |
| `C(hour_of_day_utc)[T.8]` | 0.473158 | 0.491538 |
| `C(hour_of_day_utc)[T.9]` | 1.591151 | 0.207162 |
| `C(hour_of_day_utc)[T.10]` | 0.892490 | 0.344803 |
| `C(hour_of_day_utc)[T.11]` | 0.564046 | 0.452634 |
| `C(hour_of_day_utc)[T.12]` | 0.295426 | 0.586764 |
| `C(hour_of_day_utc)[T.13]` | 1.913721 | 0.166551 |
| `C(hour_of_day_utc)[T.14]` | 0.680576 | 0.409388 |
| `C(hour_of_day_utc)[T.15]` | 1.378449 | 0.240365 |
| `C(hour_of_day_utc)[T.16]` | 1.875747 | 0.170818 |
| `C(hour_of_day_utc)[T.17]` | 0.226307 | 0.634276 |
| `C(hour_of_day_utc)[T.18]` | 2.822358 | 0.092960 |
| `C(hour_of_day_utc)[T.19]` | 0.079901 | 0.777431 |
| `C(hour_of_day_utc)[T.20]` | 0.005403 | 0.941406 |
| `C(hour_of_day_utc)[T.21]` | 0.891449 | 0.345085 |
| `C(hour_of_day_utc)[T.22]` | 0.149727 | 0.698797 |
| `C(hour_of_day_utc)[T.23]` | 1.228826 | 0.267635 |

At the coefficient level, the rank-based tests flag `breakout_strength` (p=0.000013) and `pre_trend` (p=0.014801) as possible departures from proportional hazards; this is a diagnostic signal, not proof that the model is invalid. Because 29 unadjusted tests were inspected and the UTC-hour categories are sparse, interpret these flags cautiously. The PH diagnostic does not change the fitted model or the `log1p_VA` estimate. No alternative model was fitted.

This is an observational association model, not a causal result. It covers one instrument, one exchange, and the fixed Pilot v0.1 period. Spearman, R60 regression, project tests, robustness analyses, and aggTrades analysis were not run.

## Result file

- Coefficient table: `07 Results/tables/cox_primary_coefficients_2026-11-09-03.csv`
- Separate coefficient-level PH diagnostics: `07 Results/tables/cox_primary_ph_tests_2026-11-09-01.csv`
