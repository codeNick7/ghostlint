"""Config Health detector — .env key conflicts and missing required keys."""
from __future__ import annotations
from pathlib import Path
from tiramasu_engine.detectors.base import BaseDetector
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file returning {KEY: VALUE} (skips comments and blank lines)."""
    result: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip().strip('"\'')
                if key:
                    result[key] = value
    except Exception:
        pass
    return result


_SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__"}


class ConfigHealthDetector(BaseDetector):
    category = DetectionCategory.CONFIG_HEALTH

    def detect(self, context: AnalysisContext) -> list[Finding]:
        repo_path = Path(context.repo_path)
        findings: list[Finding] = []

        # Find all .env* files
        env_files: dict[str, dict[str, str]] = {}
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

        if len(env_files) < 2:
            return findings

        # Prefer .env as the "live" config and .env.example as the "template"
        live_key = next((k for k in env_files if k.endswith("/.env") or k == ".env"), None)
        example_key = next(
            (k for k in env_files if "example" in k or "sample" in k or "template" in k), None
        )

        if live_key and example_key:
            live_keys = set(env_files[live_key])
            example_keys = set(env_files[example_key])

            # Keys in live but NOT in example → potential secret leak risk
            secret_keys = live_keys - example_keys
            for key in sorted(secret_keys):
                findings.append(Finding(
                    category=DetectionCategory.CONFIG_HEALTH,
                    title=f"Secret key `{key}` missing from example config",
                    description=(
                        f"`{key}` is present in `{live_key}` but absent from `{example_key}`. "
                        f"This may indicate a secret or credential not documented for other developers. "
                        f"Add a placeholder to the example file."
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
                    benefit="Ensures all required env vars are documented for new developers.",
                ))

            # Keys in example but NOT in live → missing required config
            missing_keys = example_keys - live_keys
            for key in sorted(missing_keys):
                findings.append(Finding(
                    category=DetectionCategory.CONFIG_HEALTH,
                    title=f"Required key `{key}` missing from live config",
                    description=(
                        f"`{key}` is documented in `{example_key}` as required but is absent "
                        f"from `{live_key}`. The application may fail at runtime."
                    ),
                    evidence=[Evidence(
                        file_path=example_key,
                        line_start=1,
                        line_end=1,
                        snippet=f"{key}=<required>",
                    )],
                    confidence=0.8,
                    risk=RiskLevel.HIGH,
                    effort=EffortLevel.MINUTES,
                    benefit="Prevents runtime failures due to missing configuration.",
                ))

        # Check for conflicting values across all env files (same key, different structural type)
        all_env_list = list(env_files.items())
        checked: set[tuple[str, str, str]] = set()
        for i, (path_a, keys_a) in enumerate(all_env_list):
            for j, (path_b, keys_b) in enumerate(all_env_list):
                if i >= j:
                    continue
                # Skip live vs example (already handled)
                if {path_a, path_b} == {live_key, example_key}:
                    continue
                for key in set(keys_a) & set(keys_b):
                    val_a = keys_a[key]
                    val_b = keys_b[key]
                    # Flag only if values differ substantially and aren't empty
                    if val_a and val_b and val_a != val_b:
                        check_key = tuple(sorted([path_a, path_b]) + [key])
                        if check_key in checked:
                            continue
                        checked.add(check_key)
                        findings.append(Finding(
                            category=DetectionCategory.CONFIG_HEALTH,
                            title=f"Conflicting value for `{key}` across env files",
                            description=(
                                f"`{key}` has different values in `{path_a}` ({val_a!r}) "
                                f"and `{path_b}` ({val_b!r}). Ensure this is intentional."
                            ),
                            evidence=[
                                Evidence(file_path=path_a, line_start=1, line_end=1,
                                         snippet=f"{key}={val_a}"),
                                Evidence(file_path=path_b, line_start=1, line_end=1,
                                         snippet=f"{key}={val_b}"),
                            ],
                            confidence=0.65,
                            risk=RiskLevel.MEDIUM,
                            effort=EffortLevel.MINUTES,
                            benefit="Consistent configuration reduces environment-specific bugs.",
                        ))

        return findings
