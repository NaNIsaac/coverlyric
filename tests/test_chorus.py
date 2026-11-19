"""후렴 찾기: the part of the song a Short should hold, found from the timed lyrics (COVER-SHORTS)."""

from coverlyric import server, tall


def timed(*texts: str, gap: float = 4.0, first: float = 10.0) -> tuple[tuple[float, str], ...]:
    return tuple((first + i * gap, text) for i, text in enumerate(texts))


def test_the_most_repeated_block_of_lines_is_the_chorus():
    lines = timed(
        "a1",
        "a2",
        "후렴 하나",
        "후렴 둘",
        "b1",
        "후렴 하나",
        "후렴 둘",
        "c1",
        "후렴 하나",
        "후렴 둘",
    )
    assert tall.chorus(lines, 200.0, 15) == (18.0, 33.0)


def test_a_longer_block_wins_over_its_part_when_both_repeat_as_often():
    lines = timed("x", "y", "z", "q", "x", "y", "z")
    first, _ = tall.chorus(lines, 200.0, 30)
    assert first == 10.0


def test_lines_match_without_case_spaces_or_punctuation():
    lines = timed("Oh, my love!", "같이 가요", "v", "oh my love", "같이 가요.", "w")
    assert tall.chorus(lines, 200.0, 15)[0] == 10.0


def test_the_clip_stays_inside_the_song_and_starts_on_a_line():
    lines = timed("v1", "후렴", "v2", "후렴", first=100.0, gap=10.0)
    assert tall.chorus(lines, 150.0, 60) == (110.0, 150.0), "shorter at the song's end"


def test_a_song_with_nothing_repeated_has_no_chorus():
    assert tall.chorus(timed("a", "b", "c"), 100.0, 30) is None
    assert tall.chorus((), 100.0, 30) is None


def test_untimed_and_empty_lines_do_not_count():
    lines = ((None, "후렴"), (10.0, ""), (12.0, "후렴"), (20.0, "x"), (30.0, ""), (32.0, "후렴"))
    assert tall.chorus(lines, 100.0, 15) == (12.0, 27.0)


def test_the_page_asks_for_the_chorus(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    app.project.lines = [(3.0, "후렴"), (6.5, "다른 줄"), (10.0, "후렴"), (13.5, "끝")]
    assert app.find_chorus(15) == {"from": 3.0, "to": 18.0}
    app.project.lines = [(3.0, "a"), (6.5, "b")]
    assert app.find_chorus(15) == {"from": None, "to": None}


def test_a_short_opens_on_its_line_already_in_place():
    from dataclasses import replace
    from pathlib import Path

    from coverlyric import render
    from coverlyric.project import Project

    p = Project.load(Path(render.__file__).parent / "demo" / "demo.json")
    style = replace(tall.shorts(p.style), clip_from=6.5, clip_to=12.0)
    first = tall.layout(6.5, p.preview_lines(), p.song(), style)
    assert first["now"]["text"] == p.lines[1][1] and first["progress"] == 1.0
    assert first["gone"] is None, "nothing leaving on the first frame"
    later = tall.layout(10.0, p.preview_lines(), p.song(), style)
    assert later["progress"] < 1.0, "lines inside the clip still move in"


def test_the_preview_of_a_short_is_on_the_song_clock(tmp_path):
    from dataclasses import replace

    app = server.App(tmp_path)
    app.demo()
    app.project.style = replace(tall.shorts(app.project.style), lead=2.0)
    jpeg, boxes, _ = app.preview(6.5, 360)
    assert boxes == {} and jpeg[:2] == b"\xff\xd8"
