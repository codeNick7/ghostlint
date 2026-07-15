## Goal
Fix the four accuracy issues found in the verification of `report-new.txt`, and add a CLI `--output/-o` option to dump the full report to a text file (console shows progress + findings table only).

## Scope note
The scanned target is a sibling repo (`COSMOS-Observation-Planner`); all fixes go in the ghostlint tool under `app/`. No changes to the target repo.

---

## Fix 1 — Orphan test calls: JS `for…of` destructuring local vars (`test_health/detector.py`)
**Root cause:** The destructure regex `_destr` (line ~157) requires `=` after the `{…}`/`[…]`, so `for (const { scenario, query, variationIndex } of allCases)` — which is followed by `of`, not `=` — is never captured. `variationIndex`/`byScenario` then look like orphan calls.
**Fix:** Add handling for `for (const {…} of …)` / `for (const […] of …)` / `for…in` patterns (the binding is followed by `of`/`in`, not `=`). Extend the regex to also accept `of`/`in` as a terminator after the destructuring pattern, and add a dedicated `for…of`/`for…in` loop regex. Keep existing `=`-terminated behavior intact.
**Test:** New `tests/unit/test_test_health.py` — assert `variationIndex` in a `for…of` destructure is NOT flagged, while a genuine orphan call IS flagged.

## Fix 2 — Unused modules: non-import wiring (`dead_code/detector.py`)
**Root cause:** `_build_referenced_module_keys` only parses Python/JS *import statements*, and the indexer only reads `.py/.js/.jsx/.ts/.tsx`. Modules wired up via (a) Claude hook commands in `.claude/settings.local.json`, (b) `if __name__ == "__main__"` runnable scripts, or (c) `python -m app.db.seed_catalog` in `.sh`/CI files are all missed.
**Fixes (three parts):**
1. `_is_module_entry_point`: treat `.claude/hooks/` (and `.claude/` hook scripts) as dynamic/non-source paths (like the existing `scripts`/`fixtures`/`seeds` segments) — these are config-invoked, never imported.
2. `_is_module_entry_point`: when a Python file's content contains `if __name__ == "__main__"`, treat it as an entry point (runnable script). This needs the file content, so pass `content` into the check (the detector already iterates `context.files` with content).
3. New helper `_scan_non_source_module_refs(repo_path)` that reads a bounded set of config/script files (`*.sh`, `Makefile`, `Dockerfile*`, `*.yml`, `*.yaml`, `*.toml`, `*.cfg`, `*.json` — skipping node_modules/.venv/.git) and extracts module references via `python -m <dotted.path>` and `from <dotted> import`/`import <dotted>` patterns. Merge these into the `referenced` set in `_detect_unused_modules`. This generically catches deployment-script / CI invocations.
**Test:** Extend `tests/unit/test_dead_code.py` — assert a file with `if __name__ == "__main__"` is not flagged; a `.claude/hooks/x.py` is not flagged; a module referenced only via `python -m` in a `.sh` is not flagged; a genuinely unused module still is.

## Fix 3 — Possible duplicates: cross-language / same-file false positives (`refactor/detector.py`)
**Root cause:** The synonym-verb heuristic (section 3) matches `get_profile` (Python route) with `fetchProfile` (TS client) because the noun lowercases to `profile` in both. It has no language or same-file guard.
**Fix:** In the synonym loop (lines ~160-208), before emitting a finding: (a) skip when both symbols are in the same file (coexisting differently-named helpers in one file are normal), and (b) skip cross-language pairs (one Python, one JS/TS) — derive language from file extension (`.py` vs `.ts/.tsx/.js/.jsx`). Synonym-verb duplicate detection is only meaningful within the same language.
**Test:** New `tests/unit/test_refactor.py` — assert `get_profile`(.py) vs `fetchProfile`(.ts) is NOT flagged; two genuinely-duplicate same-language `get_user`/`fetch_user` ARE flagged.

## Fix 4 — Duplicate logic: misleading "X and X" title (`duplicate_logic/detector.py`)
**Root cause:** When two *different files* define a same-named helper (`_get_db` in 13 route files), the title `Duplicate logic: \`_get_db\` and \`_get_db\`` looks like a self-match. The underlying finding is correct (cross-file); only the title is confusing.
**Fix:** When `sym_a.name == sym_b.name`, emit a clearer title: ``Duplicate logic: \`{name}\` duplicated across files`` and include both file paths in the description. Keep the existing title format for the distinct-name case. (Confirmed these are genuine cross-file duplicates — the same-file guard at line 318 already excludes true self-matches.)
**Note:** I am deliberately NOT changing the 10-token fingerprint threshold — I could not verify whether the trivial `def _get_db(): return SessionLocal()` actually exceeds it (python execution was sandbox-blocked), and the report's `_get_db` entries may come from larger generator-style bodies. Changing it risks suppressing real findings.

## Feature — CLI `--output/-o` option (`main.py`, `output.py`)
**Behavior:** New option `--output PATH` / `-o PATH`. When enabled:
- **Console** shows: scan progress spinner + the score panel + the findings table (compact view). A short note confirms the file was written.
- **File** receives: the full report (score panel + breakdown table + full findings table + recommendations) — i.e. everything `print_scan_result` currently prints, redirected.
- Works with `--format json` too (JSON written to the file; console shows progress + a one-line summary).

**Implementation:**
- `output.py`: refactor `print_scan_result(result, console=None)` to accept a console (default = module console). Add `print_findings_summary(result, console=None)` for the compact console view (score panel + findings table only, no breakdown/recommendations). Add `write_json_report(result, path)`.
- `main.py scan()`: add `output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write the full report to this text file (console shows progress + findings table only).")`. After scan:
  - If `output` and not json: write full report via `print_scan_result(result, console=file_console)` where `file_console = Console(file=Path(output).open("w"), ...)`, then `print_findings_summary(result)` to terminal + note "Full report written to `<output>`".
  - If `output` and json: `write_json_report(result, output)` + terminal note.
  - Else: current behavior.
- Validate output path is writable; error cleanly if parent dir missing.

## Tests & verification
- Add the three new test files / extensions listed above; run `pytest tests/unit/` to confirm green and no regressions.
- Re-run `ghostlint scan` against `COSMOS-Observation-Planner` and diff findings vs `report-new.txt` to confirm the known false positives are gone and true positives remain:
  - orphan `variationIndex`/`byScenario` → gone
  - `.claude/hooks/*`, `init_db.py`, `seed_catalog.py` unused-module → gone
  - `get_profile`/`fetchProfile` possible-duplicate → gone
  - `_get_db` duplicates → still present, clearer titles
  - unused functions / layer violations / duplicate class names → unchanged

## Files changed
- `app/ghostlint_engine/detectors/test_health/detector.py` (Fix 1)
- `app/ghostlint_engine/detectors/dead_code/detector.py` (Fix 2)
- `app/ghostlint_engine/detectors/refactor/detector.py` (Fix 3)
- `app/ghostlint_engine/detectors/duplicate_logic/detector.py` (Fix 4)
- `app/ghostlint_cli/main.py` + `app/ghostlint_cli/output.py` (CLI feature)
- `app/tests/unit/test_dead_code.py` (extended), new `test_test_health.py`, new `test_refactor.py`