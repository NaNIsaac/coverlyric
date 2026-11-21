"""The drifting light is a window of one light built once (render.whole_light), the same pixels as
building it around each centre."""

import numpy as np
import pytest

from coverlyric import render


def built_around(centre: tuple[int, int]) -> np.ndarray:
    gx = np.exp(-(((np.arange(render.W) - centre[0]) / render.LIGHT_SIGMA) ** 2) / 2)
    gy = np.exp(-(((np.arange(render.H) - centre[1]) / render.LIGHT_SIGMA) ** 2) / 2)
    glow = np.outer(gy, gx)[..., None] * (np.array([1.0, 0.93, 0.85]) * render.LIGHT_PEAK)
    return np.rint(glow).astype(np.uint8)


@pytest.mark.parametrize("t", [0.0, 3.7, 11.0, 29.5, 61.2])
def test_the_light_is_the_same_as_built_around_its_centre(t):
    centre = render.light_at(t)
    img = render.light(centre)
    assert img.size == (render.W, render.H) and img.mode == "RGBA"
    got = np.asarray(img)
    assert (got[..., :3] == built_around(centre)).all()
    assert not got[..., 3].any()
