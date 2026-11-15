"""媒体功能自检：探测、视频转换（含字幕处理）、音频转换与提取、字幕导出。

运行：python tests/test_media.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import media  # noqa: E402
from core.image_convert import convert_image  # noqa: E402

FFMPEG = media.ffmpeg_path()


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [通过] {message}")
    else:
        print(f"  [失败] {message}")
        raise SystemExit(1)


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=0x08000000)
    if result.returncode != 0:
        print(result.stderr[-800:])
        raise SystemExit(f"命令失败: {' '.join(cmd)}")


def make_media(root: Path) -> tuple[Path, Path]:
    video = root / "sample.mp4"
    run([
        str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video),
    ])

    srt = root / "sub.srt"
    srt.write_text(
        "1\n00:00:00,200 --> 00:00:01,500\n第一行字幕\n\n"
        "2\n00:00:01,600 --> 00:00:02,000\n第二行字幕\n",
        encoding="utf-8")

    with_subs = root / "with_subs.mkv"
    run([
        str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-i", str(srt),
        "-map", "0", "-map", "1", "-c", "copy", "-c:s", "srt",
        str(with_subs),
    ])
    return video, with_subs


def main() -> None:
    if not media.available():
        print("缺少 FFmpeg（bin 目录不完整）")
        return

    root = Path(tempfile.mkdtemp(prefix="pdf_producer_media_"))
    try:
        video, with_subs = make_media(root)

        print("1) 媒体探测")
        info = media.probe(with_subs)
        check(info.duration > 1.5, f"读取到时长 {info.duration:.1f}s")
        check(len(info.video_streams) == 1, "识别出 1 条视频流")
        check(len(info.audio_streams) == 1, "识别出 1 条音频流")
        check(len(info.text_subtitles) == 1, "识别出 1 条文本字幕轨")
        print("   字幕轨:", info.text_subtitles[0].label)

        print("2) 视频转换（MP4，字幕导出为 SRT）")
        produced = media.convert_video(
            with_subs, root / "out_export", "mp4", hardware="software",
            subtitles="export_srt")
        names = [p.name for p in produced]
        print("   生成:", names)
        check(any(p.suffix == ".mp4" for p in produced), "生成了 MP4")
        check(any(p.suffix == ".srt" for p in produced), "导出了 SRT 字幕")

        print("3) 视频转换（MKV，软封装字幕）")
        produced = media.convert_video(
            with_subs, root / "out_embed", "mkv", hardware="software",
            subtitles="embed")
        out_info = media.probe(produced[0])
        check(len(out_info.subtitle_streams) == 1, "MKV 保留了字幕轨")

        print("4) 视频转换（AVI，烧录字幕）")
        produced = media.convert_video(
            with_subs, root / "out_burn", "avi", hardware="software",
            subtitles="burn")
        check(produced[0].exists() and produced[0].stat().st_size > 0,
              "AVI 烧录字幕生成成功")

        print("5) 字幕导出（ASS）")
        info = media.probe(with_subs)
        ass = media.export_subtitle(with_subs, info.text_subtitles[0],
                                    root / "subtitle.ass")
        check(ass.exists() and "[Script Info]" in ass.read_text(encoding="utf-8", errors="replace"),
              "ASS 文件格式正确")

        print("6) 音轨提取（原样复制 / 转 MP3）")
        info = media.probe(with_subs)
        audio_stream = info.audio_streams[0]
        copied = media.extract_audio(with_subs, audio_stream, root / "audio_copy", None)
        check(copied.suffix == ".mka" and copied.exists(), "原样复制音轨到 MKA")
        mp3 = media.extract_audio(with_subs, audio_stream, root / "audio_mp3", "mp3")
        check(mp3.suffix == ".mp3" and mp3.exists(), "提取音轨并转 MP3")

        print("7) 音频格式转换")
        for key in ("flac", "wav", "m4a"):
            out = media.convert_audio(with_subs, root / f"audio_{key}", key)
            check(out.exists() and out.stat().st_size > 0, f"转换为 {key.upper()}")

        print("8) 硬件编码器检测")
        hw = media.detect_hardware(force=True)
        print("   可用厂商:", hw.available_vendors() or "无（将使用软件编码）")

        print("9) 图片格式转换")
        from PIL import Image
        source_png = root / "pic.png"
        Image.new("RGBA", (200, 150), (60, 120, 200, 200)).save(source_png)
        for key in ("jpg", "webp", "bmp", "tiff"):
            out = convert_image(source_png, root / f"pic_{key}", key)
            check(out.exists() and out.stat().st_size > 0, f"PNG → {key.upper()}")

        print("\n全部通过。")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
