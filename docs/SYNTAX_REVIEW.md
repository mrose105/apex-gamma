# Syntax Review — APEX Gamma

## What It Checks

The `/syntax-review` command audits every `.py` file for:

| Category | What's Checked |
|---|---|
| **Parse errors** | `ast.parse()` on every file — catches any unrunnable code |
| **Docstring placement** | Docstring must be first statement in function/class |
| **Import hygiene** | Unused imports, duplicates, imports inside functions |
| **Silent exception swallowing** | `except: pass` or `except: continue` without logging |
| **Truthy/falsy traps** | `if not x` on floats where 0.0 is a valid value (e.g. Greeks) |
| **Dead code** | Assigned-but-never-used variables, unreachable returns |
| **Type annotations** | Public functions missing return type |

## Severity Levels

- **ERROR** — code will crash or produce wrong output. Fixed automatically.
- **WARNING** — bad practice that will cause silent bugs. Fixed automatically.
- **INFO** — style or consistency issue. Reported but not auto-fixed.

## Known Issues Fixed to Date

| File | Issue | Fix |
|---|---|---|
| `scanner.py` | Docstring after `if r is None` guard | Moved docstring to first line |
| `greeks_engine.py` | `if T <= 0` didn't handle `None` return | Added `T is None` check |
| `greeks_engine.py` | `total_day` unused variable | Removed |
| `greeks_engine.py` | `.seconds` instead of `.total_seconds()` | Fixed |
| `scanner.py` | Raw `q.bid_price + q.ask_price` in first pass | Added `or 0` guard |

## How to Run

```bash
# In Claude Code:
/syntax-review
```

Scans all `.py` files in the current working directory, reports issues, fixes ERRORs and WARNINGs.
