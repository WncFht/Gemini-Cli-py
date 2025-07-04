import hashlib
from pathlib import Path

GEMINI_DIR = ".gemini"
TMP_DIR_NAME = "tmp"


def tildeify_path(p: Path) -> str:
    """Replaces the home directory with a tilde."""
    home = Path.home()
    if p.is_relative_to(home):
        return f"~/{p.relative_to(home)}"
    return str(p)


def shorten_path(file_path: str, max_len: int = 35) -> str:
    """Shortens a path string if it exceeds maxLen, prioritizing start and end."""
    if len(file_path) <= max_len:
        return file_path

    p = Path(file_path)
    # On Windows, p.parts might include the drive letter twice, e.g., ('C:', '\\', 'Users', ...).
    # We filter out the root/anchor to handle this gracefully.
    parts = [part for part in p.parts if part != p.anchor and part != "\\"]

    if len(parts) <= 2:  # e.g., ['Users', 'test.txt']
        # Fallback to simple truncation from the beginning
        return f"...{file_path[-(max_len - 3) :]}"

    # Keep the first directory and the filename
    first_dir = parts[0]
    filename = parts[-1]
    # Ellipsis and separators
    ellipsis = "..."
    separator = "/"  # Use forward slash for consistent display

    # Keep adding parts from the end until we exceed max_len
    end_parts = [filename]
    current_len = (
        len(first_dir) + len(ellipsis) + len(filename) + 2
    )  # for separators

    for i in range(len(parts) - 2, 0, -1):
        part = parts[i]
        if current_len + len(part) + 1 > max_len:
            break
        end_parts.insert(0, part)
        current_len += len(part) + 1

    return f"{first_dir}{separator}{ellipsis}{separator}{separator.join(end_parts)}"


def make_relative(target_path: Path, root_directory: Path) -> str:
    """Calculates the relative path, returning '.' for the same path."""
    try:
        relative_path = target_path.relative_to(root_directory)
        return str(relative_path) or "."
    except ValueError:
        # This can happen if target_path is not within root_directory
        return str(target_path)


def get_project_hash(project_root: str) -> str:
    """Generates a unique hash for a project based on its root path."""
    return hashlib.sha256(project_root.encode()).hexdigest()


def get_project_temp_dir(project_root: str | Path) -> Path:
    """Generates a unique temporary directory path for a project."""
    hash_val = get_project_hash(str(project_root))
    return Path.home() / GEMINI_DIR / TMP_DIR_NAME / hash_val


def is_within_root(path_to_check: Path, root_directory: Path) -> bool:
    """Checks if a path is within a given root directory."""
    try:
        path_to_check.resolve().relative_to(root_directory.resolve())
        return True
    except ValueError:
        return False


def escape_path(file_path: str) -> str:
    """Escapes spaces in a file path for shell commands."""
    return file_path.replace(" ", "\\ ")


def unescape_path(file_path: str) -> str:
    """Unescapes spaces in a file path."""
    return file_path.replace("\\ ", " ")
