import os
from datetime import date
from alpaca.trading.client import TradingClient
from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.live import OptionDataStream

# ── Alpaca Credentials ──────────────────────────────────────────────
API_KEY = os.environ.get("APCA_API_KEY_ID")
API_SECRET = os.environ.get("APCA_API_SECRET_KEY")
BASE_URL = "https://paper-api.alpaca.markets"

# ── Clients ─────────────────────────────────────────────────────────
trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
option_data_client = OptionHistoricalDataClient(API_KEY, API_SECRET)

# ── Constants ───────────────────────────────────────────────────────
UNDERLYING = "SPY"
TODAY = date.today().isoformat()

# 0DTE = expiry is today
EXPIRY = TODAY

# Greeks computation mode
GREEKS_MODE = "both"  # options: "bs", "broker", "both"

# Gamma arc trade parameters
ENTRY_MONEYNESS_THRESHOLD = 0.997   # slightly OTM (within 0.3% of spot)
GAMMA_PEAK_DECAY_TRIGGER = 0.85     # exit when gamma drops to 85% of peak
SNIPE_EXIT_MONEYNESS_CALL = 1.005   # exit call when spot is 0.5% ITM
SNIPE_EXIT_MONEYNESS_PUT = 0.995    # exit put when spot is 0.5% ITM
MIN_GAMMA = 0.01                    # ignore deep OTM noise

# Dashboard refresh interval (seconds)
REFRESH_INTERVAL = 30
