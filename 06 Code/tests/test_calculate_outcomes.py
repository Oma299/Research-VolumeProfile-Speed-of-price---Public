"""Синтетические проверки post-breakout outcomes."""

import unittest

import numpy as np
import pandas as pd

import config
from calculate_outcomes import calculate_event_outcomes, calculate_outcomes


EVENT_TIME = pd.Timestamp("2025-01-01 00:00", tz="UTC")


def _event(direction: str = "upward") -> dict:
    return {
        "event_id": "outcome-synthetic-001",
        "breakout_time": EVENT_TIME,
        "direction": direction,
        "H": 100.0 if direction == "upward" else 110.0,
        "L": 90.0 if direction == "upward" else 100.0,
        "ATR": 10.0,
        "breakout_close": 100.0,
        "profile_valid": False,
        "VA": np.nan,
    }


def _minutes(count: int = config.MAX_HORIZON_MINUTES) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open_time": pd.date_range(
                EVENT_TIME,
                periods=count,
                freq=f"{config.SOURCE_INTERVAL_MINUTES}min",
            ),
            "open": np.full(count, 100.0),
            "high": np.full(count, 101.0),
            "low": np.full(count, 99.0),
            "close": np.full(count, 100.0),
        }
    )


class OutcomeCalculationTests(unittest.TestCase):
    def test_up_and_down_targets_use_event_atr(self) -> None:
        upward = _minutes()
        upward.loc[0, ["high", "close"]] = [110.0, 101.0]
        downward = _minutes()
        downward.loc[0, ["low", "close"]] = [90.0, 99.0]

        up_result = calculate_event_outcomes(_event("upward"), upward)
        down_result = calculate_event_outcomes(_event("downward"), downward)

        self.assertEqual(up_result["target_price"], 110.0)
        self.assertEqual(down_result["target_price"], 90.0)
        self.assertTrue(up_result["target_hit"])
        self.assertTrue(down_result["target_hit"])

    def test_target_hit_in_first_minute_sets_duration_fields(self) -> None:
        minutes = _minutes()
        minutes.loc[0, "high"] = 110.0

        result = calculate_event_outcomes(_event(), minutes)

        self.assertTrue(result["target_hit"])
        self.assertEqual(result["time_to_target_minutes"], 1)
        self.assertEqual(result["observed_time_minutes"], 1)
        self.assertFalse(result["right_censored"])
        self.assertEqual(result["target_hit_bar_open_time_utc"], EVENT_TIME)

    def test_target_hit_on_minute_240_is_not_censored(self) -> None:
        minutes = _minutes()
        minutes.loc[config.MAX_HORIZON_MINUTES - 1, "high"] = 110.0

        result = calculate_event_outcomes(_event(), minutes)

        self.assertTrue(result["target_hit"])
        self.assertEqual(result["time_to_target_minutes"], config.MAX_HORIZON_MINUTES)
        self.assertEqual(result["observed_time_minutes"], config.MAX_HORIZON_MINUTES)
        self.assertFalse(result["right_censored"])

    def test_full_window_without_target_is_right_censored_at_240(self) -> None:
        result = calculate_event_outcomes(_event(), _minutes())

        self.assertFalse(result["target_hit"])
        self.assertTrue(result["right_censored"])
        self.assertEqual(result["observed_time_minutes"], config.MAX_HORIZON_MINUTES)
        self.assertTrue(np.isnan(result["time_to_target_minutes"]))
        self.assertFalse(result["outcome_missing"])

    def test_breakout_candle_is_not_an_outcome_bar(self) -> None:
        minutes = _minutes()
        breakout_candle = pd.DataFrame(
            {
                "open_time": [EVENT_TIME - pd.Timedelta(minutes=1)],
                "open": [100.0],
                "high": [10000.0],
                "low": [1.0],
                "close": [100.0],
            }
        )

        result = calculate_event_outcomes(
            _event(),
            pd.concat([breakout_candle, minutes], ignore_index=True),
        )

        self.assertFalse(result["target_hit"])
        self.assertAlmostEqual(result["mfe_240"], 0.01)
        self.assertAlmostEqual(result["mae_240"], -0.01)

    def test_directional_returns_use_exact_endpoint_candles(self) -> None:
        minutes = _minutes()
        for horizon, close in zip(config.RETURN_HORIZONS_MINUTES, (101.0, 102.0, 103.0, 104.0, 105.0)):
            minutes.loc[horizon - 1, ["high", "close"]] = [close, close]

        result = calculate_event_outcomes(_event(), minutes)

        for horizon, close in zip(config.RETURN_HORIZONS_MINUTES, (101.0, 102.0, 103.0, 104.0, 105.0)):
            self.assertAlmostEqual(result[f"r_{horizon}"], (close - 100.0) / 100.0)

    def test_mfe_and_mae_are_directional_returns(self) -> None:
        upward = _minutes()
        upward.loc[0, ["high", "low"]] = [112.0, 95.0]
        downward = _minutes()
        downward.loc[0, ["high", "low"]] = [105.0, 88.0]

        up_result = calculate_event_outcomes(_event("upward"), upward)
        down_result = calculate_event_outcomes(_event("downward"), downward)

        self.assertAlmostEqual(up_result["mfe_240"], 0.12)
        self.assertAlmostEqual(up_result["mae_240"], -0.05)
        self.assertAlmostEqual(down_result["mfe_240"], 0.12)
        self.assertAlmostEqual(down_result["mae_240"], -0.05)

    def test_return_to_box_uses_directional_close_rule(self) -> None:
        upward = _minutes()
        upward.loc[2, "close"] = 99.0
        downward = _minutes()
        downward.loc[2, "close"] = 101.0

        up_result = calculate_event_outcomes(_event("upward"), upward)
        down_result = calculate_event_outcomes(_event("downward"), downward)

        self.assertTrue(up_result["return_to_box"])
        self.assertEqual(up_result["time_to_return_box_minutes"], 3)
        self.assertTrue(down_result["return_to_box"])
        self.assertEqual(down_result["time_to_return_box_minutes"], 3)

    def test_same_minute_target_and_return_is_ambiguous(self) -> None:
        for direction in ("upward", "downward"):
            with self.subTest(direction=direction):
                minutes = _minutes()
                if direction == "upward":
                    minutes.loc[0, ["high", "close"]] = [110.0, 99.0]
                else:
                    minutes.loc[0, ["low", "close"]] = [90.0, 101.0]

                result = calculate_event_outcomes(_event(direction), minutes)

                self.assertTrue(result["target_hit"])
                self.assertTrue(result["return_to_box"])
                self.assertTrue(result["ambiguous_intrabar"])
                self.assertEqual(result["target_hit_bar_open_time_utc"], result["return_to_box_bar_open_time_utc"])

    def test_repeated_return_in_target_minute_is_not_ambiguous_when_first_return_was_earlier(self) -> None:
        for direction in ("upward", "downward"):
            with self.subTest(direction=direction):
                minutes = _minutes()
                if direction == "upward":
                    minutes.loc[0, "close"] = 99.0
                    minutes.loc[2, ["high", "close"]] = [110.0, 99.0]
                else:
                    minutes.loc[0, "close"] = 101.0
                    minutes.loc[2, ["low", "close"]] = [90.0, 101.0]

                result = calculate_event_outcomes(_event(direction), minutes)

                self.assertEqual(result["time_to_return_box_minutes"], 1)
                self.assertEqual(result["time_to_target_minutes"], 3)
                self.assertFalse(result["ambiguous_intrabar"])

    def test_target_before_first_return_is_not_ambiguous(self) -> None:
        for direction in ("upward", "downward"):
            with self.subTest(direction=direction):
                minutes = _minutes()
                if direction == "upward":
                    minutes.loc[1, "high"] = 110.0
                    minutes.loc[2, "close"] = 99.0
                else:
                    minutes.loc[1, "low"] = 90.0
                    minutes.loc[2, "close"] = 101.0

                result = calculate_event_outcomes(_event(direction), minutes)

                self.assertEqual(result["time_to_target_minutes"], 2)
                self.assertEqual(result["time_to_return_box_minutes"], 3)
                self.assertFalse(result["ambiguous_intrabar"])

    def test_target_before_gap_is_preserved_but_window_is_incomplete(self) -> None:
        minutes = _minutes()
        minutes.loc[1, "high"] = 110.0
        minutes = minutes.drop(index=10).reset_index(drop=True)

        result = calculate_event_outcomes(_event(), minutes)

        self.assertTrue(result["outcome_missing"])
        self.assertEqual(result["outcome_missing_reason"], "missing_future_minute")
        self.assertTrue(result["target_hit"])
        self.assertEqual(result["time_to_target_minutes"], 2)
        self.assertEqual(result["observed_time_minutes"], 2)
        self.assertFalse(result["right_censored"])
        self.assertFalse(result["ambiguous_intrabar"])
        self.assertTrue(np.isnan(result["mfe_240"]))
        self.assertTrue(np.isnan(result["mae_240"]))

    def test_target_after_gap_does_not_claim_first_hit(self) -> None:
        minutes = _minutes()
        minutes.loc[2, "high"] = 110.0
        minutes = minutes.drop(index=1).reset_index(drop=True)

        result = calculate_event_outcomes(_event(), minutes)

        self.assertTrue(result["outcome_missing"])
        self.assertEqual(result["outcome_missing_reason"], "missing_future_minute")
        self.assertTrue(pd.isna(result["target_hit"]))
        self.assertTrue(np.isnan(result["time_to_target_minutes"]))
        self.assertTrue(np.isnan(result["observed_time_minutes"]))
        self.assertTrue(pd.isna(result["right_censored"]))
        self.assertTrue(pd.isna(result["ambiguous_intrabar"]))

    def test_exact_endpoint_return_is_available_despite_intermediate_gap(self) -> None:
        minutes = _minutes()
        minutes.loc[config.RETURN_HORIZONS_MINUTES[0] - 1, ["high", "close"]] = [105.0, 105.0]
        minutes = minutes.drop(index=5).reset_index(drop=True)

        result = calculate_event_outcomes(_event(), minutes)

        self.assertTrue(result["outcome_missing"])
        self.assertAlmostEqual(result["r_15"], 0.05)
        self.assertAlmostEqual(result["r_30"], 0.0)

    def test_gap_without_return_does_not_become_return_false(self) -> None:
        minutes = _minutes().drop(index=5).reset_index(drop=True)

        result = calculate_event_outcomes(_event(), minutes)

        self.assertTrue(result["outcome_missing"])
        self.assertTrue(pd.isna(result["return_to_box"]))
        self.assertTrue(np.isnan(result["time_to_return_box_minutes"]))
        self.assertTrue(pd.isna(result["ambiguous_intrabar"]))

    def test_return_to_box_after_gap_is_not_claimed_as_first_return(self) -> None:
        minutes = _minutes()
        minutes.loc[3, "close"] = 101.0
        minutes = minutes.drop(index=1).reset_index(drop=True)

        result = calculate_event_outcomes(_event("downward"), minutes)

        self.assertTrue(result["outcome_missing"])
        self.assertTrue(pd.isna(result["return_to_box"]))
        self.assertTrue(np.isnan(result["time_to_return_box_minutes"]))


    def test_dataset_end_is_distinct_from_full_window_censoring(self) -> None:
        result = calculate_event_outcomes(_event(), _minutes(10))

        self.assertTrue(result["outcome_missing"])
        self.assertEqual(result["outcome_missing_reason"], "dataset_end_before_240_minutes")
        self.assertTrue(pd.isna(result["target_hit"]))
        self.assertTrue(pd.isna(result["right_censored"]))

    def test_outcome_timestamps_are_utc_and_repeatable(self) -> None:
        event = _event()
        minutes = _minutes()
        minutes.loc[0, "high"] = 110.0

        first = calculate_event_outcomes(event, minutes)
        second = calculate_event_outcomes(event, minutes)

        self.assertEqual(str(first["target_hit_bar_open_time_utc"].tz), "UTC")
        pd.testing.assert_series_equal(pd.Series(first), pd.Series(second))

    def test_batch_preserves_events_without_valid_profile(self) -> None:
        events = pd.DataFrame([_event("upward"), _event("downward")])
        result = calculate_outcomes(events, _minutes())

        self.assertEqual(result.event_id.tolist(), events.event_id.tolist())
        self.assertEqual(len(result), len(events))
        self.assertTrue(result.profile_valid.eq(False).all())


if __name__ == "__main__":
    unittest.main()