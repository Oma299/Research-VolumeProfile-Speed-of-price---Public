# Volume Ahead Metric (Pilot v0.1)

## AheadRegion & ReferenceRegion

Для события в момент $t$ с известным пробоем и $\text{ATR}[t-1]$:

- **AheadRegion:**
  - Upward: $[H, H + 1 \times \text{ATR}[t-1]]$
  - Downward: $[L - 1 \times \text{ATR}[t-1], L]$
  *(Область начинается от исходной границы box $H$ или $L$, чтобы избежать зависимости от размера пробойной свечи).*
- **Local ReferenceRegion:**
  - Boundary = $H$ (upward) или $L$ (downward).
  - $\text{ReferenceRegion} = [\text{Boundary} - 5 \times \text{ATR}[t-1], \text{Boundary} + 5 \times \text{ATR}[t-1]]$ (с тем же $\text{BinWidth} = 0.05 \times \text{ATR}[t-1]$).

## Volume Ahead Formula

$$\text{AheadDensity} = \frac{\sum \text{USDT quote volume in AheadRegion}}{\text{number of bins in AheadRegion}}$$

$$\text{ReferenceDensity} = \frac{\sum \text{USDT quote volume in ReferenceRegion}}{\text{number of bins in ReferenceRegion}}$$

$$VA = \frac{\text{AheadDensity}}{\text{ReferenceDensity}}$$

- **Primary exposure:** $\log(1 + VA)$ (без самостоятельного добавления эпсилона).
- Если $\text{ReferenceDensity} = 0$ или недоступна, $VA$ помечается как `missing`.

## Descriptive Groups (Quintiles)

Для описательных таблиц и графиков используются 5 описательных групп (квинтилей):
1. Very Low
2. Low
3. Medium
4. High
5. Very High

В Pilot v0.1 эти группы являются описательными квинтилями всей выборки и не объявляются готовыми границами out-of-sample модели. В полном исследовании границы оцениваются строго на train-периоде.

See [[02 Methodology/Research Protocol|Research Protocol]].
