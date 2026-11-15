"""Windows 11 风格的配色、样式表与主题管理。

- 提供浅色 / 深色两套调色板，以及「跟随系统」模式；
- 生成全局 QSS：圆角卡片、圆角输入框、圆角按钮、Win11 风格表格与滚动条；
- 处理 Windows 标题栏的深色沉浸效果，避免标题栏与界面割裂。
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette


def _asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def _settings_file() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    target = base / "PDFProducer"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path.cwd() / "settings.json"
    return target / "settings.json"


ASSETS = _asset_dir()
SETTINGS_PATH = _settings_file()

CHEVRON_LIGHT = (ASSETS / "chevron_light.svg").as_posix()
CHEVRON_DARK = (ASSETS / "chevron_dark.svg").as_posix()
CHECK_ICON = (ASSETS / "check_white.svg").as_posix()
SUN_ICON = (ASSETS / "sun_light.svg").as_posix()
MOON_ICON = (ASSETS / "moon_dark.svg").as_posix()


@dataclass(frozen=True)
class Palette:
    is_dark: bool
    window_bg: str
    card_bg: str
    card_border: str
    text: str
    text_secondary: str
    text_tertiary: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    control_bg: str
    control_border: str
    control_hover: str
    control_pressed: str
    list_hover: str
    list_selected: str
    row_alt: str
    log_bg: str
    danger: str
    success: str
    warning: str
    scrollbar: str
    scrollbar_hover: str
    dropdown_icon: str


LIGHT = Palette(
    is_dark=False,
    window_bg="#F3F3F3",
    card_bg="#FFFFFF",
    card_border="#E5E5E5",
    text="#1A1A1A",
    text_secondary="#5D5D5D",
    text_tertiary="#8A8A8A",
    accent="#0067C0",
    accent_hover="#1975C5",
    accent_pressed="#0B5FA8",
    accent_text="#FFFFFF",
    control_bg="#FFFFFF",
    control_border="#D6D6D6",
    control_hover="#F5F5F5",
    control_pressed="#EBEBEB",
    list_hover="#F4F4F4",
    list_selected="#E5E5E5",
    row_alt="#F7F8FA",
    log_bg="#FAFAFA",
    danger="#C42B1C",
    success="#0F7B3E",
    warning="#9D5D00",
    scrollbar="#C9C9C9",
    scrollbar_hover="#ADADAD",
    dropdown_icon=CHEVRON_LIGHT,
)

DARK = Palette(
    is_dark=True,
    window_bg="#202020",
    card_bg="#2B2B2B",
    card_border="#3A3A3A",
    text="#FFFFFF",
    text_secondary="#C9C9C9",
    text_tertiary="#9A9A9A",
    accent="#0078D4",
    accent_hover="#1A86E0",
    accent_pressed="#0064B0",
    accent_text="#FFFFFF",
    control_bg="#2D2D2D",
    control_border="#3D3D3D",
    control_hover="#333333",
    control_pressed="#3A3A3A",
    list_hover="#323232",
    list_selected="#3A3A3A",
    row_alt="#353535",
    log_bg="#262626",
    danger="#FF99A4",
    success="#6CCB8A",
    warning="#FCE100",
    scrollbar="#4A4A4A",
    scrollbar_hover="#5F5F5F",
    dropdown_icon=CHEVRON_DARK,
)

_QSS = Template("""
QMainWindow, QWidget#Root, QWidget#Content { background: $window_bg; }
QWidget#Sidebar { background: $window_bg; }
QStackedWidget { background: transparent; }

QFrame#Card {
    background: $card_bg;
    border: 1px solid $card_border;
    border-radius: 8px;
}
QFrame#CardInner { background: transparent; border: none; }

QLabel { color: $text; background: transparent; }
QLabel#Title { font-size: 26px; font-weight: 600; }
QLabel#Subtitle { color: $text_secondary; font-size: 14px; }
QLabel#SideTitle { font-size: 18px; font-weight: 600; }
QLabel#SideSubtitle { color: $text_secondary; font-size: 12px; }
QLabel#CardTitle { font-size: 15px; font-weight: 600; }
QLabel#Hint { color: $text_tertiary; font-size: 13px; }
QLabel#Status { color: $text_secondary; font-size: 13px; }
QLabel#Percent { color: $text_secondary; font-size: 13px; }
QLabel#Badge {
    background: $accent;
    color: $accent_text;
    border-radius: 8px;
    font-size: 20px;
    font-weight: 600;
    qproperty-alignment: AlignCenter;
}
QLabel#Preview {
    background: $log_bg;
    border: 1px dashed $card_border;
    border-radius: 8px;
    color: $text_tertiary;
}

QPushButton {
    background: $control_bg;
    border: 1px solid $control_border;
    border-radius: 4px;
    padding: 6px 16px;
    color: $text;
    min-height: 24px;
    font-size: 15px;
    outline: none;
}
QPushButton:hover { background: $control_hover; }
QPushButton:pressed { background: $control_pressed; }
QPushButton:disabled { color: $text_tertiary; border-color: $card_border; }
QPushButton#Accent {
    background: $accent;
    border: 1px solid $accent;
    color: $accent_text;
    font-weight: 600;
    padding: 9px 26px;
    font-size: 15px;
}
QPushButton#Accent:hover { background: $accent_hover; }
QPushButton#Accent:pressed { background: $accent_pressed; }
QPushButton#Accent:disabled { background: $control_pressed; border-color: $card_border; color: $text_tertiary; }
QPushButton#Subtle {
    background: transparent;
    border: none;
    color: $text_secondary;
    padding: 5px 10px;
    min-height: 0;
}
QPushButton#Subtle:hover { background: $control_hover; }
QPushButton#Subtle:pressed { background: $control_pressed; }
QPushButton#SubtleDanger {
    background: transparent;
    border: none;
    color: $danger;
    padding: 4px 8px;
}
QPushButton#SubtleDanger:hover { background: $control_hover; }

QLineEdit, QComboBox {
    background: $control_bg;
    border: 1px solid $control_border;
    border-radius: 4px;
    padding: 6px 10px;
    color: $text;
    selection-background-color: $accent;
    selection-color: $accent_text;
    min-height: 24px;
    font-size: 14px;
}
QLineEdit:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled { color: $text_tertiary; }
QLineEdit#SizeInput { min-width: 44px; max-width: 64px; }

QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url($dropdown_icon); width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background: $card_bg;
    border: 1px solid $card_border;
    border-radius: 6px;
    padding: 4px;
    outline: none;
    selection-background-color: $list_selected;
    selection-color: $text;
    color: $text;
    font-size: 14px;
}
QComboBox QAbstractItemView::item {
    min-height: 34px;
    padding-left: 8px;
    padding-right: 10px;
    border-left: 3px solid transparent;
    border-radius: 5px;
    margin: 0px;
    color: $text;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background: $list_selected;
    border-left: 3px solid $accent;
    color: $text;
}

QCheckBox, QRadioButton { color: $text; background: transparent; spacing: 8px; font-size: 14px; }

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid $control_border;
    background: $control_bg;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked {
    background: $accent;
    border: 1px solid $accent;
    image: url($check_icon);
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid $control_border;
    background: $control_bg;
}
QRadioButton::indicator:hover { border-color: $accent; }
QRadioButton::indicator:checked {
    border: 1px solid $accent;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 $accent, stop:0.38 $accent, stop:0.42 $control_bg, stop:1 $control_bg);
}

QTreeWidget, QTreeView, QListWidget, QListView {
    background: $control_bg;
    border: 1px solid $control_border;
    border-radius: 6px;
    outline: none;
    color: $text;
    selection-background-color: $list_selected;
    selection-color: $text;
    alternate-background-color: $row_alt;
}
QTreeWidget::item, QTreeView::item, QListWidget::item, QListView::item {
    padding: 5px 6px;
    border-radius: 4px;
}
QTreeWidget::item:selected, QTreeView::item:selected,
QListWidget::item:selected, QListView::item:selected {
    background: $list_selected;
    color: $text;
}
QTreeWidget::item:hover, QTreeView::item:hover,
QListWidget::item:hover, QListView::item:hover {
    background: $list_hover;
}

QTreeView::indicator, QListView::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid $control_border;
    background: $control_bg;
}
QTreeView::indicator:hover, QListView::indicator:hover { border-color: $accent; }
QTreeView::indicator:checked, QListView::indicator:checked {
    background: $accent;
    border: 1px solid $accent;
    image: url($check_icon);
}

QTableWidget {
    background: $card_bg;
    alternate-background-color: $row_alt;
    border: none;
    outline: none;
    gridline-color: transparent;
    selection-background-color: $list_selected;
    selection-color: $text;
}
QTableWidget::item {
    padding-left: 8px;
    padding-right: 8px;
    border: none;
    color: $text;
}
QTableWidget::item:hover { background: $list_hover; }
QTableWidget::item:selected { background: $list_selected; color: $text; }
QHeaderView { background: transparent; border: none; }
QHeaderView::section {
    background: transparent;
    border: none;
    border-bottom: 1px solid $card_border;
    padding: 8px;
    color: $text_secondary;
    font-size: 13px;
}
QTableCornerButton::section { background: transparent; border: none; }

QPlainTextEdit {
    background: $log_bg;
    border: 1px solid $card_border;
    border-radius: 6px;
    color: $text_secondary;
    padding: 6px;
    font-size: 12px;
}

QProgressBar {
    background: $control_pressed;
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
    text-align: center;
}
QProgressBar::chunk { background: $accent; border-radius: 3px; }

QListWidget#Nav {
    background: transparent;
    border: none;
    outline: none;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 2px;
}
QScrollBar::handle:vertical {
    background: $scrollbar;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: $scrollbar_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: $scrollbar;
    border-radius: 3px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: $scrollbar_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

QToolTip {
    background: $card_bg;
    color: $text;
    border: 1px solid $card_border;
    border-radius: 4px;
    padding: 4px 8px;
}

QDialog { background: $window_bg; }

QMenu {
    background: $card_bg;
    border: 1px solid $card_border;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 4px; color: $text; }
QMenu::item:selected { background: $list_selected; }
QMenu::separator { height: 1px; background: $card_border; margin: 4px 8px; }
""")


def build_qss(palette: Palette) -> str:
    values = asdict(palette)
    values["check_icon"] = CHECK_ICON
    return _QSS.substitute(values)


def apply_palette(app, palette: Palette) -> None:
    """同步 QPalette，让没有单独写样式的控件也跟随浅色 / 深色。"""
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(palette.window_bg))
    pal.setColor(QPalette.WindowText, QColor(palette.text))
    pal.setColor(QPalette.Base, QColor(palette.control_bg))
    pal.setColor(QPalette.AlternateBase, QColor(palette.card_bg))
    pal.setColor(QPalette.ToolTipBase, QColor(palette.card_bg))
    pal.setColor(QPalette.ToolTipText, QColor(palette.text))
    pal.setColor(QPalette.Text, QColor(palette.text))
    pal.setColor(QPalette.Button, QColor(palette.control_bg))
    pal.setColor(QPalette.ButtonText, QColor(palette.text))
    pal.setColor(QPalette.BrightText, QColor(palette.danger))
    pal.setColor(QPalette.Highlight, QColor(palette.accent))
    pal.setColor(QPalette.HighlightedText, QColor(palette.accent_text))
    pal.setColor(QPalette.PlaceholderText, QColor(palette.text_tertiary))
    pal.setColor(QPalette.Link, QColor(palette.accent))
    app.setPalette(pal)


def detect_system_dark() -> bool:
    """读取 Windows 系统「应用模式」是否为深色。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except OSError:
        return False


def app_font() -> QFont:
    families = set(QFontDatabase.families())
    for name in ("Microsoft YaHei UI", "微软雅黑", "Microsoft YaHei"):
        if name in families:
            font = QFont(name)
            font.setPointSizeF(12.0)
            return font
    for name in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI"):
        if name in families:
            font = QFont(name)
            font.setPointSizeF(12.0)
            return font
    fallback = QFont()
    fallback.setPointSizeF(12.0)
    return fallback


def set_dark_titlebar(window, dark: bool) -> None:
    """让 Windows 标题栏跟随深色模式（Windows 10 1809+ / Windows 11）。"""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


class ThemeManager(QObject):
    """管理「跟随系统 / 浅色 / 深色」三种模式，并持久化到 settings.json。"""

    changed = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.mode = "system"
        self.palette: Palette = LIGHT
        self._load()
        self.palette = self.resolve()

    # ---------------------------------------------------------------- 读写设置
    def _load(self) -> None:
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        mode = data.get("theme", "system")
        if mode in ("system", "light", "dark"):
            self.mode = mode

    def _save(self) -> None:
        data = {"theme": self.mode}
        try:
            SETTINGS_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---------------------------------------------------------------- 主题切换
    def resolve(self) -> Palette:
        if self.mode == "light":
            return LIGHT
        if self.mode == "dark":
            return DARK
        return DARK if detect_system_dark() else LIGHT

    def set_mode(self, mode: str) -> None:
        if mode not in ("system", "light", "dark"):
            return
        self.mode = mode
        self._save()
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        new_palette = self.resolve()
        if force or new_palette.is_dark != self.palette.is_dark:
            self.palette = new_palette
            self.changed.emit()

    def mode_label(self) -> str:
        return {"system": "跟随系统", "light": "浅色", "dark": "深色"}[self.mode]
