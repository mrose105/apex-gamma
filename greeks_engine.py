import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from datetime import datetime
from zoneinfo import ZoneInfo
import config

TZ_ET = ZoneInfo("America/New_York")

# ── Black-Scholes Greeks ─────────────────────────────────────────────

def time_to_expiry() -> float:
    """Returns fraction of trading year remaining for 0DTE (in years).
    Uses ET timezone so the result is correct on any host machine.
    """
    now = datetime.now(TZ_ET)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    remaining_secs = max((market_close - now).total_seconds(), 60)  # floor at 1 min
    trading_year = 252 * 6.5 * 3600  # seconds in a trading year
    return remaining_secs / trading_year


def bs_greeks(S, K, r, sigma, option_type="call"):
    """
    Compute full BS Greeks for a single contract.
    S     = spot price
    K     = strike
    r     = risk-free rate (annualized)
    sigma = implied volatility (annualized)
    """
    T = time_to_expiry()

    if T <= 0 or sigma <= 0:
        return None

    sqrt_T = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    # Delta
    if option_type == "call":
        delta = norm.cdf(d1)
    else:
        delta = norm.cdf(d1) - 1  # = -N(-d1)

    # Gamma (same for calls and puts)
    gamma = norm.pdf(d1) / (S * sigma * sqrt_T)

    # Theta (per calendar day, annualized with 365)
    # Call:  -(S·N'(d1)·σ)/(2√T) - r·K·e^(-rT)·N(d2)
    # Put:   -(S·N'(d1)·σ)/(2√T) + r·K·e^(-rT)·N(-d2)
    disc = K * np.exp(-r * T)
    common_theta = -(S * norm.pdf(d1) * sigma) / (2 * sqrt_T)
    if option_type == "call":
        theta = (common_theta - r * disc * norm.cdf(d2)) / 365
    else:
        theta = (common_theta + r * disc * norm.cdf(-d2)) / 365

    # Vega (per 1% move in IV)
    vega = S * norm.pdf(d1) * sqrt_T / 100

    # Rho (per 1% move in rates)
    if option_type == "call":
        rho = disc * T * norm.cdf(d2) / 100
    else:
        rho = -disc * T * norm.cdf(-d2) / 100

    # Speed — dGamma/dS = d³V/dS³
    # Positive: gamma accelerating toward ATM (entry zone)
    # Negative: gamma decelerating, peak passed (exit zone)
    speed = -(gamma / S) * (d1 / (sigma * sqrt_T) + 1)

    # Vanna — d²V/dSdσ  (= dDelta/dσ = dVega/dS)
    # Canonical: -N'(d1)·d2/σ
    vanna = -norm.pdf(d1) * d2 / sigma

    # Charm — dDelta/dt per calendar day
    # Canonical (no dividends): -N'(d1)·[2rT - d2·σ·√T] / (2T·σ·√T)
    charm = -norm.pdf(d1) * (
        (2 * r * T - d2 * sigma * sqrt_T) /
        (2 * T * sigma * sqrt_T)
    ) / 365

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 4),
        "theta": round(theta, 4),
        "vega":  round(vega, 4),
        "rho":   round(rho, 4),
        "speed": round(speed, 6),
        "vanna": round(vanna, 4),
        "charm": round(charm, 6),
        "T":     round(T * 252 * 6.5, 4),  # trading hours remaining
    }


# ── Implied Volatility Solver ────────────────────────────────────────

def implied_vol(market_price, S, K, r, option_type="call", tol=1e-6):
    """
    Back-solve IV from market price using Brent's method.
    Returns None if price is outside arbitrage bounds or solver fails.
    T is captured once and shared with fair_value_bs to avoid timestamp drift.
    """
    T = time_to_expiry()
    if T <= 0 or market_price <= 0:
        return None

    # Arbitrage bounds check
    intrinsic = max(0, S - K) if option_type == "call" else max(0, K - S)
    if market_price < intrinsic * 0.99:
        return None

    def objective(sigma):
        return fair_value_bs(S, K, r, sigma, option_type, T=T) - market_price

    try:
        iv = brentq(objective, 1e-4, 20.0, xtol=tol, maxiter=200)
        return round(iv, 6)
    except Exception:
        return None


# ── Broker Greeks (from Alpaca snapshot) ────────────────────────────

def broker_greeks(snapshot):
    """Extract Greeks from Alpaca option snapshot object."""
    try:
        g = snapshot.greeks
        return {
            "delta": round(g.delta, 4),
            "gamma": round(g.gamma, 4),
            "theta": round(g.theta, 4),
            "vega":  round(g.vega, 4),
            "rho":   round(g.rho, 4),
        }
    except Exception:
        return None


# ── Comparison & Fair Value ──────────────────────────────────────────

def compare_greeks(bs, broker):
    """Diff BS vs broker Greeks. Positive = BS higher than broker."""
    if not bs or not broker:
        return None
    return {k: round(bs[k] - broker.get(k, 0), 4) for k in ["delta", "gamma", "theta", "vega", "rho"]}


def fair_value_bs(S, K, r, sigma, option_type="call", T=None):
    """
    Theoretical BS price.
    Accepts optional T (years) so the IV solver and Greeks engine share
    the same timestamp rather than each calling time_to_expiry() independently.
    """
    if T is None:
        T = time_to_expiry()
    if T <= 0 or sigma <= 0:
        return None
    sqrt_T = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    disc = K * np.exp(-r * T)
    if option_type == "call":
        return round(S * norm.cdf(d1) - disc * norm.cdf(d2), 4)
    else:
        return round(disc * norm.cdf(-d2) - S * norm.cdf(-d1), 4)


def pricing_edge(market_price, fair_value):
    """
    Positive = market overpriced vs BS (good to SELL)
    Negative = market underpriced vs BS (good to BUY)
    """
    if not fair_value or not market_price:
        return None
    edge = round(market_price - fair_value, 4)
    pct  = round((edge / fair_value) * 100, 2) if fair_value else None
    return {"edge": edge, "edge_pct": pct}


# ── Gamma Arc Signals ────────────────────────────────────────────────

def gamma_arc_signal(current_gamma, peak_gamma, moneyness, option_type="call", speed=None):
    """
    Returns entry/exit signal based on gamma arc logic.
    moneyness  = S / K (>1 = ITM for calls, <1 = ITM for puts)
    option_type = "call" or "put"
    speed      = dGamma/dS from bs_greeks — used to detect gamma peak before it happens
                 positive = gamma still accelerating (hold/entry)
                 negative = gamma decelerating (approaching exit)
    """
    if not current_gamma or not peak_gamma:
        return "HOLD"

    gamma_ratio = current_gamma / peak_gamma

    # Danger zone: gamma collapsed regardless of direction
    if current_gamma < config.MIN_GAMMA:
        return "AVOID"

    if option_type == "call":
        is_slightly_otm = config.ENTRY_MONEYNESS_THRESHOLD <= moneyness < 1.0

        # Speed-based early signal: detect gamma inflection before moneyness threshold
        if speed is not None:
            if speed > 0 and is_slightly_otm:
                return "ENTRY"
            if speed < 0 and moneyness > 0.999:
                return "EXIT"

        # Fallback moneyness-based logic
        if is_slightly_otm:
            return "ENTRY"

        # Peak zone: at or just past ATM, gamma near max
        if 0.98 <= moneyness <= 1.005 and gamma_ratio >= 0.95:
            return "PEAK"

        # Exit: call gone ITM past snipe threshold, gamma decaying
        if moneyness >= config.SNIPE_EXIT_MONEYNESS_CALL and gamma_ratio < config.GAMMA_PEAK_DECAY_TRIGGER:
            return "EXIT"

    else:  # put
        is_slightly_otm = 1.0 < moneyness <= (1.0 / config.ENTRY_MONEYNESS_THRESHOLD)

        # Speed-based early signal for puts
        if speed is not None:
            if speed > 0 and is_slightly_otm:
                return "ENTRY"
            if speed < 0 and moneyness < 1.001:
                return "EXIT"

        # Fallback moneyness-based logic
        if is_slightly_otm:
            return "ENTRY"

        # Peak zone: at or just past ATM for puts
        if 0.995 <= moneyness <= 1.02 and gamma_ratio >= 0.95:
            return "PEAK"

        # Exit: put gone ITM past snipe threshold, gamma decaying
        if moneyness <= config.SNIPE_EXIT_MONEYNESS_PUT and gamma_ratio < config.GAMMA_PEAK_DECAY_TRIGGER:
            return "EXIT"

    return "HOLD"
