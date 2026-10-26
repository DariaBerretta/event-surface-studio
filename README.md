# Event Surface Studio

A local browser GUI for the original [robotology/event-driven `vLog2vid`](https://github.com/robotology/event-driven/tree/main/cpp_tools/log2vid) program. Generate scientific videos from YARP event logs, navigate videos on a timeline, and export individual screenshots, sequences, contact sheets, ZIP archives, and shorter MP4 clips.

**The upstream algorithms are not reimplemented.** The app runs your existing compiled `vLog2vid` executable and uses FFmpeg for operations on the generated MP4.

## Features

| Feature | Supported |
| --- | --- |
| ISO 3D (x, y, t) | Yes |
| TW temporal window | Yes |
| SCARF | Yes |
| EROS | Yes |
| ChainSAE | Yes |
| AEDSAE | Yes |
| AAE | Yes |
| Mode-specific parameters and multiple-mode rendering | Yes |
| FPS, playback rate, output dimensions, optional timestamp file | Yes |
| Graphical local file picker for `.log` (any directory) | Yes |
| Graphical local file picker for any `.mp4`, including external videos | Yes |
| Local MP4 preview with time range selector | Yes |
| Export single PNG or JPG images at selected video times | Yes |
| Export a timed sequence of PNGs or JPGs | Yes |
| Interactive drag-to-select rectangle ROI on video frame | Yes |
| Optional spatial crop for image exports | Yes |
| Make a contact sheet and ZIP | Yes |
| Export selected interval as a short MP4 clip | Yes |
| Reproducible JSON metadata for videos and sequences | Yes |

## File-picker update (existing installation)

Use the **file-picker patch ZIP** to update an existing installation.

```bash
cd ~/Downloads/event-surface-studio
unzip -o ~/Downloads/event-surface-studio-file-picker-patch.zip
./start.sh
```

Stop the running Streamlit application with `Ctrl+C` before updating. This patch retains the ROI selector and existing surface rendering, and does not require changing the Micromamba or `vLog2vid` setup.

The **Browse .log** button in the Render tab and **Browse .mp4** button in the Video & frame studio tab open a graphical folder browser. Use Home, Downloads, Up one folder, or Filesystem `/` shortcuts, click folders to navigate, then click the file to select it. The browser recognizes `.log` and `.mp4` regardless of filename capitalization. You can choose an MP4 **outside the generated-video output folder**, including a video not created with `vLog2vid`.

These are *local filesystem selectors* rather than `st.file_uploader`: they pass file paths to the existing backend without re-uploading potentially very large recordings or MP4s into Streamlit memory. They work when browser and server are running on the same Ubuntu computer; if hosting Streamlit remotely, the explorer browses files on the server computer. The selected paths remain visible and manually editable.

## ROI selector update (existing installation)

If you already have an Event Surface Studio installation, extract the separate **ROI patch ZIP** into your existing project root. For the default Downloads location:

```bash
cd ~/Downloads/event-surface-studio
unzip -o ~/Downloads/event-surface-studio-roi-patch.zip
./start.sh
```

Keep your existing `.venv` and any rendered videos. If the app is already running, stop it with `Ctrl+C` before restarting. The update requires Streamlit >=1.60, as specified in `requirements.txt`. No new Python dependencies are required.

## Prerequisites

- Linux (tested with Python and FFmpeg command-line tools; this project is designed for local Ubuntu use).
- Python 3.10 or newer, with `python3-venv` available.
- Your existing working `vLog2vid`, e.g. `~/event-driven-vlog-build/bin/vLog2vid`.
- The environment used to run the binary, e.g. `micromamba run -n eventvideo` (enabled by default).
- `ffmpeg` and `ffprobe`. Check with `ffmpeg -version` and `ffprobe -version`.

To install FFmpeg and Python virtual environment support on Ubuntu, if missing:

```bash
sudo apt update
sudo apt install ffmpeg python3-venv
```

The interface has its **own Python virtual environment** and does not change the compiled C++ setup in Micromamba.

## Quick start

```bash
git clone https://github.com/YOUR-USERNAME/event-surface-studio.git
cd event-surface-studio
./start.sh
```

Or, after downloading and extracting a ZIP of this project:

```bash
cd event-surface-studio
./start.sh
```

The first launch automatically creates `.venv` and installs only `streamlit` and `Pillow` there. Open **http://localhost:8501** in a browser. To stop, press `Ctrl+C` in the terminal.

### Your existing vLog2vid installation

The app defaults to:

- Executable: `~/event-driven-vlog-build/bin/vLog2vid`
- Micromamba: enabled
- Environment name: `eventvideo`
- Output directory: `~/Downloads/event-surface-studio`
- FFmpeg and FFprobe: system `PATH`

These are editable in the GUI sidebar. Test the original renderer separately with:

```bash
micromamba run -n eventvideo ~/event-driven-vlog-build/bin/vLog2vid --help
```

### Example workflow

1. In **Render surfaces**, click **Browse .log**, navigate to any directory, and select the desired event log. You can still type a path manually.
2. Select one or more surface modes (e.g. ISO, TW, EROS).
3. Adjust mode-specific settings in the expanders. Set output resolution to match your sensor (e.g. 640 x 480).
4. Click **Render selected videos**. MP4 files and matching JSON manifests are saved under `~/Downloads/event-surface-studio/`.
5. In **Video & frame studio**, click **Browse .mp4** to open any local MP4, regardless of where it is stored or which program created it. Alternatively select a rendered video from the **Generated video library**; click **Use library** to switch back. Use the time-range slider.
6. For a crop, enable **Crop output images to a region of interest**. Choose a preview frame, then **click and drag directly over the image** to draw a rectangle. The selection automatically maps to the original video pixel coordinates, even if the browser preview is smaller. Drag again to replace it, or select **Reset ROI** for the complete frame.
7. Preview or save a still image, export images every 0.2 seconds, or create a short MP4 clip. The rectangle crop is applied to screenshots and sequences (not MP4 clips).
8. In **Exports**, browse images/contact sheets and download ZIP archives.

### Surface parameters

| Mode | Parameters in GUI | CLI behavior |
| --- | --- | --- |
| ISO | `window`, `frontblur` | Default mode (no flag) |
| TW | `window` | `--tw` |
| SCARF | `block_size`, `alpha`, `C` | `--scarf` |
| EROS | `block_size`, `alpha` | `--eros` |
| ChainSAE | none | `--chainsae` |
| AEDSAE | `window`, `lambda` | `--aedsae` |
| AAE | `block_size` | `--aae` |

These are taken from the actual [`log2vid.cpp`](https://github.com/robotology/event-driven/blob/main/cpp_tools/log2vid/log2vid.cpp). The `--help` text and implementation differ slightly for ISO's default window; this GUI always passes the chosen window explicitly (initially 0.5 seconds).

## Data and output

No event logs are uploaded to an external server. The Streamlit app runs on `127.0.0.1`. Large logs are passed as filesystem paths to `vLog2vid` and are never loaded into the Python web server.

Output example:

```text
~/Downloads/event-surface-studio/
    recording_ISO.mp4
    recording_ISO.json
    recording_EROS.mp4
    recording_EROS.json
    screenshots/
        recording_ISO_t1.200.png
    sequences/
        recording_ISO_1_00s_3_00s_0_2s/
            frame_00000.png
            frame_00001.png
            ...
            contact_sheet.png
            sequence.json
        recording_ISO_1_00s_3_00s_0_2s.zip
    clips/
        recording_ISO_1.00_3.00_clip.mp4
```

Sequences are exported from the decoded MP4 at an approximately regular interval; selecting more samples than the source video FPS will duplicate neighboring frames. Frame timing is quantized by the source FPS. For exact original-event timestamps, a native-renderer extension is required.

**Image quality:** PNG images are lossless *once decoded*, but the video already underwent H.264 compression through `vLog2vid`. Therefore, these are **not lossless raw-event renders**. A future option can write PNG directly inside the `vLog2vid` C++ rendering loop prior to video encoding.

**Time:** The GUI's timeline uses MP4 playback seconds. With `--rate` other than 1, those differ from elapsed time in the original recording.

## Architecture

```text
YARP data.log
    |       [vLog2vid binary, upstream C++ / YARP / OpenCV]
    +-----> MP4 surface visualization + JSON manifest
                |
                +--> Browser video player + temporal range
                +--> FFmpeg screenshot PNG / JPG
                +--> FFmpeg image sequence + contact sheet + ZIP
                +--> FFmpeg cropped images
                +--> FFmpeg trimmed MP4
```

- `app.py`: Streamlit GUI.
- `event_surface_studio/core.py`: backend, validation, commands and export functions.
- `event_surface_studio/roi.py` and `roi_assets/`: browser-native drag-to-select ROI widget (Streamlit Components v2, no third-party cropper packages).
- `tests/`: automated tests, including real FFmpeg smoke tests.
- `.streamlit/config.toml`: local interface theme and localhost server settings.
- `start.sh`: single-command local launcher.

### Tests

```bash
python3 -m unittest discover -s tests -v
```

Tests requiring FFmpeg are skipped automatically if it is unavailable. Full tests also require `Pillow` for contact sheets.

## Limitations and safety

- Batch rendering processes each complete log once per selected mode. Large recordings and multi-mode runs can take time and consume disk space. There is no source-log time interval flag in the upstream CLI.
- The video player can be slower for very large MP4s; select and export a shorter clip for easier scrubbing.
- Video creation relies on an OpenCV/FFmpeg H.264 encoder (`avc1`) working in the runtime where `vLog2vid` executes. The program may return successfully without a playable video when the codec is unavailable; the GUI checks for an output file.
- Image exports use FFmpeg. Clip export requires an FFmpeg build with `libx264`.
- The GUI has access to your local filesystem as your user. It is configured to run on localhost only; do not expose its port to a network.
- The `.gitignore` excludes videos, images, recordings and the `.venv` folder so datasets do not get accidentally committed.

## Acknowledgements and licensing

This GUI is an independent wrapper around [robotology/event-driven](https://github.com/robotology/event-driven). The C++ library, its source, and its executable are *not distributed* in this repository. Upstream project licenses apply to the original renderer; the GUI itself is MIT-licensed. See [LICENSE](LICENSE).
