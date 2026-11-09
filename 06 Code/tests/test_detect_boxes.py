"""Быстрые синтетические проверки Consolidation Box detector."""

import unittest
from pathlib import Path

import pandas as pd

import config
from detect_boxes import _historical_widths, _prepare_frame, detect_boxes


def _bar(open_price: float, high: float, low: float, close: float) -> dict:
    return {"open": open_price, "high": high, "low": low, "close": close}


def _synthetic_candles(
    candidate: str = "narrow",
    activation_close: float = 100.0,
    active_count: int = 0,
    freeze_boundaries: bool = False,
) -> tuple[pd.DataFrame, int]:
    historical_count = (
        config.WIDTH_LOOKBACK_DAYS * 24 * 60 // config.CANDLE_INTERVAL_MINUTES
    )
    prefix_count = historical_count + config.BOX_LENGTH
    rows = [_bar(70.0, 130.0, 70.0, 70.0) for _ in range(prefix_count)]

    candidate_rows = []
    for position in range(config.BOX_LENGTH):
        close = 100.01 if position % 2 == 0 else 99.99
        if candidate == "narrow":
            candidate_rows.append(_bar(close, 100.1, 99.9, close))
        elif candidate == "wide":
            candidate_rows.append(_bar(close, 150.0, 50.0, close))
        elif candidate == "trend":
            close = 99.99 + 0.02 * position / (config.BOX_LENGTH - 1)
            candidate_rows.append(_bar(close, 100.1, 99.9, close))
        elif candidate == "few_central":
            close = 100.0 if position < 10 else (82.0 if position < 21 else 118.0)
            high = 120.0 if position == 0 else close + 0.1
            low = 80.0 if position == 1 else close - 0.1
            candidate_rows.append(_bar(close, high, low, close))
        else:
            raise ValueError(candidate)
    rows.extend(candidate_rows)
    activation_index = len(rows)
    activation_high = max(100.1, activation_close)
    activation_low = min(99.9, activation_close)
    rows.append(_bar(100.0, activation_high, activation_low, activation_close))

    for age in range(1, active_count):
        close = 100.01 if age % 2 else 99.99
        high, low = 100.1, 99.9
        if freeze_boundaries and age == 1:
            high, low = 110.0, 90.0
        rows.append(_bar(close, high, low, close))

    timestamps = pd.date_range(
        config.WARMUP_START,
        periods=len(rows),
        freq=f"{config.CANDLE_INTERVAL_MINUTES}min",
        tz=config.TIMEZONE,
    )
    frame = pd.DataFrame(rows)
    frame.insert(0, "open_time", timestamps)
    return frame, activation_index


class ConsolidationFilterTests(unittest.TestCase):
    def test_narrow_box_passes_width_filter(self) -> None:
        candles, _ = _synthetic_candles(active_count=config.BOX_MAX_AGE)

        result = detect_boxes(candles)

        self.assertEqual(result.diagnostics["boxes"], 1)
        self.assertEqual(result.boxes.iloc[0]["box_status"], "expired")

    def test_too_wide_candidate_is_rejected(self) -> None:
        candles, _ = _synthetic_candles(candidate="wide", active_count=config.BOX_MAX_AGE)

        result = detect_boxes(candles)

        self.assertEqual(result.diagnostics["boxes"], 0)

    def test_efficiency_ratio_at_or_above_threshold_is_rejected(self) -> None:
        candles, _ = _synthetic_candles(candidate="trend", active_count=config.BOX_MAX_AGE)

        result = detect_boxes(candles)

        self.assertEqual(result.diagnostics["boxes"], 0)

    def test_fewer_than_required_central_closes_is_rejected(self) -> None:
        candles, _ = _synthetic_candles(candidate="few_central", active_count=config.BOX_MAX_AGE)

        result = detect_boxes(candles)

        self.assertEqual(result.diagnostics["boxes"], 0)


class BoxLifecycleTests(unittest.TestCase):
    def test_upward_breakout_is_recorded_at_candle_close(self) -> None:
        candles, activation_index = _synthetic_candles(activation_close=101.0)

        result = detect_boxes(candles)

        event = result.events.iloc[0]
        self.assertEqual(event["direction"], "upward")
        self.assertEqual(event["breakout_close"], 101.0)
        self.assertEqual(event["breakout_time"], candles.loc[activation_index, "open_time"] + pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES))
        self.assertEqual(event["box_age"], 1)
        self.assertEqual(str(event["breakout_time"].tz), "UTC")

    def test_downward_breakout_is_recorded(self) -> None:
        candles, _ = _synthetic_candles(activation_close=99.0)

        result = detect_boxes(candles)

        self.assertEqual(result.events.iloc[0]["direction"], "downward")

    def test_boundaries_remain_frozen_after_activation(self) -> None:
        candles, activation_index = _synthetic_candles(
            active_count=3,
            freeze_boundaries=True,
        )
        breakout_index = activation_index + 2
        candles.loc[breakout_index, ["open", "high", "low", "close"]] = [120.0, 120.0, 99.9, 120.0]

        result = detect_boxes(candles)

        event = result.events.iloc[0]
        self.assertAlmostEqual(event["H"], 100.1)
        self.assertAlmostEqual(event["L"], 99.9)
        self.assertEqual(event["box_age"], 3)

    def test_only_first_breakout_closes_the_active_box(self) -> None:
        candles, activation_index = _synthetic_candles(activation_close=101.0, active_count=2)
        second_index = activation_index + 1
        candles.loc[second_index, ["open", "high", "low", "close"]] = [80.0, 80.0, 79.0, 80.0]

        result = detect_boxes(candles)

        self.assertEqual(result.diagnostics["breakout_events"], 1)

    def test_box_expires_after_configured_lifecycle(self) -> None:
        candles, activation_index = _synthetic_candles(active_count=config.BOX_MAX_AGE)

        result = detect_boxes(candles)

        box = result.boxes.iloc[0]
        self.assertEqual(box["box_status"], "expired")
        self.assertEqual(box["box_age_candles"], config.BOX_MAX_AGE)
        expected_termination = candles.loc[activation_index + config.BOX_MAX_AGE - 1, "open_time"] + pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
        self.assertEqual(box["box_termination_time"], expected_termination)

    def test_boxes_do_not_overlap_and_search_resumes_after_expiry(self) -> None:
        candles, activation_index = _synthetic_candles(active_count=2 * config.BOX_MAX_AGE + 1)

        result = detect_boxes(candles)

        self.assertEqual(result.diagnostics["boxes"], 2)
        self.assertEqual(result.diagnostics["overlapping_boxes"], 0)
        activation_delta = result.boxes.iloc[1]["box_activation"] - result.boxes.iloc[0]["box_activation"]
        self.assertEqual(activation_delta, config.BOX_MAX_AGE * pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES))
        self.assertEqual(result.boxes.iloc[1]["box_activation"], result.boxes.iloc[0]["box_termination_time"])


class DetectorLeakageTests(unittest.TestCase):
    def test_activation_and_lifecycle_changes_do_not_change_candidate_qualification(self) -> None:
        candles, activation_index = _synthetic_candles(active_count=config.BOX_MAX_AGE)
        changed = candles.copy()
        changed.loc[activation_index:, ["open", "high", "low", "close"]] = [
            100.04,
            130.0,
            70.0,
            100.05,
        ]

        original_box = detect_boxes(candles).boxes.iloc[0]
        changed_box = detect_boxes(changed).boxes.iloc[0]
        qualification_fields = (
            "box_start",
            "box_activation",
            "H",
            "L",
            "box_width",
            "normalized_box_width",
            "efficiency_ratio",
            "central_closes_count",
        )

        self.assertEqual(original_box["box_status"], "expired")
        self.assertEqual(changed_box["box_status"], "expired")
        for field in qualification_fields:
            self.assertEqual(original_box[field], changed_box[field], field)

    def test_future_changes_do_not_change_past_events(self) -> None:
        candles, activation_index = _synthetic_candles(activation_close=101.0)
        extended_rows = [
            _bar(100.0 + position, 101.0 + position, 99.0 + position, 100.0 + position)
            for position in range(40)
        ]
        extended_times = pd.date_range(
            candles["open_time"].iloc[-1] + pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES),
            periods=len(extended_rows),
            freq=f"{config.CANDLE_INTERVAL_MINUTES}min",
        )
        future = pd.DataFrame(extended_rows)
        future.insert(0, "open_time", extended_times)
        changed = pd.concat([candles, future], ignore_index=True)
        changed.loc[activation_index + 1 :, ["open", "high", "low", "close"]] = [
            500.0,
            600.0,
            400.0,
            550.0,
        ]

        original_event = detect_boxes(candles).events.iloc[0]
        changed_event = detect_boxes(changed).events.iloc[0]

        for column in ("box_start", "box_activation", "breakout_time", "direction", "H", "L", "ATR", "breakout_close", "breakout_strength"):
            self.assertEqual(original_event[column], changed_event[column])

    def test_candidate_width_uses_only_prior_activation_windows(self) -> None:
        candles, activation_index = _synthetic_candles(activation_close=101.0)
        frame = _prepare_frame(candles)
        rolling_high = frame["high"].rolling(config.BOX_LENGTH, min_periods=config.BOX_LENGTH).max().shift(1)
        rolling_low = frame["low"].rolling(config.BOX_LENGTH, min_periods=config.BOX_LENGTH).min().shift(1)
        widths = (rolling_high - rolling_low) / frame["close"].shift(1)
        width_history = pd.Series(widths.to_numpy(), index=pd.DatetimeIndex(frame["open_time"])).dropna()
        historical = _historical_widths(frame, activation_index, width_history)
        result = detect_boxes(candles)

        self.assertIsNotNone(historical)
        self.assertEqual(len(historical), config.WIDTH_LOOKBACK_DAYS * 24 * 60 // config.CANDLE_INTERVAL_MINUTES)
        self.assertLess(historical.index[-1], candles.loc[activation_index, "open_time"])
        self.assertEqual(result.events.iloc[0]["box_activation"], candles.loc[activation_index, "open_time"])
        self.assertAlmostEqual(result.events.iloc[0]["box_width"], 0.2)

    def test_actual_pilot_has_complete_width_history(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        dataset_name = (
            f"binance_btcusdt_spot_15m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
        )
        dataset_path = project_root / "05 Data" / "processed" / dataset_name
        if not dataset_path.exists():
            self.skipTest("Run run_block4.py first to create the local 15m Parquet")

        frame = _prepare_frame(pd.read_parquet(dataset_path))
        timestamps = pd.DatetimeIndex(frame["open_time"])
        rolling_high = frame["high"].rolling(
            config.BOX_LENGTH,
            min_periods=config.BOX_LENGTH,
        ).max().shift(1)
        rolling_low = frame["low"].rolling(
            config.BOX_LENGTH,
            min_periods=config.BOX_LENGTH,
        ).min().shift(1)
        widths = (rolling_high - rolling_low) / frame["close"].shift(1)
        width_times = pd.DatetimeIndex(timestamps[widths.notna()])
        start = pd.Timestamp(config.PILOT_START, tz=config.TIMEZONE)
        end = pd.Timestamp(config.PILOT_END, tz=config.TIMEZONE) + pd.Timedelta(days=1)
        candidate_times = timestamps[(timestamps >= start) & (timestamps < end)]

        history_start = candidate_times - pd.Timedelta(days=config.WIDTH_LOOKBACK_DAYS)
        left = width_times.searchsorted(history_start, side="left")
        right = width_times.searchsorted(candidate_times, side="left")
        expected_widths = (
            config.WIDTH_LOOKBACK_DAYS
            * 24
            * 60
            // config.CANDLE_INTERVAL_MINUTES
        )
        required_start = history_start - config.BOX_LENGTH * pd.Timedelta(
            minutes=config.CANDLE_INTERVAL_MINUTES
        )
        sufficient = (required_start >= timestamps[0]) & ((right - left) == expected_widths)
        valid_positions = sufficient.nonzero()[0]
        sufficient[valid_positions] &= (
            (width_times.take(left[valid_positions]) == history_start[valid_positions])
            & (width_times.take(right[valid_positions] - 1) == candidate_times[valid_positions] - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES))
        )

        insufficient_count = int((~sufficient).sum())
        self.assertGreater(len(candidate_times), 0)
        self.assertEqual(insufficient_count, 0)


if __name__ == "__main__":
    unittest.main()