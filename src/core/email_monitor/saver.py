"""邮件附件落盘与同名自动重命名。"""

from __future__ import annotations

from pathlib import Path


def unique_path(directory: Path, filename: str) -> Path:
    """在目录内生成不冲突的文件路径。

    规则：``name.ext`` → ``name_1.ext`` → ``name_2.ext`` …

    :param directory: 目标目录。
    :param filename: 原始文件名（仅取 basename，拒绝路径穿越）。
    :return: 目录内唯一的文件路径（尚未创建文件）。
    """
    safe_name = Path(filename).name
    candidate = directory / safe_name
    if not candidate.exists():
        return candidate

    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def save_attachment_bytes(
    directory: Path,
    filename: str,
    data: bytes,
) -> Path:
    """将附件字节写入目录，同名时自动重命名。

    :param directory: 目标目录。
    :param filename: 原始文件名。
    :param data: 附件内容。
    :return: 实际写入的文件路径。
    """
    path = unique_path(directory, filename)
    path.write_bytes(data)
    return path
