# Definitions

> Канонические определения зафиксированы в [[Pilot v0.1 Specification]].

- **Consolidation Box:** диапазон $[L, H]$ шириной $W = H - L$, построенный по 32 завершённым 15-минутным свечам ($t-32, \dots, t-1$; 8 часов), удовлетворяющий условиям относительно узкой процентной ширины ($w \le 20$-й процентиль за предыдущие 60 календарных дней завершённых окон), низкой направленности ($ER < 0.30$) и расположения $\ge 23$ из 32 закрытий в центральной области $[L + 0.1W, H - 0.1W]$. Свеча $t$ не входит в расчёт.
- **Breakout:** событие выхода цены за границы Consolidation Box на свече $t$: $\text{Close}[t] > H + 0.1 \times \text{ATR}[t-1]$ (upward) или $\text{Close}[t] < L - 0.1 \times \text{ATR}[t-1]$ (downward), где 15-минутный $\text{ATR}(14)$ рассчитан по методу Wilder по данным строго до $t-1$. Известно по закрытию свечи $t$. Ложные пробои сохраняются.
- **Resistance / Support ($H / L$):** границы Consolidation Box, замороженные после квалификации и действующие максимум 32 свечи.
- **Volume Profile (Pilot v0.1 approximation):** приближённый профиль объёма по ценам, построенный по 1-минутным барам за предыдущие 30 календарных дней (до свечи $t$, исключая её), где весь quote volume минутной свечи отнесён к ценовому bin, содержащему $\text{TypicalPrice} = (\text{High} + \text{Low} + \text{Close}) / 3$. Размер бина $\text{BinWidth} = 0.05 \times \text{ATR}[t-1]$.
- **Ex ante:** рассчитано строго по информации до момента события (не позже $t-1$).
- **Volume Ahead ($VA$):** отношение плотности исторического объёма в области впереди цены ($\text{AheadRegion}$: $[H, H + \text{ATR}]$ для вверх, $[L - \text{ATR}, L]$ для вниз) к плотности в локальной референсной области ($\text{ReferenceRegion}$: $[\text{Boundary} - 5\text{ATR}, \text{Boundary} + 5\text{ATR}]$). Primary exposure: $\log(1 + VA)$.
- **ATR:** 15-minute $\text{ATR}(14)$ по методу Wilder на основе данных до $t-1$.
- **Primary Outcome (Speed):** время в минутах после $\text{Close}[t]$ до первого достижения целевого расстояния $1 \times \text{ATR}[t-1]$ в направлении пробоя (максимум 240 минут, с учётом цензурирования).
- **Key Secondary Outcome:** Directional Return через 60 минут ($R_{60}$), где для пробоев вниз знак инвертирован, чтобы положительное значение означало движение в сторону пробоя.
- **Pre-Breakout Trend (`PreTrend`):** обычная signed return BTC за предыдущие 8 часов (32 свечи): $(\text{Close}[t-1] - \text{Close}[t-33]) / \text{Close}[t-33]$.
- **Control Variables:** volatility ($\text{ATR}[t-1] / \text{Close}[t-1]$), normalized box width ($(H - L) / \text{ATR}[t-1]$), breakout strength, pre-breakout trend (`PreTrend`), breakout direction (`breakout_direction`), hour of day UTC (`hour_of_day_utc`).
- **Look-ahead bias:** ошибка использования будущей информации (устранена строгим ex-ante дизайном).
- **Censoring:** достижение лимита наблюдения в 240 минут без касания цели (right censoring).
