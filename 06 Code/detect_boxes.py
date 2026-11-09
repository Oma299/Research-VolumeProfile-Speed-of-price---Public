"""Детектор Consolidation Box и первого breakout по Pilot v0.1."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

import config
from prepare_candles import wilder_atr


@dataclass
class DetectorResult:
    events: pd.DataFrame
    boxes: pd.DataFrame
    diagnostics: Dict[str, int]


def _prepare_frame(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"open_time", "open", "high", "low", "close"}
    missing = required.difference(candles.columns)
    if missing:
        raise ValueError(f"В 15m данных отсутствуют колонки: {sorted(missing)}")
    frame = candles.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True, errors="coerce")
    if frame["open_time"].isna().any():
        raise ValueError("15m данные содержат некорректный open_time")
    if frame["open_time"].duplicated().any():
        raise ValueError("15m данные содержат повторяющиеся open_time")
    if not frame["open_time"].is_monotonic_increasing:
        raise ValueError("15m timestamps должны быть отсортированы")
    interval = pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    if len(frame) > 1 and not frame["open_time"].diff().iloc[1:].eq(interval).all():
        raise ValueError("15m данные содержат пропущенные интервалы")
    numeric = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all() or (numeric <= 0).any().any():
        raise ValueError("OHLC содержит отсутствующие или неположительные значения")
    invalid_ohlc = (
        (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1))
        | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))
        | (numeric["low"] > numeric["high"])
    )
    if invalid_ohlc.any():
        raise ValueError("Обнаружено нарушение OHLC")
    frame.loc[:, ["open", "high", "low", "close"]] = numeric
    return frame.reset_index(drop=True)


def _historical_widths(
    frame: pd.DataFrame,
    index: int,
    width_by_activation: pd.Series,
) -> Optional[pd.Series]:
    interval = pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    activation = frame.at[index, "open_time"]
    history_start = activation - pd.Timedelta(days=config.WIDTH_LOOKBACK_DAYS)
    required_start = history_start - config.BOX_LENGTH * interval
    if required_start < frame.at[0, "open_time"]:
        return None
    historical = width_by_activation.loc[
        (width_by_activation.index >= history_start)
        & (width_by_activation.index < activation)
    ]
    expected_count = (
        config.WIDTH_LOOKBACK_DAYS
        * 24
        * 60
        // config.CANDLE_INTERVAL_MINUTES
    )
    if len(historical) != expected_count:
        return None
    if historical.index[0] != history_start or historical.index[-1] != activation - interval:
        return None
    return historical


def _candidate_metrics(
    frame: pd.DataFrame,
    index: int,
    historical_widths: pd.Series,
) -> Optional[Dict[str, Any]]:
    width_threshold = historical_widths.quantile(
        config.WIDTH_QUANTILE,
        interpolation="linear",
    )
    window = frame.iloc[index - config.BOX_LENGTH : index]
    high = float(window["high"].max())
    low = float(window["low"].min())
    width = high - low
    previous_close = float(frame.at[index - 1, "close"])
    if width <= 0 or previous_close <= 0:
        return None
    normalized_width = width / previous_close
    if normalized_width > width_threshold:
        return None

    closes = window["close"].to_numpy(dtype=float)
    movement = float(np.abs(np.diff(closes)).sum())
    if movement == 0:
        return None
    efficiency_ratio = abs(float(closes[-1] - closes[0])) / movement
    if efficiency_ratio >= config.ER_THRESHOLD:
        return None

    central_low = low + config.CENTRAL_REGION_FRACTION * width
    central_high = high - config.CENTRAL_REGION_FRACTION * width
    central_count = int(((closes >= central_low) & (closes <= central_high)).sum())
    if central_count < config.CENTRAL_CLOSES_MIN:
        return None

    return {
        "H": high,
        "L": low,
        "box_width": width,
        "normalized_box_width": normalized_width,
        "efficiency_ratio": efficiency_ratio,
        "central_closes_count": central_count,
        "box_start": frame.at[index - config.BOX_LENGTH, "open_time"],
        "box_activation": frame.at[index, "open_time"],
    }


def _event_columns() -> List[str]:
    return [
        "event_id",
        "box_start",
        "box_activation",
        "breakout_time",
        "direction",
        "H",
        "L",
        "ATR",
        "box_width",
        "box_age",
        "breakout_close",
        "breakout_strength",
        "box_start_time",
        "box_activation_time",
        "breakout_time_utc",
        "breakout_direction",
        "box_termination_time",
        "box_status",
        "box_age_candles",
        "normalized_box_width",
        "central_closes_count",
        "efficiency_ratio",
    ]


def detect_boxes(candles: pd.DataFrame) -> DetectorResult:
    """Найти qualifying boxes, breakout events и полностью истёкшие boxes."""
    frame = _prepare_frame(candles)
    interval = pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    closes = frame["close"].to_numpy(dtype=float)
    rolling_high = frame["high"].rolling(config.BOX_LENGTH, min_periods=config.BOX_LENGTH).max().shift(1)
    rolling_low = frame["low"].rolling(config.BOX_LENGTH, min_periods=config.BOX_LENGTH).min().shift(1)
    previous_close = frame["close"].shift(1)
    width_values = ((rolling_high - rolling_low) / previous_close).to_numpy(dtype=float)
    width_by_activation = pd.Series(
        width_values,
        index=pd.DatetimeIndex(frame["open_time"]),
    ).dropna()
    atr_values = wilder_atr(frame).to_numpy(dtype=float)

    event_rows: List[Dict[str, Any]] = []
    box_rows: List[Dict[str, Any]] = []
    insufficient_history = 0
    incomplete_boxes = 0
    index = config.BOX_LENGTH
    while index < len(frame):
        historical_widths = _historical_widths(frame, index, width_by_activation)
        if historical_widths is None:
            insufficient_history += 1
            index += 1
            continue
        metrics = _candidate_metrics(frame, index, historical_widths)
        if metrics is None:
            index += 1
            continue

        activation_index = index
        last_index = min(index + config.BOX_MAX_AGE, len(frame)) - 1
        box_event: Optional[Dict[str, Any]] = None
        for breakout_index in range(activation_index, last_index + 1):
            atr_index = breakout_index - 1
            atr = atr_values[atr_index] if atr_index >= 0 else np.nan
            direction: Optional[str] = None
            if np.isfinite(atr) and atr > 0:
                if closes[breakout_index] > metrics["H"] + config.BREAKOUT_BUFFER_ATR * atr:
                    direction = "upward"
                elif closes[breakout_index] < metrics["L"] - config.BREAKOUT_BUFFER_ATR * atr:
                    direction = "downward"
            age = breakout_index - activation_index + 1
            termination_time = frame.at[breakout_index, "open_time"] + interval
            box_record: Dict[str, Any] = {
                **metrics,
                "box_termination_time": termination_time,
                "box_status": "breakout" if direction else "expired",
                "box_age": age,
                "box_age_candles": age,
                "ATR": float(atr) if direction else np.nan,
            }
            if direction:
                close = closes[breakout_index]
                strength = (
                    (close - metrics["H"]) / atr
                    if direction == "upward"
                    else (metrics["L"] - close) / atr
                )
                event_id = f"event-{len(event_rows) + 1:06d}"
                event = {
                    **box_record,
                    "event_id": event_id,
                    "breakout_time": termination_time,
                    "direction": direction,
                    "breakout_close": float(close),
                    "breakout_strength": float(strength),
                    "box_start_time": metrics["box_start"],
                    "box_activation_time": metrics["box_activation"],
                    "breakout_time_utc": termination_time,
                    "breakout_direction": direction,
                }
                event_rows.append(event)
                box_event = event
                box_rows.append(box_record)
                break
            if age == config.BOX_MAX_AGE:
                box_rows.append(box_record)

        if box_event is not None:
            index = breakout_index + 1
        elif last_index - activation_index + 1 == config.BOX_MAX_AGE:
            index = last_index + 1
        else:
            incomplete_boxes += 1
            break

    events = pd.DataFrame(event_rows, columns=_event_columns())
    box_columns = [
        "box_start",
        "box_activation",
        "box_termination_time",
        "box_status",
        "box_age",
        "box_age_candles",
        "H",
        "L",
        "ATR",
        "box_width",
        "normalized_box_width",
        "central_closes_count",
        "efficiency_ratio",
    ]
    boxes = pd.DataFrame(box_rows, columns=box_columns)
    if not events.empty:
        timestamp_columns = (
            "box_start",
            "box_activation",
            "breakout_time",
            "box_start_time",
            "box_activation_time",
            "breakout_time_utc",
            "box_termination_time",
        )
        for column in timestamp_columns:
            events[column] = pd.to_datetime(events[column], utc=True)
    if not boxes.empty:
        for column in ("box_start", "box_activation", "box_termination_time"):
            boxes[column] = pd.to_datetime(boxes[column], utc=True)

    ordered_boxes = boxes.sort_values("box_activation") if not boxes.empty else boxes
    overlaps = 0
    if len(ordered_boxes) > 1:
        previous_termination = ordered_boxes["box_termination_time"].shift()
        overlaps = int((ordered_boxes["box_activation"] < previous_termination).sum())
    diagnostics = {
        "boxes": int(len(boxes)),
        "breakout_events": int(len(events)),
        "upward_events": int((events["direction"] == "upward").sum()) if not events.empty else 0,
        "downward_events": int((events["direction"] == "downward").sum()) if not events.empty else 0,
        "expired_boxes": int((boxes["box_status"] == "expired").sum()) if not boxes.empty else 0,
        "overlapping_boxes": overlaps,
        "incomplete_active_boxes": incomplete_boxes,
        "insufficient_width_history_candidates": insufficient_history,
        "invalid_or_missing_event_fields": 0,
    }
    return DetectorResult(events=events, boxes=boxes, diagnostics=diagnostics)


def pilot_period(frame: pd.DataFrame) -> pd.DataFrame:
    """Оставить breakout events внутри fixed pilot period."""
    start = pd.Timestamp(config.PILOT_START, tz=config.TIMEZONE)
    end = pd.Timestamp(config.PILOT_END, tz=config.TIMEZONE) + pd.Timedelta(days=1)
    timestamps = pd.to_datetime(frame["breakout_time"], utc=True)
    return frame.loc[timestamps.between(start, end, inclusive="both")].reset_index(drop=True)