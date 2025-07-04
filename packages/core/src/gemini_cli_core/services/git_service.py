import asyncio
import shutil
from pathlib import Path

import git

from gemini_cli_core.utils.git_utils import is_git_repository
from gemini_cli_core.utils.paths import GEMINI_DIR, get_project_hash


class GitService:
    """
    Manages a shadow Git repository for creating and restoring file snapshots.
    """

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self._shadow_repo_path = self._get_history_dir()
        self._git_cmd: git.Git | None = None

    def _get_history_dir(self) -> Path:
        hash_val = get_project_hash(str(self.project_root))
        return Path.home() / GEMINI_DIR / "history" / hash_val

    async def initialize(self) -> None:
        """Initializes the service, checking for Git and setting up the shadow repo."""
        if not await asyncio.to_thread(
            is_git_repository, str(self.project_root)
        ):
            raise ValueError(
                "GitService requires the project to be a Git repository."
            )
        if not await self.verify_git_availability():
            raise ConnectionError(
                "GitService requires Git to be installed and in the PATH."
            )
        await asyncio.to_thread(self._setup_shadow_git_repository)

    @staticmethod
    async def verify_git_availability() -> bool:
        """Verifies that the `git` command is available."""
        try:
            process = await asyncio.create_subprocess_shell(
                "git --version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            return process.returncode == 0
        except FileNotFoundError:
            return False

    def _setup_shadow_git_repository(self) -> None:
        """
        Sets up a hidden git repository to manage file history for checkpoints,
        isolated from the user's own git setup.
        """
        repo_dir = self._shadow_repo_path
        repo_dir.mkdir(parents=True, exist_ok=True)

        git_config_path = repo_dir / ".gitconfig"
        if not git_config_path.exists():
            git_config_content = (
                "[user]\n  name = Gemini CLI\n  email = gemini-cli@google.com\n"
                "[commit]\n  gpgsign = false\n"
            )
            git_config_path.write_text(git_config_content, encoding="utf-8")

        git_dir = repo_dir / ".git"
        if not git_dir.exists():
            repo = git.Repo.init(str(repo_dir), initial_branch="main")
            author = git.Actor("Gemini CLI", "gemini-cli@google.com")
            repo.index.commit(
                "Initial commit",
                author=author,
                committer=author,
                skip_hooks=True,
                allow_empty=True,
            )

        user_gitignore = self.project_root / ".gitignore"
        shadow_gitignore = repo_dir / ".gitignore"
        if user_gitignore.exists() and not shadow_gitignore.exists():
            shutil.copyfile(user_gitignore, shadow_gitignore)

        git_cmd = git.Git(str(self.project_root))
        git_cmd.update_environment(
            GIT_DIR=str(git_dir),
            GIT_WORK_TREE=str(self.project_root),
            HOME=str(repo_dir),
            XDG_CONFIG_HOME=str(repo_dir),
        )
        self._git_cmd = git_cmd

    @property
    def shadow_git_command(self) -> git.Git:
        """Returns the Git command object configured for the shadow repository."""
        if not self._git_cmd:
            raise ConnectionAbortedError(
                "GitService is not initialized. Call `initialize()` first."
            )
        return self._git_cmd

    async def get_current_commit_hash(self) -> str:
        """Gets the current HEAD commit hash from the shadow repository."""
        cmd = self.shadow_git_command
        return await asyncio.to_thread(cmd.rev_parse, "HEAD")

    async def create_file_snapshot(self, message: str) -> str:
        """Adds all files and creates a commit in the shadow repository."""

        def _sync_snapshot():
            self.shadow_git_command.add(".")
            # Use a basic commit command; GitPython's commit object is complex.
            self.shadow_git_command.commit("-m", message)
            return self.shadow_git_command.rev_parse("HEAD").strip()

        return await asyncio.to_thread(_sync_snapshot)

    async def restore_project_from_snapshot(self, commit_hash: str) -> None:
        """Restores the project state from a snapshot and cleans untracked files."""

        def _sync_restore():
            self.shadow_git_command.restore("--source", commit_hash, ".")
            self.shadow_git_command.clean("-fd")

        await asyncio.to_thread(_sync_restore)
