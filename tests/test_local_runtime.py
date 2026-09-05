"""Regression checks for empty masks and consecutive PyAV scene timestamps."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

import av
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import merge_scenes
import render_stream_whiteboard as renderer


class LocalRuntimeTests(unittest.TestCase):
    def test_renderer_preserves_original_colors_and_closes_final_wipe(self):
        with tempfile.TemporaryDirectory() as td:
            height, width = 96, 64
            image = np.empty((height, width, 3), dtype=np.uint8)
            image[:] = (40, 55, 70)
            image[12:84, 8:56] = (75, 125, 185)
            image[28:68, 20:44] = (12, 18, 24)
            image[40:56, 28:36] = (225, 235, 245)
            region = {"x": 0, "y": 0, "width": width, "height": height}
            ann = {"canvas": {"width": width, "height": height}, "elements": [{
                "region": region,
                "reveal": {"startMs": 0, "durationMs": 600, "protectedRegions": []},
            }]}
            cfg = renderer.sr.Config(
                cap_long_edge=height, fps=10, ink_path_mode="grid",
                color_fill="contour-wipe",
            )
            self.assertFalse(cfg.match_bg)
            instance = renderer.RegionStreamRenderer(image, ann, cfg, None, True)
            expected = renderer.cv2.resize(
                image, (instance.out_w, instance.out_h), interpolation=renderer.cv2.INTER_AREA,
            )
            np.testing.assert_array_equal(instance.color_img, expected)

            out = Path(td) / "preserve.mp4"
            instance.render_to(out, 1000)
            with av.open(str(out)) as video:
                frames = list(video.decode(video=0))
            final_bgr = frames[-1].to_ndarray(format="bgr24")
            mae = np.abs(final_bgr.astype(np.int16) - expected.astype(np.int16)).mean()
            self.assertLess(mae, 8.0)

    def test_empty_and_fully_protected_regions_keep_timing(self):
        for mode in ("grid", "skeleton"):
            for protected in (False, True):
                with self.subTest(mode=mode, protected=protected), tempfile.TemporaryDirectory() as td:
                    region = dict(x=0, y=0, width=40, height=40)
                    ann = {"canvas": {"width": 40, "height": 40}, "elements": [{
                        "region": region,
                        "reveal": {"startMs": 100, "durationMs": 300,
                                   "protectedRegions": [region] if protected else []},
                    }]}
                    cfg = renderer.sr.Config(cap_long_edge=40, fps=30, ink_path_mode=mode)
                    instance = renderer.RegionStreamRenderer(
                        np.full((40, 40, 3), 240, dtype=np.uint8), ann, cfg, None, True)
                    out = Path(td) / "blank.mp4"
                    progress = []
                    instance.render_to(out, 1000, progress.append)
                    with av.open(str(out)) as video:
                        frames = list(video.decode(video=0))
                    self.assertEqual(len(frames), 30)
                    self.assertTrue(progress)
                    self.assertEqual(progress, sorted(progress))
                    self.assertGreaterEqual(progress[-1], 85)

    def test_pyav_concat_has_continuous_timestamps_and_both_scenes(self):
        with tempfile.TemporaryDirectory() as td:
            clips = []
            for index, color in enumerate(((220, 20, 20), (20, 220, 20))):
                path = Path(td) / f"scene-{index}.mp4"
                clips.append(path)
                with av.open(str(path), "w") as video:
                    stream = video.add_stream("h264", rate=10)
                    stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
                    pixels = np.full((48, 64, 3), color, dtype=np.uint8)
                    for _ in range(10):
                        for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                            video.mux(packet)
                    for packet in stream.encode(None):
                        video.mux(packet)
            out = Path(td) / "joined.mp4"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(merge_scenes._pyav_concat(clips, out))
            with av.open(str(out)) as video:
                frames = list(video.decode(video=0))
            self.assertEqual(len(frames), 20)
            times = [float(f.pts * f.time_base) for f in frames]
            self.assertTrue(all(b > a for a, b in zip(times, times[1:])))
            self.assertAlmostEqual(times[-1], 1.9, places=2)
            for index, channel in ((0, 0), (10, 1)):
                self.assertEqual(int(frames[index].to_ndarray(format="rgb24").mean(axis=(0, 1)).argmax()), channel)


if __name__ == "__main__":
    unittest.main()
