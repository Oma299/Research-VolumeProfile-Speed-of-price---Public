# Код исследования

Код Pilot v0.1 хранится в этой папке. Замороженная спецификация `Pilot v0.1 Specification.md` в корне проекта остаётся единственным источником методологии и параметров.

## Модули

- `config.py` — единое место для параметров замороженной спецификации.
- `download_data.py` — загрузка помесячных Binance Spot BTCUSDT 1m архивов из Binance Vision, проверка SHA-256, качества данных и запись Parquet.
- `prepare_candles.py` — агрегация полных UTC 15m свечей и Wilder ATR(14).
- `detect_boxes.py` — поиск Consolidation Box, lifecycle и первого breakout по Pilot v0.1.
- `run_block4.py` — воспроизводимый запуск агрегации, detector, диагностики и визуальной проверки.
- `calculate_profile.py` — расчёт approximate Volume Profile и Volume Ahead для одного события и всей event table.
- `calculate_outcomes.py` — расчёт event-level post-breakout outcomes и batch CLI.
- `build_final_event_table.py` — сборка all-row raw/analysis таблиц, spec controls, availability flags и data dictionary.
- `manual_validation.py` — детерминированный outcome-blind набор графиков и manifest для ручной проверки Day 2 Block 4.
- `validation.py` — проверки данных, временных границ и предотвращения утечки.
- `plots.py` — построение описательных графиков.
- `run_pilot.py` — будущая оркестрация этапов пайплайна.
- `tests/` — проверки конфигурации, минутных данных, агрегации, ATR, detector, Volume Profile, outcomes и final event table.
- `src/`, `configs/`, `notebooks/` — существующие каталоги для будущих рабочих материалов и запусков.

## Загрузка данных

Требуется Python 3.9 или новее. Из `06 Code/` установите зависимости и запустите точные команды:

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 download_data.py
```

Загрузчик получает официальные ZIP-архивы Binance Vision за ноябрь 2024 — июнь 2025 в `05 Data/raw/`, проверяет SHA-256 и не скачивает повторно архивы, совпадающие с опубликованной контрольной суммой. Итоговый Parquet появляется в `05 Data/processed/`, отчёт JSON — в `reports/data_quality/`.

Проверяются ожидаемое число минутных свечей, UTC-диапазон и сетка, дубликаты, пропуски, OHLC, положительность цен и отрицательный объём. Нулевой объём отдельно считается, но сам по себе не считается ошибкой. Данные не дополняются и не фильтруются. При ошибке отчёт сохраняется, Parquet не создаётся, процесс завершается с ненулевым кодом.

## Последующие этапы

Этапы подготовки 15m свечей, Wilder ATR и поиска боксов выполнены. Запускать из `06 Code/`:

```sh
python3 -m unittest discover -s tests -v
python3 run_block4.py
```

15m Parquet записывается в `05 Data/processed/` и исключён из Git. Pilot event/box CSV находятся в `outputs/tables/`, диагностика и PNG-графики — в `reports/block4/`. Volume Profile, Volume Ahead и последующие outcomes этим runner-ом не рассчитываются.

Следующие этапы: ручная проверка событий и графиков, затем отдельный статистический анализ.

## Manual Validation (Day 2, Block 4)

После сборки final event tables запустите из `06 Code/`:

```sh
python3 manual_validation.py
```

Скрипт читает `outputs/tables/events_analysis.csv`, таблицу box lifecycle и сохранённый 15m Parquet. Он создаёт отдельный пакет в `reports/block4/manual_validation/`: по одному PNG на каждый выбранный breakout/expired box, `review_manifest.csv` и `MANUAL_REVIEW_GUIDE.md`. Исходные CSV и Parquet не изменяются.

Выбор основан на времени, валидном VA, profile-missing статусе и обязательной категории `ambiguous_intrabar`; target, speed, returns, MFE/MAE и censoring не используются как критерии отбора. Outcome-поля показаны только как справочные аннотации для проверки данных. В v0.1 используется только замороженный 240-минутный горизонт; период остаётся 2025-01-01 — 2025-06-30.

Оставьте `manual_status` и `manual_notes` пустыми до человеческой проверки. Допустимые статусы: `pass`, `questionable`, `fail`. Проверяйте только detection/data correctness; будущий результат цены не должен влиять на принятие события. Ручная проверка не разрешает незаметно менять методологию.

После завершения человеческой и независимой визуальной проверки зафиксируйте утверждённые решения:

```sh
python3 manual_validation.py --finalize
```

Запускайте `--finalize` только после фактического завершения review: он присваивает уже утверждённые статусы, меняет только `manual_status`/`manual_notes` в manifest и не редактирует аналитические таблицы или Parquet. Финальный отчёт сохраняется как `reports/block4/manual_validation/MANUAL_VALIDATION_REPORT.md`.

## Следующий этап

Day 2 Block 4 manual validation завершён. Следующая задача — Day 3 Block 1: leakage и validation; она ещё не начата.

## Volume Profile и Volume Ahead

После `run_block4.py` запустите из `06 Code/`:

```sh
python3 calculate_profile.py
```

Профиль строится по 1m `quote_asset_volume` за 30 календарных дней перед началом breakout-свечи. Bin grid anchored к box boundary (`H` для upward, `L` для downward), не к `breakout_close`; breakout candle и более поздние минуты исключены. Результат дополняет все event rows новыми колонками и сохраняется отдельно в `outputs/tables/consolidation_breakout_events_with_profile_2025-01-01_2025-06-30.csv`. Невалидные профили остаются в таблице с `profile_valid=False` и явной причиной.

## Post-breakout Outcomes

После `calculate_profile.py` запустите из `06 Code/`:

```sh
python3 calculate_outcomes.py
```

CLI добавляет outcomes ко всем событиям независимо от `profile_valid` и записывает новую таблицу `outputs/tables/consolidation_breakout_events_with_profile_and_outcomes_2025-01-01_2025-06-30.csv`. Первая post-breakout 1m свеча открывается в `breakout_time`; breakout candle исключена.

При полном 240-минутном follow-up target hit в минуте `m` даёт `time_to_target_minutes=m`, `observed_time_minutes=m`, `right_censored=False`. Полные 240 минут без target дают `target_hit=False`, `observed_time_minutes=240`, `right_censored=True`. Для неполного follow-up `outcome_missing=True` с причиной; обычный 240-minute censoring не назначается. Hit и его время подтверждаются только на непрерывном префиксе от `event_time`, Return to Box — также. Доступные exact-endpoint returns сохраняются и при промежуточном gap. MFE/MAE вычисляются только при полном 240-минутном окне; неизвестные значения остаются missing.

`ambiguous_intrabar=True` только когда минуты первых target touch и Return-to-Box close совпадают. Если достоверно установлено, что первые события произошли в разных минутах, значение `False`; если gap не позволяет установить первое событие, значение остаётся missing. Повторное выполнение Return-to-Box условия в минуте target не считается ambiguity, если первый возврат был раньше.

## Final Event Tables

После `calculate_outcomes.py` запустите из `06 Code/`:

```sh
python3 build_final_event_table.py
```

В `outputs/tables/` создаются `events_raw.parquet`, `events_analysis.csv` и `events_data_dictionary.md`. В каждой таблице остаются все исходные event IDs; строка не удаляется. `events_analysis.csv` добавляет availability flags: `profile_available_for_va_analysis`, `outcome_available_for_primary_analysis`, `controls_available`, `primary_analysis_eligible`, `analysis_exclusion_reason`. Основная eligibility требует доступный VA, complete outcome и controls; right-censored события допустимы. Флаги не используют target hit, return, speed или ambiguity как критерии отбора.

Исходное `normalized_box_width` сохраняет candidate-definition `(H−L)/Close[t−1]`. Отдельный Section 15 control `(H−L)/ATR[t−1]` хранится как `normalized_box_width_atr`; исходное поле не переименовывается и не перезаписывается. Controls `volatility` и `pre_trend` используют только закрытые 15m свечи `t−1` и `t−32`; `hour_of_day_utc` берётся из UTC `breakout_time`.

## Источник параметров

`Pilot v0.1 Specification.md` — источник истины для методологии и всех параметров. Параметры в `config.py` должны соответствовать этой спецификации. Менять их можно только в новой версии спецификации; изменения замороженного Pilot v0.1 не допускаются. Методологические изменения также следует фиксировать в журнале решений проекта.

Запуски анализа в будущем следует записывать в `10 Progress/Experiment Log.md`. Исследовательские черновики не являются источником истины.
