# Pilot v0.1 Specification

- **Version:** Pilot v0.1
- **Status:** FROZEN
- **Freeze Date:** 2026-10-04
- **Main Source of Truth:** This document (`Pilot v0.1 Specification.md`) serves as the canonical specification for the Research Volume Profile project. All other files must align with this specification. Any modification of frozen parameters requires creating version `v0.2` and recording a changelog entry in `[[01 Research/Decisions Log]]`. Parameters cannot be changed after looking at results or event counts.

---

## 1. Status and Scope
This document defines the complete, self-contained methodology for **Pilot v0.1** of the Research Volume Profile project. It is an empirical proof-of-concept study investigating the statistical association between historical trade volume density ahead of price following a price consolidation breakout and subsequent price speed/outcomes on BTCUSDT. It is **not** a trading strategy, causal proof, or machine learning model.

---

## 2. Research Question
**Is the historical trade volume density ahead of price in an 8-hour consolidation breakout of BTCUSDT associated with subsequent price speed in the direction of the breakout?**

- **Nature of inquiry:** Empirical association study. Positive, negative, and null results are equally valid and will be reported honestly.
- **Causality:** No causal claims or guaranteed acceleration are made.

---

## 3. Hypotheses
- **Primary Hypothesis (H1):** Lower ex-ante volume ahead ($\log(1 + VA)$) is associated with a shorter time to reach the $1 \times \text{ATR}[t-1]$ target after a breakout from an 8-hour consolidation box on 15-minute Binance BTCUSDT Spot data.
- **Null Hypothesis (H0):** Ex-ante volume ahead has no systematic association with time to the $1 \times \text{ATR}[t-1]$ target after a breakout from a consolidation box.
- **Alternative pattern note:** Low volume might reflect lack of participant interest rather than a "free path", meaning the association could be absent or have the opposite sign.

---

## 4. Data and Sample
- **Exchange:** Binance
- **Instrument:** BTCUSDT Spot
- **Source Data Resolution:** 1-minute OHLCV (Quote volume in USDT, Base volume in BTC)
- **Timezone:** UTC
- **Pilot Period:** Fixed analysis period from **2025-01-01 through 2025-06-30 UTC**. Warm-up begins **2024-11-01 UTC** to provide necessary 30-day profile lookback and 60-day width percentiles.
- **Sample Size Rule:** The analysis period is fixed and cannot be expanded after observing event counts. If fewer than 30 qualified events are obtained, this is recorded as a project limitation; period expansion is reserved for a separate future version of the study.
- **Direction:** Upward and downward breakouts combined after directional normalization (`breakout_direction` stored as a control variable).

---

## 5. Time Conventions
- All timestamps and data processing operate strictly in **UTC**.
- Calendar days (30 days for Volume Profile lookback, 60 days for box width percentiles) are measured in UTC days.

---

## 6. 1m-to-15m Aggregation
- 15-minute candles are aggregated strictly from exactly 15 consecutive 1-minute OHLCV bars aligned to UTC minute boundaries (00, 15, 30, 45):
  - Incomplete 15m candles (fewer than 15 valid 1-minute bars) are **not** used.
  - $\text{Open}_{15m} = \text{Open}_{1m}(\text{first bar})$
  - $\text{High}_{15m} = \max(\text{High}_{1m}(\text{all 15 bars}))$
  - $\text{Low}_{15m} = \min(\text{Low}_{1m}(\text{all 15 bars}))$
  - $\text{Close}_{15m} = \text{Close}_{1m}(\text{last bar})$
  - $\text{BaseVolume}_{15m} = \sum \text{BaseVolume}_{1m}(\text{all 15 bars})$ (in BTC)
  - $\text{QuoteVolume}_{15m} = \sum \text{QuoteVolume}_{1m}(\text{all 15 bars})$ (in USDT)
- For Volume Profile and Volume Ahead calculations, Binance `quote_asset_volume` (in USDT) is strictly used.

---

## 7. ATR Definition
- **Indicator:** Wilder ATR ($\text{ATR}(14)$) evaluated on 15-minute closed candles.
- **Initialization:** True Range ($TR$) is determined standardly from current High/Low and previous Close. The first ATR value equals the arithmetic mean of the first 14 valid TR values. Subsequent values follow:
  $$\text{ATR}_n = \frac{(13 \times \text{ATR}_{\text{previous}}) + \text{TR}_{\text{current}}}{14}$$
- **Timing & Constraints:** For a candidate/event at candle $t$, ATR uses only information strictly available before candle $t$, i.e., calculated up to candle $t-1$ inclusive. ATR must be finite and strictly positive ($> 0$).

---

## 8. Consolidation Candidate Definition
A candidate Consolidation Box is constructed over 32 fully completed 15-minute candles:
$$t-32, t-31, \dots, t-1$$
(corresponding to 8 hours). Candle $t$ does not participate in box construction or qualification.

Box boundaries:
- Resistance $H = \max(\text{High}_{t-32 \dots t-1})$
- Support $L = \min(\text{Low}_{t-32 \dots t-1})$
- Absolute Width $W = H - L$
- Normalized Width $w = \frac{H - L}{\text{Close}[t-1]}$

A candidate window qualifies as a Consolidation Box if and only if **all three** conditions are met:
1. **Relatively Narrow Range:**
   Normalized width $w$ does not exceed the 20th percentile of $w$ over all computable 32-candle windows with activation timestamp $u$ satisfying:
   $$t - 60 \text{ calendar days} \le u < t$$
   Each historical window uses only data available at its own activation timestamp. The current candidate $t$ is excluded from the percentile distribution. The percentile is computed using the standard linearly-interpolated empirical quantile (`pandas.Series.quantile(0.20, interpolation="linear")`). Overlapping historical windows are permitted for calculating the width distribution. If the full 60-calendar-day historical interval or required data is missing, the candidate is not evaluated and receives the reason `insufficient_width_history`.
2. **Low Directional Trend (Efficiency Ratio):**
   $$ER = \frac{|\text{Close}[t-1] - \text{Close}[t-32]|}{\sum_{i=t-31}^{t-1} |\text{Close}[i] - \text{Close}[i-1]|} < 0.30$$
   *(If denominator is 0, the window is excluded as degenerate).*
3. **Closing Price Distribution:**
   At least 23 out of 32 closing prices ($\ge 70\%$) lie within the central region:
   $$[L + 0.1W, H - 0.1W]$$
   *(If $W = 0$, the window is excluded).*

---

## 9. Box Activation and Lifecycle
1. Candidates are evaluated strictly on completed historical data.
2. If qualified on candles $t-32 \dots t-1$, the box activates on candle $t$.
3. Upon activation, boundaries $H$ and $L$ are frozen and **never** recalculated.
4. The box is checked for breakout on exactly 32 candles:
   $$t, t+1, \dots, t+31$$
5. Maximum active age of a box is 32 candles (`box_age_candles = j - t + 1`, valid integers 1 to 32).
6. If no breakout occurs by candle $t+31$, the box status becomes `expired` after the close of candle $t+31$.
7. **Strict Overlap Prohibition:** While a box is active, no new candidates are created or queued. Overlap restrictions apply exclusively to active event boxes (historical overlapping windows for width percentiles are permitted).
8. **Resumption of Search:**
   - After a breakout at candle $j$, search for a new candidate resumes on candle $j+1$.
   - After expiration at candle $t+31$, search resumes on candle $t+32$.
   - The termination candle cannot simultaneously be the breakout candle of an old box and the activation candle of a new box.
9. **Required Event/Box Record Fields:**
   - `box_activation_time`
   - `box_termination_time`
   - `box_status` (`breakout` or `expired`)
   - `box_age_candles`

---

## 10. Breakout Definition
Candle $t$ is checked for a breakout relative to frozen box boundaries $(H, L)$ and $\text{ATR}[t-1]$:
- **Upward Breakout:** $\text{Close}[t] > H + 0.1 \times \text{ATR}[t-1]$
- **Downward Breakout:** $\text{Close}[t] < L - 0.1 \times \text{ATR}[t-1]$
- **Timestamp:** The event is fixed strictly at the close of candle $t$.
- **False breakouts:** False breakouts are preserved in the dataset and are not filtered out. No retest or subsequent candle confirmation is required.

---

## 11. Event Independence and Overlap Rules
- Only the **first** valid breakout (upward or downward) is considered for a given active box.
- Immediately upon a breakout, the box closes, preventing multiple breakouts from the same box.
- Overlapping active boxes are strictly prohibited.

---

## 12. Approximate Volume Profile and Price Bins
- **Source:** Binance 1-minute `quote_asset_volume` (in USDT).
- **Profile Interval:** Let $\text{event\_time}$ be the closing timestamp of 15m breakout candle $t$.
  - $\text{breakout\_candle\_start} = \text{event\_time} - 15 \text{ minutes}$
  - $\text{profile\_end} = \text{breakout\_candle\_start}$
  - $\text{profile\_start} = \text{profile\_end} - 30 \text{ calendar days}$
  - Profile Interval = $[\text{profile\_start}, \text{profile\_end})$
  - *Example:* Breakout candle `[2025-01-05 10:00, 2025-01-05 10:15)`; $\text{event\_time} = \text{2025-01-05 10:15 UTC}$; $\text{profile\_end} = \text{2025-01-05 10:00 UTC}$; $\text{profile\_start} = \text{2024-12-06 10:00 UTC}$; exact profile interval = $[\text{2024-12-06 10:00 UTC}, \text{2025-01-05 10:00 UTC})$.
  - This uses fully closed 1-minute bars in the 30 calendar days preceding the start of the breakout candle. Breakout candle minutes are strictly excluded.
- **Profile Completeness & Validation:**
  - $\text{expected\_profile\_minutes} = 43\_200$ ($30 \times 24 \times 60$).
  - After filtering, the interval must contain exactly 43,200 unique consecutive minute timestamps. Otherwise, $VA = \text{missing}$, $\text{va\_missing} = \text{True}$, and $\text{va\_missing\_reason} = \text{"incomplete\_profile\_window"}$.
- **Bin Grid Construction:** For an event with boundary $B$ ($H$ for upward, $L$ for downward) and $\text{ATR}[t-1]$:
  - $d = 0.05 \times \text{ATR}[t-1]$
  - If $d \le 0$ or non-finite, VA receives missing reason `invalid_bin_width`.
  - The price-bin grid is anchored to box boundary $B$.
  - Bin with integer index $k$ is defined as the half-open interval:
    $$\text{Bin}(k) = [B + k \cdot d, B + (k+1) \cdot d)$$
  - Each 1-minute bar is assigned entirely to a single bin according to its typical price:
    $$\text{TypicalPrice} = \frac{\text{High} + \text{Low} + \text{Close}}{3}$$
    $$k = \text{floor}\left(\frac{\text{TypicalPrice} - B}{d}\right)$$
  - Half-open convention ensures no overlapping bins.
- **Bin Ranges & Example:**
  - Upward Ahead bins: $k = 0, \dots, 19$ (exactly 20 full bins: $[B, B + 20d)$).
  - Downward Ahead bins: $k = -20, \dots, -1$ (exactly 20 full bins: $[B - 20d, B)$).
  - Reference bins: $k = -100, \dots, 99$ (exactly 200 full bins: $[B - 100d, B + 100d)$).
  - *Numerical Example:* For $B = 100,000$, $d = 50$, and $\text{TypicalPrice} = 101,050$:
    $$k = \text{floor}\left(\frac{101,050 - 100,000}{50}\right) = \text{floor}\left(\frac{1,050}{50}\right) = 21$$
    This observation belongs to $\text{Bin}(21) = [101,050, 101,100)$, which is outside the Ahead Region but inside the Reference Region.

---

## 13. Volume Ahead Formulas
- **Sums & Densities:**
  $$\text{AheadVolume} = \sum_{k \in \text{AheadBins}} \text{QuoteVolume}_k$$
  $$\text{ReferenceVolume} = \sum_{k \in \text{ReferenceBins}} \text{QuoteVolume}_k$$
  $$\text{AheadDensity} = \frac{\text{AheadVolume}}{20}$$
  $$\text{ReferenceDensity} = \frac{\text{ReferenceVolume}}{200}$$
  *(Density in Pilot v0.1 is the average USDT quote volume per uniform price bin, not volume per dollar of price).*
- **Metric:**
  $$VA = \frac{\text{AheadDensity}}{\text{ReferenceDensity}}$$
  $$\text{log1p\_VA} = \log(1 + VA)$$
  *(No artificial epsilon added).*
- **Missing Data & Coverage Rules:**
  - If $\text{ReferenceDensity} \le 0$ or non-finite: $VA = \text{missing}$, `va_missing = True`, `va_missing_reason = "zero_or_invalid_reference_density"`.
  - **Coverage Check:** Coverage is considered sufficient only if the full Reference interval $[B - 5.0 \times \text{ATR}, B + 5.0 \times \text{ATR}]$ lies entirely within the observable historical $\text{TypicalPrice}$ range of the 30-day profile window. If the full Reference Region is not covered, $VA$ is marked missing with reason `reference_region_outside_historical_range`.
  - **Incomplete Profile Window:** If required 1-minute bars are missing within the 30-day profile window, they are **never** interpreted as zero volume; instead, $VA$ is marked missing with reason `incomplete_profile_window`.
- **Event Table Field:** Include `reference_volume` in the event table schema.

---

## 14. Outcomes
- **Outcome Timeline:** Let $\text{event\_time}$ be the closing moment of breakout candle $t$, and $P_0 = \text{Close}[t]$. The first outcome bar ($m = 1$) is the first full 1-minute candle starting at $\text{event\_time}$ and ending 1 minute later. Outcome bars are numbered $m = 1, 2, \dots, 240$.
- **Primary Outcome (Speed):** Time in minutes after $\text{Close}[t]$ until first reaching target distance $1.0 \times \text{ATR}[t-1]$ in the direction of the breakout:
  - Upward Target = $P_0 + \text{ATR}[t-1]$ (reached if 1-minute $\text{High}_m \ge \text{Target}$).
  - Downward Target = $P_0 - \text{ATR}[t-1]$ (reached if 1-minute $\text{Low}_m \le \text{Target}$).
  - If target is first reached inside bar $m$: `time_to_target_minutes = m` (integer 1 to 240).
  - If target is not reached in bars 1–240: `target_hit = False`, `right_censored = True`, `observed_time_minutes = 240`, and `time_to_target_minutes` is left null/missing so event time is not mixed with censoring time.
  - **Incomplete Follow-up:** If a full 240-minute follow-up is missing due to dataset end or missing minutes, set `outcome_missing = True`, record the specific reason, retain the event in the event table, and exclude the outcome from analysis.
- **Key Secondary Outcome:** Directional return at 60 minutes ($R_{60}$):
  - Let $s = +1$ for upward, $s = -1$ for downward.
  - $R_h = s \times \frac{\text{Close}[\text{event\_time} + h] - P_0}{P_0}$ for $h = 15, 30, 60, 120, 240$.
  - Returns use the close of the 1-minute bar ending exactly $h$ minutes after $\text{event\_time}$. If the exact bar is missing, the return is marked missing (no substitution).
- **MFE and MAE (240 minutes, relative to $P_0$, excluding breakout candle):**
  - Upward:
    $$\text{MFE}_{240} = \frac{\max(\text{High}_{m=1 \dots 240}) - P_0}{P_0}$$
    $$\text{MAE}_{240} = \frac{\min(\text{Low}_{m=1 \dots 240}) - P_0}{P_0}$$
  - Downward:
    $$\text{MFE}_{240} = \frac{P_0 - \min(\text{Low}_{m=1 \dots 240})}{P_0}$$
    $$\text{MAE}_{240} = \frac{P_0 - \max(\text{High}_{m=1 \dots 240})}{P_0}$$
  *(Positive MFE = favorable; negative MAE = adverse).*
- **Return to Box & Intrabar Ambiguity:**
  - Evaluated starting from the first outcome minute ($m = 1 \dots 240$):
    - Upward breakout: first 1-minute $\text{Close}_m < H$.
    - Downward breakout: first 1-minute $\text{Close}_m > L$.
  - Record `time_to_return_box_minutes` using the same 1–240 minute numbering.
  - **Intrabar Ambiguity (`ambiguous_intrabar`):** If target touch and Return to Box close are registered in the same 1-minute bar, set `ambiguous_intrabar = True`, save the timestamps of both, do not assign arbitrary precedence, and retain the target hit status.

---

## 15. Computed Features & Controls
- **Breakout Strength:**
  - Upward: $\frac{\text{Close}[t] - H}{\text{ATR}[t-1]}$
  - Downward: $\frac{L - \text{Close}[t]}{\text{ATR}[t-1]}$
- **Pre-Breakout Trend (`pre_trend`):** Direction-normalized return over previous 32 candles:
  $$\text{pre\_trend} = s \times \frac{\text{Close}[t-1] - \text{Close}[t-32]}{\text{Close}[t-32]}$$
  where $s = +1$ (upward), $s = -1$ (downward).
- **Normalized Box Width:** $\frac{H - L}{\text{ATR}[t-1]}$
- **Volatility:** $\frac{\text{ATR}[t-1]}{\text{Close}[t-1]}$
- *Handling:* If any denominator is missing, zero, or non-finite, the respective value is marked missing.

---

## 16. Event Table Schema
Each row in the event table represents a single validated breakout event:
- **Identification:** `event_id`, `breakout_time_utc`, `breakout_direction` (`upward` / `downward`)
- **Box Properties:** `box_start_time`, `box_activation_time`, `box_termination_time`, `box_status`, `box_age_candles`, `H`, `L`, `box_width`, `normalized_box_width`, `central_closes_count`, `efficiency_ratio`
- **Breakout & ATR:** `breakout_close`, `atr_14_15m`, `breakout_strength`
- **Volume Metrics:** `ahead_volume`, `reference_volume`, `ahead_density`, `reference_density`, `VA`, `log1p_VA`, `va_missing`, `va_missing_reason`
- **Outcomes:** `target_hit` (boolean), `time_to_target_minutes`, `observed_time_minutes`, `right_censored` (boolean), `outcome_missing` (boolean), `r_15`, `r_30`, `r_60`, `r_120`, `r_240`, `mfe_240`, `mae_240`, `return_to_box` (boolean), `time_to_return_box_minutes`, `ambiguous_intrabar` (boolean)
- **Control Variables:** `volatility`, `pre_trend`, `hour_of_day_utc`

---

## 17. Leakage Prevention & Automated Validation Checks
Mandatory automated checks prior to analysis:
1. Exactly 32 valid lifecycle candles per box.
2. Zero active-box overlaps.
3. Zero profile overlap with breakout candle.
4. Exactly 20 Ahead bins and 200 Reference bins.
5. Full 30-day profile interval coverage.
6. Full 240-minute outcome interval coverage.
7. First outcome minute starts strictly after breakout close.
8. No duplicate `event_id`s.
9. Correct upward/downward symmetry on artificial test data.
10. Missing data never converted to zero or low volume.

---

## 18. Pilot Analysis Plan
- **Primary Model:** Time-to-event analysis (Cox proportional hazards model for time to $1 \times \text{ATR}$ up to 240 minutes, handling right censoring). Kaplan-Meier curves across VA quintiles for descriptive visualization.
- **Secondary Model:** Linear/robust regression of $R_{60}$ on $\log(1 + VA)$ with controls.
- **Controls:** Volatility, normalized box width, breakout strength, pre-breakout trend, breakout direction, hour of day UTC.
- **Reporting:** Positive, negative, and null results will be reported honestly.

---

## 19. Limitations
- **Approximate Profile:** Quote volume is distributed across 1-minute TypicalPrice bins rather than trade-level tick data.
- **Pilot Scope:** Single asset (BTCUSDT Spot), single exchange (Binance), fixed 6-month period (2025-01-01 — 2025-06-30). Results cannot be generalized across all crypto or asset classes without further study. If < 30 events occur, it is recorded as a limitation.
- **Association vs Causation:** Study measures association, not causal mechanics.

---

## 20. Planned aggTrades Validation
- Aggregate trades (`aggTrades`) are **not** required for Pilot v0.1.
- A future validation step (post-pilot) will compare 1-minute approximate Volume Ahead against tick-level aggTrades profile on a subset of events to quantify approximation error.

---

## 21. Frozen Parameters Table

| Parameter | Value / Definition |
|---|---|
| Instrument / Exchange | Binance BTCUSDT Spot |
| Timezone | UTC |
| Pilot Period | Fixed 2025-01-01 — 2025-06-30 UTC (warm-up from 2024-11-01) |
| Timeframe (Box & Breakout) | 15 minutes (aggregated from 1m OHLCV; exactly 15 bars, aligned to UTC) |
| Box Length | 32 candles (8 hours: $t-32 \dots t-1$) |
| Box Width Percentile Threshold | $w \le 20$th percentile (linearly interpolated) over preceding 60 calendar days of completed windows ($u < t$) |
| Efficiency Ratio Threshold | $ER < 0.30$ |
| Central Closes Minimum | $\ge 23$ of 32 closes in $[L + 0.1W, H - 0.1W]$ |
| Maximum Box Active Age | 32 subsequent 15-minute candles ($t \dots t+31$) |
| ATR Indicator & Period | Wilder $\text{ATR}(14)$ on 15m, calculated up to $t-1$ |
| Breakout Threshold | $\text{Close}[t] > H + 0.1 \times \text{ATR}[t-1]$ (up) / $\text{Close}[t] < L - 0.1 \times \text{ATR}[t-1]$ (down) |
| Volume Profile Lookback | Previous 30 calendar days (excluding breakout candle $t$) |
| Volume Profile Source | Binance 1-minute `quote_asset_volume` (USDT), $\text{TypicalPrice} = (\text{High} + \text{Low} + \text{Close})/3$ |
| Bin Width | $d = 0.05 \times \text{ATR}[t-1]$ |
| Ahead Region Bins | 20 uniform bins ($k = 0 \dots 19$ for up, $k = -20 \dots -1$ for down) |
| Reference Region Bins | 200 uniform bins ($k = -100 \dots 99$) |
| Primary Exposure | $\log(1 + VA)$ |
| Primary Outcome | Time to $1.0 \times \text{ATR}$ target (max 240 minutes, right-censored) |
| Key Secondary Outcome | Directional return at 60 minutes ($R_{60}$) |

---

## 22. Blocking Questions
- **None.**

---

## 23. Change-Control Rule
- Any modification to parameters requires incrementing the specification version to `v0.2` and recording a formal entry in `[[01 Research/Decisions Log]]`. No parameter may be changed ad-hoc during analysis.
