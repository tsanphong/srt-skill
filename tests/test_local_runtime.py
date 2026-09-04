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
                    instance.render_to(out, 1000)
                    with av.open(str(out)) as video:
                        frames = list(video.decode(video=0))
                    self.assertEqual(len(frames), 30)

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
