"""Synthetic проверки сборки итоговой event table."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import config
from build_final_event_table import (
    ANALYSIS_FLAG_COLUMNS,
    FIELD_DEFINITIONS,
    OUTCOMES_PATH,
    build_final_event_tables,
    export_final_event_tables,
)


def _candles(count: int = 48) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01 00:00", periods=count, freq="15min", tz="UTC")
    close = 100.0 + np.arange(count, dtype=float) / 10.0
    return pd.DataFrame(
        {
            "open_time": timestamps,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        }
    )


def _events(event_time: pd.Timestamp, count: int = 2) -> pd.DataFrame:
    rows = []
    for position in range(count):
        missing_profile = position == 1
        rows.append(
            {
                "event_id": f"synthetic-{position + 1}",
                "box_start": event_time - pd.Timedelta(hours=8),
                "box_activation": event_time - pd.Timedelta(hours=1),
                "breakout_time": event_time,
                "direction": "upward" if position == 0 else "downward",
                "H": 104.0,
                "L": 99.0,
                "ATR": 2.0,
                "box_width": 5.0,
                "box_age": 2,
                "breakout_close": 105.0,
                "breakout_strength": 0.5,
                "normalized_box_width": 0.05,
                "profile_valid": not missing_profile,
                "profile_missing_reason": "reference_region_outside_historical_range" if missing_profile else None,
                "va_missing": missing_profile,
                "VA": np.nan if missing_profile else 0.5,
                "outcome_missing": False,
                "outcome_missing_reason": None,
                "target_hit": position == 1,
                "right_censored": position == 0,
            }
        )
    return pd.DataFrame(rows)


class FinalEventTableTests(unittest.TestCase):
    def test_controls_use_pre_breakout_candles_and_preserve_existing_width(self) -> None:
        candles = _candles()
        event_time = candles.open_time.iloc[40] + pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
        events = _events(event_time, count=1)
        raw_before, _, _ = build_final_event_tables(events, candles)

        changed_future = candles.copy()
        changed_future.loc[40:, ["open", "high", "low", "close"]] += 500.0
        raw_after, _, _ = build_final_event_tables(events, changed_future)

        t_open = event_time - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
        close_previous = float(candles.loc[candles.open_time.eq(t_open - pd.Timedelta(minutes=15)), "close"].iloc[0])
        close_t_minus_32 = float(candles.loc[candles.open_time.eq(t_open - config.BOX_LENGTH * pd.Timedelta(minutes=15)), "close"].iloc[0])
        self.assertAlmostEqual(raw_before.loc[0, "volatility"], 2.0 / close_previous)
        self.assertAlmostEqual(raw_before.loc[0, "pre_trend"], (close_previous - close_t_minus_32) / close_t_minus_32)
        self.assertAlmostEqual(raw_before.loc[0, "normalized_box_width_atr"], 5.0 / 2.0)
        self.assertEqual(raw_before.loc[0, "normalized_box_width"], 0.05)
        self.assertEqual(raw_before.loc[0, "hour_of_day_utc"], event_time.hour)
        pd.testing.assert_series_equal(
            raw_before.loc[0, ["volatility", "pre_trend", "normalized_box_width_atr", "hour_of_day_utc"]],
            raw_after.loc[0, ["volatility", "pre_trend", "normalized_box_width_atr", "hour_of_day_utc"]],
        )

    def test_analysis_flags_retain_censored_and_profile_invalid_events(self) -> None:
        candles = _candles()
        event_time = candles.open_time.iloc[40] + pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
        raw, analysis, _ = build_final_event_tables(_events(event_time), candles)

        self.assertEqual(len(raw), 2)
        self.assertEqual(len(analysis), 2)
        self.assertTrue(analysis.loc[0, "outcome_available_for_primary_analysis"])
        self.assertTrue(analysis.loc[0, "right_censored"])
        self.assertTrue(analysis.loc[0, "primary_analysis_eligible"])
        self.assertFalse(analysis.loc[1, "profile_available_for_va_analysis"])
        self.assertFalse(analysis.loc[1, "primary_analysis_eligible"])
        self.assertTrue(analysis.loc[1, "target_hit"])
        self.assertIn("profile_missing:", analysis.loc[1, "analysis_exclusion_reason"])
        self.assertTrue(set(ANALYSIS_FLAG_COLUMNS).issubset(analysis.columns))

    def test_missing_pre_event_candle_marks_control_missing_without_dropping_row(self) -> None:
        candles = _candles(20)
        event_time = candles.open_time.iloc[15] + pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
        raw, analysis, _ = build_final_event_tables(_events(event_time, count=1), candles)

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(analysis), 1)
        self.assertEqual(raw.loc[0, "control_missing_reason"], "missing_pre_event_15m_candles")
        self.assertFalse(analysis.loc[0, "controls_available"])
        self.assertFalse(analysis.loc[0, "primary_analysis_eligible"])

    def test_data_dictionary_covers_existing_event_schema(self) -> None:
        columns = pd.read_csv(OUTCOMES_PATH, nrows=0).columns

        self.assertEqual(set(columns).difference(FIELD_DEFINITIONS), set())

    def test_export_round_trips_and_repeats_deterministically(self) -> None:
        candles = _candles()
        event_time = candles.open_time.iloc[40] + pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
        events = _events(event_time)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event_path = root / "input.csv"
            candles_path = root / "candles.parquet"
            raw_path = root / "events_raw.parquet"
            analysis_path = root / "events_analysis.csv"
            dictionary_path = root / "events_data_dictionary.md"
            events.to_csv(event_path, index=False)
            candles.to_parquet(candles_path, index=False)

            export_final_event_tables(event_path, candles_path, raw_path, analysis_path, dictionary_path)
            first_raw = raw_path.read_bytes()
            first_analysis = analysis_path.read_bytes()
            export_final_event_tables(event_path, candles_path, raw_path, analysis_path, dictionary_path)

            raw_result = pd.read_parquet(raw_path)
            analysis_result = pd.read_csv(analysis_path, parse_dates=["breakout_time", "box_start", "box_activation"])
            self.assertEqual(first_raw, raw_path.read_bytes())
            self.assertEqual(first_analysis, analysis_path.read_bytes())
            self.assertEqual(raw_result.event_id.tolist(), events.event_id.tolist())
            self.assertEqual(analysis_result.event_id.tolist(), events.event_id.tolist())
            self.assertEqual(str(raw_result.breakout_time.dt.tz), "UTC")
            self.assertEqual(str(analysis_result.breakout_time.dt.tz), "UTC")
            self.assertTrue(dictionary_path.exists())


if __name__ == "__main__":
    unittest.main()