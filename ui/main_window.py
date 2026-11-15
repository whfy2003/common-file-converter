"""主窗口：Windows 11 风格界面，支持文件夹合并与图片合并两种模式。"""

from __future__ import annotations

import os
import queue
import shutil
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import scanner
from core.converter import convert_to_jpg
from core.models import FolderTask, Job
from core.pdf_builder import PAGE_PRESETS, build_pdf
from core.planning import plan_image_jobs, resolve_output_path, safe_name
from ui import theme
from ui.convert_page import ConvertPage
from ui.dialogs import ConvertNoticeDialog, PlanPreviewDialog
from ui.extract_page import ExtractPage
from ui.folder_dialog import FolderPickerDialog
from ui.widgets import (CardHeader, ComboBox, NavDelegate, SectionCard,
                           fade_in_widget, fade_in_window, make_table)

CONFLICT_LABELS = {
    "auto": "自动添加序号（推荐）",
    "overwrite": "覆盖同名文件",
    "skip": "跳过已存在的文件",
}
CONFLICT_KEYS = {label: key for key, label in CONFLICT_LABELS.items()}

OUTPUT_LABEL_TO_KEY = {label: key for key, label in scanner.OUTPUT_MODE_LABELS.items()}
SORT_LABEL_TO_KEY = {label: key for key, label in scanner.SORT_LABELS.items()}
PAGE_LABEL_TO_KEY = {_label: key for key, _label, _size in PAGE_PRESETS}


class WorkerBridge(QObject):
    """后台生成线程与界面线程之间的信号通道。"""

    log = Signal(str)
    progress = Signal(float, str)
    job_done = Signal(int, str)      # 根任务下标, ok / skip / fail
    finished = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, theme_manager: theme.ThemeManager):
        super().__init__()
        self.theme_manager = theme_manager

        self.folder_tasks: list[FolderTask] = []
        self.image_paths: list[Path] = []
        self._folder_entries: dict[Path, list[tuple[Path, list[Path]]]] = {}
        self._busy = False
        self._generated: list[str] = []
        self._last_dir = str(Path.home())
        self._last_auto_name = ""
        self._task_counts: dict[int, dict[str, int]] = {}
        self._task_job_total: dict[int, int] = {}
        self._worker_thread = None

        self._bridge = WorkerBridge()
        self._bridge.log.connect(self._log)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.job_done.connect(self._on_job_done)
        self._bridge.finished.connect(self._on_finished)

        self._system_timer = QTimer(self)
        self._system_timer.timeout.connect(self._check_system_theme)
        self._system_timer.start(2500)

        self.setWindowTitle("Document Tool")
        self.setWindowIcon(self._app_icon())
        self._place_window()

        self._build()
        self.theme_manager.changed.connect(self._apply_theme)
        self._apply_theme()
        self._refresh_folder_table()
        self._refresh_image_table()
        self._refresh_status()
        self._log("欢迎使用「图片合并为 PDF」。")
        self._log("① 按文件夹合并：支持「每个子文件夹各一个 PDF」与「全部合并成一个 PDF」。")
        self._log("② 按图片合并：多张图片按编号顺序合成一个 PDF。")

    # ================================================================ 窗口搭建
    def _app_icon(self) -> QIcon:
        """优先读取 assets/icon.ico，找不到或无效时回退到 icon.png。"""
        for name in ("icon.ico", "icon.png"):
            path = theme.ASSETS / name
            if path.is_file():
                icon = QIcon(str(path))
                if not icon.isNull():
                    return icon
        return QIcon()

    def _place_window(self) -> None:
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        width, height = 1180, 900
        if available is not None:
            width = min(width, available.width() - 80)
            height = min(height, available.height() - 60)
        self.resize(max(1000, width), max(720, height))
        if available is not None:
            self.move(available.center().x() - self.width() // 2,
                      available.center().y() - self.height() // 2)

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())

        content = QWidget()
        content.setObjectName("Content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(26, 22, 26, 16)
        content_layout.setSpacing(12)

        self.page_title = QLabel("按文件夹合并")
        self.page_title.setObjectName("Title")
        self.page_subtitle = QLabel("")
        self.page_subtitle.setObjectName("Subtitle")
        content_layout.addWidget(self.page_title)
        content_layout.addWidget(self.page_subtitle)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_folder_page())
        self.stack.addWidget(self._build_images_page())

        self.image_convert_page = ConvertPage("image", self.theme_manager)
        self.video_convert_page = ConvertPage("video", self.theme_manager)
        self.audio_convert_page = ConvertPage("audio", self.theme_manager)
        self.extract_page = ExtractPage(self.theme_manager)
        for page in (self.image_convert_page, self.video_convert_page,
                     self.audio_convert_page, self.extract_page):
            page.message.connect(self._log)
            page.progress.connect(self._on_progress)
            page.finished.connect(self._on_convert_finished)
            page.state_changed.connect(self._on_convert_state)
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)

        self._output_card = self._build_output_card()
        content_layout.addWidget(self._output_card)
        content_layout.addWidget(self._build_log_card())
        content_layout.addWidget(self._build_bottom_bar())

        outer.addWidget(content, 1)
        self._update_page_text(0)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(236)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 24, 14, 18)
        layout.setSpacing(10)

        app_title = QLabel("Document Tool")
        app_title.setObjectName("SideTitle")
        app_sub = QLabel("常用文件格式转换工具")
        app_sub.setObjectName("SideSubtitle")
        app_sub.setWordWrap(True)
        layout.addWidget(app_title)
        layout.addWidget(app_sub)
        layout.addSpacing(8)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setMouseTracking(True)
        self.nav.setItemDelegate(NavDelegate(self.theme_manager))
        self.nav.addItem("按文件夹合并")
        self.nav.addItem("按图片合并")
        self.nav.addItem("图片格式转换")
        self.nav.addItem("视频格式转换")
        self.nav.addItem("音频格式转换")
        self.nav.addItem("字幕音轨提取")
        self.nav.setFixedHeight(286)
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav)

        layout.addStretch(1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("Subtle")
        self.theme_button.setFixedSize(38, 38)
        self.theme_button.setIconSize(QSize(20, 20))
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.clicked.connect(self._toggle_theme)
        bottom.addWidget(self.theme_button)
        bottom.addStretch(1)
        version = QLabel("版本 1.0")
        version.setObjectName("Hint")
        bottom.addWidget(version)
        layout.addLayout(bottom)
        return sidebar

    # ------------------------------------------------------------ 文件夹页
    def _build_folder_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        card = SectionCard()
        card.body.addWidget(CardHeader(
            "待生成的 PDF",
            "添加文件夹后，每个文件夹生成一个同名 PDF；也可以让每个子文件夹各自生成一个。"))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.add_folder_button = QPushButton("＋  添加文件夹")
        self.add_folder_button.clicked.connect(self._add_folders)
        toolbar.addWidget(self.add_folder_button)
        self.folder_remove_button = QPushButton("移除选中")
        self.folder_remove_button.clicked.connect(self._remove_folders)
        toolbar.addWidget(self.folder_remove_button)
        self.folder_clear_button = QPushButton("清空")
        self.folder_clear_button.clicked.connect(self._clear_folders)
        toolbar.addWidget(self.folder_clear_button)
        self.folder_up_button = QPushButton("↑  上移")
        self.folder_up_button.clicked.connect(lambda: self._move_folder(-1))
        toolbar.addWidget(self.folder_up_button)
        self.folder_down_button = QPushButton("↓  下移")
        self.folder_down_button.clicked.connect(lambda: self._move_folder(1))
        toolbar.addWidget(self.folder_down_button)
        toolbar.addStretch(1)
        preview_hint = QLabel("双击一行可预览生成计划")
        preview_hint.setObjectName("Hint")
        toolbar.addWidget(preview_hint)
        card.body.addLayout(toolbar)

        self.folder_table = make_table(
            ["序号", "文件夹", "图片数", "将生成的 PDF", "状态"],
            [56, 250, 80, 300, 110], row_height=40)
        self.folder_table.cellDoubleClicked.connect(self._preview_folder)
        card.body.addWidget(self.folder_table, 1)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("子文件夹"))
        self.subfolder_combo = ComboBox()
        self.subfolder_combo.addItems(list(scanner.OUTPUT_MODE_LABELS.values()))
        self.subfolder_combo.setMinimumWidth(300)
        self.subfolder_combo.currentIndexChanged.connect(self._rescan_folders)
        options.addWidget(self.subfolder_combo)

        options.addSpacing(18)
        options.addWidget(QLabel("图片排序"))
        self.sort_combo = ComboBox()
        self.sort_combo.addItems(list(scanner.SORT_LABELS.values()))
        self.sort_combo.setMinimumWidth(250)
        self.sort_combo.currentIndexChanged.connect(self._rescan_folders)
        options.addWidget(self.sort_combo)
        options.addStretch(1)
        card.body.addLayout(options)

        layout.addWidget(card)
        return page

    # ------------------------------------------------------------ 图片页
    def _build_images_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        card = SectionCard()
        card.body.addWidget(CardHeader(
            "待合并的图片",
            "选择多张图片，按编号顺序合并成一个 PDF，默认使用第一张图片的名称。"))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.add_image_button = QPushButton("＋  添加图片")
        self.add_image_button.clicked.connect(self._add_images)
        toolbar.addWidget(self.add_image_button)
        self.image_remove_button = QPushButton("移除选中")
        self.image_remove_button.clicked.connect(self._remove_images)
        toolbar.addWidget(self.image_remove_button)
        self.image_clear_button = QPushButton("清空")
        self.image_clear_button.clicked.connect(self._clear_images)
        toolbar.addWidget(self.image_clear_button)
        self.image_up_button = QPushButton("↑  上移")
        self.image_up_button.clicked.connect(lambda: self._move_image(-1))
        toolbar.addWidget(self.image_up_button)
        self.image_down_button = QPushButton("↓  下移")
        self.image_down_button.clicked.connect(lambda: self._move_image(1))
        toolbar.addWidget(self.image_down_button)
        self.image_sort_button = QPushButton("按编号重排")
        self.image_sort_button.clicked.connect(self._resort_images)
        toolbar.addWidget(self.image_sort_button)
        toolbar.addStretch(1)
        card.body.addLayout(toolbar)

        self.image_table = make_table(
            ["序号", "图片文件", "格式", "大小", "所在文件夹"],
            [56, 320, 80, 90, 260], row_height=40)
        card.body.addWidget(self.image_table, 1)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("PDF 文件名"))
        self.image_name_edit = QLineEdit()
        self.image_name_edit.setMinimumWidth(280)
        self.image_name_edit.setPlaceholderText("默认使用第一张图片的名称")
        options.addWidget(self.image_name_edit)
        name_hint = QLabel("不用写 .pdf；留空时使用第一张图片的名称")
        name_hint.setObjectName("Hint")
        options.addWidget(name_hint)
        options.addStretch(1)
        card.body.addLayout(options)

        layout.addWidget(card)
        return page

    # ------------------------------------------------------------ 输出设置
    def _build_output_card(self) -> QWidget:
        card = SectionCard()
        card.body.addWidget(CardHeader("输出设置", "以下设置对两种模式都生效"))

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        label1 = QLabel("输出位置")
        label1.setFixedWidth(64)
        row1.addWidget(label1)
        self.radio_source = QRadioButton("源文件夹所在位置")
        self.radio_source.setChecked(True)
        self.radio_source.toggled.connect(self._on_output_mode_changed)
        self.radio_custom = QRadioButton("指定文件夹")
        row1.addWidget(self.radio_source)
        row1.addWidget(self.radio_custom)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("选择输出文件夹…")
        self.output_edit.setEnabled(False)
        row1.addWidget(self.output_edit, 1)
        self.output_browse_button = QPushButton("浏览…")
        self.output_browse_button.clicked.connect(self._browse_output_dir)
        row1.addWidget(self.output_browse_button)
        card.body.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        label2 = QLabel("同名文件")
        label2.setFixedWidth(64)
        row2.addWidget(label2)
        self.conflict_combo = ComboBox()
        self.conflict_combo.addItems(list(CONFLICT_LABELS.values()))
        self.conflict_combo.setMinimumWidth(200)
        row2.addWidget(self.conflict_combo)

        row2.addSpacing(18)
        label3 = QLabel("页面尺寸")
        row2.addWidget(label3)
        self.page_size_combo = ComboBox()
        for _key, label, _size in PAGE_PRESETS:
            self.page_size_combo.addItem(label)
        self.page_size_combo.setMinimumWidth(180)
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        row2.addWidget(self.page_size_combo)

        self.custom_size_widget = QWidget()
        custom_layout = QHBoxLayout(self.custom_size_widget)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(6)
        custom_layout.addWidget(QLabel("宽"))
        self.custom_width_edit = self._make_size_edit("210")
        custom_layout.addWidget(self.custom_width_edit)
        custom_layout.addWidget(QLabel("×"))
        custom_layout.addWidget(QLabel("高"))
        self.custom_height_edit = self._make_size_edit("297")
        custom_layout.addWidget(self.custom_height_edit)
        custom_layout.addWidget(QLabel("mm"))
        self.custom_size_widget.setVisible(False)
        row2.addWidget(self.custom_size_widget)
        row2.addStretch(1)
        card.body.addLayout(row2)
        return card

    def _make_size_edit(self, default: str) -> QLineEdit:
        edit = QLineEdit(default)
        edit.setObjectName("SizeInput")
        edit.setValidator(QIntValidator(10, 2000, self))
        edit.setAlignment(Qt.AlignCenter)
        return edit

    # ------------------------------------------------------------ 日志
    def _build_log_card(self) -> QWidget:
        card = SectionCard(padding=(16, 12, 16, 12), spacing=8)
        title = QLabel("处理日志")
        title.setObjectName("CardTitle")
        card.body.addWidget(title)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(600)
        self.log_view.setFixedHeight(78)
        card.body.addWidget(self.log_view)
        return card

    # ------------------------------------------------------------ 底部操作
    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        progress_row.addWidget(self.progress, 1)
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("Percent")
        self.percent_label.setFixedWidth(46)
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        progress_row.addWidget(self.percent_label)
        layout.addLayout(progress_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("Status")
        action_row.addWidget(self.status_label, 1)
        self.pause_button = QPushButton("暂停")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self._on_pause_toggle)
        action_row.addWidget(self.pause_button)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        action_row.addWidget(self.cancel_button)

        self.open_button = QPushButton("打开输出文件夹")
        self.open_button.clicked.connect(self._open_output_dir)
        action_row.addWidget(self.open_button)
        self.generate_button = QPushButton("开始生成 PDF")
        self.generate_button.setObjectName("Accent")
        self.generate_button.clicked.connect(self._on_primary_action)
        action_row.addWidget(self.generate_button)
        layout.addLayout(action_row)
        return bar

    # ================================================================ 主题
    def _apply_theme(self) -> None:
        palette = self.theme_manager.palette
        app = QApplication.instance()
        if app is not None:
            theme.apply_palette(app, palette)
        self.setStyleSheet(theme.build_qss(palette))
        theme.set_dark_titlebar(self, palette.is_dark)
        self.theme_button.setIcon(
            QIcon(theme.SUN_ICON if palette.is_dark else theme.MOON_ICON))
        self.theme_button.setToolTip(
            "切换到浅色模式" if palette.is_dark else "切换到深色模式")
        if hasattr(self, "nav"):
            self.nav.viewport().update()
        self._refresh_folder_table()
        self._refresh_image_table()

    def _toggle_theme(self) -> None:
        current = self.theme_manager.palette
        self.theme_manager.set_mode("light" if current.is_dark else "dark")

    def _check_system_theme(self) -> None:
        if self.theme_manager.mode == "system":
            self.theme_manager.refresh()

    # ================================================================ 导航
    def _on_nav_changed(self, row: int) -> None:
        if not hasattr(self, "stack"):
            return
        self.stack.setCurrentIndex(row)
        if hasattr(self, "_output_card"):
            self._output_card.setVisible(row <= 1)
        self._update_page_text(row)
        self._refresh_status()
        fade_in_widget(self.stack.currentWidget())

    def _update_page_text(self, row: int) -> None:
        titles = {
            0: ("按文件夹合并",
                "每个文件夹生成一个同名 PDF；也可以让每个子文件夹分别生成 PDF，或全部合并成一个。"),
            1: ("按图片合并",
                "选择多张图片，按编号顺序合并成一个 PDF，默认使用第一张图片的名称。"),
            2: ("图片格式转换",
                "在 JPG、PNG、WebP、BMP、GIF、TIFF 之间批量转换图片格式。"),
            3: ("视频格式转换",
                "在 MP4、MKV、MOV、AVI、FLV、WMV、WebM 之间转换，支持硬件加速与字幕处理。"),
            4: ("音频格式转换",
                "在 MP3、AAC、M4A、FLAC、WAV、WMA、OGG 之间批量转换音频格式。"),
            5: ("字幕音轨提取",
                "从视频中把字幕轨导出为 SRT / ASS，或单独提取音轨。"),
        }
        title, subtitle = titles.get(row, titles[0])
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        self._update_primary_button(row)

    # ================================================================ 文件夹操作
    def _add_folders(self) -> None:
        if self._busy:
            return
        dialog = FolderPickerDialog(self, initial_dir=self._last_dir)
        accepted = dialog.exec() == FolderPickerDialog.Accepted
        chosen = list(dialog.result) if accepted else []
        dialog.deleteLater()
        if not accepted or not chosen:
            return

        self._last_dir = str(chosen[0].parent)
        mode = self._output_mode_key()
        sort_mode = self._sort_mode_key()

        added = 0
        empty: list[str] = []
        for folder in chosen:
            if any(self._same_path(task.folder, folder) for task in self.folder_tasks):
                continue
            entries = scanner.scan_for_mode(folder, mode, sort_mode)
            if not entries:
                empty.append(folder.name)
                continue
            self.folder_tasks.append(FolderTask(folder=folder, images=[]))
            self._folder_entries[folder] = entries
            added += 1

        self._refresh_folder_table()
        self._refresh_status()
        if added:
            self._log(f"已添加 {added} 个文件夹")
        if empty:
            QMessageBox.information(
                self, "部分文件夹已跳过",
                "以下文件夹里没有找到图片，已跳过：\n\n" + "\n".join(empty[:12]))

    def _remove_folders(self) -> None:
        if self._busy:
            return
        rows = sorted({index.row() for index in self.folder_table.selectionModel().selectedRows()},
                      reverse=True)
        for row in rows:
            if 0 <= row < len(self.folder_tasks):
                task = self.folder_tasks.pop(row)
                self._folder_entries.pop(task.folder, None)
        if rows:
            self._refresh_folder_table()
            self._refresh_status()

    def _clear_folders(self) -> None:
        if self._busy or not self.folder_tasks:
            return
        self.folder_tasks.clear()
        self._folder_entries.clear()
        self._refresh_folder_table()
        self._refresh_status()

    def _move_folder(self, delta: int) -> None:
        if self._busy:
            return
        rows = self.folder_table.selectionModel().selectedRows()
        if len(rows) != 1:
            if rows:
                QMessageBox.information(self, "请选择一个", "上移 / 下移一次只能移动一个文件夹。")
            return
        index = rows[0].row()
        target = index + delta
        if not (0 <= target < len(self.folder_tasks)):
            return
        tasks = self.folder_tasks
        tasks[index], tasks[target] = tasks[target], tasks[index]
        self._refresh_folder_table()
        self.folder_table.selectRow(target)

    def _preview_folder(self, row: int, _column: int) -> None:
        if not (0 <= row < len(self.folder_tasks)):
            return
        task = self.folder_tasks[row]
        jobs = self._jobs_for_task(task)
        dialog = PlanPreviewDialog(self, f"生成计划 · {task.folder.name}", jobs)
        dialog.exec()
        dialog.deleteLater()

    def _jobs_for_task(self, task: FolderTask) -> list[Job]:
        mode = self._output_mode_key()
        sort_mode = self._sort_mode_key()
        jobs: list[Job] = []
        for target, images in scanner.scan_for_mode(task.folder, mode, sort_mode):
            if not images:
                continue
            jobs.append(Job(name=safe_name(target.name), images=images,
                            source_dir=target.parent, folder=target))
        return jobs

    def _rescan_folders(self) -> None:
        if self._busy:
            return
        mode = self._output_mode_key()
        sort_mode = self._sort_mode_key()
        for task in self.folder_tasks:
            self._folder_entries[task.folder] = scanner.scan_for_mode(
                task.folder, mode, sort_mode)
        self._refresh_folder_table()
        self._refresh_status()

    def _refresh_folder_table(self) -> None:
        if not hasattr(self, "folder_table"):
            return
        palette = self.theme_manager.palette
        table = self.folder_table
        table.setRowCount(len(self.folder_tasks))
        mode = self._output_mode_key()

        if not self.folder_tasks:
            table.set_empty_hint(
                "还没有添加文件夹\n点击「＋ 添加文件夹」开始，可一次勾选多个文件夹")
        else:
            table.set_empty_hint("")

        for index, task in enumerate(self.folder_tasks):
            entries = self._folder_entries.get(task.folder)
            if entries is None:
                entries = scanner.scan_for_mode(task.folder, mode, self._sort_mode_key())
                self._folder_entries[task.folder] = entries
            image_count = sum(len(images) for _target, images in entries)
            if len(entries) <= 1:
                output_text = f"{entries[0][0].name}.pdf" if entries else "—"
            else:
                output_text = f"{len(entries)} 个 PDF"

            values = [str(index + 1), task.folder.name, str(image_count), output_text,
                      task.status]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 2):
                    item.setTextAlignment(Qt.AlignCenter)
                elif column == 4:
                    item.setTextAlignment(Qt.AlignCenter)
                table.setItem(index, column, item)

            status_item = table.item(index, 4)
            if status_item is not None:
                color = {
                    "已完成": palette.success,
                    "失败": palette.danger,
                    "部分失败": palette.danger,
                    "无图片": palette.text_tertiary,
                }.get(task.status)
                if color:
                    status_item.setForeground(QBrush(QColor(color)))

    # ================================================================ 图片操作
    def _add_images(self) -> None:
        if self._busy:
            return
        patterns = " ".join(f"*{ext}" for ext in sorted(scanner.IMAGE_EXTS))
        files, _selected = QFileDialog.getOpenFileNames(
            self, "选择图片（可多选）", self._last_dir,
            f"图片文件 ({patterns});;所有文件 (*.*)")
        if not files:
            return

        self._last_dir = str(Path(files[0]).parent)
        existing = {str(path).lower() for path in self.image_paths}
        added = 0
        ignored: list[str] = []
        for text in files:
            path = Path(text)
            if not scanner.is_image(path):
                ignored.append(path.name)
                continue
            key = str(path).lower()
            if key in existing:
                continue
            self.image_paths.append(path)
            existing.add(key)
            added += 1

        if added:
            self.image_paths = scanner.sort_images(self.image_paths, scanner.SORT_NATURAL)
            self._refresh_image_table()
            self._sync_image_name()
            self._refresh_status()
            self._log(f"已添加 {added} 张图片")
        if ignored:
            QMessageBox.information(
                self, "部分文件已忽略",
                "以下文件不是支持的图片格式，已忽略：\n\n" + "\n".join(ignored[:12]))

    def _remove_images(self) -> None:
        if self._busy:
            return
        rows = sorted({index.row() for index in self.image_table.selectionModel().selectedRows()},
                      reverse=True)
        for row in rows:
            if 0 <= row < len(self.image_paths):
                self.image_paths.pop(row)
        if rows:
            self._refresh_image_table()
            self._sync_image_name()
            self._refresh_status()

    def _clear_images(self) -> None:
        if self._busy or not self.image_paths:
            return
        self.image_paths.clear()
        self._refresh_image_table()
        self._sync_image_name()
        self._refresh_status()

    def _move_image(self, delta: int) -> None:
        if self._busy:
            return
        rows = self.image_table.selectionModel().selectedRows()
        if len(rows) != 1:
            if rows:
                QMessageBox.information(self, "请选择一个", "上移 / 下移一次只能移动一张图片。")
            return
        index = rows[0].row()
        target = index + delta
        if not (0 <= target < len(self.image_paths)):
            return
        paths = self.image_paths
        paths[index], paths[target] = paths[target], paths[index]
        self._refresh_image_table()
        self.image_table.selectRow(target)
        self._sync_image_name()

    def _resort_images(self) -> None:
        if self._busy or not self.image_paths:
            return
        self.image_paths = scanner.sort_images(self.image_paths, scanner.SORT_NATURAL)
        self._refresh_image_table()
        self._sync_image_name()

    def _refresh_image_table(self) -> None:
        if not hasattr(self, "image_table"):
            return
        table = self.image_table
        table.setRowCount(len(self.image_paths))
        if not self.image_paths:
            table.set_empty_hint(
                "还没有添加图片\n点击「＋ 添加图片」开始，可一次选择多张图片")
        else:
            table.set_empty_hint("")
        for index, path in enumerate(self.image_paths):
            try:
                size_kb = path.stat().st_size / 1024
                size_text = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            except OSError:
                size_text = "—"
            values = [str(index + 1), path.name, scanner.format_label(path),
                      size_text, path.parent.name]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 2):
                    item.setTextAlignment(Qt.AlignCenter)
                elif column == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(index, column, item)

    def _sync_image_name(self) -> None:
        if not self.image_paths:
            self.image_name_edit.clear()
            self._last_auto_name = ""
            return
        auto_name = self.image_paths[0].stem
        current = self.image_name_edit.text().strip()
        if not current or current == self._last_auto_name:
            self.image_name_edit.setText(auto_name)
        self._last_auto_name = auto_name

    # ================================================================ 输出设置
    def _output_mode_key(self) -> str:
        return OUTPUT_LABEL_TO_KEY.get(self.subfolder_combo.currentText(),
                                       scanner.OUTPUT_SINGLE)

    def _sort_mode_key(self) -> str:
        return SORT_LABEL_TO_KEY.get(self.sort_combo.currentText(), scanner.SORT_NATURAL)

    def _on_output_mode_changed(self, _checked: bool = False) -> None:
        custom = self.radio_custom.isChecked()
        self.output_edit.setEnabled(custom)

    def _on_page_size_changed(self, _index: int) -> None:
        custom = self._page_size_key() == "custom"
        self.custom_size_widget.setVisible(custom)
        if custom and not self.custom_width_edit.text().strip():
            self.custom_width_edit.setText("210")
            self.custom_height_edit.setText("297")

    def _page_size_key(self) -> str:
        return PAGE_LABEL_TO_KEY.get(self.page_size_combo.currentText(), "auto")

    def _page_size_mm(self):
        key = self._page_size_key()
        if key == "auto":
            return None
        if key == "custom":
            try:
                width = float(self.custom_width_edit.text())
                height = float(self.custom_height_edit.text())
            except ValueError:
                return (210.0, 297.0)
            return (min(2000.0, max(10.0, width)), min(2000.0, max(10.0, height)))
        for preset_key, _label, size in PAGE_PRESETS:
            if preset_key == key:
                return size
        return None

    def _conflict_key(self) -> str:
        return CONFLICT_KEYS.get(self.conflict_combo.currentText(), "auto")

    def _browse_output_dir(self) -> None:
        initial = self.output_edit.text().strip() or self._last_dir
        chosen = QFileDialog.getExistingDirectory(self, "选择输出文件夹", initial)
        if chosen:
            self.output_edit.setText(chosen)
            self.radio_custom.setChecked(True)
            self.output_edit.setEnabled(True)

    # ================================================================ 生成
    def _build_jobs(self) -> list[Job]:
        if self.stack.currentIndex() == 0:
            mode = self._output_mode_key()
            sort_mode = self._sort_mode_key()
            jobs: list[Job] = []
            self._task_job_total = {}
            self._task_counts = {}
            for root_index, task in enumerate(self.folder_tasks):
                entries = scanner.scan_for_mode(task.folder, mode, sort_mode)
                self._folder_entries[task.folder] = entries
                task.images = [image for _target, images in entries for image in images]
                count = 0
                for target, images in entries:
                    if not images:
                        continue
                    jobs.append(Job(
                        name=safe_name(target.name),
                        images=images,
                        source_dir=target.parent,
                        folder=target,
                        task_index=root_index,
                    ))
                    count += 1
                self._task_job_total[root_index] = count
            self._refresh_folder_table()
            if not jobs:
                QMessageBox.information(self, "没有可处理的图片",
                                        "所选文件夹里没有找到可合并的图片。")
            return jobs

        images = [path for path in self.image_paths if path.exists()]
        missing = [path for path in self.image_paths if not path.exists()]
        for path in missing:
            self._log(f"文件已不存在，跳过：{path}")
        if not images:
            QMessageBox.information(self, "还没有图片", "请先添加图片。")
            return []
        name = self.image_name_edit.text().strip()
        return plan_image_jobs(images, name)

    def _on_generate(self) -> None:
        if self._busy:
            return
        if self.radio_custom.isChecked():
            target = self.output_edit.text().strip()
            if not target or not Path(target).is_dir():
                QMessageBox.warning(self, "输出位置无效",
                                    "请选择一个存在的输出文件夹，或改回「源文件夹所在位置」。")
                return

        jobs = self._build_jobs()
        if not jobs:
            return

        non_jpg = [path for job in jobs for path in job.images if not scanner.is_jpg(path)]
        if non_jpg:
            dialog = ConvertNoticeDialog(self, non_jpg)
            accepted = dialog.exec() == ConvertNoticeDialog.Accepted
            confirmed = dialog.confirmed
            dialog.deleteLater()
            if not accepted or not confirmed:
                self._log("已取消：没有确认格式转换")
                return

        self._start_jobs(jobs)

    def _start_jobs(self, jobs: list[Job]) -> None:
        self._generated = []
        self._busy = True
        self._set_busy_state(True)
        self.progress.setValue(0)
        self.percent_label.setText("0%")
        self.status_label.setText("正在准备…")
        for task in self.folder_tasks:
            task.status = "等待中"
        self._task_counts = {}
        self._refresh_folder_table()
        self._log("")
        self._log(f"开始生成：{len(jobs)} 个 PDF，共 "
                  f"{sum(len(job.images) for job in jobs)} 张图片")

        options = {
            "output_mode": "custom" if self.radio_custom.isChecked() else "source",
            "output_dir": self.output_edit.text().strip(),
            "conflict": self._conflict_key(),
            "page_size_mm": self._page_size_mm(),
            "quality": 95,
        }
        self._worker_thread = threading.Thread(target=self._worker, args=(jobs, options),
                                               daemon=True)
        self._worker_thread.start()

    def _worker(self, jobs: list[Job], options: dict) -> None:
        total = len(jobs)
        steps_total = sum(len(job.images) + 2 for job in jobs) or 1
        steps_done = 0
        succeeded = 0
        skipped = 0
        failed: list[tuple[str, str]] = []
        generated: list[str] = []
        started = time.time()
        temp_dir: Path | None = None

        def advance(text: str) -> None:
            nonlocal steps_done
            steps_done = min(steps_done + 1, steps_total)
            self._bridge.progress.emit(steps_done / steps_total, text)

        try:
            for index, job in enumerate(jobs, 1):
                self._bridge.log.emit(
                    f"[{index}/{total}] {job.name}（{len(job.images)} 张图片）")
                advance(f"准备：{job.name}")
                root_index = job.task_index if job.task_index is not None else -1
                try:
                    images = list(job.images)
                    if any(not scanner.is_jpg(path) for path in images):
                        if temp_dir is None:
                            temp_dir = Path(tempfile.mkdtemp(prefix="pdf_producer_"))
                        target_dir = temp_dir / f"{index:02d}"
                        prepared: list[Path] = []
                        converted = 0
                        for path in images:
                            if scanner.is_jpg(path):
                                prepared.append(path)
                            else:
                                converted += 1
                                prepared.append(convert_to_jpg(path, target_dir))
                                if converted == 1 or converted % 20 == 0:
                                    self._bridge.log.emit(
                                        f"  · 已转换 {converted} 张（当前：{path.name}）")
                            advance(f"转换格式：{path.name}")
                        images = prepared

                    output = resolve_output_path(job, options)
                    if output is None:
                        skipped += 1
                        self._bridge.log.emit("  · 同名文件已存在，按设置跳过")
                        advance(f"跳过：{job.name}")
                        advance(f"跳过：{job.name}")
                        self._bridge.job_done.emit(root_index, "skip")
                        continue

                    advance(f"正在写入：{output.name}")
                    build_pdf(images, output,
                              page_size_mm=options["page_size_mm"],
                              quality=options["quality"],
                              log=lambda text: self._bridge.log.emit(text))
                    advance(f"完成：{output.name}")
                    succeeded += 1
                    generated.append(str(output))
                    self._bridge.log.emit(f"  · 已生成：{output}")
                    self._bridge.job_done.emit(root_index, "ok")
                except Exception as exc:  # noqa: BLE001
                    failed.append((job.name, str(exc)))
                    self._bridge.log.emit(f"  · 失败：{exc}")
                    advance(f"失败：{job.name}")
                    self._bridge.job_done.emit(root_index, "fail")
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
            self._bridge.finished.emit({
                "total": total,
                "succeeded": succeeded,
                "skipped": skipped,
                "failed": failed,
                "generated": generated,
                "elapsed": time.time() - started,
            })

    # ================================================================ 回调
    def _on_progress(self, fraction: float, text: str) -> None:
        self.progress.setValue(int(fraction * 1000))
        self.percent_label.setText(f"{int(fraction * 100)}%")
        self.status_label.setText(text)

    def _on_job_done(self, root_index: int, result: str) -> None:
        if root_index < 0 or not (0 <= root_index < len(self.folder_tasks)):
            return
        counts = self._task_counts.setdefault(root_index, {"ok": 0, "skip": 0, "fail": 0})
        counts[result] = counts.get(result, 0) + 1
        self._update_task_status(root_index)

    def _update_task_status(self, root_index: int) -> None:
        counts = self._task_counts.get(root_index, {"ok": 0, "skip": 0, "fail": 0})
        total = self._task_job_total.get(root_index, 0)
        done = counts.get("ok", 0) + counts.get("skip", 0) + counts.get("fail", 0)
        if counts.get("fail", 0):
            status = "部分失败" if counts.get("ok", 0) else "失败"
        elif done < total:
            status = f"进行中 {done}/{total}"
        else:
            status = "已完成" if counts.get("ok", 0) else "跳过"
        self.folder_tasks[root_index].status = status
        self._refresh_folder_row_status(root_index)

    def _refresh_folder_row_status(self, root_index: int) -> None:
        if not (0 <= root_index < self.folder_table.rowCount()):
            return
        palette = self.theme_manager.palette
        status = self.folder_tasks[root_index].status
        item = self.folder_table.item(root_index, 4)
        if item is None:
            item = QTableWidgetItem(status)
            item.setTextAlignment(Qt.AlignCenter)
            self.folder_table.setItem(root_index, 4, item)
        else:
            item.setText(status)
        color = {
            "已完成": palette.success,
            "失败": palette.danger,
            "部分失败": palette.danger,
        }.get(status)
        item.setForeground(QBrush(QColor(color)) if color else QBrush(QColor(palette.text)))

    def _on_finished(self, info: dict) -> None:
        self._busy = False
        self._set_busy_state(False)
        self.progress.setValue(1000)
        self.percent_label.setText("100%")
        self._generated = list(info["generated"]) 

        parts: list[str] = []
        if info["succeeded"]:
            parts.append(f"成功 {info['succeeded']} 个")
        if info["skipped"]:
            parts.append(f"跳过 {info['skipped']} 个")
        if info["failed"]:
            parts.append(f"失败 {len(info['failed'])} 个")
        summary = "、".join(parts) if parts else "没有生成文件"
        summary += f"，用时 {info['elapsed']:.1f} 秒"
        self.status_label.setText("完成：" + summary)
        self._log(f"完成：{summary}")

        self._refresh_folder_table()

        if info["failed"]:
            detail = "\n".join(f"· {name}：{error}" for name, error in info["failed"][:6])
            QMessageBox.warning(self, "部分任务失败",
                                f"有 {len(info['failed'])} 个任务没有成功：\n\n{detail}")
        if info["generated"]:
            if self._ask_yes_no("生成完成",
                                f"已生成 {info['succeeded']} 个 PDF 文件。\n\n是否打开输出文件夹查看？",
                                "打开文件夹", "稍后查看"):
                self._open_output_dir()

    def _ask_yes_no(self, title: str, text: str, yes_text: str, no_text: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Question)
        yes_button = box.addButton(yes_text, QMessageBox.YesRole)
        no_button = box.addButton(no_text, QMessageBox.NoRole)
        box.setDefaultButton(no_button)
        box.exec()
        return box.clickedButton() is yes_button

    def _set_busy_state(self, busy: bool) -> None:
        for widget in (self.add_folder_button, self.folder_remove_button,
                       self.folder_clear_button, self.folder_up_button,
                       self.folder_down_button, self.add_image_button,
                       self.image_remove_button, self.image_clear_button,
                       self.image_up_button, self.image_down_button,
                       self.image_sort_button, self.open_button):
            widget.setEnabled(not busy)
        self.generate_button.setEnabled(not busy)
        if busy:
            self.generate_button.setText("正在处理…")
        else:
            self._update_primary_button(self.stack.currentIndex())

    def _update_primary_button(self, index: int) -> None:
        labels = {
            0: "开始生成 PDF",
            1: "开始生成 PDF",
            2: "开始转换",
            3: "开始转换",
            4: "开始转换",
            5: "开始提取",
        }
        if not self._busy:
            self.generate_button.setText(labels.get(index, "开始"))

    def _on_primary_action(self) -> None:
        if self._busy:
            return
        index = self.stack.currentIndex()
        if index <= 1:
            self._on_generate()
            return
        page = self.stack.currentWidget()
        if not hasattr(page, "start"):
            return
        if not page.start():
            return
        self._busy = True
        self._set_busy_state(True)
        self.progress.setValue(0)
        self.percent_label.setText("0%")
        self.status_label.setText("正在处理…")

    def _on_convert_state(self, running: bool, paused: bool) -> None:
        self.pause_button.setEnabled(running)
        self.cancel_button.setEnabled(running)
        self.pause_button.setText("继续" if paused else "暂停")

    def _on_pause_toggle(self) -> None:
        index = self.stack.currentIndex()
        if index < 2:
            return
        page = self.stack.currentWidget()
        if hasattr(page, "toggle_pause"):
            page.toggle_pause()

    def _on_cancel(self) -> None:
        index = self.stack.currentIndex()
        if index < 2:
            return
        page = self.stack.currentWidget()
        if hasattr(page, "cancel"):
            page.cancel()
            self._log("已请求取消当前任务…")

    def _on_convert_finished(self, info: dict) -> None:
        self._busy = False
        self._set_busy_state(False)
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.pause_button.setText("暂停")
        self.progress.setValue(1000)
        self.percent_label.setText("100%")

        if info.get("cancelled"):
            self.status_label.setText(f"已取消（已完成 {info['ok']} 个）")
            self._log(f"已取消：已完成 {info['ok']} 个，半成品已删除")
            return

        parts: list[str] = []
        if info.get("ok"):
            parts.append(f"成功 {info['ok']} 个")
        if info.get("fail"):
            parts.append(f"失败 {info['fail']} 个")
        summary = "、".join(parts) if parts else "没有生成文件"
        self.status_label.setText("完成：" + summary)
        self._log(f"完成：{summary}")

        if info.get("errors"):
            detail = "\n".join(info["errors"][:6])
            QMessageBox.warning(self, "部分任务失败",
                                f"有 {info['fail']} 个任务失败：\n\n{detail}")
        if info.get("outputs"):
            if self._ask_yes_no("处理完成",
                                f"已生成 {info['ok']} 个文件。\n\n是否打开输出文件夹查看？",
                                "打开文件夹", "稍后查看"):
                self._open_output_dir()

    # ================================================================ 其他
    def _log(self, text: str) -> None:
        if not text:
            return
        self.log_view.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    def _refresh_status(self) -> None:
        if self._busy:
            return
        index = self.stack.currentIndex()
        if index == 0:
            count = len(self.folder_tasks)
            if count == 0:
                self.status_label.setText("就绪：点击「＋ 添加文件夹」开始，可一次勾选多个文件夹")
                return
            images = sum(len(images) for entries in self._folder_entries.values()
                         for _target, images in entries)
            pdfs = sum(len(entries) for entries in self._folder_entries.values())
            self.status_label.setText(
                f"当前：{count} 个文件夹，{images} 张图片，将生成 {pdfs} 个 PDF")
        elif index == 1:
            count = len(self.image_paths)
            if count == 0:
                self.status_label.setText("就绪：点击「＋ 添加图片」开始，可一次选择多张图片")
            else:
                self.status_label.setText(f"当前：{count} 张图片，将合并成 1 个 PDF")
        else:
            labels = {2: "图片格式转换", 3: "视频格式转换", 4: "音频格式转换", 5: "字幕音轨提取"}
            self.status_label.setText(
                f"就绪：{labels.get(index, '')}，添加文件后点击底部按钮开始")

    def _open_output_dir(self) -> None:
        index = self.stack.currentIndex()
        if index >= 2:
            page = self.stack.currentWidget()
            target = page.output_dir() if hasattr(page, "output_dir") else None
            if target is None:
                target = Path.home()
        elif self.radio_custom.isChecked() and self.output_edit.text().strip():
            target = Path(self.output_edit.text().strip())
        elif self._generated:
            target = Path(self._generated[0]).parent
        elif self.folder_tasks:
            target = self.folder_tasks[0].folder.parent
        elif self.image_paths:
            target = self.image_paths[0].parent
        else:
            target = Path.home()
        if not target.is_dir():
            QMessageBox.information(self, "无法打开", f"文件夹不存在：\n{target}")
            return
        try:
            os.startfile(str(target))  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            QMessageBox.information(self, "无法打开", f"打开文件夹失败：\n{exc}")

    @staticmethod
    def _same_path(a: Path, b: Path) -> bool:
        try:
            return a.resolve().as_posix().lower() == b.resolve().as_posix().lower()
        except OSError:
            return str(a).lower() == str(b).lower()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_shown_once", False):
            self._shown_once = True
            fade_in_window(self, 220)

    def closeEvent(self, event) -> None:
        if self._busy:
            if not self._ask_yes_no("正在生成",
                                    "还有任务正在生成，现在退出会中断当前任务。\n\n确定要退出吗？",
                                    "退出", "继续等待"):
                event.ignore()
                return
        event.accept()
