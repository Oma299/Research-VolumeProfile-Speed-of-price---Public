"""Расчёт approximate Volume Profile и Volume Ahead для breakout events."""

import argparse
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

import numpy as np
import pandas as pd

import config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = PROJECT_ROOT / "outputs" / "tables" / (
    f"consolidation_breakout_events_{config.PILOT_START}_{config.PILOT_END}.csv"
)
MINUTE_DATA_PATH = PROJECT_ROOT / "05 Data" / "processed" / (
    f"binance_btcusdt_spot_1m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
)
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "tables" / (
    f"consolidation_breakout_events_with_profile_{config.PILOT_START}_{config.PILOT_END}.csv"
)

EventLike = Union[pd.Series, Mapping[str, Any]]

PROFILE_RESULT_COLUMNS = (
    "profile_start",
    "profile_end",
    "profile_expected_minutes",
    "profile_observed_minutes",
    "profile_boundary",
    "profile_bin_width",
    "profile_typical_price_min",
    "profile_typical_price_max",
    "ahead_volume",
    "reference_volume",
    "ahead_density",
    "reference_density",
    "VA",
    "log1p_VA",
    "profile_valid",
    "profile_missing_reason",
    "va_missing",
    "va_missing_reason",
)


def typical_price(minute_bars: pd.DataFrame) -> pd.Series:
    """Рассчитать typical price каждой минутной свечи."""
    required = {"high", "low", "close"}
    missing = required.difference(minute_bars.columns)
    if missing:
        raise ValueError(f"В минутных данных отсутствуют колонки: {sorted(missing)}")
    return (
        pd.to_numeric(minute_bars["high"], errors="coerce")
        + pd.to_numeric(minute_bars["low"], errors="coerce")
        + pd.to_numeric(minute_bars["close"], errors="coerce")
    ) / 3.0


def price_bin_indices(
    typical_prices: Union[pd.Series, np.ndarray],
    boundary: float,
    bin_width: float,
) -> np.ndarray:
    """Вернуть целочисленные индексы half-open bins, anchored к B."""
    if not np.isfinite(boundary) or not np.isfinite(bin_width) or bin_width <= 0:
        raise ValueError("Граница и ширина price bin должны быть конечными, bin_width > 0")
    prices = np.asarray(typical_prices, dtype=float)
    return np.floor((prices - boundary) / bin_width).astype(np.int64)


def _event_value(event: EventLike, key: str, fallback: Optional[str] = None) -> Any:
    if key in event:
        return event[key]
    if fallback is not None and fallback in event:
        return event[fallback]
    return None


def _empty_result(
    profile_start: pd.Timestamp,
    profile_end: pd.Timestamp,
    observed_minutes: int,
    reason: str,
    boundary: float = np.nan,
    bin_width: float = np.nan,
    typical_min: float = np.nan,
    typical_max: float = np.nan,
) -> Dict[str, Any]:
    return {
        "profile_start": profile_start,
        "profile_end": profile_end,
        "profile_expected_minutes": config.PROFILE_EXPECTED_MINUTES,
        "profile_observed_minutes": observed_minutes,
        "profile_boundary": boundary,
        "profile_bin_width": bin_width,
        "profile_typical_price_min": typical_min,
        "profile_typical_price_max": typical_max,
        "ahead_volume": np.nan,
        "reference_volume": np.nan,
        "ahead_density": np.nan,
        "reference_density": np.nan,
        "VA": np.nan,
        "log1p_VA": np.nan,
        "profile_valid": False,
        "profile_missing_reason": reason,
        "va_missing": True,
        "va_missing_reason": reason,
    }


def calculate_event_profile(event: EventLike, minute_bars: pd.DataFrame) -> Dict[str, Any]:
    """Рассчитать профиль и Volume Ahead для одного event без будущих минут."""
    required_columns = {"open_time", "high", "low", "close", "quote_asset_volume"}
    missing_columns = required_columns.difference(minute_bars.columns)
    if missing_columns:
        raise ValueError(f"В минутных данных отсутствуют колонки: {sorted(missing_columns)}")

    raw_event_time = _event_value(event, "breakout_time", "breakout_time_utc")
    try:
        event_time = pd.Timestamp(raw_event_time)
        if pd.isna(event_time) or event_time.tzinfo is None:
            raise ValueError("breakout timestamp must be timezone-aware")
        event_time = event_time.tz_convert(config.TIMEZONE)
    except (TypeError, ValueError, OverflowError):
        return _empty_result(pd.NaT, pd.NaT, 0, "invalid_event_time")

    profile_end = event_time - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    profile_start = profile_end - pd.Timedelta(days=config.PROFILE_LOOKBACK_DAYS)
    expected_times = pd.date_range(
        profile_start,
        periods=config.PROFILE_EXPECTED_MINUTES,
        freq=f"{config.SOURCE_INTERVAL_MINUTES}min",
    )

    timestamps = pd.to_datetime(minute_bars["open_time"], utc=True, errors="coerce")
    in_window = timestamps.ge(profile_start) & timestamps.lt(profile_end)
    profile = minute_bars.loc[in_window].copy()
    profile["open_time"] = timestamps.loc[in_window]
    profile = profile.sort_values("open_time", kind="stable").reset_index(drop=True)
    unique_times = pd.DatetimeIndex(profile["open_time"].drop_duplicates())
    if len(profile) != config.PROFILE_EXPECTED_MINUTES or not unique_times.equals(expected_times):
        return _empty_result(profile_start, profile_end, len(unique_times), "incomplete_profile_window")

    numeric_columns = ("high", "low", "close", "quote_asset_volume")
    numeric = profile.loc[:, numeric_columns].apply(pd.to_numeric, errors="coerce")
    numeric_values = numeric.to_numpy(dtype=float)
    if not np.isfinite(numeric_values).all() or (numeric["quote_asset_volume"] < 0).any():
        return _empty_result(profile_start, profile_end, len(unique_times), "invalid_profile_data")
    prices = (numeric["high"] + numeric["low"] + numeric["close"]) / 3.0
    typical_min = float(prices.min())
    typical_max = float(prices.max())

    direction = _event_value(event, "direction", "breakout_direction")
    if direction not in ("upward", "downward"):
        return _empty_result(
            profile_start,
            profile_end,
            len(unique_times),
            "invalid_direction",
            typical_min=typical_min,
            typical_max=typical_max,
        )

    boundary_key = "H" if direction == "upward" else "L"
    try:
        boundary = float(_event_value(event, boundary_key))
    except (TypeError, ValueError):
        boundary = np.nan
    if not np.isfinite(boundary):
        return _empty_result(
            profile_start,
            profile_end,
            len(unique_times),
            "invalid_boundary",
            typical_min=typical_min,
            typical_max=typical_max,
        )
    try:
        atr = float(_event_value(event, "ATR", "atr_14_15m"))
    except (TypeError, ValueError):
        atr = np.nan
    bin_width = config.BIN_WIDTH_ATR * atr
    if not np.isfinite(bin_width) or bin_width <= 0:
        return _empty_result(
            profile_start,
            profile_end,
            len(unique_times),
            "invalid_bin_width",
            boundary=boundary,
            bin_width=bin_width,
            typical_min=typical_min,
            typical_max=typical_max,
        )

    reference_distance = config.REFERENCE_DISTANCE_ATR * atr
    if typical_min > boundary - reference_distance or typical_max < boundary + reference_distance:
        return _empty_result(
            profile_start,
            profile_end,
            len(unique_times),
            "reference_region_outside_historical_range",
            boundary=boundary,
            bin_width=bin_width,
            typical_min=typical_min,
            typical_max=typical_max,
        )

    indices = price_bin_indices(prices, boundary, bin_width)
    volumes = numeric["quote_asset_volume"].to_numpy(dtype=float)
    reference_half_count = config.REFERENCE_BIN_COUNT // 2
    reference_mask = (indices >= -reference_half_count) & (indices < reference_half_count)
    if direction == "upward":
        ahead_mask = (indices >= 0) & (indices < config.AHEAD_BIN_COUNT)
    else:
        ahead_mask = (indices >= -config.AHEAD_BIN_COUNT) & (indices < 0)

    ahead_volume = float(volumes[ahead_mask].sum())
    reference_volume = float(volumes[reference_mask].sum())
    ahead_density = ahead_volume / config.AHEAD_BIN_COUNT
    reference_density = reference_volume / config.REFERENCE_BIN_COUNT
    result = {
        "profile_start": profile_start,
        "profile_end": profile_end,
        "profile_expected_minutes": config.PROFILE_EXPECTED_MINUTES,
        "profile_observed_minutes": len(unique_times),
        "profile_boundary": boundary,
        "profile_bin_width": bin_width,
        "profile_typical_price_min": typical_min,
        "profile_typical_price_max": typical_max,
        "ahead_volume": ahead_volume,
        "reference_volume": reference_volume,
        "ahead_density": ahead_density,
        "reference_density": reference_density,
        "VA": np.nan,
        "log1p_VA": np.nan,
        "profile_valid": False,
        "profile_missing_reason": None,
        "va_missing": True,
        "va_missing_reason": None,
    }
    if not np.isfinite(reference_density) or reference_density <= 0:
        result["profile_missing_reason"] = "zero_or_invalid_reference_density"
        result["va_missing_reason"] = "zero_or_invalid_reference_density"
        return result

    volume_ahead_ratio = ahead_density / reference_density
    result["VA"] = volume_ahead_ratio
    result["log1p_VA"] = float(np.log1p(volume_ahead_ratio))
    result["profile_valid"] = True
    result["profile_missing_reason"] = None
    result["va_missing"] = False
    result["va_missing_reason"] = None
    return result


def calculate_volume_ahead(events: pd.DataFrame, minute_bars: pd.DataFrame) -> pd.DataFrame:
    """Вернуть все исходные события с profile metrics и явными missing reasons."""
    if events.columns.duplicated().any():
        raise ValueError("Event table contains duplicate column names")
    results = [calculate_event_profile(event, minute_bars) for _, event in events.iterrows()]
    profile_results = pd.DataFrame(results, columns=PROFILE_RESULT_COLUMNS, index=events.index)
    return pd.concat([events.copy(), profile_results], axis=1)


def run_profile_pipeline(
    events_path: Path = EVENTS_PATH,
    minute_data_path: Path = MINUTE_DATA_PATH,
    output_path: Path = OUTPUT_PATH,
) -> pd.DataFrame:
    """Рассчитать профиль для всей event table и сохранить CSV."""
    timestamp_columns = [
        "box_start",
        "box_activation",
        "breakout_time",
        "box_start_time",
        "box_activation_time",
        "breakout_time_utc",
        "box_termination_time",
    ]
    events = pd.read_csv(events_path, parse_dates=timestamp_columns)
    minute_bars = pd.read_parquet(minute_data_path)
    profiled_events = calculate_volume_ahead(events, minute_bars)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profiled_events.to_csv(output_path, index=False)
    return profiled_events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--minute-data", type=Path, default=MINUTE_DATA_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    arguments = parser.parse_args()
    profiled = run_profile_pipeline(arguments.events, arguments.minute_data, arguments.output)
    print(f"Processed events: {len(profiled)}")
    print(f"Valid profiles: {int(profiled['profile_valid'].sum())}")
    print(f"Invalid profiles: {int((~profiled['profile_valid']).sum())}")
    print("Missing reasons:")
    print(profiled.loc[~profiled["profile_valid"], "profile_missing_reason"].value_counts(dropna=False).to_string())
    print(f"Output: {arguments.output}")


if __name__ == "__main__":
    main()