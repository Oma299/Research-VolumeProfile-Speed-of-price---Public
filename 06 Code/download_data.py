"""Загрузка и проверка минутных свечей Binance Spot из Binance Vision."""

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

import pandas as pd

import config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "05 Data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "05 Data" / "processed"
REPORT_DIR = PROJECT_ROOT / "reports" / "data_quality"
DATASET_PATH = PROCESSED_DIR / "binance_btcusdt_spot_1m_2024-11-01_2025-06-30.parquet"
REPORT_PATH = REPORT_DIR / "binance_btcusdt_spot_1m_quality_report.json"
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
ARCHIVE_COLUMNS = (
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "base_volume",
    "close_time_ms",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
)
PRICE_COLUMNS = ("open", "high", "low", "close")
VOLUME_COLUMNS = ("base_volume", "quote_asset_volume")


class DataQualityError(Exception):
    """Ошибка загрузки или качества данных с сохранённым отчётом."""


def _utc_timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _period() -> tuple[pd.Timestamp, pd.Timestamp]:
    start = _utc_timestamp(config.WARMUP_START)
    end = _utc_timestamp(config.PILOT_END) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return start, end


def _months_in_period(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Period]:
    return list(pd.period_range(start=start.strftime("%Y-%m"), end=end.strftime("%Y-%m"), freq="M"))


def _archive_url(symbol: str, interval: str, month: pd.Period) -> str:
    filename = f"{symbol}-{interval}-{month.strftime('%Y-%m')}.zip"
    return f"{BASE_URL}/{symbol}/{interval}/{filename}"


def _get_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ResearchVolumeProfile/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checksum_for(url: str) -> str:
    checksum_text = _get_bytes(f"{url}.CHECKSUM").decode("ascii").strip()
    match = re.match(r"^([0-9a-fA-F]{64})\s+", checksum_text)
    if not match:
        raise ValueError(f"Не удалось распознать SHA-256 в {url}.CHECKSUM")
    return match.group(1).lower()


def _read_archive_bytes(archive_bytes: bytes, source_name: str) -> pd.DataFrame:
    with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"CRC-проверка ZIP не пройдена для {bad_member}")
        csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(csv_members) != 1:
            raise ValueError(f"Ожидался один CSV в {source_name}, найдено: {len(csv_members)}")
        with archive.open(csv_members[0]) as source:
            frame = pd.read_csv(source, header=None, names=ARCHIVE_COLUMNS)

    frame["open_time"] = _to_utc_timestamps(frame["open_time_ms"])
    frame["close_time"] = _to_utc_timestamps(frame["close_time_ms"])
    for column in PRICE_COLUMNS + VOLUME_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("number_of_trades", "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["source_file"] = source_name
    return frame.drop(columns=["open_time_ms", "close_time_ms"])


def _to_utc_timestamps(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    microseconds = numeric.abs() >= 10**14
    timestamps = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns, UTC]")
    timestamps.loc[~microseconds] = pd.to_datetime(
        numeric.loc[~microseconds], unit="ms", utc=True, errors="coerce"
    )
    timestamps.loc[microseconds] = pd.to_datetime(
        numeric.loc[microseconds], unit="us", utc=True, errors="coerce"
    )
    return timestamps


def _load_month(
    month: pd.Period,
    symbol: str,
    interval: str,
) -> tuple[pd.DataFrame, str]:
    url = _archive_url(symbol, interval, month)
    filename = url.rsplit("/", 1)[-1]
    archive_path = RAW_DIR / filename
    expected_checksum = _checksum_for(url)

    if archive_path.exists():
        archive_bytes = archive_path.read_bytes()
        if _sha256(archive_bytes) != expected_checksum:
            raise ValueError(
                f"Существующий архив {archive_path} не совпадает с официальной SHA-256; "
                "файл оставлен без изменений. Проверьте его вручную."
            )
        reused = "reused"
    else:
        archive_bytes = _get_bytes(url)
        if _sha256(archive_bytes) != expected_checksum:
            raise ValueError(f"SHA-256 загруженного архива {filename} не совпадает с Binance Vision")
        _read_archive_bytes(archive_bytes, filename)
        temporary_path = archive_path.with_suffix(archive_path.suffix + ".part")
        temporary_path.write_bytes(archive_bytes)
        temporary_path.replace(archive_path)
        reused = "downloaded"

    frame = _read_archive_bytes(archive_bytes, filename)
    return frame, reused


def validate_data(
    frame: pd.DataFrame,
    start: Optional[object] = None,
    end: Optional[object] = None,
) -> tuple[dict[str, object], pd.DatetimeIndex]:
    """Проверить временной ряд и вернуть метрики вместе с минутами, которых не хватает."""
    period_start, period_end = _period() if start is None or end is None else (_utc_timestamp(start), _utc_timestamp(end))
    expected = pd.date_range(period_start, period_end, freq="min", tz="UTC")
    timestamps = pd.to_datetime(frame["open_time"], utc=True, errors="coerce")
    valid_timestamps = timestamps.dropna()
    duplicate_mask = timestamps.notna() & timestamps.duplicated(keep="first")
    out_of_period = timestamps.notna() & ((timestamps < period_start) | (timestamps > period_end))
    observed = pd.DatetimeIndex(valid_timestamps.unique())
    missing = expected.difference(observed).sort_values()
    expected_set = set(expected)
    unexpected_grid = timestamps.notna() & timestamps.between(period_start, period_end) & ~timestamps.isin(expected_set)

    numeric_columns = PRICE_COLUMNS + VOLUME_COLUMNS
    numeric = frame.loc[:, numeric_columns].apply(pd.to_numeric, errors="coerce")
    invalid_numeric = numeric.isna().any(axis=1)
    high_violation = numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)
    low_violation = numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)
    inverted_range = numeric["high"] < numeric["low"]
    ohlc_union = high_violation | low_violation | inverted_range
    nonpositive_price = (numeric.loc[:, PRICE_COLUMNS] <= 0).any(axis=1)
    negative_base_volume = numeric["base_volume"] < 0
    negative_quote_volume = numeric["quote_asset_volume"] < 0
    negative_volume = negative_base_volume | negative_quote_volume

    first = valid_timestamps.min() if not valid_timestamps.empty else pd.NaT
    last = valid_timestamps.max() if not valid_timestamps.empty else pd.NaT
    metrics: dict[str, object] = {
        "expected_rows": len(expected),
        "actual_rows": len(frame),
        "first_open_time_utc": None if pd.isna(first) else first.isoformat(),
        "last_open_time_utc": None if pd.isna(last) else last.isoformat(),
        "duplicate_open_time_rows": int(duplicate_mask.sum()),
        "duplicate_open_time_values": int(valid_timestamps[valid_timestamps.duplicated(keep=False)].nunique()),
        "missing_minute_intervals": len(missing),
        "missing_minute_timestamps_utc": [timestamp.isoformat() for timestamp in missing],
        "timestamps_outside_period_rows": int(out_of_period.sum()),
        "timestamps_off_minute_grid_rows": int(unexpected_grid.sum()),
        "unparseable_open_time_rows": int(timestamps.isna().sum()),
        "invalid_numeric_rows": int(invalid_numeric.sum()),
        "high_below_max_open_close_low_rows": int(high_violation.sum()),
        "low_above_min_open_close_high_rows": int(low_violation.sum()),
        "high_below_low_rows": int(inverted_range.sum()),
        "ohlc_violation_rows": int(ohlc_union.sum()),
        "nonpositive_price_rows": int(nonpositive_price.sum()),
        "negative_base_volume_rows": int(negative_base_volume.sum()),
        "negative_quote_volume_rows": int(negative_quote_volume.sum()),
        "negative_volume_rows": int(negative_volume.sum()),
        "zero_base_volume_rows": int((numeric["base_volume"] == 0).sum()),
        "zero_quote_volume_rows": int((numeric["quote_asset_volume"] == 0).sum()),
    }
    error_metrics = (
        "duplicate_open_time_rows",
        "missing_minute_intervals",
        "timestamps_outside_period_rows",
        "timestamps_off_minute_grid_rows",
        "unparseable_open_time_rows",
        "invalid_numeric_rows",
        "high_below_max_open_close_low_rows",
        "low_above_min_open_close_high_rows",
        "high_below_low_rows",
        "nonpositive_price_rows",
        "negative_volume_rows",
    )
    metrics["checks_passed"] = all(metrics[name] == 0 for name in error_metrics) and len(frame) == len(expected)
    return metrics, missing


def _save_report(report: dict[str, object]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _print_summary(report: dict[str, object]) -> None:
    metrics = report.get("quality", {})
    print(f"Статус: {report['status']}")
    if isinstance(metrics, dict) and metrics:
        print(f"Строк: {metrics['actual_rows']} / {metrics['expected_rows']}")
        print(f"Диапазон UTC: {metrics['first_open_time_utc']} — {metrics['last_open_time_utc']}")
        print(f"Дубликаты open_time: {metrics['duplicate_open_time_rows']}")
        print(f"Пропущенные минуты: {metrics['missing_minute_intervals']}")
        print(f"Нулевой quote volume: {metrics['zero_quote_volume_rows']}")
        print(f"Нарушения OHLC: {metrics['ohlc_violation_rows']}")
    print(f"Отчёт: {REPORT_PATH}")
    if report.get("dataset_path"):
        print(f"Parquet: {report['dataset_path']}")


def download_ohlcv() -> Path:
    """Загрузить месячные архивы, проверить весь период и записать Parquet."""
    start, end = _period()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    archive_status: dict[str, str] = {}
    errors = []

    for month in _months_in_period(start, end):
        try:
            frame, state = _load_month(month, config.SYMBOL, "1m")
            frames.append(frame)
            archive_status[month.strftime("%Y-%m")] = state
        except (OSError, ValueError, zipfile.BadZipFile, urllib.error.URLError) as error:
            errors.append({"month": month.strftime("%Y-%m"), "error": str(error)})
            break

    if errors:
        report = {
            "status": "failed",
            "source": "Binance Vision Spot monthly klines",
            "symbol": config.SYMBOL,
            "interval": "1m",
            "timezone": "UTC",
            "period_start_utc": start.isoformat(),
            "period_end_utc": end.isoformat(),
            "archive_status": archive_status,
            "errors": errors,
            "dataset_path": None,
        }
        _save_report(report)
        _print_summary(report)
        raise DataQualityError("Загрузка архивов прервана; подробности сохранены в отчёте.")

    data = pd.concat(frames, ignore_index=True)
    data["open_time"] = pd.to_datetime(data["open_time"], utc=True, errors="coerce")
    data["close_time"] = pd.to_datetime(data["close_time"], utc=True, errors="coerce")
    data = data.sort_values("open_time", kind="stable", na_position="last").reset_index(drop=True)
    metrics, _ = validate_data(data, start, end)
    report = {
        "status": "passed" if metrics["checks_passed"] else "failed",
        "source": "Binance Vision Spot monthly klines",
        "source_url": f"{BASE_URL}/{config.SYMBOL}/1m/",
        "symbol": config.SYMBOL,
        "interval": "1m",
        "timezone": "UTC",
        "period_start_utc": start.isoformat(),
        "period_end_utc": end.isoformat(),
        "warmup_period": "2024-11-01 through 2024-12-31 UTC",
        "pilot_period": "2025-01-01 through 2025-06-30 UTC",
        "archive_status": archive_status,
        "quality": metrics,
        "dataset_path": str(DATASET_PATH) if metrics["checks_passed"] else None,
    }
    _save_report(report)
    _print_summary(report)

    if not metrics["checks_passed"]:
        raise DataQualityError("Проверка качества не пройдена; строки сохранены в отчёте, подозрительные данные не исправлялись.")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = DATASET_PATH.with_suffix(DATASET_PATH.suffix + ".tmp")
    data.to_parquet(temporary_path, index=False)
    temporary_path.replace(DATASET_PATH)
    return DATASET_PATH


if __name__ == "__main__":
    try:
        download_ohlcv()
    except DataQualityError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        sys.exit(2)