"""格式转换页面：图片格式转换 / 视频格式转换 / 音频格式转换。"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.image_convert import (
    ICO_SIZES,
    IMAGE_TARGETS,
    convert_image,
    convert_to_ico,
    render_ico_image,
)
from core.media import (
    AUDIO_TARGETS,
    VIDEO_TARGETS,
    ConversionCancelled,
    ProcessController,
    convert_audio,
    convert_video,
)
from ui import theme
from ui.widgets import CardHeader, ComboBox, SectionCard, make_table

KIND_LABELS = {"image": "图片", "video": "视频", "audio": "音频"}

VIDEO_EXTENSIONS = (
    ".mkv", ".mp4", ".avi", ".flv", ".mov", ".wmv", ".webm",
    ".m4v", ".ts", ".mpg", ".mpeg", ".3gp",
)
AUDIO_EXTENSIONS = (
    ".mp3", ".aac", ".flac", ".m4a", ".wav", ".wma", ".ogg", ".opus", ".ac3",
)
IMAGE_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif",
)

TARGET_LABELS = {
    "image": {key: spec["label"] for key, spec in IMAGE_TARGETS.items()},
    "video": {key: spec.label for key, spec in VIDEO_TARGETS.items()},
    "audio": {key: spec.label for key, spec in AUDIO_TARGETS.items()},
}

HARDWARE_OPTIONS = [
    ("auto", "自动（优先硬件加速）"),
    ("software", "仅软件编码"),
    ("nvidia", "NVIDIA（NVENC）"),
    ("amd", "AMD（AMF）"),
    ("intel", "Intel（QSV）"),
]

SUBTITLE_OPTIONS = [
    ("auto", "自动（目标格式支持时保留字幕）"),
    ("embed", "嵌入视频（不支持的格式自动烧录）"),
    ("export_srt", "导出字幕文件（SRT）"),
    ("export_ass", "导出字幕文件（ASS）"),
    ("burn", "烧录到画面（硬字幕）"),
    ("ignore", "忽略字幕"),
]

QUALITY_LABELS = {"85": "标准（85）", "92": "高清（92）", "96": "超清（96）"}


class ConvertPage(QWidget):
    """图片 / 视频 / 音频的批量格式转换页面。"""

    message = Signal(str)
    progress = Signal(float, str)
    file_status = Signal(int, str)
    finished = Signal(object)
    state_changed = Signal(bool, bool)   # running, paused

    def __init__(self, kind: str, theme_manager, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.theme_manager = theme_manager
        self._paths: list[Path] = []
        self._running = False
        self._controller = ProcessController()
        self.setAcceptDrops(True)
        self.file_status.connect(self._on_file_status)
        self._build()

    # ------------------------------------------------------------------ 界面
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        card = SectionCard()
        card.body.addWidget(CardHeader(
            f"待转换的{KIND_LABELS[self.kind]}",
            "支持一次添加多个文件；转换结果默认输出到源文件所在文件夹。"))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.add_button = QPushButton("＋  添加文件")
        self.add_button.clicked.connect(self._add_files)
        toolbar.addWidget(self.add_button)
        self.remove_button = QPushButton("移除选中")
        self.remove_button.clicked.connect(self._remove_selected)
        toolbar.addWidget(self.remove_button)
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self._clear)
        toolbar.addWidget(self.clear_button)
        toolbar.addStretch(1)
        card.body.addLayout(toolbar)

        self.table = make_table(
            ["序号", "文件名", "格式", "大小", "状态"],
            [56, 340, 90, 100, 110], row_height=40)
        card.body.addWidget(self.table, 1)
        layout.addWidget(card, 1)

        settings = SectionCard()
        settings.body.addWidget(CardHeader("转换设置"))

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(QLabel("目标格式"))
        self.target_combo = ComboBox()
        for key, label in TARGET_LABELS[self.kind].items():
            self.target_combo.addItem(label, key)
        self.target_combo.setMinimumWidth(150)
        row1.addWidget(self.target_combo)

        if self.kind == "image":
            row1.addSpacing(16)
            row1.addWidget(QLabel("输出质量"))
            self.quality_slider = QSlider(Qt.Horizontal)
            self.quality_slider.setRange(10, 100)
            self.quality_slider.setValue(92)
            self.quality_slider.setSingleStep(1)
            self.quality_slider.setFixedWidth(200)
            self.quality_slider.valueChanged.connect(self._on_quality_changed)
            row1.addWidget(self.quality_slider)
            self.quality_value_label = QLabel("92")
            self.quality_value_label.setObjectName("Hint")
            self.quality_value_label.setMinimumWidth(32)
            row1.addWidget(self.quality_value_label)

        if self.kind == "video":
            row1.addSpacing(16)
            row1.addWidget(QLabel("硬件加速"))
            self.hardware_combo = ComboBox()
            for value, label in HARDWARE_OPTIONS:
                self.hardware_combo.addItem(label, value)
            self.hardware_combo.setMinimumWidth(190)
            row1.addWidget(self.hardware_combo)

        row1.addStretch(1)
        settings.body.addLayout(row1)

        if self.kind == "image":
            self.ico_panel = QWidget()
            ico_layout = QVBoxLayout(self.ico_panel)
            ico_layout.setContentsMargins(0, 0, 0, 0)
            ico_layout.setSpacing(8)

            size_row = QHBoxLayout()
            size_row.setSpacing(6)
            size_row.addWidget(QLabel("图标尺寸"))
            self.ico_size_checks: dict[int, QCheckBox] = {}
            for size in ICO_SIZES:
                check = QCheckBox(str(size))
                check.setChecked(size in (16, 24, 32, 48, 64, 128, 256))
                check.toggled.connect(self._on_ico_settings_changed)
                self.ico_size_checks[size] = check
                size_row.addWidget(check)
            size_row.addStretch(1)
            ico_layout.addLayout(size_row)

            option_row = QHBoxLayout()
            option_row.setSpacing(8)
            option_row.addWidget(QLabel("空白区域"))
            self.ico_background_combo = ComboBox()
            self.ico_background_combo.addItem("透明", "transparent")
            self.ico_background_combo.addItem("白色填充", "white")
            self.ico_background_combo.currentIndexChanged.connect(
                self._on_ico_settings_changed)
            option_row.addWidget(self.ico_background_combo)
            option_row.addSpacing(14)
            option_row.addWidget(QLabel("边缘"))
            self.ico_corner_combo = ComboBox()
            self.ico_corner_combo.addItem("圆角", "round")
            self.ico_corner_combo.addItem("矩形", "square")
            self.ico_corner_combo.currentIndexChanged.connect(
                self._on_ico_settings_changed)
            option_row.addWidget(self.ico_corner_combo)
            option_row.addSpacing(14)
            size_hint = QLabel("ICO 规范最大 256×256，勾选更大尺寸时会按 256 输出")
            size_hint.setObjectName("Hint")
            option_row.addWidget(size_hint)
            option_row.addStretch(1)
            ico_layout.addLayout(option_row)

            preview_row = QHBoxLayout()
            preview_row.setSpacing(12)
            self.ico_preview = QLabel("添加图片后显示预览")
            self.ico_preview.setObjectName("Preview")
            self.ico_preview.setFixedSize(168, 168)
            self.ico_preview.setAlignment(Qt.AlignCenter)
            preview_row.addWidget(self.ico_preview)
            preview_row.addStretch(1)
            ico_layout.addLayout(preview_row)

            self.ico_panel.setVisible(False)
            settings.body.addWidget(self.ico_panel)
            self.target_combo.currentIndexChanged.connect(self._on_target_changed)

        if self.kind == "video":
            row2 = QHBoxLayout()
            row2.setSpacing(10)
            row2.addWidget(QLabel("字幕处理"))
            self.subtitle_combo = ComboBox()
            for value, label in SUBTITLE_OPTIONS:
                self.subtitle_combo.addItem(label, value)
            self.subtitle_combo.setMinimumWidth(280)
            row2.addWidget(self.subtitle_combo)
            row2.addStretch(1)
            settings.body.addLayout(row2)

        output_row = QHBoxLayout()
        output_row.setSpacing(10)
        output_row.addWidget(QLabel("输出位置"))
        self.radio_source = QRadioButton("源文件夹")
        self.radio_source.setChecked(True)
        self.radio_source.toggled.connect(self._on_output_mode_changed)
        self.radio_custom = QRadioButton("指定文件夹")
        output_row.addWidget(self.radio_source)
        output_row.addWidget(self.radio_custom)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("选择输出文件夹…")
        self.output_edit.setEnabled(False)
        output_row.addWidget(self.output_edit, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_output)
        output_row.addWidget(browse)
        settings.body.addLayout(output_row)

        layout.addWidget(settings)

    def _on_quality_changed(self, value: int) -> None:
        self.quality_value_label.setText(str(value))

    # ------------------------------------------------------------------ ICO
    def _on_target_changed(self, _index: int = 0) -> None:
        if self.kind != "image":
            return
        is_ico = self.target_combo.currentData() == "ico"
        self.ico_panel.setVisible(is_ico)
        if is_ico:
            self._update_ico_preview()

    def _on_ico_settings_changed(self, _value=None) -> None:
        if self.kind == "image" and self.target_combo.currentData() == "ico":
            self._update_ico_preview()

    def _ico_options(self) -> dict:
        sizes = [size for size, check in self.ico_size_checks.items()
                 if check.isChecked()]
        return {
            "sizes": sorted(sizes) or [256],
            "background": self.ico_background_combo.currentData(),
            "corner": self.ico_corner_combo.currentData(),
        }

    def _update_ico_preview(self) -> None:
        if self.kind != "image":
            return
        if self.target_combo.currentData() != "ico":
            return
        if not self._paths:
            self.ico_preview.setPixmap(QPixmap())
            self.ico_preview.setText("添加图片后显示预览")
            return
        options = self._ico_options()
        try:
            image = render_ico_image(self._paths[0], 256,
                                     options["background"], options["corner"])
            try:
                pixmap = self._pil_to_pixmap(image)
            finally:
                image.close()
            self.ico_preview.setText("")
            self.ico_preview.setPixmap(
                pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:  # noqa: BLE001
            self.ico_preview.setPixmap(QPixmap())
            self.ico_preview.setText("无法预览")

    @staticmethod
    def _pil_to_pixmap(image) -> QPixmap:
        rgba = image.convert("RGBA")
        try:
            data = rgba.tobytes("raw", "RGBA")
            qimage = QImage(data, rgba.width, rgba.height,
                            QImage.Format_RGBA8888).copy()
        finally:
            rgba.close()
        return QPixmap.fromImage(qimage)

    def _on_output_mode_changed(self, _checked: bool = False) -> None:
        self.output_edit.setEnabled(self.radio_custom.isChecked())

    def _browse_output(self) -> None:
        start = self.output_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择输出文件夹", start)
        if chosen:
            self.output_edit.setText(chosen)
            self.radio_custom.setChecked(True)
            self.output_edit.setEnabled(True)

    # ------------------------------------------------------------------ 文件
    def _extensions(self) -> tuple[str, ...]:
        if self.kind == "image":
            return IMAGE_EXTENSIONS
        if self.kind == "video":
            return VIDEO_EXTENSIONS
        return AUDIO_EXTENSIONS

    def _add_files(self) -> None:
        if self._running:
            return
        patterns = " ".join(f"*{ext}" for ext in self._extensions())
        caption = f"选择{KIND_LABELS[self.kind]}文件（可多选）"
        files, _selected = QFileDialog.getOpenFileNames(
            self, caption, str(Path.home()),
            f"{KIND_LABELS[self.kind]}文件 ({patterns});;所有文件 (*.*)")
        if not files:
            return
        self._add_paths([Path(text) for text in files])

    def _add_paths(self, files: list[Path]) -> None:
        existing = {str(path).lower() for path in self._paths}
        added = 0
        for path in files:
            if not path.is_file():
                continue
            if str(path).lower() in existing:
                continue
            self._paths.append(path)
            existing.add(str(path).lower())
            added += 1
        if added:
            self._refresh_table()
            self._update_ico_preview()

    # ------------------------------------------------------------------ 拖放
    def _accepts_file(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in self._extensions()

    def _files_from_drop(self, paths: list[Path]) -> list[Path]:
        found: list[Path] = []
        for path in paths:
            if self._accepts_file(path):
                found.append(path)
            elif path.is_dir():
                try:
                    found.extend(sorted(p for p in path.iterdir() if self._accepts_file(p)))
                except OSError:
                    continue
        return found

    def dragEnterEvent(self, event) -> None:
        if self._running:
            event.ignore()
            return
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if self._accepts_file(path) or path.is_dir():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls() and not self._running:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if self._running:
            event.ignore()
            return
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        files = self._files_from_drop(paths)
        if files:
            self._add_paths(files)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _remove_selected(self) -> None:
        if self._running:
            return
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()},
                      reverse=True)
        for row in rows:
            if 0 <= row < len(self._paths):
                self._paths.pop(row)
        if rows:
            self._refresh_table()
            self._update_ico_preview()

    def _clear(self) -> None:
        if self._running:
            return
        self._paths.clear()
        self._refresh_table()
        self._update_ico_preview()

    def _refresh_table(self) -> None:
        table = self.table
        table.setRowCount(len(self._paths))
        if not self._paths:
            table.set_empty_hint("还没有添加文件\n点击「＋ 添加文件」选择要转换的内容")
        else:
            table.set_empty_hint("")
        for index, path in enumerate(self._paths):
            try:
                size_mb = path.stat().st_size / (1024 * 1024)
                size_text = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{size_mb * 1024:.0f} KB"
            except OSError:
                size_text = "—"
            values = [str(index + 1), path.name, path.suffix.lstrip(".").upper(),
                      size_text, "待转换"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 2, 3):
                    item.setTextAlignment(Qt.AlignCenter if column != 3
                                          else Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(index, column, item)

    def _on_file_status(self, row: int, status: str) -> None:
        if not (0 <= row < self.table.rowCount()):
            return
        item = self.table.item(row, 4)
        if item is None:
            item = QTableWidgetItem(status)
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, item)
        else:
            item.setText(status)
        palette = self.theme_manager.palette
        color = {"完成": palette.success, "失败": palette.danger,
                 "转换中": palette.accent}.get(status)
        if color:
            item.setForeground(QBrush(QColor(color)))

    # ------------------------------------------------------------------ 转换
    def is_running(self) -> bool:
        return self._running

    def _options(self) -> dict:
        options = {
            "target": self.target_combo.currentData(),
            "custom": self.radio_custom.isChecked(),
            "output_dir": self.output_edit.text().strip(),
            "quality": 92,
        }
        if self.kind == "image":
            options["quality"] = int(self.quality_slider.value())
        if self.kind == "video":
            options["hardware"] = self.hardware_combo.currentData()
            options["subtitles"] = self.subtitle_combo.currentData()
        if self.kind == "image" and options["target"] == "ico":
            options["ico"] = self._ico_options()
        return options

    def start(self) -> bool:
        if self._running:
            return False
        if not self._paths:
            QMessageBox.information(self, "还没有文件", "请先添加要转换的文件。")
            return False
        options = self._options()
        if options["custom"]:
            folder = Path(options["output_dir"])
            if not options["output_dir"] or not folder.is_dir():
                QMessageBox.warning(self, "输出位置无效", "请选择一个存在的输出文件夹。")
                return False

        self._running = True
        self._controller = ProcessController()
        self._reset_status()
        self.state_changed.emit(True, False)
        thread = threading.Thread(target=self._worker,
                                  args=(list(self._paths), options), daemon=True)
        thread.start()
        return True

    def toggle_pause(self) -> bool:
        if not self._running:
            return False
        paused = self._controller.toggle()
        self.state_changed.emit(True, paused)
        return paused

    def cancel(self) -> None:
        if self._running:
            self._controller.cancel()

    def _reset_status(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 4)
            if item is not None:
                item.setText("待转换")
                palette = self.theme_manager.palette
                item.setForeground(QBrush(QColor(palette.text)))

    def _output_base(self, source: Path, options: dict) -> Path:
        if options["custom"]:
            folder = Path(options["output_dir"])
        else:
            folder = source.parent
        return folder / source.stem

    def _worker(self, files: list[Path], options: dict) -> None:
        total = len(files)
        succeeded = 0
        failed = 0
        errors: list[str] = []
        outputs: list[str] = []
        cancelled = False

        for index, source in enumerate(files):
            if self._controller.cancelled:
                cancelled = True
                break
            self.file_status.emit(index, "转换中")
            self.message.emit(f"[{index + 1}/{total}] {source.name}")
            base_offset = index

            def on_progress(value: float, base: int = base_offset) -> None:
                self.progress.emit((base + value) / total, f"正在转换：{source.name}")

            try:
                output_base = self._output_base(source, options)
                if self.kind == "image":
                    if options["target"] == "ico":
                        ico = options["ico"]
                        output = convert_to_ico(source, output_base, ico["sizes"],
                                                ico["background"], ico["corner"])
                    else:
                        output = convert_image(source, output_base, options["target"],
                                               quality=options["quality"])
                    outputs.append(str(output))
                elif self.kind == "audio":
                    output = convert_audio(source, output_base, options["target"],
                                           on_progress=on_progress,
                                           on_log=lambda text: self.message.emit(text),
                                           controller=self._controller)
                    outputs.append(str(output))
                else:
                    produced = convert_video(
                        source, output_base, options["target"],
                        hardware=options["hardware"],
                        subtitles=options["subtitles"],
                        on_progress=on_progress,
                        on_log=lambda text: self.message.emit(text),
                        controller=self._controller)
                    outputs.extend(str(path) for path in produced)
                succeeded += 1
                self.file_status.emit(index, "完成")
                self.message.emit(f"  · 已生成：{Path(outputs[-1]).name}")
            except ConversionCancelled:
                cancelled = True
                self.file_status.emit(index, "已取消")
                self.message.emit("  · 已取消当前任务，半成品已删除")
                break
            except Exception as exc:  # noqa: BLE001
                failed += 1
                errors.append(f"{source.name}：{exc}")
                self.file_status.emit(index, "失败")
                self.message.emit(f"  · 失败：{exc}")

        self._running = False
        self.state_changed.emit(False, False)
        self.finished.emit({
            "total": total,
            "ok": succeeded,
            "fail": failed,
            "errors": errors,
            "outputs": outputs,
            "cancelled": cancelled,
        })

    def output_dir(self) -> Path | None:
        if self.radio_custom.isChecked() and self.output_edit.text().strip():
            return Path(self.output_edit.text().strip())
        if self._paths:
            return self._paths[0].parent
        return None
