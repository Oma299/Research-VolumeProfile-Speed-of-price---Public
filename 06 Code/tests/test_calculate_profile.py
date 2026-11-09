"""Проверки approximate Volume Profile и Volume Ahead."""

import unittest

import numpy as np
import pandas as pd

import config
from calculate_profile import (
    calculate_event_profile,
    calculate_volume_ahead,
    price_bin_indices,
    typical_price,
)


def _event(direction: str = "upward", atr: float = 20.0) -> dict:
    return {
        "event_id": "synthetic-001",
        "breakout_time": pd.Timestamp("2025-01-31 00:15", tz="UTC"),
        "direction": direction,
        "H": 1000.0,
        "L": 1000.0,
        "ATR": atr,
        "breakout_close": 1025.0 if direction == "upward" else 975.0,
    }


def _profile_bars(direction: str = "upward") -> pd.DataFrame:
    profile_end = pd.Timestamp("2025-01-31 00:00", tz="UTC")
    profile_start = profile_end - pd.Timedelta(days=config.PROFILE_LOOKBACK_DAYS)
    count = config.PROFILE_EXPECTED_MINUTES
    prices = np.full(count, 1050.0)
    volumes = np.ones(count)
    prices[0] = 900.0
    prices[-1] = 1100.0
    if direction == "upward":
        prices[1] = 1000.0
        prices[2] = 1019.0
        volumes[1:3] = [2.0, 3.0]
    else:
        prices[1] = 980.0
        prices[2] = 999.0
        volumes[1:3] = [2.0, 3.0]
    return pd.DataFrame(
        {
            "open_time": pd.date_range(
                profile_start,
                periods=count,
                freq=f"{config.SOURCE_INTERVAL_MINUTES}min",
            ),
            "high": prices,
            "low": prices,
            "close": prices,
            "quote_asset_volume": volumes,
        }
    )


class ProfileCalculationTests(unittest.TestCase):
    def test_typical_price_uses_high_low_close(self) -> None:
        candles = pd.DataFrame({"high": [101.0], "low": [98.0], "close": [100.0]})

        result = typical_price(candles)

        self.assertAlmostEqual(result.iloc[0], (101.0 + 98.0 + 100.0) / 3.0)

    def test_bin_indices_are_floor_based_and_boundary_anchored(self) -> None:
        prices = [1000.0, 1019.0, 1020.0, 999.0, 900.0, 1100.0]

        bins = price_bin_indices(prices, boundary=1000.0, bin_width=1.0)

        self.assertEqual(bins.tolist(), [0, 19, 20, -1, -100, 100])

    def test_upward_volume_ahead_uses_bins_zero_through_nineteen(self) -> None:
        result = calculate_event_profile(_event("upward"), _profile_bars("upward"))

        self.assertTrue(result["profile_valid"])
        self.assertEqual(result["profile_boundary"], 1000.0)
        self.assertEqual(result["profile_bin_width"], 1.0)
        self.assertEqual(result["ahead_volume"], 5.0)
        self.assertEqual(result["reference_volume"], 43202.0)
        self.assertAlmostEqual(result["ahead_density"], 5.0 / config.AHEAD_BIN_COUNT)
        self.assertAlmostEqual(result["reference_density"], 43202.0 / config.REFERENCE_BIN_COUNT)
        self.assertAlmostEqual(result["VA"], result["ahead_density"] / result["reference_density"])
        self.assertAlmostEqual(result["log1p_VA"], np.log1p(result["VA"]))

    def test_downward_volume_ahead_uses_bins_minus_twenty_through_minus_one(self) -> None:
        result = calculate_event_profile(_event("downward"), _profile_bars("downward"))

        self.assertTrue(result["profile_valid"])
        self.assertEqual(result["profile_boundary"], 1000.0)
        self.assertEqual(result["ahead_volume"], 5.0)
        self.assertEqual(result["reference_volume"], 43202.0)

    def test_breakout_candle_and_future_minutes_are_excluded(self) -> None:
        event = _event("upward")
        bars = _profile_bars("upward")
        profile_end = event["breakout_time"] - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
        extra = pd.DataFrame(
            {
                "open_time": [profile_end, profile_end + pd.Timedelta(minutes=1)],
                "high": [1e9, 1e9],
                "low": [1e9, 1e9],
                "close": [1e9, 1e9],
                "quote_asset_volume": [1e12, 1e12],
            }
        )

        baseline = calculate_event_profile(event, bars)
        with_future = calculate_event_profile(event, pd.concat([bars, extra], ignore_index=True))

        self.assertEqual(baseline["profile_end"], profile_end)
        self.assertEqual(baseline["profile_observed_minutes"], config.PROFILE_EXPECTED_MINUTES)
        self.assertEqual(baseline["ahead_volume"], with_future["ahead_volume"])
        self.assertEqual(baseline["reference_volume"], with_future["reference_volume"])
        self.assertEqual(baseline["VA"], with_future["VA"])

    def test_lookback_is_exactly_thirty_calendar_days_half_open(self) -> None:
        result = calculate_event_profile(_event(), _profile_bars())

        self.assertEqual(result["profile_end"], pd.Timestamp("2025-01-31 00:00", tz="UTC"))
        self.assertEqual(
            result["profile_start"],
            result["profile_end"] - pd.Timedelta(days=config.PROFILE_LOOKBACK_DAYS),
        )
        self.assertEqual(result["profile_observed_minutes"], config.PROFILE_EXPECTED_MINUTES)
        self.assertTrue(result["profile_start"] <= result["profile_end"])

    def test_zero_and_missing_atr_are_invalid(self) -> None:
        bars = _profile_bars()
        for atr in (0.0, np.nan, None):
            with self.subTest(atr=atr):
                result = calculate_event_profile(_event(atr=atr), bars)
                self.assertFalse(result["profile_valid"])
                self.assertTrue(result["va_missing"])
                self.assertEqual(result["va_missing_reason"], "invalid_bin_width")

    def test_insufficient_history_is_explicit_not_silently_zeroed(self) -> None:
        bars = _profile_bars().iloc[1:].reset_index(drop=True)

        result = calculate_event_profile(_event(), bars)

        self.assertFalse(result["profile_valid"])
        self.assertTrue(result["va_missing"])
        self.assertEqual(result["profile_missing_reason"], "incomplete_profile_window")
        self.assertEqual(result["va_missing_reason"], "incomplete_profile_window")
        self.assertTrue(np.isnan(result["ahead_volume"]))

    def test_reference_region_outside_observed_price_range_is_explicit(self) -> None:
        bars = _profile_bars()
        bars.loc[:, ["high", "low", "close"]] = 1000.0

        result = calculate_event_profile(_event(), bars)

        self.assertFalse(result["profile_valid"])
        self.assertEqual(result["profile_missing_reason"], "reference_region_outside_historical_range")

    def test_zero_reference_density_is_explicit(self) -> None:
        bars = _profile_bars()
        bars["quote_asset_volume"] = 0.0

        result = calculate_event_profile(_event(), bars)

        self.assertFalse(result["profile_valid"])
        self.assertEqual(result["profile_missing_reason"], "zero_or_invalid_reference_density")
        self.assertTrue(np.isnan(result["VA"]))

    def test_profile_timestamps_remain_timezone_aware_utc(self) -> None:
        result = calculate_event_profile(_event(), _profile_bars())

        self.assertEqual(str(result["profile_start"].tz), "UTC")
        self.assertEqual(str(result["profile_end"].tz), "UTC")

    def test_repeated_calculation_is_deterministic(self) -> None:
        event = _event()
        bars = _profile_bars()

        first = calculate_event_profile(event, bars)
        second = calculate_event_profile(event, bars)

        pd.testing.assert_series_equal(pd.Series(first), pd.Series(second))

    def test_table_application_preserves_events_and_marks_each_profile(self) -> None:
        events = pd.DataFrame([_event("upward"), _event("downward")])
        bars = _profile_bars("upward")

        result = calculate_volume_ahead(events, bars)

        self.assertEqual(len(result), len(events))
        self.assertEqual(result["event_id"].tolist(), events["event_id"].tolist())
        self.assertEqual(result["profile_valid"].tolist(), [True, True])
        self.assertEqual(str(result["profile_start"].dt.tz), "UTC")


if __name__ == "__main__":
    unittest.main()