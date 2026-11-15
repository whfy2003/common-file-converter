"""多选文件夹对话框：左右分栏、复选框、支持拖动批量选择。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import fade_in_window


class _CheckTree(QTreeWidget):
    """选中行时切换勾选：拖过的每一行按它自己的当前状态取反。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_space = None
        self._updating = False
        self._touched: set = set()
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.setAlternatingRowColors(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setIndentation(14)
        self.setMouseTracking(True)
        self.setAutoScroll(True)
        self.itemSelectionChanged.connect(self._sync_selection_checks)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._touched = set()
        super().mousePressEvent(event)

    def _sync_selection_checks(self) -> None:
        """每选中一行就按它自己的状态取反，且一次拖动里每行只切换一次。"""
        if self._updating:
            return
        items = self.selectedItems()
        if not items:
            return
        self._updating = True
        for item in items:
            key = item.data(0, Qt.UserRole) or item.text(0)
            if key in self._touched:
                continue
            self._touched.add(key)
            if item.checkState(0) == Qt.Checked:
                item.setCheckState(0, Qt.Unchecked)
            else:
                item.setCheckState(0, Qt.Checked)
        self._updating = False

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and self.on_space is not None:
            self.on_space()
            return
        self._touched = set()
        super().keyPressEvent(event)


class FolderPickerDialog(QDialog):
    """返回用户勾选的一组文件夹（勾选状态跨目录保留）。"""

    def __init__(self, parent=None, initial_dir: str | Path | None = None):
        super().__init__(parent)
        self.result: list[Path] = []
        self.checked: dict[Path, bool] = {}
        self.current_dir = Path(initial_dir) if initial_dir else Path.home()
        self._rows: list[Path] = []
        self._syncing = False

        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(40)
        self._rebuild_timer.timeout.connect(self._rebuild_selected)

        self.setWindowTitle("选择文件夹（可多选）")
        self.setModal(True)
        self.resize(1060, 640)
        self._build()
        self._refresh(self.current_dir)

    # ------------------------------------------------------------------ 界面
    def showEvent(self, event) -> None:
        super().showEvent(event)
        fade_in_window(self, 150)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.up_button = QPushButton("↑  上一级")
        self.up_button.clicked.connect(self._go_up)
        self.path_edit = QLineEdit(str(self.current_dir))
        self.path_edit.returnPressed.connect(self._go_to_entry)
        go_button = QPushButton("转到")
        go_button.clicked.connect(self._go_to_entry)
        browse_button = QPushButton("浏览…")
        browse_button.clicked.connect(self._browse)
        path_row.addWidget(self.up_button)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(go_button)
        path_row.addWidget(browse_button)
        outer.addLayout(path_row)

        body = QHBoxLayout()
        body.setSpacing(14)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.left = _CheckTree()
        self.left.setHeaderLabels(["文件夹名称"])
        self.left.setMinimumWidth(380)
        self.left.itemDoubleClicked.connect(self._on_double_clicked)
        self.left.on_space = self._toggle_left_selection
        left_layout.addWidget(self.left, 1)

        left_row = QHBoxLayout()
        left_row.setSpacing(8)
        self.left_count_label = QLabel("已选择 0 个文件夹")
        self.left_count_label.setObjectName("Hint")
        left_row.addWidget(self.left_count_label)
        left_row.addStretch(1)
        self.add_selected_button = QPushButton("添加所选")
        self.add_selected_button.clicked.connect(self._add_selected_left)
        left_row.addWidget(self.add_selected_button)
        left_layout.addLayout(left_row)

        body.addWidget(left_panel, 3)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)

        self.right = _CheckTree()
        self.right.setHeaderLabels(["文件夹", "上级目录"])
        self.right.setColumnWidth(0, 215)
        self.right.setColumnWidth(1, 170)
        self.right.header().setStretchLastSection(True)
        self.right.on_space = self._toggle_right_selection
        side_layout.addWidget(self.right, 1)

        right_row = QHBoxLayout()
        right_row.setSpacing(8)
        self.count_label = QLabel("已选择 0 个文件夹")
        self.count_label.setObjectName("Hint")
        right_row.addWidget(self.count_label)
        right_row.addStretch(1)
        self.remove_button = QPushButton("移除所选")
        self.remove_button.clicked.connect(self._remove_selected)
        right_row.addWidget(self.remove_button)
        side_layout.addLayout(right_row)
        body.addWidget(side, 4)

        outer.addLayout(body, 1)

        hint = QLabel(
            "单击方框勾选；双击可以进入下一级；左右两侧都能按住鼠标左键拖动批量选中；"
            "左侧选中后点「添加所选」，右侧选中后点「移除所选」。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        add_current = QPushButton("加入当前文件夹")
        add_current.clicked.connect(self._add_current)
        clear_button = QPushButton("清空选择")
        clear_button.clicked.connect(self._clear_all)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        confirm_button = QPushButton("确定添加")
        confirm_button.setObjectName("Accent")
        confirm_button.clicked.connect(self._confirm)

        footer.addWidget(add_current)
        footer.addWidget(clear_button)
        footer.addStretch(1)
        footer.addWidget(cancel_button)
        footer.addWidget(confirm_button)
        outer.addLayout(footer)

    # ------------------------------------------------------------------ 目录
    def _refresh(self, folder: Path) -> None:
        folder = Path(folder)
        if not folder.is_dir():
            QMessageBox.warning(self, "路径无效",
                                f"文件夹不存在或无法访问：\n{folder}")
            return
        self.current_dir = folder
        self.path_edit.setText(str(folder))
        self.left.clear()
        self._rows = []

        try:
            entries = sorted(
                (path for path in folder.iterdir() if path.is_dir()),
                key=lambda p: p.name.lower(),
            )
        except OSError as exc:
            QMessageBox.critical(self, "无法读取", f"读取文件夹失败：\n{exc}")
            return

        icon = self.style().standardIcon(QStyle.SP_DirIcon)
        self._syncing = True
        for path in entries:
            self._rows.append(path)
            item = QTreeWidgetItem([path.name])
            item.setIcon(0, icon)
            item.setToolTip(0, str(path))
            item.setData(0, Qt.UserRole, str(path))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            self.left.addTopLevelItem(item)
        self._syncing = False

        if not entries:
            placeholder = QTreeWidgetItem(["（这个文件夹里没有子文件夹）"])
            placeholder.setFlags(Qt.NoItemFlags)
            self.left.addTopLevelItem(placeholder)

        self._rebuild_selected()

    def _go_up(self) -> None:
        parent = self.current_dir.parent
        self._refresh(parent if parent != self.current_dir else Path.home())

    def _go_to_entry(self) -> None:
        text = self.path_edit.text().strip().strip('"')
        if text:
            self._refresh(Path(text))

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "进入文件夹", str(self.current_dir))
        if chosen:
            self._refresh(Path(chosen))

    # ------------------------------------------------------------------ 左侧勾选

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        text = item.data(0, Qt.UserRole)
        if text:
            self._refresh(Path(text))

    def _toggle_left_selection(self) -> None:
        items = self.left.selectedItems()
        if not items:
            return
        first = items[0]
        target = Qt.Unchecked if first.checkState(0) == Qt.Checked else Qt.Checked
        self._syncing = True
        for item in items:
            text = item.data(0, Qt.UserRole)
            if not text:
                continue
            item.setCheckState(0, target)
            self.checked[Path(text)] = target == Qt.Checked
        self._syncing = False
        self._rebuild_selected()

    def _add_selected_left(self) -> None:
        targets: set[str] = set()
        for item in self.left.selectedItems():
            text = item.data(0, Qt.UserRole)
            if text:
                targets.add(text)
        for index in range(self.left.topLevelItemCount()):
            item = self.left.topLevelItem(index)
            if item.checkState(0) == Qt.Checked:
                text = item.data(0, Qt.UserRole)
                if text:
                    targets.add(text)
        if not targets:
            QMessageBox.information(self, "还没有选择",
                                    "请先在左侧选中要添加的文件夹。")
            return
        for text in targets:
            self.checked[Path(text)] = True
        self._clear_left_marks()
        self._rebuild_selected()

    # ------------------------------------------------------------------ 右侧
    def _toggle_right_selection(self) -> None:
        items = self.right.selectedItems()
        if not items:
            return
        first = items[0]
        target = Qt.Unchecked if first.checkState(0) == Qt.Checked else Qt.Checked
        self._syncing = True
        for item in items:
            item.setCheckState(0, target)
        self._syncing = False

    def _remove_selected(self) -> None:
        targets: set[str] = set()
        for item in self.right.selectedItems():
            text = item.data(0, Qt.UserRole)
            if text:
                targets.add(text)
        for index in range(self.right.topLevelItemCount()):
            item = self.right.topLevelItem(index)
            if item.checkState(0) == Qt.Checked:
                text = item.data(0, Qt.UserRole)
                if text:
                    targets.add(text)
        if not targets:
            QMessageBox.information(self, "还没有选择",
                                    "请先勾选或选中要移除的文件夹。")
            return
        for text in targets:
            self.checked[Path(text)] = False
        self._rebuild_selected()

    def _rebuild_selected(self) -> None:
        chosen = [path for path, on in self.checked.items() if on]
        icon = self.style().standardIcon(QStyle.SP_DirIcon)
        self._syncing = True
        self.right.clear()
        for path in chosen:
            item = QTreeWidgetItem([path.name, path.parent.name])
            item.setIcon(0, icon)
            item.setToolTip(0, str(path))
            item.setData(0, Qt.UserRole, str(path))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            self.right.addTopLevelItem(item)
        self._syncing = False
        count_text = f"已选择 {len(chosen)} 个文件夹"
        self.count_label.setText(count_text)
        self.left_count_label.setText(count_text)

    def _clear_left_marks(self) -> None:
        self._syncing = True
        for index in range(self.left.topLevelItemCount()):
            item = self.left.topLevelItem(index)
            item.setCheckState(0, Qt.Unchecked)
        self._syncing = False

    def _add_current(self) -> None:
        if self.current_dir.is_dir():
            self.checked[self.current_dir] = True
            self._rebuild_selected()

    def _clear_all(self) -> None:
        self.checked.clear()
        self._clear_left_marks()
        self._rebuild_selected()

    def _confirm(self) -> None:
        chosen = [path for path, on in self.checked.items() if on and path.is_dir()]
        if not chosen:
            QMessageBox.information(self, "还没有选择", "请先勾选至少一个文件夹。")
            return
        self.result = chosen
        self.accept()
