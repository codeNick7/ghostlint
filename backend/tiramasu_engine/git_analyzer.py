from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Optional


class GitAnalyzer:
    """Thin wrapper around GitPython for repository history analysis."""

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self._repo = None

    def _get_repo(self):
        if self._repo is not None:
            return self._repo
        try:
            import git
            self._repo = git.Repo(self.repo_path, search_parent_directories=True)
            return self._repo
        except Exception:
            return None

    def is_git_repo(self) -> bool:
        """Return True if the path is inside a git repository."""
        repo = self._get_repo()
        return repo is not None

    def get_changed_files(self) -> list[str]:
        """Return relative paths of files changed vs HEAD (staged + unstaged)."""
        repo = self._get_repo()
        if repo is None:
            return []

        changed: set[str] = set()
        try:
            # Unstaged changes
            for item in repo.index.diff(None):
                changed.add(item.a_path)
                if item.b_path:
                    changed.add(item.b_path)
        except Exception:
            pass

        try:
            # Staged changes (index vs HEAD)
            head = repo.head
            if not head.is_detached and head.commit:
                for item in repo.index.diff(head.commit):
                    changed.add(item.a_path)
                    if item.b_path:
                        changed.add(item.b_path)
        except Exception:
            pass

        try:
            # Untracked files
            for f in repo.untracked_files:
                changed.add(f)
        except Exception:
            pass

        return sorted(changed)

    def get_changed_files_vs_branch(self, base: str = "main") -> list[str]:
        """Return relative paths of files changed vs a given base branch."""
        repo = self._get_repo()
        if repo is None:
            return []

        changed: set[str] = set()
        try:
            # Try the given base, fall back to 'master'
            branches_to_try = [base, "master", "main"]
            base_commit = None
            for b in branches_to_try:
                try:
                    base_commit = repo.commit(b)
                    break
                except Exception:
                    continue

            if base_commit is None:
                return self.get_changed_files()

            for item in repo.head.commit.diff(base_commit):
                changed.add(item.a_path)
                if item.b_path:
                    changed.add(item.b_path)
        except Exception:
            pass

        return sorted(changed)

    def get_file_first_seen(self, rel_path: str) -> Optional[datetime]:
        """Return the datetime of the first commit touching this file, or None."""
        repo = self._get_repo()
        if repo is None:
            return None
        try:
            commits = list(repo.iter_commits(paths=rel_path, reverse=True, max_count=1))
            if commits:
                return datetime.fromtimestamp(commits[0].committed_date)
        except Exception:
            pass
        return None

    def get_file_commit_count(self, rel_path: str) -> int:
        """Return the total number of commits that touched this file."""
        repo = self._get_repo()
        if repo is None:
            return 0
        try:
            return sum(1 for _ in repo.iter_commits(paths=rel_path))
        except Exception:
            return 0
