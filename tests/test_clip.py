"""The 10 s preview clip: small, half the frame rate, the preview's look, made by the page's own job."""

import re
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from coverlyric import anim, media, render, server
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


def probe(path: Path) -> str:
    return subprocess.run(
        [media.ffmpeg(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    ).stderr


def test_a_quick_clip_is_small_and_takes_every_second_frame(tmp_path):
    demo = Project.load(DEMO)
    out, seen = tmp_path / "quick.mp4", []
    render.render(
        out,
        demo.preview_lines(),
        demo.song(),
        render.Style(),
        workers=2,
        span=(3.0, 8.0),
        report=lambda *args: seen.append(args),
        quick=True,
    )
    info = probe(out)
    rate = render.FPS // render.QUICK_STEP
    assert "960x540" in info and re.search(rf"\b{rate} fps\b", info) and "Audio: aac" in info
    assert media.duration(str(out)) == pytest.approx(5.0, abs=0.1)
    done, total, frames, frames_total, _ = seen[-1]
    assert (done, total) == pytest.approx((5.0, 5.0))
    assert frames == frames_total == 5 * rate


def wait(app: server.App, seconds: float = 120) -> dict:
    end = time.time() + seconds
    while app.clip.get("state") == "running" and time.time() < end:
        time.sleep(0.2)
    return app.clip


def test_the_page_gets_a_clip_from_the_preview_time(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    started = app.start_clip(4.0)
    assert started["state"] == "running" and started["total"] == pytest.approx(server.CLIP_S)
    job = wait(app)
    assert job["state"] == "done" and job["url"].startswith("/media/clip?v=")
    clip = app.clip_file
    assert media.duration(str(clip)) == pytest.approx(server.CLIP_S, abs=0.1)
    # Near the end of the song the clip is what is left, from at most a second before the end.
    app.start_clip(17.5)
    assert app.clip["at"] == pytest.approx(app.project.song().duration - 1.0)
    assert wait(app)["state"] == "done"
    assert not list(app.output.glob("*.mp4")), "a look is not a finished video"


def test_a_clip_waits_for_a_running_render(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    app.job = {"state": "running"}
    with pytest.raises(ValueError):
        app.start_clip(0.0)


def test_a_quick_clip_keeps_the_moving_picture(tmp_path):
    demo = Project.load(DEMO)
    picture = tmp_path / "green.png"
    Image.new("RGBA", (40, 40), (0, 255, 0, 255)).save(picture)
    song = replace(demo.song(), anim=(str(picture),))
    out = tmp_path / "anim.mp4"
    render.render(
        out, demo.preview_lines(), song, render.Style(), 2, (5.0, 6.0), lambda *_: None, True
    )
    raw = subprocess.run(
        [
            media.ffmpeg(),
            "-v",
            "error",
            "-i",
            str(out),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    frame = np.frombuffer(raw, np.uint8).reshape(render.QUICK_SIZE[1], render.QUICK_SIZE[0], 3)
    x, y = (c * render.QUICK_SIZE[0] // render.W for c in anim.CENTRE)
    r, g, b = frame[y, x].astype(int)
    assert g > 200 and r < 60 and b < 60
