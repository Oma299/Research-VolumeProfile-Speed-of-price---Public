"""Расчёт post-breakout price/speed outcomes для событий Pilot v0.1."""

import argparse
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union

import numpy as np
import pandas as pd

import config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = PROJECT_ROOT / "outputs" / "tables" / (
    f"consolidation_breakout_events_with_profile_{config.PILOT_START}_{config.PILOT_END}.csv"
)
MINUTE_DATA_PATH = PROJECT_ROOT / "05 Data" / "processed" / (
    f"binance_btcusdt_spot_1m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
)
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "tables" / (
    f"consolidation_breakout_events_with_profile_and_outcomes_{config.PILOT_START}_{config.PILOT_END}.csv"
)

EventLike = Union[pd.Series, Mapping[str, Any]]

OUTCOME_COLUMNS = (
    "target_price",
    "target_hit",
    "time_to_target_minutes",
    "observed_time_minutes",
    "right_censored",
    "outcome_missing",
    "outcome_missing_reason",
    "outcome_expected_minutes",
    "outcome_observed_minutes",
    "outcome_contiguous_prefix_minutes",
    "target_hit_bar_open_time_utc",
    "r_15",
    "r_30",
    "r_60",
    "r_120",
    "r_240",
    "mfe_240",
    "mae_240",
    "return_to_box",
    "time_to_return_box_minutes",
    "return_to_box_bar_open_time_utc",
    "ambiguous_intrabar",
)


def _event_value(event: EventLike, key: str, fallback: Optional[str] = None) -> Any:
    if key in event:
        return event[key]
    if fallback is not None and fallback in event:
        return event[fallback]
    return None


def _prepare_minute_bars(
    minute_bars: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DatetimeIndex, pd.Timestamp]:
    required = {"open_time", "open", "high", "low", "close"}
    missing = required.difference(minute_bars.columns)
    if missing:
        raise ValueError(f"В минутных данных отсутствуют колонки: {sorted(missing)}")

    frame = minute_bars.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True, errors="coerce")
    frame = frame.loc[frame["open_time"].notna()].sort_values("open_time", kind="stable")
    if frame.empty:
        empty = pd.DataFrame(columns=("open", "high", "low", "close"))
        empty.index = pd.DatetimeIndex([], tz=config.TIMEZONE, name="open_time")
        return empty, pd.DatetimeIndex([], tz=config.TIMEZONE), pd.NaT

    all_times = pd.DatetimeIndex(frame["open_time"])
    duplicate_times = pd.DatetimeIndex(all_times[all_times.duplicated(keep=False)].unique())
    frame = frame.loc[~frame["open_time"].duplicated(keep=False)].copy()
    price_columns = ("open", "high", "low", "close")
    numeric = frame.loc[:, price_columns].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
    valid &= (numeric > 0).all(axis=1).to_numpy()
    valid &= numeric["high"].ge(numeric[["open", "close", "low"]].max(axis=1)).to_numpy()
    valid &= numeric["low"].le(numeric[["open", "close", "high"]].min(axis=1)).to_numpy()
    numeric.loc[~valid, :] = np.nan
    frame.loc[:, list(price_columns)] = numeric
    max_time = all_times.max()
    frame = frame.set_index("open_time").loc[:, list(price_columns)]
    return frame, duplicate_times, max_time


def _missing_result(reason: str) -> Dict[str, Any]:
    result = {column: np.nan for column in OUTCOME_COLUMNS}
    result.update(
        {
            "target_hit": pd.NA,
            "right_censored": pd.NA,
            "outcome_missing": True,
            "outcome_missing_reason": reason,
            "outcome_expected_minutes": config.MAX_HORIZON_MINUTES,
            "outcome_observed_minutes": 0,
            "outcome_contiguous_prefix_minutes": 0,
            "return_to_box": pd.NA,
            "ambiguous_intrabar": pd.NA,
        }
    )
    return result


def _calculate_prepared_event(
    event: EventLike,
    minute_indexed: pd.DataFrame,
    duplicate_times: pd.DatetimeIndex,
    max_minute_time: pd.Timestamp,
) -> Dict[str, Any]:
    try:
        event_time = pd.Timestamp(_event_value(event, "breakout_time", "breakout_time_utc"))
        if pd.isna(event_time) or event_time.tzinfo is None:
            return _missing_result("invalid_event_time")
        event_time = event_time.tz_convert(config.TIMEZONE)
        p0 = float(_event_value(event, "breakout_close"))
        atr = float(_event_value(event, "ATR", "atr_14_15m"))
        direction = _event_value(event, "direction", "breakout_direction")
        high_boundary = float(_event_value(event, "H"))
        low_boundary = float(_event_value(event, "L"))
    except (TypeError, ValueError, OverflowError):
        return _missing_result("invalid_event_fields")
    if (
        not np.isfinite([p0, atr, high_boundary, low_boundary]).all()
        or p0 <= 0
        or atr <= 0
        or high_boundary <= low_boundary
        or direction not in ("upward", "downward")
    ):
        return _missing_result("invalid_event_fields")

    interval = pd.Timedelta(minutes=config.SOURCE_INTERVAL_MINUTES)
    expected_times = pd.date_range(
        event_time,
        periods=config.MAX_HORIZON_MINUTES,
        freq=interval,
    )
    window = minute_indexed.reindex(expected_times)
    valid_rows = window.loc[:, ("open", "high", "low", "close")].notna().all(axis=1).to_numpy()
    duplicate_mask = expected_times.isin(duplicate_times)
    valid_rows &= ~duplicate_mask
    full_followup = bool(valid_rows.all())
    missing_positions = np.flatnonzero(~valid_rows)
    first_missing_time = expected_times[missing_positions[0]] if len(missing_positions) else None
    contiguous_prefix = int(missing_positions[0]) if len(missing_positions) else config.MAX_HORIZON_MINUTES
    observed_minutes = int(valid_rows.sum())

    if full_followup:
        missing_reason = None
    elif first_missing_time in duplicate_times:
        missing_reason = "duplicate_future_minute"
    elif first_missing_time in minute_indexed.index:
        missing_reason = "invalid_future_ohlc"
    elif pd.notna(max_minute_time) and first_missing_time <= max_minute_time:
        missing_reason = "missing_future_minute"
    else:
        missing_reason = "dataset_end_before_240_minutes"

    sign = 1.0 if direction == "upward" else -1.0
    target = p0 + sign * config.TARGET_ATR * atr
    target_hits = (
        window["high"].ge(target).to_numpy()
        if direction == "upward"
        else window["low"].le(target).to_numpy()
    )
    target_hit_positions = np.flatnonzero(target_hits[:contiguous_prefix])
    target_position = int(target_hit_positions[0]) if len(target_hit_positions) else None

    box_returns = (
        window["close"].lt(high_boundary).to_numpy()
        if direction == "upward"
        else window["close"].gt(low_boundary).to_numpy()
    )
    box_return_positions = np.flatnonzero(box_returns[:contiguous_prefix])
    box_return_position = int(box_return_positions[0]) if len(box_return_positions) else None

    result: Dict[str, Any] = {
        "target_price": target,
        "target_hit": pd.NA,
        "time_to_target_minutes": np.nan,
        "observed_time_minutes": np.nan,
        "right_censored": pd.NA,
        "outcome_missing": not full_followup,
        "outcome_missing_reason": missing_reason,
        "outcome_expected_minutes": config.MAX_HORIZON_MINUTES,
        "outcome_observed_minutes": observed_minutes,
        "outcome_contiguous_prefix_minutes": contiguous_prefix,
        "target_hit_bar_open_time_utc": pd.NaT,
        "r_15": np.nan,
        "r_30": np.nan,
        "r_60": np.nan,
        "r_120": np.nan,
        "r_240": np.nan,
        "mfe_240": np.nan,
        "mae_240": np.nan,
        "return_to_box": pd.NA,
        "time_to_return_box_minutes": np.nan,
        "return_to_box_bar_open_time_utc": pd.NaT,
        "ambiguous_intrabar": pd.NA,
    }

    if target_position is not None:
        target_minute = target_position + 1
        result["target_hit"] = True
        result["time_to_target_minutes"] = target_minute
        result["observed_time_minutes"] = target_minute
        result["right_censored"] = False
        result["target_hit_bar_open_time_utc"] = expected_times[target_position]
    elif full_followup:
        result["target_hit"] = False
        result["observed_time_minutes"] = config.MAX_HORIZON_MINUTES
        result["right_censored"] = True

    if box_return_position is not None:
        result["return_to_box"] = True
        result["time_to_return_box_minutes"] = box_return_position + 1
        result["return_to_box_bar_open_time_utc"] = expected_times[box_return_position]
    elif full_followup:
        result["return_to_box"] = False

    if target_position is not None:
        result["ambiguous_intrabar"] = target_position == box_return_position
    elif full_followup:
        result["ambiguous_intrabar"] = False

    for horizon in config.RETURN_HORIZONS_MINUTES:
        endpoint_time = event_time + pd.Timedelta(minutes=horizon) - interval
        if endpoint_time in minute_indexed.index and endpoint_time not in duplicate_times:
            endpoint_close = minute_indexed.at[endpoint_time, "close"]
            if pd.notna(endpoint_close):
                result[f"r_{horizon}"] = sign * (float(endpoint_close) - p0) / p0

    if full_followup:
        highs = window["high"].to_numpy(dtype=float)
        lows = window["low"].to_numpy(dtype=float)
        if direction == "upward":
            result["mfe_240"] = (float(highs.max()) - p0) / p0
            result["mae_240"] = (float(lows.min()) - p0) / p0
        else:
            result["mfe_240"] = (p0 - float(lows.min())) / p0
            result["mae_240"] = (p0 - float(highs.max())) / p0

    return result


def calculate_event_outcomes(event: EventLike, minute_bars: pd.DataFrame) -> Dict[str, Any]:
    """Рассчитать time, return, excursions и box return для одного события."""
    indexed, duplicates, max_time = _prepare_minute_bars(minute_bars)
    return _calculate_prepared_event(event, indexed, duplicates, max_time)


def calculate_outcomes(events: pd.DataFrame, minute_bars: pd.DataFrame) -> pd.DataFrame:
    """Дополнить каждое событие outcome-полями, не фильтруя строки по VA."""
    if events.columns.duplicated().any():
        raise ValueError("Event table contains duplicate column names")
    duplicate_columns = set(OUTCOME_COLUMNS).intersection(events.columns)
    if duplicate_columns:
        raise ValueError(f"Event table already contains outcome columns: {sorted(duplicate_columns)}")
    indexed, duplicates, max_time = _prepare_minute_bars(minute_bars)
    rows = [
        _calculate_prepared_event(event, indexed, duplicates, max_time)
        for _, event in events.iterrows()
    ]
    outcome_frame = pd.DataFrame(rows, columns=OUTCOME_COLUMNS, index=events.index)
    timestamp_columns = ("target_hit_bar_open_time_utc", "return_to_box_bar_open_time_utc")
    for column in timestamp_columns:
        outcome_frame[column] = pd.to_datetime(outcome_frame[column], utc=True)
    for column in ("target_hit", "right_censored", "return_to_box", "ambiguous_intrabar"):
        outcome_frame[column] = outcome_frame[column].astype("boolean")
    return pd.concat([events.copy(), outcome_frame], axis=1)


def run_outcome_pipeline(
    events_path: Path = EVENTS_PATH,
    minute_data_path: Path = MINUTE_DATA_PATH,
    output_path: Path = OUTPUT_PATH,
) -> pd.DataFrame:
    """Рассчитать все outcomes и записать отдельную таблицу."""
    event_timestamps = [
        "box_start",
        "box_activation",
        "breakout_time",
        "box_start_time",
        "box_activation_time",
        "breakout_time_utc",
        "box_termination_time",
        "profile_start",
        "profile_end",
        "target_hit_bar_open_time_utc",
        "return_to_box_bar_open_time_utc",
    ]
    parse_dates = [
        column
        for column in event_timestamps
        if column in pd.read_csv(events_path, nrows=0).columns
    ]
    events = pd.read_csv(events_path, parse_dates=parse_dates)
    minute_bars = pd.read_parquet(minute_data_path)
    outcomes = calculate_outcomes(events, minute_bars)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes.to_csv(output_path, index=False)
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--minute-data", type=Path, default=MINUTE_DATA_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    arguments = parser.parse_args()
    outcomes = run_outcome_pipeline(arguments.events, arguments.minute_data, arguments.output)
    print(f"Processed events: {len(outcomes)}")
    print(f"Complete outcomes: {int((~outcomes['outcome_missing']).sum())}")
    print(f"Incomplete outcomes: {int(outcomes['outcome_missing'].sum())}")
    print(f"Target hits: {int(outcomes['target_hit'].fillna(False).sum())}")
    print(f"Right-censored: {int(outcomes['right_censored'].fillna(False).sum())}")
    print("Missing reasons:")
    print(outcomes.loc[outcomes["outcome_missing"], "outcome_missing_reason"].value_counts(dropna=False).to_string())
    print(f"Output: {arguments.output}")


if __name__ == "__main__":
    main()