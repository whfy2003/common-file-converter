"""选项逻辑测试：输出路径、冲突策略、子文件夹模式、递归扫描与页面尺寸。"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core import scanner  # noqa: E402
from core.models import Job  # noqa: E402
from core.pdf_builder import build_pdf  # noqa: E402
from core.planning import plan_folder_jobs, resolve_output_path, safe_name  # noqa: E402


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [通过] {message}")
    else:
        print(f"  [失败] {message}")
        raise SystemExit(1)


def make_image(path: Path, color=(120, 160, 220), size=(400, 300)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color)
    image.save(path)
    image.close()


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="pdf_producer_opts_"))
    try:
        out_dir = root / "输出"
        out_dir.mkdir()

        print("1) 同名文件处理")
        job = Job(name="测试", images=[], source_dir=root)
        options_auto = {"output_mode": "source", "output_dir": "", "conflict": "auto"}
        options_over = {"output_mode": "source", "output_dir": "", "conflict": "overwrite"}
        options_skip = {"output_mode": "source", "output_dir": "", "conflict": "skip"}

        first = resolve_output_path(job, options_auto)
        check(first.name == "测试.pdf", "没有同名文件时直接使用「名称.pdf」")
        first.write_bytes(b"%PDF-1.4")
        second = resolve_output_path(job, options_auto)
        check(second.name == "测试 (2).pdf", "自动编号：测试.pdf → 测试 (2).pdf")
        second.write_bytes(b"%PDF-1.4")
        third = resolve_output_path(job, options_auto)
        check(third.name == "测试 (3).pdf", "自动编号：测试 (2).pdf → 测试 (3).pdf")
        check(resolve_output_path(job, options_over).name == "测试.pdf",
              "覆盖模式返回同名文件")
        check(resolve_output_path(job, options_skip) is None,
              "跳过模式返回 None")

        print("2) 指定输出目录")
        custom = {"output_mode": "custom", "output_dir": str(out_dir),
                  "conflict": "auto"}
        check(resolve_output_path(job, custom).parent == out_dir,
              "自定义目录时输出到指定文件夹")

        print("3) 文件名清理")
        check(safe_name('a/b:c*?"<>|') == "a_b_c______", "非法字符被替换为下划线")
        check(safe_name("  ..名字..  ") == "名字", "首尾的点和空格被去掉")
        check(safe_name("***") == "___", "全非法字符被替换为下划线")
        check(safe_name("   ") == "合并文件", "空名称使用兜底名称")

        print("4) 子文件夹输出模式")
        parent = root / "父目录"
        make_image(parent / "1.jpg")
        make_image(parent / "子A" / "1.jpg")
        make_image(parent / "子A" / "2.jpg")
        make_image(parent / "子B" / "1.jpg")

        single = scanner.scan_for_mode(parent, scanner.OUTPUT_SINGLE)
        check(len(single) == 1 and len(single[0][1]) == 1,
              "只合并当前文件夹：1 个 PDF、1 张图片")

        per_sub = scanner.scan_for_mode(parent, scanner.OUTPUT_PER_SUBFOLDER)
        check(len(per_sub) == 3, "每个子文件夹各一个 PDF：共 3 个（含当前文件夹）")
        names = [target.name for target, _images in per_sub]
        check(names == ["父目录", "子A", "子B"], "顺序：当前文件夹 → 子文件夹（自然排序）")

        merged = scanner.scan_for_mode(parent, scanner.OUTPUT_MERGE_ALL)
        check(len(merged) == 1 and len(merged[0][1]) == 4,
              "全部合并：1 个 PDF、4 张图片")

        jobs = plan_folder_jobs(parent, scanner.OUTPUT_PER_SUBFOLDER, scanner.SORT_NATURAL)
        check(len(jobs) == 3, "规划任务：3 个 PDF")
        check(jobs[1].name == "子A" and jobs[1].source_dir == parent,
              "子文件夹 PDF 以其目录名命名，输出到上级文件夹")

        print("5) 递归扫描与排序")
        nested = root / "带子目录"
        make_image(nested / "2.jpg")
        make_image(nested / "10.jpg")
        make_image(nested / "子目录" / "3.jpg")
        top_only = scanner.scan_folder(nested, recursive=False)
        check(len(top_only) == 2, "不包含子文件夹时只扫描当前层")
        all_images = scanner.scan_folder(nested, recursive=True)
        check(len(all_images) == 3, "包含子文件夹时扫描到 3 张")
        names = [path.name for path in all_images]
        check(names[0] == "2.jpg" and names[1] == "10.jpg",
              "按相对路径自然排序（子目录排在后面）")

        print("6) 页面尺寸选项")
        single_dir = root / "单张"
        single_dir.mkdir()
        make_image(single_dir / "1.jpg", size=(800, 600))

        from pypdf import PdfReader

        pdf = out_dir / "原始.pdf"
        build_pdf([single_dir / "1.jpg"], pdf, page_size_mm=None)
        box = PdfReader(str(pdf)).pages[0].mediabox
        check(abs(float(box.width) - 800 * 0.75) < 2,
              "与图片相同大小：页面宽度与图片像素对应")

        for label, (width_mm, height_mm) in (("A4", (210.0, 297.0)),
                                             ("A5", (148.0, 210.0)),
                                             ("B5", (176.0, 250.0)),
                                             ("Letter", (215.9, 279.4)),
                                             ("自定义 100x150", (100.0, 150.0))):
            target = out_dir / f"{label}.pdf"
            build_pdf([single_dir / "1.jpg"], target,
                      page_size_mm=(width_mm, height_mm))
            page_box = PdfReader(str(target)).pages[0].mediabox
            expected = width_mm / 25.4 * 72
            check(abs(float(page_box.width) - expected) < 1,
                  f"{label} 页面宽度 {float(page_box.width):.1f}pt")

        print("\n全部通过。")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
