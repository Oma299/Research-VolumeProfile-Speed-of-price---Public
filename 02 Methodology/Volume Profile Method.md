# Volume Profile Method (Pilot v0.1 Approximation)

## Ex-Ante Construction & Approximation Statement

В Pilot v0.1 Volume Profile строится по **1-minute bars**, а не по отдельным сделкам (aggregate trades).

- **Честное указание:** “Approximate historical volume-by-price profile constructed from one-minute bars.”
- **Ограничения:**
  - распределение объёма внутри минутной свечи неизвестно;
  - присвоение всего quote volume минутной свечи к ценовому bin, содержащему $\text{TypicalPrice} = (\text{High} + \text{Low} + \text{Close}) / 3$, является приближением;
  - в полной версии после пилота метод может быть заменён на построение профиля по Binance aggregate trades (необязательно для Pilot v0.1).

## Historical Window & Bins

- **Окно профиля:** предыдущие 30 календарных дней, заканчивающиеся непосредственно перед началом пробойной свечи $t$ (свеча $t$ и все будущие данные полностью исключены). Профиль охватывает более широкий диапазон цен, чем сам Consolidation Box.
- **Размер ценового бина:** $\text{BinWidth} = 0.05 \times \text{ATR}[t-1]$ (фиксируется для события $t$).
- **Единица объёма:** USDT quote volume.

## Unvisited / Uncovered Levels

- Если bin находится внутри диапазона от минимального до максимального $\text{TypicalPrice}$ 30-дневного профиля, но в него не попала ни одна минутная свеча, его volume равен нулю.
- Если AheadRegion или ReferenceRegion выходит за диапазон наблюдавшихся $\text{TypicalPrice}$, $VA$ помечается как `missing`. Отсутствие исторических наблюдений не объявляется автоматически Low Volume Zone. События с missing VA сохраняются в event table, но исключаются из основного анализа VA (их доля обязательно сообщается).

See [[02 Methodology/Research Protocol|Research Protocol]].
