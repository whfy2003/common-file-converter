"""把一组图片按顺序合成为一个 PDF 文件。

优先使用 img2pdf：它会把 JPG 原始数据直接嵌入 PDF，不重新压缩，速度快、体积小。
如果遇到特殊图片（例如 CMYK JPEG）导致无损写入失败，会自动退回 Pillow 重新编码的方案。

页面尺寸支持两种方式：
- None：每页大小与图片本身一致（按图片 DPI 换算）；
- (宽, 高) 毫米：统一页面尺寸，图片等比缩放后居中放置。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFile

from core.converter import DEFAULT_DPI, open_frame, to_rgb

ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    import img2pdf
except ImportError:  # pragma: no cover - 环境缺依赖时走兼容方案
    img2pdf = None

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0
# 兼容方案（Pillow）使用的渲染分辨率
RENDER_DPI = 96.0

# 常用纸张尺寸（毫米，纵向）
PAGE_PRESETS: list[tuple[str, str, tuple[float, float] | None]] = [
    ("auto", "与图片相同大小", None),
    ("A3", "A3　297 × 420 mm", (297.0, 420.0)),
    ("A4", "A4　210 × 297 mm", (210.0, 297.0)),
    ("A5", "A5　148 × 210 mm", (148.0, 210.0)),
    ("B4", "B4　250 × 353 mm", (250.0, 353.0)),
    ("B5", "B5　176 × 250 mm", (176.0, 250.0)),
    ("Letter", "Letter　216 × 279 mm", (215.9, 279.4)),
    ("Legal", "Legal　216 × 356 mm", (215.9, 355.6)),
    ("custom", "自定义尺寸…", None),
]

PRESET_MM = {key: size for key, _label, size in PAGE_PRESETS if size is not None}
PRESET_LABELS = {key: label for key, label, _size in PAGE_PRESETS}


def mm_to_pt(value: float) -> float:
    return value / MM_PER_INCH * PT_PER_INCH


def mm_to_px(value: float) -> int:
    return max(1, int(round(value / MM_PER_INCH * RENDER_DPI)))


def page_px(page_size_mm: tuple[float, float] | None) -> tuple[int, int] | None:
    """把毫米尺寸换算成 96 DPI 下的像素尺寸（兼容方案使用）。"""
    if page_size_mm is None:
        return None
    return (mm_to_px(page_size_mm[0]), mm_to_px(page_size_mm[1]))


def _layout_for(page_size_mm: tuple[float, float] | None):
    if img2pdf is None:
        raise RuntimeError("img2pdf 不可用")
    if page_size_mm is None:
        # 默认布局：页面大小等于图片本身（按图片 DPI 换算）
        return img2pdf.get_layout_fun()
    width_pt = mm_to_pt(page_size_mm[0])
    height_pt = mm_to_pt(page_size_mm[1])
    return img2pdf.get_layout_fun(pagesize=(width_pt, height_pt),
                                  fit=img2pdf.FitMode.into)


def build_pdf(image_paths, output_path: Path | str,
              page_size_mm: tuple[float, float] | None = None,
              quality: int = 95, log=None) -> str:
    """把 image_paths 按顺序合成 output_path。

    返回实际使用的引擎名称（"img2pdf" 或 "pillow"）。
    """
    image_paths = [Path(p) for p in image_paths]
    output_path = Path(output_path)
    if not image_paths:
        raise ValueError("没有可合并的图片")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if img2pdf is not None:
        try:
            _build_with_img2pdf(image_paths, output_path, page_size_mm)
            return "img2pdf"
        except Exception as exc:  # noqa: BLE001 - 需要兜底任何图片异常
            try:
                if output_path.exists():
                    output_path.unlink()
            except OSError:
                pass
            if log:
                log(f"  · 无损写入失败（{exc}），改用兼容模式重新生成")

    _build_with_pillow(image_paths, output_path, page_size_mm, quality, log)
    return "pillow"


def _build_with_img2pdf(image_paths: list[Path], output_path: Path,
                        page_size_mm: tuple[float, float] | None) -> None:
    layout = _layout_for(page_size_mm)
    with open(output_path, "wb") as handle:
        img2pdf.convert(
            [str(p) for p in image_paths],
            layout_fun=layout,
            outputstream=handle,
        )


def _render_page(path: Path, target_px: tuple[int, int] | None) -> Image.Image:
    """把一张图片渲染成 PDF 页码图像（兼容方案使用）。"""
    image = open_frame(path)
    try:
        rgb = to_rgb(image)
        try:
            if target_px is not None:
                canvas = Image.new("RGB", target_px, (255, 255, 255))
                scaled = rgb.copy()
                try:
                    scaled.thumbnail(target_px, Image.LANCZOS)
                    left = (target_px[0] - scaled.width) // 2
                    top = (target_px[1] - scaled.height) // 2
                    canvas.paste(scaled, (left, top))
                finally:
                    scaled.close()
                return canvas
            return rgb.copy()
        finally:
            if rgb is not image:
                rgb.close()
    finally:
        image.close()


def _build_with_pillow(image_paths: list[Path], output_path: Path,
                       page_size_mm: tuple[float, float] | None,
                       quality: int, log=None) -> None:
    target_px = page_px(page_size_mm)
    pages: list[Image.Image] = []
    total = len(image_paths)
    try:
        for index, path in enumerate(image_paths, 1):
            pages.append(_render_page(path, target_px))
            if log and total > 40 and index % 20 == 0:
                log(f"  · 已处理 {index}/{total} 页")
        first, rest = pages[0], pages[1:]
        first.save(
            output_path,
            "PDF",
            save_all=True,
            append_images=rest,
            resolution=(RENDER_DPI, RENDER_DPI),
            quality=quality,
        )
    finally:
        for page in pages:
            try:
                page.close()
            except Exception:
                pass
