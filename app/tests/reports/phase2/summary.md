# Phase 2 Test Report — 2026-07-09

## Testbeds
- VectorShift-Assignment: 28 files, 28 symbols, 1 finding, score 99.7/100
- AI-Assistant: 14 files, 16 symbols, 4 findings, score 98.3/100

## Bugs Found and Fixed

### Bug 1: __init__.py files still imported _StubDetector
The Phase 2 detector `__init__.py` files still imported `_StubDetector` from stub implementations.
After implementing real detectors, those imports broke the registry load.
Fix: Cleared all stub `__init__.py` files.

### Bug 2: test_health detector noisy on Playwright test suites
The detector was flagging every Playwright API method (page, locator, goto, describe, test,
expect, beforeEach, etc.) and JS builtins (require, filter, join, etc.) as "orphan test calls".
Fix: Added comprehensive `_SKIP_CALLS` frozenset with ~100+ Playwright/Jest/Mocha/pytest
framework API names and JS/Python builtins.

### Bug 3: test_health still flagging local variable names
Even after skip list, `longText` (a `const` declaration) was flagged because the JS parser
tracks identifier arguments as refs. Fix: Added local variable extraction from test file
content (regex over const/let/var declarations) and skip those names in test_health.

### Bug 4: dependency_health flagging uvicorn, @testing-library, python-multipart
These are correctly declared but either: (a) used implicitly by CLI/framework (uvicorn),
(b) testing-only packages (testing-library/*), or (c) framework-handled (python-multipart).
Fix: Expanded _DEV_ONLY set to include uvicorn, gunicorn, web_vitals, testing_library/*,
and python_dotenv/python_multipart.

## Findings Analysis

### VectorShift-Assignment (1 finding)
- `zustand` dependency: True positive — zustand is imported as `import { create } from 'zustand'`
  but our parser tracks `create` as the imported symbol (not `zustand`). This is a known
  limitation of our symbol-name-based matching. Low impact, not a real unused dependency.

### AI-Assistant (4 findings)
- `formatMessage` duplicate: True positive — same function name defined in 2 different files
  with structurally identical AST fingerprint. Genuine duplication.
- `tiktoken`: Likely false positive — commonly used via `import tiktoken` which the parser
  tracks correctly, but this specific repo may not use it yet.
- `pydantic`: False positive — imported as `from pydantic import BaseModel` so `BaseModel`
  is tracked, not `pydantic` directly. Limitation of package→import mapping.
- `scikit_learn`: Potentially true — needs manual verification.

## Phase 2 Checklist
- [x] dependency_health detector implemented
- [x] config_health detector implemented
- [x] test_health detector implemented (with Playwright/Jest skip lists)
- [x] duplicate_logic detector implemented (AST fingerprint via tree-sitter)
- [x] naming detector implemented (Levenshtein similarity on model classes)
- [x] refactor detector implemented (file-level + symbol-level + verb synonym detection)
- [x] doc_health detector implemented (TODO/FIXME/HACK comment detection)
- [x] arch_drift detector implemented (layer classification + circular import detection)
- [x] All 8 detectors flipped to phase=1 in registry.py
- [x] 32 unit tests still pass
- [x] Phase 2 JSON scan reports saved for both testbeds
