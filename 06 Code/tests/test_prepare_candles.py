"""Проверки UTC-агрегации и Wilder ATR."""

import unittest

import numpy as np
import pandas as pd

from prepare_candles import aggregate_15m, true_range, wilder_atr


def _minute_bars(count: int) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01 00:00", periods=count, freq="min", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": timestamps,
            "open": np.arange(count, dtype=float) + 100,
            "high": np.arange(count, dtype=float) + 102,
            "low": np.arange(count, dtype=float) + 99,
            "close": np.arange(count, dtype=float) + 101,
            "base_volume": np.ones(count),
            "quote_asset_volume": np.full(count, 2.0),
            "number_of_trades": np.full(count, 3),
            "taker_buy_base_asset_volume": np.full(count, 0.25),
        }
    )


class AggregateCandlesTests(unittest.TestCase):
    def test_aggregates_exact_utc_bars_and_sums_additive_fields(self) -> None:
        minutes = _minute_bars(30).iloc[::-1].reset_index(drop=True)

        bars = aggregate_15m(minutes)

        self.assertEqual(len(bars), 2)
        self.assertTrue(bars["open_time"].is_monotonic_increasing)
        self.assertEqual(str(bars["open_time"].dt.tz), "UTC")
        self.assertEqual(bars["open_time"].tolist(), list(pd.date_range(
            "2025-01-01 00:00", periods=2, freq="15min", tz="UTC"
        )))
        self.assertEqual(bars.loc[0, "open"], 100.0)
        self.assertEqual(bars.loc[0, "high"], 116.0)
        self.assertEqual(bars.loc[0, "low"], 99.0)
        self.assertEqual(bars.loc[0, "close"], 115.0)
        self.assertEqual(bars.loc[0, "base_volume"], 15.0)
        self.assertEqual(bars.loc[0, "quote_asset_volume"], 30.0)
        self.assertEqual(bars.loc[0, "number_of_trades"], 45)
        self.assertEqual(bars.loc[0, "taker_buy_base_asset_volume"], 3.75)

    def test_discards_incomplete_15_minute_interval(self) -> None:
        bars = aggregate_15m(_minute_bars(16))

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars.loc[0, "open_time"], pd.Timestamp("2025-01-01 00:00", tz="UTC"))

    def test_rejects_duplicate_minute_timestamps(self) -> None:
        minutes = _minute_bars(16)
        minutes.loc[15, "open_time"] = minutes.loc[0, "open_time"]

        with self.assertRaisesRegex(ValueError, "повторяющиеся"):
            aggregate_15m(minutes)


class WilderAtrTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candles = pd.DataFrame(
            {
                "high": [10.0, 12.0, 13.0, 12.0, 13.0],
                "low": [8.0, 9.0, 9.0, 10.0, 11.0],
                "close": [9.0, 11.0, 10.0, 11.0, 12.0],
            }
        )

    def test_true_range_uses_previous_close(self) -> None:
        self.assertEqual(true_range(self.candles).tolist(), [2.0, 3.0, 4.0, 2.0, 2.0])

    def test_seed_and_recursive_wilder_smoothing(self) -> None:
        atr = wilder_atr(self.candles, period=3)

        self.assertTrue(atr.iloc[:2].isna().all())
        self.assertAlmostEqual(atr.iloc[2], 3.0)
        self.assertAlmostEqual(atr.iloc[3], 8.0 / 3.0)
        self.assertAlmostEqual(atr.iloc[4], (2 * (8.0 / 3.0) + 2.0) / 3.0)

    def test_future_candles_do_not_change_previous_atr(self) -> None:
        changed = self.candles.copy()
        changed.loc[4, ["high", "low", "close"]] = [1000.0, 1.0, 500.0]

        original_atr = wilder_atr(self.candles, period=3)
        changed_atr = wilder_atr(changed, period=3)

        pd.testing.assert_series_equal(original_atr.iloc[:4], changed_atr.iloc[:4])

    def test_warmup_starts_after_full_seed(self) -> None:
        atr = wilder_atr(self.candles.iloc[:2], period=3)

        self.assertTrue(atr.isna().all())


if __name__ == "__main__":
    unittest.main()