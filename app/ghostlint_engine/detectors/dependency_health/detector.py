"""Dependency Health detector — unused declared packages, undeclared imports."""
from __future__ import annotations
import re
from pathlib import Path
from ghostlint_engine.detectors.base import BaseDetector
from ghostlint_engine.graph.context import AnalysisContext
from ghostlint_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)

# Packages that are tooling/dev-only and are never imported directly in code
_DEV_ONLY = {
    "pytest", "black", "ruff", "mypy", "pylint", "flake8", "isort",
    "bandit", "coverage", "pytest_asyncio", "pytest_cov", "pytest_mock",
    "hypothesis", "faker", "factory_boy", "responses", "freezegun",
    "eslint", "prettier", "jest", "ts_node", "typescript", "webpack",
    "vite", "rollup", "esbuild", "tailwindcss", "autoprefixer",
    "postcss", "sass", "less", "nodemon", "concurrently", "husky",
    "lint_staged", "commitizen", "semantic_release",
    "hatchling", "setuptools", "wheel", "build", "pip", "twine",
    "types_requests", "types_pyyaml", "types_redis", "httpx",
    # Testing libraries (imported by test runner, not source code)
    "@testing_library/react", "@testing_library/jest_dom", "@testing_library/user_event",
    "testing_library/react", "testing_library/jest_dom", "testing_library/user_event",
    "@testing_library", "testing_library",
    "web_vitals",  # Only called in reportWebVitals.js bootstrap
    # Server frameworks used implicitly / via CLI, not direct Python import
    "uvicorn", "gunicorn", "hypercorn", "daphne",
    # Python meta-packages
    "python_dotenv", "python_multipart",
}


def _norm(name: str) -> str:
    """Normalize package name: lowercase, replace -/. with _."""
    return re.sub(r"[-.]", "_", name.strip().lower().split("[")[0].split(">")[0].split("<")[0].split("=")[0].split("~")[0].split("!")[0])


def _parse_requirements_txt(path: Path) -> list[str]:
    packages = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            match = re.match(r"^([A-Za-z0-9_\-\.]+)", line)
            if match:
                packages.append(_norm(match.group(1)))
    except Exception:
        pass
    return packages


def _parse_pyproject_toml(path: Path) -> list[str]:
    packages = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        in_deps = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("dependencies = [") or stripped == "dependencies = [":
                in_deps = True
                rest = stripped[len("dependencies = ["):].strip().rstrip("]").strip()
                for item in rest.split(","):
                    item = item.strip().strip('"\'').strip()
                    if item:
                        match = re.match(r"^([A-Za-z0-9_\-\.]+)", item)
                        if match:
                            packages.append(_norm(match.group(1)))
                if "]" in stripped[len("dependencies = ["):]:
                    in_deps = False
                continue
            if in_deps:
                if stripped == "]" or stripped.startswith("]"):
                    in_deps = False
                    continue
                item = stripped.strip('",').strip("'").strip()
                if item and not item.startswith("#"):
                    match = re.match(r"^([A-Za-z0-9_\-\.]+)", item)
                    if match:
                        packages.append(_norm(match.group(1)))
    except Exception:
        pass
    return packages


def _parse_package_json(path: Path) -> list[str]:
    packages = []
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        for section in ("dependencies", "peerDependencies"):
            for name in data.get(section, {}):
                packages.append(_norm(name))
    except Exception:
        pass
    return packages


class DependencyHealthDetector(BaseDetector):
    category = DetectionCategory.DEPENDENCY_HEALTH

    def detect(self, context: AnalysisContext) -> list[Finding]:
        repo_path = Path(context.repo_path)
        findings: list[Finding] = []

        # Collect all import names from the symbol graph (kind="import")
        imported_names: set[str] = set()
        for name, refs in context.symbol_graph.references.items():
            for ref in refs:
                if ref.kind == "import":
                    normalized = _norm(name)
                    imported_names.add(normalized)
                    # Top-level module name (e.g. "os" from "os_path")
                    imported_names.add(normalized.split("_")[0])

        # Find manifest files
        manifests: list[tuple[Path, list[str]]] = []
        _skip_parts = {".venv", "venv", "node_modules", ".git", "__pycache__"}

        for req_file in repo_path.rglob("requirements*.txt"):
            if any(p in req_file.parts for p in _skip_parts):
                continue
            pkgs = _parse_requirements_txt(req_file)
            if pkgs:
                manifests.append((req_file, pkgs))

        for toml_file in repo_path.rglob("pyproject.toml"):
            if any(p in toml_file.parts for p in _skip_parts):
                continue
            pkgs = _parse_pyproject_toml(toml_file)
            if pkgs:
                manifests.append((toml_file, pkgs))

        for pkg_json in repo_path.rglob("package.json"):
            if any(p in pkg_json.parts for p in _skip_parts):
                continue
            pkgs = _parse_package_json(pkg_json)
            if pkgs:
                manifests.append((pkg_json, pkgs))

        seen: set[str] = set()
        for manifest_path, declared in manifests:
            try:
                rel_manifest = str(manifest_path.relative_to(repo_path))
            except ValueError:
                rel_manifest = str(manifest_path)

            for pkg in declared:
                if pkg in _DEV_ONLY:
                    continue
                # Check if the package or any reasonable variant is imported
                pkg_variants = {pkg, pkg.replace("_", ""), pkg.split("_")[0]}
                matched = any(
                    imp == v or imp.startswith(v) or v.startswith(imp)
                    for imp in imported_names
                    for v in pkg_variants
                    if len(v) >= 3  # avoid false matches on very short names
                )
                if not matched:
                    key = f"{rel_manifest}:{pkg}"
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(Finding(
                        category=DetectionCategory.DEPENDENCY_HEALTH,
                        title=f"Potentially unused dependency: `{pkg}`",
                        description=(
                            f"`{pkg}` is declared in `{rel_manifest}` but no matching import "
                            f"was found in the scanned source files. It may be a transitive "
                            f"dependency, used via reflection, or genuinely unused."
                        ),
                        evidence=[Evidence(
                            file_path=rel_manifest,
                            line_start=1,
                            line_end=1,
                            snippet=f"Package: {pkg}",
                        )],
                        confidence=0.7,
                        risk=RiskLevel.LOW,
                        effort=EffortLevel.MINUTES,
                        benefit="Reducing unused dependencies shrinks the install footprint and attack surface.",
                    ))

        return findings
