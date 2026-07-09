# Architectural Drift Engine

**Engine name:** `arch_drift`  
**Speed:** medium  
**Phase:** 1

## What It Detects

Violations of layered architecture conventions, including:

- **Layer boundary violations**: a lower-level layer (e.g., `utils/`) importing directly from a higher-level layer (e.g., `routes/`)
- **Cyclic dependencies**: two or more modules that mutually import each other, forming a cycle in the dependency graph
- **Layer leakage**: database/model imports appearing in API route files, or API-specific code appearing in service layers

## How It Works

1. **Layer classification**: Every file is classified into a layer based on its directory path:
   - `routes/`, `api/`, `controllers/`, `views/`, `routers/` → **API layer**
   - `services/`, `use_cases/`, `handlers/` → **Service layer**
   - `models/`, `db/`, `database/`, `repositories/`, `repo/` → **Data layer**
   - `utils/`, `helpers/`, `lib/`, `common/`, `shared/` → **Utility layer**

2. **Import extraction**: Relative imports (`from ..models import User`, `import ../db/session`) are extracted from file content using regex.

3. **Dependency graph**: A directed graph is built from file → imported file edges.

4. **Cycle detection**: NetworkX `find_cycle()` detects circular dependency chains. Each cycle is reported as a single finding listing all files in the cycle.

5. **Boundary violations**: Checks that imports flow top-down (API → Service → Data, not Data → API).

## Example Output

```
ARCH DRIFT  Cyclic dependency: auth.py → session.py → auth.py    src/db/auth.py:0       conf 85%
ARCH DRIFT  utils/db_helper.py imports from routes/api.py         src/utils/db_helper.py:0  conf 75%
```

## Limitations

- Import classification is based on directory naming conventions. Non-standard layouts (e.g., a project that puts everything flat in `src/`) may produce no findings even if there is architectural drift.
- Only relative imports are analyzed. Absolute imports within the same package require full module path resolution, which is not implemented in Phase 1.

## Running This Engine

```bash
tiramasu scan -e arch_drift
```
