"""Generate an outcome-blind manual validation package for Pilot v0.1."""

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERIOD_TAG = f"{config.PILOT_START}_{config.PILOT_END}"
EVENTS_PATH = PROJECT_ROOT / "outputs" / "tables" / "events_analysis.csv"
ANALYSIS_EVENTS_PATH = EVENTS_PATH
BOXES_PATH = PROJECT_ROOT / "outputs" / "tables" / f"consolidation_boxes_{PERIOD_TAG}.csv"
CANDLES_PATH = PROJECT_ROOT / "05 Data" / "processed" / (
    f"binance_btcusdt_spot_15m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
)
OUTPUT_DIR = PROJECT_ROOT / "reports" / "block4" / "manual_validation"
CHARTS_DIR_NAME = "charts"
MANIFEST_NAME = "review_manifest.csv"
GUIDE_NAME = "MANUAL_REVIEW_GUIDE.md"
REPORT_NAME = "MANUAL_VALIDATION_REPORT.md"
ALLOWED_MANUAL_STATUSES = ("pass", "questionable", "fail")
EXPECTED_REVIEW_ITEMS = 49
EXPECTED_BREAKOUT_ITEMS = 44
EXPECTED_EXPIRED_ITEMS = 5
EXPECTED_PROFILE_MISSING_ITEMS = 24
PROFILE_MISSING_REASON = "reference_region_outside_historical_range"

MANIFEST_COLUMNS = (
    "review_id",
    "item_type",
    "event_id_or_box_id",
    "categories",
    "chart_path",
    "direction",
    "activation_time",
    "breakout_or_expiration_time",
    "VA",
    "missing_reason",
    "manual_status",
    "manual_notes",
)

CATEGORY_ORDER = (
    "earliest_upward_breakouts",
    "earliest_downward_breakouts",
    "lowest_valid_va",
    "highest_valid_va",
    "profile_missing",
    "ambiguous_intrabar",
    "earliest_expired_boxes",
)

GUIDE_TEXT = """# Manual Validation Guide: Day 2, Block 4

## Run

From `06 Code/`, run:

```sh
python3 manual_validation.py
```

The script reads the saved event analysis CSV, detector box CSV, and 15-minute Parquet. It writes one chart per unique review item, `review_manifest.csv`, and this guide under `reports/block4/manual_validation/`. It does not edit the input tables or Parquet files.

Pilot v0.1 uses the frozen 240-minute outcome horizon. The stale “next 20 hourly bars” wording in the older pilot instructions does not apply.

## Record a Review

Fill `manual_status` with exactly one of `pass`, `questionable`, or `fail`. Add a concise explanation in `manual_notes`. Leave both fields blank until a human reviews the item.

Assess only detection and data correctness: whether the displayed candles and UTC times match the saved data; whether the box start, activation, frozen H/L and breakout or expiration are placed correctly; whether direction and breakout close agree with the detector record; whether the profile-validity label and Ahead Region geometry agree with the frozen inputs; and whether the target/censor annotation matches the saved outcome record.

Future outcome quality must never influence acceptance. Do not pass or fail an event because it hit a target, moved quickly or favorably, returned to the box, or had a particular return, MFE, MAE, or censoring status. Outcome annotations are displayed for data checking only.

Do not silently change thresholds, formulas, sample dates, detector/profile/outcome logic, or event inclusion rules during review. Record a proposed methodology change separately and obtain approval for a new specification version before implementing it.
"""


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _as_bool(value: Any) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _utc(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(config.TIMEZONE)
    return timestamp.tz_convert(config.TIMEZONE)


def _iso_utc(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return _utc(value).isoformat().replace("+00:00", "Z")


def _event_valid_va(events: pd.DataFrame) -> pd.Series:
    values = pd.to_numeric(events["VA"], errors="coerce")
    return (
        events["profile_valid"].map(_as_bool)
        & ~events["va_missing"].map(_as_bool)
        & values.notna()
        & np.isfinite(values.to_numpy(dtype=float))
    )


def _stable_time_sort(frame: pd.DataFrame, time_column: str, tie_column: str) -> pd.DataFrame:
    result = frame.copy()
    result[time_column] = pd.to_datetime(result[time_column], utc=True, errors="coerce")
    if result[time_column].isna().any():
        raise ValueError(f"Invalid UTC timestamps in {time_column}")
    return result.sort_values([time_column, tie_column], kind="mergesort")


def select_review_items(events: pd.DataFrame, boxes: pd.DataFrame) -> List[Dict[str, Any]]:
    """Select required cases without using outcome quality or performance fields."""
    required_events = {
        "event_id",
        "breakout_time",
        "direction",
        "box_activation",
        "VA",
        "profile_valid",
        "va_missing",
        "ambiguous_intrabar",
    }
    missing_events = required_events.difference(events.columns)
    if missing_events:
        raise ValueError(f"Event table is missing columns: {sorted(missing_events)}")
    required_boxes = {"box_start", "box_activation", "box_termination_time", "box_status"}
    missing_boxes = required_boxes.difference(boxes.columns)
    if missing_boxes:
        raise ValueError(f"Box table is missing columns: {sorted(missing_boxes)}")
    if events["event_id"].isna().any() or events["event_id"].astype(str).duplicated().any():
        raise ValueError("event_id values must be present and unique")

    event_frame = events.copy()
    event_frame["event_id"] = event_frame["event_id"].astype(str)
    event_frame["breakout_time"] = pd.to_datetime(event_frame["breakout_time"], utc=True, errors="coerce")
    event_frame["box_activation"] = pd.to_datetime(event_frame["box_activation"], utc=True, errors="coerce")
    if event_frame[["breakout_time", "box_activation"]].isna().any().any():
        raise ValueError("Event table contains invalid UTC timestamps")
    valid_va = _event_valid_va(event_frame)
    numeric_va = pd.to_numeric(event_frame["VA"], errors="coerce")
    selected: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add_event_rows(rows: pd.DataFrame, category: str) -> None:
        for _, row in rows.iterrows():
            key = ("breakout", str(row["event_id"]))
            item = selected.setdefault(key, {"item_type": "breakout", "source": row.copy(), "categories": []})
            if category not in item["categories"]:
                item["categories"].append(category)

    ordered = _stable_time_sort(event_frame, "breakout_time", "event_id")
    for direction, category in (
        ("upward", "earliest_upward_breakouts"),
        ("downward", "earliest_downward_breakouts"),
    ):
        add_event_rows(ordered.loc[ordered["direction"].eq(direction)].head(5), category)

    valid_events = event_frame.loc[valid_va].copy()
    valid_events["_numeric_va"] = numeric_va.loc[valid_va]
    low = valid_events.sort_values(
        ["_numeric_va", "breakout_time", "event_id"],
        ascending=[True, True, True],
        kind="mergesort",
    ).head(5)
    high = valid_events.sort_values(
        ["_numeric_va", "breakout_time", "event_id"],
        ascending=[False, True, True],
        kind="mergesort",
    ).head(5)
    add_event_rows(low, "lowest_valid_va")
    add_event_rows(high, "highest_valid_va")
    add_event_rows(event_frame.loc[~valid_va].sort_values(["breakout_time", "event_id"], kind="mergesort"), "profile_missing")
    ambiguous = event_frame.loc[event_frame["ambiguous_intrabar"].map(_as_bool)]
    add_event_rows(ambiguous.sort_values(["breakout_time", "event_id"], kind="mergesort"), "ambiguous_intrabar")

    expired = boxes.loc[boxes["box_status"].astype(str).str.lower().eq("expired")].copy()
    if not expired.empty:
        expired["_box_sort_id"] = expired["box_activation"].astype(str) + "|" + expired["box_termination_time"].astype(str)
        expired = _stable_time_sort(expired, "box_activation", "_box_sort_id").head(5)
        for _, row in expired.iterrows():
            activation = _utc(row["box_activation"])
            box_id = f"expired-box-{activation:%Y%m%dT%H%M%SZ}"
            key = ("expired_box", box_id)
            item = selected.setdefault(key, {"item_type": "expired_box", "source": row.copy(), "categories": []})
            item["categories"].append("earliest_expired_boxes")

    category_rank = {category: rank for rank, category in enumerate(CATEGORY_ORDER)}
    items = list(selected.values())
    items.sort(
        key=lambda item: (
            _utc(item["source"]["box_activation"]),
            item["item_type"],
            str(item["source"].get("event_id", "")),
        )
    )
    for item in items:
        item["categories"] = sorted(item["categories"], key=category_rank.__getitem__)
    return items


def target_price_for_event(event: pd.Series) -> float:
    """Return the frozen 1 ATR target solely for chart annotation."""
    direction = event.get("direction", event.get("breakout_direction"))
    sign = 1.0 if direction == "upward" else -1.0 if direction == "downward" else None
    if sign is None:
        raise ValueError(f"Unsupported breakout direction: {direction}")
    return float(event["breakout_close"]) + sign * config.TARGET_ATR * float(event["ATR"])


def outcome_annotation(event: pd.Series) -> Tuple[str, Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """Return chart text, its vertical-marker time, and the chart end time."""
    event_time = _utc(event["breakout_time"])
    horizon_end = event_time + pd.Timedelta(minutes=config.MAX_HORIZON_MINUTES)
    if _as_bool(event.get("target_hit", False)):
        hit_open = event.get("target_hit_bar_open_time_utc")
        if pd.isna(hit_open):
            minutes = int(event["time_to_target_minutes"])
            hit_open = event_time + pd.Timedelta(minutes=minutes - 1)
        hit_open = _utc(hit_open)
        chart_end = hit_open.floor(f"{config.CANDLE_INTERVAL_MINUTES}min") + pd.Timedelta(
            minutes=2 * config.CANDLE_INTERVAL_MINUTES
        )
        chart_end = min(chart_end, horizon_end)
        minutes = int(event["time_to_target_minutes"])
        label = f"Target hit in {minutes} min; target-touch minute opens {_iso_utc(hit_open)}"
        return label, hit_open, chart_end
    if _as_bool(event.get("right_censored", False)):
        return f"240-minute right-censor endpoint {_iso_utc(horizon_end)}", horizon_end, horizon_end
    reason = event.get("outcome_missing_reason")
    label = f"Outcome annotation unavailable: {reason or 'incomplete follow-up'}"
    return label, None, horizon_end


def missing_va_reason(event: pd.Series) -> str:
    reason = event.get("va_missing_reason")
    if reason is None or pd.isna(reason) or not str(reason).strip():
        reason = event.get("profile_missing_reason")
    return str(reason) if reason is not None and not pd.isna(reason) else "profile_missing_reason_unavailable"


def _dashed_line(
    draw: ImageDraw.ImageDraw,
    start: Tuple[int, int],
    end: Tuple[int, int],
    fill: str,
    width: int = 2,
    dash: int = 9,
) -> None:
    x1, y1 = start
    x2, y2 = end
    length = max(abs(x2 - x1), abs(y2 - y1))
    if length == 0:
        return
    for offset in range(0, length, dash * 2):
        last_offset = min(offset + dash, length)
        first = (x1 + (x2 - x1) * offset // length, y1 + (y2 - y1) * offset // length)
        last = (x1 + (x2 - x1) * last_offset // length, y1 + (y2 - y1) * last_offset // length)
        draw.line((first, last), fill=fill, width=width)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_chart(item: Dict[str, Any], candles: pd.DataFrame, output_path: Path, review_id: str) -> None:
    source = item["source"]
    expired = item["item_type"] == "expired_box"
    box_start = _utc(source["box_start"])
    activation = _utc(source["box_activation"])
    termination = _utc(source["box_termination_time"])
    event_time: Optional[pd.Timestamp] = None
    hit_or_censor_time: Optional[pd.Timestamp] = None
    target: Optional[float] = None
    ahead_low: Optional[float] = None
    ahead_high: Optional[float] = None
    if expired:
        chart_end = termination
        item_title = "EXPIRED WITHOUT BREAKOUT"
    else:
        event_time = _utc(source["breakout_time"])
        outcome_label, hit_or_censor_time, chart_end = outcome_annotation(source)
        target = target_price_for_event(source)
        direction = source["direction"]
        boundary = float(source["H"] if direction == "upward" else source["L"])
        atr = float(source["ATR"])
        bin_width = config.BIN_WIDTH_ATR * atr
        if direction == "upward":
            ahead_low, ahead_high = boundary, boundary + config.AHEAD_BIN_COUNT * bin_width
        else:
            ahead_low, ahead_high = boundary - config.AHEAD_BIN_COUNT * bin_width, boundary
        item_title = f"{str(direction).upper()} BREAKOUT  |  {source['event_id']}"

    candle_frame = candles.loc[
        candles["open_time"].ge(box_start) & candles["open_time"].lt(chart_end)
    ].copy().reset_index(drop=True)
    if candle_frame.empty:
        raise ValueError(f"No 15-minute candles available for {review_id}")
    chart_start = box_start
    if chart_end <= chart_start:
        raise ValueError(f"Invalid chart time window for {review_id}")

    width, height = 1900, 1180
    image = Image.new("RGB", (width, height), "#f4f6f4")
    draw = ImageDraw.Draw(image)
    title_font = _font(30, bold=True)
    meta_font = _font(18)
    label_font = _font(15)
    small_font = _font(13)
    ink = "#25383a"
    muted = "#526365"
    plot = (122, 260, 1635, 1005)
    left, top, right, bottom = plot

    draw.text((46, 24), item_title, font=title_font, fill=ink)
    draw.text(
        (48, 72),
        f"Review {review_id}  |  Categories: {'; '.join(item['categories'])}",
        font=meta_font,
        fill=muted,
    )
    if expired:
        detail = (
            f"Box start {_iso_utc(box_start)}  |  Activation {_iso_utc(activation)}  |  "
            f"Expiration {_iso_utc(termination)}  |  Frozen H {float(source['H']):,.2f}  |  "
            f"Frozen L {float(source['L']):,.2f}  |  expired without breakout"
        )
        draw.text((48, 116), detail, font=meta_font, fill=ink)
    else:
        direction = str(source["direction"])
        va_valid = _event_valid_va(pd.DataFrame([source])).iloc[0]
        va_text = f"VA {float(source['VA']):.6g}" if va_valid else f"VA missing: {missing_va_reason(source)}"
        detail_one = (
            f"Box start {_iso_utc(box_start)}  |  Activation {_iso_utc(activation)}  |  "
            f"Breakout close {_iso_utc(event_time)} ({direction})"
        )
        detail_two = (
            f"Frozen H {float(source['H']):,.2f}  |  Frozen L {float(source['L']):,.2f}  |  "
            f"Breakout close price {float(source['breakout_close']):,.2f}  |  {va_text}"
        )
        draw.text((48, 112), detail_one, font=meta_font, fill=ink)
        draw.text((48, 148), detail_two, font=meta_font, fill=ink)
        draw.text((48, 184), outcome_label, font=meta_font, fill="#8d4a5b")
        ahead_text = f"Ahead Region [{ahead_low:,.2f}, {ahead_high:,.2f})  |  B={float(source['H'] if direction == 'upward' else source['L']):,.2f}  d=0.05 x ATR[t-1]={config.BIN_WIDTH_ATR * float(source['ATR']):,.4f}"
        draw.text((48, 218), ahead_text, font=meta_font, fill="#286c78")

    all_prices = candle_frame[["high", "low"]].to_numpy(dtype=float).ravel().tolist()
    all_prices.extend([float(source["H"]), float(source["L"])])
    if target is not None:
        all_prices.append(target)
    if ahead_low is not None and ahead_high is not None:
        all_prices.extend([ahead_low, ahead_high])
    price_min, price_max = min(all_prices), max(all_prices)
    span = max(price_max - price_min, abs(price_max) * 0.0001, 1e-8)
    price_min -= span * 0.07
    price_max += span * 0.07
    time_span_seconds = (chart_end - chart_start).total_seconds()

    def x_at(timestamp: pd.Timestamp) -> int:
        fraction = (timestamp - chart_start).total_seconds() / time_span_seconds
        return int(left + fraction * (right - left))

    def y_at(price: float) -> int:
        return int(bottom - (price - price_min) / (price_max - price_min) * (bottom - top))

    draw.rectangle(plot, fill="#fbfcfa", outline="#b9c7c4", width=2)
    if ahead_low is not None and ahead_high is not None:
        y_high, y_low = y_at(ahead_high), y_at(ahead_low)
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle((left, y_high, right, y_low), fill=(76, 170, 180, 58))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(image)

    for grid_index in range(7):
        fraction = grid_index / 6
        y = int(top + fraction * (bottom - top))
        price = price_max - fraction * (price_max - price_min)
        draw.line((left, y, right, y), fill="#e1e7e4", width=1)
        label = f"{price:,.1f}"
        bounds = draw.textbbox((0, 0), label, font=label_font)
        draw.text((left - (bounds[2] - bounds[0]) - 14, y - 9), label, font=label_font, fill=muted)

    for tick_index in range(5):
        timestamp = chart_start + (chart_end - chart_start) * tick_index / 4
        x = x_at(timestamp)
        draw.line((x, top, x, bottom), fill="#edf0ee", width=1)
        label = timestamp.strftime("%m-%d %H:%M UTC")
        bounds = draw.textbbox((0, 0), label, font=small_font)
        draw.text((x - (bounds[2] - bounds[0]) // 2, bottom + 12), label, font=small_font, fill=muted)

    interval = pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    candle_spacing = (right - left) * interval.total_seconds() / time_span_seconds
    candle_width = max(3, min(17, int(candle_spacing * 0.62)))
    breakout_candle_open = event_time - interval if event_time is not None else None
    for _, candle in candle_frame.iterrows():
        open_time = _utc(candle["open_time"])
        center_time = open_time + interval / 2
        x = x_at(center_time)
        if breakout_candle_open is not None and open_time == breakout_candle_open:
            draw.rectangle(
                (x - candle_width, top, x + candle_width, bottom),
                fill="#fff3d6",
            )
        up = float(candle["close"]) >= float(candle["open"])
        color = "#13836d" if up else "#c64f4a"
        draw.line((x, y_at(float(candle["high"])), x, y_at(float(candle["low"]))), fill=color, width=2)
        body_top = y_at(max(float(candle["open"]), float(candle["close"])))
        body_bottom = y_at(min(float(candle["open"]), float(candle["close"])))
        if body_bottom - body_top < 2:
            body_bottom = body_top + 2
        draw.rectangle((x - candle_width // 2, body_top, x + candle_width // 2, body_bottom), fill=color, outline=color)

    boundary_labels: List[Tuple[int, float, str]] = []
    for boundary, label in ((float(source["H"]), "Frozen H"), (float(source["L"]), "Frozen L")):
        y = y_at(boundary)
        _dashed_line(draw, (x_at(activation), y), (right, y), "#315f85", width=2, dash=8)
        boundary_labels.append((y, boundary, label))
    label_x = right + 24
    previous_label_y: Optional[int] = None
    for line_y, boundary, label in sorted(boundary_labels):
        label_y = max(top + 12, min(bottom - 12, line_y))
        if previous_label_y is not None and label_y - previous_label_y < 30:
            label_y = min(bottom - 12, previous_label_y + 30)
        text = f"{label} {boundary:,.2f}"
        text_bounds = draw.textbbox((0, 0), text, font=label_font)
        label_width = text_bounds[2] - text_bounds[0]
        draw.line((right, line_y, label_x - 8, line_y), fill="#315f85", width=1)
        if label_y != line_y:
            draw.line((label_x - 8, line_y, label_x - 8, label_y), fill="#315f85", width=1)
        draw.rectangle(
            (label_x - 4, label_y - 12, label_x + label_width + 6, label_y + 11),
            fill="#fbfcfa",
        )
        draw.text((label_x, label_y - 10), text, font=label_font, fill="#315f85")
        previous_label_y = label_y

    markers: Sequence[Tuple[pd.Timestamp, str, str]] = (
        (box_start, "Box start", "#6b7475"),
        (activation, "Activation", "#bf841d"),
    )
    for timestamp, _, color in markers:
        _dashed_line(draw, (x_at(timestamp), top), (x_at(timestamp), bottom), color, width=2, dash=7)
    if expired:
        _dashed_line(draw, (x_at(termination), top), (x_at(termination), bottom), "#8d4a5b", width=3, dash=5)
    else:
        assert event_time is not None and target is not None
        _dashed_line(draw, (x_at(event_time), top), (x_at(event_time), bottom), "#9c5262", width=3, dash=5)
        target_y = y_at(target)
        _dashed_line(draw, (left, target_y), (right, target_y), "#d18436", width=3, dash=10)
        draw.text((left + 10, target_y - 21), f"1 ATR target {target:,.2f}", font=label_font, fill="#a96820")
        if hit_or_censor_time is not None:
            marker_color = "#8d4a5b" if _as_bool(source.get("target_hit", False)) else "#444f50"
            _dashed_line(draw, (x_at(hit_or_censor_time), top), (x_at(hit_or_censor_time), bottom), marker_color, width=2, dash=4)
        assert ahead_low is not None and ahead_high is not None
        _dashed_line(draw, (left, y_at(ahead_low)), (right, y_at(ahead_low)), "#3b9aa5", width=2, dash=6)
        _dashed_line(draw, (left, y_at(ahead_high)), (right, y_at(ahead_high)), "#3b9aa5", width=2, dash=6)

    legend_y = 1080
    legend_entries = [
        ("#6b7475", "Box start"),
        ("#bf841d", "Activation"),
        ("#315f85", "Frozen H/L"),
    ]
    if expired:
        legend_entries.extend([("#8d4a5b", "Expiration"), ("#13836d", "15m up candle"), ("#c64f4a", "15m down candle")])
    else:
        legend_entries.extend(
            [
                ("#9c5262", "Breakout close"),
                ("#d18436", "1 ATR target"),
                ("#3b9aa5", "Ahead Region bounds"),
                ("#13836d", "15m up candle"),
                ("#c64f4a", "15m down candle"),
            ]
        )
    x_legend = left
    for color, label in legend_entries:
        draw.line((x_legend, legend_y + 8, x_legend + 30, legend_y + 8), fill=color, width=4)
        draw.text((x_legend + 38, legend_y), label, font=small_font, fill=muted)
        text_width = draw.textbbox((0, 0), label, font=small_font)[2]
        x_legend += text_width + 72

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)


def _manifest_row(review_id: str, item: Dict[str, Any], chart_path: Path, output_root: Path) -> Dict[str, Any]:
    source = item["source"]
    expired = item["item_type"] == "expired_box"
    if expired:
        item_id = str(item["box_id"])
        time_value = source["box_termination_time"]
        direction = ""
        va = ""
        reason = ""
    else:
        item_id = str(source["event_id"])
        time_value = source["breakout_time"]
        direction = str(source["direction"])
        valid_va = _event_valid_va(pd.DataFrame([source])).iloc[0]
        va = float(source["VA"]) if valid_va else ""
        reason = "" if valid_va else missing_va_reason(source)
    try:
        chart_value = chart_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        chart_value = chart_path.as_posix()
    return {
        "review_id": review_id,
        "item_type": item["item_type"],
        "event_id_or_box_id": item_id,
        "categories": "; ".join(item["categories"]),
        "chart_path": chart_value,
        "direction": direction,
        "activation_time": _iso_utc(source["box_activation"]),
        "breakout_or_expiration_time": _iso_utc(time_value),
        "VA": va,
        "missing_reason": reason,
        "manual_status": "",
        "manual_notes": "",
    }


def _category_summary(manifest: pd.DataFrame) -> Dict[str, Any]:
    memberships: Dict[str, set] = {category: set() for category in CATEGORY_ORDER}
    for row in manifest.itertuples(index=False):
        for category in row.categories.split("; ") if row.categories else []:
            memberships[category].add(row.event_id_or_box_id)
    counts = {category: len(memberships[category]) for category in CATEGORY_ORDER}
    overlaps = {
        f"{first} & {second}": len(memberships[first].intersection(memberships[second]))
        for index, first in enumerate(CATEGORY_ORDER)
        for second in CATEGORY_ORDER[index + 1 :]
        if memberships[first].intersection(memberships[second])
    }
    return {"category_counts": counts, "category_overlaps": overlaps}


def finalize_review_manifest(manifest: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Record the approved human decisions without changing analytical fields."""
    required_manifest = set(MANIFEST_COLUMNS)
    missing_manifest = required_manifest.difference(manifest.columns)
    if missing_manifest:
        raise ValueError(f"Review manifest is missing columns: {sorted(missing_manifest)}")
    required_events = {"event_id", "profile_valid", "va_missing", "VA", "va_missing_reason", "right_censored"}
    missing_events = required_events.difference(events.columns)
    if missing_events:
        raise ValueError(f"Analysis event table is missing columns: {sorted(missing_events)}")
    if len(manifest) != EXPECTED_REVIEW_ITEMS or manifest["review_id"].duplicated().any():
        raise ValueError(f"Expected {EXPECTED_REVIEW_ITEMS} unique review items")
    item_counts = manifest["item_type"].value_counts().to_dict()
    if item_counts != {"breakout": EXPECTED_BREAKOUT_ITEMS, "expired_box": EXPECTED_EXPIRED_ITEMS}:
        raise ValueError("Review manifest item counts do not match the approved Block 4 sample")
    if events["event_id"].isna().any() or events["event_id"].astype(str).duplicated().any():
        raise ValueError("Analysis event IDs must be present and unique")

    indexed_events = events.assign(event_id=events["event_id"].astype(str)).set_index("event_id")
    missing_profile_count = 0
    result = manifest.copy()
    result["manual_status"] = result["manual_status"].fillna("").astype(object)
    result["manual_notes"] = result["manual_notes"].fillna("").astype(object)
    for index, row in result.iterrows():
        if row["item_type"] == "expired_box":
            note = "Frozen boundaries and expiration are visually consistent; no close-based breakout before expiration."
        elif row["item_type"] == "breakout":
            event_id = str(row["event_id_or_box_id"])
            if event_id not in indexed_events.index:
                raise ValueError(f"Review event is absent from analysis table: {event_id}")
            event = indexed_events.loc[event_id]
            profile_missing = (
                not _as_bool(event["profile_valid"])
                or _as_bool(event["va_missing"])
                or pd.isna(event["VA"])
            )
            if profile_missing:
                missing_profile_count += 1
                reason = event["va_missing_reason"]
                if pd.isna(reason) or not str(reason).strip():
                    reason = row["missing_reason"]
                reason = str(reason)
                if reason != PROFILE_MISSING_REASON:
                    raise ValueError(f"Unexpected profile-missing reason for {event_id}: {reason}")
                note = f"Detection and chart are visually consistent; VA remains missing because {reason}."
            else:
                note = "Visual boundaries, lifecycle, direction and annotations are consistent."
            if _as_bool(event["right_censored"]):
                note += " Target not reached within 240 minutes; this is a valid right-censored outcome, not a review failure."
        else:
            raise ValueError(f"Unsupported review item type: {row['item_type']}")
        result.at[index, "manual_status"] = "pass"
        result.at[index, "manual_notes"] = note

    if missing_profile_count != EXPECTED_PROFILE_MISSING_ITEMS:
        raise ValueError(
            f"Expected {EXPECTED_PROFILE_MISSING_ITEMS} profile-missing reviewed events; found {missing_profile_count}"
        )
    if not result["manual_status"].isin(ALLOWED_MANUAL_STATUSES).all():
        raise ValueError("Final manifest contains an unsupported manual status")
    return result


def finalize_review_manifest_file(
    manifest_path: Path,
    events_path: Path = ANALYSIS_EVENTS_PATH,
) -> pd.DataFrame:
    """Finalize one manifest file; all analysis/source inputs are read-only."""
    manifest_path = Path(manifest_path)
    events_path = Path(events_path)
    if manifest_path.resolve() == events_path.resolve():
        raise ValueError("Manifest output must not overwrite the analysis event table")
    manifest = pd.read_csv(manifest_path)
    events = pd.read_csv(events_path)
    finalized = finalize_review_manifest(manifest, events)
    finalized.to_csv(manifest_path, index=False)
    return finalized


def generate_manual_validation(
    events: pd.DataFrame,
    boxes: pd.DataFrame,
    candles: pd.DataFrame,
    output_dir: Path = OUTPUT_DIR,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Generate chart files, manifest, and review guide without changing inputs."""
    required_candles = {"open_time", "open", "high", "low", "close"}
    missing_candles = required_candles.difference(candles.columns)
    if missing_candles:
        raise ValueError(f"15-minute data is missing columns: {sorted(missing_candles)}")
    candle_frame = candles.copy()
    candle_frame["open_time"] = pd.to_datetime(candle_frame["open_time"], utc=True, errors="coerce")
    candle_frame = candle_frame.sort_values("open_time", kind="mergesort").reset_index(drop=True)
    if candle_frame.empty or candle_frame["open_time"].isna().any():
        raise ValueError("15-minute candles must contain valid UTC timestamps")

    items = select_review_items(events, boxes)
    output_dir = Path(output_dir)
    manifest_path = output_dir / MANIFEST_NAME
    if manifest_path.exists():
        existing_manifest = pd.read_csv(manifest_path)
        if any(
            existing_manifest[column].fillna("").astype(str).str.strip().ne("").any()
            for column in ("manual_status", "manual_notes")
            if column in existing_manifest.columns
        ):
            raise ValueError("Existing manual decisions found; refusing to overwrite the reviewed manifest")
    charts_dir = output_dir / CHARTS_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        review_id = f"review-{index:04d}"
        item["box_id"] = (
            f"expired-box-{_utc(item['source']['box_activation']):%Y%m%dT%H%M%SZ}"
            if item["item_type"] == "expired_box"
            else ""
        )
        chart_name = f"{review_id}_{item['item_type']}.png"
        chart_path = charts_dir / chart_name
        _draw_chart(item, candle_frame, chart_path, review_id)
        rows.append(_manifest_row(review_id, item, chart_path, output_dir))

    manifest = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    manifest.to_csv(manifest_path, index=False)
    (output_dir / GUIDE_NAME).write_text(GUIDE_TEXT, encoding="utf-8")
    summary = {
        "unique_breakout_charts": int(manifest["item_type"].eq("breakout").sum()),
        "expired_box_charts": int(manifest["item_type"].eq("expired_box").sum()),
        **_category_summary(manifest),
    }
    return manifest, summary


def run_manual_validation(
    events_path: Path = EVENTS_PATH,
    boxes_path: Path = BOXES_PATH,
    candles_path: Path = CANDLES_PATH,
    output_dir: Path = OUTPUT_DIR,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    event_header = pd.read_csv(events_path, nrows=0).columns
    event_dates = [column for column in ("breakout_time", "box_activation", "box_start") if column in event_header]
    box_header = pd.read_csv(boxes_path, nrows=0).columns
    box_dates = [column for column in ("box_start", "box_activation", "box_termination_time") if column in box_header]
    events = pd.read_csv(events_path, parse_dates=event_dates)
    boxes = pd.read_csv(boxes_path, parse_dates=box_dates)
    candles = pd.read_parquet(candles_path)
    return generate_manual_validation(events, boxes, candles, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--finalize", action="store_true", help="Record the approved human decisions in an existing manifest")
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--boxes", type=Path, default=BOXES_PATH)
    parser.add_argument("--candles-15m", type=Path, default=CANDLES_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    arguments = parser.parse_args()
    if arguments.finalize:
        manifest_path = arguments.output_dir / MANIFEST_NAME
        manifest = finalize_review_manifest_file(manifest_path, arguments.events)
        counts = manifest["manual_status"].value_counts().to_dict()
        print(f"Finalized items: {len(manifest)}")
        print(f"Manual status counts: {counts}")
        print(f"Manifest: {manifest_path}")
        return
    manifest, summary = run_manual_validation(
        arguments.events,
        arguments.boxes,
        arguments.candles_15m,
        arguments.output_dir,
    )
    print(f"Unique reviewed items: {len(manifest)}")
    print(f"Breakout charts: {summary['unique_breakout_charts']}")
    print(f"Expired-box charts: {summary['expired_box_charts']}")
    print("Category counts:")
    for category, count in summary["category_counts"].items():
        print(f"  {category}: {count}")
    print(f"Category overlaps: {summary['category_overlaps']}")
    print(f"Manifest: {arguments.output_dir / MANIFEST_NAME}")
    print(f"Charts: {arguments.output_dir / CHARTS_DIR_NAME}")


if __name__ == "__main__":
    main()