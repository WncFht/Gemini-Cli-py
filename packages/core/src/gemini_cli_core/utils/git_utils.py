"""
This file is refactored from packages/core_ts/src/utils/gitUtils.ts
and packages/core_ts/src/utils/gitIgnoreParser.ts.
"""

from pathlib import Path

import pathspec


def find_git_root(start_dir: str | Path) -> Path | None:
    """Finds the root directory of a git repository."""
    current_dir = Path(start_dir).resolve()
    while True:
        if (current_dir / ".git").exists():
            return current_dir
        if current_dir.parent == current_dir:  # Reached the filesystem root
            return None
        current_dir = current_dir.parent


def is_git_repository(directory: str | Path) -> bool:
    """Checks if a directory is within a git repository."""
    return find_git_root(directory) is not None


class GitIgnoreParser:
    """A parser for .gitignore files."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self._spec: pathspec.PathSpec | None = None
        self._patterns: list[str] = []

    @property
    def spec(self) -> pathspec.PathSpec:
        """Lazily loads and returns the pathspec."""
        if self._spec is None:
            self._load_all_patterns()
        return self._spec

    def _load_all_patterns(self):
        """Loads all gitignore patterns."""
        self.add_patterns([".git"])  # Always ignore .git
        if is_git_repository(self.project_root):
            self._load_patterns_from_file(self.project_root / ".gitignore")
            self._load_patterns_from_file(
                self.project_root / ".git" / "info" / "exclude"
            )
        self._spec = pathspec.PathSpec.from_lines(
            "gitwildmatch", self._patterns
        )

    def _load_patterns_from_file(self, file_path: Path):
        """Loads patterns from a single file."""
        if file_path.is_file():
            with file_path.open("r", encoding="utf-8") as f:
                patterns = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]
                self.add_patterns(patterns)

    def add_patterns(self, patterns: list[str]):
        """Adds patterns to the parser."""
        self._patterns.extend(patterns)
        # Invalidate spec cache if new patterns are added after initial load
        self._spec = None

    def is_ignored(self, file_path: str | Path) -> bool:
        """Checks if a given file path is ignored."""
        p = Path(file_path)
        if not p.is_absolute():
            relative_path = p
        else:
            try:
                relative_path = p.relative_to(self.project_root)
            except ValueError:
                # Path is outside the project root, not ignored by this context.
                return False

        return self.spec.match_file(str(relative_path))

    def get_patterns(self) -> list[str]:
        """Returns all loaded patterns."""
        if self._spec is None:  # Ensure patterns are loaded
            self._load_all_patterns()
        return self._patterns
