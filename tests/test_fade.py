"""The fade: 0.5 s in from black and silence at the start, 1.5 s out at the end, on by default."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from coverlyric import media, render
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


def frame_at(path: Path, t: float) -> np.ndarray:
    raw = subprocess.run(
        [
            media.ffmpeg(),
            "-v",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=192:108",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8)


def loudness(path: Path, t: float, length: float = 0.1) -> float:
    raw = subprocess.run(
        [
            media.ffmpeg(),
            "-v",
            "error",
            "-ss",
            f"{t:.3f}",
            "-t",
            f"{length}",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    samples = np.frombuffer(raw, np.int16).astype(np.float64)
    return float(np.sqrt((samples**2).mean())) if samples.size else 0.0


def make(tmp_path: Path, span, style: render.Style) -> Path:
    demo = Project.load(DEMO)
    out = tmp_path / "fade.mp4"
    render.render(out, demo.preview_lines(), demo.song(), style, 2, span, lambda *_: None)
    return out


def test_the_filters_follow_the_part_of_the_song():
    on, off = render.Style(), render.Style(fade=False)
    assert on.fade
    assert render.fades(off, 18.0, 0.0, 18.0) == ([], [])
    assert render.fades(on, 18.0, 5.0, 10.0) == ([], [])
    vf, af = render.fades(on, 18.0, 0.0, 18.0)
    assert vf == ["fade=t=in:st=0:d=0.5", "fade=t=out:st=16.500:d=1.5"]
    assert af == ["afade=t=in:st=0:d=0.5", "afade=t=out:st=16.500:d=1.5"]
    # A clip that holds the end fades out within the clip's own time.
    assert render.fades(on, 18.0, 13.0, 18.0)[0] == ["fade=t=out:st=3.500:d=1.5"]


def close(a: np.ndarray, b: np.ndarray) -> bool:
    """Equal but for the encoder: the two videos are compressed separately."""
    return np.abs(a.astype(int) - b.astype(int)).mean() < 2


def pair(tmp_path: Path, span) -> tuple[Path, Path]:
    """The same part with and without the fade: the demo tone itself is loudest at its start."""
    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    return make(tmp_path / "on", span, render.Style()), make(
        tmp_path / "off", span, render.Style(fade=False)
    )


def test_the_start_rises_from_black_and_silence(tmp_path):
    on, off = pair(tmp_path, (0.0, 3.0))
    assert frame_at(on, 0.0).mean() < 3 < 20 < frame_at(off, 0.0).mean()
    assert close(frame_at(on, 1.0), frame_at(off, 1.0))
    assert loudness(on, 0.0, 0.05) < 0.15 * loudness(off, 0.0, 0.05)
    assert loudness(on, 1.0) == pytest.approx(loudness(off, 1.0), rel=0.05)


def test_the_end_sinks_to_black_and_silence(tmp_path):
    end = Project.load(DEMO).song().duration
    on, off = pair(tmp_path, (end - 3.0, end))
    assert close(frame_at(on, 0.5), frame_at(off, 0.5))
    assert frame_at(on, 2.95).mean() < 0.15 * frame_at(off, 2.95).mean()
    assert loudness(on, 2.85) < 0.15 * loudness(off, 2.85)


@pytest.mark.parametrize("quick", [False, True])
def test_the_clip_and_the_video_both_take_the_fade(tmp_path, quick):
    demo = Project.load(DEMO)
    out = tmp_path / "q.mp4"
    render.render(
        out,
        demo.preview_lines(),
        demo.song(),
        render.Style(),
        2,
        (0.0, 2.0),
        lambda *_: None,
        quick,
    )
    assert frame_at(out, 0.0).mean() < 3
