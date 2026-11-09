# Does Historical Volume Ahead Relate to BTCUSDT Breakout Speed?

I study whether historical trading volume in the price area ahead of a breakout is associated with how quickly BTCUSDT moves after breaking out of a consolidation.

This is an observational pilot. It looks for associations; it does not test a trading strategy or establish that volume causes faster or slower price moves.

## The idea in plain language

A Volume Profile groups historical trading volume by price. It can show where trading was concentrated in the past. I focus on the price area just beyond a consolidation boundary: does that area’s historical volume relate to the speed or direction of the move after price breaks out?

The pilot uses 1-minute OHLCV candles. It does not know the exact distribution of trades inside each minute. Instead, it assigns the minute’s entire USDT quote volume to one price bin, using that candle’s typical price. This makes the OHLCV Volume Profile an **approximation** of a trade-level profile.

## Data and method

The frozen Pilot v0.1 uses Binance BTCUSDT Spot 1-minute OHLCV data, with quote volume measured in USDT. The fixed analysis period is 2025-01-01 through 2025-06-30 UTC; the required warm-up begins 2024-11-01. The study identifies breakouts from qualified 8-hour consolidations using completed 15-minute candles.

For each breakout, I build the approximate profile from the 30 calendar days before the breakout candle starts. The interval includes its start and excludes its end. The breakout candle and all later candles are excluded from the profile.

Here is how the price bins are defined:

- The anchor price `B` is the consolidation high for an upward breakout and the consolidation low for a downward breakout.
- The bin width is `d = 0.05 × ATR(14)[t−1]`, using the frozen specification’s Wilder ATR on 15-minute candles. Each bin is a half-open interval of width `d` anchored at `B`.
- For each 1-minute candle, the code calculates `Typical Price = (High + Low + Close) / 3` and assigns the candle’s full `quote_asset_volume` to the bin containing that price. It does not split volume across prices within the minute.
- The ahead region contains 20 bins, or 1 ATR: from `B` to `B + 1 ATR` for an upward breakout, and from `B − 1 ATR` to `B` for a downward breakout.
- The reference region contains 200 bins, or 10 ATR in total: from `B − 5 ATR` to `B + 5 ATR`.

The code sums volume in each region, then divides by the number of bins to get average USDT quote volume per bin. `VA` is ahead density divided by reference density. The primary exposure is `log1p_VA = ln(1 + VA)`; no extra epsilon is added. The profile is marked missing if its 30-day window does not contain exactly 43,200 consecutive 1-minute bars, if the reference density is invalid, or if the full reference region is outside the historical typical-price range.

The primary analysis is a Cox proportional-hazards model for time to a 1 ATR move within 240 minutes, with right censoring when the target is not reached. The secondary analysis is an OLS model of directional 60-minute return (`R60`) with HC3 robust standard errors. UTC hour and breakout direction are categorical predictors. The complete frozen method is in the [Pilot v0.1 Specification](./Pilot%20v0.1%20Specification.md); definitions are in [Definitions](./01%20Research/Definitions.md). The calculation is implemented in [`calculate_profile.py`](./06%20Code/calculate_profile.py).

## Preliminary results

The current event table contains 300 eligible events for these models: 231 reached the 1 ATR target and 69 were right-censored.

- **Cox model:** for a one-unit increase in `log1p_VA`, the estimated hazard ratio was 1.68 (95% CI 0.53–5.31; p = 0.376). The interval includes 1, so this pilot does not show a clear association with time to target. The model also raised a low-variation warning for `volatility` and `pre_trend`. Coefficient-level proportional-hazards diagnostics flagged `breakout_strength` and `pre_trend`; those p-values were not adjusted for multiple checks.
- **R60 model:** the estimated coefficient for a one-unit increase in `log1p_VA` was −0.00152 (HC3 SE 0.00271; 95% CI −0.00686 to 0.00382; p = 0.576). `R60` is a directional 60-minute return expressed as a fraction, not a percentage. The interval includes zero, so this model also does not show a clear association.

These are preliminary, sample-specific estimates. The sample is modest, the profile is approximated from 1-minute bars, and the Cox diagnostics indicate possible proportional-hazards concerns for some controls. The results are observational and do not establish causality.

## What comes next

I have collected Binance aggTrades archives for a future trade-level validation, but I have not analyzed them. The next methodological step is to compare the OHLCV-based profile with a profile calculated from aggTrades, then assess how that approximation affects Volume Ahead. The raw archives are not part of this project’s public files.

## Reproducibility and project contents

The frozen specification records the pilot rules. The [`06 Code`](./06%20Code/) folder contains the project’s analysis scripts and requirements files. The scripts are organized as separate stages; see the [code documentation](./06%20Code/README.md) for usage details.

## Implementation status

`06 Code/run_pilot.py` and `06 Code/plots.py` are placeholders and are not implemented. Neither file was used to produce the results reported here.
