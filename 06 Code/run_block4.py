"""Агрегация 15m, Consolidation Box detector и диагностика блока 4."""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import config
from detect_boxes import detect_boxes, pilot_period
from download_data import DATASET_PATH as MINUTE_DATASET_PATH, validate_data
from prepare_candles import aggregate_15m, wilder_atr


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "05 Data" / "processed"
OUTPUT_TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
OUTPUT_FIGURES_DIR = PROJECT_ROOT / "reports" / "block4" / "figures"
DIAGNOSTIC_PATH = PROJECT_ROOT / "reports" / "block4" / "consolidation_detector_diagnostics.json"
PERIOD_TAG = f"{config.PILOT_START}_{config.PILOT_END}"
FIFTEEN_MINUTE_DATASET_PATH = PROCESSED_DIR / f"binance_btcusdt_spot_15m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
EVENTS_PATH = OUTPUT_TABLES_DIR / f"consolidation_breakout_events_{PERIOD_TAG}.csv"
BOXES_PATH = OUTPUT_TABLES_DIR / f"consolidation_boxes_{PERIOD_TAG}.csv"
EVENT_FIGURE_PATH = OUTPUT_FIGURES_DIR / f"breakout_event_review_{PERIOD_TAG}.png"
EXPIRED_FIGURE_PATH = OUTPUT_FIGURES_DIR / f"expired_box_review_{PERIOD_TAG}.png"


def _utc_period() -> Tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(config.PILOT_START, tz=config.TIMEZONE)
    end = pd.Timestamp(config.PILOT_END, tz=config.TIMEZONE) + pd.Timedelta(days=1)
    return start, end


def _within_period(values: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    timestamps = pd.to_datetime(values, utc=True)
    return timestamps.ge(start) & timestamps.le(end)


def _sample_event_boxes(events: pd.DataFrame, boxes: pd.DataFrame) -> List[Tuple[pd.Series, pd.Series]]:
    samples: List[Tuple[pd.Series, pd.Series]] = []
    selected_activations = set()
    for direction in ("upward", "downward"):
        directional = events.loc[events["direction"].eq(direction)].sort_values("breakout_time")
        for _, event in directional.head(5).iterrows():
            matches = boxes.loc[boxes["box_activation"].eq(event["box_activation"])]
            if not matches.empty:
                samples.append((matches.iloc[0], event))
                selected_activations.add(event["box_activation"])
    if len(samples) < min(10, len(events)):
        for _, event in events.sort_values("breakout_time").iterrows():
            if event["box_activation"] in selected_activations:
                continue
            matches = boxes.loc[boxes["box_activation"].eq(event["box_activation"])]
            if not matches.empty:
                samples.append((matches.iloc[0], event))
                selected_activations.add(event["box_activation"])
            if len(samples) >= min(10, len(events)):
                break
    return samples


def _font(size: int) -> Any:
    try:
        return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _dashed_line(draw: Any, start: Tuple[int, int], end: Tuple[int, int], fill: str, dash: int = 7) -> None:
    x1, y1 = start
    x2, y2 = end
    length = max(abs(x2 - x1), abs(y2 - y1))
    if length == 0:
        return
    for offset in range(0, length, dash * 2):
        end_offset = min(offset + dash, length)
        first = (x1 + (x2 - x1) * offset // length, y1 + (y2 - y1) * offset // length)
        last = (x1 + (x2 - x1) * end_offset // length, y1 + (y2 - y1) * end_offset // length)
        draw.line((first, last), fill=fill, width=2)


def _draw_sample_panel(
    draw: Any,
    rectangle: Tuple[int, int, int, int],
    candles: pd.DataFrame,
    box: pd.Series,
    event: pd.Series = None,
) -> None:
    interval = pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    start_time = pd.Timestamp(box["box_start"])
    end_time = pd.Timestamp(box["box_termination_time"])
    visible = candles.loc[
        candles["open_time"].ge(start_time)
        & candles["open_time"].lt(end_time)
    ].reset_index(drop=True)
    left, top, right, bottom = rectangle
    draw.rectangle(rectangle, fill="#fbfcfa", outline="#cbd4d2", width=2)
    if visible.empty:
        draw.text((left + 20, top + 30), "No candles in box interval", font=_font(18), fill="#263a3c")
        return

    title_font = _font(17)
    label_font = _font(13)
    chart_left, chart_right = left + 70, right - 24
    chart_top, chart_bottom = top + 54, bottom - 54
    activation_time = pd.Timestamp(box["box_activation"])
    termination_candle_time = end_time - interval
    prices = visible[["high", "low"]].to_numpy(dtype=float).ravel().tolist() + [float(box["H"]), float(box["L"])]
    price_min, price_max = min(prices), max(prices)
    padding = max((price_max - price_min) * 0.08, abs(price_max) * 0.0002)
    price_min -= padding
    price_max += padding
    chart_height = chart_bottom - chart_top
    chart_width = chart_right - chart_left
    price_y = lambda value: int(chart_bottom - (value - price_min) / (price_max - price_min) * chart_height)
    spacing = chart_width / max(len(visible) - 1, 1)
    candle_width = max(3, min(10, int(spacing * 0.56)))

    for grid_part in range(5):
        y_position = chart_top + chart_height * grid_part // 4
        price = price_max - (price_max - price_min) * grid_part / 4
        draw.line((chart_left, y_position, chart_right, y_position), fill="#e3e8e6", width=1)
        draw.text((left + 8, y_position - 8), f"{price:,.0f}", font=label_font, fill="#536366")

    activation_positions = visible.index[visible["open_time"].eq(activation_time)].tolist()
    termination_positions = visible.index[visible["open_time"].eq(termination_candle_time)].tolist()
    activation_x = int(chart_left + activation_positions[0] * spacing) if activation_positions else chart_left
    termination_x = int(chart_left + termination_positions[-1] * spacing) if termination_positions else chart_right
    for boundary in (box["H"], box["L"]):
        y_position = price_y(float(boundary))
        _dashed_line(draw, (activation_x, y_position), (chart_right, y_position), "#315a7d", dash=5)
        draw.text((chart_right - 66, y_position - 17), f"{boundary:,.1f}", font=label_font, fill="#315a7d")

    _dashed_line(draw, (activation_x, chart_top), (activation_x, chart_bottom), "#cc8c27", dash=5)
    _dashed_line(draw, (termination_x, chart_top), (termination_x, chart_bottom), "#8b4d63", dash=4)
    for position, row in visible.iterrows():
        up = row["close"] >= row["open"]
        color = "#16836b" if up else "#c34b45"
        x_position = int(chart_left + position * spacing)
        draw.line((x_position, price_y(float(row["high"])), x_position, price_y(float(row["low"]))), fill=color, width=2)
        body_top = price_y(float(max(row["open"], row["close"])))
        body_bottom = price_y(float(min(row["open"], row["close"])))
        if body_bottom - body_top < 2:
            body_bottom = body_top + 2
        draw.rectangle(
            (x_position - candle_width // 2, body_top, x_position + candle_width // 2, body_bottom),
            fill=color,
            outline=color,
        )

    if event is None:
        title = f"Expired | age {int(box['box_age_candles'])} | {activation_time:%Y-%m-%d %H:%M} UTC"
    else:
        title = f"{event['direction']} breakout | age {int(event['box_age'])} | {event['breakout_time']:%Y-%m-%d %H:%M} UTC"
    draw.text((left + 14, top + 12), title, font=title_font, fill="#203638")
    draw.text((chart_left, bottom - 40), f"Start {start_time:%m-%d %H:%M} UTC", font=label_font, fill="#536366")
    draw.text((chart_right - 158, bottom - 40), f"End {termination_candle_time:%m-%d %H:%M} UTC", font=label_font, fill="#536366")
    draw.text((left + 15, top + 34), "H/L frozen", font=label_font, fill="#315a7d")
    draw.text((left + 125, top + 34), "Activation", font=label_font, fill="#a36c16")
    draw.text((left + 230, top + 34), "Breakout" if event is not None else "Expiration", font=label_font, fill="#8b4d63")


def _save_review_figure(
    samples: List[Tuple[pd.Series, pd.Series]],
    candles: pd.DataFrame,
    output_path: Path,
    expired: bool = False,
) -> None:
    if not samples:
        return
    columns = 2 if len(samples) <= 10 else 3
    rows = (len(samples) + columns - 1) // columns
    panel_width, panel_height = 1000, 390
    image = Image.new("RGB", (columns * panel_width, rows * panel_height), "#eef2f0")
    draw = ImageDraw.Draw(image)
    heading = "Expired Consolidation Boxes" if expired else "Consolidation Breakout Events"
    draw.text((24, 14), heading, font=_font(23), fill="#203638")
    for index, (box, event) in enumerate(samples):
        column, row = index % columns, index // columns
        left = column * panel_width + 14
        top = row * panel_height + 52
        rectangle = (left, top, left + panel_width - 28, top + panel_height - 64)
        _draw_sample_panel(draw, rectangle, candles, box, None if expired else event)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)


def _event_field_errors(events: pd.DataFrame) -> int:
    required = (
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
    )
    if events.empty:
        return 0
    invalid = events.loc[:, required].isna().any(axis=1)
    for column in ("box_start", "box_activation", "breakout_time"):
        parsed = pd.to_datetime(events[column], errors="coerce")
        if not isinstance(parsed.dtype, pd.DatetimeTZDtype) or str(parsed.dt.tz) != config.TIMEZONE:
            invalid |= True
        invalid |= parsed.isna()
    numeric_columns = ("H", "L", "ATR", "box_width", "box_age", "breakout_close", "breakout_strength")
    numeric = events.loc[:, numeric_columns].apply(pd.to_numeric, errors="coerce")
    invalid |= ~np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
    invalid |= numeric["ATR"] <= 0
    invalid |= numeric["H"] <= numeric["L"]
    invalid |= numeric["box_width"] <= 0
    invalid |= ~events["direction"].isin(("upward", "downward"))
    invalid |= events["event_id"].duplicated(keep=False)
    return int(invalid.sum())


def run_block4() -> Dict[str, Any]:
    """Создать 15m данные, события, диагностику и визуальные проверки."""
    minute_bars = pd.read_parquet(MINUTE_DATASET_PATH)
    quality, missing_minutes = validate_data(minute_bars)
    if not quality["checks_passed"] or len(missing_minutes):
        raise ValueError("Очищенный 1m набор не прошёл повторную проверку качества")

    start, end = _utc_period()
    candles = aggregate_15m(minute_bars)
    candles["atr_14"] = wilder_atr(candles)
    expected_15m = pd.date_range(
        candles["open_time"].iloc[0],
        candles["open_time"].iloc[-1],
        freq=f"{config.CANDLE_INTERVAL_MINUTES}min",
    )
    candle_index = pd.DatetimeIndex(candles["open_time"])
    missing_15m = expected_15m.difference(candle_index)
    expected_first_15m = pd.Timestamp(config.WARMUP_START, tz=config.TIMEZONE)
    expected_last_15m = end - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    minute_groups = minute_bars.assign(
        _interval_start=pd.to_datetime(minute_bars["open_time"], utc=True).dt.floor(
            f"{config.CANDLE_INTERVAL_MINUTES}min"
        )
    ).groupby("_interval_start").size()
    incomplete_groups = int(minute_groups.ne(config.BARS_PER_CANDLE).sum())
    numeric_ohlc = candles[["open", "high", "low", "close"]].to_numpy(dtype=float)
    ohlc_valid = bool(
        np.isfinite(numeric_ohlc).all()
        and (candles["high"] >= candles[["open", "close", "low"]].max(axis=1)).all()
        and (candles["low"] <= candles[["open", "close", "high"]].min(axis=1)).all()
    )
    if (
        len(missing_15m)
        or incomplete_groups
        or not ohlc_valid
        or candles["open_time"].iloc[0] != expected_first_15m
        or candles["open_time"].iloc[-1] != expected_last_15m
    ):
        raise ValueError("15m aggregation validation failed")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    candles.to_parquet(FIFTEEN_MINUTE_DATASET_PATH, index=False)
    persisted_candles = pd.read_parquet(FIFTEEN_MINUTE_DATASET_PATH)
    if len(persisted_candles) != len(candles) or str(persisted_candles["open_time"].dt.tz) != config.TIMEZONE:
        raise ValueError("15m Parquet round-trip validation failed")

    result = detect_boxes(candles)
    pilot_events = pilot_period(result.events)
    pilot_boxes = result.boxes.loc[
        _within_period(result.boxes["box_termination_time"], start, end)
    ].reset_index(drop=True)
    pilot_box_activations = set(pilot_boxes["box_activation"])
    pilot_events = pilot_events.loc[pilot_events["box_activation"].isin(pilot_box_activations)].reset_index(drop=True)

    samples = _sample_event_boxes(pilot_events, pilot_boxes)
    expired_boxes = pilot_boxes.loc[pilot_boxes["box_status"].eq("expired")].sort_values("box_activation")
    expired_samples = [(row, None) for _, row in expired_boxes.head(3).iterrows()]
    _save_review_figure(samples, candles, EVENT_FIGURE_PATH)
    _save_review_figure(expired_samples, candles, EXPIRED_FIGURE_PATH, expired=True)

    OUTPUT_TABLES_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    pilot_events.to_csv(EVENTS_PATH, index=False)
    pilot_boxes.to_csv(BOXES_PATH, index=False)
    timestamp_columns = [
        "box_start",
        "box_activation",
        "breakout_time",
        "box_start_time",
        "box_activation_time",
        "breakout_time_utc",
        "box_termination_time",
    ]
    persisted_events = pd.read_csv(EVENTS_PATH, parse_dates=timestamp_columns)
    if not persisted_events.empty and any(
        not isinstance(persisted_events[column].dtype, pd.DatetimeTZDtype)
        or str(persisted_events[column].dt.tz) != config.TIMEZONE
        for column in timestamp_columns
    ):
        raise ValueError("Event CSV round-trip lost timezone-aware UTC timestamps")

    overlaps = 0
    if len(pilot_boxes) > 1:
        ordered_boxes = pilot_boxes.sort_values("box_activation")
        overlaps = int(
            (
                ordered_boxes["box_activation"].iloc[1:].reset_index(drop=True)
                < ordered_boxes["box_termination_time"].iloc[:-1].reset_index(drop=True)
            ).sum()
        )
    event_times = pd.to_datetime(pilot_events["breakout_time"], utc=True) if not pilot_events.empty else pd.Series(dtype="datetime64[ns, UTC]")
    diagnostic: Dict[str, Any] = {
        "status": "passed" if not len(missing_15m) and not incomplete_groups and ohlc_valid else "failed",
        "timezone": config.TIMEZONE,
        "period_start_utc": pd.Timestamp(config.WARMUP_START, tz=config.TIMEZONE).isoformat(),
        "period_end_utc": end.isoformat(),
        "pilot_start_utc": start.isoformat(),
        "pilot_end_exclusive_utc": end.isoformat(),
        "minute_candles": int(len(minute_bars)),
        "expected_minute_candles": int(quality["expected_rows"]),
        "fifteen_minute_candles": int(len(candles)),
        "expected_fifteen_minute_candles": int(len(expected_15m)),
        "expected_first_fifteen_minute_open_time_utc": expected_first_15m.isoformat(),
        "actual_first_fifteen_minute_open_time_utc": candles["open_time"].iloc[0].isoformat(),
        "expected_last_fifteen_minute_open_time_utc": expected_last_15m.isoformat(),
        "actual_last_fifteen_minute_open_time_utc": candles["open_time"].iloc[-1].isoformat(),
        "missing_fifteen_minute_intervals": int(len(missing_15m)),
        "incomplete_source_groups": incomplete_groups,
        "fifteen_minute_duplicates": int(candles["open_time"].duplicated().sum()),
        "fifteen_minute_sorted": bool(candles["open_time"].is_monotonic_increasing),
        "fifteen_minute_timezone": str(candles["open_time"].dt.tz),
        "fifteen_minute_ohlc_valid": ohlc_valid,
        "atr_14_first_valid_time_utc": (
            candles.loc[candles["atr_14"].notna(), "open_time"].iloc[0].isoformat()
            if candles["atr_14"].notna().any()
            else None
        ),
        "boxes": int(len(pilot_boxes)),
        "breakout_events": int(len(pilot_events)),
        "upward_events": int(pilot_events["direction"].eq("upward").sum()),
        "downward_events": int(pilot_events["direction"].eq("downward").sum()),
        "expired_boxes_without_breakout": int(pilot_boxes["box_status"].eq("expired").sum()),
        "minimum_breakout_time_utc": event_times.min().isoformat() if not event_times.empty else None,
        "maximum_breakout_time_utc": event_times.max().isoformat() if not event_times.empty else None,
        "overlapping_boxes": overlaps,
        "invalid_or_missing_required_event_fields": _event_field_errors(pilot_events),
        "event_csv_timestamps_timezone_aware_utc": bool(
            persisted_events.empty
            or all(
                isinstance(persisted_events[column].dtype, pd.DatetimeTZDtype)
                and str(persisted_events[column].dt.tz) == config.TIMEZONE
                for column in timestamp_columns
            )
        ),
        "incomplete_active_boxes_at_data_end": result.diagnostics["incomplete_active_boxes"],
        "insufficient_width_history_candidates": result.diagnostics["insufficient_width_history_candidates"],
        "breakout_charts_created": len(samples),
        "expired_box_charts_created": len(expired_samples),
        "event_table_path": str(EVENTS_PATH.relative_to(PROJECT_ROOT)),
        "box_table_path": str(BOXES_PATH.relative_to(PROJECT_ROOT)),
        "fifteen_minute_parquet_path": str(FIFTEEN_MINUTE_DATASET_PATH.relative_to(PROJECT_ROOT)),
        "breakout_figure_path": str(EVENT_FIGURE_PATH.relative_to(PROJECT_ROOT)) if samples else None,
        "expired_figure_path": str(EXPIRED_FIGURE_PATH.relative_to(PROJECT_ROOT)) if expired_samples else None,
        "parameters": {
            "box_length": config.BOX_LENGTH,
            "box_max_age": config.BOX_MAX_AGE,
            "width_quantile": config.WIDTH_QUANTILE,
            "width_lookback_days": config.WIDTH_LOOKBACK_DAYS,
            "efficiency_ratio_threshold": config.ER_THRESHOLD,
            "central_closes_minimum": config.CENTRAL_CLOSES_MIN,
            "atr_length": config.ATR_LENGTH,
            "breakout_buffer_atr": config.BREAKOUT_BUFFER_ATR,
        },
    }
    DIAGNOSTIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC_PATH.write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(diagnostic, indent=2, ensure_ascii=False))
    return diagnostic


if __name__ == "__main__":
    run_block4()