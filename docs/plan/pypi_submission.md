# PyPI Submission Plan

## Status: COMPLETE

## Gaps identified

### 1. `pyproject.toml` metadata (app/pyproject.toml)
- [x] Add `authors`
- [x] Add `license`
- [x] Add `readme` pointing to README.md
- [x] Add `classifiers`
- [x] Add `keywords`
- [ ] Add `[project.urls]` (Homepage, Repository, Issues) — skipped, URL not provided
- [x] Fix `packages` list — removed `"app"`

### 2. LICENSE file
- [x] MIT LICENSE created at repo root and copied to app/

### 3. README accessible from build root
- [x] README.md copied to app/

### 4. Build validation
- [x] `python -m build` → ghostlint-0.1.0.tar.gz + ghostlint-0.1.0-py3-none-any.whl
- [x] `twine check dist/*` → both PASSED

### 5. Package name check
- [ ] Verify "ghostlint" is not already taken on PyPI — do this before uploading

## Decisions needed from user
- License type (MIT recommended)
- Author name/email for pyproject.toml
- GitHub repo URL

## Tests: 267/267 passing ✓
