"""A song given as a video, such as a phone's screen recording whose sound starts after its picture:
the project keeps the sound alone, from its own first sample (cli.song_in)."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from coverlyric import cli, media

DEMO = Path(cli.__file__).parent / "demo"


@pytest.fixture(scope="module")
def recording(tmp_path_factory) -> Path:
    """Three seconds of grey picture; its sound, a 440 Hz tone for one second then silence, starts
    0.4 s after the picture, as in a screen recording."""
    out = tmp_path_factory.mktemp("rec") / "screen.mp4"
    subprocess.run(
        [media.ffmpeg(), "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=3",
         "-itsoffset", "0.4", "-f", "lavfi", "-i", r"aevalsrc=0.5*sin(2*PI*440*t)*lt(t\,1):s=44100:d=2.6",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(out)],
        check=True,
    )  # fmt: skip
    return out


def test_a_recording_s_sound_starts_late(recording):
    assert 0.3 < media.recording(str(recording)) < 0.5
    assert media.recording(str(DEMO / "tone.wav")) is None


def test_a_new_project_keeps_the_sound_from_its_own_start(recording, tmp_path, capsys):
    project = cli.new_project(tmp_path / "p", recording, DEMO / "cover.png", title="t")
    assert project.audio == "song.flac"
    assert "starts 0." in capsys.readouterr().err
    song = project.path(project.audio)
    assert media.recording(song) is None
    assert project.duration == pytest.approx(2.6, abs=0.05)
    # The tone is there from the first moment, not after 0.4 s of nothing.
    start = media.samples(song, 8000, start=0.0, length=0.2)
    assert np.abs(start[:400]).max() > 0.3
    assert np.abs(media.samples(song, 8000, start=1.2, length=0.2)).max() < 0.05
