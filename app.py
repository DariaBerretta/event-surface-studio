"""Local browser interface for the upstream event-driven vLog2vid executable."""

from __future__ import annotations

import base64
import hashlib
import io
import math
import os
import shutil
import time
from pathlib import Path

import streamlit as st
from PIL import Image

from event_surface_studio.roi import normalize_roi, register_roi_selector
from event_surface_studio.file_picker import draw_picker, picker_start_directory

from event_surface_studio.core import (
    BackendSettings,
    MODE_DESCRIPTIONS,
    MODE_PARAMETERS,
    RenderSettings,
    StudioError,
    SURFACES,
    archive_directory,
    clip_video,
    default_video_prefix,
    extract_frame_bytes,
    find_videos,
    format_seconds,
    make_contact_sheet,
    probe_video,
    render_video,
    safe_slug,
    save_sequence,
    save_still,
    validate_interval,
    video_path,
)

st.set_page_config(
    page_title="Event Surface Studio",
    page_icon="\U0001f39e",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .block-container {max-width: 1280px; padding-top: 2.0rem; padding-bottom: 4rem;}
    h1,h2,h3 {letter-spacing: -0.035em;}
    [data-testid="stMetric"] {background: rgba(122,135,157,.08); border: 1px solid rgba(122,135,157,.2); padding: 16px; border-radius: 10px;}
    .ess-kicker {letter-spacing:.18em; font-weight:750; font-size:.75rem; color:#7da5ff; margin-bottom:.5rem;}
    .ess-desc {color:#a3b0c1; font-size:1.0rem; line-height:1.6; margin-bottom:1.4rem;}
    .ess-card {background:rgba(106,124,157,.08); border:1px solid rgba(113,132,168,.2); border-radius:12px; padding:16px;}
    [data-testid="stSidebar"] {border-right:1px solid rgba(140,150,165,.15);}
    div[data-testid="stTabs"] button {font-weight:650;}
</style>
""",
    unsafe_allow_html=True,
)

HOME = Path.home()
DEFAULT_OUTPUT = HOME / "Downloads" / "event-surface-studio"
DEFAULT_BINARY = HOME / "event-driven-vlog-build" / "bin" / "vLog2vid"
ROI_PICKER = register_roi_selector()


@st.cache_data(show_spinner=False)
def cached_probe(path: str, file_size: int, file_mtime: int, ffprobe: str) -> dict:
    del file_size, file_mtime
    return probe_video(Path(path), ffprobe)


@st.cache_data(max_entries=12, show_spinner=False)
def cached_roi_preview(path: str, file_size: int, file_mtime: int,
                       at: float, ffmpeg: str) -> str:
    """Extract a display-sized JPEG. Selection coordinates use video pixels."""
    del file_size, file_mtime
    raw = extract_frame_bytes(Path(path), at, BackendSettings(ffmpeg=ffmpeg))
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        image.thumbnail((1000, 800), Image.Resampling.LANCZOS)
        stream = io.BytesIO()
        image.save(stream, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def video_info(path: Path, backend: BackendSettings) -> dict:
    stat = path.stat()
    return cached_probe(str(path), stat.st_size, stat.st_mtime_ns, backend.ffprobe)


def fail(error: Exception) -> None:
    st.error(str(error))


def unique_dir(parent: Path, name: str) -> Path:
    stem = safe_slug(name)
    candidate = parent / stem
    index = 2
    while candidate.exists():
        candidate = parent / f"{stem}_{index}"
        index += 1
    return candidate


@st.dialog("Choose a YARP event log (.log)", width="large")
def choose_log_dialog() -> None:
    draw_picker(".log", "log", "pending_source_path")


@st.dialog("Choose a video (.mp4)", width="large")
def choose_video_dialog() -> None:
    draw_picker(".mp4", "mp4", "pending_external_video")


def open_file_picker(context: str, preferred_path: str) -> None:
    """Open the browser-based file chooser at the most useful directory."""
    directory = picker_start_directory(preferred_path)
    st.session_state[f"picker_dir_{context}"] = str(directory)
    st.session_state[f"picker_page_{context}"] = 0
    st.session_state[f"picker_filter_{context}"] = ""
    if context == "log":
        choose_log_dialog()
    else:
        choose_video_dialog()


def surface_parameters(mode: str) -> dict[str, float | int]:
    parameters: dict[str, float | int] = {}
    defaults = MODE_PARAMETERS[mode]
    if not defaults:
        st.caption("This surface has no additional command-line parameters.")
        return parameters
    cols = st.columns(min(3, len(defaults)))
    for i, (name, default) in enumerate(defaults.items()):
        with cols[i % len(cols)]:
            label = {
                "window": "Time window (s)",
                "frontblur": "Front buildup (s)",
                "block_size": "Block size",
                "alpha": "Alpha",
                "C": "Intensity (C)",
                "lambda": "Lambda",
            }.get(name, name)
            if name == "block_size":
                parameters[name] = st.number_input(label, min_value=1, max_value=99,
                                                   value=int(default), step=1, key=f"{mode}_{name}")
            else:
                parameters[name] = st.number_input(label, min_value=0.0001 if name == "window" else 0.0,
                                                   max_value=1000.0, value=float(default),
                                                   step=0.01 if name in ("window", "frontblur") else 0.1,
                                                   format="%.4f", key=f"{mode}_{name}")
    return parameters


with st.sidebar:
    st.markdown('<div class="ess-kicker">LOCAL RESEARCH TOOL</div>', unsafe_allow_html=True)
    st.title("Event Surface Studio")
    st.caption("YARP event logs to scientific videos and image sequences")
    st.divider()
    st.subheader("Paths & runtime")
    st.text_input("Output directory", value=str(DEFAULT_OUTPUT), key="output_dir")
    st.text_input("vLog2vid executable", value=str(DEFAULT_BINARY), key="binary_path")
    st.toggle("Run inside Micromamba", value=True, key="use_micromamba")
    if st.session_state.use_micromamba:
        st.text_input("Environment name", value="eventvideo", key="env_name")
    st.text_input("FFmpeg command or path", value="ffmpeg", key="ffmpeg_path")
    st.text_input("FFprobe command or path", value="ffprobe", key="ffprobe_path")
    st.divider()
    st.markdown("**Backend status**")
    bin_found = Path(st.session_state.binary_path).expanduser().is_file()
    mm_found = bool(shutil.which("micromamba"))
    ffmpeg_found = bool(shutil.which(st.session_state.ffmpeg_path)) or Path(st.session_state.ffmpeg_path).is_file()
    ffprobe_found = bool(shutil.which(st.session_state.ffprobe_path)) or Path(st.session_state.ffprobe_path).is_file()
    st.caption(("Available" if bin_found else "Missing") + "  -  vLog2vid")
    if st.session_state.use_micromamba:
        st.caption(("Available" if mm_found else "Missing") + "  -  Micromamba")
    st.caption(("Available" if ffmpeg_found and ffprobe_found else "Missing") + "  -  FFmpeg / FFprobe")
    if not ffmpeg_found or not ffprobe_found:
        st.info("Install FFmpeg: `sudo apt install ffmpeg`")
    st.divider()
    st.caption("Runs on your computer. No dataset uploads or cloud processing.")

backend = BackendSettings(
    binary=Path(st.session_state.binary_path).expanduser(),
    use_micromamba=st.session_state.use_micromamba,
    env_name=st.session_state.get("env_name", "eventvideo"),
    ffmpeg=st.session_state.ffmpeg_path,
    ffprobe=st.session_state.ffprobe_path,
)
output_dir = Path(st.session_state.output_dir).expanduser()

st.markdown('<div class="ess-kicker">EVENT-BASED VISION / VISUALIZATION WORKFLOW</div>', unsafe_allow_html=True)
st.title("Render surfaces. Capture moments.")
st.markdown(
    '<div class="ess-desc">Use the original <b>vLog2vid</b> renderer for every supported event surface. '
    'Preview videos, select intervals, and export publication-ready image sequences from the rendered video.</div>',
    unsafe_allow_html=True,
)

tab_render, tab_editor, tab_gallery, tab_about = st.tabs(
    ["01  Render surfaces", "02  Video & frame studio", "03  Exports", "04  Guide"]
)

with tab_render:
    st.subheader("Source & render settings")
    if "source_path" not in st.session_state:
        st.session_state.source_path = ""
    if "pending_source_path" in st.session_state:
        st.session_state.source_path = st.session_state.pop("pending_source_path")
    st.markdown("**Event log**")
    choose_source_col, source_text_col = st.columns([1, 4], vertical_alignment="bottom")
    with choose_source_col:
        if st.button("Browse .log", icon="📂", use_container_width=True):
            open_file_picker("log", st.session_state.source_path)
    with source_text_col:
        st.text_input("Selected YARP event log", key="source_path",
                      placeholder="Choose a .log from any folder (or enter a path)",
                      label_visibility="collapsed")
    source = Path(st.session_state.source_path).expanduser() if st.session_state.source_path else None
    if source and source.is_file():
        st.caption(f"Source found | {source.stat().st_size / (1024**2):,.1f} MiB | {source}")
    elif source:
        st.warning("The specified log file does not exist or cannot be accessed.")

    col_settings, col_modes = st.columns([1, 1.3], gap="large")
    with col_settings:
        st.markdown("**Video properties**")
        c1, c2 = st.columns(2)
        with c1:
            width = st.number_input("Width (px)", min_value=16, max_value=8192,
                                    value=640, step=2)
            fps = st.number_input("Output FPS", min_value=1, max_value=240, value=30)
        with c2:
            height = st.number_input("Height (px)", min_value=16, max_value=8192,
                                     value=480, step=2)
            rate = st.number_input("Playback rate", min_value=0.01, max_value=100.0,
                                   value=1.0, step=0.25)
        st.text_input("Custom filename prefix (optional)", key="prefix_input",
                      placeholder=default_video_prefix(source) if source else "recording")
        timestamps_input = st.text_input("Custom frame timestamps file (optional)",
                                         value="", placeholder="/path/to/timestamps.txt",
                                         help="vLog2vid --timestamps: timestamps used to schedule output frames.")
        st.caption("Dimensions describe the output video; match your source sensor for undistorted surfaces.")
        overwrite = st.checkbox("Overwrite existing videos with the same name", value=False)
    with col_modes:
        st.markdown("**Surface representations**")
        modes = st.multiselect("Render one or more modes", SURFACES, default=["ISO"])
        if not modes:
            st.info("Select at least one surface representation.")
        all_parameters: dict[str, dict] = {}
        for mode in modes:
            with st.expander(f"{mode}  -  {MODE_DESCRIPTIONS[mode]}", expanded=len(modes) == 1):
                all_parameters[mode] = surface_parameters(mode)

    render_clicked = st.button("Render selected videos", type="primary", disabled=not modes or not source or not source.is_file(),
                               width="stretch")
    if render_clicked:
        try:
            if not bin_found:
                raise StudioError("vLog2vid executable not found. Fix the path in the sidebar.")
            if width % 2 or height % 2:
                raise StudioError("Use even video dimensions for H.264 output")
            prefix = st.session_state.prefix_input.strip() or default_video_prefix(source)
            status = st.status("Rendering videos with vLog2vid", expanded=True)
            progress_bar = st.progress(0)
            progress_line = st.empty()
            results = []
            with status:
                for index, mode in enumerate(modes):
                    target = video_path(output_dir, prefix, mode)
                    config = RenderSettings(
                        source=source, output=target, surface=mode, fps=int(fps),
                        rate=float(rate), width=int(width), height=int(height),
                        parameters=all_parameters[mode],
                        timestamps=Path(timestamps_input).expanduser() if timestamps_input else None,
                    )
                    st.write(f"{index+1}/{len(modes)}  -  {mode}  ->  `{target.name}`")
                    last_report = [0.0]

                    def show_progress(message: str) -> None:
                        if time.monotonic() - last_report[0] > 0.6:
                            progress_line.caption(message[-160:])
                            last_report[0] = time.monotonic()

                    result = render_video(config, backend, overwrite=overwrite, progress=show_progress)
                    results.append(result)
                    st.session_state.last_video = str(result)
                    progress_bar.progress((index + 1) / len(modes))
                status.update(label=f"Completed: {len(results)} videos", state="complete", expanded=False)
            st.success("Videos saved to: " + str(output_dir))
            for result in results:
                st.code(str(result))
        except (StudioError, OSError, ValueError) as error:
            fail(error)

with tab_editor:
    st.subheader("Inspect, trim & extract")
    if "external_video" not in st.session_state:
        st.session_state.external_video = ""
    if "pending_external_video" in st.session_state:
        st.session_state.external_video = st.session_state.pop("pending_external_video")

    # The library is a convenience, never a restriction on which MP4 can be used.
    videos = find_videos(output_dir)
    last = st.session_state.get("last_video")
    options = [str(p) for p in videos]
    if last and Path(last).is_file() and last not in options:
        options.insert(0, last)

    st.markdown("**Choose a video from anywhere on your computer**")
    choose_video_col, chosen_path_col = st.columns([1, 4], vertical_alignment="bottom")
    with choose_video_col:
        if st.button("Browse .mp4", icon="📂", use_container_width=True):
            open_file_picker("mp4", st.session_state.external_video or last or "")
    with chosen_path_col:
        st.text_input("Selected external MP4", key="external_video",
                      placeholder="Choose an MP4 from any folder (or enter a path)",
                      label_visibility="collapsed")

    if options:
        def use_library_selection() -> None:
            st.session_state.external_video = ""

        library_col, reset_col = st.columns([4, 1], vertical_alignment="bottom")
        with library_col:
            index = options.index(last) if last in options else 0
            picked = st.selectbox("Generated video library (optional)", options, index=index,
                                  key="library_video", on_change=use_library_selection)
        with reset_col:
            if st.button("Use library", use_container_width=True):
                st.session_state.pending_external_video = ""
                st.rerun()
    else:
        picked = ""
        st.caption("No generated MP4 files in the output directory yet. You can still open any existing MP4 above.")

    selected = (Path(st.session_state.external_video).expanduser()
                if st.session_state.external_video.strip() else Path(picked))
    if st.session_state.external_video.strip() and selected.is_file():
        st.caption(f"Opened external video: {selected}")
    if selected.is_file():
        try:
            info = video_info(selected, backend)
            duration = float(info["duration"])
            x1, x2, x3, x4 = st.columns(4)
            x1.metric("Duration", format_seconds(duration))
            x2.metric("Resolution", f"{info['width']} x {info['height']}")
            x3.metric("Frame rate", f"{info['fps']:.2f} fps")
            x4.metric("File size", f"{selected.stat().st_size / 1024**2:.1f} MiB")

            if duration <= 0.1:
                st.warning("This video is too short for timeline extraction.")
            else:
                st.markdown("**Select a section of the video timeline**")
                end_default = min(duration, 5.0)
                start, end = st.slider("Video time (seconds)", min_value=0.0,
                                       max_value=float(duration), value=(0.0, end_default),
                                       step=0.1 if duration >= 0.2 else 0.01,
                                       format="%.2f", key=f"range_{str(selected)}")
                st.caption(f"Selected: {format_seconds(start)} to {format_seconds(end)}  |  "
                           "These are video playback times, not original event timestamps if rate != 1.")
                # String offsets preserve sub-second precision in Streamlit.
                st.video(str(selected), start_time=f"{start:.3f}s", end_time=f"{end:.3f}s")
                if end <= start:
                    st.warning("Choose a non-zero interval.")
                else:
                    validate_interval(start, end, duration)
                    st.divider()
                    crop_enabled = st.checkbox("Crop output images to a region of interest", value=False,
                                               help="Draw the crop directly on a video frame. It is used for screenshots and image sequences.")
                    crop = None
                    if crop_enabled:
                        width_px, height_px = int(info["width"]), int(info["height"])
                        video_id = hashlib.sha256(str(selected.resolve()).encode("utf-8")).hexdigest()[:16]
                        selection_key = f"roi_selected_{video_id}_{width_px}x{height_px}"
                        version_key = f"roi_revision_{video_id}"
                        st.session_state.setdefault(selection_key, (0, 0, width_px, height_px))
                        st.session_state.setdefault(version_key, 0)

                        preview_time = st.number_input(
                            "Frame used to draw the ROI (s)", min_value=0.0,
                            max_value=float(max(0.0, duration - 0.001)),
                            value=float(min(start, max(0.0, duration - 0.001))),
                            step=0.1, format="%.3f", key=f"roi_time_{video_id}",
                            help="Change the frame to find a good crop. The ROI stays fixed across all exported frames.")
                        try:
                            stats = selected.stat()
                            image_uri = cached_roi_preview(
                                str(selected), stats.st_size, stats.st_mtime_ns,
                                preview_time, backend.ffmpeg)
                            selection = st.session_state[selection_key]
                            picked_roi = ROI_PICKER(
                                data={"image": image_uri, "width": width_px,
                                      "height": height_px, "selection": list(selection)},
                                default={"selection": list(selection)},
                                key=f"roi_picker_{video_id}_{st.session_state[version_key]}",
                                on_selection_change=lambda: None,
                            )
                            if picked_roi.selection is not None:
                                selection = normalize_roi(picked_roi.selection, width_px, height_px)
                                st.session_state[selection_key] = selection
                            crop = selection
                            x, y, cw, ch = crop
                            crop_col, reset_col = st.columns([3, 1], vertical_alignment="center")
                            with crop_col:
                                st.caption(f"Selected ROI: x={x}, y={y}, width={cw}, height={ch} pixels "
                                           f"(source: {width_px} x {height_px}).")
                            with reset_col:
                                if st.button("Reset ROI", key=f"roi_reset_{video_id}", width="stretch"):
                                    st.session_state[selection_key] = (0, 0, width_px, height_px)
                                    st.session_state[version_key] += 1
                                    st.rerun()
                        except (StudioError, ValueError, OSError) as error:
                            fail(error)
                            st.warning("ROI preview is unavailable. Disable cropping or check FFmpeg.")
                            st.stop()
                    dimensions = (info["width"], info["height"])
                    still_col, sequence_col = st.columns(2, gap="large")
                    with still_col:
                        st.markdown("**Single screenshot**")
                        at = st.number_input("Capture at (s)", min_value=0.0,
                                             max_value=max(0.0, duration - 0.001),
                                             value=float(min(start, max(0.0, duration - 0.001))),
                                             step=0.1, format="%.3f")
                        still_format = st.selectbox("Image format", ["png", "jpg"], key="still_format")
                        if st.button("Preview screenshot", width="stretch"):
                            try:
                                preview_path = output_dir / ".preview" / "current_frame.png"
                                save_still(selected, at, preview_path, backend, crop, dimensions)
                                st.session_state.preview_image_bytes = preview_path.read_bytes()
                            except (StudioError, OSError) as error:
                                fail(error)
                        if "preview_image_bytes" in st.session_state:
                            st.image(st.session_state.preview_image_bytes, caption="Preview (not saved to exports)", width="stretch")
                        if st.button("Save screenshot", type="primary", width="stretch"):
                            try:
                                dest_dir = output_dir / "screenshots"
                                target = dest_dir / f"{safe_slug(selected.stem)}_t{at:.3f}.{still_format}"
                                save_still(selected, at, target, backend, crop, dimensions)
                                st.session_state.last_still = str(target)
                                st.success(f"Saved: {target}")
                            except (StudioError, OSError) as error:
                                fail(error)
                        last_still = Path(st.session_state.get("last_still", ""))
                        if last_still.is_file():
                            with last_still.open("rb") as handle:
                                st.download_button("Download saved screenshot", data=handle,
                                                   file_name=last_still.name,
                                                   mime="image/png" if last_still.suffix == ".png" else "image/jpeg")
                    with sequence_col:
                        st.markdown("**Screenshot sequence**")
                        interval = st.number_input("Time between frames (s)", min_value=0.01,
                                                   max_value=60.0, value=0.2, step=0.05,
                                                   format="%.3f", key="sequence_interval")
                        image_format = st.selectbox("Sequence image format", ["png", "jpg"], key="sequence_format")
                        estimate = math.ceil((end - start) / interval)
                        st.caption(f"About {estimate} images at 1 image every {interval:g} seconds")
                        if st.button("Export image sequence", type="primary", width="stretch"):
                            try:
                                destination = unique_dir(output_dir / "sequences",
                                    f"{selected.stem}_{start:.2f}s_{end:.2f}s_{interval:g}s")
                                images = save_sequence(selected, start, end, interval, destination,
                                                       image_format, backend, crop, dimensions)
                                contact = make_contact_sheet(images, destination / "contact_sheet.png")
                                archive = archive_directory(destination, destination.with_suffix(".zip"))
                                st.session_state.last_sequence_dir = str(destination)
                                st.session_state.last_archive = str(archive)
                                st.success(f"Exported {len(images)} images to {destination}")
                                st.image(str(contact), caption="Contact sheet (first 48 images)", width="stretch")
                            except (StudioError, OSError) as error:
                                fail(error)
                        if st.session_state.get("last_archive"):
                            archive_path = Path(st.session_state.last_archive)
                            if archive_path.exists():
                                if archive_path.stat().st_size < 150 * 1024**2:
                                    with archive_path.open("rb") as stream:
                                        st.download_button("Download latest sequence (ZIP)", stream,
                                                           file_name=archive_path.name, mime="application/zip")
                                else:
                                    st.caption("Sequence ZIP was saved locally; it is too large for an in-browser download.")

                    st.divider()
                    st.markdown("**Export selected interval as an MP4 clip**")
                    if st.button("Save video clip"):
                        try:
                            clips_dir = output_dir / "clips"
                            clips_dir.mkdir(parents=True, exist_ok=True)
                            filename = f"{safe_slug(selected.stem)}_{start:.2f}_{end:.2f}_clip.mp4"
                            output_clip = clips_dir / filename
                            suffix = 2
                            while output_clip.exists():
                                output_clip = clips_dir / f"{Path(filename).stem}_{suffix}.mp4"
                                suffix += 1
                            clip_video(selected, start, end, output_clip, backend)
                            st.success("Saved: " + str(output_clip))
                        except (StudioError, OSError) as error:
                            fail(error)
        except (StudioError, OSError, ValueError) as error:
            fail(error)
    else:
        st.caption("Click Browse .mp4 to open a video from any folder, or choose one from your generated video library.")

with tab_gallery:
    st.subheader("Your exports")
    videos = find_videos(output_dir)
    left, right = st.columns(2)
    with left:
        st.markdown("**Generated videos and clips**")
        if videos:
            for path in videos[:20]:
                st.write(f"`{path.name}`  |  {path.stat().st_size/1024**2:.1f} MiB")
        else:
            st.caption("No MP4 exports yet.")
    with right:
        st.markdown("**Image sequences**")
        sequence_root = output_dir / "sequences"
        sequence_dirs = sorted([p for p in sequence_root.iterdir() if p.is_dir()],
                               key=lambda p: p.stat().st_mtime, reverse=True) if sequence_root.is_dir() else []
        if sequence_dirs:
            chosen = st.selectbox("Sequence directory", [str(p) for p in sequence_dirs])
            chosen_path = Path(chosen)
            contact = chosen_path / "contact_sheet.png"
            if contact.is_file():
                st.image(str(contact), caption="Contact sheet", width="stretch")
            images = sorted([*chosen_path.glob("frame_*.png"), *chosen_path.glob("frame_*.jpg")])
            st.caption(f"{len(images)} images at {chosen_path}")
            if images:
                cols = st.columns(3)
                for i, frame in enumerate(images[:12]):
                    with cols[i % 3]:
                        st.image(str(frame), caption=frame.name, width="stretch")
            archive = chosen_path.with_suffix(".zip")
            if archive.is_file() and archive.stat().st_size < 150 * 1024**2:
                with archive.open("rb") as handle:
                    st.download_button("Download ZIP", handle, file_name=archive.name, mime="application/zip")
        else:
            st.caption("No image sequences yet.")

with tab_about:
    st.subheader("How it works")
    st.markdown(
        """
This is a **local** Streamlit interface. It does not attempt to reproduce or replace the original rendering algorithms.

1. **Render** invokes `vLog2vid` from the [robotology/event-driven](https://github.com/robotology/event-driven) project to create MP4 videos.
2. **Inspect** uses FFprobe for video information and the browser's video player for timeline navigation.
3. **Export** uses FFmpeg to generate screenshots, regular image sequences, contact sheets, ZIP archives, and short video clips.

Supported surface types: **ISO**, **TW**, **SCARF**, **EROS**, **ChainSAE**, **AEDSAE**, **AAE**.

**Important for scientific figures:** PNG export is lossless *relative to the decoded MP4 frame*, but the source MP4 has already passed through H.264 compression. It is not a lossless export directly from raw events. For native, pre-encoding PNG export, `vLog2vid` would need an additional upstream-compatible output path.

**Timing:** A video rendered using `--rate != 1` changes playback speed. The frame selection interface always works in **video playback seconds**, not the original recording timestamp domain. ISO windows, including the front blur, still use the renderer's original event-time semantics.

**Security:** Run this only on localhost. The file browser and command executor have access to local files as your current user. File paths are passed to subprocesses as arguments, not through a shell.
"""
    )
    with st.expander("Troubleshooting"):
        st.code("micromamba run -n eventvideo ~/event-driven-vlog-build/bin/vLog2vid --help")
        st.code("ffmpeg -version\nffprobe -version")
        st.caption("If a render completes with no MP4, check that the OpenCV avc1/H.264 encoder is available in the runtime.")
