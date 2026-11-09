# День 3, Блок 4: комплект графиков

## Статус

Созданы все четыре обязательных графика подробного плана. Четвёртый график показывает Kaplan–Meier time-to-target по пяти VA-квинтилям. Это описательная визуализация, не тест значимости и не вывод о связи VA с исходом. Первые три графика и их контекст описаны в прежнем [отчёте частичного выполнения](../block4_partial/BLOCK4_PARTIAL_REPORT.md); этот отчёт фиксирует завершение комплекта.

## Источники и группы

Источник событий: `outputs/tables/events_analysis.csv` — 324 уникальных event IDs. Для VA summaries использованы 300 событий с конечным валидным VA; 24 missing VA (22 UP, 2 DOWN, все `reference_region_outside_historical_range`) сохранены как missing и не включались в группы. VA-квинтили рассчитаны по линейным порогам 20/40/60/80% с правозамкнутыми интервалами; ties не разделялись. Получено пять непустых групп по 60 событий.

Все 300 VA-доступных событий имели полный 240-минутный follow-up: 231 target hit и 69 right-censored no-hit. Incomplete follow-up — 0. Hit rate включает полный no-hit как недостижение цели за горизонт; Kaplan–Meier использует `observed_time_minutes` и `target_hit`, сохраняя censoring. Медиана указывается только если кривая достигает 0.5; в этом запуске медианы оценились во всех группах.

## Графики

1. `07 Results/figures/day3_block4_01_box_breakout_event-000004.png` — 15m Consolidation Box и UP breakout.
2. `07 Results/figures/day3_block4_02_volume_profile_event-000004.png` — 30-дневный профиль и Ahead Region по исходным 1m данным.
3. `07 Results/figures/day3_block4_03_log1p_va_distribution.png` — распределение для 300 доступных VA, 24 missing показаны отдельно.
4. `07 Results/figures/day3_block4_04_km_time_to_target_by_va_quintile.png` — Kaplan–Meier time-to-target по квинтилям VA.

Числовые описательные summaries сохранены в `07 Results/tables/day3_block3_va_quintile_summaries.csv`; метод и результаты сводки — в `reports/day3/block3_wide_descriptive/DAY3_BLOCK3_DESCRIPTIVE_SUMMARIES.md`.

## Что не выполнялось

Spearman, R60 regression, bootstrap CI, Cox, тесты значимости, weighting/imputation и дополнительные outcomes (MFE, MAE, другие returns, Return to Box) не рассчитывались. Широкая часть Block 3 остаётся незавершённой до выполнения этих отдельных задач и подтверждения соответствующих правил. Frozen Pilot v0.1 и подробный план не менялись.

## Проверки

- 324 строки и уникальность event IDs; 300 валидных VA и 24 missing.
- Пять непустых групп по 60; направления в группах сохранены.
- Hit-rate denominators по 60 на группу; 231 hits, 69 censored; incomplete — 0.
- KM использует время наблюдения и индикатор target hit; график визуально проверен.
- Исходные данные и frozen spec не изменялись.
