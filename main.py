"""
main.py — APEX Gamma trading engine orchestrator.

Architecture:
  scanner.py        → scan + signal generation (pure data, no side effects)
  risk_manager.py   → entry/exit approval (pure logic, no side effects)
  execution.py      → order placement (single point of broker contact)
  position_manager.py → state & P&L tracking (persistence layer)
  main.py           → orchestration loop (connects all four layers)

Loop (every REFRESH_INTERVAL seconds):
  1. Scan: fetch chain, compute Greeks, generate signals
  2. Manage exits: check each open position for EXIT signal / stop-loss / forced liq
  3. Manage entries: find top ENTRY signals, run risk filters, execute
  4. Log portfolio state

Run modes:
  python3 main.py              # live trading (respects config.PAPER)
  python3 main.py --paper      # force paper mode regardless of config
  python3 main.py --scan-only  # signal generation only, no orders placed
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import execution as ex
import scanner
from position_manager import PositionManager
from risk_manager import RiskManager

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("apex_gamma.log"),
    ],
)
log = logging.getLogger("apex_gamma.main")

TZ_ET = ZoneInfo("America/New_York")


# ── Helpers ──────────────────────────────────────────────────────────

def _fetch_vix() -> float | None:
    """
    Fetch VIX spot level for regime filter.
    Uses Alpaca stock quote on ^VIX (returns None if unavailable on paper tier).
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest
        client = StockHistoricalDataClient(config.API_KEY, config.API_SECRET)
        req    = StockLatestQuoteRequest(symbol_or_symbols="VIX")
        q      = client.get_stock_latest_quote(req)
        vix    = (q["VIX"].ask_price + q["VIX"].bid_price) / 2
        return round(vix, 2)
    except Exception:
        return None  # not available on all Alpaca tiers — risk filter skips it


def _market_is_open() -> bool:
    now = datetime.now(TZ_ET)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now <= market_close


# ── Exit Loop ────────────────────────────────────────────────────────

def process_exits(pm: PositionManager, rm: RiskManager, df, scan_only: bool) -> None:
    """
    For each open position, update Greeks from current scan, then check
    if it should be exited. If yes, submit exit order and close record.
    """
    if pm.position_count() == 0:
        return

    for pos_id, pos in list(pm.open_positions.items()):
        if pos.state != "OPEN":
            continue

        # Match position symbol to current scan row
        row_match = df[df["symbol"] == pos.symbol]
        if row_match.empty:
            log.warning("Position %s symbol %s not found in scan — stale?", pos_id, pos.symbol)
            continue

        row = row_match.iloc[0]
        pm.update_greeks(pos_id, row)

        should_exit, reason = rm.should_exit(pos_id, row["signal"])
        if not should_exit:
            upnl = pos.unrealized_pnl(pos.current_price)
            log.info(
                "HOLDING %s | %s K=%.0f | signal=%s | mid=$%.4f | P&L=$%.2f",
                pos_id, pos.option_type.upper(), pos.strike,
                row["signal"], pos.current_price, upnl,
            )
            continue

        log.info("EXIT TRIGGERED %s — %s", pos_id, reason)

        if scan_only:
            log.info("[SCAN-ONLY] Would exit %s @ $%.4f", pos_id, pos.current_price)
            continue

        pm.mark_closing(pos_id)
        fill = ex.place_exit_order(pos.symbol, pos.current_price, pos.contracts)
        if fill is not None:
            realized = pm.close_position(pos_id, fill)
            log.info("EXIT COMPLETE %s | realized=$%.2f", pos_id, realized)
        else:
            log.error("EXIT FAILED %s — order did not fill, position remains OPEN", pos_id)
            pos.state = "OPEN"  # revert so next cycle retries


# ── Entry Loop ───────────────────────────────────────────────────────

def process_entries(
    pm: PositionManager,
    rm: RiskManager,
    df,
    spot: float,
    vix: float | None,
    scan_only: bool,
) -> None:
    """
    Find top ENTRY-signal contracts, run risk filters, execute entries.
    Stops after filling MAX_OPEN_POSITIONS or exhausting ENTRY candidates.
    """
    phase = scanner.get_market_phase()
    if phase in ("NO_ENTRY", "CLOSE", "CLOSED"):
        return

    entry_candidates = df[df["signal"] == "ENTRY"].copy()
    if entry_candidates.empty:
        log.info("No ENTRY signals this cycle")
        return

    # Sort: highest gamma first (strongest arc momentum)
    entry_candidates = entry_candidates.sort_values("bs_gamma", ascending=False)

    for _, row in entry_candidates.iterrows():
        if pm.position_count() >= config.MAX_OPEN_POSITIONS:
            break

        approved, reason = rm.approve_entry(row, spot, vix)
        if not approved:
            log.info("ENTRY BLOCKED [%s]: %s", row["symbol"][-16:], reason)
            continue

        log.info(
            "ENTRY APPROVED | %s %s K=%.0f | gamma=%.4f | iv=%.1f%% | mid=$%.4f",
            row["type"].upper(), row["symbol"][-16:], row["strike"],
            row["bs_gamma"], row["iv"] * 100, row["mid_price"],
        )

        if scan_only:
            log.info("[SCAN-ONLY] Would enter %s @ $%.4f", row["symbol"], row["mid_price"])
            continue

        fill = ex.place_entry_order(row["symbol"], row["mid_price"], config.MAX_CONTRACTS_PER_TRADE)
        if fill is not None:
            pos_id = pm.open_position(row, config.MAX_CONTRACTS_PER_TRADE, fill, spot)
            log.info("ENTRY COMPLETE | pos_id=%s | fill=$%.4f", pos_id, fill)
        else:
            log.warning("ENTRY FAILED | %s — order did not fill", row["symbol"])


# ── Main Loop ────────────────────────────────────────────────────────

def run(scan_only: bool = False) -> None:
    mode_label = "SCAN-ONLY" if scan_only else ("PAPER" if config.PAPER else "LIVE")
    log.info("=" * 60)
    log.info("APEX GAMMA ENGINE STARTING | mode=%s | underlying=%s", mode_label, config.UNDERLYING)
    log.info("=" * 60)

    pm = PositionManager()
    rm = RiskManager(pm)

    if not scan_only:
        acct = ex.get_account_info()
        log.info("Account | equity=$%.2f | buying_power=$%.2f | PDT count=%d",
                 acct.get("equity", 0), acct.get("buying_power", 0), acct.get("daytrade_count", 0))

    while True:
        if not _market_is_open():
            phase = scanner.get_market_phase()
            if phase == "CLOSED":
                log.info("Market closed. Engine halting. | %s", pm.summary())
                break
            log.info("Waiting for market open...")
            time.sleep(30)
            continue

        cycle_start = time.time()
        log.info("── SCAN CYCLE ── %s", datetime.now(TZ_ET).strftime("%H:%M:%S ET"))

        try:
            df, spot = scanner.run_scan()
        except Exception as e:
            log.error("Scan failed: %s — sleeping %ds", e, config.REFRESH_INTERVAL)
            time.sleep(config.REFRESH_INTERVAL)
            continue

        if df.empty:
            log.warning("Empty scan result — no contracts processed")
            time.sleep(config.REFRESH_INTERVAL)
            continue

        vix = _fetch_vix()
        log.info("SPY spot=$%.2f | VIX=%s | %s", spot, f"{vix:.1f}" if vix else "N/A", pm.summary())

        # 1. Exits first — always check before entries
        process_exits(pm, rm, df, scan_only)

        # 2. Entries — only if capacity available
        process_entries(pm, rm, df, spot, vix, scan_only)

        # 3. Portfolio snapshot
        pg = pm.portfolio_greeks()
        log.info(
            "Portfolio Greeks | Δ=%.2f | Γ=%.4f | Θ=$%.2f/day | V=%.4f",
            pg["delta"], pg["gamma"], pg["theta"], pg["vega"],
        )

        elapsed = time.time() - cycle_start
        sleep_for = max(0, config.REFRESH_INTERVAL - elapsed)
        log.info("Cycle complete in %.1fs — next scan in %.0fs", elapsed, sleep_for)
        time.sleep(sleep_for)


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APEX Gamma Trading Engine")
    parser.add_argument(
        "--scan-only", action="store_true",
        help="Generate signals and log without placing orders"
    )
    parser.add_argument(
        "--paper", action="store_true",
        help="Force paper trading mode regardless of config.PAPER"
    )
    args = parser.parse_args()

    if args.paper:
        config.PAPER = True
        log.info("Forced paper mode via --paper flag")

    run(scan_only=args.scan_only)
