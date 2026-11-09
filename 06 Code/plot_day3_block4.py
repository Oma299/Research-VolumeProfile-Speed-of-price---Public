"""Create the first three descriptive figures for Day 3 Block 4."""

from pathlib import Path
import os
import sys
import tempfile
from typing import Dict, Tuple

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "research-volume-profile-matplotlib"),
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config
import calculate_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = PROJECT_ROOT / "outputs" / "tables" / "events_analysis.csv"
MINUTE_DATA_PATH = PROJECT_ROOT / "05 Data" / "processed" / (
    f"binance_btcusdt_spot_1m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
)
CANDLE_DATA_PATH = PROJECT_ROOT / "05 Data" / "processed" / (
    f"binance_btcusdt_spot_15m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
)
OUTPUT_DIR = PROJECT_ROOT / "07 Results" / "figures"


def _select_example(events: pd.DataFrame) -> pd.Series:
    valid = events.loc[
        events["breakout_direction"].eq("upward")
        & events["profile_valid"].astype(bool)
        & ~events["va_missing"].astype(bool)
        & events["VA"].notna()
    ].sort_values("breakout_time_utc", kind="stable")
    if valid.empty:
        raise ValueError("No valid upward event is available for the example figures")
    return valid.iloc[0]


def _plot_box_breakout(event: pd.Series, candles: pd.DataFrame, output_path: Path) -> None:
    candle_times = pd.to_datetime(candles["open_time"], utc=True)
    box_start = pd.Timestamp(event["box_start_time"]).tz_convert(config.TIMEZONE)
    activation = pd.Timestamp(event["box_activation_time"]).tz_convert(config.TIMEZONE)
    breakout_time = pd.Timestamp(event["breakout_time_utc"]).tz_convert(config.TIMEZONE)
    breakout_open = breakout_time - pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    view = candles.loc[(candle_times >= box_start) & (candle_times < breakout_time)].copy()
    view["open_time"] = candle_times.loc[view.index]
    view = view.sort_values("open_time", kind="stable")
    if view.empty or view["open_time"].iloc[-1] != breakout_open:
        raise ValueError("15-minute candles do not include the event's breakout candle")

    figure, axes = plt.subplots(figsize=(13, 6.5))
    candle_width_days = 0.008
    for candle in view.itertuples(index=False):
        rising = candle.close >= candle.open
        color = "#18866b" if rising else "#c54f4f"
        axes.vlines(candle.open_time, candle.low, candle.high, color=color, linewidth=1.0)
        axes.bar(
            candle.open_time,
            abs(candle.close - candle.open),
            width=candle_width_days,
            bottom=min(candle.open, candle.close),
            color=color,
            edgecolor=color,
            linewidth=0.5,
        )

    upper = float(event["H"])
    lower = float(event["L"])
    axes.axvspan(box_start, activation, color="#83a9bf", alpha=0.13, label="Formation window")
    axes.hlines([upper, lower], activation, breakout_time, colors="#334f60", linestyles="--", linewidth=1.4)
    axes.axvline(box_start, color="#77838c", linestyle=":", linewidth=1.0, label="Box start")
    axes.axvline(activation, color="#2878a0", linestyle="-.", linewidth=1.3, label="Box activation")
    axes.axvline(breakout_time, color="#d56b32", linestyle="-", linewidth=1.5, label="Breakout close")
    axes.text(activation, upper, "  H", va="bottom", color="#334f60")
    axes.text(activation, lower, "  L", va="top", color="#334f60")

    axes.set_title(f"Consolidation box and breakout | {event['event_id']} | UP")
    axes.set_ylabel("BTCUSDT price (USDT)")
    axes.set_xlabel("UTC")
    axes.xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M", tz=mdates.UTC))
    axes.grid(axis="y", alpha=0.22)
    axes.legend(loc="best", ncol=2, frameon=False)
    figure.autofmt_xdate()
    figure.tight_layout()
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _profile_bins(
    event: pd.Series,
    minute_bars: pd.DataFrame,
) -> Tuple[Dict[str, object], np.ndarray, np.ndarray]:
    profile_result = calculate_profile.calculate_event_profile(event, minute_bars)
    if not profile_result["profile_valid"]:
        raise ValueError(f"Example profile is invalid: {profile_result['profile_missing_reason']}")
    if profile_result["profile_observed_minutes"] != config.PROFILE_EXPECTED_MINUTES:
        raise ValueError("Example profile does not contain the full 30-day minute window")
    if not np.isclose(float(profile_result["VA"]), float(event["VA"]), rtol=0.0, atol=1e-12):
        raise ValueError("Recomputed profile VA does not match the persisted event value")

    timestamps = pd.to_datetime(minute_bars["open_time"], utc=True)
    start = pd.Timestamp(profile_result["profile_start"])
    end = pd.Timestamp(profile_result["profile_end"])
    profile = minute_bars.loc[timestamps.ge(start) & timestamps.lt(end)].copy()
    profile["open_time"] = timestamps.loc[profile.index]
    profile = profile.sort_values("open_time", kind="stable")
    if len(profile) != config.PROFILE_EXPECTED_MINUTES:
        raise ValueError("Selected source minutes do not match the validated profile window")

    typical_prices = calculate_profile.typical_price(profile)
    bin_indices = calculate_profile.price_bin_indices(
        typical_prices,
        float(profile_result["profile_boundary"]),
        float(profile_result["profile_bin_width"]),
    )
    reference_indices = np.arange(-config.REFERENCE_BIN_COUNT // 2, config.REFERENCE_BIN_COUNT // 2)
    in_reference = (bin_indices >= reference_indices[0]) & (bin_indices < reference_indices[-1] + 1)
    bin_volumes = (
        profile.loc[in_reference]
        .assign(bin_index=bin_indices[in_reference])
        .groupby("bin_index")["quote_asset_volume"]
        .sum()
        .reindex(reference_indices, fill_value=0.0)
        .to_numpy(dtype=float)
    )
    return profile_result, reference_indices, bin_volumes


def _plot_volume_profile(event: pd.Series, minute_bars: pd.DataFrame, output_path: Path) -> Dict[str, object]:
    profile_result, bin_indices, bin_volumes = _profile_bins(event, minute_bars)
    boundary = float(profile_result["profile_boundary"])
    bin_width = float(profile_result["profile_bin_width"])
    atr = float(event["ATR"])
    bin_centers = boundary + (bin_indices + 0.5) * bin_width
    is_ahead = (
        (bin_indices >= 0) & (bin_indices < config.AHEAD_BIN_COUNT)
        if event["breakout_direction"] == "upward"
        else (bin_indices >= -config.AHEAD_BIN_COUNT) & (bin_indices < 0)
    )
    bar_colors = np.where(is_ahead, "#dc7a3d", "#527487")

    figure, axes = plt.subplots(figsize=(10.5, 8), constrained_layout=True)
    axes.barh(bin_centers, bin_volumes, height=bin_width * 0.88, color=bar_colors, linewidth=0)
    axes.axhline(boundary, color="#172b3a", linestyle="--", linewidth=1.4, label="Box boundary B")
    if event["breakout_direction"] == "upward":
        ahead_low, ahead_high = boundary, boundary + config.AHEAD_DISTANCE_ATR * atr
    else:
        ahead_low, ahead_high = boundary - config.AHEAD_DISTANCE_ATR * atr, boundary
    axes.axhspan(ahead_low, ahead_high, color="#f0b06e", alpha=0.18, label="Ahead Region (20 bins)")
    axes.set_ylim(
        boundary - config.REFERENCE_DISTANCE_ATR * atr,
        boundary + config.REFERENCE_DISTANCE_ATR * atr,
    )
    profile_window = (
        f"{pd.Timestamp(profile_result['profile_start']).strftime('%Y-%m-%d %H:%M')} to "
        f"{pd.Timestamp(profile_result['profile_end']).strftime('%Y-%m-%d %H:%M')} UTC"
    )
    axes.set_title(
        f"30-day Volume Profile | {event['event_id']} | UP\n"
        f"{len(bin_indices)} bins | VA={float(profile_result['VA']):.4f} | {profile_window}",
        fontsize=11,
    )
    axes.set_xlabel("Quote volume per price bin (USDT)")
    axes.set_ylabel("Typical price (USDT)")
    axes.grid(axis="x", alpha=0.22)
    axes.legend(loc="upper right", frameon=False)
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return profile_result


def _plot_va_distribution(events: pd.DataFrame, output_path: Path) -> Tuple[int, int]:
    values = pd.to_numeric(events["log1p_VA"], errors="coerce")
    va = pd.to_numeric(events["VA"], errors="coerce")
    available = events.loc[events["profile_valid"].astype(bool) & va.notna() & values.notna()].copy()
    missing = events.loc[events["va_missing"].astype(bool) | va.isna()].copy()
    if available.empty or len(available) + len(missing) != len(events):
        raise ValueError("VA availability flags do not partition the event table")

    figure, (histogram, availability) = plt.subplots(
        1,
        2,
        figsize=(13, 5.5),
        gridspec_kw={"width_ratios": [2.4, 1.4]},
        constrained_layout=True,
    )
    histogram.hist(available["log1p_VA"], bins=20, color="#287d78", edgecolor="white", linewidth=0.6)
    histogram.set_title(f"Available VA only (n={len(available)})")
    histogram.set_xlabel("log(1 + VA)")
    histogram.set_ylabel("Event count")
    histogram.grid(axis="y", alpha=0.22)

    directions = ("upward", "downward")
    direction_labels = ("UP", "DOWN")
    positions = np.arange(len(directions), dtype=float)
    available_counts = np.array([int((available["breakout_direction"] == direction).sum()) for direction in directions])
    missing_counts = np.array([int((missing["breakout_direction"] == direction).sum()) for direction in directions])
    availability.barh(positions + 0.18, available_counts, height=0.32, color="#287d78", label="VA available")
    availability.barh(positions - 0.18, missing_counts, height=0.32, color="#d26a45", label="VA missing")
    for position, count in zip(positions + 0.18, available_counts):
        availability.text(count + 2, position, str(count), va="center", fontsize=9)
    for position, count in zip(positions - 0.18, missing_counts):
        availability.text(count + 2, position, str(count), va="center", fontsize=9)
    availability.set_yticks(positions, direction_labels)
    availability.set_xlim(0, max(available_counts) * 1.18)
    availability.set_title(f"Availability shown separately\nMissing: {len(missing)}/{len(events)}")
    availability.set_xlabel("Event count")
    availability.grid(axis="x", alpha=0.22)
    availability.legend(loc="lower right", frameon=False)

    figure.suptitle("Distribution of log(1 + VA)", fontsize=14)
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return len(available), len(missing)


def create_figures() -> Dict[str, object]:
    for path in (EVENTS_PATH, MINUTE_DATA_PATH, CANDLE_DATA_PATH):
        if not path.is_file():
            raise FileNotFoundError(f"Required source data is missing: {path}")

    events = pd.read_csv(EVENTS_PATH, low_memory=False)
    candles = pd.read_parquet(CANDLE_DATA_PATH)
    minute_bars = pd.read_parquet(MINUTE_DATA_PATH)
    event = _select_example(events)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    box_path = OUTPUT_DIR / f"day3_block4_01_box_breakout_{event['event_id']}.png"
    profile_path = OUTPUT_DIR / f"day3_block4_02_volume_profile_{event['event_id']}.png"
    distribution_path = OUTPUT_DIR / "day3_block4_03_log1p_va_distribution.png"

    _plot_box_breakout(event, candles, box_path)
    profile_result = _plot_volume_profile(event, minute_bars, profile_path)
    available_count, missing_count = _plot_va_distribution(events, distribution_path)
    return {
        "event_id": str(event["event_id"]),
        "box_path": box_path,
        "profile_path": profile_path,
        "distribution_path": distribution_path,
        "profile_minutes": int(profile_result["profile_observed_minutes"]),
        "profile_va": float(profile_result["VA"]),
        "available_va_events": available_count,
        "missing_va_events": missing_count,
    }


def main() -> int:
    result = create_figures()
    print(f"Example event: {result['event_id']}")
    print(f"Profile window minutes: {result['profile_minutes']}; VA: {result['profile_va']:.12g}")
    print(f"Available VA events: {result['available_va_events']}; missing VA events: {result['missing_va_events']}")
    for key in ("box_path", "profile_path", "distribution_path"):
        print(result[key].relative_to(PROJECT_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
