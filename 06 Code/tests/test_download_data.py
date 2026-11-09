"""Проверки качества минутных данных Binance."""

import unittest

import pandas as pd

from download_data import _to_utc_timestamps, validate_data


def _frame(times: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open_time": pd.to_datetime(times, utc=True),
            "open": [100.0] * len(times),
            "high": [101.0] * len(times),
            "low": [99.0] * len(times),
            "close": [100.5] * len(times),
            "base_volume": [1.0] * len(times),
            "quote_asset_volume": [100.0] * len(times),
        }
    )


class DataQualityTests(unittest.TestCase):
    start = "2025-01-01 00:00:00+00:00"
    end = "2025-01-01 00:02:00+00:00"

    def test_converts_millisecond_and_microsecond_binance_timestamps(self) -> None:
        values = pd.Series([1730419200000, 1735689600000000])

        timestamps = _to_utc_timestamps(values)

        self.assertEqual(timestamps.iloc[0], pd.Timestamp("2024-11-01 00:00:00+00:00"))
        self.assertEqual(timestamps.iloc[1], pd.Timestamp("2025-01-01 00:00:00+00:00"))

    def test_complete_valid_range_passes_and_counts_zero_volume(self) -> None:
        frame = _frame(
            [
                "2025-01-01 00:00:00+00:00",
                "2025-01-01 00:01:00+00:00",
                "2025-01-01 00:02:00+00:00",
            ]
        )
        frame.loc[1, "quote_asset_volume"] = 0.0

        metrics, missing = validate_data(frame, self.start, self.end)

        self.assertTrue(metrics["checks_passed"])
        self.assertEqual(metrics["expected_rows"], 3)
        self.assertEqual(metrics["actual_rows"], 3)
        self.assertEqual(metrics["zero_quote_volume_rows"], 1)
        self.assertEqual(len(missing), 0)

    def test_reports_duplicates_missing_minutes_and_out_of_period_rows(self) -> None:
        frame = _frame(
            [
                "2025-01-01 00:00:00+00:00",
                "2025-01-01 00:02:00+00:00",
                "2025-01-01 00:02:00+00:00",
                "2025-01-01 00:03:00+00:00",
            ]
        )

        metrics, missing = validate_data(frame, self.start, self.end)

        self.assertFalse(metrics["checks_passed"])
        self.assertEqual(metrics["duplicate_open_time_rows"], 1)
        self.assertEqual(metrics["missing_minute_intervals"], 1)
        self.assertEqual(metrics["timestamps_outside_period_rows"], 1)
        self.assertEqual(missing[0], pd.Timestamp("2025-01-01 00:01:00+00:00"))

    def test_reports_invalid_ohlc_nonpositive_prices_and_negative_volume(self) -> None:
        frame = _frame(["2025-01-01 00:00:00+00:00", "2025-01-01 00:01:00+00:00", "2025-01-01 00:02:00+00:00"])
        frame.loc[0, "high"] = 98.0
        frame.loc[0, "low"] = 97.0
        frame.loc[1, "low"] = 0.0
        frame.loc[2, "base_volume"] = -1.0

        metrics, _ = validate_data(frame, self.start, self.end)

        self.assertFalse(metrics["checks_passed"])
        self.assertEqual(metrics["high_below_max_open_close_low_rows"], 1)
        self.assertEqual(metrics["high_below_low_rows"], 0)
        self.assertEqual(metrics["ohlc_violation_rows"], 1)
        self.assertEqual(metrics["nonpositive_price_rows"], 1)
        self.assertEqual(metrics["negative_base_volume_rows"], 1)
        self.assertEqual(metrics["negative_volume_rows"], 1)


if __name__ == "__main__":
    unittest.main()