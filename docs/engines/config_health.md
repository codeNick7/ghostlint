# Configuration Health Engine

**Engine name:** `config_health`  
**Speed:** fast  
**Phase:** 1

## What It Detects

Drift and inconsistency across `.env` configuration files:

- **Secret leak risk**: keys that are present in `.env` (which may contain real credentials) but missing from `.env.example` (the template that should be committed to version control). If `.env.example` doesn't list it, contributors won't know the key exists.
- **Missing configuration**: keys defined in `.env.example` that are absent from the actual `.env`. The running application may be missing required config values.

## How It Works

1. Finds all `.env*` files in the repository root and subdirectories (`.env`, `.env.example`, `.env.local`, `.env.production`, etc.).
2. Parses each file line-by-line, extracting `KEY=VALUE` pairs (ignoring comments and blank lines).
3. Compares `.env` against `.env.example`:
   - Keys in `.env` but not in `.env.example` → **secret leak risk** (confidence 0.8)
   - Keys in `.env.example` but not in `.env` → **missing config** (confidence 0.7)

## Example Output

```
CONFIG HEALTH  STRIPE_SECRET_KEY in .env but missing from .env.example   .env:14   conf 80%  risk high
CONFIG HEALTH  REDIS_URL defined in .env.example but missing from .env    .env.example:8  conf 70%  risk medium
```

## Why This Matters

`.env` files containing real API keys and database passwords are frequently committed to version control by accident. Keeping `.env.example` in sync with `.env` ensures:

1. New developers know what environment variables to set.
2. Secret keys are not silently omitted from the documented interface.
3. The application does not start with missing required configuration.

## Running This Engine

```bash
ghostlint scan -e config_health
ghostlint scan --quick   # config_health is included in --quick (fast engine)
```
