from __future__ import annotations
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
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "vendor", ".mypy_cache",
    ".pytest_cache", "coverage", ".tox", "eggs", ".eggs",
}

MAX_FILE_BYTES = 512 * 1024  # skip files larger than 512 KB


@dataclass
class FileInfo:
    path: Path
    relative_path: str
    language: str
    size: int
    content_hash: str
    content: str


class FileIndexer:
    def index(self, repo_path: Path, exclude_dirs: set[str] | None = None) -> list[FileInfo]:
        excludes = EXCLUDE_DIRS | (exclude_dirs or set())
        results: list[FileInfo] = []

        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in excludes for part in file_path.parts):
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
