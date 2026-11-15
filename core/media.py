"""FFmpeg / FFprobe 封装：媒体探测、视频音频转换、字幕与音轨提取。

- 视频转码支持硬件加速：NVIDIA（NVENC）、AMD（AMF）、Intel（QSV），
  启动时实际试编码一次来确认硬件可用，失败时自动回退软件编码。
- 字幕处理：软封装（目标容器支持时）、导出为 SRT/ASS 文件、或烧录到画面。
"""

from __future__ import annotations

import collections
import json
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
TEXT_SUBTITLE_CODECS = {
    "subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text", "microdvd",
}


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def ffmpeg_path() -> Path:
    return _base_dir() / "bin" / "ffmpeg.exe"


def ffprobe_path() -> Path:
    return _base_dir() / "bin" / "ffprobe.exe"


def available() -> bool:
    return ffmpeg_path().is_file() and ffprobe_path().is_file()


# ---------------------------------------------------------------------- 探测
@dataclass
class Stream:
    kind: str            # video / audio / subtitle
    index: int           # 全局流索引
    type_index: int      # 同类型内的序号（对应 -map 0:a:N）
    codec: str
    language: str = ""
    title: str = ""
    text_subtitle: bool = False

    @property
    def label(self) -> str:
        parts = [self.kind, f"#{self.type_index + 1}", self.codec]
        if self.language:
            parts.append(self.language)
        if self.title:
            parts.append(self.title)
        return " · ".join(parts)


@dataclass
class MediaInfo:
    path: Path
    duration: float = 0.0
    streams: list[Stream] = field(default_factory=list)

    @property
    def video_streams(self) -> list[Stream]:
        return [s for s in self.streams if s.kind == "video"]

    @property
    def audio_streams(self) -> list[Stream]:
        return [s for s in self.streams if s.kind == "audio"]

    @property
    def subtitle_streams(self) -> list[Stream]:
        return [s for s in self.streams if s.kind == "subtitle"]

    @property
    def text_subtitles(self) -> list[Stream]:
        return [s for s in self.subtitle_streams if s.text_subtitle]


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        timeout=timeout,
    )


def probe(path: Path | str) -> MediaInfo:
    """读取媒体文件的基本信息与所有流。"""
    path = Path(path)
    if not available():
        raise RuntimeError("没有找到 FFmpeg，请确认 bin 目录完整")
    result = _run([
        str(ffprobe_path()), "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ], timeout=60)
    if result.returncode != 0:
        message = (result.stderr or "").strip() or "无法读取该文件"
        raise RuntimeError(message.splitlines()[-1])

    data = json.loads(result.stdout or "{}")
    info = MediaInfo(path=path)
    try:
        info.duration = float(data.get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        info.duration = 0.0

    counters: dict[str, int] = {}
    for raw in data.get("streams", []):
        codec_type = raw.get("codec_type", "")
        if codec_type not in ("video", "audio", "subtitle"):
            continue
        if codec_type == "video" and raw.get("disposition", {}).get("attached_pic"):
            continue
        kind = codec_type
        type_index = counters.get(kind, 0)
        counters[kind] = type_index + 1
        codec = (raw.get("codec_name") or "").lower()
        tags = raw.get("tags", {}) or {}
        info.streams.append(Stream(
            kind=kind,
            index=int(raw.get("index", 0)),
            type_index=type_index,
            codec=codec,
            language=str(tags.get("language", "") or ""),
            title=str(tags.get("title", "") or ""),
            text_subtitle=(kind == "subtitle" and codec in TEXT_SUBTITLE_CODECS),
        ))
    return info


# ---------------------------------------------------------------------- 硬件
@dataclass
class HardwareInfo:
    nvidia: bool = False
    amd: bool = False
    intel: bool = False
    checked: bool = False

    def best(self) -> str | None:
        if self.nvidia:
            return "nvidia"
        if self.amd:
            return "amd"
        if self.intel:
            return "intel"
        return None

    def available_vendors(self) -> list[str]:
        vendors = []
        if self.nvidia:
            vendors.append("nvidia")
        if self.amd:
            vendors.append("amd")
        if self.intel:
            vendors.append("intel")
        return vendors


_HW_CACHE: HardwareInfo | None = None


def _try_encoder(encoder: str) -> bool:
    if not available():
        return False
    try:
        result = _run([
            str(ffmpeg_path()), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1",
            "-frames:v", "2", "-c:v", encoder, "-f", "null", "-",
        ], timeout=25)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def detect_hardware(force: bool = False) -> HardwareInfo:
    """检测本机可用的硬件编码器（会实际试编码一次）。"""
    global _HW_CACHE
    if _HW_CACHE is not None and not force:
        return _HW_CACHE

    info = HardwareInfo()
    if available():
        try:
            result = _run([str(ffmpeg_path()), "-hide_banner", "-encoders"], timeout=30)
            encoders = (result.stdout or "") + (result.stderr or "")
        except (OSError, subprocess.SubprocessError):
            encoders = ""
        if "h264_nvenc" in encoders:
            info.nvidia = _try_encoder("h264_nvenc")
        if "h264_amf" in encoders:
            info.amd = _try_encoder("h264_amf")
        if "h264_qsv" in encoders:
            info.intel = _try_encoder("h264_qsv")
    info.checked = True
    _HW_CACHE = info
    return info


HW_ENCODER = {
    "nvidia": {"h264": "h264_nvenc", "hevc": "hevc_nvenc"},
    "amd": {"h264": "h264_amf", "hevc": "hevc_amf"},
    "intel": {"h264": "h264_qsv", "hevc": "hevc_qsv"},
}

HW_EXTRA = {
    "nvidia": ["-preset", "p4", "-cq", "23"],
    "amd": ["-quality", "balanced"],
    "intel": ["-global_quality", "23"],
}


# ---------------------------------------------------------------------- 格式
@dataclass(frozen=True)
class VideoTarget:
    key: str
    label: str
    ext: str
    video_codec: str
    audio_codec: str
    subtitle_mode: str          # copy / mov_text / none
    extra: tuple = ()

    @property
    def supports_soft_subtitles(self) -> bool:
        return self.subtitle_mode != "none"


VIDEO_TARGETS: dict[str, VideoTarget] = {
    "mp4": VideoTarget("mp4", "MP4", ".mp4", "libx264", "aac", "mov_text",
                       ("-movflags", "+faststart")),
    "mkv": VideoTarget("mkv", "MKV", ".mkv", "libx264", "aac", "copy"),
    "mov": VideoTarget("mov", "MOV", ".mov", "libx264", "aac", "mov_text"),
    "avi": VideoTarget("avi", "AVI", ".avi", "mpeg4", "mp3", "none"),
    "flv": VideoTarget("flv", "FLV", ".flv", "libx264", "aac", "none"),
    "wmv": VideoTarget("wmv", "WMV", ".wmv", "wmv2", "wmav2", "none"),
    "webm": VideoTarget("webm", "WebM", ".webm", "libvpx-vp9", "libopus", "none"),
}


@dataclass(frozen=True)
class AudioTarget:
    key: str
    label: str
    ext: str
    codec: str
    extra: tuple = ()


AUDIO_TARGETS: dict[str, AudioTarget] = {
    "mp3": AudioTarget("mp3", "MP3", ".mp3", "libmp3lame", ("-b:a", "192k")),
    "aac": AudioTarget("aac", "AAC", ".aac", "aac", ("-b:a", "192k")),
    "m4a": AudioTarget("m4a", "M4A", ".m4a", "aac", ("-b:a", "192k")),
    "flac": AudioTarget("flac", "FLAC", ".flac", "flac"),
    "wav": AudioTarget("wav", "WAV", ".wav", "pcm_s16le"),
    "wma": AudioTarget("wma", "WMA", ".wma", "wmav2", ("-b:a", "192k")),
    "ogg": AudioTarget("ogg", "OGG", ".ogg", "libvorbis", ("-b:a", "192k")),
}


# ---------------------------------------------------------------------- 执行
class ConversionCancelled(Exception):
    """用户主动取消了当前转换。"""


if sys.platform == "win32":
    import ctypes

    _PROCESS_SUSPEND_RESUME = 0x0800

    def _open_process(pid: int):
        return ctypes.windll.kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, pid)

    def suspend_process(pid: int) -> bool:
        """挂起进程（冻结所有线程），用于暂停转换。"""
        handle = _open_process(pid)
        if not handle:
            return False
        try:
            return ctypes.windll.ntdll.NtSuspendProcess(handle) == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    def resume_process(pid: int) -> bool:
        handle = _open_process(pid)
        if not handle:
            return False
        try:
            return ctypes.windll.ntdll.NtResumeProcess(handle) == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
else:  # pragma: no cover - 非 Windows 平台不支持暂停
    def suspend_process(pid: int) -> bool:
        return False

    def resume_process(pid: int) -> bool:
        return False


class ProcessController:
    """管理当前运行的 ffmpeg 进程：暂停 / 继续 / 取消。"""

    def __init__(self):
        self._process = None
        self._pid: int | None = None
        self._paused = False
        self._cancelled = False
        self._lock = threading.Lock()

    def attach(self, process) -> None:
        with self._lock:
            self._process = process
            self._pid = process.pid
            self._paused = False
            self._cancelled = False

    def detach(self) -> None:
        with self._lock:
            self._process = None
            self._pid = None
            self._paused = False

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def pause(self) -> bool:
        with self._lock:
            if self._pid is None or self._paused:
                return self._paused
            if suspend_process(self._pid):
                self._paused = True
            return self._paused

    def resume(self) -> bool:
        with self._lock:
            if self._pid is None or not self._paused:
                return False
            if resume_process(self._pid):
                self._paused = False
            return not self._paused

    def toggle(self) -> bool:
        if self.paused:
            self.resume()
        else:
            self.pause()
        return self.paused

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            process = self._process
        if process is not None:
            try:
                process.terminate()
            except OSError:
                pass


def _run_ffmpeg(cmd: list[str], duration: float,
                on_progress=None, on_log=None,
                controller: ProcessController | None = None) -> None:
    """执行 ffmpeg，并从 -progress 输出解析进度。"""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if controller is not None:
        controller.attach(process)
    tail: collections.deque[str] = collections.deque(maxlen=40)
    try:
        for line in process.stdout:
            tail.append(line.rstrip())
            if line.startswith("out_time_us="):
                try:
                    microseconds = int(line.split("=", 1)[1])
                except (ValueError, IndexError):
                    continue
                if duration > 0 and on_progress:
                    on_progress(min(0.99, microseconds / 1_000_000.0 / duration))
            elif line.startswith("progress=end") and on_progress:
                on_progress(1.0)
    finally:
        process.stdout.close()
        process.wait()
        if controller is not None:
            controller.detach()

    if controller is not None and controller.cancelled:
        raise ConversionCancelled()

    if process.returncode != 0:
        message = "；".join(line for line in tail if line.strip())
        raise RuntimeError(message[-400:] or f"FFmpeg 退出码 {process.returncode}")


def _unique_output(base: Path, ext: str) -> Path:
    candidate = base.with_suffix(ext)
    index = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name} ({index})").with_suffix(ext)
        index += 1
    return candidate


# ---------------------------------------------------------------------- 视频
def convert_video(source: Path, output_base: Path, target_key: str,
                  hardware: str = "auto", subtitles: str = "auto",
                  on_progress=None, on_log=None,
                  controller: ProcessController | None = None) -> list[Path]:
    """转换视频。返回生成的文件列表（视频 + 可能导出的字幕）。"""
    source = Path(source)
    target = VIDEO_TARGETS[target_key]
    info = probe(source)
    output = _unique_output(output_base, target.ext)

    subtitle_streams = info.text_subtitles
    action = _resolve_subtitle_action(target, subtitles, subtitle_streams)

    cmd = [str(ffmpeg_path()), "-y", "-hide_banner", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", "-i", str(source),
           "-map", "0:v:0?", "-map", "0:a?"]

    codec = target.video_codec
    video_extra = list(target.extra)
    vendor = _pick_vendor(hardware)
    if vendor and target.video_codec == "libx264":
        hw_codec = HW_ENCODER[vendor]["h264"]
        codec = hw_codec
        video_extra.extend(HW_EXTRA[vendor])
        if on_log:
            names = {"nvidia": "NVIDIA NVENC", "amd": "AMD AMF", "intel": "Intel QSV"}
            on_log(f"  · 硬件加速：{names.get(vendor, vendor)}")
    elif hardware != "software" and on_log:
        on_log("  · 未检测到可用硬件编码器，使用软件编码")

    cmd += ["-c:v", codec, *video_extra, "-c:a", target.audio_codec, "-b:a", "192k"]

    produced: list[Path] = []
    burn_source: Path | None = None
    if action == "burn" and subtitle_streams:
        burn_source = Path(_temp_srt(source, subtitle_streams[0]))
        cmd += ["-vf", _subtitle_filter(burn_source)]
        if on_log:
            on_log(f"  · 字幕将烧录到画面：{subtitle_streams[0].label}")
    elif action == "embed_soft":
        cmd += ["-map", "0:s?", "-c:s", target.subtitle_mode]
        if on_log:
            on_log(f"  · 保留 {len(subtitle_streams)} 条字幕轨（软封装）")

    cmd.append(str(output))
    try:
        _run_ffmpeg(cmd, info.duration, on_progress, on_log, controller)
    except ConversionCancelled:
        output.unlink(missing_ok=True)
        raise
    finally:
        if burn_source is not None and burn_source.exists():
            burn_source.unlink(missing_ok=True)

    produced.append(output)

    if action == "export" and subtitle_streams:
        target_format = "ass" if subtitles == "export_ass" else "srt"
        for stream in subtitle_streams:
            exported = _unique_output(
                output.with_name(f"{output.stem}_字幕{stream.type_index + 1}"),
                f".{target_format}")
            export_subtitle(source, stream, exported)
            produced.append(exported)
            if on_log:
                on_log(f"  · 已导出字幕：{exported.name}")
    return produced


def _resolve_subtitle_action(target: VideoTarget, subtitles: str,
                             subtitle_streams: list[Stream]) -> str:
    if not subtitle_streams:
        return "ignore"
    if subtitles == "auto":
        return "embed_soft" if target.supports_soft_subtitles else "ignore"
    if subtitles == "ignore":
        return "ignore"
    if subtitles == "embed":
        return "embed_soft" if target.supports_soft_subtitles else "burn"
    if subtitles in ("export_srt", "export_ass"):
        return "export"
    if subtitles == "burn":
        return "burn"
    return "ignore"


def _pick_vendor(hardware: str) -> str | None:
    if hardware == "software":
        return None
    hw = detect_hardware()
    if hardware == "auto":
        return hw.best()
    if hardware == "nvidia" and hw.nvidia:
        return "nvidia"
    if hardware == "amd" and hw.amd:
        return "amd"
    if hardware == "intel" and hw.intel:
        return "intel"
    return None


def _temp_srt(source: Path, stream: Stream) -> str:
    import tempfile

    folder = Path(tempfile.mkdtemp(prefix="pdf_producer_sub_"))
    target = folder / "subtitle.srt"
    export_subtitle(source, stream, target)
    return str(target)


def _subtitle_filter(subtitle_path: Path) -> str:
    # ffmpeg 滤镜中的 Windows 路径需要转义冒号和反斜杠
    path = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
    return f"subtitles='{path}':force_style='FontName=Microsoft YaHei,FontSize=20'"


# ---------------------------------------------------------------------- 音频
def convert_audio(source: Path, output_base: Path, target_key: str,
                  on_progress=None, on_log=None,
                  controller: ProcessController | None = None) -> Path:
    source = Path(source)
    target = AUDIO_TARGETS[target_key]
    output = _unique_output(output_base, target.ext)
    info = probe(source)
    cmd = [str(ffmpeg_path()), "-y", "-hide_banner", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", "-i", str(source),
           "-vn", "-map", "0:a:0", "-c:a", target.codec, *target.extra,
           str(output)]
    try:
        _run_ffmpeg(cmd, info.duration, on_progress, on_log, controller)
    except ConversionCancelled:
        output.unlink(missing_ok=True)
        raise
    return output


def extract_audio(source: Path, stream: Stream, output_base: Path,
                  target_key: str | None,
                  on_progress=None, on_log=None,
                  controller: ProcessController | None = None) -> Path:
    """提取指定音轨；target_key 为 None 时原样复制到 mka 容器。"""
    source = Path(source)
    info = probe(source)
    if target_key is None:
        output = _unique_output(output_base, ".mka")
        codec_args = ["-c:a", "copy"]
    else:
        target = AUDIO_TARGETS[target_key]
        output = _unique_output(output_base, target.ext)
        codec_args = ["-c:a", target.codec, *target.extra]
    cmd = [str(ffmpeg_path()), "-y", "-hide_banner", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", "-i", str(source),
           "-map", f"0:a:{stream.type_index}", *codec_args, str(output)]
    try:
        _run_ffmpeg(cmd, info.duration, on_progress, on_log, controller)
    except ConversionCancelled:
        output.unlink(missing_ok=True)
        raise
    return output


# ---------------------------------------------------------------------- 字幕
def export_subtitle(source: Path, stream: Stream, output: Path,
                    on_progress=None, on_log=None,
                    controller: ProcessController | None = None) -> Path:
    """把指定字幕轨导出为 SRT 或 ASS（由输出扩展名决定）。"""
    source = Path(source)
    output = Path(output)
    fmt = output.suffix.lstrip(".").lower() or "srt"
    codec = "ass" if fmt == "ass" else "srt"
    info = probe(source)
    cmd = [str(ffmpeg_path()), "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(source),
           "-map", f"0:s:{stream.type_index}",
           "-c:s", codec,
           str(output)]
    try:
        _run_ffmpeg(cmd, 0.0, on_progress, on_log, controller)
    except ConversionCancelled:
        output.unlink(missing_ok=True)
        raise
    return output
