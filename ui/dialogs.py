"""辅助对话框：非 JPG 格式提醒、生成计划预览。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import scanner
from core.models import Job
from ui.widgets import fade_in_window


class ConvertNoticeDialog(QDialog):
    """提醒用户：检测到非 JPG 图片，将先转换为 JPG 再合并。"""

    def __init__(self, parent=None, paths: list[Path] | None = None):
        super().__init__(parent)
        self.confirmed = False
        self.paths = list(paths or [])
        self.setWindowTitle("需要先转换图片格式")
        self.setModal(True)
        self.setFixedSize(680, 540)
        self._build()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        fade_in_window(self, 150)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 18)
        outer.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        badge = QLabel("!")
        badge.setObjectName("Badge")
        badge.setFixedSize(36, 36)
        title = QLabel("检测到不是 JPG 格式的图片")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        title_row.addWidget(badge)
        title_row.addWidget(title, 1)
        outer.addLayout(title_row)

        counts = Counter(scanner.format_label(path) for path in self.paths)
        detail = "、".join(f"{name} × {count}" for name, count in counts.most_common())
        info = QLabel(
            f"共有 {len(self.paths)} 张图片不是 JPG 格式（{detail}）。\n"
            "按处理流程，会先把它们转换成 JPG，再统一合并成 PDF。\n"
            "原始图片不会被修改或删除；转换只发生在临时目录，生成完成后自动清理。"
        )
        info.setWordWrap(True)
        info.setObjectName("Hint")
        outer.addWidget(info)

        list_title = QLabel("涉及的图片")
        list_title.setStyleSheet("font-size: 13px; font-weight: 600;")
        outer.addWidget(list_title)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        for index, path in enumerate(self.paths, 1):
            self.list_widget.addItem(
                f"{index}.  {path.name}    （{scanner.format_label(path)}）")
        outer.addWidget(self.list_widget, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("先转换，再继续")
        confirm.setObjectName("Accent")
        confirm.setDefault(True)
        confirm.clicked.connect(self._confirm)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        outer.addLayout(buttons)

    def _confirm(self) -> None:
        self.confirmed = True
        self.accept()


class PlanPreviewDialog(QDialog):
    """预览一次生成会产出哪些 PDF、每个 PDF 包含哪些图片。"""

    def __init__(self, parent=None, title: str = "生成计划", jobs: list[Job] | None = None):
        super().__init__(parent)
        self.jobs = list(jobs or [])
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(760, 580)
        self._build()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        fade_in_window(self, 150)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(10)

        heading = QLabel(f"将生成 {len(self.jobs)} 个 PDF")
        heading.setStyleSheet("font-size: 15px; font-weight: 600;")
        outer.addWidget(heading)

        hint = QLabel("展开每一项可以查看该 PDF 包含的图片顺序；页面按列表顺序生成。")
        hint.setObjectName("Hint")
        outer.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["PDF / 图片", "页数 / 格式", "输出位置"])
        self.tree.setColumnWidth(0, 360)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 260)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        outer.addWidget(self.tree, 1)

        for job in self.jobs:
            output_name = f"{job.name}.pdf"
            parent_item = QTreeWidgetItem([output_name, f"{len(job.images)} 页",
                                           str(job.source_dir)])
            parent_item.setExpanded(False)
            self.tree.addTopLevelItem(parent_item)
            for index, path in enumerate(job.images, 1):
                child = QTreeWidgetItem([
                    f"{index}.  {path.name}",
                    scanner.format_label(path),
                    "",
                ])
                parent_item.addChild(child)
        if self.jobs:
            self.tree.topLevelItem(0).setExpanded(True)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        outer.addLayout(buttons)
