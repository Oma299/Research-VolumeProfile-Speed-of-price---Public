# Data Dictionary

Словарь описывает поля Pilot v0.1; канонические определения заданы замороженной спецификацией.

| Field | Meaning | Type/unit | Known before breakout? |
|---|---|---|---|
| `timestamp` | Начало/конец бара по принятому стандарту | datetime with timezone | Yes |
| `open`, `high`, `low`, `close` | OHLC цены | price | Yes, after bar closes |
| `volume` | Объём бара | source-specific | Yes, after bar closes |
| `resistance` | Ex-ante уровень сопротивления | price | Yes |
| `atr` | Ex-ante ATR | price units | Yes |
| `ahead_volume` | Raw Volume Ahead: сумма `quote_asset_volume` в Ahead bins | USDT quote volume | Yes, профильный интервал до breakout candle |
| `VA` | Volume Ahead ratio: `ahead_density / reference_density` | Безразмерное отношение плотностей | Yes, рассчитывается по ex-ante профилю |
| `outcome` | success/failure/censored/ambiguous | category | No |
| `bars_to_outcome` | Время до первого исхода | hourly bars | No |
