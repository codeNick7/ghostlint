# Documentation Health Engine

**Engine name:** `doc_health`  
**Speed:** medium  
**Phase:** 1

## What It Detects

Stale inline annotations that signal deferred or abandoned work:

- `TODO` — work that was planned but not done
- `FIXME` — known bugs left unresolved
- `HACK` — workarounds that need to be revisited
- `XXX` — urgent concerns that need attention
- `TEMP` / `TEMPORARY` — code intended to be removed
- `REMOVEME` — explicit removal markers

## How It Works

1. Reads every indexed source file.
2. Scans each line with a case-insensitive regex for the above keywords in comment syntax (`#`, `//`, `/*`, `*`).
3. Reports the file path, line number, and the comment text.
4. Capped at **5 findings per file** to avoid flooding the report in heavily commented legacy files.

All findings have confidence 0.6 and risk `low` — these are informational flags, not bugs.

## Example Output

```
DOC HEALTH  TODO: remove after migration to v2 API          src/api/legacy.py:204   conf 60%  risk low
DOC HEALTH  FIXME: this breaks on leap years                src/utils/dates.py:88   conf 60%  risk low
DOC HEALTH  HACK: workaround for library bug #4521          src/db/session.py:17    conf 60%  risk low
```

## Interpreting Results

A high number of `TODO`/`FIXME` comments is a signal that technical debt is accumulating. Unlike linters, tiramisu tracks these across the entire repository and surfaces them in a health score that can trigger CI gates.

The health score impact of doc_health findings is intentionally small — a few TODOs shouldn't fail a build. Use `--min-confidence` to suppress doc_health findings entirely if desired:

```bash
tiramisu scan --min-confidence 0.65   # doc_health findings (conf 0.6) will be filtered out
```

## Running This Engine

```bash
tiramisu scan -e doc_health
tiramisu scan -e doc_health --min-confidence 0.65   # suppress doc findings, keep others
```
