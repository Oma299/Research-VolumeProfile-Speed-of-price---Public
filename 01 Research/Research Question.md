The Problem:
> Основной источник истины и каноническая спецификация: [[Pilot v0.1 Specification]].

Volume Profile показывает распределение исторического торгового объёма по ценовым уровням. Трейдеры предполагают, что зоны низкого объёма цена проходит быстрее, а зоны высокого объёма могут создавать сопротивление движению. Однако это предположение редко проверяется как формальная статистическая гипотеза. В данном исследовании (Pilot v0.1) проверяется, связана ли плотность исторического торгового объёма в ценовой области впереди пробоя из 8-часовой консолидации BTCUSDT (Binance Spot) с последующей скоростью движения цены в направлении пробоя.

# Research Question


## Primary Research Question

**Is the historical trade volume density ahead of price in an 8-hour consolidation breakout of BTCUSDT associated with subsequent price speed in the direction of the breakout?**

Простыми словами: связана ли плотность исторического торгового объёма впереди цены со скоростью её последующего движения после выхода из 8-часовой ценовой консолидации? Исследование изучает статистическую связь, не заявляет причинность, не утверждает гарантированное ускорение, не позиционируется как готовая торговая стратегия и допускает положительный, отрицательный и нулевой результат.

## Scope

- **Instrument & Market:** Binance BTCUSDT Spot (UTC, 1-minute OHLCV source, 15-minute timeframe for box and breakout detection).
- **Direction:** Both upward and downward breakouts (combined after directional normalization; `breakout_direction` stored as control).
- **Period:** 2025-01-01 — 2025-06-30 (with warm-up from 2024-11-01; expandable to 2025-12-31 if < 30 events).
- **Predictor:** Ex-ante Volume Ahead Metric ($\log(1 + VA)$), profile constructed from 1-minute bars over the previous 30 calendar days (excluding candle $t$).
- **Primary Outcome:** Time in minutes after $\text{Close}[t]$ until first reaching target distance $1 \times \text{ATR}[t-1]$ (max 240 minutes, right-censored).
- **Key Secondary Outcome:** Directional return at 60 minutes ($R_{60}$).
