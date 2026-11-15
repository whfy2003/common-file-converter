"""图片扫描、格式判断与文件名排序。

排序规则的核心是「自然排序」：把文件名里的数字段按数值比较，
所以 2.jpg 会排在 10.jpg 前面，符合「带编号的图片从小到大」的要求。
"""

from __future__ import annotations

import re
from pathlib import Path

# 支持识别的图片扩展名（统一小写、带点）
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".jfif",
    ".png", ".bmp", ".dib",
    ".gif", ".webp", ".tif", ".tiff",
    ".ico", ".ppm", ".pgm", ".pnm", ".tga", ".avif",
}

# 视为「已经是 JPG」的扩展名（无需转换）
JPG_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif"}

# 排序方式
SORT_NATURAL = "natural"
SORT_NAME = "name"
SORT_MODIFIED = "modified"

SORT_LABELS = {
    SORT_NATURAL: "按图片编号（自然排序，推荐）",
    SORT_NAME: "按文件名（字母顺序）",
    SORT_MODIFIED: "按修改时间（从早到晚）",
}

# 子文件夹的输出方式
OUTPUT_SINGLE = "single"
OUTPUT_PER_SUBFOLDER = "per_subfolder"
OUTPUT_MERGE_ALL = "merge_all"

OUTPUT_MODE_LABELS = {
    OUTPUT_SINGLE: "只合并当前文件夹里的图片",
    OUTPUT_PER_SUBFOLDER: "每个子文件夹各生成一个 PDF",
    OUTPUT_MERGE_ALL: "所有子文件夹合并成一个 PDF",
}

_NUMBER_RE = re.compile(r"(\d+)")


def natural_key(text: str):
    """生成可比较的排序键：数字段按数值比较，其余按小写文本比较。

    返回的列表元素是形如 (0, 数字, "") 或 (1, 0, 文本) 的元组，
    同一位置上的元素类型固定，所以可以直接用 sorted 比较。
    """
    key = []
    for index, part in enumerate(_NUMBER_RE.split(text)):
        if index % 2 == 1:
            key.append((0, int(part), ""))
        else:
            key.append((1, 0, part.strip().lower()))
    return key


def is_image(path: Path | str) -> bool:
    """按扩展名判断是否是可处理的图片。"""
    return Path(path).suffix.lower() in IMAGE_EXTS


def is_jpg(path: Path | str) -> bool:
    """判断是否已经是 JPG（jpg / jpeg / jpe / jfif 都算）。"""
    return Path(path).suffix.lower() in JPG_EXTS


def format_label(path: Path | str) -> str:
    """返回用于界面展示的格式名，例如 JPG、PNG、WEBP。"""
    suffix = Path(path).suffix.lower()
    if suffix in JPG_EXTS:
        return "JPG"
    return suffix.lstrip(".").upper() or "未知"


def sort_images(paths, mode: str = SORT_NATURAL, base: Path | None = None):
    """按指定方式排序图片列表。

    base 不为空时使用相对路径排序（用于递归子文件夹的场景），
    这样不同子文件夹里的同名图片也能稳定排序。
    """
    paths = list(paths)

    if mode == SORT_MODIFIED:
        def _mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        return sorted(paths, key=_mtime)

    def _relative(path: Path) -> str:
        if base is not None:
            try:
                return path.relative_to(base).as_posix()
            except ValueError:
                pass
        return path.name

    if mode == SORT_NAME:
        return sorted(paths, key=lambda p: _relative(p).lower())
    return sorted(paths, key=lambda p: natural_key(_relative(p)))


def scan_folder(folder: Path | str, recursive: bool = False,
                sort_mode: str = SORT_NATURAL) -> list[Path]:
    """扫描文件夹里所有图片，并按指定方式排序。"""
    folder = Path(folder)
    if not folder.is_dir():
        return []

    found: list[Path] = []
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    for item in iterator:
        try:
            if item.is_file() and is_image(item):
                found.append(item)
        except OSError:
            continue

    return sort_images(found, sort_mode, base=folder if recursive else None)


def _scan_tree(folder: Path, sort_mode: str) -> dict[Path, list[Path]]:
    """一次遍历，把文件夹（含所有子文件夹）里的图片按所在目录分组。"""
    groups: dict[Path, list[Path]] = {}
    try:
        iterator = folder.rglob("*")
        for item in iterator:
            try:
                if item.is_file() and is_image(item):
                    groups.setdefault(item.parent, []).append(item)
            except OSError:
                continue
    except OSError:
        pass
    for parent, images in groups.items():
        groups[parent] = sort_images(images, sort_mode)
    return groups


def _ordered_dirs(folder: Path, groups: dict[Path, list[Path]]) -> list[Path]:
    """先当前文件夹，再按相对路径自然排序的子文件夹。"""
    ordered: list[Path] = []
    if folder in groups:
        ordered.append(folder)
    sub_dirs = sorted(
        (path for path in groups if path != folder),
        key=lambda p: natural_key(p.relative_to(folder).as_posix()),
    )
    ordered.extend(sub_dirs)
    return ordered


def scan_for_mode(folder: Path | str, mode: str = OUTPUT_SINGLE,
                  sort_mode: str = SORT_NATURAL) -> list[tuple[Path, list[Path]]]:
    """按子文件夹输出模式，返回 [(目录, 图片列表), ...]。

    每个元组对应一个将要生成的 PDF：目录名就是 PDF 的默认名称。
    """
    folder = Path(folder)
    if not folder.is_dir():
        return []

    groups = _scan_tree(folder, sort_mode)

    if mode == OUTPUT_MERGE_ALL:
        images: list[Path] = []
        for parent in _ordered_dirs(folder, groups):
            images.extend(groups[parent])
        return [(folder, images)] if images else []

    if mode == OUTPUT_SINGLE:
        images = groups.get(folder, [])
        return [(folder, images)] if images else []

    return [(path, groups[path]) for path in _ordered_dirs(folder, groups)
            if groups[path]]
