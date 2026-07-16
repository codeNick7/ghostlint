from __future__ import annotations
import fnmatch
import hashlib
from dataclasses import dataclass
from pathlib import Path

LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

EXCLUDE_DIRS: set[str] = {
    # ── VCS ──────────────────────────────────────────────────────────────────
    ".git", ".svn", ".hg",

    # ── Python virtualenvs & caches ──────────────────────────────────────────
    # Named-venv directories (common conventions)
    ".venv", "venv", "env", ".env",
    "virtualenv", ".virtualenv",
    # Safety net: catches any venv regardless of outer folder name
    "site-packages", "dist-packages",
    # Windows venv layout — only unambiguous names used as segment checks
    # (Lib/Scripts/Include are too generic; site-packages is the safe net below)
    # Tooling caches
    "__pycache__", ".tox", ".eggs", "eggs",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".hypothesis", "htmlcov",

    # ── JS / TS package managers ──────────────────────────────────────────────
    "node_modules",
    ".yarn", ".pnp",
    "bower_components",

    # ── Build & bundler outputs ───────────────────────────────────────────────
    "dist", "build", "out",
    ".next", ".nuxt", ".svelte-kit", ".solid",
    "storybook-static", ".expo", ".turbo",
    ".parcel-cache", ".webpack", ".rollup.cache",
    ".output",          # Nuxt 3 output dir

    # ── Generated / auto-synced ───────────────────────────────────────────────
    "generated", "__generated__", ".generated",

    # ── Mobile bundler output ─────────────────────────────────────────────────
    "assets",           # android/app/src/main/assets, iOS asset bundle

    # ── Vendored third-party code ─────────────────────────────────────────────
    "vendor", "vendors", "third_party", "third-party",

    # ── Test artefacts & coverage ─────────────────────────────────────────────
    "coverage", ".coverage", "htmlcov",
    ".nyc_output",

    # ── IDE / editor state ────────────────────────────────────────────────────
    ".idea", ".vscode",

    # ── Misc caches ───────────────────────────────────────────────────────────
    ".cache", ".temp", ".tmp",
}

MAX_FILE_BYTES = 512 * 1024  # skip files larger than 512 KB


def _matches_exclude_pattern(rel_path: str, patterns: list[str]) -> bool:
    """Return True if rel_path should be excluded by a user-supplied pattern list.

    Pattern semantics (case-sensitive, forward-slash normalized):
      - ``web-new``          → plain name: excluded if any path segment equals it
      - ``frontend/store``   → path prefix: excluded if rel_path starts with it
      - ``*.generated.py``   → glob: matched against the filename only
      - ``src/**/*.test.ts`` → glob: matched against the full relative path
    """
    norm = rel_path.replace("\\", "/")
    parts = norm.split("/")
    for pat in patterns:
        p = pat.replace("\\", "/").strip().rstrip("/")
        if not p or p.startswith("#"):
            continue
        if "*" in p or "?" in p or "[" in p:
            # Glob: try full-path match, then filename-only match
            if fnmatch.fnmatch(norm, p) or fnmatch.fnmatch(parts[-1], p):
                return True
        elif "/" in p:
            # Relative path prefix: frontend/store/foo.tsx starts with frontend/store
            if norm.startswith(p + "/") or norm == p:
                return True
        else:
            # Plain segment name: matches any directory or file name in the path
            if p in parts:
                return True
    return False


@dataclass
class FileInfo:
    path: Path
    relative_path: str
    language: str
    size: int
    content_hash: str
    content: str


class FileIndexer:
    def index(
        self,
        repo_path: Path,
        exclude_dirs: set[str] | None = None,
        exclude_paths: list[str] | None = None,
    ) -> list[FileInfo]:
        excludes = EXCLUDE_DIRS | (exclude_dirs or set())
        user_patterns = exclude_paths or []
        results: list[FileInfo] = []

        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in excludes for part in file_path.parts):
                continue
            # User-supplied exclude patterns (CLI --exclude / config file)
            if user_patterns:
                rel = str(file_path.relative_to(repo_path))
                if _matches_exclude_pattern(rel, user_patterns):
                    continue

            language = LANGUAGE_MAP.get(file_path.suffix.lower())
            if language is None:
                continue

            size = file_path.stat().st_size
            if size > MAX_FILE_BYTES:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            content_hash = hashlib.md5(content.encode()).hexdigest()
            relative = str(file_path.relative_to(repo_path))

            results.append(FileInfo(
                path=file_path,
                relative_path=relative,
                language=language,
                size=size,
                content_hash=content_hash,
                content=content,
            ))

        return sorted(results, key=lambda f: f.relative_path)
