# ⚡ APEX Gamma

**Precision 0DTE SPY options scanner and execution engine built on real-time Greeks.**

---

## Overview

APEX Gamma is a quantitative options trading system designed around the gamma arc lifecycle of 0DTE (same-day expiry) SPY contracts. The core thesis: near-expiry options experience a predictable gamma explosion as they approach ATM, creating a narrow, high-conviction entry window before rapid decay sets in. This system identifies that window in real time.

Built on Alpaca's options data API with a full Black-Scholes engine running in parallel — because broker-provided Greeks aren't always available, and when they are, diffing them against BS is signal in itself.

---

## Architecture

```
config.py          — Alpaca client setup, strategy constants, gamma arc parameters
greeks_engine.py   — Black-Scholes Greeks, implied vol solver, gamma arc signal logic
scanner.py         — Live SPY 0DTE chain scan, IV back-solve, contract ranking
dashboard.py       — Streamlit dashboard: gamma surface, IV smile, signal alerts
```

---

## How It Works

### 1. Greeks Engine (`greeks_engine.py`)
- Full Black-Scholes implementation: Δ, Γ, Θ, V, ρ
- **Implied vol solver** using Brent's method — back-solves IV from market price when broker doesn't provide it (common on paper accounts and off-hours)
- **Gamma arc signal logic** — call/put aware, uses moneyness thresholds to classify each contract as `ENTRY`, `PEAK`, `EXIT`, `HOLD`, or `AVOID`
- BS vs broker Greeks diff — positive diff on gamma = BS sees more convexity than the market is pricing

### 2. Scanner (`scanner.py`)
- Pulls the full SPY 0DTE chain via Alpaca `OptionChainRequest`
- Two-pass design: first pass finds the gamma peak per option type, second pass scores every contract against it
- Computes pricing edge (market mid vs BS fair value) for each contract
- Outputs a ranked DataFrame sorted by signal priority → gamma magnitude

### 3. Dashboard (`dashboard.py`)
- Streamlit UI with dark theme
- **Gamma surface chart** — BS gamma across all near-ATM strikes with live spot line
- **IV smile chart** — implied vol curve for calls and puts
- **Pricing edge panel** — market vs BS fair value by strike
- **Signal alert panel** — ENTRY / PEAK / EXIT contracts surfaced at a glance
- Sidebar controls for option type, signal filter, strike range, and auto-refresh

---

## Gamma Arc Signal Logic

| Signal  | Condition |
|---------|-----------|
| `ENTRY` | Slightly OTM (within 0.3% of spot), gamma building |
| `PEAK`  | At or just past ATM, gamma near maximum |
| `EXIT`  | Past snipe threshold (0.5% ITM), gamma decaying >15% from peak |
| `AVOID` | Gamma collapsed below minimum threshold |
| `HOLD`  | None of the above |

**Key parameters (tunable in `config.py`):**
```python
ENTRY_MONEYNESS_THRESHOLD  = 0.997   # how close to ATM before entry
GAMMA_PEAK_DECAY_TRIGGER   = 0.85    # exit when gamma drops to 85% of peak
SNIPE_EXIT_MONEYNESS_CALL  = 1.005   # exit call at 0.5% ITM
SNIPE_EXIT_MONEYNESS_PUT   = 0.995   # exit put at 0.5% ITM
```

---

## Setup

```bash
git clone https://github.com/mrose105/apex_gamma
cd apex_gamma
pip install alpaca-py pandas numpy scipy streamlit plotly
```

Set environment variables:
```bash
export APCA_API_KEY_ID="your_key"
export APCA_API_SECRET_KEY="your_secret"
```

Run the scanner:
```bash
python3 scanner.py
```

Launch the dashboard:
```bash
streamlit run dashboard.py
```

---

## Stack

- **Alpaca Markets API** — options chain data, order execution
- **Black-Scholes / scipy** — Greeks computation, IV back-solving
- **Pandas / NumPy** — chain processing and ranking
- **Streamlit / Plotly** — live dashboard

---

*Paper trading mode by default. Not financial advice.*
