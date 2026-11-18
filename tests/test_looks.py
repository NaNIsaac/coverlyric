"""The looks on the 꾸미기 step: one set of keys each, and a small still of every look."""

import base64
import io
from dataclasses import replace

import pytest
from PIL import Image

from coverlyric import looks, server
from coverlyric.render import Style


def test_every_look_sets_the_same_keys_and_nothing_else():
    for name, keys in looks.LOOKS.items():
        assert set(keys) == set(looks.KEYS), name
        Style.from_dict(keys)


def test_the_first_look_is_the_default_and_looks_are_told_apart():
    assert looks.current(Style()) == "기본"
    assert len({tuple(sorted(keys.items())) for keys in looks.LOOKS.values()}) == len(looks.LOOKS)
    for name in looks.LOOKS:
        assert looks.current(looks.apply(Style(), name)) == name


def test_a_look_keeps_the_album_text_and_places():
    style = replace(Style(), layout="disc", font="x.ttf", album_x=40, fade=False)
    dark = looks.apply(style, "어둡게")
    assert (dark.layout, dark.font, dark.album_x, dark.fade) == ("disc", "x.ttf", 40, False)
    assert looks.current(replace(dark, dim=0.1)) is None
    with pytest.raises(ValueError):
        looks.apply(style, "보라")


def test_the_page_gets_a_still_of_each_look(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    data = app.look_stills(7.0)
    assert list(data["stills"]) == list(looks.LOOKS) and data["current"] == "기본"
    head, _, body = data["stills"]["흑백"].partition(",")
    assert head == "data:image/jpeg;base64"
    still = Image.open(io.BytesIO(base64.b64decode(body)))
    assert still.size == (320, 180)
    r, g, b = still.convert("RGB").getpixel((10, 10))
    assert max(r, g, b) - min(r, g, b) <= 6
