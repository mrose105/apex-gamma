"""
position_manager.py — Position lifecycle tracking for APEX Gamma.

Responsibilities:
  - Open / close position records with full entry Greeks
  - Per-position P&L (unrealized and realized)
  - Aggregate portfolio Greeks (delta, gamma, theta, vega)
  - JSON persistence so state survives process restarts
  - State machine: OPEN → CLOSING → CLOSED

Usage:
    pm = PositionManager()
    pos_id = pm.open_position(row, contracts=1, fill_price=1.25, spot=635.0)
    pm.update_greeks(pos_id, current_row)
    pnl = pm.unrealized_pnl(pos_id, current_mid=1.80)
    pm.close_position(pos_id, fill_price=1.80)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd

import config

log = logging.getLogger(__name__)
TZ_ET = ZoneInfo("America/New_York")
POSITIONS_FILE = "positions.json"


# ── Position Dataclass ───────────────────────────────────────────────

@dataclass
class Position:
    pos_id:          str
    symbol:          str
    option_type:     str    # "call" | "put"
    strike:          float
    contracts:       int
    entry_price:     float  # per-share mid at fill (option premium)
    entry_time:      str    # ISO timestamp ET
    entry_spot:      float
    entry_moneyness: float
    entry_iv:        float
    entry_delta:     float
    entry_gamma:     float
    entry_theta:     float
    entry_vega:      float
    entry_speed:     float

    state:           str   = "OPEN"   # OPEN | CLOSING | CLOSED
    exit_price:      Optional[float] = None
    exit_time:       Optional[str]   = None
    realized_pnl:    Optional[float] = None  # $ total (contracts * 100 * price diff)

    # Updated each scan cycle
    current_price:   float = 0.0
    current_delta:   float = 0.0
    current_gamma:   float = 0.0
    current_theta:   float = 0.0
    current_vega:    float = 0.0
    current_iv:      float = 0.0
    current_signal:  str   = "HOLD"

    @property
    def cost_basis(self) -> float:
        """Total $ paid to enter (entry premium × contracts × 100 shares)."""
        return self.entry_price * self.contracts * 100

    def unrealized_pnl(self, current_mid: float) -> float:
        """Unrealized P&L in dollars."""
        return (current_mid - self.entry_price) * self.contracts * 100

    def unrealized_pnl_pct(self, current_mid: float) -> float:
        """Unrealized P&L as % of cost basis."""
        if self.cost_basis == 0:
            return 0.0
        return self.unrealized_pnl(current_mid) / self.cost_basis * 100

    def stop_loss_breached(self) -> bool:
        """True if unrealized loss exceeds MAX_LOSS_PER_POSITION_PCT of cost basis."""
        if self.current_price <= 0:
            return False
        return self.unrealized_pnl(self.current_price) / self.cost_basis < -config.MAX_LOSS_PER_POSITION_PCT


# ── Position Manager ─────────────────────────────────────────────────

class PositionManager:
    """
    Thread-safe (single-process) in-memory position book with JSON persistence.
    Survives process restarts via load_from_disk() / save_to_disk().
    """

    def __init__(self, positions_file: str = POSITIONS_FILE):
        self._file = positions_file
        self._positions: Dict[str, Position] = {}
        self.load_from_disk()

    # ── Persistence ──────────────────────────────────────────────────

    def save_to_disk(self) -> None:
        with open(self._file, "w") as f:
            json.dump(
                {pid: asdict(p) for pid, p in self._positions.items()},
                f, indent=2, default=str
            )

    def load_from_disk(self) -> None:
        if not os.path.exists(self._file):
            return
        try:
            with open(self._file) as f:
                raw = json.load(f)
            for pid, d in raw.items():
                self._positions[pid] = Position(**d)
            log.info("Loaded %d positions from disk", len(self._positions))
        except Exception as e:
            log.warning("Could not load positions file: %s", e)

    # ── Open / Close ─────────────────────────────────────────────────

    def open_position(
        self,
        row: pd.Series,
        contracts: int,
        fill_price: float,
        spot: float,
    ) -> str:
        """
        Record a new position entry.
        row      — scanner df row with bs_* Greeks and iv fields
        contracts — number of option contracts
        fill_price — actual fill price (per share, e.g. 1.50)
        spot      — SPY spot at entry
        Returns pos_id (UUID string).
        """
        pos_id = str(uuid.uuid4())[:8]
        now_et = datetime.now(TZ_ET).isoformat()

        pos = Position(
            pos_id          = pos_id,
            symbol          = row["symbol"],
            option_type     = row["type"],
            strike          = row["strike"],
            contracts       = contracts,
            entry_price     = fill_price,
            entry_time      = now_et,
            entry_spot      = spot,
            entry_moneyness = row["moneyness"],
            entry_iv        = row["iv"],
            entry_delta     = row.get("bs_delta", 0.0) or 0.0,
            entry_gamma     = row.get("bs_gamma", 0.0) or 0.0,
            entry_theta     = row.get("bs_theta", 0.0) or 0.0,
            entry_vega      = row.get("bs_vega",  0.0) or 0.0,
            entry_speed     = row.get("bs_speed", 0.0) or 0.0,
            current_price   = fill_price,
            current_delta   = row.get("bs_delta", 0.0) or 0.0,
            current_gamma   = row.get("bs_gamma", 0.0) or 0.0,
            current_theta   = row.get("bs_theta", 0.0) or 0.0,
            current_vega    = row.get("bs_vega",  0.0) or 0.0,
            current_iv      = row["iv"],
            current_signal  = row.get("signal", "HOLD"),
        )
        self._positions[pos_id] = pos
        self.save_to_disk()
        log.info(
            "OPENED %s | %s %s K=%.0f | %d contracts @ $%.4f | spot=$%.2f",
            pos_id, pos.option_type.upper(), pos.symbol[-16:],
            pos.strike, contracts, fill_price, spot,
        )
        return pos_id

    def close_position(self, pos_id: str, fill_price: float) -> float:
        """
        Mark position CLOSED and record realized P&L.
        Returns realized P&L in dollars.
        """
        pos = self._positions.get(pos_id)
        if pos is None:
            raise KeyError(f"Position {pos_id} not found")
        if pos.state == "CLOSED":
            log.warning("Position %s already closed", pos_id)
            return 0.0

        pos.exit_price   = fill_price
        pos.exit_time    = datetime.now(TZ_ET).isoformat()
        pos.realized_pnl = (fill_price - pos.entry_price) * pos.contracts * 100
        pos.state        = "CLOSED"
        self.save_to_disk()
        log.info(
            "CLOSED %s | %s %s K=%.0f | exit=$%.4f | P&L=$%.2f",
            pos_id, pos.option_type.upper(), pos.symbol[-16:],
            pos.strike, fill_price, pos.realized_pnl,
        )
        return pos.realized_pnl

    def mark_closing(self, pos_id: str) -> None:
        """Flag position as being exited (order submitted, awaiting fill)."""
        pos = self._positions[pos_id]
        pos.state = "CLOSING"
        self.save_to_disk()

    # ── Update ───────────────────────────────────────────────────────

    def update_greeks(self, pos_id: str, row: pd.Series) -> None:
        """Refresh current-cycle Greeks/price/signal for an open position."""
        pos = self._positions.get(pos_id)
        if pos is None or pos.state != "OPEN":
            return
        pos.current_price  = row.get("mid_price",  pos.current_price)
        pos.current_delta  = row.get("bs_delta",   pos.current_delta) or pos.current_delta
        pos.current_gamma  = row.get("bs_gamma",   pos.current_gamma) or pos.current_gamma
        pos.current_theta  = row.get("bs_theta",   pos.current_theta) or pos.current_theta
        pos.current_vega   = row.get("bs_vega",    pos.current_vega)  or pos.current_vega
        pos.current_iv     = row.get("iv",          pos.current_iv)
        pos.current_signal = row.get("signal",      "HOLD")

    # ── Queries ──────────────────────────────────────────────────────

    @property
    def open_positions(self) -> Dict[str, Position]:
        return {pid: p for pid, p in self._positions.items() if p.state == "OPEN"}

    @property
    def all_positions(self) -> Dict[str, Position]:
        return dict(self._positions)

    def position_count(self) -> int:
        return len(self.open_positions)

    def already_holding(self, symbol: str) -> bool:
        """True if there's already an open or closing position in this symbol."""
        return any(
            p.symbol == symbol and p.state in ("OPEN", "CLOSING")
            for p in self._positions.values()
        )

    def portfolio_greeks(self) -> dict:
        """
        Sum of Greeks across all open positions (scaled to $ per contract-lot).
        delta_dollars = net delta × spot × 100 ($ move per $1 SPY move)
        theta_dollars = net theta × contracts × 100 ($ per day across portfolio)
        """
        net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
        for pos in self.open_positions.values():
            mult = pos.contracts * 100
            net["delta"] += pos.current_delta * mult
            net["gamma"] += pos.current_gamma * mult
            net["theta"] += pos.current_theta * mult
            net["vega"]  += pos.current_vega  * mult
        return {k: round(v, 4) for k, v in net.items()}

    def total_unrealized_pnl(self) -> float:
        return sum(
            p.unrealized_pnl(p.current_price)
            for p in self.open_positions.values()
            if p.current_price > 0
        )

    def total_realized_pnl(self) -> float:
        return sum(
            p.realized_pnl for p in self._positions.values()
            if p.realized_pnl is not None
        )

    def summary(self) -> str:
        pg = self.portfolio_greeks()
        return (
            f"Positions: {self.position_count()} open | "
            f"Unrealized: ${self.total_unrealized_pnl():.2f} | "
            f"Realized: ${self.total_realized_pnl():.2f} | "
            f"Net Δ: {pg['delta']:.2f} | Net Θ: ${pg['theta']:.2f}/day"
        )
