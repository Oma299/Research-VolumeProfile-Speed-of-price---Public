"""Read-only Pilot v0.1 pre-analysis leakage and integrity validation."""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd

import config
from calculate_outcomes import calculate_event_outcomes
from calculate_profile import calculate_event_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERIOD_TAG = f"{config.PILOT_START}_{config.PILOT_END}"
OUTPUT_DIR = PROJECT_ROOT / "reports" / "day3" / "block1_validation"
REPORT_PATH = OUTPUT_DIR / "VALIDATION_REPORT.md"

EVENTS_PATH = PROJECT_ROOT / "outputs" / "tables" / "events_analysis.csv"
RAW_EVENTS_PATH = PROJECT_ROOT / "outputs" / "tables" / "events_raw.parquet"
BOXES_PATH = PROJECT_ROOT / "outputs" / "tables" / f"consolidation_boxes_{PERIOD_TAG}.csv"
MINUTE_DATA_PATH = PROJECT_ROOT / "05 Data" / "processed" / (
    f"binance_btcusdt_spot_1m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
)
CANDLES_15M_PATH = PROJECT_ROOT / "05 Data" / "processed" / (
    f"binance_btcusdt_spot_15m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
)

EVENT_COLUMNS = {
    "event_id", "box_start", "box_activation", "box_termination_time", "box_status",
    "box_age_candles", "breakout_time", "direction", "H", "L", "ATR", "breakout_close",
    "profile_start", "profile_end", "profile_expected_minutes", "profile_observed_minutes",
    "profile_boundary", "profile_bin_width", "ahead_volume", "reference_volume", "ahead_density",
    "reference_density", "VA", "log1p_VA", "profile_valid", "va_missing", "va_missing_reason",
    "profile_available_for_va_analysis", "primary_analysis_eligible", "target_hit",
    "time_to_target_minutes", "observed_time_minutes", "right_censored", "outcome_missing",
    "outcome_expected_minutes", "outcome_observed_minutes", "target_hit_bar_open_time_utc",
}
RAW_EVENT_COLUMNS = {"event_id"}
BOX_COLUMNS = {"box_start", "box_activation", "box_termination_time", "box_status", "box_age_candles", "H", "L"}
MINUTE_COLUMNS = {"open_time", "open", "high", "low", "close"}
CANDLE_COLUMNS = {"open_time", "open", "high", "low", "close", "atr_14"}
TIMESTAMP_COLUMNS = {
    "box_start", "box_activation", "box_termination_time", "breakout_time", "profile_start",
    "profile_end", "target_hit_bar_open_time_utc",
}

Check = Dict[str, str]


def _check(
    check_id: str,
    name: str,
    passed: bool,
    observed: str,
    expected: str,
    evidence: str,
    note: str = "",
) -> Check:
    return {
        "id": check_id,
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "observed": observed,
        "expected": expected,
        "evidence": evidence,
        "note": note,
    }


def _require_artifacts(paths: Sequence[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Required validation artifacts are missing: {', '.join(missing)}")


def _require_columns(frame: pd.DataFrame, required: set, label: str) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Required columns missing from {label}: {', '.join(sorted(missing))}")


def _parse_timestamps(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in TIMESTAMP_COLUMNS.intersection(result.columns):
        result[column] = pd.to_datetime(result[column], utc=True, errors="coerce")
    return result


def load_artifacts() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the persisted artifacts without modifying them; fail on absent input/schema."""
    paths = (EVENTS_PATH, RAW_EVENTS_PATH, BOXES_PATH, MINUTE_DATA_PATH, CANDLES_15M_PATH)
    _require_artifacts(paths)
    event_header = pd.read_csv(EVENTS_PATH, nrows=0).columns
    event_dates = sorted(TIMESTAMP_COLUMNS.intersection(event_header))
    box_dates = ("box_start", "box_activation", "box_termination_time")
    events = pd.read_csv(EVENTS_PATH, parse_dates=event_dates, low_memory=False)
    raw_events = pd.read_parquet(RAW_EVENTS_PATH)
    boxes = pd.read_csv(BOXES_PATH, parse_dates=list(box_dates))
    minute_bars = pd.read_parquet(MINUTE_DATA_PATH)
    candles_15m = pd.read_parquet(CANDLES_15M_PATH)
    _require_columns(events, EVENT_COLUMNS, str(EVENTS_PATH))
    _require_columns(raw_events, RAW_EVENT_COLUMNS, str(RAW_EVENTS_PATH))
    _require_columns(boxes, BOX_COLUMNS, str(BOXES_PATH))
    _require_columns(minute_bars, MINUTE_COLUMNS, str(MINUTE_DATA_PATH))
    _require_columns(candles_15m, CANDLE_COLUMNS, str(CANDLES_15M_PATH))
    return (
        _parse_timestamps(events), raw_events, _parse_timestamps(boxes), minute_bars.copy(), candles_15m.copy()
    )


def _regular_index(values: pd.Series, minutes: int) -> Tuple[pd.DatetimeIndex, bool]:
    index = pd.DatetimeIndex(pd.to_datetime(values, utc=True, errors="coerce"))
    regular = bool(
        len(index) > 1
        and index.is_monotonic_increasing
        and not index.has_duplicates
        and not index.isna().any()
        and index.to_series().diff().dropna().eq(pd.Timedelta(minutes=minutes)).all()
    )
    return index, regular


def _window_is_covered(index: pd.DatetimeIndex, start: pd.Timestamp, count: int, minutes: int) -> bool:
    if pd.isna(start) or index.empty:
        return False
    start = pd.Timestamp(start)
    position = int(index.searchsorted(start))
    last = position + count - 1
    return (
        position < len(index)
        and last < len(index)
        and index[position] == start
        and index[last] == start + pd.Timedelta(minutes=minutes * (count - 1))
    )


def _missing_profile_rows(events: pd.DataFrame) -> pd.Series:
    va = pd.to_numeric(events["VA"], errors="coerce")
    profile_valid = events["profile_valid"].fillna(False).astype(bool)
    va_missing = events["va_missing"].fillna(True).astype(bool)
    return (~profile_valid) | va_missing | va.isna()


def _synthetic_profile_symmetry() -> Dict[str, Any]:
    """Exercise mirrored UP/DOWN profile bins through the production profile function."""
    count = config.PROFILE_EXPECTED_MINUTES
    boundary = 100_000.0
    atr = 20.0
    width = config.BIN_WIDTH_ATR * atr
    indices = np.repeat(np.arange(-99, 100, dtype=np.int64), count // 200)
    remainder = count - len(indices)
    indices = np.concatenate((indices, np.repeat(-21, remainder // 2), np.repeat(20, remainder // 2)))
    prices = boundary + (indices + 0.5) * width
    prices[0] = boundary - config.REFERENCE_DISTANCE_ATR * atr - width
    prices[1] = boundary + config.REFERENCE_DISTANCE_ATR * atr + width
    end = pd.Timestamp("2025-02-01 00:00:00", tz=config.TIMEZONE)
    start = end - pd.Timedelta(days=config.PROFILE_LOOKBACK_DAYS)
    bars = pd.DataFrame(
        {
            "open_time": pd.date_range(start, periods=count, freq=f"{config.SOURCE_INTERVAL_MINUTES}min"),
            "high": prices,
            "low": prices,
            "close": prices,
            "quote_asset_volume": np.ones(count, dtype=float),
        }
    )
    event_time = end + pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    events = (
        {"breakout_time": event_time, "direction": "upward", "H": boundary, "L": boundary - 10, "ATR": atr},
        {"breakout_time": event_time, "direction": "downward", "H": boundary + 10, "L": boundary, "ATR": atr},
    )
    up, down = (calculate_event_profile(event, bars) for event in events)
    same = all(result["profile_valid"] for result in (up, down))
    same &= up["profile_boundary"] == down["profile_boundary"] == boundary
    same &= up["profile_bin_width"] == down["profile_bin_width"] == width
    same &= up["ahead_volume"] == down["ahead_volume"]
    same &= up["reference_volume"] == down["reference_volume"]
    same &= np.isclose(up["VA"], down["VA"], rtol=0.0, atol=1e-12)
    return {"passed": bool(same), "up": up, "down": down}


def _synthetic_outcome_symmetry() -> Dict[str, Any]:
    """Exercise mirrored UP/DOWN target and direction-normalized outcomes."""
    event_time = pd.Timestamp("2025-01-01 00:00:00", tz=config.TIMEZONE)
    count = config.MAX_HORIZON_MINUTES
    times = pd.date_range(event_time, periods=count, freq=f"{config.SOURCE_INTERVAL_MINUTES}min")
    close = np.full(count, 100.0)
    close[59:] = 101.0
    high = close + 0.2
    low = close - 0.2
    high[2] = 103.0
    low[2] = 99.0
    up_bars = pd.DataFrame({"open_time": times, "open": close, "high": high, "low": low, "close": close})
    down_bars = up_bars.copy()
    down_bars.loc[:, "open"] = 200.0 - up_bars["open"].to_numpy()
    down_bars.loc[:, "high"] = 200.0 - up_bars["low"].to_numpy()
    down_bars.loc[:, "low"] = 200.0 - up_bars["high"].to_numpy()
    down_bars.loc[:, "close"] = 200.0 - up_bars["close"].to_numpy()
    common = {"breakout_time": event_time, "breakout_close": 100.0, "ATR": 2.0}
    up_event = {**common, "direction": "upward", "H": 99.0, "L": 95.0}
    down_event = {**common, "direction": "downward", "H": 105.0, "L": 101.0}
    up = calculate_event_outcomes(up_event, up_bars)
    down = calculate_event_outcomes(down_event, down_bars)
    fields = ("target_hit", "time_to_target_minutes", "right_censored", "observed_time_minutes", "r_60", "mfe_240", "mae_240", "return_to_box")
    same = all(
        (pd.isna(up[field]) and pd.isna(down[field]))
        or np.isclose(float(up[field]), float(down[field]), rtol=0.0, atol=1e-12)
        for field in fields
    )
    return {"passed": bool(same), "up": up, "down": down}


def _validated_candles(candles: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    frame = candles.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True, errors="coerce")
    numeric = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy(dtype=float)
    valid = np.isfinite(values).all(axis=1) & (numeric > 0).all(axis=1).to_numpy()
    valid &= numeric["high"].ge(numeric[["open", "close", "low"]].max(axis=1)).to_numpy()
    valid &= numeric["low"].le(numeric[["open", "close", "high"]].min(axis=1)).to_numpy()
    frame.loc[:, ["open", "high", "low", "close"]] = numeric
    frame["atr_14"] = pd.to_numeric(frame["atr_14"], errors="coerce")
    return frame, pd.Series(valid, index=frame.index)


def _formation_window_counts(boxes: pd.DataFrame, candles: pd.DataFrame) -> Tuple[List[int], List[int]]:
    frame, valid_ohlc = _validated_candles(candles)
    valid_counts = []
    observed_counts = []
    for row in boxes.itertuples(index=False):
        formation = frame["open_time"].ge(row.box_start) & frame["open_time"].lt(row.box_activation)
        observed_counts.append(int(formation.sum()))
        valid_counts.append(int(valid_ohlc.loc[formation].sum()))
    return valid_counts, observed_counts


def _lifecycle_consistency(
    events: pd.DataFrame,
    boxes: pd.DataFrame,
    candles: pd.DataFrame,
) -> Dict[str, Any]:
    """Check active age, termination timing, first breakout, and expiration semantics."""
    frame, valid_ohlc = _validated_candles(candles)
    frame = frame.reset_index(drop=True)
    valid_ohlc = valid_ohlc.reset_index(drop=True)
    time_to_position = {timestamp: position for position, timestamp in enumerate(frame["open_time"])}
    ages = pd.to_numeric(boxes["box_age_candles"], errors="coerce")
    statuses = boxes["box_status"].astype(str).str.lower()
    event_groups = {activation: group for activation, group in events.groupby("box_activation", sort=False)}
    age_is_valid = []
    age_timestamp_matches = []
    active_ohlc_matches_age = []
    first_breakout_valid = []
    expired_without_breakout = []
    expired_at_max_age = []

    for box_index, box in enumerate(boxes.itertuples(index=False)):
        age = ages.iloc[box_index]
        activation = box.box_activation
        termination = box.box_termination_time
        interval_age = (termination - activation).total_seconds() / (config.CANDLE_INTERVAL_MINUTES * 60)
        age_timestamp_matches.append(pd.notna(age) and interval_age == age)
        age_is_valid.append(pd.notna(age) and 1 <= age <= config.BOX_MAX_AGE)
        active_mask = frame["open_time"].ge(activation) & frame["open_time"].lt(termination)
        active = frame.loc[active_mask]
        active_positions = active.index.to_list()
        active_ohlc_matches_age.append(
            len(active_positions) == age and bool(valid_ohlc.loc[active_positions].all())
        )

        breakout_signals = []
        signal_directions = []
        for position in active_positions:
            previous_position = position - 1
            atr = frame.at[previous_position, "atr_14"] if previous_position >= 0 else np.nan
            close = frame.at[position, "close"]
            can_evaluate = valid_ohlc.iloc[position] and np.isfinite(atr) and atr > 0
            if not can_evaluate:
                breakout_signals.append(None)
                signal_directions.append(None)
                continue
            upward = close > float(box.H) + config.BREAKOUT_BUFFER_ATR * atr
            downward = close < float(box.L) - config.BREAKOUT_BUFFER_ATR * atr
            breakout_signals.append(bool(upward or downward))
            signal_directions.append("upward" if upward else "downward" if downward else None)

        if statuses.iloc[box_index] == "breakout":
            matching_events = event_groups.get(activation, pd.DataFrame())
            terminal_is_last = bool(active_positions) and active_positions[-1] == time_to_position.get(termination - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES), -1)
            prior_no_breakout = all(signal is False for signal in breakout_signals[:-1])
            terminal_breakout = bool(breakout_signals and breakout_signals[-1] is True)
            direction_matches = (
                len(matching_events) == 1
                and terminal_breakout
                and matching_events.iloc[0]["direction"] == signal_directions[-1]
                and matching_events.iloc[0]["breakout_time"] == termination
            )
            first_breakout_valid.append(
                terminal_is_last and prior_no_breakout and direction_matches
            )
        elif statuses.iloc[box_index] == "expired":
            matching_events = event_groups.get(activation, pd.DataFrame())
            no_breakout = all(signal is False for signal in breakout_signals)
            expired_without_breakout.append(no_breakout and matching_events.empty)
            expired_at_max_age.append(pd.notna(age) and age == config.BOX_MAX_AGE)
        else:
            first_breakout_valid.append(False)
            expired_without_breakout.append(False)
            expired_at_max_age.append(False)

    def count_true(values: List[bool]) -> int:
        return sum(bool(value) for value in values)

    return {
        "passed": statuses.isin(("breakout", "expired")).all()
        and all(age_is_valid)
        and all(age_timestamp_matches)
        and all(active_ohlc_matches_age)
        and all(first_breakout_valid)
        and all(expired_without_breakout)
        and all(expired_at_max_age),
        "box_count": len(boxes),
        "age_valid_count": count_true(age_is_valid),
        "age_timestamp_count": count_true(age_timestamp_matches),
        "active_ohlc_age_count": count_true(active_ohlc_matches_age),
        "first_breakout_count": count_true(first_breakout_valid),
        "expired_no_breakout_count": count_true(expired_without_breakout),
        "expired_age_32_count": count_true(expired_at_max_age),
        "age_min": int(ages.min()),
        "age_max": int(ages.max()),
        "breakout_boxes": int(statuses.eq("breakout").sum()),
        "expired_boxes": int(statuses.eq("expired").sum()),
    }


def _profile_window_results(events: pd.DataFrame, minute_index: pd.DatetimeIndex) -> List[bool]:
    results = []
    for row in events.itertuples(index=False):
        expected_end = row.breakout_time - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
        expected_start = expected_end - pd.Timedelta(days=config.PROFILE_LOOKBACK_DAYS)
        results.append(
            row.profile_start == expected_start
            and row.profile_end == expected_end
            and _window_is_covered(minute_index, row.profile_start, config.PROFILE_EXPECTED_MINUTES, 1)
        )
    return results


def _outcome_window_results(events: pd.DataFrame, minute_index: pd.DatetimeIndex) -> List[bool]:
    return [
        _window_is_covered(minute_index, row.breakout_time, config.MAX_HORIZON_MINUTES, 1)
        for row in events.itertuples(index=False)
    ]


def evaluate_validation_checks(
    events: pd.DataFrame,
    raw_events: pd.DataFrame,
    boxes: pd.DataFrame,
    minute_bars: pd.DataFrame,
    candles_15m: pd.DataFrame,
) -> List[Check]:
    """Evaluate Section 17 checks plus direct integrity/timing checks in memory."""
    _require_columns(events, EVENT_COLUMNS, "events_analysis")
    _require_columns(raw_events, RAW_EVENT_COLUMNS, "events_raw")
    _require_columns(boxes, BOX_COLUMNS, "consolidation_boxes")
    _require_columns(minute_bars, MINUTE_COLUMNS, "1m Parquet")
    _require_columns(candles_15m, CANDLE_COLUMNS, "15m Parquet")
    events = _parse_timestamps(events)
    boxes = _parse_timestamps(boxes)
    minute_index, minute_grid_ok = _regular_index(minute_bars["open_time"], config.SOURCE_INTERVAL_MINUTES)
    candle_index, candle_grid_ok = _regular_index(candles_15m["open_time"], config.CANDLE_INTERVAL_MINUTES)

    event_ids = events["event_id"].astype(str)
    raw_ids = raw_events["event_id"].astype(str)
    event_times = events["breakout_time"]
    ages = pd.to_numeric(boxes["box_age_candles"], errors="coerce")
    statuses = boxes["box_status"].astype(str).str.lower()
    formation_valid_counts, formation_observed_counts = _formation_window_counts(boxes, candles_15m)
    formation_duration_ok = (
        boxes["box_activation"] - boxes["box_start"]
    ).eq(pd.Timedelta(minutes=config.BOX_LENGTH * config.CANDLE_INTERVAL_MINUTES))
    formation_ok = all(
        valid_count == config.BOX_LENGTH and observed_count == config.BOX_LENGTH and bool(duration_ok)
        for valid_count, observed_count, duration_ok in zip(
            formation_valid_counts, formation_observed_counts, formation_duration_ok
        )
    )
    checks = [
        _check(
            "17.1", "Exactly 32 valid completed pre-activation formation candles per box", bool(formation_ok),
            f"boxes={len(boxes)}; valid formation candle count range={min(formation_valid_counts)}..{max(formation_valid_counts)}; "
            f"exactly-32-valid={sum(count == config.BOX_LENGTH for count in formation_valid_counts)}; "
            f"exactly-32-observed={sum(count == config.BOX_LENGTH for count in formation_observed_counts)}; "
            f"8-hour intervals={int(formation_duration_ok.sum())}/{len(boxes)}",
            "Exactly 32 valid completed 15m candles in [box_start, box_activation) for every box",
            "consolidation_boxes CSV box_start/box_activation; 15m Parquet open_time and OHLC",
            "Approved interpretation: Section 17.1 validates the formation interval, not post-activation lifetime. Active lifetime is checked separately under Sections 9 and 11.",
        )
    ]

    ordered_boxes = boxes.sort_values("box_activation", kind="mergesort")
    overlap_count = 0
    if len(ordered_boxes) > 1:
        overlap_count = int((
            ordered_boxes["box_activation"].iloc[1:].reset_index(drop=True)
            < ordered_boxes["box_termination_time"].iloc[:-1].reset_index(drop=True)
        ).sum())
    checks.append(_check(
        "17.2", "Zero active-box overlaps", overlap_count == 0, f"overlapping intervals={overlap_count}",
        "0 active-box overlaps", "consolidation_boxes CSV: box_activation/box_termination_time",
    ))

    expected_end = event_times - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    expected_start = expected_end - pd.Timedelta(days=config.PROFILE_LOOKBACK_DAYS)
    profile_boundaries_match = events["profile_end"].eq(expected_end) & events["profile_start"].eq(expected_start)
    checks.append(_check(
        "17.3", "Zero profile overlap with breakout candle", bool(profile_boundaries_match.all()),
        f"rows with exact profile boundaries={int(profile_boundaries_match.sum())}/{len(events)}",
        "[breakout_time-15m-30d, breakout_time-15m); breakout candle wholly excluded",
        "events_analysis.csv: profile_start/profile_end/breakout_time",
    ))

    valid_profile = ~_missing_profile_rows(events)
    boundaries = pd.to_numeric(events["profile_boundary"], errors="coerce").to_numpy(dtype=float)
    expected_boundary = np.where(events["direction"].eq("upward"), events["H"], events["L"]).astype(float)
    widths = pd.to_numeric(events["profile_bin_width"], errors="coerce").to_numpy(dtype=float)
    expected_width = config.BIN_WIDTH_ATR * pd.to_numeric(events["ATR"], errors="coerce").to_numpy(dtype=float)
    geometry_ok = np.isclose(boundaries, expected_boundary, rtol=1e-12, atol=1e-12)
    geometry_ok &= np.isclose(widths, expected_width, rtol=1e-12, atol=1e-12)
    geometry_ok |= ~valid_profile.to_numpy()
    profile_synthetic = _synthetic_profile_symmetry()
    bins_ok = (
        config.AHEAD_BIN_COUNT == 20
        and config.REFERENCE_BIN_COUNT == 200
        and bool(geometry_ok.all())
        and profile_synthetic["passed"]
    )
    checks.append(_check(
        "17.4", "Exactly 20 Ahead bins and 200 Reference bins", bins_ok,
        f"config counts={config.AHEAD_BIN_COUNT}/{config.REFERENCE_BIN_COUNT}; valid-event boundary/width rows="
        f"{int((geometry_ok & valid_profile.to_numpy()).sum())}/{int(valid_profile.sum())}; synthetic symmetry={profile_synthetic['passed']}",
        "20 Ahead bins, 200 Reference bins; B=H for UP/B=L for DOWN; d=0.05*ATR[t-1]",
        "config.py; events_analysis.csv profile_boundary/profile_bin_width; synthetic profile calculation",
    ))

    profile_windows = _profile_window_results(events, minute_index)
    profile_counts_ok = (
        pd.to_numeric(events["profile_expected_minutes"], errors="coerce").eq(config.PROFILE_EXPECTED_MINUTES)
        & pd.to_numeric(events["profile_observed_minutes"], errors="coerce").eq(config.PROFILE_EXPECTED_MINUTES)
    )
    profile_coverage_ok = minute_grid_ok and all(profile_windows) and bool(profile_counts_ok.all())
    checks.append(_check(
        "17.5", "Full 30-day profile interval coverage", profile_coverage_ok,
        f"complete 1m windows={sum(profile_windows)}/{len(events)}; expected/observed counts correct="
        f"{int(profile_counts_ok.sum())}/{len(events)}; 1m grid continuous={minute_grid_ok}",
        "43,200 unique consecutive minutes in every half-open 30-day profile interval",
        "events_analysis.csv profile timestamps/counts; 1m Parquet open_time",
    ))

    outcome_windows = _outcome_window_results(events, minute_index)
    outcome_expected = pd.to_numeric(events["outcome_expected_minutes"], errors="coerce").eq(config.MAX_HORIZON_MINUTES)
    outcome_observed = pd.to_numeric(events["outcome_observed_minutes"], errors="coerce").eq(config.MAX_HORIZON_MINUTES)
    complete = ~events["outcome_missing"].fillna(True).astype(bool)
    checks.append(_check(
        "17.6", "Full 240-minute outcome interval coverage",
        minute_grid_ok and all(outcome_windows) and bool(outcome_expected.all()) and bool(outcome_observed.all()) and bool(complete.all()),
        f"complete 1m follow-ups={sum(outcome_windows)}/{len(events)}; expected/observed 240="
        f"{int(outcome_expected.sum())}/{int(outcome_observed.sum())}; complete outcomes={int(complete.sum())}/{len(events)}",
        "240 consecutive 1m outcome bars after every event; incomplete follow-up flagged and retained",
        "events_analysis.csv outcome fields; 1m Parquet open_time",
    ))

    first_minute_present = event_times.isin(minute_index)
    breakout_open_present = (event_times - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)).isin(candle_index)
    hit = events["target_hit"].fillna(False).astype(bool)
    target_open = events["target_hit_bar_open_time_utc"]
    target_minutes = pd.to_numeric(events["time_to_target_minutes"], errors="coerce")
    target_timing_ok = (~hit) | (
        target_open.ge(event_times)
        & target_open.lt(event_times + pd.Timedelta(minutes=config.MAX_HORIZON_MINUTES))
        & (((target_open - event_times).dt.total_seconds() / 60.0) + 1).eq(target_minutes)
    )
    checks.append(_check(
        "17.7", "First outcome minute starts strictly after breakout close",
        bool(first_minute_present.all() and breakout_open_present.all() and target_timing_ok.all()),
        f"event_time present as first 1m open={int(first_minute_present.sum())}/{len(events)}; "
        f"breakout candle opens at event_time-15m={int(breakout_open_present.sum())}/{len(events)}; "
        f"target timestamps/durations agree={int(target_timing_ok.sum())}/{len(events)}",
        "Outcome starts at first full 1m bar opening at event_time; breakout candle excluded; target minute is 1..240",
        "events_analysis.csv event/target timestamps; 1m/15m Parquet open_time",
    ))

    ids_unique = not event_ids.duplicated().any() and not raw_ids.duplicated().any()
    ids_match = set(event_ids) == set(raw_ids)
    checks.append(_check(
        "17.8", "No duplicate event IDs", ids_unique and ids_match,
        f"analysis rows/unique={len(events)}/{event_ids.nunique()}; raw rows/unique={len(raw_events)}/{raw_ids.nunique()}; ID sets equal={ids_match}",
        "No duplicate event_id values; raw and analysis ID sets match",
        "events_analysis.csv and events_raw.parquet event_id",
    ))

    outcome_synthetic = _synthetic_outcome_symmetry()
    checks.append(_check(
        "17.9", "Correct UP/DOWN symmetry on artificial test data",
        profile_synthetic["passed"] and outcome_synthetic["passed"],
        f"profile VA UP/DOWN={profile_synthetic['up']['VA']:.12g}/{profile_synthetic['down']['VA']:.12g}; "
        f"target minutes UP/DOWN={outcome_synthetic['up']['time_to_target_minutes']}/"
        f"{outcome_synthetic['down']['time_to_target_minutes']}; "
        f"directional R60 UP/DOWN={outcome_synthetic['up']['r_60']}/{outcome_synthetic['down']['r_60']}",
        "Mirrored synthetic UP/DOWN profiles and price paths produce equivalent VA and direction-normalized outcomes",
        "Production calculate_profile and calculate_outcomes functions on in-memory synthetic inputs",
    ))

    missing = _missing_profile_rows(events)
    missing_reason = events.loc[missing, "va_missing_reason"].astype(str)
    dependent_columns = ("VA", "log1p_VA", "ahead_volume", "reference_volume", "ahead_density", "reference_density")
    null_metrics = events.loc[missing, list(dependent_columns)].isna().all(axis=None)
    unavailable = ~events.loc[missing, "profile_available_for_va_analysis"].fillna(True).astype(bool)
    ineligible = ~events.loc[missing, "primary_analysis_eligible"].fillna(True).astype(bool)
    no_zero_va = pd.to_numeric(events.loc[missing, "VA"], errors="coerce").isna().all()
    exact_reason = missing_reason.eq("reference_region_outside_historical_range").all()
    checks.append(_check(
        "17.10", "Missing data never converted to zero or low volume",
        int(missing.sum()) == 24 and null_metrics and unavailable.all() and ineligible.all() and no_zero_va and exact_reason,
        f"missing profile rows={int(missing.sum())}; VA-dependent values null={bool(null_metrics)}; "
        f"VA unavailable={bool(unavailable.all())}; analysis-ineligible={bool(ineligible.all())}; "
        f"exact reason={bool(exact_reason)}; missing VA is null={bool(no_zero_va)}",
        "24 missing profiles retain null VA/metrics and explicit reason; no imputation or zero substitution",
        "events_analysis.csv profile fields and eligibility flags",
    ))

    # Direct integrity/timing checks clarify the variable active lifetime in Sections 9 and 11.
    lifecycle = _lifecycle_consistency(events, boxes, candles_15m)
    checks.append(_check(
        "I.1", "Section 9/11 active lifetime, first-breakout, and expiration consistency",
        lifecycle["passed"],
        f"boxes={lifecycle['box_count']}; age valid 1..32={lifecycle['age_valid_count']}/{lifecycle['box_count']} "
        f"(range {lifecycle['age_min']}..{lifecycle['age_max']}); age matches termination timestamps="
        f"{lifecycle['age_timestamp_count']}/{lifecycle['box_count']}; active valid-candle counts match age="
        f"{lifecycle['active_ohlc_age_count']}/{lifecycle['box_count']}; first breakout at terminal candle="
        f"{lifecycle['first_breakout_count']}/{lifecycle['breakout_boxes']}; expired without breakout="
        f"{lifecycle['expired_no_breakout_count']}/{lifecycle['expired_boxes']}; expired age 32="
        f"{lifecycle['expired_age_32_count']}/{lifecycle['expired_boxes']}",
        "Active age 1..32; termination timestamp matches persisted age; breakout boxes close on their first valid breakout; expired boxes have no breakout and age 32",
        "consolidation_boxes CSV; events_analysis.csv; 15m Parquet open_time/OHLC/atr_14",
    ))

    activation_rows = boxes.set_index("box_activation")
    event_status = events["box_activation"].map(activation_rows["box_status"])
    event_h = events["box_activation"].map(activation_rows["H"])
    event_l = events["box_activation"].map(activation_rows["L"])
    event_box_matches = (
        event_status.astype(str).str.lower().eq("breakout")
        & events["box_status"].astype(str).str.lower().eq("breakout")
        & event_h.eq(events["H"])
        & event_l.eq(events["L"])
        & events["box_termination_time"].eq(events["breakout_time"])
    )
    checks.append(_check(
        "I.2", "Event-to-box identity and frozen boundaries", bool(event_box_matches.all()),
        f"breakout events matching box status, frozen H/L, and termination={int(event_box_matches.sum())}/{len(events)}",
        "Each event maps to a breakout box with matching activation, status, frozen boundaries, and termination time",
        "events_analysis.csv; consolidation_boxes CSV",
    ))

    start = pd.Timestamp(config.PILOT_START, tz=config.TIMEZONE)
    end = pd.Timestamp(config.PILOT_END, tz=config.TIMEZONE) + pd.Timedelta(days=1)
    period_ok = events["breakout_time"].ge(start).all() and events["breakout_time"].lt(end).all()
    utc_ok = str(minute_index.tz) == config.TIMEZONE and str(candle_index.tz) == config.TIMEZONE
    checks.append(_check(
        "I.3", "UTC grids and fixed pilot period", minute_grid_ok and candle_grid_ok and period_ok and utc_ok,
        f"1m regular UTC={minute_grid_ok and str(minute_index.tz) == config.TIMEZONE}; "
        f"15m regular UTC={candle_grid_ok and str(candle_index.tz) == config.TIMEZONE}; "
        f"events within fixed period={bool(period_ok)}",
        "Strict unique UTC candle grids; event timestamps within 2025-01-01 through 2025-06-30",
        "1m/15m Parquet; events_analysis.csv; config.py",
    ))

    censored = events["right_censored"].fillna(False).astype(bool)
    censored_ok = (
        censored
        & ~events["target_hit"].fillna(False).astype(bool)
        & pd.to_numeric(events["observed_time_minutes"], errors="coerce").eq(config.MAX_HORIZON_MINUTES)
        & pd.to_numeric(events["time_to_target_minutes"], errors="coerce").isna()
        & ~events["outcome_missing"].fillna(True).astype(bool)
    )
    checks.append(_check(
        "I.4", "Right-censored outcomes represented and retained", int(censored.sum()) == 75 and int(censored_ok.sum()) == 75,
        f"right-censored={int(censored.sum())}; correctly represented={int(censored_ok.sum())}; event rows retained={len(events)}",
        "All 75 have target_hit=False, observed_time=240, time_to_target missing, complete follow-up, and remain in table",
        "events_analysis.csv outcome fields",
    ))
    return checks


def render_report(checks: Sequence[Mapping[str, str]]) -> str:
    failures = sum(check["status"] == "FAIL" for check in checks)
    lines = [
        "# Day 3 Block 1 Validation Report", "",
        "Scope: read-only evaluation of the ten mandatory pre-analysis checks in Section 17 of the frozen Pilot v0.1 specification, plus direct integrity/timing checks. No statistical analysis or source-data modifications were performed.", "",
        f"**Overall result: {'FAIL' if failures else 'PASS'}** ({len(checks) - failures} pass, {failures} fail).", "",
        "## Section 17 Checks", "",
        "| Check | Result | Observed value | Expected rule | Evidence/source artifact |", "|---|---|---|---|---|",
    ]
    for item in checks:
        if not item["id"].startswith("17."):
            continue
        values = [f"{item['id']} {item['name']}", item["status"], item["observed"], item["expected"], item["evidence"]]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ") for value in values) + " |")
        if item["note"]:
            lines.extend(["", f"**Note on {item['id']}:** {item['note']}"])
    lines.extend(["", "## Supporting Integrity Checks", "", "| Check | Result | Observed value | Expected rule | Evidence/source artifact |", "|---|---|---|---|---|"])
    for item in checks:
        if item["id"].startswith("17."):
            continue
        values = [f"{item['id']} {item['name']}", item["status"], item["observed"], item["expected"], item["evidence"]]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ") for value in values) + " |")
    lines.extend([
        "", "## Scope Confirmation", "",
        "No temporal splits, embargoes, VA quintiles, proportional-hazards testing, resampling, multiple-testing correction, model fitting, or VA–outcome analysis was performed.", "",
    ])
    return "\n".join(lines)


def write_validation_report(report: str, output_path: Path = REPORT_PATH) -> Path:
    """Write only within the approved Day 3 Block 1 report directory."""
    root = OUTPUT_DIR.resolve()
    target = Path(output_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError("Validation output must be inside reports/day3/block1_validation/") from error
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    return target


def validate_pipeline(
    events: pd.DataFrame,
    candles_15m: pd.DataFrame,
    minute_bars: pd.DataFrame,
    boxes: pd.DataFrame,
    raw_events: pd.DataFrame,
) -> List[Check]:
    """Evaluate validation checks on copies/references without modifying any input frame."""
    return evaluate_validation_checks(events, raw_events, boxes, minute_bars, candles_15m)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    events, raw_events, boxes, minute_bars, candles_15m = load_artifacts()
    checks = validate_pipeline(events, candles_15m, minute_bars, boxes, raw_events)
    report_path = write_validation_report(render_report(checks))
    for item in checks:
        print(f"{item['status']} {item['id']} {item['name']}: {item['observed']}")
    failures = sum(item["status"] == "FAIL" for item in checks)
    print(f"Overall: {'FAIL' if failures else 'PASS'} ({len(checks) - failures} pass, {failures} fail)")
    print(f"Report: {report_path.relative_to(PROJECT_ROOT).as_posix()}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())