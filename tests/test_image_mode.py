"""图片模式逻辑测试：多张图片 → 一个 PDF，默认使用第一张图片命名。"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from core import scanner  # noqa: E402
from core.pdf_builder import build_pdf  # noqa: E402
from core.planning import plan_image_jobs  # noqa: E402


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [通过] {message}")
    else:
        print(f"  [失败] {message}")
        raise SystemExit(1)


def make_image(path: Path, color) -> None:
    image = Image.new("RGB", (600, 480), color)
    image.save(path)
    image.close()


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="pdf_producer_mode_"))
    try:
        source = root / "相册"
        source.mkdir()
        for name, color in (("第1张.jpg", (200, 80, 80)),
                            ("第2张.png", (80, 160, 200)),
                            ("第3张.jpg", (90, 190, 120)),
                            ("第10张.jpg", (200, 180, 80))):
            make_image(source / name, color)

        paths = scanner.sort_images(list(source.iterdir()), scanner.SORT_NATURAL)
        print(f"1) 排序：{[path.name for path in paths]}")
        check([path.name for path in paths] ==
              ["第1张.jpg", "第2张.png", "第3张.jpg", "第10张.jpg"],
              "按编号自然排序：1、2、3、10")

        jobs = plan_image_jobs(paths, "我的相册")
        check(len(jobs) == 1, "图片模式只产生 1 个任务")
        check(jobs[0].name == "我的相册", "任务名称为手动指定的名称")

        default_jobs = plan_image_jobs(paths, "")
        check(default_jobs[0].name == "第1张", "留空时默认使用第一张图片的名称")

        output = source / "我的相册.pdf"
        build_pdf(jobs[0].images, output, page_size_mm=(210.0, 297.0))
        check(output.exists(), "PDF 已输出到第一张图片所在目录")
        reader = PdfReader(str(output))
        check(len(reader.pages) == 4, "共 4 页，顺序与列表一致")
        print(f"   生成结果：{output.name}，{len(reader.pages)} 页")

        print("\n全部通过。")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
