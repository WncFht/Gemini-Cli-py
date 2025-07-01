import logging
import os
import re
from typing import Dict, List, Tuple

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def generate_anchor(text: str) -> str:
    """从标题文本生成一个 GitHub 风格的锚点。"""
    text = text.lower()
    # 移除非字母数字字符，但保留连字符和空格
    text = re.sub(r"[^\w\s-]", "", text)
    # 用连字符替换空格和下划线
    text = re.sub(r"[\s_]+", "-", text)
    return text


def adjust_markdown_content(
    content: str,
    file_path: str,
    base_dir: str,
    heading_level_offset: int,
    file_anchor_map: Dict[str, str],
) -> str:
    """调整 Markdown 内容中的标题级别并修复相对链接。"""

    # 1. 调整标题级别
    def adjust_heading(match: re.Match[str]) -> str:
        hashes = match.group(1)
        return "#" * (len(hashes) + heading_level_offset)

    adjusted_content = re.sub(r"^(#+)", adjust_heading, content, flags=re.MULTILINE)

    # 2. 修复相对链接
    def fix_link(match: re.Match[str]) -> str:
        full_match_text = match.group(0)
        link_text_part = match.group(1)  # e.g., ![alt text] or [link text]
        link_url = match.group(2)

        # 忽略绝对 URL 和已有的锚点链接
        if link_url.startswith(("http://", "https://", "#")):
            return full_match_text

        current_dir = os.path.dirname(file_path)
        # 解析 URL 片段
        url_parts = link_url.split("#", 1)
        path_part = url_parts[0]
        fragment_part = f"#{url_parts[1]}" if len(url_parts) > 1 else ""

        if not path_part:  # 如果只是一个本地锚点链接，则不处理
            return full_match_text

        target_abs_path = os.path.normpath(os.path.join(current_dir, path_part))

        if target_abs_path in file_anchor_map:
            # 这是一个指向我们集合中另一个 Markdown 文件的链接
            new_url = "#" + file_anchor_map[target_abs_path] + fragment_part
            return f"{link_text_part}({new_url})"
        else:
            # 这是一个指向资产（如图片）的链接
            new_relative_path = os.path.relpath(
                target_abs_path, os.path.dirname(base_dir)
            )
            if os.name == "nt":
                new_relative_path = new_relative_path.replace("\\", "/")

            # 确保它是一个正确的相对路径格式
            new_url = (
                "./" + new_relative_path
                if not new_relative_path.startswith((".", "/"))
                else new_relative_path
            )
            new_url += fragment_part
            return f"{link_text_part}({new_url})"

    # Markdown 链接的正则表达式: ![text](url) 或 [text](url)
    adjusted_content = re.sub(r"(!?\[.*?\])\(([^)]+)\)", fix_link, adjusted_content)

    return adjusted_content


def combine_markdown_files(
    base_dir: str, index_file: str, output_file: str, doc_title: str
) -> None:
    """
    抓取目录中的 Markdown 文件，将它们合并成一个单一的文件，
    并带有调整后的标题层级、目录和修复后的相对链接。
    """
    abs_base_dir = os.path.abspath(base_dir)
    abs_output_file = os.path.join(abs_base_dir, output_file)
    abs_index_file = os.path.join(abs_base_dir, index_file)

    all_files: List[Tuple[int, str]] = []  # (深度, 绝对路径)
    for root, dirs, files in os.walk(abs_base_dir, topdown=True):
        # 排除隐藏目录（如 .git）
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        depth = (
            root.replace(abs_base_dir, "").count(os.sep) if root != abs_base_dir else 0
        )

        md_files = sorted(
            [
                f
                for f in files
                if f.endswith(".md") and os.path.join(root, f) != abs_output_file
            ]
        )

        for md_file in md_files:
            all_files.append((depth, os.path.join(root, md_file)))

    # 排序文件，确保 index.md 在最前面，然后按路径排序
    all_files.sort(key=lambda x: (x[1] != abs_index_file, x[1]))

    file_anchor_map: Dict[str, str] = {}
    toc_lines: List[str] = []

    # 第一遍：生成锚点和目录结构
    for depth, file_path in all_files:
        relative_path = os.path.relpath(file_path, abs_base_dir)
        if os.name == "nt":
            relative_path = relative_path.replace("\\", "/")

        section_title = relative_path.replace(".md", "")
        anchor = generate_anchor(section_title)
        file_anchor_map[file_path] = anchor

        indent = "  " * depth
        toc_lines.append(f"{indent}- [{section_title}](#{anchor})")

    combined_content: List[str] = [
        f"# {doc_title}\n",
        "## 目录\n",
        "\n".join(toc_lines),
        "\n\n---\n",
    ]

    # 第二遍：读取文件，调整内容并合并
    for depth, file_path in all_files:
        relative_path = os.path.relpath(file_path, abs_base_dir)
        if os.name == "nt":
            relative_path = relative_path.replace("\\", "/")

        section_heading_level = depth + 2  # #主标题 -> ##文件标题
        section_title = relative_path

        combined_content.append(f"\n{'#' * section_heading_level} {section_title}\n\n")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original_content = f.read()

            processed_content = adjust_markdown_content(
                original_content,
                file_path,
                abs_output_file,
                section_heading_level,
                file_anchor_map,
            )

            combined_content.append(processed_content)
            combined_content.append("\n\n---\n")

        except Exception:
            logger.exception(f"处理文件时出错 {file_path}")

    try:
        with open(abs_output_file, "w", encoding="utf-8") as f:
            f.write("".join(combined_content))
        logger.info(f"已成功将文档合并到 {abs_output_file}")
    except Exception:
        logger.exception(f"写入输出文件时出错 {abs_output_file}")


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    combine_markdown_files(
        base_dir=script_dir,
        index_file="index.md",
        output_file="all_in_one_doc.md",
        doc_title="Gemini CLI 综合文档",
    )
