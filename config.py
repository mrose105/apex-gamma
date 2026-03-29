import os
from alpaca.trading.client import TradingClient
from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.live import OptionDataStream


def today_et() -> str:
    """Return today's date in ET timezone as ISO string. Safe across midnight."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


# ── Alpaca Credentials ──────────────────────────────────────────────
API_KEY    = os.environ.get("APCA_API_KEY_ID")
API_SECRET = os.environ.get("APCA_API_SECRET_KEY")
BASE_URL   = "https://paper-api.alpaca.markets"
PAPER      = True  # flip to False for live

# ── Clients ─────────────────────────────────────────────────────────
trading_client     = TradingClient(API_KEY, API_SECRET, paper=PAPER)
option_data_client = OptionHistoricalDataClient(API_KEY, API_SECRET)

# ── Underlying ───────────────────────────────────────────────────────
UNDERLYING = "SPY"
EXPIRY     = today_et()   # re-evaluated fresh every call

# ── Greeks / Model ───────────────────────────────────────────────────
RISK_FREE_RATE = 0.0365   # SOFR 3.65% as of 2026-03-26 — update monthly
GREEKS_MODE    = "both"   # "bs" | "broker" | "both"

# ── Gamma Arc Signal Parameters ──────────────────────────────────────
ENTRY_MONEYNESS_THRESHOLD  = 0.997  # enter when spot within 0.3% below strike (calls)
GAMMA_PEAK_DECAY_TRIGGER   = 0.85   # exit when gamma falls to 85% of chain peak
SNIPE_EXIT_MONEYNESS_CALL  = 1.005  # exit call once 0.5% ITM
SNIPE_EXIT_MONEYNESS_PUT   = 0.995  # exit put once 0.5% ITM
MIN_GAMMA                  = 0.01   # ignore deep OTM noise

# ── Execution Parameters ──────────────────────────────────────────────
MAX_CONTRACTS_PER_TRADE    = 1      # contracts per order leg
MAX_OPEN_POSITIONS         = 3      # simultaneous open positions
LIMIT_AGGRESSION           = 0.01   # pay up to $0.01 above mid for limit orders

# ── Risk Filters (pre-entry) ─────────────────────────────────────────
MAX_SPREAD_PCT             = 0.20   # skip if bid-ask spread > 20% of mid
MIN_OPEN_INTEREST          = 50     # skip illiquid contracts
MAX_THETA_GAMMA_RATIO      = 3.0    # skip if |theta|/gamma > 3 (gamma too expensive)
VIX_ENTRY_MIN              = 10.0   # don't buy gamma when VIX is too low
VIX_ENTRY_MAX              = 45.0   # don't buy gamma in panic (spreads too wide)

# ── Portfolio-Level Risk Limits ───────────────────────────────────────
MAX_PORTFOLIO_DELTA        = 35.0   # max net $ delta per SPY point (100 shares = 1 contract)
MAX_PORTFOLIO_THETA        = -400.0 # max $ theta bleed per day across all positions
MAX_LOSS_PER_POSITION_PCT  = 0.60   # stop-loss: exit if position loses 60% of entry value

# ── Dashboard / Collector ────────────────────────────────────────────
REFRESH_INTERVAL           = 30     # seconds between scans
