"""Letter times and the upright karaoke look: the letter being sung lit, the turning disc, its wear."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from coverlyric import render, tall, timing
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"
YELLOW = render.hex_rgb(tall.HIGHLIGHT)


def demo(**keys) -> tuple[tuple[tuple[float, str], ...], render.Song, render.Style]:
    p = Project.load(DEMO)
    return p.preview_lines(), p.song(), replace(tall.shorts(p.style), **keys)


def spread(start: float, text: str, step: float = 0.3) -> tuple[float, ...]:
    return tuple(start + step * i for i in range(sum(not c.isspace() for c in text)))


def yellow(img) -> int:
    rgb = np.asarray(img.convert("RGB"), dtype=np.int16)
    return int((np.abs(rgb - YELLOW).sum(axis=2) < 30).sum())


def test_times_for_every_letter_are_kept():
    assert timing.letter_times("가 나!", [1, 2, 3]) == (1.0, 2.0, 3.0)


def test_punctuation_takes_the_time_of_the_letter_before_it():
    assert timing.letter_times("가, 나!", [1.0, 2.0]) == (1.0, 1.0, 2.0, 2.0)
    assert timing.letter_times('"가"', [4.0]) == (4.0, 4.0, 4.0), "an opening mark takes the first"


def test_times_that_fit_neither_count_are_dropped():
    assert timing.letter_times("가나다", [1.0, 2.0]) is None
    assert timing.letter_times("...", []) is None


def test_a_project_keeps_its_letter_times(tmp_path):
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    start, text = data["lines"][1]
    data["letters"] = [{"n": 2, "text": text, "times": list(spread(start, text))}]
    path = tmp_path / "project.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    p = Project.load(path)
    assert p.song().letters == ((start, text, spread(start, text)),)
    p.save(path)
    assert Project.load(path).letters == p.letters


def test_without_letter_times_the_song_has_none():
    assert Project.load(DEMO).song().letters == ()


def test_letter_times_of_a_changed_or_untimed_line_are_left_out():
    p = Project.load(DEMO)
    text = p.lines[1][1]
    p.letters = [
        {"n": 2, "text": text + "!", "times": [1.0]},
        {"n": 1, "text": p.lines[0][1], "times": "x"},
        {"n": 99, "text": text, "times": [1.0]},
    ]
    assert p.song().letters == ()
    p.lines[1] = (None, text)
    p.letters = [{"n": 2, "text": text, "times": list(spread(0.0, text))}]
    assert p.song().letters == ()


def test_only_the_letter_being_sung_is_lit_when_a_line_repeats_a_letter():
    times = (10.0, 10.5, 11.0)
    lines = ((9.0, "라라라"),)
    _, song, style = demo(highlight="letter", clip_from=8.0, clip_to=14.0)
    p = tall.Painter(lines, replace(song, letters=((9.0, "라라라", times),)), style)
    lit = [on for _, on in p.lyric_state(10.6)[2]]
    assert lit == [False, True, False]
    sizes = [s for s, _ in p.lyric_state(10.6)[2]]
    assert sizes[1] == tall.LETTER_POP and sizes[2] == 1.0
    assert p.lines[0][0] == 9.0


def test_a_punctuation_mark_does_not_end_its_letter():
    _, song, style = demo(highlight="letter", clip_from=0.0, clip_to=6.0)
    times = timing.letter_times("가!", [2.0])
    p = tall.Painter(((1.0, "가!"),), replace(song, letters=((1.0, "가!", times),)), style)
    assert [on for _, on in p.lyric_state(3.0)[2]] == [True, True]


def test_a_line_comes_in_no_later_than_its_first_letter():
    _, song, style = demo(highlight="letter", clip_from=0.0, clip_to=6.0)
    p = tall.Painter(((2.0, "가나"),), replace(song, letters=((2.0, "가나", (1.6, 2.2)),)), style)
    assert p.lines == ((1.6, "가나"),)


def test_the_letter_look_lights_the_sung_letter_and_the_line_look_does_not():
    lines, song, style = demo(clip_from=0.0, clip_to=0.0)
    start, text = lines[2]
    song = replace(song, letters=((start, text, spread(start, text)),))
    at = start + 0.3 * 3 + 0.2
    assert yellow(tall.Painter(lines, song, replace(style, highlight="letter")).image(at)) > 500
    assert yellow(tall.Painter(lines, song, style).image(at)) == 0


def test_without_letter_times_the_letter_look_lights_nothing():
    lines, song, style = demo(highlight="letter")
    start, _ = lines[2]
    assert yellow(tall.Painter(lines, song, style).image(start + 1.0)) == 0


def test_the_disc_turns_whole_turns_over_the_clip():
    lines, song, style = demo(upright_look="disc", clip_from=2.0, clip_to=0.0, spin=5.0)
    p = tall.Painter(lines, song, style)
    first, last = p.span
    assert p.turns == round((last - first) / 5.0) >= 1
    assert p.turn(last) % 360 == pytest.approx(0, abs=1e-6)
    a, b = np.asarray(p.background(first)), np.asarray(p.background(first + 1))
    assert (a != b).any(), "it turns"
    gap = np.abs(np.asarray(p.background(last)).astype(int) - a)
    assert gap.max() < 8, "the loop meets"


def test_a_still_disc_does_not_turn():
    lines, song, style = demo(upright_look="disc", spin=0.0)
    p = tall.Painter(lines, song, style)
    assert p.turns == 0
    assert (np.asarray(p.background(2.0)) == np.asarray(p.background(9.0))).all()


def test_the_bands_cover_the_disc():
    lines, song, style = demo(upright_look="disc", bars=True, bars_height=0.145)
    p = tall.Painter(lines, song, style)
    img = np.asarray(p.background(5.0).convert("RGB"))
    assert (img[: p.frame.bar - 1] == 0).all()
    assert (img[p.frame.h - p.frame.bar + 1 :] == 0).all()


def test_wear_peels_paint_and_keeps_its_colours():
    art = render.square(str(Path(render.__file__).parent / "demo" / "cover.png"))
    face = render.disc_print(art, 200)
    old, wear = tall.worn(face, 200)
    again, _ = tall.worn(face, 200)
    a0, a1 = np.asarray(face), np.asarray(old)
    assert (a1 == np.asarray(again)).all(), "the same wear every time"
    peeled = a1[..., 3] < a0[..., 3]
    assert 0 < peeled.mean() < 0.05, "a few places, not the whole print"
    assert (a1[..., :3] == a0[..., :3]).all(), "colours unchanged"
    assert 0 < np.asarray(wear)[..., 3].max() <= 38, "faint scratches"
