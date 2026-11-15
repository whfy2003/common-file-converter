"""任务规划：文件名清理、输出路径冲突处理、按模式生成任务列表。"""

from __future__ import annotations

import re
from pathlib import Path

from core import scanner
from core.models import Job

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_PDF_SUFFIX = re.compile(r"\.pdf$", re.IGNORECASE)


def safe_name(name: str) -> str:
    """清理文件名里的非法字符。"""
    cleaned = _ILLEGAL_CHARS.sub("_", name).strip().strip(".")
    return cleaned or "合并文件"


def strip_pdf_suffix(name: str) -> str:
    return _PDF_SUFFIX.sub("", name).strip()


def resolve_output_path(job: Job, options: dict) -> Path | None:
    """计算某个任务的输出文件路径；按冲突策略决定是否跳过。"""
    if options["output_mode"] == "custom":
        base_dir = Path(options["output_dir"])
    else:
        base_dir = Path(job.source_dir)

    if not base_dir.is_dir():
        raise ValueError(f"输出文件夹不存在：{base_dir}")

    name = safe_name(job.name)
    path = base_dir / f"{name}.pdf"

    if not path.exists():
        return path
    if options["conflict"] == "overwrite":
        return path
    if options["conflict"] == "skip":
        return None

    index = 2
    while True:
        candidate = base_dir / f"{name} ({index}).pdf"
        if not candidate.exists():
            return candidate
        index += 1


def plan_folder_jobs(folder: Path, mode: str,
                     sort_mode: str) -> list[Job]:
    """按子文件夹输出模式，规划某个根文件夹要生成哪些 PDF。"""
    folder = Path(folder)
    jobs: list[Job] = []
    for target, images in scanner.scan_for_mode(folder, mode, sort_mode):
        if not images:
            continue
        jobs.append(Job(
            name=safe_name(target.name),
            images=images,
            source_dir=target.parent,
            folder=target,
        ))
    return jobs


def plan_image_jobs(images: list[Path], name: str) -> list[Job]:
    """图片模式：所有图片合成一个 PDF。"""
    if not images:
        return []
    clean = safe_name(strip_pdf_suffix(name) or images[0].stem)
    return [Job(name=clean, images=list(images), source_dir=images[0].parent)]
