"""
文件夹结构工具 - 从 getFolderStructure.ts 迁移
"""

from pathlib import Path
from typing import Any


async def get_folder_structure(
    directory: str,
    file_service: Any | None = None,
    max_depth: int = 3,
) -> str:
    """
    获取目录结构的字符串表示

    Args:
        directory: 目标目录路径
        file_service: 文件服务（可选）
        max_depth: 最大递归深度

    Returns:
        目录结构的字符串表示

    """
    try:
        path = Path(directory)
        if not path.exists():
            return f"目录不存在: {directory}"

        if not path.is_dir():
            return f"不是目录: {directory}"

        lines = ["目录结构:"]
        _build_tree(path, lines, "", 0, max_depth)

        return "\n".join(lines)

    except Exception as e:
        return f"获取目录结构时出错: {e!s}"


def _build_tree(
    path: Path,
    lines: list[str],
    prefix: str,
    depth: int,
    max_depth: int,
) -> None:
    """
    递归构建目录树

    Args:
        path: 当前路径
        lines: 结果行列表
        prefix: 前缀字符串
        depth: 当前深度
        max_depth: 最大深度

    """
    if depth > max_depth:
        return

    try:
        entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            current_prefix = "└── " if is_last else "├── "
            next_prefix = "    " if is_last else "│   "

            if entry.is_dir():
                lines.append(f"{prefix}{current_prefix}{entry.name}/")
                _build_tree(
                    entry,
                    lines,
                    prefix + next_prefix,
                    depth + 1,
                    max_depth,
                )
            else:
                # 获取文件大小
                try:
                    size = entry.stat().st_size
                    size_str = _format_size(size)
                    lines.append(
                        f"{prefix}{current_prefix}{entry.name} ({size_str})"
                    )
                except:
                    lines.append(f"{prefix}{current_prefix}{entry.name}")

    except PermissionError:
        lines.append(f"{prefix}[权限被拒绝]")
    except Exception as e:
        lines.append(f"{prefix}[错误: {e!s}]")


def _format_size(size: int) -> str:
    """
    格式化文件大小

    Args:
        size: 字节大小

    Returns:
        格式化的大小字符串

    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"
