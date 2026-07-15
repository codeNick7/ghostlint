# Plan: Fix ghostlint detectors (FPs/FNs) + add TS parsing, then validate against COSMOS

## Context
The stale `report.txt` (1265 findings, 46% precision) predates several recent fixes. A fresh run of the **current** code produces **1075 findings**. After row-by-row verification, the remaining broken detectors and their root causes are precisely identified. This plan fixes each at its root cause, adds the missing TypeScript parser, and re-runs ghostlint to validate.

All Python runs use `/Users/vadirajdeshpande/workspace/ghostlint/backend/.venv/bin/python`. Baseline (before): 1075 findings.

---

## Fix 1 — Orphan test detector (224 → ~2 findings)
**File:** `backend/ghostlint_engine/detectors/test_health/detector.py`
**Root cause:** The Python/JS parsers record method calls like `datetime.utcnow()`, `Path.read_text()`, `pytest.approx()`, `obj.commit()` with `kind="call"` — identical to bare function calls `foo()`. The detector then treats these library method names as missing project functions. (129 distinct symbols: `Path`, `__file__`, `insert`, `datetime`, `approx`, etc.)

**Change:**
- In `python_parser.py` (~:129) and `js_parser.py` (~:113): tag attribute/method calls (the `attribute`/`member_expression` branch of call_expression) with `kind="attribute"` instead of `kind="call"`. Bare `foo()` calls keep `kind="call"`.
- This is safe: dead-code detection uses the symbol *graph* (`get_unreferenced()`), which builds edges from ALL refs regardless of kind (`symbol_graph.add_reference` doesn't filter by kind). Only the orphan-test detector filters on `kind == "call"`.
- In the detector: only consider `kind == "call"` refs (already does — so attribute calls now auto-excluded). Add a curated `_STDLIB_KNOWN` set (datetime, Path, json, time, logging, etc.) and require the bare call name to NOT look like a known stdlib/library module, as a second safety net. Keep the 2 genuine TPs (`_search_esa`, `_build_forecast_rows`).

## Fix 2 — Refactor "coexisting old/new" (104 → 0 findings)
**File:** `backend/ghostlint_engine/detectors/refactor/detector.py`
**Root cause:** `_SYM_LEGACY_RE.sub("", name).strip("_")` strips a *leading* underscore, so `_get_db` → `get_db`, `_table_exists` → `table_exists`. All 104 findings are one of 9 such pairs (`get_db`+`_get_db` = 58, `table_exists`+`_table_exists` = 16, etc.) — none are real version coexistence.
**Change:** Only match *trailing* version/legacy suffixes (the regex already targets suffixes; the bug is `.strip("_")`). Replace `.strip("_")` with leaving leading underscores intact, and require the suffix match to actually have changed the name by removing a real version token (not a leading underscore). Quick validation: ensure the 104 go to 0 while real `foo`/`fooV2` pairs still match.

## Fix 3 — Unused modules: exclude framework/entry-point/generated files (23 of 173 → 0)
**File:** `backend/ghostlint_engine/detectors/dead_code/detector.py` (`_is_module_entry_point`, `_MODULE_ENTRY_POINT_STEMS`)
**Change:** Add to the entry-point stem set and path checks:
- Next.js App Router convention files: `robots`, `sitemap`, `manifest`, `icon`, `apple-icon`, `opengraph-image`, `twitter-image` (under an `app/` dir).
- Framework-generated: `next-env.d.ts`, `_buildManifest.js`, `_ssgManifest.js`, `cordova.js`, `cordova_plugins.js` (match by stem in a `_GENERATED_STEMS` set, or by path containing `public/_next/` or `public/cordova`).
- Standalone analysis/test scripts: treat `global-setup`, `global-teardown`, `analyze-*`, `playwright.config`, `capacitor.config`, `*.config.{ts,js}` as entry points.
- Template files: any path containing `/templates/`.
- Alembic `env.py` is already handled by the `env` ... actually add `env` stem OR keep it via the alembic `alembic/` dynamic segment (env.py sits at `backend/alembic/env.py` — add `alembic` is already in dynamic segments, but env.py is at the alembic root, not versions/. Add `env` to stems).
The remaining ~150 unused modules are real TPs (dead UI components, superseded assistants) and stay.

## Fix 4 — Stale comment detector (17 → ~0-2 findings)
**File:** `backend/ghostlint_engine/detectors/doc_health/detector.py`
**Root cause:** Regex `#.*?\b(TODO|...|TEMP|...|BUG|...)\b` matches the words "temp" (temperature), "bug" inside prose/FAQ text, and TODOs baked into minified build artifacts.
**Change:**
- Require the marker at (or near) the *start* of the comment, e.g. `#\s*(TODO|FIXME|HACK|XXX|BUG)\b` and `//\s*(TODO|...)` — a leading-word match, not substring-after-arbitrary-text. This drops "temp"/"bug" inside prose (they never start a comment with the marker).
- Drop `TEMP`/`REMOVEME`/`NOCOMMIT` from the stale set (they're not stale-marker conventions; TEMP matches "temperature"). Keep TODO/FIXME/HACK/XXX/BUG only when comment-leading.
- Exclude build-artifact dirs: reuse `indexer.EXCLUDE_DIRS` to skip files under `_next/`, `public/`, `dist/`, `out/` etc. (these are already excluded from indexing, but the doc detector iterates `context.files` which is post-exclusion — confirm `_next` is gone; if mobile `public/` assets remain indexed, add an explicit path skip).

## Fix 5 — Config consistency (60 findings → ~0-5 findings)
**File:** `backend/ghostlint_engine/detectors/config_health/detector.py`
**Root cause (3 sub-checks):**
- *Conflicting value (8)*: still compares values across different env files; per-env differences are intended.
- *Required key missing (45)*: all 45 point at `.env.prod.template:1` — the "live" key resolution picks the template as `live_key` when no real `.env` is found at repo root (the real `backend/.env` IS present but the matcher `k.endswith("/.env") or k == ".env"` should catch `backend/.env` — verify; likely the issue is it compares against the template regardless).
- *Secret key missing (7)*: flags non-secret config (`COMPANY_NAME`, `SITE_NAME`, URLs) and misses that they're already in the example.
**Change:**
- *Conflicting*: only flag a value conflict when the SAME key appears 2+ times within ONE env file with different values (a real internal contradiction), not across files. This is the only genuine config conflict.
- *Required missing / Secret missing*: restrict the live↔example comparison to a SINGLE canonical live/example pair per directory (not cross-directory), and only emit "secret missing" for keys that match a secret-like pattern (`*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `API_KEY`, etc.) — not `COMPANY_NAME`. Skip keys already present in the example. Expected: drops to ~0.

## Fix 6 — Near-duplicate names (6 → 0 findings)
**File:** `backend/ghostlint_engine/detectors/naming/detector.py`
**Root cause:** Flags Request/Response and Create/Update pairs as "near-duplicate" — these are intentional, non-confusing API conventions.
**Change:** In the near-duplicate check, skip a pair if their stripped stems are equal (e.g. `ChatRequest`→`chat`, `ChatResponse`→`chat`: equal → skip) OR they form a known complementary suffix pair (`Request`/`Response`, `Input`/`Output`, `Create`/`Update`, `Req`/`Resp`). Already-reported exact-duplicate-class check (5 TPs) stays untouched.

## Fix 7 — Duplicate logic: reduce false positives (38 → ~0; reduce trivial-boilerplate noise)
**File:** `backend/ghostlint_engine/detectors/duplicate_logic/detector.py`
**Change:**
- Raise the minimum body-token threshold (`len(tokens) < 5` → e.g. `< 10`) so 1–2 line boilerplate (`def _get_db(): return SessionLocal()`) isn't fingerprinted. This drops most of the 26 `_get_db` copies and the 12 `_get_db`+`nasa_apod` shape FPs from the duplicate set.
- Skip abstract-method implementations: if a method overrides an `@abstractmethod` parent (base class in `_ENTRY_BASE_CLASSES` / ABC), don't fingerprint it. Drops the 22 `applies_to`/`apply` rules-engine FPs.
- Skip thin delegator wrappers (single `return X(...)` body that calls a same-named symbol) — drops the 4 `get_target_cities` FPs.

## Fix 8 — Add TypeScript/TSX parsing (enables accurate TS analysis)
**Files:** `backend/pyproject.toml` (add dep), `backend/ghostlint_engine/ast_engine/ts_parser.py` (new), `backend/ghostlint_engine/ast_engine/__init__.py` (register).
**Change:**
- Add `tree-sitter-typescript` dependency; install via `.venv/bin/pip install tree-sitter-typescript`.
- Create `TSParser` mirroring `JSParser` (TSX uses near-identical node types). Build two language objects: `language_typescript()` for `.ts`, `language_tsx()` for `.tsx`.
- Register `"typescript"` → parser in `PARSERS` so `.ts/.tsx` files are now parsed for defs/refs (they were indexed but skipped — `scanner.py:72` returned `parser=None`).
- Reuse the JS parser's `_walk_definitions`/`_walk_references` node-type handling (TS is a superset). This makes dead-code, naming, duplicate-logic, and arch-drift work on TSX for the first time. Note: this may surface NEW true positives (e.g. unused TS components) and is expected.

---

## Validation (final step)
1. Re-run: `backend/.venv/bin/python -m ghostlint_cli.main scan ~/workspace/COSMOS-Observation-Planner --format json > /tmp/baseline_after.json`
2. Compare category counts before (1075) vs after. Expected drops:
   - orphan_test: 224 → ~2
   - refactor old/new: 104 → 0
   - stale_comment: 17 → ~0
   - required_key_missing: 45 → ~0
   - secret_key_missing: 7 → ~0
   - conflicting_config: 8 → ~0
   - near_duplicate: 6 → 0
   - unused_module: 173 → ~150 (−23 entry points)
   - duplicate_logic: 388 → lower (FPs + trivial boilerplate removed)
   - unused_function: 89 → may rise slightly as TS parsing adds refs (net likely down)
3. Spot-check the remaining findings to confirm the 2 genuine orphan-test TPs and the 5 duplicate-class TPs are preserved.
4. Confirm no detector crashes (currently swallowed silently at `scanner.py:106`).
5. Update `backend/report_analysis.md` with the before/after numbers.

## Scope / non-goals
- NOT deleting any code in the COSMOS project itself — only fixing the ghostlint tool.
- NOT touching the genuinely-accurate detectors beyond FP removal (duplicate class names, layer violations stay).
- The duplicate_logic detector stays focused on FP removal + boilerplate threshold per your direction; we are not rewriting it.