# Dead Code Engine

**Engine name:** `dead_code`  
**Speed:** fast  
**Phase:** 1

## What It Detects

Functions, methods, and classes that have zero callers anywhere in the repository. These symbols are defined but never invoked — they consume cognitive overhead, inflate test surface, and can silently diverge from the rest of the codebase as it evolves.

## How It Works

1. Parses every Python and JavaScript/TypeScript file using tree-sitter AST parsers.
2. Builds a symbol definition graph: each function, class, and arrow function gets a node.
3. Collects all references (call expressions, imports, JSX component usage).
4. Uses **two-pass resolution**: all definitions are registered first, then all references are linked. This prevents false positives when file A imports a symbol from file B that is parsed later alphabetically.
5. Any symbol with `in_degree == 0` (no incoming edges) is a dead-code candidate.
6. A confidence score is computed based on symbol type and naming.

## Confidence Scoring

| Factor | Adjustment |
|---|---|
| Base score | +0.50 |
| Private name (`_foo`) | +0.30 |
| Plain function (no decorator) | +0.15 |
| Arrow function | +0.10 |
| Method (likely called via `self`) | −0.15 |
| Class definition | −0.10 |

Only findings at or above the `--min-confidence` threshold (default 0.6) are reported.

## What It Skips (Entry Points)

The engine automatically skips symbols that are idiomatic entry points and cannot be detected as callers via static analysis:

- Common entry-point names: `main`, `run`, `start`, `init`, `setup`, `teardown`, `handler`, `lambda_handler`, `create_app`, `application`
- Test functions: any name starting with `test_`
- Dunder methods: `__init__`, `__str__`, `__repr__`, etc.
- Framework decorators: `@app.route`, `@router.get`, `@router.post`, `@app.get`, `@pytest.fixture`, `@celery.task`, `@property`, `@staticmethod`, `@classmethod`, `@click.command`, `@asynccontextmanager`

## Example Output

```
DEAD CODE  _format_legacy_response   src/utils/response.py:142   conf 82%  risk medium
```

## False Positives

A symbol may be incorrectly flagged as dead if:

- It is called via `getattr()` or dynamic dispatch (the engine does not evaluate runtime attribute access).
- It is exported and used by an external package that is not in this repository.
- It is a callback registered by string name in a framework config (e.g., Django `urlpatterns`).

To suppress a finding, rename the function with a framework-recognized decorator or add it to the entry-point list in a future `tiramisu.yml` config.

## Running This Engine

```bash
tiramisu scan -e dead_code
tiramisu scan -e dead_code --min-confidence 0.75
tiramisu scan -e dead_code --changed       # only files changed vs HEAD
tiramisu scan --quick                      # dead_code is included in --quick
```
