import pandas as pd
import numpy as np
from datetime import date
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest, OptionChainRequest
import config
import greeks_engine as ge

# ── Fetch Live 0DTE SPY Chain ────────────────────────────────────────

def get_spy_chain():
    """Pull full SPY 0DTE options chain from Alpaca."""
    client = config.option_data_client

    request = OptionChainRequest(
        underlying_symbol=config.UNDERLYING,
        expiration_date=config.EXPIRY,
    )

    chain = client.get_option_chain(request)
    return chain

# ── Get Spot Price ───────────────────────────────────────────────────

def get_spot_price():
    """Get current SPY spot price from Alpaca trading client."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest

    stock_client = StockHistoricalDataClient(config.API_KEY, config.API_SECRET)
    req = StockLatestQuoteRequest(symbol_or_symbols=config.UNDERLYING)
    quote = stock_client.get_stock_latest_quote(req)
    mid = (quote[config.UNDERLYING].ask_price + quote[config.UNDERLYING].bid_price) / 2
    return round(mid, 2)

# ── Parse Chain into DataFrame ───────────────────────────────────────

def build_chain_df(chain, spot, r=0.05):
    """
    For each contract in chain, compute:
    - BS Greeks
    - Broker Greeks
    - Greeks diff
    - Fair value & pricing edge
    - Gamma arc signal
    """
    rows = []

    # Track gamma peaks per option type for arc signal
    gamma_peaks = {"call": 0.0, "put": 0.0}

    # First pass: find gamma peaks
    for symbol, snapshot in chain.items():
        try:
            opt_type = "call" if "C" in symbol.split("SPY")[1] else "put"
            strike_str = symbol[-8:]
            K = int(strike_str) / 1000
            iv = snapshot.implied_volatility
            if not iv:
                q = snapshot.latest_quote
                if not q:
                    continue
                mid = (q.bid_price + q.ask_price) / 2
                iv = ge.implied_vol(mid, spot, K, r, opt_type)
            if not iv:
                continue
            bs = ge.bs_greeks(S=spot, K=K, r=r, sigma=iv, option_type=opt_type)
            if bs and bs["gamma"] > gamma_peaks[opt_type]:
                gamma_peaks[opt_type] = bs["gamma"]
        except Exception:
            continue

    # Second pass: build full rows
    for symbol, snapshot in chain.items():
        try:
            opt_type = "call" if "C" in symbol.split("SPY")[1] else "put"

            # Parse strike from OCC symbol
            strike_str = symbol[-8:]
            K = int(strike_str) / 1000

            # Market price (mid) — computed first so IV solver can use it
            bid = snapshot.latest_quote.bid_price or 0
            ask = snapshot.latest_quote.ask_price or 0
            mid_price = round((bid + ask) / 2, 4)

            if mid_price <= 0:
                continue

            iv = snapshot.implied_volatility
            if not iv:
                iv = ge.implied_vol(mid_price, spot, K, r, opt_type)
            if not iv or iv <= 0:
                continue

            # Moneyness
            moneyness = round(spot / K, 4)

            # BS Greeks
            bs = ge.bs_greeks(S=spot, K=K, r=r, sigma=iv, option_type=opt_type)

            # Broker Greeks
            broker = ge.broker_greeks(snapshot)

            # Diff
            diff = ge.compare_greeks(bs, broker)

            # Fair value & edge
            fv = ge.fair_value_bs(S=spot, K=K, r=r, sigma=iv, option_type=opt_type)
            edge = ge.pricing_edge(mid_price, fv)

            # Gamma arc signal
            peak = gamma_peaks[opt_type]
            gamma_val = bs["gamma"] if bs else 0
            signal = ge.gamma_arc_signal(gamma_val, peak, moneyness, option_type=opt_type)

            rows.append({
                "symbol":        symbol,
                "type":          opt_type,
                "strike":        K,
                "moneyness":     moneyness,
                "mid_price":     mid_price,
                "fair_value":    fv,
                "edge":          edge["edge"] if edge else None,
                "edge_pct":      edge["edge_pct"] if edge else None,
                "iv":            round(iv, 4),
                # BS Greeks
                "bs_delta":      bs["delta"] if bs else None,
                "bs_gamma":      bs["gamma"] if bs else None,
                "bs_theta":      bs["theta"] if bs else None,
                "bs_vega":       bs["vega"] if bs else None,
                "bs_rho":        bs["rho"] if bs else None,
                # Broker Greeks
                "br_delta":      broker["delta"] if broker else None,
                "br_gamma":      broker["gamma"] if broker else None,
                "br_theta":      broker["theta"] if broker else None,
                "br_vega":       broker["vega"] if broker else None,
                # Diff
                "gamma_diff":    diff["gamma"] if diff else None,
                "delta_diff":    diff["delta"] if diff else None,
                # Signal
                "signal":        signal,
                "hours_left":    bs["T"] if bs else None,
            })

        except Exception as e:
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Sort by signal priority then gamma
    signal_order = {"ENTRY": 0, "PEAK": 1, "EXIT": 2, "HOLD": 3, "AVOID": 4}
    df["signal_rank"] = df["signal"].map(signal_order)
    df = df.sort_values(["signal_rank", "bs_gamma"], ascending=[True, False])
    df = df.drop(columns=["signal_rank"])
    df = df.reset_index(drop=True)

    return df

# ── Main Scanner Run ─────────────────────────────────────────────────

def run_scan():
    """Full scan: fetch chain, get spot, build df."""
    print(f"Fetching SPY 0DTE chain for {config.EXPIRY}...")
    spot = get_spot_price()
    print(f"SPY Spot: ${spot}")
    chain = get_spy_chain()
    print(f"Contracts fetched: {len(chain)}")
    df = build_chain_df(chain, spot)
    print(f"Contracts processed: {len(df)}")
    return df, spot

if __name__ == "__main__":
    df, spot = run_scan()
    print("\n── TOP ENTRY SIGNALS ──")
    print(df[df["signal"] == "ENTRY"][["symbol","strike","moneyness","bs_gamma","edge_pct","signal"]].head(10).to_string())
    print("\n── TOP EXIT SIGNALS ──")
    print(df[df["signal"] == "EXIT"][["symbol","strike","moneyness","bs_gamma","edge_pct","signal"]].head(10).to_string())
