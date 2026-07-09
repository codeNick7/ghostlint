# Dependency Health Engine

**Engine name:** `dependency_health`  
**Speed:** fast  
**Phase:** 1

## What It Detects

Package dependencies that are declared but never actually used in source code:

- Dependencies listed in `requirements.txt`, `pyproject.toml` `[project.dependencies]`, or `package.json` `dependencies`/`devDependencies`
- Cross-referenced against actual import statements in source files
- Any declared dependency that has no matching import is flagged as potentially unused

## How It Works

1. **Dependency extraction**: Reads declared packages from:
   - `requirements.txt` (one package per line, strips version pins)
   - `pyproject.toml` `[project] dependencies` array
   - `package.json` `dependencies` and `devDependencies`

2. **Import extraction**: Collects all import names from indexed Python files (`import X`, `from X import Y`) and JS/TS files (`import ... from 'X'`, `require('X')`).

3. **Name normalization**: Normalizes package names (e.g., `python-dotenv` → `dotenv`, `Pillow` → `PIL`) to match how packages are actually imported vs. how they are declared.

4. **Comparison**: Any declared package not found in any import is flagged.

## Dev-Only Skip List

Packages that are commonly used only at dev/runtime and never imported directly are skipped:

`uvicorn`, `gunicorn`, `pytest`, `pytest-asyncio`, `black`, `ruff`, `mypy`, `pre-commit`, `ipython`, `notebook`, `wheel`, `setuptools`, `pip`, `build`, `twine`

## Confidence

Fixed at **0.7** per unused dependency — high enough to surface, low enough to acknowledge that some packages are used indirectly (transitive imports, CLI tools, etc.).

## Example Output

```
DEPENDENCY HEALTH  'celery' declared in requirements.txt but never imported   requirements.txt:24  conf 70%
DEPENDENCY HEALTH  'boto3' in package.json but no JS import found             package.json:11      conf 70%
```

## False Positives

- Packages used as command-line tools (e.g., `black`, `ruff`) are in the skip list but some tool-only deps may slip through.
- Packages with non-obvious import names (e.g., `Pillow` is imported as `PIL`, `python-dateutil` as `dateutil`) — the engine normalizes common ones but may miss edge cases.
- Packages imported conditionally with `try/except ImportError` (e.g., optional extras) will be flagged even though they are legitimately used.

## Running This Engine

```bash
tiramasu scan -e dependency_health
tiramasu scan --quick   # dependency_health is included in --quick (fast engine)
```
