# Duplicate Logic Engine

**Engine name:** `duplicate_logic`  
**Speed:** slow  
**Phase:** 1

## What It Detects

Functions across different files that have structurally identical implementations. Unlike text-similarity tools (which catch copy-paste), this engine uses **AST structural fingerprinting** — it ignores variable names and literal values and compares only the shape of the code. Two functions that compute the same algorithm with differently named variables will be flagged.

## How It Works

1. Collects all function definitions (Python: `def`, JS: `function` declarations, arrow functions, methods).
2. For each function, performs a DFS traversal of its AST and records the sequence of **node types** — ignoring identifiers, literals, and comments.
3. The resulting sequence is the function's structural fingerprint.
4. Groups functions by fingerprint. Any group with 2+ members from **different files** is a duplicate cluster.
5. Reports one finding per cluster with all locations listed.

## Confidence

Fixed at **0.75** for structural matches — high confidence that the logic is identical in structure, even if names differ.

## Example

These two functions produce the same fingerprint:

```python
# file: orders.py
def calculate_tax(price, rate):
    if price > 0:
        return price * rate
    return 0.0

# file: invoices.py
def compute_fee(amount, multiplier):
    if amount > 0:
        return amount * multiplier
    return 0.0
```

## Output

```
DUPLICATE LOGIC  calculate_tax / compute_fee   src/orders.py:14  src/invoices.py:88   conf 75%
```

## What It Skips

- Functions within the **same file** (intra-file duplicates — often intentional overloads or slight variants).
- Very short functions (fewer than ~3 AST node types) — too small to be meaningful duplicates.

## False Positives

Some structural patterns are genuinely common boilerplate (e.g., a null-check guard followed by a return). The engine may flag these as duplicates even though the intent is different. Raise `--min-confidence` to filter marginal cases.

## Running This Engine

```bash
tiramisu scan -e duplicate_logic
tiramisu scan -e duplicate_logic --min-confidence 0.8
```

Note: This engine is marked **slow** because it compares all pairs of parsed functions. On large repos (1000+ files) it may take 20–60 seconds.
