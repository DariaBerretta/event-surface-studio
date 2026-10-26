"""Backend for Event Surface Studio. All external commands use argument lists."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile


SURFACES = ("ISO", "TW", "SCARF", "EROS", "ChainSAE", "AEDSAE", "AAE")
MODE_FLAGS = {
    "ISO": None,
    "TW": "--tw",
    "SCARF": "--scarf",
    "EROS": "--eros",
    "ChainSAE": "--chainsae",
    "AEDSAE": "--aedsae",
    "AAE": "--aae",
}
MODE_PARAMETERS = {
    "ISO": {"window": 0.5, "frontblur": 0.02},
    "TW": {"window": 0.01},
    "SCARF": {"block_size": 14, "alpha": 1.0, "C": 0.3},
    "EROS": {"block_size": 7, "alpha": 0.3},
    "ChainSAE": {},
    "AEDSAE": {"window": 0.3, "lambda": 0.3},
    "AAE": {"block_size": 15},
}
MODE_DESCRIPTIONS = {
    "ISO": "3D space-time projection (x, y, t)",
    "TW": "Temporal window of accumulated events",
    "SCARF": "Spatially accumulated event surface",
    "EROS": "Exponentially reduced ordinal surface",
    "ChainSAE": "Chain surface of active events",
    "AEDSAE": "Adaptive exponential-decay surface",
    "AAE": "Adaptive activity event surface",
}


class StudioError(RuntimeError):
    """A user-facing backend error."""


@dataclass(frozen=True)
class RenderSettings:
    source: Path
    output: Path
    surface: str
    fps: int = 30
    rate: float = 1.0
    width: int = 640
    height: int = 480
    parameters: dict[str, float | int] = field(default_factory=dict)
    timestamps: Path | None = None


@dataclass(frozen=True)
class BackendSettings:
    binary: Path = field(default_factory=lambda: Path.home() / "event-driven-vlog-build/bin/vLog2vid")
    use_micromamba: bool = True
    env_name: str = "eventvideo"
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"


def safe_slug(text: str) -> str:
    result = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in text.strip())
    return result.strip("_")[:96] or "recording"


def default_video_prefix(source: Path) -> str:
    if source.name == "data.log" and len(source.parents) >= 2:
        return safe_slug(f"{source.parent.parent.name}_{source.parent.name}")
    return safe_slug(source.stem)


def video_path(output_dir: Path, prefix: str, mode: str) -> Path:
    return output_dir / f"{safe_slug(prefix)}_{safe_slug(mode)}.mp4"


def _check_path(path: Path, what: str) -> Path:
    expanded = path.expanduser().resolve()
    if not expanded.is_file():
        raise StudioError(f"{what} does not exist or is not a file: {expanded}")
    return expanded


def validate_render(settings: RenderSettings) -> None:
    _check_path(settings.source, "Event log")
    if settings.surface not in SURFACES:
        raise StudioError(f"Unknown surface: {settings.surface}")
    if settings.fps < 1 or settings.fps > 240:
        raise StudioError("FPS must be between 1 and 240")
    if not math.isfinite(settings.rate) or settings.rate <= 0:
        raise StudioError("Playback rate must be positive")
    if settings.width < 16 or settings.height < 16:
        raise StudioError("Width and height must both be >= 16")
    if settings.width % 2 or settings.height % 2:
        raise StudioError("Width and height must be even for H.264 video output")
    if settings.timestamps is not None:
        _check_path(settings.timestamps, "Timestamps file")
    allowed = MODE_PARAMETERS[settings.surface]
    if set(settings.parameters) - set(allowed):
        raise StudioError("Unsupported parameters for surface " + settings.surface)
    for key, value in settings.parameters.items():
        if not math.isfinite(float(value)):
            raise StudioError(f"Invalid {key}")
        if key == "block_size":
            if int(value) < 1 or float(value) != int(value):
                raise StudioError("block_size must be a positive integer")
        elif key == "window" and value <= 0:
            raise StudioError("window must be positive")
        elif key in ("alpha", "frontblur", "lambda", "C") and value < 0:
            raise StudioError(f"{key} cannot be negative")


def render_command(settings: RenderSettings, backend: BackendSettings) -> list[str]:
    validate_render(settings)
    binary = _check_path(backend.binary, "vLog2vid executable")
    command = [str(binary), "--file", str(settings.source.expanduser().resolve()),
               "--out", str(settings.output.expanduser().resolve()),
               "--fps", str(settings.fps), "--rate", str(settings.rate),
               "--width", str(settings.width), "--height", str(settings.height)]
    if settings.timestamps:
        command += ["--timestamps", str(settings.timestamps.expanduser().resolve())]
    flag = MODE_FLAGS[settings.surface]
    if flag:
        command.append(flag)
    values = {**MODE_PARAMETERS[settings.surface], **settings.parameters}
    for key, value in values.items():
        command += [f"--{key}", str(value)]
    if backend.use_micromamba:
        if not shutil.which("micromamba"):
            raise StudioError("micromamba was not found on PATH")
        command = ["micromamba", "run", "-n", backend.env_name, *command]
    return command


def _run(command: list[str], progress: Callable[[str], None] | None = None) -> str:
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors="replace", bufsize=1)
    except FileNotFoundError as error:
        raise StudioError(f"Command not found: {command[0]}") from error
    tail: deque[str] = deque(maxlen=85)
    assert process.stdout is not None
    try:
        for line in process.stdout:
            # vLog2vid prints carriage-return-delimited progress updates.
            tail.append(line[-2500:].strip())
            if progress and line.strip():
                progress(line[-250:].strip())
    finally:
        process.stdout.close()
    code = process.wait()
    output = "\n".join(tail)
    if code != 0:
        raise StudioError(f"Command failed (exit {code}):\n{output}")
    return output


def render_video(settings: RenderSettings, backend: BackendSettings,
                 overwrite: bool = False, progress: Callable[[str], None] | None = None) -> Path:
    if settings.output.exists() and not overwrite:
        raise StudioError(f"Output already exists: {settings.output}. Enable overwrite or change the name.")
    settings.output.parent.mkdir(parents=True, exist_ok=True)
    command = render_command(settings, backend)
    _run(command, progress)
    if not settings.output.is_file() or settings.output.stat().st_size == 0:
        raise StudioError("vLog2vid finished without producing a video. Check codec avc1/H.264 availability.")
    manifest = {
        "tool": "Event Surface Studio",
        "rendered_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(settings.source.expanduser().resolve()),
        "output": str(settings.output.expanduser().resolve()),
        "surface": settings.surface,
        "fps": settings.fps, "rate": settings.rate,
        "width": settings.width, "height": settings.height,
        "parameters": {**MODE_PARAMETERS[settings.surface], **settings.parameters},
        "timestamps": str(settings.timestamps) if settings.timestamps else None,
        "command": command,
    }
    settings.output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    return settings.output


def probe_video(path: Path, ffprobe: str = "ffprobe") -> dict:
    _check_path(path, "Video")
    command = [ffprobe, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height,r_frame_rate,nb_frames:format=duration",
               "-of", "json", str(path)]
    try:
        process = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise StudioError(f"ffprobe not found: {ffprobe}. Install FFmpeg first.") from error
    if process.returncode:
        raise StudioError("Cannot inspect video: " + process.stderr[-1000:])
    try:
        payload = json.loads(process.stdout)
        stream = payload["streams"][0]
        duration = float(payload.get("format", {}).get("duration") or 0)
        fps_parts = (stream.get("r_frame_rate") or "0/1").split("/")
        fps = float(fps_parts[0]) / float(fps_parts[1])
        if not duration and fps and stream.get("nb_frames"):
            duration = int(stream["nb_frames"]) / fps
        if duration <= 0:
            raise ValueError("missing or invalid duration")
        return {"duration": duration, "width": int(stream["width"]),
                "height": int(stream["height"]), "fps": fps,
                "frames": stream.get("nb_frames")}
    except (ValueError, KeyError, IndexError, ZeroDivisionError) as error:
        raise StudioError("ffprobe could not determine video duration/format") from error


def validate_interval(start: float, end: float, duration: float) -> None:
    if not all(math.isfinite(x) for x in (start, end, duration)):
        raise StudioError("Timestamps must be finite")
    if start < 0 or end <= start or end > duration + 0.05:
        raise StudioError(f"Invalid selection {start:.3f} - {end:.3f}s; video length {duration:.3f}s")


def crop_filter(crop: tuple[int, int, int, int] | None,
                video_width: int, video_height: int) -> list[str]:
    if crop is None:
        return []
    x, y, width, height = crop
    if (x < 0 or y < 0 or width < 1 or height < 1
            or x + width > video_width or y + height > video_height):
        raise StudioError("Crop must fit within the video image")
    return [f"crop={width}:{height}:{x}:{y}"]


def extract_frame_bytes(video: Path, at: float, backend: BackendSettings) -> bytes:
    """Get an uncropped PNG frame for the interactive ROI preview.

    Unlike save_still, no file is written to disk. Browser-side preview sizes
    can subsequently be reduced without altering the crop's source dimensions.
    """
    _check_path(video, "Video")
    if not math.isfinite(at) or at < 0:
        raise StudioError("Preview timestamp must be non-negative")
    cmd = [backend.ffmpeg, "-hide_banner", "-loglevel", "error", "-ss",
           f"{at:.6f}", "-i", str(video), "-frames:v", "1", "-f",
           "image2pipe", "-vcodec", "png", "pipe:1"]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError as error:
        raise StudioError(f"ffmpeg not found: {backend.ffmpeg}. Install FFmpeg first.") from error
    if proc.returncode or not proc.stdout:
        raise StudioError("Could not extract ROI preview frame: " +
                          proc.stderr.decode("utf-8", errors="replace")[-800:])
    return proc.stdout


def still_command(video: Path, at: float, destination: Path, backend: BackendSettings,
                  crop: tuple[int, int, int, int] | None = None,
                  video_size: tuple[int, int] | None = None) -> list[str]:
    if not math.isfinite(at) or at < 0:
        raise StudioError("Screenshot time must be non-negative")
    cmd = [backend.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{at:.6f}", "-i", str(video), "-frames:v", "1"]
    if crop:
        if video_size is None:
            raise StudioError("Video size required for crop")
        cmd += ["-vf", ",".join(crop_filter(crop, *video_size))]
    if destination.suffix.lower() in (".jpg", ".jpeg"):
        cmd += ["-q:v", "2"]
    return [*cmd, str(destination)]


def save_still(video: Path, at: float, destination: Path, backend: BackendSettings,
               crop: tuple[int, int, int, int] | None = None,
               video_size: tuple[int, int] | None = None) -> Path:
    _check_path(video, "Video")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(still_command(video, at, destination, backend, crop, video_size))
    if not destination.is_file() or not destination.stat().st_size:
        raise StudioError("No frame was produced at the selected timestamp")
    return destination


def sequence_command(video: Path, start: float, end: float, interval: float,
                     output_pattern: Path, backend: BackendSettings,
                     crop: tuple[int, int, int, int] | None = None,
                     video_size: tuple[int, int] | None = None) -> list[str]:
    if not math.isfinite(interval) or interval <= 0:
        raise StudioError("Frame interval must be positive")
    if start < 0 or end <= start:
        raise StudioError("Invalid frame interval selection")
    filters = [f"fps={1.0 / interval:.9f}"]
    if crop:
        if video_size is None:
            raise StudioError("Video size required for crop")
        filters += crop_filter(crop, *video_size)
    cmd = [backend.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{start:.6f}", "-t", f"{end-start:.6f}", "-i", str(video),
           "-vf", ",".join(filters), "-start_number", "0"]
    if output_pattern.suffix.lower() in (".jpg", ".jpeg"):
        cmd += ["-q:v", "2"]
    return [*cmd, str(output_pattern)]


def save_sequence(video: Path, start: float, end: float, interval: float,
                  destination: Path, image_format: str, backend: BackendSettings,
                  crop: tuple[int, int, int, int] | None = None,
                  video_size: tuple[int, int] | None = None,
                  max_images: int = 1000) -> list[Path]:
    _check_path(video, "Video")
    if image_format not in ("png", "jpg"):
        raise StudioError("Image format must be png or jpg")
    if not math.isfinite(interval) or interval <= 0:
        raise StudioError("Frame interval must be positive")
    estimate = math.ceil((end - start) / interval)
    if estimate > max_images:
        raise StudioError(f"Selection would export approximately {estimate} frames (limit {max_images})")
    if destination.exists() and any(destination.iterdir()):
        raise StudioError("Destination must be an empty or new directory to avoid mixing image sequences")
    destination.mkdir(parents=True, exist_ok=True)
    pattern = destination / f"frame_%05d.{image_format}"
    _run(sequence_command(video, start, end, interval, pattern, backend, crop, video_size))
    images = sorted(destination.glob(f"frame_*.{image_format}"))
    if not images:
        raise StudioError("FFmpeg produced no images in the requested range")
    metadata = {"source_video": str(video), "start_seconds": start,
                "end_seconds": end, "interval_seconds": interval,
                "format": image_format, "crop": crop, "number_of_images": len(images)}
    (destination / "sequence.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return images


def clip_video(video: Path, start: float, end: float,
               destination: Path, backend: BackendSettings) -> Path:
    _check_path(video, "Video")
    if end <= start or start < 0:
        raise StudioError("Invalid clip bounds")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [backend.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{start:.6f}", "-t", f"{end-start:.6f}", "-i", str(video),
               "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
               "-movflags", "+faststart", str(destination)]
    _run(command)
    if not destination.is_file() or not destination.stat().st_size:
        raise StudioError("Clip was not produced")
    return destination


def make_contact_sheet(images: list[Path], destination: Path, columns: int = 4,
                       cell_width: int = 300, max_items: int = 48) -> Path:
    """Build a labelled overview of the first max_items exported images."""
    from PIL import Image, ImageDraw, ImageOps

    if not images:
        raise StudioError("No images available for a contact sheet")
    selected = images[:max_items]
    columns = max(1, min(columns, len(selected)))
    rows = math.ceil(len(selected) / columns)
    cell_height = int(cell_width * 0.8)
    canvas = Image.new("RGB", (columns * cell_width, rows * (cell_height + 30)), "#f4f4f4")
    drawer = ImageDraw.Draw(canvas)
    for index, path in enumerate(selected):
        with Image.open(path) as photo:
            thumb = ImageOps.contain(photo.convert("RGB"), (cell_width - 14, cell_height - 14))
        x = (index % columns) * cell_width + (cell_width - thumb.width) // 2
        y = (index // columns) * (cell_height + 30) + (cell_height - thumb.height) // 2
        canvas.paste(thumb, (x, y))
        drawer.text(((index % columns) * cell_width + 8,
                     (index // columns) * (cell_height + 30) + cell_height + 4),
                    path.name, fill="#333333")
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination)
    return destination


def archive_directory(directory: Path, archive: Path) -> Path:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=5) as zf:
        for path in sorted(directory.iterdir()):
            if path.is_file() and path != archive:
                zf.write(path, arcname=path.name)
    return archive


def find_videos(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(folder.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]


def format_seconds(seconds: float) -> str:
    minutes, secs = divmod(max(seconds, 0), 60)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"
