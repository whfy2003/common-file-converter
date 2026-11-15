"""图片格式转换（JPG / PNG / WebP / BMP / GIF / TIFF / ICO）。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from core.converter import open_frame, to_rgb

IMAGE_TARGETS: dict[str, dict] = {
    "jpg": {"label": "JPG", "ext": ".jpg", "format": "JPEG"},
    "png": {"label": "PNG", "ext": ".png", "format": "PNG"},
    "webp": {"label": "WebP", "ext": ".webp", "format": "WEBP"},
    "bmp": {"label": "BMP", "ext": ".bmp", "format": "BMP"},
    "gif": {"label": "GIF", "ext": ".gif", "format": "GIF"},
    "tiff": {"label": "TIFF", "ext": ".tiff", "format": "TIFF"},
    "ico": {"label": "ICO 图标", "ext": ".ico", "format": "ICO"},
}

# 常用图标尺寸（16 到 1024）
ICO_SIZES = [16, 24, 32, 48, 64, 96, 128, 256, 512, 1024]


def unique_output(base: Path, ext: str) -> Path:
    candidate = base.with_suffix(ext)
    index = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name} ({index})").with_suffix(ext)
        index += 1
    return candidate


def convert_image(source: Path, output_base: Path, target_key: str,
                  quality: int = 92) -> Path:
    """把一张图片转换成目标格式，返回实际写入的文件。"""
    source = Path(source)
    output_base = Path(output_base)
    spec = IMAGE_TARGETS[target_key]
    output = unique_output(output_base, spec["ext"])

    image = open_frame(source)
    try:
        fmt = spec["format"]
        if fmt == "JPEG":
            rgb = to_rgb(image)
            try:
                rgb.save(output, "JPEG", quality=quality, optimize=True)
            finally:
                if rgb is not image:
                    rgb.close()
        elif fmt == "BMP":
            rgb = to_rgb(image)
            try:
                rgb.save(output, "BMP")
            finally:
                if rgb is not image:
                    rgb.close()
        elif fmt == "WEBP":
            image.save(output, "WEBP", quality=quality)
        elif fmt == "GIF":
            converted = image.convert("P")
            try:
                converted.save(output, "GIF")
            finally:
                converted.close()
        elif fmt == "TIFF":
            image.save(output, "TIFF")
        else:
            image.save(output, "PNG")
    finally:
        image.close()
    return output


def render_ico_image(source: Path | str, size: int, background: str = "transparent",
                     corner: str = "square") -> Image.Image:
    """按图标设置渲染一张正方形 RGBA 图像。

    - background：transparent（透明）/ white（白色填充）
    - corner：round（圆角）/ square（矩形）
    """
    size = max(8, int(size))
    image = open_frame(source)
    try:
        content = image.convert("RGBA")
    finally:
        image.close()

    canvas = Image.new(
        "RGBA", (size, size),
        (255, 255, 255, 255) if background == "white" else (0, 0, 0, 0))

    scaled = content.copy()
    try:
        scaled.thumbnail((size, size), Image.LANCZOS)
        left = (size - scaled.width) // 2
        top = (size - scaled.height) // 2
        canvas.alpha_composite(scaled, (left, top))
    finally:
        scaled.close()
        content.close()

    if corner == "round":
        radius = max(2, int(size * 0.18))
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
        alpha = canvas.getchannel("A")
        combined = ImageChops.multiply(alpha, mask)
        canvas.putalpha(combined)
        alpha.close()
        combined.close()
        mask.close()

    return canvas


def convert_to_ico(source: Path, output_base: Path, sizes: list[int],
                   background: str = "transparent", corner: str = "square") -> Path:
    """把图片转换为多尺寸 ICO 图标。

    ICO 规范最大为 256×256，超过的尺寸会按 256 处理。
    """
    chosen = sorted({int(size) for size in sizes}) or [256]
    chosen = [size for size in chosen if 16 <= size <= 256] or [256]
    max_size = max(chosen)

    canvas = render_ico_image(source, max_size, background, corner)
    output = unique_output(Path(output_base), ".ico")
    try:
        canvas.save(output, format="ICO", sizes=[(size, size) for size in chosen])
    finally:
        canvas.close()
    return output
