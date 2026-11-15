"""Qt 界面冒烟测试：渲染截图并验证生成流程。

运行：python tests/qt_smoke.py
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import scanner  # noqa: E402
from core.models import FolderTask  # noqa: E402
from ui import theme  # noqa: E402
from ui.dialogs import ConvertNoticeDialog  # noqa: E402
from ui.folder_dialog import FolderPickerDialog  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

SAMPLE = ROOT / "tests" / "sample_data"
SHOTS = ROOT / "tests" / "shots"

PALETTE = [
    (66, 133, 244), (52, 168, 83), (251, 188, 5), (234, 67, 53),
    (171, 71, 188), (0, 172, 193), (255, 112, 67), (124, 179, 66),
    (63, 81, 181), (141, 110, 99),
]


def make_picture(path: Path, size: tuple[int, int], color) -> None:
    from PIL import ImageDraw

    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle([18, 18, size[0] - 18, size[1] - 18],
                   outline=(255, 255, 255), width=5)
    draw.ellipse([size[0] // 3, size[1] // 3,
                  size[0] * 2 // 3, size[1] * 2 // 3],
                 outline=(255, 255, 255), width=4)
    image.save(path)
    image.close()


def build_samples() -> None:
    if SAMPLE.exists():
        shutil.rmtree(SAMPLE)
    SAMPLE.mkdir(parents=True)

    travel = SAMPLE / "2024 旅行照片"
    travel.mkdir()
    for number in range(1, 9):
        make_picture(travel / f"{number}.jpg",
                     (640 + number * 30, 420 + number * 20),
                     PALETTE[number % len(PALETTE)])

    product = SAMPLE / "产品图 - 扫描"
    product.mkdir()
    for number in range(1, 4):
        make_picture(product / f"{number}.png", (560, 760), PALETTE[(number + 3) % 10])
    make_picture(product / "4.bmp", (520, 700), PALETTE[8])
    make_picture(product / "5.jpg", (520, 700), PALETTE[9])

    gallery = SAMPLE / "图集"
    day1 = gallery / "第一天"
    day1.mkdir(parents=True)
    for number in range(1, 4):
        make_picture(day1 / f"{number}.jpg", (600, 440), PALETTE[number % 10])
    day2 = gallery / "第二天"
    day2.mkdir()
    for number in range(1, 4):
        make_picture(day2 / f"{number}.jpg", (600, 440), PALETTE[(number + 4) % 10])


def pump(app, seconds: float = 0.35) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def grab(widget, name: str) -> None:
    pixmap = widget.grab()
    pixmap.save(str(SHOTS / name))
    print(f"截图：{name}  {pixmap.width()}x{pixmap.height()}")


def main() -> None:
    SHOTS.mkdir(exist_ok=True)
    build_samples()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(theme.app_font())

    manager = theme.ThemeManager()
    manager.set_mode("light")
    window = MainWindow(manager)
    window.show()
    pump(app, 0.5)
    grab(window, "qt_01_empty_light.png")

    # 注入 4 个根文件夹
    folders = [SAMPLE / "2024 旅行照片", SAMPLE / "产品图 - 扫描",
               SAMPLE / "资料图片", SAMPLE / "图集"]
    if not (SAMPLE / "资料图片").exists():
        (SAMPLE / "资料图片").mkdir()
        for number in range(1, 7):
            make_picture(SAMPLE / "资料图片" / f"{number:02d}.jpeg",
                         (500, 680), PALETTE[(number + 5) % 10])

    for folder in folders:
        entries = scanner.scan_for_mode(folder, scanner.OUTPUT_SINGLE,
                                        scanner.SORT_NATURAL)
        window.folder_tasks.append(FolderTask(folder=folder, images=[]))
        window._folder_entries[folder] = entries
    window._refresh_folder_table()
    window._refresh_status()
    pump(app, 0.3)
    grab(window, "qt_02_folder_light.png")

    # 切换为「每个子文件夹各一个 PDF」
    window.subfolder_combo.setCurrentText(scanner.OUTPUT_MODE_LABELS[scanner.OUTPUT_PER_SUBFOLDER])
    window._rescan_folders()
    pump(app, 0.3)
    grab(window, "qt_03_subfolder_light.png")

    # 深色模式
    manager.set_mode("dark")
    pump(app, 0.4)
    grab(window, "qt_04_folder_dark.png")

    # 图片模式
    window.nav.setCurrentRow(1)
    picked = []
    for folder in (SAMPLE / "2024 旅行照片", SAMPLE / "资料图片"):
        picked.extend(scanner.scan_folder(folder)[:3])
    window.image_paths.extend(picked)
    window._refresh_image_table()
    window._sync_image_name()
    window._refresh_status()
    pump(app, 0.3)
    grab(window, "qt_05_images_dark.png")

    manager.set_mode("light")
    pump(app, 0.4)
    grab(window, "qt_06_images_light.png")

    # 自定义页面尺寸
    window.nav.setCurrentRow(0)
    window.page_size_combo.setCurrentText("自定义尺寸…")
    pump(app, 0.4)
    grab(window, "qt_10_custom_size.png")
    window.page_size_combo.setCurrentText("与图片相同大小")

    # 主题按钮：点一下切换日夜
    before = manager.palette.is_dark
    window.theme_button.click()
    pump(app, 0.3)
    after = manager.palette.is_dark
    print(f"主题按钮切换：{before} -> {after}")
    window.theme_button.click()
    pump(app, 0.2)

    # 下拉菜单：位置与行高
    window.subfolder_combo.showPopup()
    pump(app, 0.25)
    popup = window.subfolder_combo.view().window()
    origin = window.subfolder_combo.mapToGlobal(
        window.subfolder_combo.rect().bottomLeft())
    print(f"下拉弹窗位置：({popup.x()}, {popup.y()})，"
          f"控件底部：({origin.x()}, {origin.y()})，"
          f"控件高：{window.subfolder_combo.height()}，"
          f"弹窗高：{popup.height()}")
    popup.grab().save(str(SHOTS / "qt_11_combo_popup.png"))
    window.subfolder_combo.hidePopup()
    pump(app, 0.2)

    # 对话框
    picker = FolderPickerDialog(window, initial_dir=str(SAMPLE))
    picker.show()
    picker.checked[SAMPLE / "2024 旅行照片"] = True
    picker.checked[SAMPLE / "图集"] = True
    picker._rebuild_selected()
    pump(app, 0.4)
    grab(picker, "qt_07_picker.png")

    # 右侧勾选一行 -> 点「移除所选」
    if picker.right.topLevelItemCount() > 0:
        first = picker.right.topLevelItem(0)
        first.setCheckState(0, Qt.Checked)
        picker._remove_selected()
        pump(app, 0.3)
        remaining = [path for path, on in picker.checked.items() if on]
        print(f"移除所先后剩余：{len(remaining)} 个")
        grab(picker, "qt_12_picker_after_remove.png")
    picker.close()

    non_jpg = [p for p in scanner.scan_folder(SAMPLE / "产品图 - 扫描")
               if not scanner.is_jpg(p)]
    notice = ConvertNoticeDialog(window, non_jpg)
    notice.show()
    pump(app, 0.4)
    grab(notice, "qt_08_notice.png")
    notice.close()

    # 生成流程（文件夹模式）
    window.nav.setCurrentRow(0)
    window.subfolder_combo.setCurrentText(scanner.OUTPUT_MODE_LABELS[scanner.OUTPUT_PER_SUBFOLDER])
    window._rescan_folders()
    window._ask_yes_no = lambda *args, **kwargs: False
    window._bridge.log.connect(lambda text: print("LOG:", text, flush=True))
    window._bridge.progress.connect(lambda f, t: print("PROG:", round(f, 2), t, flush=True))
    window._bridge.job_done.connect(lambda i, r: print("DONE:", i, r, flush=True))
    window._bridge.finished.connect(lambda info: print("FINISHED:", info.get("succeeded"), flush=True))
    jobs = window._build_jobs()
    print(f"生成计划：{len(jobs)} 个 PDF", flush=True)
    window._start_jobs(jobs)
    deadline = time.time() + 120
    while window._busy and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    print(f"生成结束，busy={window._busy}", flush=True)
    pump(app, 0.5)
    grab(window, "qt_09_finished.png")

    pdfs = sorted(SAMPLE.rglob("*.pdf"))
    print(f"生成 {len(pdfs)} 个 PDF：")
    from pypdf import PdfReader
    for pdf in pdfs:
        print(f"  · {pdf.relative_to(SAMPLE)}  {len(PdfReader(str(pdf)).pages)} 页")

    manager.set_mode("system")
    window.close()
    app.processEvents()


if __name__ == "__main__":
    main()
