"""核心逻辑自检：扫描排序、JPG 转换、PDF 生成。

直接运行：python tests/test_core.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core import scanner  # noqa: E402
from core.converter import convert_to_jpg  # noqa: E402
from core.pdf_builder import build_pdf  # noqa: E402


def make_test_images(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    colors = [
        (226, 87, 87), (240, 160, 70), (245, 214, 88), (150, 200, 90),
        (80, 180, 140), (70, 150, 220), (90, 110, 200), (150, 100, 210),
        (210, 100, 180), (120, 120, 130),
    ]
    # 故意乱序创建，验证排序不依赖创建顺序
    for number in (7, 2, 10, 1, 5, 3, 9, 4, 8, 6):
        width = 600 + number * 40
        height = 400 + number * 30
        image = Image.new("RGB", (width, height), colors[number - 1])
        image.save(folder / f"{number}.jpg", quality=92)
        image.close()
        time.sleep(0.01)

    # 非 JPG 格式（四角透明，中间是不透明的圆形）
    from PIL import ImageDraw

    png = Image.new("RGBA", (500, 380), (0, 0, 0, 0))
    draw = ImageDraw.Draw(png)
    draw.ellipse((50, 40, 450, 340), fill=(40, 120, 200, 255))
    png.save(folder / "封面.png")
    png.close()

    bmp = Image.new("RGB", (420, 300), (200, 90, 40))
    bmp.save(folder / "扫描.bmp")
    bmp.close()

    # 带 EXIF 方向的 JPEG
    jpeg = Image.new("RGB", (640, 480), (60, 160, 120))
    exif = Image.Exif()
    exif[274] = 6  # Orientation = 顺时针旋转 90°
    jpeg.save(folder / "旋转照片.jpg", quality=92, exif=exif)
    jpeg.close()


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [通过] {message}")
    else:
        print(f"  [失败] {message}")
        raise SystemExit(1)


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="pdf_producer_test_"))
    try:
        source = temp_root / "照片文件夹"
        make_test_images(source)
        out_dir = temp_root / "输出"
        out_dir.mkdir()

        print("1) 扫描与自然排序")
        images = scanner.scan_folder(source)
        names = [p.name for p in images]
        print("   顺序:", " -> ".join(names))
        check(len(images) == 13, "共扫描到 13 张图片")
        numbers = [p for p in images if p.stem.isdigit()]
        check([p.stem for p in numbers] == [str(i) for i in range(1, 11)],
              "数字编号按 1..10 自然排序（不是 1,10,2...）")

        print("2) 非 JPG 格式转换")
        non_jpg = [p for p in images if not scanner.is_jpg(p)]
        check(len(non_jpg) == 2, "识别出 2 张非 JPG 图片（PNG / BMP）")
        converted_dir = temp_root / "转换"
        converted = [convert_to_jpg(p, converted_dir) for p in non_jpg]
        for path in converted:
            with Image.open(path) as checkImage:
                check(checkImage.format == "JPEG", f"{path.name} 已转换为 JPEG")
        with Image.open(converted[0]) as png_as_jpg:
            check(png_as_jpg.size == (500, 380), "PNG 转换后尺寸不变")
            check(png_as_jpg.getpixel((5, 5))[0] > 200,
                  "PNG 透明区域已填成白色")

        print("3) 生成 PDF（与图片相同大小）")
        all_images = [convert_to_jpg(p, converted_dir) if not scanner.is_jpg(p) else p
                      for p in images]
        output = out_dir / "照片文件夹.pdf"
        engine = build_pdf(all_images, output, page_size_mm=None, log=print)
        print("   引擎:", engine)
        check(output.exists() and output.stat().st_size > 0, "PDF 文件已生成")

        from pypdf import PdfReader
        reader = PdfReader(str(output))
        check(len(reader.pages) == 13, "PDF 页数 = 13")
        box = reader.pages[0].mediabox
        # 1.jpg 尺寸 640x430，96dpi 下 1px = 0.75pt
        print(f"   第一页尺寸: {float(box.width):.1f} x {float(box.height):.1f} pt")
        check(abs(float(box.width) - 640 * 0.75) < 2, "第一页宽度与图片一致")

        print("4) 生成 PDF（A4 页面）")
        output_a4 = out_dir / "照片文件夹_A4.pdf"
        engine = build_pdf(all_images, output_a4, page_size_mm=(210.0, 297.0), log=print)
        print("   引擎:", engine)
        reader_a4 = PdfReader(str(output_a4))
        box_a4 = reader_a4.pages[0].mediabox
        print(f"   第一页尺寸: {float(box_a4.width):.1f} x {float(box_a4.height):.1f} pt")
        check(abs(float(box_a4.width) - 595.28) < 1, "A4 页面宽度 = 595pt")

        print("5) 其它常用纸张尺寸")
        for label, (width_mm, height_mm) in (("A5", (148.0, 210.0)),
                                             ("B5", (176.0, 250.0)),
                                             ("Letter", (215.9, 279.4)),
                                             ("自定义 100x150", (100.0, 150.0))):
            target = out_dir / f"{label}.pdf"
            build_pdf(all_images[:1], target, page_size_mm=(width_mm, height_mm))
            page_box = PdfReader(str(target)).pages[0].mediabox
            expected = width_mm / 25.4 * 72
            check(abs(float(page_box.width) - expected) < 1,
                  f"{label} 页面宽度 {float(page_box.width):.1f}pt（应为 {expected:.1f}pt）")

        print("6) 同名文件自动编号")
        print("   已存在同名文件，生成时应由调用方处理（resolve_output_path）")

        print("\n全部通过。测试目录:", temp_root)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
