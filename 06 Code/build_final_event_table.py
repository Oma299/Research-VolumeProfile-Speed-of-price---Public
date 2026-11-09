"""Сборка raw и analysis event tables по frozen Pilot v0.1."""

import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

import config
from calculate_outcomes import OUTPUT_PATH as OUTCOMES_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDLES_PATH = PROJECT_ROOT / "05 Data" / "processed" / (
    f"binance_btcusdt_spot_15m_{config.WARMUP_START}_{config.PILOT_END}.parquet"
)
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "tables"
RAW_OUTPUT_PATH = OUTPUT_DIR / "events_raw.parquet"
ANALYSIS_OUTPUT_PATH = OUTPUT_DIR / "events_analysis.csv"
DATA_DICTIONARY_PATH = OUTPUT_DIR / "events_data_dictionary.md"

EVENT_TIMESTAMP_COLUMNS = (
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
)
CONTROL_COLUMNS = (
    "volatility",
    "pre_trend",
    "normalized_box_width_atr",
    "hour_of_day_utc",
    "control_missing_reason",
)
ANALYSIS_FLAG_COLUMNS = (
    "profile_available_for_va_analysis",
    "outcome_available_for_primary_analysis",
    "controls_available",
    "primary_analysis_eligible",
    "analysis_exclusion_reason",
)


def _utc_events(events: pd.DataFrame) -> pd.DataFrame:
    missing = {"event_id", "breakout_time", "direction", "ATR", "H", "L"}.difference(events.columns)
    if missing:
        raise ValueError(f"В event table отсутствуют колонки: {sorted(missing)}")
    if events.columns.duplicated().any():
        raise ValueError("Event table contains duplicate column names")
    if events["event_id"].isna().any() or events["event_id"].duplicated().any():
        raise ValueError("event_id должен быть заполнен и уникален")
    frame = events.copy()
    frame["breakout_time"] = pd.to_datetime(frame["breakout_time"], utc=True, errors="coerce")
    if frame["breakout_time"].isna().any():
        raise ValueError("breakout_time содержит некорректные timestamps")
    return frame


def _pre_event_controls(events: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    required = {"open_time", "close"}
    missing = required.difference(candles.columns)
    if missing:
        raise ValueError(f"В 15m candles отсутствуют колонки: {sorted(missing)}")
    source = candles.copy()
    source["open_time"] = pd.to_datetime(source["open_time"], utc=True, errors="coerce")
    if source["open_time"].isna().any() or source["open_time"].duplicated().any():
        raise ValueError("15m candles содержат invalid или duplicate open_time")
    if not source["open_time"].is_monotonic_increasing:
        raise ValueError("15m candles должны быть отсортированы по open_time")
    closes = pd.to_numeric(source["close"], errors="coerce")
    indexed = pd.Series(closes.to_numpy(dtype=float), index=pd.DatetimeIndex(source["open_time"]))
    interval = pd.Timedelta(minutes=config.CANDLE_INTERVAL_MINUTES)
    control_rows: List[Dict[str, Any]] = []

    for event in events.itertuples(index=False):
        event_time = pd.Timestamp(event.breakout_time).tz_convert(config.TIMEZONE)
        breakout_candle_open = event_time - interval
        previous_candle_open = breakout_candle_open - interval
        pretrend_start_open = breakout_candle_open - config.BOX_LENGTH * interval
        row: Dict[str, Any] = {
            "volatility": np.nan,
            "pre_trend": np.nan,
            "normalized_box_width_atr": np.nan,
            "hour_of_day_utc": int(event_time.hour),
            "control_missing_reason": None,
        }
        if previous_candle_open not in indexed.index or pretrend_start_open not in indexed.index:
            row["control_missing_reason"] = "missing_pre_event_15m_candles"
            control_rows.append(row)
            continue

        previous_close = float(indexed.at[previous_candle_open])
        pretrend_start_close = float(indexed.at[pretrend_start_open])
        atr = float(event.ATR)
        boundary_width = float(event.H) - float(event.L)
        if (
            not np.isfinite([previous_close, pretrend_start_close, atr, boundary_width]).all()
            or previous_close == 0
            or pretrend_start_close == 0
            or atr <= 0
        ):
            row["control_missing_reason"] = "invalid_pre_event_control_denominator"
            control_rows.append(row)
            continue

        sign = 1.0 if event.direction == "upward" else -1.0 if event.direction == "downward" else np.nan
        if not np.isfinite(sign):
            row["control_missing_reason"] = "invalid_breakout_direction"
            control_rows.append(row)
            continue
        row["volatility"] = atr / previous_close
        row["pre_trend"] = sign * (previous_close - pretrend_start_close) / pretrend_start_close
        row["normalized_box_width_atr"] = boundary_width / atr
        control_rows.append(row)

    return pd.DataFrame(control_rows, index=events.index, columns=CONTROL_COLUMNS)


def _analysis_table(raw: pd.DataFrame) -> pd.DataFrame:
    result = raw.copy()
    profile_valid = result["profile_valid"].fillna(False).astype(bool)
    va_missing = result["va_missing"].fillna(True).astype(bool)
    outcome_missing = result["outcome_missing"].fillna(True).astype(bool)
    target_known = result["target_hit"].notna()
    censor_known = result["right_censored"].notna()
    profile_available = profile_valid & ~va_missing & result["VA"].notna()
    outcome_available = ~outcome_missing & target_known & censor_known
    controls_available = result.loc[:, ("volatility", "pre_trend", "normalized_box_width_atr", "hour_of_day_utc")].notna().all(axis=1)
    eligible = profile_available & outcome_available & controls_available

    reasons: List[str] = []
    for index in result.index:
        event_reasons: List[str] = []
        if not profile_available.loc[index]:
            reason = result.at[index, "profile_missing_reason"]
            event_reasons.append(f"profile_missing:{reason or 'profile_not_valid'}")
        if not outcome_available.loc[index]:
            reason = result.at[index, "outcome_missing_reason"]
            event_reasons.append(f"outcome_missing:{reason or 'outcome_not_complete'}")
        if not controls_available.loc[index]:
            reason = result.at[index, "control_missing_reason"]
            event_reasons.append(f"controls_missing:{reason or 'control_not_available'}")
        reasons.append(";".join(event_reasons))

    result["profile_available_for_va_analysis"] = profile_available.astype(bool)
    result["outcome_available_for_primary_analysis"] = outcome_available.astype(bool)
    result["controls_available"] = controls_available.astype(bool)
    result["primary_analysis_eligible"] = eligible.astype(bool)
    result["analysis_exclusion_reason"] = reasons
    return result


def build_final_event_tables(
    events: pd.DataFrame,
    candles_15m: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Собрать all-row raw Parquet schema и analysis CSV schema с flags."""
    source = _utc_events(events)
    if source["event_id"].nunique() != len(source):
        raise ValueError("Event IDs are not unique")
    controls = _pre_event_controls(source, candles_15m)
    raw = pd.concat([source, controls], axis=1)
    analysis = _analysis_table(raw)
    return raw, analysis


FIELD_DEFINITIONS: Dict[str, Tuple[str, str, str, str, str]] = {
    "event_id": ("Уникальный идентификатор события", "id", "Источник event table", "Идентификация события", "Не допускается"),
    "box_start": ("Начало 32-свечного candidate window", "UTC timestamp", "Исходная event table", "Open-time первой свечи candidate window", "Не допускается"),
    "box_start_time": ("Alias box_start из event schema", "UTC timestamp", "Исходная event table", "Open-time первой свечи candidate window", "Не допускается"),
    "box_activation": ("Активация box", "UTC timestamp", "Исходная event table", "Open-time activation candle", "Не допускается"),
    "box_activation_time": ("Alias box_activation из event schema", "UTC timestamp", "Исходная event table", "Open-time activation candle", "Не допускается"),
    "breakout_time": ("Закрытие 15m breakout candle и event_time", "UTC timestamp", "Исходная event table", "Close-time breakout candle; первая outcome 1m candle открывается здесь", "Не допускается"),
    "breakout_time_utc": ("Alias breakout_time из event schema", "UTC timestamp", "Исходная event table", "Close-time breakout candle", "Не допускается"),
    "box_termination_time": ("Время завершения box", "UTC timestamp", "Исходная event table", "Breakout close-time или expiration close-time", "Не допускается"),
    "box_status": ("Статус lifecycle box", "категория", "breakout или expired", "Lifecycle box", "Не допускается"),
    "direction": ("Направление breakout", "категория", "Исходная event table", "UP=upward; DOWN=downward", "Не допускается"),
    "breakout_direction": ("Alias direction из event schema", "категория", "Исходная event table", "Направление breakout", "Не допускается"),
    "H": ("Верхняя граница box", "цена USDT", "Исходная event table", "Frozen box boundary до breakout", "Не допускается"),
    "L": ("Нижняя граница box", "цена USDT", "Исходная event table", "Frozen box boundary до breakout", "Не допускается"),
    "ATR": ("Wilder ATR(14) для события", "цена USDT", "Исходная event table", "ATR[t−1], известный до breakout candle", "Не допускается для outcome target"),
    "box_width": ("Абсолютная ширина box", "цена USDT", "H − L", "Frozen box boundaries", "Не допускается"),
    "normalized_box_width": ("Ширина для candidate width qualification", "доля", "(H−L)/Close[t−1] при box activation; исходное поле detector", "Использует только данные до box activation", "Как в source event table"),
    "box_age": ("Возраст box на breakout", "15m свечи", "Исходная event table", "Lifecycle свечи, начиная с activation", "Не допускается"),
    "box_age_candles": ("Alias box_age", "15m свечи", "Исходная event table", "Lifecycle свечи, начиная с activation", "Не допускается"),
    "breakout_close": ("P0, close breakout candle", "цена USDT", "Close[t]", "Известно в breakout_time", "Не допускается"),
    "breakout_strength": ("Сила пробоя", "ATR units", "UP: (Close−H)/ATR; DOWN: (L−Close)/ATR", "Breakout candle close и ATR[t−1]", "Как в source event table"),
    "central_closes_count": ("Число закрытий в central region", "свечи", "Исходная event table", "Candidate window до activation", "Как в source event table"),
    "efficiency_ratio": ("Efficiency Ratio candidate", "доля", "Исходная event table", "Candidate window до activation", "Как в source event table"),
    "normalized_box_width_atr": ("ATR-normalized box width control", "ATR units", "(H−L)/ATR[t−1] по Section 15", "Box H/L и ATR события, известный до breakout", "Missing при недоступном/невалидном знаменателе"),
    "volatility": ("Волатильность control", "доля", "ATR[t−1]/Close[t−1]", "Предыдущая закрытая 15m свеча перед breakout candle", "Missing при недоступном/нулевом знаменателе"),
    "pre_trend": ("Направленно-нормализованный pre-breakout trend", "доля", "s×(Close[t−1]−Close[t−32])/Close[t−32]", "15m closes только до breakout candle", "Missing при недоступном/нулевом знаменателе"),
    "hour_of_day_utc": ("UTC hour control", "час 0–23", "hour(breakout_time UTC)", "Close-time события, доступный в event_time", "Missing при некорректном breakout_time"),
    "control_missing_reason": ("Причина отсутствия одного или нескольких controls", "текст/пусто", "Сборщик final table", "Недоступные только pre-event 15m candles/denominators", "Пусто, если controls рассчитаны"),
    "profile_start": ("Начало 30-дневного profile window", "UTC timestamp", "profile_end − 30 calendar days", "До breakout candle", "Как в source profile table"),
    "profile_end": ("Конец profile window, исключительный", "UTC timestamp", "breakout_time − 15 minutes", "Open-time breakout candle", "Как в source profile table"),
    "profile_expected_minutes": ("Ожидаемое число минут profile window", "минуты", "config.PROFILE_EXPECTED_MINUTES", "Profile interval", "Как в source profile table"),
    "profile_observed_minutes": ("Уникальные наблюдавшиеся profile минуты", "минуты", "Исходный profile result", "Profile interval", "Как в source profile table"),
    "profile_boundary": ("Bin grid boundary B", "цена USDT", "H для UP; L для DOWN", "Исходный profile result", "Missing при невалидном профиле"),
    "profile_bin_width": ("Ширина price bin", "цена USDT", "BIN_WIDTH_ATR×ATR[t−1]", "ATR известен до breakout candle", "Missing при невалидном bin width"),
    "profile_typical_price_min": ("Минимальная TypicalPrice в profile window", "цена USDT", "Min((High+Low+Close)/3)", "Profile interval", "Missing если профиль не рассчитан"),
    "profile_typical_price_max": ("Максимальная TypicalPrice в profile window", "цена USDT", "Max((High+Low+Close)/3)", "Profile interval", "Missing если профиль не рассчитан"),
    "ahead_volume": ("Raw Volume Ahead", "USDT quote volume", "Сумма quote_asset_volume в Ahead bins", "Только profile interval до breakout candle", "Missing при невалидном профиле"),
    "reference_volume": ("Объём в reference bins", "USDT quote volume", "Сумма quote_asset_volume в reference bins", "Только profile interval до breakout candle", "Missing при невалидном профиле"),
    "ahead_density": ("Средний ahead объём на bin", "USDT/bin", "ahead_volume/AHEAD_BIN_COUNT", "Profile interval до breakout", "Missing при невалидном профиле"),
    "reference_density": ("Средний reference объём на bin", "USDT/bin", "reference_volume/REFERENCE_BIN_COUNT", "Profile interval до breakout", "Missing при невалидном профиле"),
    "VA": ("Volume Ahead ratio", "безразмерная доля", "ahead_density/reference_density", "Ex-ante profile", "Missing если profile invalid; см. va_missing_reason"),
    "log1p_VA": ("Логарифм Volume Ahead ratio", "безразмерная доля", "log(1+VA)", "Ex-ante profile", "Missing если VA missing"),
    "profile_valid": ("Валиден ли профиль", "boolean", "Profile validation result", "Profile interval до breakout", "False означает причину в profile_missing_reason"),
    "profile_missing_reason": ("Почему профиль не рассчитан/невалиден", "текст/пусто", "Profile pipeline", "Profile interval", "Пусто при валидном профиле"),
    "va_missing": ("Отсутствует ли VA", "boolean", "Profile pipeline", "Ex-ante feature", "True означает см. va_missing_reason"),
    "va_missing_reason": ("Причина missing VA", "текст/пусто", "Profile pipeline", "Ex-ante feature", "Пусто при доступном VA"),
    "target_price": ("Целевая цена", "цена USDT", "P0 ± TARGET_ATR×ATR[t−1] по направлению", "P0=Close breakout candle", "Missing при невалидных event fields"),
    "target_hit": ("Достигнута ли цель в непрерывно наблюдаемой части follow-up", "nullable boolean", "UP: High≥target; DOWN: Low≤target", "Минуты от event_time; first hit только до первого gap", "Missing если first-hit status неизвестен из-за gap"),
    "time_to_target_minutes": ("Время до первого подтверждённого target hit", "минуты", "m, первая минута m=1", "Непрерывный префикс от event_time", "Missing при no-hit или неизвестном первом hit"),
    "observed_time_minutes": ("Время наблюдения/подтверждённого hit", "минуты", "При hit=m; при полном no-hit=240", "От event_time", "Missing если follow-up неполон и hit не подтверждён"),
    "right_censored": ("Полные 240 минут наблюдались без target hit", "nullable boolean", "True только при полном 240m no-hit", "Полное окно после event_time", "Missing при неполном follow-up без confirmed hit"),
    "outcome_missing": ("Неполный/невалидный follow-up для основного outcome", "boolean", "Outcome pipeline", "После event_time", "False означает полный follow-up"),
    "outcome_missing_reason": ("Причина неполного follow-up", "текст/пусто", "Outcome pipeline", "Окно до event_time+240m", "Пусто при полном follow-up"),
    "outcome_expected_minutes": ("Ожидаемая длина follow-up", "минуты", "config.MAX_HORIZON_MINUTES", "После event_time", "Не missing"),
    "outcome_observed_minutes": ("Число валидных уникальных future минут в окне", "минуты", "Outcome pipeline count", "Окно event_time…event_time+240m", "0 если future rows отсутствуют"),
    "outcome_contiguous_prefix_minutes": ("Длина последовательного префикса до первого gap", "минуты", "Outcome pipeline count", "Начиная с event_time", "0 если первая минута отсутствует"),
    "target_hit_bar_open_time_utc": ("Open-time минуты первого подтверждённого target touch", "UTC timestamp", "Minute index m", "Внутри непрерывного префикса", "Missing если target не подтверждён"),
    "r_15": ("Directional return через 15 минут", "доля, не проценты", "s×(Close_endpoint−P0)/P0", "Свеча закрывается в event_time+15m", "Missing если endpoint candle недоступна/невалидна"),
    "r_30": ("Directional return через 30 минут", "доля, не проценты", "s×(Close_endpoint−P0)/P0", "Свеча закрывается в event_time+30m", "Missing если endpoint candle недоступна/невалидна"),
    "r_60": ("Directional return через 60 минут", "доля, не проценты", "s×(Close_endpoint−P0)/P0", "Свеча закрывается в event_time+60m", "Missing если endpoint candle недоступна/невалидна"),
    "r_120": ("Directional return через 120 минут", "доля, не проценты", "s×(Close_endpoint−P0)/P0", "Свеча закрывается в event_time+120m", "Missing если endpoint candle недоступна/невалидна"),
    "r_240": ("Directional return через 240 минут", "доля, не проценты", "s×(Close_endpoint−P0)/P0", "Свеча закрывается в event_time+240m", "Missing если endpoint candle недоступна/невалидна"),
    "mfe_240": ("Максимальное благоприятное движение", "доля, не проценты", "Формула MFE Section 14 относительно P0", "Полные post-breakout минуты 1–240", "Missing если окно 240m неполно"),
    "mae_240": ("Максимальное неблагоприятное движение", "доля, не проценты", "Формула MAE Section 14 относительно P0", "Полные post-breakout минуты 1–240", "Missing если окно 240m неполно"),
    "return_to_box": ("Был ли подтверждён первый return close за границу box", "nullable boolean", "UP Close<H; DOWN Close>L", "Первое событие только в непрерывном префиксе", "Missing при неполном окне без установленного return"),
    "time_to_return_box_minutes": ("Время до первого Return-to-Box close", "минуты", "m, первая минута m=1", "Непрерывный префикс от event_time", "Missing если первое время неизвестно"),
    "return_to_box_bar_open_time_utc": ("Open-time минуты первого Return-to-Box close", "UTC timestamp", "Minute index m", "Непрерывный префикс", "Missing если return не установлен"),
    "ambiguous_intrabar": ("Совпали ли минуты первых target и Return-to-Box событий", "nullable boolean", "True iff first-event minute positions match", "Только если оба first events установлены", "Missing если gap не позволяет установить одно событие"),
    "profile_available_for_va_analysis": ("Доступен ли VA feature", "boolean flag", "profile_valid and not va_missing and VA present", "Profile output", "False для profile-missing событий"),
    "outcome_available_for_primary_analysis": ("Доступен ли complete primary outcome", "boolean flag", "not outcome_missing and target/censor status known", "Outcome output", "False для incomplete outcome"),
    "controls_available": ("Все spec controls вычислены", "boolean flag", "Проверка control columns not-null", "Controls только pre-event", "False при control_missing_reason"),
    "primary_analysis_eligible": ("Доступны VA, полный outcome и controls", "boolean flag", "AND трёх availability flags", "Флаг для primary VA/outcome анализа; строка не удаляется", "False для соответствующих missing inputs"),
    "analysis_exclusion_reason": ("Причины false primary_analysis_eligible", "текст/пусто", "Объединение missing reasons", "Не использует target_hit, returns, speed, censoring или ambiguity как фильтр", "Пусто, если eligible"),
}


def render_data_dictionary(raw: pd.DataFrame, analysis: pd.DataFrame) -> str:
    missing_definitions = set(analysis.columns).difference(FIELD_DEFINITIONS)
    if missing_definitions:
        raise ValueError(f"Нет data dictionary definitions: {sorted(missing_definitions)}")
    lines = [
        "# Final Event Tables Data Dictionary",
        "",
        "`events_raw.parquet` и `events_analysis.csv` сохраняют по одной строке на каждый исходный `event_id`; физических фильтров строк нет. Analysis CSV добавляет eligibility flags, которые не удаляют строки.",
        "",
        "## Inclusion flags",
        "",
        "- `profile_available_for_va_analysis`: исходный VA валиден; 24 profile-invalid события не имеют наблюдаемого VA.",
        "- `outcome_available_for_primary_analysis`: outcome follow-up полный; right-censored события допустимы, поскольку 240 минут наблюдались полностью.",
        "- `controls_available`: все controls из specification вычислимы по данным до breakout.",
        "- `primary_analysis_eligible`: все три availability flags True. Это flag, не фильтр экспорта; target hit, returns, speed, censoring и ambiguity не участвуют в отборе.",
        "- `analysis_exclusion_reason`: диагностическое описание недоступных измерений; строки остаются в CSV/Parquet.",
        "",
        "## Missing-value distinctions",
        "",
        "`time_to_target_minutes` — время до hit или missing при no-hit/неизвестном первом hit; `observed_time_minutes` — duration для survival outcome. `right_censored=True` означает только полный 240m no-hit; `outcome_missing=True` означает incomplete/invalid follow-up. Profile missing (`profile_valid=False`, `va_missing=True`) относится только к VA feature и не делает outcome missing. `r_*`, `mfe_240` и `mae_240` хранят доли, не проценты.",
        "",
        "`normalized_box_width` сохранён без изменения как Section 8 candidate width `(H−L)/Close[t−1]`. Section 15 отдельно определяет ATR-normalized control; он записан как `normalized_box_width_atr=(H−L)/ATR[t−1]`.",
        "",
        "## Columns",
        "",
        "| Column | dtype | Meaning | Units | Formula / source | Time anchor | Missing meaning |",
        "|---|---|---|---|---|---|---|",
    ]
    for column in analysis.columns:
        meaning, units, formula, timing, missing = FIELD_DEFINITIONS[column]
        values = [column, str(analysis[column].dtype), meaning, units, formula, timing, missing]
        escaped = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(escaped) + " |")
    lines.extend(
        [
            "",
            f"Raw rows: {len(raw)}. Analysis rows: {len(analysis)}. `event_id` is unique in both.",
            "",
        ]
    )
    return "\n".join(lines)


def build_final_event_tables(
    events: pd.DataFrame,
    candles_15m: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    """Build all-row raw and analysis tables plus an exhaustive dictionary."""
    source = _utc_events(events)
    controls = _pre_event_controls(source, candles_15m)
    raw = pd.concat([source, controls], axis=1)
    analysis = _analysis_table(raw)
    dictionary = render_data_dictionary(raw, analysis)
    return raw, analysis, dictionary


def _assert_source_preserved(source: pd.DataFrame, result: pd.DataFrame) -> None:
    if len(source) != len(result) or source["event_id"].tolist() != result["event_id"].tolist():
        raise ValueError("Export lost, reordered, or duplicated source events")
    for column in source.columns:
        if column in EVENT_TIMESTAMP_COLUMNS:
            left = pd.to_datetime(source[column], utc=True, errors="coerce")
            right = pd.to_datetime(result[column], utc=True, errors="coerce")
            equal = left.eq(right) | (left.isna() & right.isna())
            if not equal.all():
                raise ValueError(f"Source timestamp field changed during build: {column}")
        elif pd.api.types.is_numeric_dtype(source[column].dtype):
            left = pd.to_numeric(source[column], errors="coerce").to_numpy(dtype=float)
            right = pd.to_numeric(result[column], errors="coerce").to_numpy(dtype=float)
            if not np.isclose(left, right, rtol=1e-13, atol=1e-13, equal_nan=True).all():
                raise ValueError(f"Source numeric field changed during build: {column}")
        else:
            left = source[column].fillna("<NA>").astype(str)
            right = result[column].fillna("<NA>").astype(str)
            if not left.equals(right):
                raise ValueError(f"Source field changed during build: {column}")


def export_final_event_tables(
    events_path: Path = OUTCOMES_PATH,
    candles_path: Path = CANDLES_PATH,
    raw_path: Path = RAW_OUTPUT_PATH,
    analysis_path: Path = ANALYSIS_OUTPUT_PATH,
    dictionary_path: Path = DATA_DICTIONARY_PATH,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Read inputs, validate/build all rows, and write the three final artifacts."""
    header = pd.read_csv(events_path, nrows=0).columns
    parse_dates = [column for column in EVENT_TIMESTAMP_COLUMNS if column in header]
    events = pd.read_csv(events_path, parse_dates=parse_dates)
    candles = pd.read_parquet(candles_path)
    raw, analysis, dictionary = build_final_event_tables(events, candles)
    _assert_source_preserved(events, raw)
    _assert_source_preserved(events, analysis)
    if raw["event_id"].duplicated().any() or analysis["event_id"].duplicated().any():
        raise ValueError("Final event_id must be unique")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    dictionary_path.parent.mkdir(parents=True, exist_ok=True)
    raw.to_parquet(raw_path, index=False)
    analysis.to_csv(analysis_path, index=False)
    dictionary_path.write_text(dictionary, encoding="utf-8")

    raw_check = pd.read_parquet(raw_path)
    csv_dates = [column for column in EVENT_TIMESTAMP_COLUMNS if column in analysis.columns]
    analysis_check = pd.read_csv(analysis_path, parse_dates=csv_dates)
    _assert_source_preserved(events, raw_check)
    _assert_source_preserved(events, analysis_check)
    if len(raw_check) != len(events) or len(analysis_check) != len(events):
        raise ValueError("Final table round-trip changed the row count")
    for column in EVENT_TIMESTAMP_COLUMNS:
        if column in raw_check and str(raw_check[column].dt.tz) != config.TIMEZONE:
            raise ValueError(f"Parquet timestamp is not timezone-aware UTC: {column}")
        if column in analysis_check and str(analysis_check[column].dt.tz) != config.TIMEZONE:
            raise ValueError(f"CSV timestamp is not timezone-aware UTC: {column}")
    return raw_check, analysis_check


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=OUTCOMES_PATH)
    parser.add_argument("--candles-15m", type=Path, default=CANDLES_PATH)
    parser.add_argument("--raw-output", type=Path, default=RAW_OUTPUT_PATH)
    parser.add_argument("--analysis-output", type=Path, default=ANALYSIS_OUTPUT_PATH)
    parser.add_argument("--dictionary-output", type=Path, default=DATA_DICTIONARY_PATH)
    args = parser.parse_args()
    raw, analysis = export_final_event_tables(
        args.events,
        args.candles_15m,
        args.raw_output,
        args.analysis_output,
        args.dictionary_output,
    )
    print(f"Raw events: {len(raw)}")
    print(f"Analysis rows (all retained): {len(analysis)}")
    print(f"Primary analysis eligible flag: {int(analysis['primary_analysis_eligible'].sum())}")
    print("Exclusion reasons:")
    print(analysis.loc[~analysis["primary_analysis_eligible"], "analysis_exclusion_reason"].value_counts(dropna=False).to_string())
    print(f"Raw Parquet: {args.raw_output}")
    print(f"Analysis CSV: {args.analysis_output}")
    print(f"Data dictionary: {args.dictionary_output}")


if __name__ == "__main__":
    main()