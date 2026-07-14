"""Config Health detector — .env key conflicts and missing required keys.

Design principles (revised):
- **Never compare values across different env files.** Separate files exist
  precisely so each environment can differ (.env.local vs .env.prod.template vs
  web/.env vs backend/.env). A value differing across files is intended, not a
  defect.
- A genuine config conflict is an *internal* contradiction: the SAME key defined
  two+ times within ONE file with different values (last-write-wins surprises).
- "Required key missing" compares a live config against its example template
  *within the same directory* only, and only when both exist. It does not report
  against a template in a different directory.
- "Secret key missing" only fires for keys whose name looks like a secret
  (*_KEY, *_TOKEN, *_SECRET, *_PASSWORD, API_KEY, ...), never for ordinary
  config like COMPANY_NAME or a backend URL.
"""
from __future__ import annotations
import re
from pathlib import Path
from tiramisu_engine.detectors.base import BaseDetector
from tiramisu_engine.graph.context import AnalysisContext
from tiramisu_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)


def _parse_env_file(path: Path) -> dict[str, list[tuple[str, int]]]:
    """Parse a .env file returning {KEY: [(value, line_no), ...]}.

    Multiple definitions of the same key are preserved (each with its line
    number) so intra-file contradictions can be detected. Comments/blank lines
    are skipped.
    """
    result: dict[str, list[tuple[str, int]]] = {}
    try:
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip().strip('"\'')
                if key:
                    result.setdefault(key, []).append((value, lineno))
    except Exception:
        pass
    return result


_SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__"}

# Key-name patterns that indicate a genuine secret/credential.
_SECRET_KEY_RE = re.compile(
    r"(API_KEY|API_SECRET|ACCESS_TOKEN|ACCESS_SECRET|SECRET|PASSWORD|PASSWD|"
    r"PRIVATE_KEY|CLIENT_SECRET|JWT_SECRET|SIGNING_KEY|CREDENTIAL|AUTH_TOKEN|"
    r"REVALIDATION_SECRET|SERVICE_KEY)$",
    re.IGNORECASE,
)

# Keys that are NOT secrets even if they contain "KEY"/"SECRET" substrings —
# e.g. NEXT_PUBLIC_* is public-by-convention, ANON_KEY is a public anon key.
_PUBLIC_KEY_RE = re.compile(r"^(NEXT_PUBLIC_|PUBLIC_|ANONYMOUS_)", re.IGNORECASE)


def _is_secret_key(key: str) -> bool:
    if _PUBLIC_KEY_RE.match(key):
        return False
    return bool(_SECRET_KEY_RE.search(key))


class ConfigHealthDetector(BaseDetector):
    category = DetectionCategory.CONFIG_HEALTH

    def detect(self, context: AnalysisContext) -> list[Finding]:
        repo_path = Path(context.repo_path)
        findings: list[Finding] = []

        # Find all .env* files (relative path -> parsed {key: [(value,line)]})
        env_files: dict[str, dict[str, list[tuple[str, int]]]] = {}
        for env_path in repo_path.rglob(".env*"):
            if not env_path.is_file():
                continue
            if any(p in env_path.parts for p in _SKIP_PARTS):
                continue
            try:
                rel = str(env_path.relative_to(repo_path))
            except ValueError:
                rel = str(env_path)
            parsed = _parse_env_file(env_path)
            if parsed:
                env_files[rel] = parsed

        if len(env_files) < 1:
            return findings

        # 1. Intra-file contradictions: the SAME key defined 2+ times in ONE
        #    file with different values. This is the only genuine "conflicting
        #    value" — it causes last-write-wins surprises. We never compare
        #    across files (per-env differences are intended).
        for rel, kv in env_files.items():
            for key, occurrences in kv.items():
                if len(occurrences) < 2:
                    continue
                unique_values = {v for v, _ in occurrences}
                if len(unique_values) <= 1:
                    continue  # same value repeated — harmless
                lines = [ln for _, ln in occurrences]
                evidence = [
                    Evidence(file_path=rel, line_start=ln, line_end=ln, snippet=f"{key}={v}")
                    for v, ln in occurrences
                ]
                findings.append(Finding(
                    category=DetectionCategory.CONFIG_HEALTH,
                    title=f"Conflicting value for `{key}` in `{rel}`",
                    description=(
                        f"`{key}` is defined {len(occurrences)} times in `{rel}` "
                        f"with different values (lines {', '.join(str(l) for l in lines)}). "
                        f"Only the last definition takes effect — consolidate to a single value."
                    ),
                    evidence=evidence,
                    confidence=0.85,
                    risk=RiskLevel.MEDIUM,
                    effort=EffortLevel.MINUTES,
                    benefit="Prevents last-write-wins config surprises within a single environment.",
                ))

        # 2. Per-directory live↔example comparison.
        #    Group env files by their parent directory, and within each directory
        #    compare a single live config against its example template. This avoids
        #    cross-directory false positives (e.g. backend/.env vs web/.env.example).
        by_dir: dict[str, dict[str, dict[str, list[tuple[str, int]]]]] = {}
        for rel, kv in env_files.items():
            parent = str(Path(rel).parent)
            by_dir.setdefault(parent, {})[rel] = kv

        for dir_path, dir_envs in by_dir.items():
            # Pair each live config with its matching example template by name
            # correspondence: ".env" ↔ ".env.example", ".env.local" ↔
            # ".env.local.example", ".env.mobile" ↔ ".env.mobile.example".
            # This avoids the false positive where ".env" gets paired with the
            # minimal ".env.local.example" (which only documents overrides).
            for live_key, example_key in self._pair_live_example(sorted(dir_envs)):
                if not live_key or not example_key:
                    continue

                live_kv = {k: [v for v, _ in occ] for k, occ in dir_envs[live_key].items()}
                example_keys = set(dir_envs[example_key].keys())

                # Secrets in live but absent from example → undocumented secret
                for key in sorted(set(live_kv) - example_keys):
                    if not _is_secret_key(key):
                        continue  # not a secret — documenting it is optional
                    findings.append(Finding(
                        category=DetectionCategory.CONFIG_HEALTH,
                        title=f"Secret key `{key}` missing from example config",
                        description=(
                            f"`{key}` looks like a secret/credential present in `{live_key}` "
                            f"but absent from `{example_key}`. Add a placeholder so other "
                            f"developers know it is required."
                        ),
                        evidence=[Evidence(
                            file_path=live_key,
                            line_start=1,
                            line_end=1,
                            snippet=f"{key}=<redacted>",
                        )],
                        confidence=0.75,
                        risk=RiskLevel.MEDIUM,
                        effort=EffortLevel.MINUTES,
                        benefit="Documents required secrets for new developers without leaking values.",
                    ))

        return findings

    @staticmethod
    def _pair_live_example(env_paths: list[str]) -> list[tuple[str | None, str | None]]:
        """Pair each live .env file with its matching example template.

        Pairing is by name correspondence: ".env" ↔ ".env.example",
        ".env.local" ↔ ".env.local.example". A live file with no matching
        example, or an example with no live file, is skipped. This avoids the
        false positive where ".env" gets paired with ".env.local.example"
        (a minimal override template for a different file).
        """
        _EXAMPLE_SUFFIXES = (".example", ".sample", ".template")
        # Build a lookup from a live base-name to its full example path.
        # ".env.local.example" → live base ".env.local", example marker ".example"
        examples_by_base: dict[str, str] = {}
        for rel in env_paths:
            name = Path(rel).name
            for suf in _EXAMPLE_SUFFIXES:
                if name.endswith(suf):
                    base = name[: -len(suf)]  # ".env.local"
                    examples_by_base[base] = rel
                    break
        pairs: list[tuple[str | None, str | None]] = []
        for rel in env_paths:
            name = Path(rel).name
            if any(name.endswith(suf) for suf in _EXAMPLE_SUFFIXES):
                continue  # this is an example, not a live file
            example = examples_by_base.get(name)
            if example:
                pairs.append((rel, example))
        return pairs
