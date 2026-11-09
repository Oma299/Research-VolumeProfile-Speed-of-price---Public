"""Агрегация минутных Binance-свечей и причинно корректный Wilder ATR."""

import numpy as np
import pandas as pd
from typing import Optional

import config


REQUIRED_COLUMNS = ("open_time", "open", "high", "low", "close")


def aggregate_15m(minute_bars: pd.DataFrame) -> pd.DataFrame:
    """Собрать только полные свечи из 15 последовательных минутных OHLCV-баров."""
    missing_columns = set(REQUIRED_COLUMNS).difference(minute_bars.columns)
    if missing_columns:
        raise ValueError(f"В минутных данных отсутствуют колонки: {sorted(missing_columns)}")

    frame = minute_bars.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True, errors="coerce")
    if frame["open_time"].isna().any():
        raise ValueError("Минутные данные содержат некорректный open_time")
    if frame["open_time"].duplicated().any():
        raise ValueError("Минутные данные содержат повторяющиеся open_time")
    if not frame["open_time"].eq(frame["open_time"].dt.floor("min")).all():
        raise ValueError("open_time должен лежать на UTC минутной сетке")
    frame = frame.sort_values("open_time", kind="stable").reset_index(drop=True)
    frame["_interval_start"] = frame["open_time"].dt.floor(
        f"{config.CANDLE_INTERVAL_MINUTES}min"
    )

    aggregations: dict[str, tuple[str, str]] = {
        "open": ("open", "first"),
        "high": ("high", "max"),
        "low": ("low", "min"),
        "close": ("close", "last"),
    }
    additive_columns = [
        column
        for column in frame.columns
        if column.endswith("_volume") or column == "number_of_trades"
    ]
    for column in additive_columns:
        aggregations[column] = (column, "sum")
    if "close_time" in frame.columns:
        aggregations["close_time"] = ("close_time", "last")

    grouped = frame.groupby("_interval_start", sort=True)
    bars = grouped.agg(**aggregations)
    counts = grouped.size()
    complete = counts.eq(config.BARS_PER_CANDLE)
    for interval_start in counts.index[complete]:
        observed = pd.DatetimeIndex(
            frame.loc[frame["_interval_start"].eq(interval_start), "open_time"]
        )
        expected = pd.date_range(
            interval_start,
            periods=config.BARS_PER_CANDLE,
            freq=f"{config.SOURCE_INTERVAL_MINUTES}min",
        )
        if not observed.equals(expected):
            complete.loc[interval_start] = False

    bars = bars.loc[complete].rename_axis("open_time").reset_index()
    bars["open_time"] = pd.to_datetime(bars["open_time"], utc=True)
    return bars.sort_values("open_time", kind="stable").reset_index(drop=True)


def true_range(candles: pd.DataFrame) -> pd.Series:
    """Вернуть стандартный True Range; для первой свечи используется high-low."""
    required = {"high", "low", "close"}
    missing_columns = required.difference(candles.columns)
    if missing_columns:
        raise ValueError(f"В свечах отсутствуют колонки: {sorted(missing_columns)}")
    previous_close = candles["close"].shift(1)
    ranges = pd.concat(
        [
            candles["high"] - candles["low"],
            (candles["high"] - previous_close).abs(),
            (candles["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    result = ranges.max(axis=1, skipna=True)
    return result.where(candles[["high", "low", "close"]].notna().all(axis=1))


def wilder_atr(candles: pd.DataFrame, period: Optional[int] = None) -> pd.Series:
    """Рассчитать Wilder ATR с арифметическим seed из первых period TR."""
    atr_period = config.ATR_LENGTH if period is None else period
    if atr_period < 1:
        raise ValueError("Период ATR должен быть положительным")

    ranges = true_range(candles).to_numpy(dtype=float)
    values = np.full(len(ranges), np.nan, dtype=float)
    seed: list[float] = []
    previous_atr: float | None = None
    for position, current_range in enumerate(ranges):
        if not np.isfinite(current_range):
            seed.clear()
            previous_atr = None
            continue
        if previous_atr is None:
            seed.append(float(current_range))
            if len(seed) == atr_period:
                previous_atr = float(np.mean(seed))
                values[position] = previous_atr
            continue
        previous_atr = ((atr_period - 1) * previous_atr + current_range) / atr_period
        values[position] = previous_atr
    return pd.Series(values, index=candles.index, name=f"atr_{atr_period}")


def prepare_candles(minute_bars: pd.DataFrame) -> pd.DataFrame:
    """Подготовить полные UTC 15-минутные свечи из минутных баров."""
    return aggregate_15m(minute_bars)