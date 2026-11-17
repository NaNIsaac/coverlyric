"""A lyric line wider than the panel shrinks, then wraps to two rows, and never runs past the band."""

import numpy as np

from coverlyric import render

STYLE = render.Style()
SHORT = "첫 번째 줄이에요"
MEDIUM = "가나다라마바사아자차카타파하 가나다라마바사"  # a little wider than the panel
LONG = "가나다라마바사아자차카타파하 가나다라마바사아자차카타파하 가나다라"


def fits(*texts):
    return render.line_fits(tuple((float(i), t) for i, t in enumerate(texts)), STYLE)


def test_a_short_line_keeps_its_size():
    assert fits(SHORT) == [(1.0, 1)]


def test_a_little_too_wide_line_shrinks_on_one_row():
    [(factor, rows)] = fits(MEDIUM)
    assert rows == 1 and render.MIN_FIT <= factor < 1.0


def test_a_long_line_wraps_to_two_rows():
    [(factor, rows)] = fits(LONG)
    assert rows == 2 and factor <= 1.0


def test_an_empty_line_is_not_marked():
    assert fits("") == [(1.0, 1)]


def test_the_current_line_stays_inside_the_band():
    lines = ((0.0, LONG), (5.0, SHORT))
    panel = np.asarray(render.panel_at(0.0, lines, STYLE))
    mid = panel.shape[0] // 2
    edge = 14 + 6  # the band's inset plus a little
    band_rows = panel[mid - 30 : mid + 30]
    text = band_rows[:, :, 3] > 200  # the band itself is about 165 opaque
    assert not text[:, :edge].any() and not text[:, -edge:].any()
    assert text.any()


def outline_height(text: str) -> int:
    """Rows of the panel's middle where the current line's red outline shows."""
    style = render.Style(lyric_edge="outline", lyric_edge_colour="#ff0000")
    panel = np.asarray(render.panel_at(0.0, ((0.0, text), (5.0, SHORT)), style)).astype(int)
    mid = panel.shape[0] // 2
    band = panel[mid - 60 : mid + 60]
    red = (band[..., 0] > 200) & (band[..., 1] < 80) & (band[..., 2] < 80) & (band[..., 3] > 200)
    rows = np.flatnonzero(red.any(axis=1))
    return int(rows[-1] - rows[0]) if rows.size else 0


def test_both_rows_of_a_wrapped_line_get_the_outline():
    one = outline_height(SHORT)
    assert one > 0 and outline_height(LONG) > 1.4 * one
