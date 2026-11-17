"""Output choices: 24 or 30 frames a second, and 1080p or 720p."""

import re
import subprocess
from pathlib import Path

import pytest

from coverlyric import media, render
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


def probe(path: Path) -> str:
    return subprocess.run(
        [media.ffmpeg(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    ).stderr


def make(tmp_path: Path, **style) -> tuple[str, tuple]:
    demo = Project.load(DEMO)
    out, seen = tmp_path / "out.mp4", []
    render.render(
        out,
        demo.preview_lines(),
        demo.song(),
        render.Style(**style),
        workers=2,
        span=(3.0, 5.0),
        report=lambda *args: seen.append(args),
    )
    return probe(out), seen[-1]


@pytest.mark.parametrize(
    ("fps", "height", "size"), [(30, 1080, "1920x1080"), (24, 720, "1280x720")]
)
def test_rate_and_size(tmp_path, fps, height, size):
    info, (_, _, frames, frames_total, _) = make(tmp_path, fps=fps, height=height)
    assert size in info and re.search(rf"\b{fps} fps\b", info)
    assert frames == frames_total == 2 * fps


def test_unknown_rate_falls_back_to_the_default():
    assert render.rate(render.Style(fps=25)) == render.FPS
    assert render.rate(render.Style(fps=30)) == 30


def test_one_cd_turn_is_whole_frames_at_both_rates():
    for fps in render.RATES:
        found = render.turn_set(render.Style(fps=fps))
        assert found is not None and found[1] == round(render.Style().spin * fps)
