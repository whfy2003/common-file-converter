"""界面与生成流程共用的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FolderTask:
    """「按文件夹合并」模式下的一个任务：一个文件夹 → 一个 PDF。"""

    folder: Path
    images: list[Path] = field(default_factory=list)
    status: str = "待生成"

    @property
    def output_name(self) -> str:
        """PDF 文件默认使用文件夹名称。"""
        return self.folder.name


@dataclass
class Job:
    """真正交给后台线程执行的一项生成任务。"""

    name: str                    # PDF 文件名（不含扩展名）
    images: list[Path]           # 要合并的图片，顺序即页面顺序
    source_dir: Path             # 默认输出位置（源文件所在文件夹）
    folder: Path | None = None   # 对应的文件夹（图片模式为 None）
    task_index: int | None = None  # 在文件夹任务列表中的下标，用于回写状态

    @property
    def output_name(self) -> str:
        return self.name
