# Logic Review

Run a full trading logic and quantitative correctness audit across the APEX Gamma engine.

## Steps

### 1. Greeks Engine (`greeks_engine.py`)
- Verify BS formula: d1, d2, each Greek against canonical reference
- Verify theta sign convention (must be negative for long options)
- Verify speed formula: `-(Γ/S) × (d1/(σ√T) + 1)`
- Verify vanna formula: `-N'(d1) × d2 / σ`
- Verify charm formula: canonical no-dividend form
- Verify `time_to_expiry()` returns `None` after 4pm ET, positive before
- Verify `gamma_breakeven_move` formula: `sqrt(2 × |Θ| × dt / Γ)`
- Verify IV solver shares `T` with `fair_value_bs` (no timestamp drift)

### 2. Signal Logic (`greeks_engine.gamma_arc_signal`)
- Verify ENTRY fires when `speed > 0` (calls) or `speed < 0` (puts) while slightly OTM
- Verify speed EXIT fires WITHOUT requiring `gamma_ratio < threshold` (leading indicator, not lagging)
- Verify PEAK is checked before speed EXIT (no dead-code ordering)
- Verify put speed sign convention is inverted vs calls (speed = dΓ/dS, not dΓ/d(-S))
- Verify AVOID fires when `gamma < MIN_GAMMA` regardless of other conditions
- Verify moneyness fallback ENTRY only fires when `speed is None`

### 3. Scanner (`scanner.py`)
- Verify OCC symbol parsing: `symbol[-8:]` → strike in dollars
- Verify option type detection is not fooled by digits
- Verify first-pass gamma peak uses same `r` as second pass
- Verify `None` bid/ask guarded in both passes
- Verify `today_et()` called fresh each scan (not cached EXPIRY)
- Verify market phase suppression: NO_ENTRY after 3:35, CLOSE at 3:38

### 4. Risk Manager (`risk_manager.py`)
- Verify vol regime check: EXPENSIVE blocks entry, UNKNOWN passes through
- Verify theta/gamma ratio direction: high ratio = bad (overpriced gamma)
- Verify portfolio delta uses absolute value for limit comparison
- Verify portfolio theta uses signed comparison (theta is negative)
- Verify stop-loss uses `<` not `<=` (avoid triggering on exact threshold)

### 5. Position Manager (`position_manager.py`)
- Verify `cost_basis` = entry_price × contracts × 100
- Verify `unrealized_pnl` = (current - entry) × contracts × 100
- Verify `stop_loss_breached` compares pnl/cost_basis against `MAX_LOSS_PER_POSITION_PCT`
- Verify `portfolio_greeks` sums scaled by `contracts × 100`

### 6. Vol Tracker (`vol_tracker.py`)
- Verify annualization uses calendar-year convention matching IV (365 × 24 × 3600 / interval)
- Verify `realized_move_per_interval` is in dollar terms matching `gamma_breakeven`
- Verify `vol_regime` thresholds: CHEAP ≥ 1.2×, FAIR 0.8–1.2×, EXPENSIVE < 0.8×
- Verify `is_ready()` gates all checks at fewer than 3 observations

## Output format

For each issue:
```
[SEVERITY] module:function — description of the logical error
Expected: <what it should be>
Found:    <what it actually is>
```

After the list, output:
```
── LOGIC REVIEW SUMMARY ──
Modules checked: N
Critical (wrong math/signal):  N
Major (wrong behavior):        N
Minor (edge case/improvement): N
```

Then fix all Critical and Major issues automatically. List every change made with the mathematical justification.
