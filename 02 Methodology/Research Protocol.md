# Research Protocol (Pilot v0.1)

> Каноническая спецификация: [[Pilot v0.1 Specification]].

## Objective

Проверить, связана ли плотность исторического торгового объёма в ценовой области впереди пробоя из 8-часовой консолидации BTCUSDT с последующей скоростью движения цены в направлении пробоя. Исследование носит характер предварительного протокола Pilot v0.1 (proof of concept); причинное влияние или гарантированное ускорение не заявляются.

## Study Scope & Data Specification

- **Exchange:** Binance.
- **Instrument:** BTCUSDT.
- **Market:** Spot.
- **Time zone:** UTC.
- **Source data resolution:** 1-minute OHLCV.
- **Box and breakout timeframe:** 15 minutes.
- **Pilot period:** 2025-01-01 — 2025-06-30 (warm-up from at least 2024-12-01). If < 30 events, expand to 2025-12-31.
- **Volume unit:** Quote volume in USDT.
- **Direction:** Upward and downward breakouts combined after directional normalization (`breakout_direction` used as control).

## Event Sequence & Consolidation Box

1. Кандидатный Consolidation Box строится по 32 завершённым 15-минутным свечам ($t-32 \dots t-1$, 8 часов). Свеча $t$ не участвует в расчёте box.
2. Проверяются 3 условия консолидации:
   - **A. Относительно узкий диапазон:** процентная ширина $w = (H - L) / \text{Close}[t-1] \le 20$-му процентилю ширины завершённых 32-свечных окон за предыдущие 60 календарных дней (только окна, завершившиеся до конца текущего окна).
   - **B. Низкая направленность (ER):** $ER = |\text{Close}[t-1] - \text{Close}[t-32]| / \sum |\text{Close}[i] - \text{Close}[i-1]| < 0.30$.
   - **C. Расположение закрытий:** $\ge 23$ из 32 закрытий находятся в центральной области $[L + 0.1W, H - 0.1W]$.
3. **Жизненный цикл box:** границы $H$ и $L$ замораживаются, box активен максимум 32 свечи, учитывается только первый валидный пробой (вверх или вниз), после чего box закрывается. Перекрывающиеся активные box запрещены.
4. Рассчитывается 15-минутный $\text{ATR}(14)$ по методу Wilder по данным строго до $t-1$.
5. Пробой фиксируется на закрытии свечи $t$:
   - Upward: $\text{Close}[t] > H + 0.1 \times \text{ATR}[t-1]$
   - Downward: $\text{Close}[t] < L - 0.1 \times \text{ATR}[t-1]$
6. Строится ex-ante приближённый Volume Profile по 1-minute барам за предыдущие 30 календарных дней (исключая свечу $t$).
7. Вычисляется Volume Ahead Metric ($\log(1 + VA)$).
8. Измерение исходов начинается строго после $\text{Close}[t]$.
9. Оценивается первичный исход (время до $1 \times \text{ATR}$, макс 240 мин, цензурирование) и вторичные исходы ($R_{60}$, MFE/MAE и т.д.).

See [[02 Methodology/Consolidation Box Detection|Consolidation Box Detection]], [[02 Methodology/Breakout Definition|Breakout Definition]], [[02 Methodology/Volume Profile Method|Volume Profile Method]], [[02 Methodology/Volume Ahead Metric|Volume Ahead Metric]], [[02 Methodology/Speed and Outcomes|Speed and Outcomes]], [[02 Methodology/Statistical Plan|Statistical Plan]], and [[02 Methodology/Bias and Leakage Checklist|Bias and Leakage Checklist]].
