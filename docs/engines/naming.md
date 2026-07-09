# Naming Consistency Engine

**Engine name:** `naming`  
**Speed:** slow  
**Phase:** 1

## What It Detects

Naming inconsistencies that signal redundant or confusingly similar abstractions:

1. **Near-duplicate class names**: Classes with model/DTO/schema suffixes (`Model`, `Schema`, `DTO`, `Entity`, `Response`, `Request`, `Payload`) where two names are very similar (Levenshtein similarity > 0.7). Example: `UserModel` and `UserEntity` in different files.

2. **Exact duplicate names across files**: The same class or function name defined in multiple different files (e.g., `UserService` defined in `src/services/user.py` and also in `src/legacy/user.py`).

## How It Works

1. Collects all class and function definitions across the repository.
2. For near-duplicate detection: filters symbols with known DTO/schema suffixes. Computes pairwise Levenshtein similarity between all name pairs in different files. Pairs above the 0.7 threshold are flagged.
3. For exact duplicates: groups symbols by name, flags any group where the same name appears in 2+ distinct files.

**Levenshtein similarity** is computed as:
```
similarity = 1 - (edit_distance / max(len(a), len(b)))
```

## Example Output

```
NAMING  Near-duplicate: UserModel (models.py) vs UserEntity (entities.py)   src/models.py:12    conf 72%
NAMING  Exact duplicate: 'parse_config' defined in 3 files                  src/utils/config.py:5  conf 80%
```

## Why This Matters

Near-duplicate class names often indicate that a codebase has accumulated multiple representations of the same concept — a `UserModel` that maps to DB rows, a `UserSchema` for validation, a `UserDTO` for API responses, and a `UserEntity` for domain logic. While these may be intentional layered representations, they can also be the result of different developers solving the same problem independently. Tiramasu surfaces them so the team can decide consciously whether each is needed.

## Tuning

Near-duplicate detection at the default 0.7 threshold can be noisy on codebases with large model layers. Raise `--min-confidence` to filter marginal pairs:

```bash
tiramasu scan -e naming --min-confidence 0.75
```

## Running This Engine

```bash
tiramasu scan -e naming
tiramasu scan -e naming --min-confidence 0.75
```

Note: This engine is marked **slow** because it computes pairwise similarity across all class names. On repos with hundreds of model classes, this can take several seconds.
