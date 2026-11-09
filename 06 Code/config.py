"""Централизованные параметры Pilot v0.1 из замороженной спецификации."""

# Instrument and time conventions.
EXCHANGE = "Binance"
SYMBOL = "BTCUSDT"
MARKET = "spot"
TIMEZONE = "UTC"

# Fixed sample period and warm-up period.
PILOT_START = "2025-01-01"
PILOT_END = "2025-06-30"
WARMUP_START = "2024-11-01"
MIN_QUALIFIED_EVENTS = 30

# Source and aggregated candle intervals.
SOURCE_INTERVAL_MINUTES = 1
CANDLE_INTERVAL_MINUTES = 15
BARS_PER_CANDLE = 15

# Consolidation candidate, qualification, and lifecycle.
BOX_LENGTH = 32
BOX_MAX_AGE = 32
WIDTH_QUANTILE = 0.20
WIDTH_LOOKBACK_DAYS = 60
ER_THRESHOLD = 0.30
CENTRAL_CLOSES_MIN = 23
CENTRAL_REGION_FRACTION = 0.10

# Breakout indicator and threshold.
ATR_LENGTH = 14
BREAKOUT_BUFFER_ATR = 0.10

# Historical volume profile and price-bin regions.
PROFILE_LOOKBACK_DAYS = 30
PROFILE_EXPECTED_MINUTES = 43_200
BIN_WIDTH_ATR = 0.05
AHEAD_BIN_COUNT = 20
REFERENCE_BIN_COUNT = 200
AHEAD_DISTANCE_ATR = 1.0
REFERENCE_DISTANCE_ATR = 5.0

# Post-breakout outcomes.
TARGET_ATR = 1.0
MAX_HORIZON_MINUTES = 240
RETURN_HORIZONS_MINUTES = (15, 30, 60, 120, 240)