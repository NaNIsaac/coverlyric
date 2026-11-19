"""The moving picture: GIF timing, image order, looping, transparency, placement and the render path."""

import io
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from coverlyric import anim, render, server
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"
RED, GREEN, BLUE = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)


def gif(path: Path, colours, durations, transparent_corner=False) -> str:
    frames = []
    for colour in colours:
        img = Image.new("RGBA", (40, 40), colour)
        if transparent_corner:
            img.paste((0, 0, 0, 0), (0, 0, 20, 20))
        frames.append(img)
    frames[0].save(
        path, save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=2
    )
    return str(path)


def images(folder: Path, colours) -> tuple[str, ...]:
    paths = []
    for i, colour in enumerate(colours):
        path = folder / f"frame{i}.png"
        Image.new("RGBA", (30, 60), colour).save(path)
        paths.append(str(path))
    return tuple(paths)


def centre(img: Image.Image) -> tuple:
    return img.getpixel((img.width // 2, img.height // 2))


@pytest.fixture
def demo() -> Project:
    return Project.load(DEMO)


def test_a_gif_keeps_its_own_delays_and_loops(tmp_path):
    path = gif(tmp_path / "a.gif", [RED, GREEN, BLUE], [100, 300, 200])
    timing, pictures = anim.at((path,), 8.0, 1.0)
    assert timing.ends == pytest.approx((0.1, 0.4, 0.6))
    assert [timing.index(t) for t in (0.0, 0.05, 0.2, 0.39, 0.45, 0.59)] == [0, 0, 1, 1, 2, 2]
    assert [timing.index(t) for t in (0.6, 0.65, 0.8, 60.0 + 0.45)] == [0, 0, 1, 2]
    assert [centre(p)[:3] for p in pictures] == [RED[:3], GREEN[:3], BLUE[:3]]


def test_images_show_in_the_given_order_at_the_chosen_fps(tmp_path):
    paths = images(tmp_path, [BLUE, RED, GREEN])
    timing, pictures = anim.at(paths, 2.0, 1.0)
    assert [timing.index(t) for t in (0.0, 0.49, 0.5, 1.2, 1.5, 3.1)] == [0, 0, 1, 2, 0, 0]
    assert [centre(p) for p in pictures] == [BLUE, RED, GREEN]
    # Scaled once to the placed size, keeping the shape: the longer side is SIDE * scale.
    assert timing.size == (180, 360)
    assert anim.at(paths, 2.0, 0.5)[0].size == (90, 180)


def test_a_long_gif_keeps_at_most_max_frames_over_the_same_loop(tmp_path):
    colours = [(i % 256, 0, 0, 255) for i in range(300)]
    timing, pictures = anim.at((gif(tmp_path / "long.gif", colours, [40] * 300),), 8.0, 1.0)
    assert len(pictures) <= anim.MAX_FRAMES and len(pictures) == len(timing.ends)
    assert timing.ends[-1] == pytest.approx(12.0)
    assert timing.nbytes() <= anim.MAX_MB * 2**20


def test_a_transparent_gif_shows_the_frame_through(tmp_path, demo):
    path = gif(tmp_path / "t.gif", [RED], [100], transparent_corner=True)
    song, lines = demo.song(), demo.preview_lines()
    plain = render.frame(5.0, lines, song, replace(demo.style, drift=False))
    style = render.Style(anim_x=-400, anim_y=-200, drift=False)  # the light would tint the picture
    with_anim = render.frame(5.0, lines, replace(song, anim=(path,)), style)
    x0, y0, x1, y1 = render.boxes(style, 5.0, replace(song, anim=(path,)))["anim"]
    clear, solid = (x0 + 10, y0 + 10), (x1 - 10, y1 - 10)
    base = render.frame(5.0, lines, song, style)
    assert with_anim.getpixel(clear) == base.getpixel(clear)
    assert with_anim.getpixel(solid) == RED[:3]
    assert np.array_equal(np.asarray(plain), np.asarray(base))  # no picture: the frame as before


def test_under_the_album_the_album_covers_it(tmp_path, demo):
    path = images(tmp_path, [GREEN])
    song = replace(demo.song(), anim=path)
    lines = demo.preview_lines()
    case = render.geometry(render.Style()).case
    # Centre the picture on the case: above, it shows; under, the case's opaque cover hides it.
    cx, cy = (case[0] + case[2]) // 2, (case[1] + case[3]) // 2
    move = {"anim_x": cx - anim.CENTRE[0], "anim_y": cy - anim.CENTRE[1]}
    above = render.frame(5.0, lines, song, render.Style(**move, drift=False))
    under = render.frame(5.0, lines, song, render.Style(**move, anim_above=False))
    assert above.getpixel((cx, cy)) == GREEN[:3]
    assert under.getpixel((cx, cy)) != GREEN[:3]
    assert under.getpixel((cx, cy)) == render.frame(
        5.0, lines, demo.song(), render.Style()
    ).getpixel((cx, cy))


def test_the_round_disc_covers_a_picture_under_it(tmp_path, demo):
    path = images(tmp_path, [GREEN])
    song = replace(demo.song(), anim=path)
    g = render.geometry(render.Style(layout="disc"))
    move = {"anim_x": g.round_c[0] - anim.CENTRE[0], "anim_y": g.round_c[1] - anim.CENTRE[1]}
    style = render.Style(layout="disc", anim_above=False, **move)
    img = render.frame(5.0, demo.preview_lines(), song, style)
    plain = render.frame(5.0, demo.preview_lines(), demo.song(), render.Style(layout="disc"))
    assert img.getpixel(g.round_c) == plain.getpixel(g.round_c)


def test_the_render_path_draws_what_the_preview_shows(tmp_path, demo):
    """Workers read the frames from shared memory; the frames match the preview's."""
    paths = images(tmp_path, [BLUE, RED, GREEN])
    song = replace(demo.song(), anim=paths)
    style, lines = render.Style(anim_y=-300), demo.preview_lines()
    timing, pictures = anim.at(paths, style.anim_fps, style.anim_scale)
    memory = anim.share(timing, pictures)
    p = render.Painter(lines, song, style, moving=(memory.name, timing))
    try:
        for t in (2.0, 2.2, 2.4, 7.0):
            got = Image.frombytes("RGBA", (render.W, render.H), p.raw(t)).convert("RGB")
            assert np.array_equal(np.asarray(got), np.asarray(render.frame(t, lines, song, style)))
    finally:
        p.pictures.memory.close()
        memory.close()
        memory.unlink()


def test_the_project_keeps_the_files_next_to_it(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    one = Image.new("RGBA", (8, 8), RED)
    buf = io.BytesIO()
    one.save(buf, "PNG")
    app.upload("anim", "b.png", buf.getvalue())
    app.upload("anim", "a.png", buf.getvalue())
    app.upload("anim", "a.png", buf.getvalue())
    assert app.project.anim == ["anim/b.png", "anim/a.png", "anim/a-2.png"]
    assert all((app.work / name).is_file() for name in app.project.anim)
    app.update({"anim": ["anim/a-2.png", "anim/b.png", "../../outside.png"]})
    assert app.project.anim == ["anim/a-2.png", "anim/b.png"]
    assert not (app.work / "anim" / "a.png").exists()
    loaded = Project.load(app.file)
    assert loaded.anim == ["anim/a-2.png", "anim/b.png"]
    assert loaded.song().anim == tuple(str((app.work / n).resolve()) for n in loaded.anim)
    gif(tmp_path / "g.gif", [RED, GREEN], [100, 100])
    app.upload("anim", "walk.gif", (tmp_path / "g.gif").read_bytes())
    assert app.project.anim == ["anim/walk.gif"]
    assert not (app.work / "anim" / "b.png").exists()
    with pytest.raises(ValueError):
        app.upload("anim", "x.png", b"not an image")
