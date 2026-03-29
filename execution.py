"""
execution.py — Order placement and fill tracking for APEX Gamma.

Design:
  - All orders sent as limit orders at mid + LIMIT_AGGRESSION to avoid
    crossing the spread entirely, while still likely filling in liquid 0DTE.
  - Returns fill price on success, None on failure/timeout.
  - Slippage is logged as fill_price - mid_price for post-trade analysis.
  - Stateless — position tracking lives in PositionManager.

Broker: Alpaca Markets (paper or live, controlled by config.PAPER).
Swap this module for IBKR / TDA / Tradier by implementing the same
place_entry_order / place_exit_order interface.

Usage:
    fill = place_entry_order(symbol, mid_price, contracts=1)
    fill = place_exit_order(symbol, mid_price, contracts=1)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest

import config

log = logging.getLogger(__name__)

_POLL_INTERVAL = 1.0   # seconds between fill status checks
_FILL_TIMEOUT  = 15    # seconds before cancelling unfilled limit order


def _submit_limit_order(
    symbol: str,
    side: OrderSide,
    qty: int,
    limit_price: float,
) -> Optional[float]:
    """
    Submit a limit order and poll for fill up to _FILL_TIMEOUT seconds.
    Returns fill price on success, None on timeout or error.
    """
    client = config.trading_client
    req = LimitOrderRequest(
        symbol      = symbol,
        qty         = qty,
        side        = side,
        time_in_force = TimeInForce.DAY,
        limit_price = round(limit_price, 2),
    )

    try:
        order = client.submit_order(req)
        order_id = str(order.id)
        log.info(
            "ORDER SUBMITTED | %s %s x%d @ limit $%.2f | id=%s",
            side.value.upper(), symbol[-16:], qty, limit_price, order_id,
        )
    except Exception as e:
        log.error("Order submission failed for %s: %s", symbol, e)
        return None

    # Poll for fill
    deadline = time.time() + _FILL_TIMEOUT
    while time.time() < deadline:
        try:
            o = client.get_order_by_id(order_id)
            status = str(o.status).lower()

            if status == "filled":
                fill_price = float(o.filled_avg_price)
                log.info(
                    "FILLED | %s %s x%d @ $%.4f | id=%s",
                    side.value.upper(), symbol[-16:], qty, fill_price, order_id,
                )
                return fill_price

            if status in ("cancelled", "expired", "rejected"):
                log.warning("Order %s ended with status: %s", order_id, status)
                return None

        except Exception as e:
            log.warning("Error polling order %s: %s", order_id, e)

        time.sleep(_POLL_INTERVAL)

    # Timeout — cancel the order
    log.warning("Order %s timed out after %ds — cancelling", order_id, _FILL_TIMEOUT)
    try:
        client.cancel_order_by_id(order_id)
    except Exception as e:
        log.error("Failed to cancel order %s: %s", order_id, e)
    return None


def place_entry_order(
    symbol: str,
    mid_price: float,
    contracts: int = None,
) -> Optional[float]:
    """
    Buy to open: limit order at mid + LIMIT_AGGRESSION.
    Returns fill price or None if order failed/timed out.
    """
    if contracts is None:
        contracts = config.MAX_CONTRACTS_PER_TRADE

    limit_price = mid_price + config.LIMIT_AGGRESSION
    fill = _submit_limit_order(symbol, OrderSide.BUY, contracts, limit_price)

    if fill is not None:
        slippage = fill - mid_price
        log.info("Entry slippage: $%.4f (fill=%.4f mid=%.4f)", slippage, fill, mid_price)

    return fill


def place_exit_order(
    symbol: str,
    mid_price: float,
    contracts: int = None,
) -> Optional[float]:
    """
    Sell to close: limit order at mid - LIMIT_AGGRESSION (concede $0.01 to exit).
    Returns fill price or None if order failed/timed out.
    """
    if contracts is None:
        contracts = config.MAX_CONTRACTS_PER_TRADE

    limit_price = max(mid_price - config.LIMIT_AGGRESSION, 0.01)
    fill = _submit_limit_order(symbol, OrderSide.SELL, contracts, limit_price)

    if fill is not None:
        slippage = mid_price - fill  # positive = we received less than mid
        log.info("Exit slippage: $%.4f (fill=%.4f mid=%.4f)", slippage, fill, mid_price)

    return fill


def get_account_info() -> dict:
    """Return key account metrics for logging / dashboard."""
    try:
        acct = config.trading_client.get_account()
        return {
            "buying_power":  float(acct.buying_power),
            "equity":        float(acct.equity),
            "cash":          float(acct.cash),
            "daytrade_count": int(acct.daytrade_count),
        }
    except Exception as e:
        log.error("Could not fetch account info: %s", e)
        return {}
