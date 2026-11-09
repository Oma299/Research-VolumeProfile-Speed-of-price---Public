# Speed and Outcomes (Pilot v0.1)

## Primary Outcome (Speed)

- **Определение:** время в минутах после закрытия пробойной свечи $t$ до первого достижения расстояния $1 \times \text{ATR}[t-1]$ в направлении пробоя:
  - Upward Target = $\text{Close}[t] + \text{ATR}[t-1]$ (достигнуто, если High минутной свечи $\ge \text{Target}$).
  - Downward Target = $\text{Close}[t] - \text{ATR}[t-1]$ (достигнуто, если Low минутной свечи $\le \text{Target}$).
- **Максимальный горизонт:** 240 минут после $\text{Close}[t]$.
- **Цензурирование (Censoring):** если цель не достигнута за 240 минут, событие не удаляется и не получает вымышленное время; оно считается right-censored на 240 минутах.

## Key Secondary Outcome

- **Directional Return через 60 минут ($R_{60}$):**
  - Upward: $R_{60} = (\text{Close}[t+60m] - \text{Close}[t]) / \text{Close}[t]$
  - Downward: $R_{60} = (\text{Close}[t] - \text{Close}[t+60m]) / \text{Close}[t]$
  (Положительное значение всегда означает движение в направлении пробоя).

## Exploratory Outcomes

Оставляются как secondary/exploratory:
- Directional returns через 15, 30, 120 и 240 минут;
- MFE за 240 минут;
- MAE за 240 минут;
- Return to Box;
- Доля достижения 1 ATR за 240 минут.

## Return to Box & Intrabar Ambiguity

- **Return to Box:**
  - Upward breakout: 1-minute Close $< H$.
  - Downward breakout: 1-minute Close $> L$.
- **Intrabar Ambiguity:** Если в пределах одной минутной свечи одновременно достигнуты target и выполнено условие Return to Box, порядок по OHLC определить невозможно. Наблюдение получает статус `ambiguous_intrabar = True` (порядок не присваивается произвольно).

See [[02 Methodology/Research Protocol|Research Protocol]].
