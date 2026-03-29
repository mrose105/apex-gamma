# Logic Review — APEX Gamma

## What It Checks

The `/logic-review` command audits all trading logic and math for quantitative correctness.

## Modules Covered

### `greeks_engine.py`
The mathematical core. Every formula is checked against canonical Black-Scholes references.

| Greek | Formula | Convention |
|---|---|---|
| Delta | `N(d1)` call, `N(d1)-1` put | Standard |
| Gamma | `N'(d1) / (S·σ·√T)` | Same for calls/puts |
| Theta | `-(S·N'·σ)/(2√T) ∓ r·K·e^(-rT)·N(±d2)` | Per calendar day / 365 |
| Vega | `S·N'(d1)·√T / 100` | Per 1% IV move |
| Rho | `K·T·e^(-rT)·N(±d2) / 100` | Per 1% rate move |
| Speed | `-(Γ/S)·(d1/(σ√T) + 1)` | d³V/dS³ |
| Vanna | `-N'(d1)·d2/σ` | d²V/dSdσ |
| Charm | `-N'(d1)·[2rT - d2·σ·√T] / (2T·σ·√T) / 365` | dΔ/dt per day |

**IV convention:** calendar year (365 × 24 × 3600) — matches all market-quoted IVs.

### `gamma_arc_signal` Logic

```
ENTRY  ← speed > 0 (calls) or speed < 0 (puts) while slightly OTM
           speed is a LEADING indicator — fires before gamma peaks
PEAK   ← gamma_ratio ≥ 0.95 and near ATM
EXIT   ← speed sign inverts (NO gamma_ratio guard — leading, not lagging)
           fallback: moneyness past snipe threshold AND gamma_ratio < 0.85
AVOID  ← gamma < MIN_GAMMA (deep OTM, no arc to ride)
HOLD   ← everything else
```

**Key principle:** Speed sign flip = gamma convergence point (d³V/dS³ = 0 at Γ peak).
Requiring gamma decay confirmation (gamma_ratio) after a speed signal turns a leading indicator into a lagging one and defeats its purpose.

### `gamma_breakeven_move`

```
break_even = sqrt(2 × |Θ| × dt / Γ)

Where dt = interval_seconds / 86400 (fraction of calendar day)

Interpretation:
  realized_SPY_move > break_even → gamma is cheap (enter)
  realized_SPY_move < break_even → gamma is expensive (skip)
```

### `vol_tracker.py` Regime Classification

```
CHEAP     = realized_move > breakeven × 1.2   → enter
FAIR      = 0.8× ≤ realized_move ≤ 1.2×       → neutral
EXPENSIVE = realized_move < breakeven × 0.8   → skip
UNKNOWN   = fewer than 3 observations          → pass through
```

## Known Issues Fixed to Date

| Module | Issue | Fix |
|---|---|---|
| `greeks_engine` | IV annualized with trading year (252×6.5) | Switched to calendar year (365×24×3600) — IVs were ~2.3× too low |
| `greeks_engine` | `time_to_expiry()` returned tiny positive T after close | Returns `None` after 4pm ET |
| `greeks_engine` | PEAK unreachable — speed EXIT checked before PEAK | Reordered: PEAK checked first |
| `greeks_engine` | Put speed signals inverted | Speed < 0 = ENTRY for puts (not > 0) |
| `greeks_engine` | Speed EXIT required `gamma_ratio < 0.85` | Removed — speed is leading, not lagging |
| `greeks_engine` | Charm denominator → 0 near expiry | T_charm clamped to 1-minute floor |
| `scanner` | `r = 0.05` hardcoded | Pulled from `config.RISK_FREE_RATE` |
| `scanner` | `EXPIRY` stale across midnight | `today_et()` called fresh each scan |
| `config` | Risk-free rate wrong | Updated to SOFR 3.65% |

## How to Run

```bash
# In Claude Code:
/logic-review
```

Checks all math, signal flow, and boundary conditions. Fixes Critical and Major issues automatically with mathematical justification for each change.
