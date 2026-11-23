"""A Short's hook caption in a taller top band, the picture's top cut off, and the loop blend's
length."""

from dataclasses import replace

import numpy as np
from test_shapes import demo, pixels

from coverlyric import render, tall

HOOK = "첫 줄 문구|둘째 줄 노란 말"


def short(**style):
    return demo("tall", bars=True, clip_from=6.0, clip_to=10.0, **style)


def test_without_a_hook_or_a_crop_the_frame_is_as_before():
    lines, song, style = short()
    plain = pixels(render.frame(8.0, lines, song, style))
    blank = pixels(render.frame(8.0, lines, song, replace(style, hook=" | ", crop_top=0)))
    assert np.array_equal(plain, blank)


def test_the_hook_band_is_taller_and_holds_the_yellow_words():
    lines, song, style = short(hook=HOOK, hook_hi="노란 말")
    fr = tall.frame_of(style)
    img = pixels(render.frame(8.0, lines, song, style))
    band = img[: fr.bar + tall.HOOK_SHIFT]
    edge = img[fr.bar + tall.HOOK_SHIFT - 4 : fr.bar + tall.HOOK_SHIFT]
    assert (edge == 0).all(), "the band reaches HOOK_SHIFT px further down, plain black"
    yellow = (band[..., 0] > 200) & (band[..., 1] > 170) & (band[..., 2] < 120)
    white = (band > 230).all(axis=-1)
    assert yellow.sum() > 500 and white.sum() > 500
    plain = pixels(render.frame(8.0, lines, song, replace(style, hook="")))
    below = img[fr.bar + tall.HOOK_SHIFT : fr.h - fr.bar]
    assert np.array_equal(below, plain[fr.bar : fr.h - fr.bar - tall.HOOK_SHIFT])


def test_crop_top_moves_the_picture_up():
    lines, song, style = short()
    fr = tall.frame_of(style)
    plain = pixels(render.frame(8.0, lines, song, style))
    cut = pixels(render.frame(8.0, lines, song, replace(style, crop_top=90)))
    assert np.array_equal(cut[fr.bar : fr.h - fr.bar - 90], plain[fr.bar + 90 : fr.h - fr.bar])
    assert (cut[fr.h - fr.bar - 90 :] == 0).all(), "the bottom band takes the room"


def test_hook_and_crop_need_the_bands():
    lines, song, style = demo("tall", clip_from=6.0, clip_to=10.0)
    plain = pixels(render.frame(8.0, lines, song, style))
    asked = pixels(render.frame(8.0, lines, song, replace(style, hook=HOOK, crop_top=90)))
    assert np.array_equal(plain, asked)


def test_one_hook_row_is_centred_and_a_third_row_is_dropped():
    style = short(hook="하나|둘|셋")[2]
    assert tall.hook_rows(style) == ["하나", "둘"]
    assert tall.hook_rows(replace(style, bars=False)) == []


def test_a_long_hook_row_shrinks_to_the_frame():
    style = short(hook="아주 길고 긴 훅 문구가 한 줄에 다 들어가지 않을 만큼 길게 이어지는 경우")[2]
    fr = tall.frame_of(style)
    band = pixels(tall.hook_band(style, fr))
    lit = np.where((band > 200).all(axis=-1).any(axis=0))[0]
    assert lit.min() >= fr.margin - 2 and lit.max() <= fr.w - fr.margin + 2


def test_the_loop_blends_loop_blend_seconds():
    _, song, style = short(loop=True)
    assert tall.loop_length(style, song) == 0.5
    assert tall.loop_length(replace(style, loop_blend=0.3), song) == 0.3
    assert tall.loop_length(replace(style, loop_blend=9.0), song) == 6.0, (
        "no more than the clip's start"
    )
    assert tall.loop_length(replace(style, loop=False, loop_blend=0.3), song) == 0.0
