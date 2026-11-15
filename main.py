"""图片合并为 PDF —— 程序入口。

双击「启动 PDF 合并工具.bat」即可运行；也可以在本目录执行：
    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

_REQUIREMENTS = (
    ("PIL", "Pillow"),
    ("img2pdf", "img2pdf"),
    ("PySide6", "PySide6"),
)


def _missing_dependencies() -> list[str]:
    missing: list[str] = []
    for module, name in _REQUIREMENTS:
        try:
            __import__(module)
        except ImportError:
            missing.append(name)
    return missing


def _show_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("缺少运行组件", message)
        root.destroy()
    except Exception:
        print(message)


def main() -> int:
    missing = _missing_dependencies()
    if missing:
        _show_error(
            "缺少以下运行组件：\n\n"
            + "\n".join(f"· {name}" for name in missing)
            + "\n\n请先双击运行 install_deps.bat 安装，然后重新打开程序。"
        )
        return 1

    from PySide6.QtWidgets import QApplication

    from ui import theme
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Document Tool")
    app.setApplicationDisplayName("Document Tool")
    app.setStyle("Fusion")
    app.setFont(theme.app_font())

    manager = theme.ThemeManager()
    window = MainWindow(manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
