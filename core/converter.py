"""图片格式处理：读取、方向校正、透明背景填白、转换为 JPG。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

DEFAULT_DPI = 96


def get_safe_dpi(image: Image.Image) -> tuple[float, float]:
    """读取图片自带的 DPI；数值不合理时退回 96。"""
    dpi = image.info.get("dpi")
    if isinstance(dpi, (tuple, list)) and len(dpi) >= 2:
        try:
            x, y = float(dpi[0]), float(dpi[1])
            if 1.0 <= x <= 1200.0 and 1.0 <= y <= 1200.0:
                return (x, y)
        except (TypeError, ValueError):
            pass
    return (DEFAULT_DPI, DEFAULT_DPI)


def to_rgb(image: Image.Image) -> Image.Image:
    """转换为 RGB 图像；如果有透明区域，用白色填充。"""
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        rgba.close()
        return canvas
    try:
        return image.convert("RGB")
    except Exception:
        return image.convert("L").convert("RGB")


def open_frame(path: Path | str) -> Image.Image:
    """打开图片并返回可安全使用的对象：只取第一帧、按 EXIF 方向摆正。"""
    raw = Image.open(path)
    try:
        raw.seek(0)
    except (EOFError, ValueError, OSError):
        pass
    try:
        image = ImageOps.exif_transpose(raw)
    except Exception:
        image = raw.copy()
    if image is not raw:
        raw.close()
    return image


def unique_path(path: Path) -> Path:
    """若目标文件已存在，追加 _1、_2 后缀。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    index = 1
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def convert_to_jpg(source: Path | str, target_dir: Path | str,
                   quality: int = 95) -> Path:
    """把任意支持的图片转换为 JPG，保存到 target_dir 并返回新路径。

    - 透明背景填白
    - 按 EXIF 方向摆正
    - 动图只取第一帧
    - 尽量保留原图 DPI 信息
    """
    source = Path(source)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    image = open_frame(source)
    try:
        dpi = get_safe_dpi(image)
        rgb = to_rgb(image)
        try:
            target = unique_path(target_dir / f"{source.stem}.jpg")
            rgb.save(target, "JPEG", quality=quality, dpi=dpi, optimize=True)
        finally:
            if rgb is not image:
                rgb.close()
    finally:
        image.close()

    return target
