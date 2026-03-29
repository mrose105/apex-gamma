"""
vol_tracker.py — Intraday realized volatility tracker for APEX Gamma.

Tracks rolling SPY price history to compute:
  - realized_move_per_interval: mean |ΔS| over last N samples (dollars)
  - realized_vol_annualized: annualized vol from recent returns (same convention as IV)

These are compared against gamma_breakeven (from greeks_engine) to determine
whether gamma is cheap or expensive at any given moment:

  realized_move > gamma_breakeven  → CHEAP  (enter)
  realized_move ≈ gamma_breakeven  → FAIR   (neutral)
  realized_move < gamma_breakeven  → EXPENSIVE (skip)

Usage:
    tracker = RealizedVolTracker(window=20, interval_seconds=30)
    tracker.update(spot)                    # call each scan cycle
    regime = tracker.vol_regime(breakeven)  # per-contract check
    stats  = tracker.stats()                # full metrics dict
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

TZ_ET = ZoneInfo("America/New_York")


class RealizedVolTracker:
    """
    Rolling window realized vol tracker.

    window            — number of scan intervals to include (default 20 = 10 min at 30s)
    interval_seconds  — scan frequency; used for annualization
    """

    def __init__(self, window: int = 20, interval_seconds: int = 30):
        self.window           = window
        self.interval_seconds = interval_seconds
        self._prices: deque   = deque(maxlen=window + 1)  # +1 to compute N returns from N+1 prices
        self._timestamps: deque = deque(maxlen=window + 1)

    def update(self, spot: float) -> None:
        """Record a new spot price observation."""
        self._prices.append(spot)
        self._timestamps.append(datetime.now(TZ_ET))

    def _returns(self) -> list[float]:
        """Log returns between consecutive observations."""
        prices = list(self._prices)
        if len(prices) < 2:
            return []
        return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]

    def realized_move_per_interval(self) -> Optional[float]:
        """
        Mean absolute SPY dollar move per scan interval over the rolling window.
        Compared directly against gamma_breakeven (also in dollar terms).
        Returns None if fewer than 3 observations (insufficient data).
        """
        prices = list(self._prices)
        if len(prices) < 3:
            return None
        abs_moves = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        return round(sum(abs_moves) / len(abs_moves), 4)

    def realized_vol_annualized(self) -> Optional[float]:
        """
        Annualized realized volatility using calendar-year convention (matching IV).
        Uses std of log returns × sqrt(intervals per year).
        Returns None if fewer than 3 observations.
        """
        rets = self._returns()
        if len(rets) < 2:
            return None
        n = len(rets)
        mean = sum(rets) / n
        variance = sum((r - mean) ** 2 for r in rets) / (n - 1)
        intervals_per_year = (365 * 24 * 3600) / self.interval_seconds
        return round(math.sqrt(variance * intervals_per_year), 4)

    def vol_regime(self, gamma_breakeven: Optional[float]) -> str:
        """
        Compare realized move to gamma break-even.

        CHEAP     — realized move > breakeven × 1.2  (gamma undervalued, enter)
        FAIR      — realized move within 20% of breakeven (neutral)
        EXPENSIVE — realized move < breakeven × 0.8  (gamma overvalued, skip)
        UNKNOWN   — insufficient price history
        """
        move = self.realized_move_per_interval()
        if move is None or gamma_breakeven is None or gamma_breakeven <= 0:
            return "UNKNOWN"
        ratio = move / gamma_breakeven
        if ratio >= 1.2:
            return "CHEAP"
        if ratio >= 0.8:
            return "FAIR"
        return "EXPENSIVE"

    def stats(self) -> dict:
        """Full metrics snapshot for logging and dashboard."""
        move = self.realized_move_per_interval()
        rvol = self.realized_vol_annualized()
        return {
            "observations":        len(self._prices),
            "realized_move_30s":   move,
            "realized_vol_annual": rvol,
            "realized_vol_pct":    round(rvol * 100, 2) if rvol else None,
            "window_seconds":      self.window * self.interval_seconds,
        }

    def is_ready(self) -> bool:
        """True once we have enough history to make a decision."""
        return len(self._prices) >= 3
