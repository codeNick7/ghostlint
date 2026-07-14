# Incomplete Refactors Engine

**Engine name:** `refactor`  
**Speed:** medium  
**Phase:** 1

## What It Detects

Code that shows signs of a migration that was started but never finished. This includes:

- **Legacy filename patterns**: files named `*_old.py`, `*_v1.py`, `*_new.py`, `*_legacy.py`, `*_deprecated.py`, `*_backup.py`
- **Versioned symbol names**: functions/classes with suffixes like `_old`, `_v1`, `_v2`, `_new`, `_legacy` that coexist with their unsuffixed counterpart
- **Verb synonym pairs**: two functions in the same codebase that do conceptually the same thing using different verbs — e.g., `get_user` and `fetch_user`, `create_order` and `add_order`, `delete_record` and `remove_record`

## How It Works

**File-level detection:** Scans all indexed file paths for legacy naming patterns using regex. Confidence: 0.80.

**Symbol-level versioning:** For every function/class with a version suffix (`_old`, `_v1`, etc.), checks if the base name also exists in the same file or codebase. If both `process_payment` and `process_payment_v2` are present, flags the pair. Confidence: 0.65.

**Verb synonym pairs:** Builds a name index across all files. For each pair of verb synonyms (get/fetch, create/add, update/modify, delete/remove, send/emit, parse/decode, validate/check, init/setup, load/read), looks for functions whose names differ only by the synonym. Confidence: 0.65.

## Example Output

```
INCOMPLETE REFACTOR  auth_old.py still present alongside auth.py         src/auth_old.py:0       conf 80%
INCOMPLETE REFACTOR  get_user / fetch_user — verb synonym pair           src/services/user.py:45  conf 65%
INCOMPLETE REFACTOR  process_payment_v2 coexists with process_payment    src/payments.py:88      conf 65%
```

## False Positives

- Some projects legitimately maintain `_v2` APIs for backwards compatibility. If the old version is intentionally kept, the finding can be suppressed by renaming to a non-legacy pattern (e.g., `process_payment_deprecated` is still flagged, but `process_payment_compat` is not).
- Verb synonyms may be intentional when both functions exist for different call sites or argument signatures. Raise `--min-confidence` to 0.7+ to filter these.

## Running This Engine

```bash
tiramisu scan -e refactor
tiramisu scan -e refactor --min-confidence 0.7
```
