"""The music player look (layout=player) for the 16:9 video (COVER-PLAYER)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from coverlyric import __main__ as entry
from coverlyric import player, render
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo"
PLAYER = render.Style(layout="player")


@pytest.fixture(scope="module")
def demo() -> Project:
    p = Project.load(DEMO / "demo.json")
    p.folder = DEMO
    return p


def inside(box: tuple[int, ...]) -> bool:
    return 0 <= box[0] < box[2] <= render.W and 0 <= box[1] < box[3] <= render.H


@pytest.mark.parametrize("height", [1080, 720])
def test_every_part_is_inside_the_frame(demo, height):
    style = replace(PLAYER, height=height)
    found = render.boxes(style)
    assert set(found) == {"album", "panel"}
    assert all(inside(b) for b in found.values()), found
    assert not render.overlaps(found["album"], found["panel"])
    img = render.frame(5.0, demo.preview_lines(), demo.song(), style)
    assert img.size == (render.W, render.H), "drawn at 1080 and scaled by ffmpeg, as the wide look"


def test_the_column_moves_and_scales_with_the_album_keys():
    moved = render.boxes(replace(PLAYER, album_x=40, album_y=-20))["album"]
    plain = render.boxes(PLAYER)["album"]
    assert (moved[0] - plain[0], moved[1] - plain[1]) == (40, -20)
    small = render.boxes(replace(PLAYER, album_scale=0.8))["album"]
    assert small[2] - small[0] < plain[2] - plain[0]


@pytest.mark.parametrize(
    ("t", "played", "left"),
    [
        (0.0, "0:00", "-3:27"),
        (26.4, "0:26", "-3:01"),
        (207.0, "3:27", "-0:00"),
        (300.0, "3:27", "-0:00"),
    ],
)
def test_time_played_and_time_left(t, played, left):
    song = render.Song("a.wav", "c.png", "t", duration=207.0)
    assert player.times(t, song) == (played, left)


def test_the_silences_do_not_count():
    song = render.Song("a.wav", "c.png", "t", duration=74.0, lead=2.0, tail=2.0)
    assert player.times(1.0, song) == ("0:00", "-1:10")
    assert player.times(72.5, song) == ("1:10", "-0:00")
    assert player.share(1.0, song) == 0.0 and player.share(37.0, song) == 0.5


def test_the_line_under_the_title():
    song = render.Song("a.wav", "c.png", "아리랑", artist="민요")
    assert player.subtitle(song) == "민요 — 아리랑 - Single"
    assert player.subtitle(replace(song, album="옛 노래")) == "민요 — 옛 노래"
    assert player.subtitle(replace(song, artist="")) == "아리랑 - Single"


def test_an_empty_date_has_no_badge(demo):
    song = demo.song()
    bare, at = player.chrome(song, PLAYER)
    dated, _ = player.chrome(replace(song, released="2026.06.23"), PLAYER)
    bx, by, bh = player.BADGE
    x, y = player.COVER[0] + bx - at[0], player.COVER[1] + by - at[1]
    spot = (x + bh // 2, y + 4, x + 3 * bh, y + bh - 4)
    assert song.released == ""
    assert bare.crop(spot).tobytes() != dated.crop(spot).tobytes()


def test_the_bar_and_the_list_move_with_the_song(demo):
    lines, song = demo.preview_lines(), demo.song()
    still = replace(PLAYER, spin=0.0, drift=False)
    a = render.frame(4.0, lines, song, still)
    b = render.frame(12.0, lines, song, still)
    bar = render.boxes(still)["album"]
    x0, _, x1, _ = player.box((player.TEXT_X, 0, player.TEXT_RIGHT, 0), still)
    _, y = player.scaled(0, player.BAR_Y, still)
    row = (x0, round(y) - 1, x1, round(y) + 1)
    assert a.crop(row).tobytes() != b.crop(row).tobytes()
    panel = render.boxes(still)["panel"]
    assert a.crop(panel).tobytes() != b.crop(panel).tobytes()
    assert bar[2] <= panel[0]


def test_a_still_cd_and_a_turning_one(demo):
    lines, song = demo.preview_lines(), demo.song()
    turning = replace(PLAYER, drift=False)
    p = render.painter(lines, song, turning)
    assert p.state(5.0)[0] != p.state(5.5)[0], "the CD turns"
    still = render.painter(lines, song, replace(turning, spin=0.0))
    assert still.state(5.0)[0] is None


def test_the_title_card_and_the_opening_still_work(demo):
    lines, song = demo.preview_lines(), demo.song()
    card = render.frame(0.2, lines, song, replace(PLAYER, intro=2.0))
    assert (
        card.tobytes()
        == render.intro_card(song, replace(PLAYER, intro=2.0), render.stamp(song.art))
        .convert("RGB")
        .tobytes()
    )


def test_no_tilt_in_the_player_look():
    assert render.tilt_of(replace(PLAYER, tilt=20.0)) is None


def test_album_and_date_are_kept_in_the_project(tmp_path):
    p = Project(tmp_path, title="t", album="옛 노래", released="2026.06.23")
    p.save(tmp_path / "project.json")
    back = Project.load(tmp_path / "project.json")
    assert (back.album, back.released) == ("옛 노래", "2026.06.23")
    assert (back.song().album, back.song().released) == ("옛 노래", "2026.06.23")
    assert Project.from_dict(tmp_path, {}).released == ""


def test_the_command_line_sets_the_look_album_and_date(capsys, tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    Project(folder, title="t").save(folder / "project.json")
    with pytest.raises(SystemExit) as done:
        entry.main(
            [
                "project",
                "set",
                str(folder),
                "layout=player",
                "album=옛 노래",
                "released=2026.06.23",
                "--json",
            ]
        )
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert done.value.code == 0
    assert (data["album"], data["released"], data["style"]["layout"]) == (
        "옛 노래",
        "2026.06.23",
        "player",
    )


def test_the_page_keeps_album_and_date(tmp_path):
    from coverlyric import server

    app = server.App(tmp_path)
    app.demo()
    app.update({"album": "옛 노래", "released": "2026.06.23", "style": {"layout": "player"}})
    state = app.state()
    assert (state["album"], state["released"], state["style"]["layout"]) == (
        "옛 노래",
        "2026.06.23",
        "player",
    )
