from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from event_surface_studio.roi import normalize_roi
from event_surface_studio.file_picker import (
    directory_entries, picker_start_directory, normalize_extension,
)

from event_surface_studio.core import (
    BackendSettings, MODE_PARAMETERS, RenderSettings, StudioError, SURFACES,
    archive_directory, clip_video, crop_filter, default_video_prefix,
    extract_frame_bytes,
    make_contact_sheet, probe_video, render_command, safe_slug, save_sequence,
    save_still, sequence_command, video_path,
)


class RenderCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.binary = self.root / "vLog2vid"
        self.binary.write_text("fake exe")
        self.log = self.root / "data.log"
        self.log.write_text("some events")
        self.backend = BackendSettings(binary=self.binary, use_micromamba=False)

    def test_all_modes_and_options(self):
        for mode in SURFACES:
            with self.subTest(mode=mode):
                config = RenderSettings(source=self.log, output=self.root / f"{mode}.mp4",
                                        surface=mode, parameters=MODE_PARAMETERS[mode])
                cmd = render_command(config, self.backend)
                self.assertEqual(cmd[0], str(self.binary))
                self.assertIn("--file", cmd)
                self.assertIn("--out", cmd)
                if mode == "ISO":
                    self.assertNotIn("--iso", cmd)
                else:
                    self.assertIn("--" + mode.lower(), cmd)
                for key in MODE_PARAMETERS[mode]:
                    self.assertIn("--" + key, cmd)

    def test_filename_and_prefix(self):
        src = Path("/example/S9_Directions/ch0dvs/data.log")
        self.assertEqual(default_video_prefix(src), "S9_Directions_ch0dvs")
        self.assertEqual(video_path(self.root, "My Scene", "ISO").name, "My_Scene_ISO.mp4")
        self.assertEqual(safe_slug("weird name / test"), "weird_name___test")

    def test_bad_parameters_rejected(self):
        config = RenderSettings(source=self.log, output=self.root / "out.mp4",
                                surface="TW", parameters={"window": -1})
        with self.assertRaises(StudioError):
            render_command(config, self.backend)
        config = RenderSettings(source=self.log, output=self.root / "out.mp4",
                                surface="ISO", width=641)
        with self.assertRaises(StudioError):
            render_command(config, self.backend)

    def test_roi_normalization(self):
        self.assertEqual(normalize_roi([20, 10, 60, 70], 160, 120), (20, 10, 60, 70))
        self.assertEqual(normalize_roi([-10, 110, 200, 30], 160, 120), (0, 110, 160, 10))
        self.assertEqual(normalize_roi([159, 119, 25, 25], 160, 120), (159, 119, 1, 1))
        with self.assertRaises(ValueError):
            normalize_roi([float("nan"), 5, 10, 10], 160, 120)
        with self.assertRaises(ValueError):
            normalize_roi([1, 2, 3], 160, 120)

    def test_crop_validation(self):
        self.assertEqual(crop_filter((10, 20, 50, 60), 160, 120), ["crop=50:60:10:20"])
        with self.assertRaises(StudioError):
            crop_filter((150, 0, 50, 50), 160, 120)


class LocalFilePickerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "recordings").mkdir()
        (self.root / "videos").mkdir()
        (self.root / "data.LOG").write_text("events")
        (self.root / "clip.MP4").write_bytes(b"mp4")
        (self.root / "notes.txt").write_text("notes")
        (self.root / ".hidden.log").write_text("hidden")

    def test_can_browse_logs_anywhere_without_upload(self):
        directories, logs = directory_entries(self.root, ".log")
        self.assertEqual({p.name for p in directories}, {"recordings", "videos"})
        self.assertEqual([p.name for p in logs], ["data.LOG"])
        self.assertEqual([p.name for p in directory_entries(self.root, ".log", show_hidden=True)[1]],
                         [".hidden.log", "data.LOG"])

    def test_can_browse_external_mp4_independently_of_output_directory(self):
        _directories, videos = directory_entries(self.root, ".mp4")
        self.assertEqual([p.name for p in videos], ["clip.MP4"])
        self.assertEqual(directory_entries(self.root, ".mp4", "CLIP")[1], videos)

    def test_picker_initial_directory(self):
        self.assertEqual(picker_start_directory(self.root / "clip.MP4"), self.root)
        self.assertEqual(picker_start_directory(self.root / "recordings"),
                         self.root / "recordings")
        self.assertEqual(picker_start_directory("/missing/path", self.root), self.root)

    def test_disallow_unexpected_file_extensions(self):
        self.assertEqual(normalize_extension(".MP4"), ".mp4")
        with self.assertRaises(ValueError):
            directory_entries(self.root, ".exe")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class VideoSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / "source.mp4"
        p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=20:duration=2",
                            "-c:v", "mpeg4", str(self.video)], capture_output=True, text=True)
        if p.returncode:
            self.fail(p.stderr)
        self.backend = BackendSettings(use_micromamba=False)

    def test_preview_frame_matches_video_size(self):
        from io import BytesIO
        raw = extract_frame_bytes(self.video, 0.5, self.backend)
        self.assertTrue(raw.startswith(b"\x89PNG"))
        if self._has_pillow():
            from PIL import Image
            with Image.open(BytesIO(raw)) as frame:
                self.assertEqual(frame.size, (160, 120))

    def test_probe_still_and_sequence(self):
        video = probe_video(self.video)
        self.assertAlmostEqual(video["duration"], 2.0, delta=0.2)
        still = save_still(self.video, 0.5, self.root / "still.png", self.backend,
                           crop=(10, 10, 80, 70), video_size=(160, 120))
        self.assertTrue(still.stat().st_size > 100)
        sequence_dir = self.root / "images"
        frames = save_sequence(self.video, .2, 1.4, .2, sequence_dir, "png", self.backend)
        self.assertGreaterEqual(len(frames), 5)
        self.assertLessEqual(len(frames), 7)
        self.assertTrue((sequence_dir / "sequence.json").exists())
        with (sequence_dir / "sequence.json").open() as handle:
            self.assertEqual(json.load(handle)["format"], "png")
        if self._has_pillow():
            contact = make_contact_sheet(frames, sequence_dir / "contact_sheet.png")
            self.assertGreater(contact.stat().st_size, 100)
        zipfile = archive_directory(sequence_dir, self.root / "frames.zip")
        self.assertGreater(zipfile.stat().st_size, 100)
        with self.assertRaises(StudioError):
            save_sequence(self.video, .2, 1.4, .2, sequence_dir, "png", self.backend)

    def _has_pillow(self):
        try:
            import PIL  # noqa: F401
            return True
        except ImportError:
            return False

    def test_clip(self):
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
        if "libx264" not in proc.stdout:
            self.skipTest("FFmpeg without libx264")
        clip = clip_video(self.video, .4, 1.3, self.root / "clip.mp4", self.backend)
        info = probe_video(clip)
        self.assertAlmostEqual(info["duration"], .9, delta=.25)

    def test_sequence_command_selection(self):
        cmd = sequence_command(self.video, .5, 1.5, .25, self.root / "frame_%03d.png",
                               self.backend, (0, 0, 120, 80), (160, 120))
        self.assertIn("fps=4.000000000,crop=120:80:0:0", cmd)
        self.assertIn("-t", cmd)


if __name__ == "__main__":
    unittest.main()
