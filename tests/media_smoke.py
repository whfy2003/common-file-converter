"""媒体页面冒烟测试：截图 + 图片/字幕提取流程。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import media  # noqa: E402
from ui import theme  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

SAMPLE = ROOT / "tests" / "media_sample"
SHOTS = ROOT / "tests" / "shots"
FFMPEG = media.ffmpeg_path()


def pump(app, seconds: float = 0.4) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def grab(widget, name: str) -> None:
    pixmap = widget.grab()
    pixmap.save(str(SHOTS / name))
    print(f"截图: {name}  {pixmap.width()}x{pixmap.height()}")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, capture_output=True, creationflags=0x08000000)


def make_files() -> Path:
    if SAMPLE.exists():
        shutil.rmtree(SAMPLE)
    SAMPLE.mkdir(parents=True)

    Image.new("RGB", (400, 300), (120, 160, 220)).save(SAMPLE / "pic.png")
    Image.new("RGB", (320, 240), (200, 120, 90)).save(SAMPLE / "pic2.png")

    video = SAMPLE / "sample.mp4"
    run([
        str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video),
    ])
    srt = SAMPLE / "sub.srt"
    srt.write_text("1\n00:00:00,200 --> 00:00:01,500\n测试字幕\n",
                   encoding="utf-8")
    with_subs = SAMPLE / "with_subs.mkv"
    run([
        str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-i", str(srt),
        "-map", "0", "-map", "1", "-c", "copy", "-c:s", "srt", str(with_subs),
    ])
    return with_subs


def wait_page(app, page, timeout: float = 60) -> None:
    end = time.time() + timeout
    while page.is_running() and time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> None:
    SHOTS.mkdir(exist_ok=True)
    with_subs = make_files()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(theme.app_font())

    manager = theme.ThemeManager()
    manager.set_mode("light")
    window = MainWindow(manager)
    window._ask_yes_no = lambda *args, **kwargs: False
    window.show()
    pump(app, 0.6)

    print("1) 四个新页面截图")
    for index, name in ((2, "image"), (3, "video"), (4, "audio"), (5, "extract")):
        window.nav.setCurrentRow(index)
        pump(app, 0.45)
        grab(window, f"qt_13_{name}_page.png")

    print("2) 图片格式转换（界面流程）")
    page = window.image_convert_page
    window.nav.setCurrentRow(2)
    page._paths = [SAMPLE / "pic.png", SAMPLE / "pic2.png"]
    page._refresh_table()
    page.target_combo.setCurrentIndex(0)  # JPG
    page.start()
    wait_page(app, page)
    outputs = sorted(SAMPLE.glob("pic*.jpg"))
    print("   生成:", [p.name for p in outputs])
    if len(outputs) != 2:
        print("   [失败] 图片转换数量不对")
        return

    print("3) 字幕音轨提取（界面流程）")
    extract = window.extract_page
    window.nav.setCurrentRow(5)
    info = media.probe(with_subs)
    extract._rows = [(with_subs, stream)
                     for stream in info.audio_streams + info.subtitle_streams]
    extract._refresh_table()
    pump(app, 0.3)
    grab(window, "qt_14_extract_filled.png")
    extract.start()
    wait_page(app, extract)
    produced = [p.name for p in SAMPLE.glob("with_subs_*")]
    print("   生成:", produced)
    if not produced:
        print("   [失败] 没有提取到文件")
        return

    print("4) 视频页面有数据截图")
    video_page = window.video_convert_page
    window.nav.setCurrentRow(3)
    video_page._paths = [with_subs]
    video_page._refresh_table()
    pump(app, 0.4)
    grab(window, "qt_15_video_filled.png")

    print("\n全部通过。")
    window.close()


if __name__ == "__main__":
    main()
