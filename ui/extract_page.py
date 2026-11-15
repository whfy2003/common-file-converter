"""字幕音轨提取页面：把视频里的字幕轨导出为 SRT/ASS，或提取音轨。"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import media
from core.media import (ConversionCancelled, ProcessController, Stream,
                         export_subtitle, extract_audio)
from ui import theme
from ui.widgets import CardHeader, ComboBox, SectionCard, make_table

VIDEO_EXTENSIONS = (
    ".mkv", ".mp4", ".avi", ".flv", ".mov", ".wmv", ".webm",
    ".m4v", ".ts", ".mpg", ".mpeg", ".3gp",
)

SUBTITLE_FORMATS = [("srt", "SRT 字幕"), ("ass", "ASS 字幕")]

AUDIO_FORMATS = [
    (None, "原样复制（不重新编码）"),
    ("m4a", "M4A"),
    ("mp3", "MP3"),
    ("aac", "AAC"),
    ("flac", "FLAC"),
    ("wav", "WAV"),
]


def _unique(base: Path, ext: str) -> Path:
    candidate = base.with_suffix(ext)
    index = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name} ({index})").with_suffix(ext)
        index += 1
    return candidate


class ExtractPage(QWidget):
    """从视频中提取字幕轨与音轨。"""

    message = Signal(str)
    progress = Signal(float, str)
    file_status = Signal(int, str)
    finished = Signal(object)
    state_changed = Signal(bool, bool)   # running, paused

    def __init__(self, theme_manager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._rows: list[tuple[Path, Stream]] = []
        self._running = False
        self._controller = ProcessController()
        self.file_status.connect(self._on_file_status)
        self._build()

    # ------------------------------------------------------------------ 界面
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        card = SectionCard()
        card.body.addWidget(CardHeader(
            "视频字幕与音轨",
            "添加视频后会列出它的字幕轨与音轨，勾选后点「开始提取」。"))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.add_button = QPushButton("＋  添加视频")
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
            ["选择", "文件", "类型", "编码", "语言 / 标题", "状态"],
            [64, 260, 80, 100, 220, 100], row_height=40)
        card.body.addWidget(self.table, 1)
        layout.addWidget(card, 1)

        settings = SectionCard()
        settings.body.addWidget(CardHeader("提取设置"))

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(QLabel("字幕格式"))
        self.subtitle_combo = ComboBox()
        for value, label in SUBTITLE_FORMATS:
            self.subtitle_combo.addItem(label, value)
        self.subtitle_combo.setMinimumWidth(150)
        row1.addWidget(self.subtitle_combo)

        row1.addSpacing(18)
        row1.addWidget(QLabel("音轨格式"))
        self.audio_combo = ComboBox()
        for value, label in AUDIO_FORMATS:
            self.audio_combo.addItem(label, value)
        self.audio_combo.setMinimumWidth(220)
        row1.addWidget(self.audio_combo)
        row1.addStretch(1)
        settings.body.addLayout(row1)

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
    def _add_files(self) -> None:
        if self._running:
            return
        patterns = " ".join(f"*{ext}" for ext in VIDEO_EXTENSIONS)
        files, _selected = QFileDialog.getOpenFileNames(
            self, "选择视频文件（可多选）", str(Path.home()),
            f"视频文件 ({patterns});;所有文件 (*.*)")
        if not files:
            return

        added = 0
        existing = {(source, stream.type_index, stream.kind)
                    for source, stream in self._rows}
        for text in files:
            path = Path(text)
            try:
                info = media.probe(path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "无法读取", f"{path.name}：\n{exc}")
                continue
            streams = info.audio_streams + info.subtitle_streams
            if not streams:
                QMessageBox.information(self, "没有可提取的轨道",
                                        f"{path.name} 里没有音频或字幕轨。")
                continue
            for stream in streams:
                key = (path, stream.type_index, stream.kind)
                if key in existing:
                    continue
                self._rows.append((path, stream))
                existing.add(key)
            added += 1
        if added:
            self._refresh_table()

    def _remove_selected(self) -> None:
        if self._running:
            return
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()},
                      reverse=True)
        for row in rows:
            if 0 <= row < len(self._rows):
                self._rows.pop(row)
        if rows:
            self._refresh_table()

    def _clear(self) -> None:
        if self._running:
            return
        self._rows.clear()
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.table
        table.setRowCount(len(self._rows))
        if not self._rows:
            table.set_empty_hint("还没有添加视频\n点击「＋ 添加视频」后会自动列出字幕轨与音轨")
        else:
            table.set_empty_hint("")

        for index, (source, stream) in enumerate(self._rows):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            default_checked = stream.kind == "audio" or stream.text_subtitle
            check_item.setCheckState(Qt.Checked if default_checked else Qt.Unchecked)
            table.setItem(index, 0, check_item)

            kind_label = "字幕" if stream.kind == "subtitle" else "音频"
            meta = " ".join(part for part in (stream.language, stream.title) if part) or "—"
            values = [source.name, kind_label, stream.codec, meta, "待提取"]
            for offset, value in enumerate(values):
                item = QTableWidgetItem(value)
                if offset in (1, 2):
                    item.setTextAlignment(Qt.AlignCenter)
                table.setItem(index, offset + 1, item)

    def _on_file_status(self, row: int, status: str) -> None:
        if not (0 <= row < self.table.rowCount()):
            return
        item = self.table.item(row, 5)
        if item is None:
            item = QTableWidgetItem(status)
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 5, item)
        else:
            item.setText(status)
        palette = self.theme_manager.palette
        color = {"完成": palette.success, "失败": palette.danger,
                 "提取中": palette.accent}.get(status)
        if color:
            item.setForeground(QBrush(QColor(color)))

    # ------------------------------------------------------------------ 提取
    def is_running(self) -> bool:
        return self._running

    def _checked_rows(self) -> list[int]:
        rows = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                rows.append(row)
        return rows

    def start(self) -> bool:
        if self._running:
            return False
        rows = self._checked_rows()
        if not rows:
            QMessageBox.information(self, "还没有选择",
                                    "请先勾选要提取的字幕轨或音轨。")
            return False
        if self.radio_custom.isChecked():
            folder = Path(self.output_edit.text().strip())
            if not self.output_edit.text().strip() or not folder.is_dir():
                QMessageBox.warning(self, "输出位置无效", "请选择一个存在的输出文件夹。")
                return False

        self._running = True
        self._controller = ProcessController()
        self._reset_status()
        self.state_changed.emit(True, False)
        targets = [(row, self._rows[row]) for row in rows]
        options = {
            "subtitle_format": self.subtitle_combo.currentData(),
            "audio_target": self.audio_combo.currentData(),
            "custom": self.radio_custom.isChecked(),
            "output_dir": self.output_edit.text().strip(),
        }
        thread = threading.Thread(target=self._worker, args=(targets, options),
                                  daemon=True)
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
            item = self.table.item(row, 5)
            if item is not None:
                item.setText("待提取")
                item.setForeground(QBrush(QColor(self.theme_manager.palette.text)))

    def _worker(self, targets: list[tuple[int, tuple[Path, Stream]]],
                options: dict) -> None:
        total = len(targets)
        succeeded = 0
        failed = 0
        errors: list[str] = []
        outputs: list[str] = []

        cancelled = False
        for position, (row, (source, stream)) in enumerate(targets):
            if self._controller.cancelled:
                cancelled = True
                break
            self.file_status.emit(row, "提取中")
            label = "字幕" if stream.kind == "subtitle" else "音轨"
            self.message.emit(f"[{position + 1}/{total}] {source.name} · {label} "
                              f"#{stream.type_index + 1}")
            base = position

            def on_progress(value: float, base: int = base) -> None:
                self.progress.emit((base + value) / total,
                                   f"正在提取：{source.name}")

            try:
                folder = self._output_folder(source, options)
                if stream.kind == "subtitle":
                    fmt = options["subtitle_format"]
                    base_path = folder / f"{source.stem}_字幕{stream.type_index + 1}"
                    output = _unique(base_path, f".{fmt}")
                    export_subtitle(source, stream, output,
                                    on_progress=on_progress,
                                    on_log=lambda text: self.message.emit(text),
                                    controller=self._controller)
                else:
                    base_path = folder / f"{source.stem}_音轨{stream.type_index + 1}"
                    output = extract_audio(source, stream, base_path,
                                           options["audio_target"],
                                           on_progress=on_progress,
                                           on_log=lambda text: self.message.emit(text),
                                           controller=self._controller)
                outputs.append(str(output))
                succeeded += 1
                self.file_status.emit(row, "完成")
                self.message.emit(f"  · 已生成：{Path(output).name}")
            except ConversionCancelled:
                cancelled = True
                self.file_status.emit(row, "已取消")
                self.message.emit("  · 已取消当前任务，半成品已删除")
                break
            except Exception as exc:  # noqa: BLE001
                failed += 1
                errors.append(f"{source.name}（{label}）：{exc}")
                self.file_status.emit(row, "失败")
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

    def _output_folder(self, source: Path, options: dict) -> Path:
        if options["custom"]:
            return Path(options["output_dir"])
        return source.parent

    def output_dir(self) -> Path | None:
        if self.radio_custom.isChecked() and self.output_edit.text().strip():
            return Path(self.output_edit.text().strip())
        if self._rows:
            return self._rows[0][0].parent
        return None
