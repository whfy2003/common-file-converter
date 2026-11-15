"""Win11 风格的基础控件：导航项绘制、圆角卡片、表格与卡头。"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHeaderView,
    QLabel,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


def fade_in_window(window: QWidget, duration: int = 160) -> None:
    """窗口整体淡入，让弹窗出现得更自然。"""
    try:
        window.setWindowOpacity(0.0)
    except Exception:
        return
    animation = QPropertyAnimation(window, b"windowOpacity", window)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.start(QAbstractAnimation.DeleteWhenStopped)


def fade_in_widget(widget: QWidget, duration: int = 180) -> None:
    """控件内容淡入（用于切换标签页）。"""
    if widget is None:
        return
    widget.setGraphicsEffect(None)
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)

    def _clear() -> None:
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    animation.finished.connect(_clear)
    animation.start(QAbstractAnimation.DeleteWhenStopped)


class _RowHeightDelegate(QStyledItemDelegate):
    """让下拉列表每一行的高度与下拉控件一致。"""

    def __init__(self, parent=None, row_height: int = 38):
        super().__init__(parent)
        self._row_height = row_height

    def set_row_height(self, height: int) -> None:
        self._row_height = max(28, int(height))

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        size.setHeight(self._row_height)
        return size


class ComboBox(QComboBox):
    """下拉列表固定出现在控件下方，带淡入 + 下滑的过渡动画。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxVisibleItems(10)
        self._row_delegate = _RowHeightDelegate(self, 38)
        self.view().setItemDelegate(self._row_delegate)

    def showPopup(self) -> None:
        row_height = max(30, self.height())
        self._row_delegate.set_row_height(row_height)
        super().showPopup()

        view = self.view()
        rows = min(max(1, self.count()), self.maxVisibleItems())
        # 行高与控件一致；额外留出列表的内边距与边框
        view.setFixedHeight(rows * row_height + 10)

        popup = view.window()
        popup.setFixedWidth(self.width())
        popup.adjustSize()
        origin = self.mapToGlobal(QPoint(0, self.height() + 2))
        popup.move(origin)

        try:
            popup.setWindowOpacity(0.0)
        except Exception:
            return

        fade = QPropertyAnimation(popup, b"windowOpacity", popup)
        fade.setDuration(130)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        fade.start(QAbstractAnimation.DeleteWhenStopped)

        slide = QPropertyAnimation(popup, b"pos", popup)
        slide.setDuration(130)
        slide.setStartValue(QPoint(origin.x(), origin.y() - 8))
        slide.setEndValue(origin)
        slide.setEasingCurve(QEasingCurve.OutCubic)
        slide.start(QAbstractAnimation.DeleteWhenStopped)


class NavDelegate(QStyledItemDelegate):
    """左侧导航项：圆角背景，选中时左侧出现 Win11 的蓝色竖条。"""

    def __init__(self, theme_manager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        size.setHeight(46)
        return size

    def paint(self, painter: QPainter, option, index) -> None:
        palette = self.theme_manager.palette
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(option.rect).adjusted(6, 3, -6, -3)
        path = QPainterPath()
        path.addRoundedRect(rect, 5, 5)

        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            painter.fillPath(path, QColor(palette.list_selected))
        elif hovered:
            painter.fillPath(path, QColor(palette.list_hover))

        text = str(index.data(Qt.DisplayRole) or "")
        font = QFont(option.font)
        font.setPointSizeF(12.0)
        font.setWeight(QFont.DemiBold if selected else QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor(palette.text))
        painter.drawText(rect.adjusted(16, 0, -10, 0),
                         Qt.AlignVCenter | Qt.AlignLeft, text)

        if selected:
            bar = QRectF(rect.left() + 1.5, rect.top() + 12, 3, rect.height() - 24)
            bar_path = QPainterPath()
            bar_path.addRoundedRect(bar, 1.5, 1.5)
            painter.fillPath(bar_path, QColor(palette.accent))

        painter.restore()


class SectionCard(QFrame):
    """Win11 设置页里的分组卡片：圆角、无阴影、细边框。"""

    def __init__(self, parent=None, padding: tuple[int, int, int, int] = (16, 14, 16, 14),
                 spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*padding)
        self.body.setSpacing(spacing)


class CardHeader(QWidget):
    """卡片标题 + 灰色说明文字。"""

    def __init__(self, title: str, description: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        layout.addWidget(self.title_label)
        self.description_label = None
        if description:
            self.description_label = QLabel(description)
            self.description_label.setObjectName("Hint")
            self.description_label.setWordWrap(True)
            layout.addWidget(self.description_label)


def make_table(headers: list[str], widths: list[int],
               row_height: int = 40, parent=None) -> QTableWidget:
    table = EmptyHintTable(headers, widths, row_height, parent)
    return table


class EmptyHintTable(QTableWidget):
    """带空状态提示的表格：没有数据时在表格中间显示一行提示文字。"""

    def __init__(self, headers: list[str], widths: list[int],
                 row_height: int = 40, parent=None):
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(row_height)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setWordWrap(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsClickable(False)
        header.setFixedHeight(38)
        header.setSectionResizeMode(QHeaderView.Interactive)
        for index, width in enumerate(widths):
            self.setColumnWidth(index, width)

        self._empty_label = QLabel(self.viewport())
        self._empty_label.setObjectName("Status")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._empty_label.setWordWrap(True)
        self._empty_label.hide()

    def set_empty_hint(self, text: str) -> None:
        self._empty_label.setText(text or "")
        if text:
            self._position_empty()
            self._empty_label.show()
        else:
            self._empty_label.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_empty()

    def _position_empty(self) -> None:
        rect = self.viewport().rect()
        self._empty_label.resize(rect.size())
        self._empty_label.move(0, 0)
