# Syntax Review

Run a full syntax and code quality audit across all Python files in the project.

## Steps

1. **Parse check** — run `ast.parse()` on every `.py` file and report any `SyntaxError`
2. **Docstring placement** — flag any function/class where a non-string statement precedes the docstring
3. **Import hygiene** — flag unused imports, duplicate imports, and imports inside functions that could be top-level
4. **Bare except blocks** — flag `except Exception: pass` or `except: continue` that silently swallow errors without logging
5. **Truthy/falsy traps** — flag `if not x` on numeric values where `x == 0` is a valid state (e.g. greeks that can legitimately be 0.0)
6. **f-string / format consistency** — flag mixing of `%` formatting and f-strings in the same file
7. **Type annotation gaps** — flag public functions missing return type annotations
8. **Dead code** — flag variables assigned but never used, and unreachable `return` statements

## Output format

For each issue found, output:
```
[SEVERITY] filename.py:line_number — description
```
Severity levels: ERROR (will crash), WARNING (bad practice), INFO (style)

After the list, output a summary:
```
── SYNTAX REVIEW SUMMARY ──
Files scanned: N
Errors:   N
Warnings: N
Info:     N
```

Then fix all ERRORs and WARNINGs automatically. List every change made.
