"""
This file is refactored from packages/core_ts/src/services/fileDiscoveryService.ts.
It provides a service for discovering and filtering files based on ignore files.
"""

from pathlib import Path

import pathspec

from gemini_cli_core.utils.git_utils import is_git_repository

GEMINI_IGNORE_FILE_NAME = ".geminiignore"


class FileDiscoveryService:
    """
    A service to discover files, respecting .gitignore and .geminiignore rules.
    """

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.git_ignore_spec: pathspec.PathSpec | None = None
        if is_git_repository(str(self.project_root)):
            self.git_ignore_spec = self._load_spec_from_file(
                self.project_root / ".gitignore"
            )

        self.gemini_ignore_spec: pathspec.PathSpec | None = (
            self._load_spec_from_file(
                self.project_root / GEMINI_IGNORE_FILE_NAME
            )
        )
        self.gemini_ignore_patterns: list[str] = self._load_patterns_from_file(
            self.project_root / GEMINI_IGNORE_FILE_NAME
        )

    def _load_patterns_from_file(self, file_path: Path) -> list[str]:
        if not file_path.is_file():
            return []
        with file_path.open("r", encoding="utf-8") as f:
            return f.read().splitlines()

    def _load_spec_from_file(self, file_path: Path) -> pathspec.PathSpec | None:
        patterns = self._load_patterns_from_file(file_path)
        if not patterns:
            return None
        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def filter_files(
        self,
        file_paths: list[str],
        respect_git_ignore: bool = True,
        respect_gemini_ignore: bool = True,
    ) -> list[str]:
        """Filters a list of file paths based on git ignore rules."""
        filtered_paths = []
        for file_path_str in file_paths:
            file_path = Path(file_path_str)
            # pathspec works with relative or absolute paths, but for consistency
            # with .gitignore behavior, we should use paths relative to the project root.
            try:
                relative_path = file_path.relative_to(self.project_root)
            except ValueError:
                # The file is outside the project root, decide how to handle.
                # For now, we'll let it pass the filter.
                relative_path = file_path

            if respect_git_ignore and self.should_git_ignore_file(
                str(relative_path)
            ):
                continue
            if respect_gemini_ignore and self.should_gemini_ignore_file(
                str(relative_path)
            ):
                continue
            filtered_paths.append(file_path_str)
        return filtered_paths

    def should_git_ignore_file(self, file_path: str) -> bool:
        """Checks if a single file should be git-ignored."""
        if self.git_ignore_spec:
            return self.git_ignore_spec.match_file(file_path)
        return False

    def should_gemini_ignore_file(self, file_path: str) -> bool:
        """Checks if a single file should be gemini-ignored."""
        if self.gemini_ignore_spec:
            return self.gemini_ignore_spec.match_file(file_path)
        return False

    def get_gemini_ignore_patterns(self) -> list[str]:
        """Returns loaded patterns from .geminiignore."""
        return self.gemini_ignore_patterns
