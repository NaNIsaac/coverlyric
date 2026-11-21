"""The case's plastic greys and softens what shows through it (case_haze), and only that."""

from dataclasses import replace
from pathlib import Path

import numpy as np

from coverlyric import render
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


def frames(**keys) -> tuple[np.ndarray, render.Painter]:
    p = Project.load(DEMO)
    style = replace(p.style, layout="case", drift=False, **keys)
    painter = render.Painter(p.preview_lines(), p.song(), style, shared=None)
    return np.asarray(painter.image(6.0).convert("RGB")).astype(int), painter


def test_the_plastic_greys_only_what_lies_under_the_case():
    clear, painter = frames(case_haze=0.0)
    hazed, _ = frames()
    g = painter.g
    x0, y0, x1, y1 = g.case
    cover = (x0 + g.hinge, y0 + g.inset, x1 - g.inset, y1 - g.inset)
    differs = np.abs(hazed - clear).sum(axis=2) > 0
    assert differs[y0:y1, x0:x1].any(), "the strip around the cover is greyed"
    inside = differs[cover[1] + 4 : cover[3] - 4, cover[0] + 4 : cover[2] - 4]
    assert not inside.any(), "the cover lies on top of the plastic"
    outside = differs.copy()
    outside[y0:y1, x0:x1] = False
    assert not outside.any()
    milk = np.array(render.MILK[:3])
    strip = (slice(y0 + 2, y1 - 2), slice(x0 + 2, x0 + g.hinge - 2))
    near = np.abs(hazed[strip] - milk).mean(), np.abs(clear[strip] - milk).mean()
    assert near[0] < near[1], "nearer the plastic's grey"


def test_a_tilted_case_keeps_its_plastic_clear():
    assert (frames(tilt=12.0)[0] == frames(tilt=12.0, case_haze=0.0)[0]).all()
