# Test Health Engine

**Engine name:** `test_health`  
**Speed:** medium  
**Phase:** 1

## What It Detects

Orphan tests — test functions that call functions or methods which no longer exist in the main codebase. These tests pass vacuously (calling a nonexistent symbol may raise `AttributeError` or `ImportError` at runtime rather than failing the assertion) or are simply never executed.

## How It Works

1. **Test file discovery**: Finds all test files matching `test_*.py`, `*_test.py`, `*.test.js`, `*.test.ts`, `*.spec.js`, `*.spec.ts`.

2. **Symbol collection from main code**: Collects all defined function and class names from non-test source files.

3. **Call extraction from tests**: Extracts all call expressions (function names being called) from within test files.

4. **Cross-reference**: Any called name that does not exist in the main codebase symbol set is flagged as an orphan call.

## Framework Symbol Skip List

The engine skips calls that are part of standard test framework APIs to avoid false positives:

**pytest:** `assert`, `assertEqual`, `assertTrue`, `assertFalse`, `assertRaises`, `assertIn`, `assertNotIn`, `patch`, `Mock`, `MagicMock`, `fixture`, `parametrize`, `raises`, `mark`, `skip`, `fail`, `setup`, `teardown`, `setUp`, `tearDown`

**Jest/Mocha/Playwright:** `describe`, `it`, `expect`, `beforeEach`, `afterEach`, `beforeAll`, `afterAll`, `test`, `jest`, `vi`, `cy`, `page`, `browser`, `context`, `render`, `screen`, `fireEvent`, `waitFor`, `userEvent`, `getByText`, `getByRole`, `queryByText`

## Example Output

```
TEST HEALTH  test calls 'process_legacy_order' which no longer exists   tests/test_orders.py:88   conf 70%
TEST HEALTH  test calls 'validate_v1_schema' not found in codebase      tests/test_schema.py:34   conf 70%
```

## Limitations

- The engine compares symbol **names** only, not full module paths. If the same function name exists in multiple files, the test will not be flagged even if the specific function being tested was removed.
- Dynamic calls (`getattr(obj, method_name)()`) are not tracked.
- Mocked functions (`@patch('module.func')`) may cause false positives if the real function was removed but the mock target string was not updated.

## Running This Engine

```bash
ghostlint scan -e test_health
```
