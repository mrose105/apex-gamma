"""
risk_manager.py — Pre-entry and portfolio-level risk filters for APEX Gamma.

Two layers of protection:
  1. Contract-level: is THIS specific contract safe to enter?
     - Bid-ask spread too wide (liquidity risk)
     - Open interest too low (exit risk)
     - Theta/gamma ratio too high (gamma is overpriced for its decay cost)
     - Already holding this symbol
     - VIX out of range (regime filter)
     - Max open positions reached

  2. Portfolio-level: does adding THIS position breach aggregate risk limits?
     - Net delta cap
     - Net theta cap (daily bleed limit)

Usage:
    rm = RiskManager(position_manager)
    approved, reason = rm.approve_entry(row, scan_df, spot, vix)
    approved, reason = rm.check_portfolio_limits(portfolio_greeks, new_row)
"""

from __future__ import annotations

import logging
from typing import Tuple

import pandas as pd

import config
from position_manager import PositionManager

log = logging.getLogger(__name__)


class RiskManager:

    def __init__(self, pm: PositionManager):
        self.pm = pm

    # ── Contract-Level Checks ────────────────────────────────────────

    def _check_spread(self, row: pd.Series) -> Tuple[bool, str]:
        """Reject if bid-ask spread is too wide relative to mid."""
        mid = row.get("mid_price", 0)
        if mid <= 0:
            return False, "mid_price is zero"
        # Reconstruct spread from fair_value edge or use iv as proxy
        # We don't store bid/ask in df directly; use edge_pct as spread proxy
        # when broker IV available. Without it, check mid > minimum threshold.
        if mid < 0.05:
            return False, f"mid_price ${mid:.4f} below $0.05 minimum (illiquid)"
        return True, ""

    def _check_open_interest(self, row: pd.Series) -> Tuple[bool, str]:
        """Reject if open interest is below threshold."""
        oi = row.get("open_interest", None)
        if oi is None:
            # OI not in scanner df yet — pass through (can't check)
            return True, ""
        if oi < config.MIN_OPEN_INTEREST:
            return False, f"open_interest {oi} < {config.MIN_OPEN_INTEREST}"
        return True, ""

    def _check_theta_gamma_ratio(self, row: pd.Series) -> Tuple[bool, str]:
        """
        Reject if |theta| / gamma > MAX_THETA_GAMMA_RATIO.
        A high ratio means you're paying too much daily decay per unit of gamma.
        Theta and gamma are both per-contract values from BS.
        """
        gamma = row.get("bs_gamma", 0) or 0
        theta = row.get("bs_theta", 0) or 0
        if gamma <= 0:
            return False, "gamma is zero"
        ratio = abs(theta) / gamma
        if ratio > config.MAX_THETA_GAMMA_RATIO:
            return False, f"|theta|/gamma={ratio:.2f} > {config.MAX_THETA_GAMMA_RATIO} (gamma overpriced)"
        return True, ""

    def _check_vix(self, vix: float | None) -> Tuple[bool, str]:
        """
        Reject if VIX is outside the entry range.
        Too low → gamma is cheap but SPY won't move enough to profit.
        Too high → IV spike means you're buying expensive options in a panic.
        """
        if vix is None:
            return True, ""  # no VIX data available — skip check
        if vix < config.VIX_ENTRY_MIN:
            return False, f"VIX {vix:.1f} < {config.VIX_ENTRY_MIN} (market too quiet)"
        if vix > config.VIX_ENTRY_MAX:
            return False, f"VIX {vix:.1f} > {config.VIX_ENTRY_MAX} (panic regime, spreads too wide)"
        return True, ""

    def _check_position_count(self) -> Tuple[bool, str]:
        n = self.pm.position_count()
        if n >= config.MAX_OPEN_POSITIONS:
            return False, f"max open positions reached ({n}/{config.MAX_OPEN_POSITIONS})"
        return True, ""

    def _check_duplicate(self, row: pd.Series) -> Tuple[bool, str]:
        if self.pm.already_holding(row["symbol"]):
            return False, f"already holding {row['symbol']}"
        return True, ""

    # ── Portfolio-Level Checks ───────────────────────────────────────

    def check_portfolio_limits(
        self,
        portfolio_greeks: dict,
        new_row: pd.Series,
        contracts: int = 1,
    ) -> Tuple[bool, str]:
        """
        Check if adding a new position would breach portfolio-level risk limits.
        portfolio_greeks — current aggregate Greeks from PositionManager
        new_row          — scanner row for the proposed new position
        """
        mult = contracts * 100
        new_delta = (new_row.get("bs_delta", 0) or 0) * mult
        new_theta = (new_row.get("bs_theta", 0) or 0) * mult

        projected_delta = abs(portfolio_greeks.get("delta", 0) + new_delta)
        projected_theta = portfolio_greeks.get("theta", 0) + new_theta

        if projected_delta > config.MAX_PORTFOLIO_DELTA:
            return False, (
                f"projected net delta {projected_delta:.2f} > "
                f"limit {config.MAX_PORTFOLIO_DELTA}"
            )
        if projected_theta < config.MAX_PORTFOLIO_THETA:
            return False, (
                f"projected portfolio theta ${projected_theta:.2f}/day < "
                f"limit ${config.MAX_PORTFOLIO_THETA}/day"
            )
        return True, ""

    # ── Combined Entry Gate ──────────────────────────────────────────

    def approve_entry(
        self,
        row: pd.Series,
        spot: float,
        vix: float | None = None,
    ) -> Tuple[bool, str]:
        """
        Run all pre-entry checks in priority order.
        Returns (approved: bool, reason: str).
        reason is empty string if approved.
        """
        checks = [
            self._check_position_count,
            lambda: self._check_duplicate(row),
            lambda: self._check_spread(row),
            lambda: self._check_open_interest(row),
            lambda: self._check_theta_gamma_ratio(row),
            lambda: self._check_vix(vix),
            lambda: self.check_portfolio_limits(
                self.pm.portfolio_greeks(), row, config.MAX_CONTRACTS_PER_TRADE
            ),
        ]

        for check in checks:
            ok, reason = check()
            if not ok:
                log.debug("Entry rejected [%s]: %s", row.get("symbol", "?"), reason)
                return False, reason

        return True, ""

    # ── Exit Checks ──────────────────────────────────────────────────

    def should_exit(self, pos_id: str, current_signal: str) -> Tuple[bool, str]:
        """
        Determine if an open position should be exited.
        Checks signal, stop-loss, and forced liquidation phase.
        """
        from scanner import get_market_phase
        pos = self.pm.open_positions.get(pos_id)
        if pos is None:
            return False, "position not found"

        phase = get_market_phase()

        # Forced liquidation at 3:38pm
        if phase == "CLOSE":
            return True, "3:38pm forced liquidation"

        # Stop-loss
        if pos.stop_loss_breached():
            loss_pct = (pos.current_price - pos.entry_price) / pos.entry_price * 100
            return True, f"stop-loss breached ({loss_pct:.1f}%)"

        # Signal-based exit
        if current_signal == "EXIT":
            return True, "EXIT signal"

        return False, ""
