"""Draw lyric-video frames with Pillow and pipe them to ffmpeg.

The left side holds the cover, either in a clear jewel case with a CD half out (the print turns, the case
stays still) or as a still round disc. The right side holds the lyric list, which moves one row per line
with a quintic ease and keeps the current line on a coloured band. Title, artist and an optional playback
bar sit on a blurred, darkened copy of the cover. Every element can be moved and scaled through `Style`;
the default style is the original look.
"""

from __future__ import annotations

import colorsys
import errno
import math
import subprocess
import tempfile
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass, fields, replace
from functools import lru_cache
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import anim, fonts, media

# 24 fps: the slow turn of the disc and the eased lyric list look the same as at 30, with a fifth
# fewer frames to draw and encode.
W, H, FPS = 1920, 1080, 24
# The upright frames tall.py draws, by shape: 9:16 for Shorts, 1:1 and 4:5 for feeds.
UPRIGHT = {"tall": (1080, 1920), "square": (1080, 1080), "portrait": (1080, 1350)}
RATES = (24, 30)  # frame rates the page offers; FPS is the default
# Smaller videos are drawn at 1080 like the rest and scaled once by ffmpeg: the render is bound by the
# encoder, which then has a little under half the pixels.
HEIGHTS = {1080: None, 720: (1280, 720)}
CHUNK = 4  # frames a worker draws at a time
FRAME = W * H * 4  # one RGBA frame, 8.3 MB
# A quick clip for looking, not for keeping: every second frame, half size, the fastest x264.
QUICK_STEP, QUICK_SIZE = 2, (960, 540)
QUICK_X264 = ["-preset", "ultrafast", "-crf", "26", "-threads", "2"]
SS = 2  # the lyric panel and title are drawn at twice the size and scaled down
DIM_WEIGHT, NOW_WEIGHT = 350, 600
DIM_SIZE, NOW_SIZE = 34, 44
TRACKING = 0.04  # extra space between letters, in em
MIN_FIT = 0.75  # a long line shrinks to this share of its size before it wraps to two rows
ROW_PITCH = 1.08  # distance between the two rows of a wrapped line, in em

DISC_C, DISC_R = (560, 610), 330
CASE = (110, 318, 714, 902)
HINGE = 40
INSET = 12  # between the case edge and the printed cover inside it
CASE_DISC_R = 262
HOLE = 0.075  # centre hole radius, as a fraction of the disc radius
SLIDE = (0.3, 1.9)  # seconds: the disc slides out of the case once
PANEL = (1010, 250, 1850, 970)
ROW = 92
PLAYER_PANEL, PLAYER_ROW = (
    (985, 150, 1840, 1010),
    97,
)  # the player look's list: taller, left aligned
SCROLL = 0.45
ENTER = 1.2  # seconds the list takes to rise into the empty panel for the first line
VISIBLE = 3.4
EDGE = 70
BAND_ALPHA = 165
OUTLINE_WIDTH = 0.06  # of the font size
SHADOW_DROP, SHADOW_ALPHA = 0.05, 0.7  # offset as a share of the font size, and strength
TITLE_Y, ARTIST_Y, TITLE_BOX = 100, 162, 240
INTRO_FADE = 0.8  # seconds the opening title card takes to fade into the song's frame
# In a long intro the title and the artist show in the lyric panel and go before the lines come in:
# in and out over these seconds of a 16 s intro, stretched in proportion for a longer or shorter one.
OPENING = ((5.0, 6.5), (9.5, 10.5))
OPENING_FOR = 16.0
OPENING_LEAST = 8.0  # seconds before the first line an intro needs for the title
# The light that drifts over the frame: its peak in levels of 255, its size, and how slowly it goes
# round (seconds across and down; unequal, so the path does not repeat within a song).
LIGHT_PEAK, LIGHT_SIGMA, LIGHT_PERIODS = 16, 380, (53.0, 71.0)
BAR = (110, 1000, 1850, 1040)
# The album's tilt: at most this many degrees, seen from this many pixels away, close enough that
# 20 degrees already reads as turned.
TILT_MAX, TILT_DISTANCE = 40.0, 1150


@dataclass(frozen=True)
class Style:
    """Everything the user can change. Offsets are in pixels of the 1920x1080 frame; scales are factors."""

    layout: str = (
        "case"  # case | disc | player (player.py: the cover and buttons of a music player)
    )
    font: str = fonts.DEFAULT
    band: str = "#c49668"
    lyric_colour: str = "#ffffff"
    lyric_edge: str = "none"  # none | outline | shadow, for lyrics on a light cover
    lyric_edge_colour: str = "#000000"
    blur: int = 30
    dim: float = 0.5
    spin: float = 7.0  # seconds per turn of the case's CD; 0 keeps it still
    show_cd: bool = True  # the case layout's CD half out of the case
    case_haze: float = 0.15  # 0 to 1: the case's plastic greys and softens what shows through it
    album_x: int = 0
    album_y: int = 0
    album_scale: float = 1.0
    tilt: float = 0.0  # degrees the album turns about its upright axis; positive faces it right
    panel_x: int = 0
    panel_y: int = 0
    panel_scale: float = 1.0
    title_x: int = 0
    title_y: int = 0
    title_scale: float = 1.0
    show_title: bool = True
    bar: bool = False
    bar_x: int = 0
    bar_y: int = 0
    bar_scale: float = 1.0
    fade: bool = True  # the video and the sound fade in at the start and out at the end
    fps: int = FPS  # one of RATES
    height: int = 1080  # one of HEIGHTS
    anim_x: int = 0
    anim_y: int = 0
    anim_scale: float = 1.0
    anim_fps: float = 8.0  # frames per second of an image list; a GIF keeps its own delays
    anim_above: bool = True  # over everything, or under the album and the lyrics
    tone: str = "none"  # background colour: none | warm | cool | mono | cover (tinted with the cover's colour)
    vignette: float = 0.0  # 0 to 1: how much darker the background gets towards the frame's edges
    floor: float = 0.0  # 0 to 1: a soft shadow on the floor under the album
    reflection: bool = False  # the case mirrored on the floor under it (case layout)
    intro: float = 0.0  # seconds of a full-frame title card at the start, ended by the first line
    opening: bool = True  # in a long intro the title and the artist show in the lyric panel
    drift: bool = True  # a soft light drifts slowly over the frame
    lead: float = 0.0  # seconds of silence before the song starts
    tail: float = 0.0  # seconds of silence after the song ends
    shape: str = "wide"  # wide (16:9) or one of UPRIGHT: tall (9:16), square (1:1), portrait (4:5)
    loop: bool = False  # upright: the end blends into the start, so it repeats without a seam
    # upright loop: the video ends with this many seconds of the song before clip_from, so its last
    # moment runs into its first (tall.lead); with loop_lead_line, the line sung just before the clip.
    loop_lead: float = 0.0
    loop_lead_line: bool = False
    clip_from: float = 0.0  # upright: the part of the song the video holds, in song seconds
    clip_to: float = 0.0  # 0 is the end of the song
    bars: bool = False  # upright: solid bands across the top and the bottom
    bars_colour: str = "#000000"
    bars_height: float = 0.12  # each band's share of the frame height
    bars_top: str = ""  # a short text on the top band
    bars_bottom: str = ""
    bars_size: int = 48  # px of the band texts
    highlight: str = "line"  # upright: line, or letter to light only the letter being sung
    upright_look: str = "cover"  # upright: cover, or disc for the turning CD behind the lyrics
    disc_wear: str = "none"  # upright disc: none, or worn for peeled paint and faint scratches
    # Over the user's own video (Song.video), any shape: its first frame goes with the start of
    # the song (of a Short's part) moved by video_offset seconds; a shorter video starts again
    # (loop) or holds its last frame (hold); video_sound takes its sound instead of the song's.
    video_offset: float = 0.0
    video_end: str = "loop"
    video_sound: bool = False
    video_ink: str = "#ffffff"  # the text over the video
    video_lit: str = "#ffd23f"  # the letter being sung, with highlight=letter
    video_edge: str = "shadow"  # shadow | none
    video_band: str = "none"  # none | paper | dark, behind the lines
    video_band_alpha: float = 0.85
    # Where the lines go: bottom | middle | low (lower, where a Short's caption can cover them).
    video_text: str = "bottom"

    @classmethod
    def from_dict(cls, data: dict) -> Style:
        names = {f.name for f in fields(cls)}
        kept = {}
        for key, value in data.items():
            if key not in names:
                continue
            default = getattr(cls, key)
            kept[key] = type(default)(value) if not isinstance(default, bool) else bool(value)
        return replace(cls(), **kept)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Song:
    audio: str
    art: str
    title: str
    artist: str = ""
    duration: float = 0.0
    anim: tuple[str, ...] = ()  # the moving picture: one GIF or images in order
    video: str = ""  # the user's video, drawn in place of the cover (overlay.py)
    lead: float = 0.0  # seconds of silence the video has before the audio starts; in duration
    tail: float = 0.0  # seconds of silence after the audio; in duration
    # When each letter is sung, per line: (line start, line text, one time per letter but spaces).
    letters: tuple[tuple[float, str, tuple[float, ...]], ...] = ()
    album: str = ""  # the player look's line under the title; empty: the title as a single
    released: str = ""  # the player look's badge on the cover, as typed (2026.06.23); empty: none


def band_rgb(style: Style) -> tuple[int, int, int]:
    return hex_rgb(style.band)


def hex_rgb(colour: str) -> tuple[int, int, int]:
    h = colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def scaled_box(box: tuple[int, int, int, int], s: float, dx: int, dy: int) -> tuple[int, ...]:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return (
        round(cx + (box[0] - cx) * s) + dx,
        round(cy + (box[1] - cy) * s) + dy,
        round(cx + (box[2] - cx) * s) + dx,
        round(cy + (box[3] - cy) * s) + dy,
    )


@dataclass(frozen=True)
class Geometry:
    case: tuple[int, ...]
    hinge: int
    inset: int
    disc_r: int
    disc_x: int  # the case CD's centre once slid out
    round_c: tuple[int, int]
    round_r: int
    panel: tuple[int, ...]
    row: float
    title: tuple[int, int, float]  # centre x, top y, scale
    bar: tuple[int, ...]


@lru_cache(maxsize=64)
def geometry(style: Style) -> Geometry:
    s = style.album_scale
    case = scaled_box(CASE, s, style.album_x, style.album_y)
    inset, disc_r = round(INSET * s), round(CASE_DISC_R * s)
    # The CD stops with its hole just behind the opaque cover, so a bit less than half of it shows.
    disc_x = case[2] - inset - round(disc_r * HOLE) - round(6 * s)
    round_c = (round(DISC_C[0] + style.album_x), round(DISC_C[1] + style.album_y))
    return Geometry(
        case=case,
        hinge=round(HINGE * s),
        inset=inset,
        disc_r=disc_r,
        disc_x=disc_x,
        round_c=round_c,
        round_r=round(DISC_R * s),
        panel=scaled_box(
            PLAYER_PANEL if style.layout == "player" else PANEL,
            style.panel_scale,
            style.panel_x,
            style.panel_y,
        ),
        row=(PLAYER_ROW if style.layout == "player" else ROW) * style.panel_scale,
        title=(W // 2 + style.title_x, style.title_y, style.title_scale),
        bar=scaled_box(BAR, style.bar_scale, style.bar_x, style.bar_y),
    )


@dataclass(frozen=True)
class Tilt:
    """The album turned about the upright line through its centre and seen from a fixed distance.
    A flat drawing of `region` (frame pixels) is warped into `box`; a plane seen in perspective is a
    homography, so the four corners fix it. The view is scaled so the nearest edge keeps its flat
    size: the album only shrinks, never grows past its flat place, the lyrics or the CD's turn box."""

    region: tuple[int, int, int, int]
    box: tuple[int, int, int, int]
    centre: tuple[float, float]
    cos: float
    sin: float
    near: float  # TILT_DISTANCE plus the nearest edge's depth: that edge is drawn at scale 1
    coeffs: tuple[float, ...]  # Pillow's PERSPECTIVE data: box pixel -> region pixel

    def point(self, x: float, y: float) -> tuple[float, float]:
        u, v = x - self.centre[0], y - self.centre[1]
        k = self.near / (TILT_DISTANCE + u * self.sin)
        return self.centre[0] + u * self.cos * k, self.centre[1] + v * k

    def bounds(self, box: tuple[int, ...]) -> tuple[int, int, int, int]:
        """The frame box that holds `box` once tilted."""
        pts = [self.point(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return math.floor(min(xs)), math.floor(min(ys)), math.ceil(max(xs)), math.ceil(max(ys))

    def over(self, region: tuple[int, ...]) -> Tilt:
        """The same tilt, warping another flat region of the album's plane (its reflection)."""
        box = self.bounds(region)
        rows, rhs = [], []
        for x in (region[0], region[2]):
            for y in (region[1], region[3]):
                px, py = self.point(x, y)
                px, py, fx, fy = px - box[0], py - box[1], x - region[0], y - region[1]
                rows += [
                    [px, py, 1, 0, 0, 0, -fx * px, -fx * py],
                    [0, 0, 0, px, py, 1, -fy * px, -fy * py],
                ]
                rhs += [fx, fy]
        coeffs = tuple(float(c) for c in np.linalg.solve(np.array(rows), np.array(rhs)))
        return replace(self, region=tuple(region), box=box, coeffs=coeffs)

    def apply(self, flat: Image.Image, part: tuple[int, ...] | None = None) -> Image.Image:
        """`flat`, the size of region, warped: all of box, or only the frame box `part` of it. In
        premultiplied alpha, so the transparent pixels around the album do not darken its edges."""
        part = part or self.box
        a, b, c, d, e, f, g, h = self.coeffs
        dx, dy = part[0] - self.box[0], part[1] - self.box[1]
        w = g * dx + h * dy + 1
        shifted = (
            a / w, b / w, (a * dx + b * dy + c) / w,
            d / w, e / w, (d * dx + e * dy + f) / w,
            g / w, h / w,
        )  # fmt: skip
        size = (part[2] - part[0], part[3] - part[1])
        # Only the flat pixels the part reads are converted and sampled, with the bicubic's reach.
        a, b, c, d, e, f, g, h = shifted
        xs, ys = [], []
        for px in (0, size[0]):
            for py in (0, size[1]):
                w = g * px + h * py + 1
                xs.append((a * px + b * py + c) / w)
                ys.append((d * px + e * py + f) / w)
        ix, iy = max(0, math.floor(min(xs)) - 3), max(0, math.floor(min(ys)) - 3)
        crop = (
            ix,
            iy,
            min(flat.width, math.ceil(max(xs)) + 3),
            min(flat.height, math.ceil(max(ys)) + 3),
        )
        shifted = (a - ix * g, b - ix * h, c - ix, d - iy * g, e - iy * h, f - iy, g, h)
        source = flat.crop(crop).convert("RGBa")
        warped = source.transform(size, Image.PERSPECTIVE, shifted, Image.BICUBIC)
        return warped.convert("RGBA")


@lru_cache(maxsize=16)
def tilt_of(style: Style) -> Tilt | None:
    """The album's tilt, or None when it faces the viewer."""
    angle = max(-TILT_MAX, min(TILT_MAX, style.tilt))
    if abs(angle) < 0.05 or style.layout == "player":
        return None
    g = geometry(style)
    if style.layout == "case":
        cy = (g.case[1] + g.case[3]) / 2
        centre = ((g.case[0] + g.case[2]) / 2, cy)
        # Wide enough for the CD at every point of its slide out of the case.
        region = (
            g.case[0],
            min(g.case[1], math.floor(cy - g.disc_r)),
            max(g.case[2], g.disc_x + g.disc_r),
            max(g.case[3], math.ceil(cy + g.disc_r)),
        )
    else:
        (cx, cy), r = g.round_c, g.round_r
        centre, region = (cx, cy), (cx - r, cy - r, cx + r, cy + r)
    region = (region[0] - 2, region[1] - 2, region[2] + 2, region[3] + 2)
    rad = math.radians(angle)
    sin = math.sin(rad)
    near = TILT_DISTANCE + min((region[0] - centre[0]) * sin, (region[2] - centre[0]) * sin)
    return Tilt(region, region, centre, math.cos(rad), sin, near, ()).over(region)


def tilted_shadow(
    layer: Image.Image, at: tuple[int, int], drop: tuple[int, int], blur: int, alpha: int
):
    """A frame-size shadow of a tilted album's outline, moved by `drop`."""
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mask = layer.getchannel("A").point(lambda v: alpha if v else 0)
    shade.paste((0, 0, 0, 255), (at[0] + drop[0], at[1] + drop[1]), mask)
    return shade.filter(ImageFilter.GaussianBlur(blur))


def disc_centre_x(g: Geometry, t: float) -> float:
    """Where the case CD's centre is at time t: inside the case until SLIDE, then sliding out."""
    inside = (g.case[0] + g.case[2]) // 2
    return inside + (g.disc_x - inside) * ease((t - SLIDE[0]) / (SLIDE[1] - SLIDE[0]))


def boxes(
    style: Style, t: float = SLIDE[1], song: Song | None = None
) -> dict[str, tuple[int, ...]]:
    """The frame area of each movable element at time t, for the drag handles on the preview; the
    moving picture's needs the song, which names its files. A Short and the text over a video
    have none to drag."""
    if is_upright(style) or (song is not None and song.video):
        return {}
    if style.layout == "player":
        from . import player

        return player.boxes(style)
    g = geometry(style)
    if style.layout == "case":
        right = (
            max(g.case[2], round(disc_centre_x(g, t)) + g.disc_r) if style.show_cd else g.case[2]
        )
        album = (g.case[0], g.case[1], right, g.case[3])
    else:
        cx, cy = g.round_c
        album = (cx - g.round_r, cy - g.round_r, cx + g.round_r, cy + g.round_r)
    if tilted := tilt_of(style):
        album = tilted.bounds(album)
    t = g.title[2]
    title = (
        round(g.title[0] - 600 * t),
        round(g.title[1] + 55 * t),
        round(g.title[0] + 600 * t),
        round(g.title[1] + 185 * t),
    )
    out = {"album": album, "panel": g.panel}
    if style.show_title:
        out["title"] = title
    if style.bar:
        out["bar"] = g.bar
    if (
        song is not None
        and song.anim
        and (found := anim.at(song.anim, style.anim_fps, style.anim_scale))
    ):
        out["anim"] = anim.box(found[0].size, style.anim_x, style.anim_y)
    return out


def overlaps(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


MILK = (196, 200, 206, 255)  # the colour the case's plastic greys things towards


def haze(img: Image.Image, box: tuple[int, ...], amount: float) -> None:
    """What lies under the case in box, softened by 1.2 px and greyed by `amount` towards MILK, as
    clear plastic does; the cover is laid on after, so this shows only around it."""
    x0, y0 = max(0, box[0]), max(0, box[1])
    x1, y1 = min(img.width, box[2]), min(img.height, box[3])
    if amount <= 0 or x1 <= x0 or y1 <= y0:
        return
    under = img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(1.2))
    under = Image.blend(under, Image.new("RGBA", under.size, MILK), min(amount, 1.0))
    mask = Image.new("L", (box[2] - box[0], box[3] - box[1]), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), 6, fill=255)
    mask = mask.crop((x0 - box[0], y0 - box[1], x1 - box[0], y1 - box[1]))
    img.paste(under, (x0, y0), mask)


def place(dst: Image.Image, src: Image.Image, x: int, y: int) -> None:
    """alpha_composite that accepts a position partly or wholly outside the frame."""
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(src.width, dst.width - x), min(src.height, dst.height - y)
    if right <= left or bottom <= top:
        return
    if (left, top, right, bottom) != (0, 0, src.width, src.height):
        src = src.crop((left, top, right, bottom))
    dst.alpha_composite(src, (x + left, y + top))


@lru_cache(maxsize=512)
def font(path: str, size: float, weight: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    try:
        axes = f.get_variation_axes()
    except OSError:
        return f  # a static font has one weight
    values = []
    for axis in axes:
        name = axis.get("name", b"")
        if isinstance(name, bytes):
            name = name.decode("latin-1")
        if name.lower() == "weight":
            values.append(min(max(weight, axis["minimum"]), axis["maximum"]))
        else:
            values.append(axis["default"])
    f.set_variation_by_axes(values)
    return f


def tracked(
    draw: ImageDraw.ImageDraw,
    centre: tuple[float, float],
    text: str,
    f: ImageFont.FreeTypeFont,
    fill: tuple,
    tracking: float = TRACKING,
    stroke: float = 0,
    stroke_fill: tuple | None = None,
) -> None:
    """Text centred on ``centre`` with ``tracking`` em between letters (Pillow has no letter spacing),
    with an outline ``stroke`` px wide when asked."""
    gap = f.size * tracking
    widths = [f.getlength(ch) for ch in text]
    x = centre[0] - (sum(widths) + gap * (len(text) - 1)) / 2
    for ch, w in zip(text, widths, strict=True):
        draw.text(
            (x, centre[1]),
            ch,
            font=f,
            fill=fill,
            anchor="lm",
            stroke_width=stroke,
            stroke_fill=stroke_fill,
        )
        x += w + gap


def lettered(
    draw: ImageDraw.ImageDraw,
    centre: tuple[float, float],
    text: str,
    f: ImageFont.FreeTypeFont,
    alpha: int,
    style: Style,
    tracking: float = TRACKING,
) -> None:
    """``tracked`` text in the lyric colour, with the style's outline or shadow: the lyrics, the title
    and the artist share them so a light cover can be read in all three."""
    ink, rim = hex_rgb(style.lyric_colour), hex_rgb(style.lyric_edge_colour)
    if style.lyric_edge == "shadow":
        # A hard offset copy: a blur of the panel would cost more than the panel on each moving frame.
        drop = f.size * SHADOW_DROP
        x, y = centre
        tracked(draw, (x + drop, y + drop), text, f, (*rim, round(alpha * SHADOW_ALPHA)), tracking)
    if style.lyric_edge == "outline":
        stroke = max(1, round(f.size * OUTLINE_WIDTH))
        tracked(draw, centre, text, f, (*ink, alpha), tracking, stroke, (*rim, alpha))
    else:
        tracked(draw, centre, text, f, (*ink, alpha), tracking)


def text_width(text: str, f: ImageFont.FreeTypeFont, tracking: float = TRACKING) -> float:
    """The width ``tracked`` draws ``text`` at."""
    return sum(f.getlength(ch) for ch in text) + f.size * tracking * max(0, len(text) - 1)


def halves(text: str) -> tuple[str, str]:
    """Two rows of about equal length, broken at the space nearest the middle, or mid-word when the
    line has no space."""
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    at = min(spaces, key=lambda i: abs(i - len(text) / 2)) if spaces else len(text) // 2
    return text[:at].strip(), text[at:].strip()


@lru_cache(maxsize=1024)
def fit(
    text: str, face: str, size: float, room: float, row: float
) -> tuple[float, tuple[str, ...]]:
    """How a line fits the panel at the current-line size: a factor for the font size and the rows
    it is drawn in. One factor per line, used at every size of its move, keeps the move smooth."""
    f = font(face, size, NOW_WEIGHT)
    width = text_width(text, f)
    if width <= room:
        return 1.0, (text,)
    if room / width >= MIN_FIT:
        return round(room / width, 3), (text,)
    rows = halves(text)
    widest = max(text_width(r, f) for r in rows)
    tall = row * 0.85 / (2 * ROW_PITCH * size)  # two rows inside the band, with air
    return round(min(1.0, room / widest, tall), 3), rows


def panel_fit(style: Style) -> tuple[str, float, float, float]:
    """The font, current-line size, usable width and row height of the panel, in panel pixels."""
    g = geometry(style)
    k = style.panel_scale
    room = (g.panel[2] - g.panel[0] - 2 * (14 + 16) * k) * SS  # inside the band, with a margin
    return fonts.resolve(style.font), NOW_SIZE * k * SS, room, g.row * SS


def line_fits(lines: tuple[tuple[float, str], ...], style: Style) -> list[tuple[float, int]]:
    """For the page: each line's size factor and row count, so long lines can be marked."""
    face, size, room, row = panel_fit(style)
    out = []
    for _, text in lines:
        factor, rows = fit(text, face, size, room, row) if text else (1.0, (text,))
        out.append((factor, len(rows)))
    return out


@lru_cache(maxsize=2)
def square(path: str, art_stamp: float = 0.0) -> Image.Image:
    """The centre square of the cover. Cached and shared: callers must not draw on it."""
    art = Image.open(path).convert("RGB")
    side = min(art.size)
    return art.crop(
        (
            (art.width - side) // 2,
            (art.height - side) // 2,
            (art.width + side) // 2,
            (art.height + side) // 2,
        )
    )


def circle_mask(size: int, inner: float = 0.0, outer: float = 1.0) -> Image.Image:
    """An anti-aliased ring mask: 255 between inner and outer (fractions of the radius)."""
    big = size * 2
    mask = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(mask)
    r = big / 2
    d.ellipse((r - r * outer, r - r * outer, r + r * outer - 1, r + r * outer - 1), fill=255)
    if inner:
        d.ellipse((r - r * inner, r - r * inner, r + r * inner, r + r * inner), fill=0)
    return mask.resize((size, size), Image.LANCZOS)


TONES = ("none", "warm", "cool", "mono", "cover")
# Channel mixes for the warm and cool tones, as the 12 numbers Image.convert takes (R, G, B rows).
WARM = (1.08, 0.04, 0, 0, 0, 1.0, 0, 0, 0, 0, 0.86, 0)
COOL = (0.88, 0, 0, 0, 0, 1.0, 0.02, 0, 0, 0.04, 1.1, 0)


@lru_cache(maxsize=2)
def cover_colour(path: str, art_stamp: float = 0.0) -> tuple[int, int, int]:
    """The cover's own colour: of its five main colours, the one with the most area times saturation,
    so a small grey border or a dark corner does not win over the colour people see."""
    small = square(path, art_stamp).convert("RGB").resize((64, 64))
    pal = small.quantize(5, method=Image.Quantize.MEDIANCUT)
    rgb = pal.getpalette()

    def weight(item: tuple[int, int]) -> float:
        count, k = item
        _, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in rgb[k * 3 : k * 3 + 3]))
        return count * (sat * val + 0.05)

    k = max(pal.getcolors(), key=weight)[1]
    return tuple(rgb[k * 3 : k * 3 + 3])


def toned(bg: Image.Image, tone: str, path: str, art_stamp: float) -> Image.Image:
    if tone == "warm":
        return bg.convert("RGB", WARM)
    if tone == "cool":
        return bg.convert("RGB", COOL)
    if tone == "mono":
        return ImageOps.grayscale(bg).convert("RGB")
    if tone == "cover":
        colour = cover_colour(path, art_stamp)
        lift = 255 / max(max(colour), 1)
        return ImageOps.colorize(
            ImageOps.grayscale(bg), (0, 0, 0), tuple(round(c * lift) for c in colour)
        )
    return bg


@lru_cache(maxsize=2)
@lru_cache(maxsize=2)
def vignette_mask(strength: float) -> Image.Image:
    """Multiplier for the background: 1 in the middle, falling smoothly to 1 - 0.85 x strength at the
    corners. Elliptical, so it follows the 16:9 frame."""
    y, x = np.ogrid[0:H, 0:W]
    d = np.hypot((x - W / 2) / (W / 2), (y - H / 2) / (H / 2)) / math.sqrt(2)
    u = np.clip((d - 0.35) / 0.65, 0, 1)
    fall = u * u * (3 - 2 * u)
    mask = (1 - 0.85 * strength * fall) * 255
    return Image.fromarray(mask.astype(np.uint8), "L").convert("RGB")


@lru_cache(maxsize=2)
def backdrop(
    path: str, art_stamp: float, blur: int, dim: float, tone: str = "none", vignette: float = 0.0
) -> Image.Image:
    """The cover filling the frame, blurred and darkened. It does not depend on where anything is placed,
    so moving the album or the lyrics on the preview does not redo it. Shared: callers copy it."""
    art = square(path, art_stamp)
    scale = max(W / art.width, H / art.height)
    bg = art.resize((math.ceil(art.width * scale), math.ceil(art.height * scale)), Image.LANCZOS)
    bg = bg.crop(
        (
            (bg.width - W) // 2,
            (bg.height - H) // 2,
            (bg.width - W) // 2 + W,
            (bg.height - H) // 2 + H,
        )
    )
    if blur > 0:
        bg = bg.filter(ImageFilter.GaussianBlur(blur))
    bg = toned(bg.convert("RGB"), tone, path, art_stamp)
    if vignette > 0:
        bg = ImageChops.multiply(bg, vignette_mask(min(vignette, 1.0)))
    return Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), dim).convert("RGBA")


def background(song: Song, style: Style, art_stamp: float = 0.0) -> Image.Image:
    g = geometry(style)
    face = fonts.resolve(style.font)
    bg = backdrop(song.art, art_stamp, style.blur, style.dim, style.tone, style.vignette).copy()
    cx, top, s = g.title
    if not style.show_title:
        return Image.alpha_composite(bg, panel_layer(g, style))
    box = round(TITLE_BOX * s)
    text = Image.new("RGBA", (W * SS, box * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(text)
    lettered(
        d,
        (W * SS / 2, TITLE_Y * s * SS),
        song.title,
        font(face, 58 * s * SS, 600),
        255,
        style,
        0.06,
    )
    if song.artist:
        lettered(
            d,
            (W * SS / 2, ARTIST_Y * s * SS),
            song.artist,
            font(face, 26 * s * SS, 400),
            165,
            style,
            0.18,
        )
    place(bg, text.resize((W, box), Image.LANCZOS), cx - W // 2, top)
    return Image.alpha_composite(bg, panel_layer(g, style))


@lru_cache(maxsize=2)
def intro_card(song: Song, style: Style, art_stamp: float = 0.0) -> Image.Image:
    """The opening card: the background a little darker, the title and the artist large in the middle."""
    face = fonts.resolve(style.font)
    bg = backdrop(song.art, art_stamp, style.blur, style.dim, style.tone, style.vignette)
    card = Image.blend(bg, Image.new("RGBA", (W, H), (0, 0, 0, 255)), 0.3)
    text = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(text)
    title = font(face, 104 * SS, 700)
    while text_width(song.title, title, 0.04) > W * 0.86 * SS and title.size > 40 * SS:
        title = font(face, title.size * 0.92, 700)
    y = H / 2 - (30 if song.artist else 0)
    lettered(d, (W * SS / 2, y * SS), song.title, title, 255, style, 0.04)
    if song.artist:
        lettered(
            d, (W * SS / 2, (y + 96) * SS), song.artist, font(face, 40 * SS, 400), 190, style, 0.2
        )
    return Image.alpha_composite(card, text.resize((W, H), Image.LANCZOS))


def intro_end(lines: tuple[tuple[float, str], ...], style: Style) -> float:
    """When the opening card is gone: after style.intro seconds, or at the first line if sooner."""
    if style.intro <= 0:
        return 0.0
    return min(style.intro, lines[0][0]) if lines else style.intro


def veil(t: float, end: float) -> float:
    """How much of the opening card covers the frame at t: 1, then down to 0 over the last INTRO_FADE."""
    if t >= end:
        return 0.0
    return round(min(1.0, (end - t) / INTRO_FADE), 3)


def opening_steps(
    lines: tuple[tuple[float, str], ...], style: Style
) -> tuple[tuple[float, float], ...] | None:
    """When the title comes in and goes in a long intro, or None: no opening, the full-frame card of
    style.intro instead, or an intro shorter than OPENING_LEAST."""
    if not (style.opening and style.intro <= 0 and lines and lines[0][1]):
        return None
    first = lines[0][0]
    if first < OPENING_LEAST:
        return None
    k = first / OPENING_FOR
    return tuple((a * k, b * k) for a, b in OPENING)


def opening_at(t: float, steps: tuple[tuple[float, float], ...] | None) -> float:
    """How much of the title in the panel shows at t."""
    if steps is None:
        return 0.0
    (a, b), (c, d) = steps
    return round(ease((t - a) / (b - a)) * (1 - ease((t - c) / (d - c))), 2)


@lru_cache(maxsize=2)
def opening_panel(song: Song, style: Style) -> Image.Image:
    """The title and the artist large in the lyric panel, for a long intro."""
    g = geometry(style)
    k = style.panel_scale
    face = fonts.resolve(style.font)
    pw, ph = (g.panel[2] - g.panel[0]) * SS, (g.panel[3] - g.panel[1]) * SS
    layer = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    room = pw - 2 * 48 * k * SS
    title = font(face, 72 * k * SS, 700)
    while text_width(song.title, title, 0.04) > room and title.size > 30 * k * SS:
        title = font(face, title.size * 0.92, 700)
    # A light grey of the lyric colour rather than the colour itself, which reads as too bright
    # this large in a still panel: #D2D2D2 and #B4B4B4 for white.
    rows = [(song.title, title, 210, 0.04, 0.0)]
    if song.artist:
        rows.append((song.artist, font(face, 32 * k * SS, 400), 180, 0.14, 86 * k * SS))
    top = ph / 2 - rows[-1][4] / 2
    ink = hex_rgb(style.lyric_colour)
    for text, f, level, tracking, dy in rows:
        grey = "#{:02x}{:02x}{:02x}".format(*(round(c * level / 255) for c in ink))
        lettered(d, (pw / 2, top + dy), text, f, 255, replace(style, lyric_colour=grey), tracking)
    return layer.reduce(SS)


def faded(layer: Image.Image, share: float) -> Image.Image:
    """The layer with its alpha scaled by share."""
    out = layer.copy()
    out.putalpha(layer.getchannel("A").point(lambda v: round(v * share)))
    return out


def light_at(t: float) -> tuple[int, int]:
    """Where the drifting light's centre is at t: wandering over the middle of the frame."""
    px, py = LIGHT_PERIODS
    x = W * (0.5 + 0.25 * math.sin(2 * math.pi * t / px))
    y = H * (0.42 + 0.2 * math.sin(2 * math.pi * t / py + 1.0))
    return round(x), round(y)


@lru_cache(maxsize=1)
def whole_light() -> Image.Image:
    """The light centred on a frame twice the video's size, built once: every frame's light is a
    window of it (light)."""
    gx = np.exp(-(((np.arange(2 * W) - W) / LIGHT_SIGMA) ** 2) / 2)
    gy = np.exp(-(((np.arange(2 * H) - H) / LIGHT_SIGMA) ** 2) / 2)
    glow = np.outer(gy, gx)[..., None] * (np.array([1.0, 0.93, 0.85]) * LIGHT_PEAK)
    rgba = np.zeros((2 * H, 2 * W, 4), np.uint8)
    rgba[..., :3] = np.rint(glow).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def light(centre: tuple[int, int]) -> Image.Image:
    """A soft warm light around centre, to add to a frame: RGB levels, no alpha."""
    x, y = W - centre[0], H - centre[1]
    return whole_light().crop((x, y, x + W, y + H))


def panel_layer(g: Geometry, style: Style) -> Image.Image:
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle(
        g.panel, radius=round(20 * style.panel_scale), fill=(0, 0, 0, 105)
    )
    return panel


def floor_shadow(box: tuple[int, ...], s: float, strength: float) -> Image.Image:
    """A wide, soft oval on the floor under an album whose box is (x0, y0, x1, y1)."""
    x0, _, x1, y1 = box
    pad, depth = round((x1 - x0) * 0.08), round(34 * s)
    oval = (x0 - pad, y1 - depth // 2, x1 + pad, y1 + depth)
    return shadow(oval, round(26 * s), round(200 * min(strength, 1.0)), True)


def reflection(layer: Image.Image, box: tuple[int, ...], s: float) -> Image.Image:
    """The bottom 45 % of the album in box, mirrored under it and fading out."""
    x0, _, _, y1 = box
    gap = round(4 * s)
    part = layer.crop(box).transpose(Image.FLIP_TOP_BOTTOM)
    part = part.crop((0, 0, part.width, min(round(part.height * 0.45), H - y1 - gap)))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if part.height <= 0:
        return out
    fade = np.linspace(0.32, 0.0, part.height)[:, None] * np.ones((1, part.width))
    alpha = np.asarray(part.getchannel("A"), dtype=float) * fade
    part.putalpha(Image.fromarray(alpha.astype(np.uint8), "L"))
    place(out, part, x0, y1 + gap)
    return out


def shadow(box: tuple[int, ...], blur: int, alpha: int, round_: bool = False) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    (d.ellipse if round_ else d.rectangle)(box, fill=(0, 0, 0, alpha))
    return layer.filter(ImageFilter.GaussianBlur(blur))


@lru_cache(maxsize=4)
def silver(radius: int) -> Image.Image:
    """The bare disc: silver with an angular sheen that stays put while the print turns, as light on a
    real CD."""
    size = radius * 2
    y, x = np.mgrid[0:size, 0:size] - (size - 1) / 2
    angle, dist = np.arctan2(y, x), np.hypot(x, y) / radius
    sheen = 178 + 38 * np.cos(2 * angle + 0.6) + 16 * np.cos(6 * angle + 1.3) - 18 * dist
    rgb = np.dstack([sheen, sheen + 2, sheen + 6]).clip(0, 255).astype("uint8")
    return Image.fromarray(rgb, "RGB").convert("RGBA")


def disc_print(art: Image.Image, radius: int) -> Image.Image:
    size = radius * 2
    face = art.resize((size, size), Image.LANCZOS).convert("RGBA")
    face.putalpha(circle_mask(size, 0.36, 0.975).point(lambda v: v * 236 // 255))
    return face


class Disc:
    """A CD: silver, the print from disc_print turned clockwise, a clear inner ring, a centre hole and a
    thin silver rim. Only the print turns, so everything else is drawn once; the rings replace the
    pixels under them, as ImageDraw does, through a mask of exactly those pixels."""

    def __init__(self, face: Image.Image, radius: int):
        size = radius * 2
        self.face = face
        self.silver = silver(radius)
        self.rings = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        self.ring_mask = Image.new("L", (size, size), 0)
        rings, mask = ImageDraw.Draw(self.rings), ImageDraw.Draw(self.ring_mask)
        for frac, colour, width in (
            (0.36, (225, 228, 235, 160), 2),
            (0.33, (120, 124, 132, 120), 1),
            (0.17, (235, 238, 244, 140), 2),
        ):
            r = radius * frac
            box = (radius - r, radius - r, radius + r, radius + r)
            rings.ellipse(box, outline=colour, width=width)
            mask.ellipse(box, outline=255, width=width)
        self.rim = Image.new("RGBA", (size, size), (206, 210, 218, 255))
        self.rim.putalpha(circle_mask(size, 0.982, 1.0))
        self.hole = circle_mask(size, HOLE, 1.0)

    def at(self, turn: float) -> Image.Image:
        """The disc turned by `turn` degrees clockwise."""
        disc = self.silver.copy()
        disc.alpha_composite(self.face.rotate(-turn, Image.BICUBIC))
        disc.paste(self.rings, (0, 0), self.ring_mask)
        disc.alpha_composite(self.rim)
        disc.putalpha(ImageChops.multiply(disc.getchannel("A"), self.hole))
        return disc


def jewel_case(art: Image.Image, g: Geometry, s: float) -> Image.Image:
    """The cover in a clear case: spine with ridges on the left, edge highlights, a soft diagonal
    reflection."""
    x0, y0, x1, y1 = g.case
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cover = (x0 + g.hinge, y0 + g.inset, x1 - g.inset, y1 - g.inset)
    side = cover[2] - cover[0]
    place(layer, art.resize((side, cover[3] - cover[1]), Image.LANCZOS).convert("RGBA"), *cover[:2])
    plastic = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(plastic)
    d.rounded_rectangle(g.case, radius=6, fill=(255, 255, 255, 16))
    d.rectangle((x0, y0, x0 + g.hinge - 4, y1), fill=(255, 255, 255, 22))
    for k, a in ((6, 90), (12, 50), (19, 110), (26, 45), (33, 80)):
        k = round(k * s)
        d.line((x0 + k, y0 + 4, x0 + k, y1 - 4), fill=(255, 255, 255, a), width=1)
    d.rounded_rectangle(g.case, radius=6, outline=(255, 255, 255, 150), width=2)
    d.rectangle(
        (cover[0] - 3, cover[1] - 3, cover[2] + 3, cover[3] + 3),
        outline=(255, 255, 255, 55),
        width=1,
    )
    d.line((x0 + 8, y0 + 1, x1 - round(40 * s), y0 + 1), fill=(255, 255, 255, 200), width=2)
    d.line((x1 - 1, y0 + 10, x1 - 1, y0 + (y1 - y0) // 2), fill=(255, 255, 255, 160), width=2)
    hinge = round(12 * s)
    for yy in (y0 + 10, y1 - round(22 * s)):
        d.rectangle((x0 + 2, yy, x0 + hinge, yy + hinge), outline=(255, 255, 255, 90), width=1)
    yy, xx = np.mgrid[0 : y1 - y0, 0 : x1 - x0]
    u = (xx * 0.62 + yy * 0.78) / ((x1 - x0) * 0.62 + (y1 - y0) * 0.78)
    gloss = 34 * np.exp(-(((u - 0.33) / 0.09) ** 2)) + 16 * np.exp(-(((u - 0.47) / 0.025) ** 2))
    sheet = Image.new("RGBA", (x1 - x0, y1 - y0), (255, 255, 255, 0))
    sheet.putalpha(Image.fromarray(gloss.clip(0, 255).astype("uint8"), "L"))
    place(plastic, sheet, x0, y0)
    layer.alpha_composite(plastic)
    return layer


def offset_box(box: tuple[int, ...], dx: int, dy: int, grow: int = 0) -> tuple[int, ...]:
    return (box[0] + dx, box[1] + dy, box[2] + dx + grow, box[3] + dy + grow)


@lru_cache(maxsize=8)
def scene(song: Song, style: Style, art_stamp: float = 0.0) -> tuple:
    """The still layers: (background, the case CD's print or None, case or None)."""
    g = geometry(style)
    s = style.album_scale
    art = square(song.art, art_stamp)
    bg = background(song, style, art_stamp)
    if style.layout == "case":
        x0, y0, x1, y1 = g.case
        case = jewel_case(art, g, s)
        tilted = tilt_of(style)
        if style.reflection:
            mirror = reflection(case, g.case, s)
            if tilted and (ref := mirror.getbbox()):
                # The mirror image stands in the album's plane under it, so the same tilt turns it.
                turned = tilted.over(ref)
                flat, mirror = mirror.crop(ref), Image.new("RGBA", (W, H), (0, 0, 0, 0))
                place(mirror, turned.apply(flat), *turned.box[:2])
            bg = Image.alpha_composite(bg, mirror)
        if style.floor > 0:
            foot = tilted.bounds(g.case) if tilted else g.case
            bg = Image.alpha_composite(bg, floor_shadow(foot, s, style.floor))
        if tilted:
            flat = case.crop(tilted.region)
            shade = tilted_shadow(
                tilted.apply(flat),
                tilted.box[:2],
                (round(8 * s), round(19 * s)),
                round(18 * s),
                140,
            )
        else:
            drop = (x0 + round(8 * s), y0 + round(16 * s), x1 + round(8 * s), y1 + round(22 * s))
            shade = shadow(drop, round(18 * s), 140)
        return Image.alpha_composite(bg, shade), disc_print(art, g.disc_r), case
    under, disc, at = round_album(song, style, art_stamp)
    bg = under.copy()
    place(bg, disc, *at)
    return bg, None, None


@lru_cache(maxsize=2)
def round_album(song: Song, style: Style, art_stamp: float = 0.0) -> tuple:
    """The round layout's background with the disc's shadow, the disc, and where it goes."""
    g, s = geometry(style), style.album_scale
    r = g.round_r
    disc = square(song.art, art_stamp).resize((r * 2, r * 2), Image.LANCZOS).convert("RGBA")
    disc.putalpha(circle_mask(r * 2))
    cx, cy = g.round_c
    at = (cx - r, cy - r)
    foot = (cx - r, cy - r, cx + r, cy + r)
    if tilted := tilt_of(style):
        flat = Image.new(
            "RGBA", (tilted.region[2] - tilted.region[0], tilted.region[3] - tilted.region[1])
        )
        flat.paste(disc, (at[0] - tilted.region[0], at[1] - tilted.region[1]))
        disc, at = tilted.apply(flat), tilted.box[:2]
        foot = tilted.bounds(foot)
        shade = tilted_shadow(disc, at, (0, round(10 * s)), round(14 * s), 120)
    else:
        drop = (
            cx - r - round(6 * s),
            cy - r + round(4 * s),
            cx + r + round(6 * s),
            cy + r + round(16 * s),
        )
        shade = shadow(drop, round(14 * s), 120, True)
    bg = background(song, style, art_stamp)
    if style.floor > 0:
        bg = Image.alpha_composite(bg, floor_shadow(foot, s, style.floor))
    bg = Image.alpha_composite(bg, shade)
    return bg, disc, at


def ease(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * u * (u * (6 * u - 15) + 10)


@lru_cache(maxsize=4)
def moves(times: tuple[float, ...]) -> tuple[tuple[float, float], ...]:
    """(start, length) of the move onto each line: centred on its start, at most SCROLL, and inside the
    time between the previous line's move and the line itself, so a fast pair of lines never overlaps."""
    out, done = [], -math.inf
    for i, s in enumerate(times):
        gap = s - times[i - 1] if i else SCROLL * 2
        length = min(SCROLL, 0.8 * gap)
        start = max(s - length / 2, done)
        length = max(0.05, min(length, s + length / 2 - start))
        out.append((start, length))
        done = start + length
    return tuple(out)


def position(t: float, times: tuple[float, ...], intro: float) -> float:
    """The list's row at time t. Before the first line it sits below the panel, so the intro shows an
    empty panel, then rises over ENTER seconds, ending where the move onto the first line would end."""
    if not times:
        return intro
    (start, length), *rest = moves(times)
    end = start + length
    enter = min(ENTER, end)
    if t < end:
        return intro * (1 - ease((t - end + enter) / enter))
    pos = 0.0
    for i, (start, length) in enumerate(rest, 1):
        if t < start:
            break
        pos = i - 1 + ease((t - start) / length)
    return pos


def panel_position(t: float, lines: tuple[tuple[float, str], ...], style: Style) -> float:
    """The lyric list's row at time t; the panel is drawn from this alone."""
    g = geometry(style)
    intro = -((g.panel[3] - g.panel[1]) / 2 / g.row) - 0.1  # every line below the panel
    return position(t, tuple(s for s, _ in lines), intro)


def lyric_panel(t: float, lines: tuple[tuple[float, str], ...], style: Style) -> Image.Image:
    return panel_at(panel_position(t, lines, style), lines, style)


# Between two moves the list stands still for seconds and the panel is the same picture, so the
# last few are kept; 840x720 RGBA is 2.4 MB each.
@lru_cache(maxsize=4)
def panel_at(pos: float, lines: tuple[tuple[float, str], ...], style: Style) -> Image.Image:
    g = geometry(style)
    k_scale = style.panel_scale
    x0, y0, x1, y1 = g.panel
    pw, ph = (x1 - x0) * SS, (y1 - y0) * SS
    layer = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    row = g.row
    mid = ph / 2
    face, now, room, row_px = panel_fit(style)

    def filled(k: int) -> float:
        return 1.0 if 0 <= k < len(lines) and lines[k][1] else 0.0

    lo = math.floor(pos)
    band = filled(lo) + (filled(lo + 1) - filled(lo)) * (pos - lo)
    if band > 0:
        pad = 14 * k_scale
        d.rounded_rectangle(
            (pad * SS, mid - row * SS / 2, pw - pad * SS, mid + row * SS / 2),
            radius=10 * k_scale * SS,
            fill=(*band_rgb(style), int(BAND_ALPHA * band)),
        )
    for k in range(max(0, lo - math.ceil(VISIBLE)), min(len(lines), lo + math.ceil(VISIBLE) + 2)):
        text = lines[k][1]
        if not text:
            continue
        off = k - pos
        near = max(0.0, 1 - abs(off))
        dim = max(0.0, 1 - (max(abs(off), 1) - 1) / (VISIBLE - 1)) * 150
        y = mid + off * row * SS
        edge_px = EDGE * k_scale * SS
        edge = min(1.0, max(0.0, y / edge_px), max(0.0, (ph - y) / edge_px))
        alpha = int((dim + (255 - dim) * near) * edge)
        if alpha <= 0:
            continue
        factor, rows = fit(text, face, now, room, row_px)
        size = round((DIM_SIZE + (NOW_SIZE - DIM_SIZE) * near) * k_scale * SS * factor * 2) / 2
        weight = round((DIM_WEIGHT + (NOW_WEIGHT - DIM_WEIGHT) * near) / 25) * 25
        f = font(face, size, weight)
        pitch = size * ROW_PITCH
        for n, part in enumerate(rows):
            at = y + (n - (len(rows) - 1) / 2) * pitch
            lettered(d, (pw / 2, at), part, f, alpha, style)
    # Averaging each 2x2 block takes 8 ms where LANCZOS took 37 ms, and this runs on every frame of a
    # move; the panel differs from LANCZOS by about one level of 255 on average (PSNR about 47 dB).
    return layer.reduce(SS)


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def progress_bar(t: float, song: Song, style: Style) -> Image.Image:
    g = geometry(style)
    x0, y0, x1, y1 = g.bar
    w, h = (x1 - x0) * SS, (y1 - y0) * SS
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    s = style.bar_scale
    f = font(fonts.resolve(style.font), 20 * s * SS, 500)
    label = 70 * s * SS
    track_h = 6 * s * SS
    left, right, mid = label, w - label, h / 2
    d.rounded_rectangle(
        (left, mid - track_h / 2, right, mid + track_h / 2),
        radius=track_h / 2,
        fill=(255, 255, 255, 60),
    )
    share = min(1.0, max(0.0, t / song.duration)) if song.duration else 0.0
    if share > 0:
        d.rounded_rectangle(
            (left, mid - track_h / 2, left + (right - left) * share, mid + track_h / 2),
            radius=track_h / 2,
            fill=(*band_rgb(style), 235),
        )
    d.text((label - 14 * s * SS, mid), clock(t), font=f, fill=(255, 255, 255, 200), anchor="rm")
    d.text(
        (right + 14 * s * SS, mid),
        clock(song.duration),
        font=f,
        fill=(255, 255, 255, 200),
        anchor="lm",
    )
    return layer.resize((x1 - x0, y1 - y0), Image.LANCZOS)


def forget_art() -> None:
    """Drop every cached layer made from the cover, after a new cover is saved under the same name."""
    for cached in (square, backdrop, cover_colour, scene, round_album):
        cached.cache_clear()
    from . import player

    player.forget()


def stamp(path: str) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


TURNS_MB = 192  # one turn of the CD shared by the workers; a bigger CD is drawn for every frame


def rate(style: Style) -> int:
    return style.fps if style.fps in RATES else FPS


def is_upright(style: Style) -> bool:
    """Drawn by tall.py: a Short or a square or 4:5 frame, rather than the wide 16:9 one."""
    return style.shape in UPRIGHT


def frame_size(style: Style) -> tuple[int, int]:
    """The size frames are drawn at: 1920x1080, or the upright shape's. None has more bytes than
    the wide frame, so every frame fits a FRAME slot."""
    return UPRIGHT.get(style.shape, (W, H))


def turn_set(style: Style) -> tuple[tuple[int, int, int, int], int] | None:
    """The frame box of the CD once it is out of the case, and the frames one turn takes, when one
    turn is a whole number of frames and its pictures fit in TURNS_MB."""
    if is_upright(style) or style.layout != "case" or not style.show_cd or style.spin <= 0:
        return None
    period = style.spin * rate(style)
    if abs(period - round(period)) > 1e-6:
        return None
    g = geometry(style)
    cy, r = (g.case[1] + g.case[3]) // 2, g.disc_r
    box = (g.disc_x - r, cy - r, g.disc_x + r, cy + r)
    if tilted := tilt_of(style):
        # Two pixels more each way for the bicubic warp's reach.
        box = tilted.bounds((box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2))
    box = (max(0, box[0]), max(0, box[1]), min(W, box[2]), min(H, box[3]))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    if (box[2] - box[0]) * (box[3] - box[1]) * 3 * round(period) > TURNS_MB * 2**20:
        return None
    return box, round(period)


def turns_bytes(box: tuple[int, ...], period: int) -> int:
    return (box[2] - box[0]) * (box[3] - box[1]) * 3 * period + period


class Turns:
    """The frame inside the CD's box for each frame of one turn, in memory the workers share. The
    worker that first needs a picture draws it and marks it done; the others copy it."""

    def __init__(self, name: str, box: tuple[int, ...], period: int):
        self.memory = shared_memory.SharedMemory(name=name)
        self.box, self.period = box, period
        self.size = (box[2] - box[0], box[3] - box[1])
        self.entry = self.size[0] * self.size[1] * 3

    def get(self, n: int, draw) -> Image.Image:
        # No view into the memory outlives this call, so the worker can close it at exit.
        k = n % self.period
        buf, done = self.memory.buf, self.period * self.entry + k
        with buf[k * self.entry : (k + 1) * self.entry] as view:
            if not buf[done]:
                # Two workers may draw the same picture at once; they write the same bytes.
                view[:] = draw().tobytes()
                buf[done] = 1
            return Image.frombytes("RGB", self.size, view)


class Painter:
    """The frames of one song and style. A frame is a function of three things: where the CD is and
    how far it has turned, the lyric list's row, and the playback bar. Everything else is drawn once
    here, and a frame whose three things equal the previous frame's is that frame again."""

    def __init__(
        self,
        lines: tuple[tuple[float, str], ...],
        song: Song,
        style: Style,
        shared: str | None = None,
        moving: tuple[str, anim.Timing] | None = None,
    ):
        self.lines, self.song, self.style = lines, song, style
        self.g = g = geometry(style)
        stamped = stamp(song.art)
        bg, face, case = scene(song, style, stamped)
        self.disc = self.case = self.turns = self.over = None
        self.hazed = 0.0  # case_haze where it applies: a tilted case keeps its plastic clear
        self.timing = self.pictures = None
        if moving:
            self.timing, self.pictures = moving[1], anim.Shared(*moving)
        elif song.anim and (found := anim.at(song.anim, style.anim_fps, style.anim_scale)):
            self.timing, self.pictures = found
        if self.timing:
            self.anim_box = anim.box(self.timing.size, style.anim_x, style.anim_y)
        # A picture under the album that overlaps it must be drawn before the album, so the album
        # cannot stay in the background or come from the shared turn.
        under = self.timing is not None and not style.anim_above
        tucked = under and overlaps(self.anim_box, boxes(style)["album"])
        self.tilt = tilt_of(style)
        if case is not None:
            box = case.getbbox() or (0, 0, 1, 1)
            self.case, self.case_at = case.crop(box), box[:2]
            if self.tilt:
                # The case alone, tilted, for frames without a CD and for the still around a turn.
                self.case_flat = case.crop(self.tilt.region)
                case_only = (self.tilt.apply(self.case_flat), *self.tilt.box[:2])
            else:
                case_only = (self.case, *self.case_at)
                self.hazed = style.case_haze
            if style.show_cd:
                self.disc = Disc(face, g.disc_r)
            elif tucked:
                self.over = case_only
            else:
                bg = bg.copy()
                haze(bg, g.case, self.hazed)
                place(bg, *case_only)
        elif tucked:
            bg, disc, at = round_album(song, style, stamped)
            self.over = (disc, *at)
        self.bg = bg
        self.intro = intro_end(lines, style)
        self.card = intro_card(song, style, stamped) if self.intro > 0 else None
        self.steps = opening_steps(lines, style)
        self.opening = opening_panel(song, style) if self.steps else None
        if shared and self.disc is not None and not tucked and (turning := turn_set(style)):
            self.turns = Turns(shared, *turning)
            # Outside the CD's box a turning frame is the background and the case, always.
            self.still = bg.copy()
            haze(self.still, g.case, self.hazed)
            place(self.still, *case_only)
        self.last: tuple = (None, b"")

    def state(self, t: float) -> tuple:
        cover = veil(t, self.intro)
        if cover == 1:
            return (
                None,
                None,
                None,
                None,
                1.0,
                0.0,
                None,
            )  # the card hides the frame: every such frame is the same
        disc = None
        if self.disc is not None:
            disc = (
                round(disc_centre_x(self.g, t)),
                360 * t / self.style.spin if self.style.spin > 0 else 0.0,
            )
        # The bar's fill grows by a fraction of a pixel each frame, so with it no two frames match.
        bar = t if self.style.bar else None
        picture = self.timing.index(t) if self.timing else None
        title = opening_at(t, self.steps)
        glow = light_at(t) if self.style.drift else None
        return disc, panel_position(t, self.lines, self.style), bar, picture, cover, title, glow

    def image(self, t: float, state: tuple | None = None) -> Image.Image:
        """The frame at t, RGBA."""
        disc, pos, bar, picture, cover, title, glow = state or self.state(t)
        if cover == 1:
            return self.card.copy()
        g = self.g
        if disc is not None and self.turns is not None and disc[0] == g.disc_x:
            img = self.still.copy()
            box = self.turns.box
            img.paste(
                self.turns.get(round(t * rate(self.style)), lambda: self.cd_box(*disc, box)),
                box[:2],
            )
            disc = None  # drawn
        else:
            img = self.bg.copy()
        if picture is not None and not self.style.anim_above:
            place(img, self.pictures[picture], *self.anim_box[:2])
        if disc is not None:
            self.draw_cd(img, *disc, (0, 0))
        elif self.over:
            place(img, *self.over)
        place(img, panel_at(pos, self.lines, self.style), *g.panel[:2])
        if title > 0:
            place(img, faded(self.opening, title), *g.panel[:2])
        if bar is not None:
            place(img, progress_bar(t, self.song, self.style), *g.bar[:2])
        if picture is not None and self.style.anim_above:
            place(img, self.pictures[picture], *self.anim_box[:2])
        if cover > 0:
            img = Image.blend(img, self.card, cover)
        if glow is not None:
            img = ImageChops.add(img, light(glow))
        return img

    def draw_cd(self, img: Image.Image, x: int, turn: float, origin: tuple[int, int]) -> None:
        """The CD at x, turned, and the case over it, into img whose top left is `origin` of the frame."""
        g = self.g
        cy = (g.case[1] + g.case[3]) // 2
        if self.tilt:
            # Drawn flat, then tilted as one: CD and case share the perspective.
            r0 = self.tilt.region
            flat = Image.new("RGBA", self.case_flat.size, (0, 0, 0, 0))
            place(flat, self.disc.at(turn), x - g.disc_r - r0[0], cy - g.disc_r - r0[1])
            flat.alpha_composite(self.case_flat)
            # Only the part img covers is warped: a turn picture is a small box of the frame.
            b0 = self.tilt.box
            part = (
                max(b0[0], origin[0]),
                max(b0[1], origin[1]),
                min(b0[2], origin[0] + img.width),
                min(b0[3], origin[1] + img.height),
            )
            if part[2] > part[0] and part[3] > part[1]:
                place(img, self.tilt.apply(flat, part), part[0] - origin[0], part[1] - origin[1])
            return
        place(img, self.disc.at(turn), x - g.disc_r - origin[0], cy - g.disc_r - origin[1])
        haze(img, offset_box(g.case, -origin[0], -origin[1]), self.hazed)
        place(img, self.case, self.case_at[0] - origin[0], self.case_at[1] - origin[1])

    def cd_box(self, x: int, turn: float, box: tuple[int, ...]) -> Image.Image:
        """The frame inside box with the CD at x, turned: background, CD, case."""
        region = self.bg.crop(box)
        self.draw_cd(region, x, turn, box[:2])
        return region.convert("RGB")

    def raw(self, t: float) -> bytes:
        """The frame at t as RGBA bytes for ffmpeg."""
        state = self.state(t)
        if state == self.last[0]:
            return self.last[1]
        raw = self.image(t, state).tobytes()
        self.last = (state, raw)
        return raw


_painters: dict = {}


def painter(
    lines: tuple[tuple[float, str], ...],
    song: Song,
    style: Style,
    shared: str | None = None,
    moving: tuple[str, anim.Timing] | None = None,
) -> Painter:
    """The painter for these inputs, kept while scene() still returns the same layers (the page
    clears scene's cache when a file is replaced) and the moving picture's files are unchanged."""
    if song.video:
        from . import overlay

        return overlay.painter(lines, song, style)
    if is_upright(style):
        from . import tall

        return tall.painter(lines, song, style)
    if style.layout == "player":
        from . import player

        return player.painter(lines, song, style, moving)
    layers = scene(song, style, stamp(song.art))
    key = (lines, song, style, shared, moving, anim.stamps(song.anim))
    found = _painters.get(key)
    if found is None or found[0] is not layers:
        if len(_painters) >= 2:
            _painters.pop(next(iter(_painters)))
        panel_at.cache_clear()  # a font file replaced under the same name
        found = _painters[key] = (layers, Painter(lines, song, style, shared, moving))
    return found[1]


def frame(t: float, lines: tuple[tuple[float, str], ...], song: Song, style: Style) -> Image.Image:
    return painter(lines, song, style).image(t).convert("RGB")


_attached: dict[str, shared_memory.SharedMemory] = {}


def attached(name: str) -> shared_memory.SharedMemory:
    if name not in _attached:
        _attached[name] = shared_memory.SharedMemory(name=name)
    return _attached[name]


def render_chunk(args) -> list[int]:
    """Draw frames start..stop into the chunk's slots of the shared frame memory and say which slot
    holds each frame. Pickling 8 MB frames back to the main process cost more than drawing them."""
    start, stop, step, lines, song, style, turns, moving, frames, first = args
    p = painter(lines, song, style, turns, moving)
    fps = rate(style)
    buf = attached(frames).buf
    slots, slot, last = [], first - 1, None
    for n in range(start, stop, step):
        raw = p.raw(n / fps)
        if raw is not last:
            slot += 1
            with buf[slot * FRAME : slot * FRAME + len(raw)] as view:
                view[:] = raw
            last = raw
        slots.append(slot)
    return slots


def render(
    out: Path,
    lines: tuple[tuple[float, str], ...],
    song: Song,
    style: Style,
    workers: int,
    span: tuple[float, float] | None = None,
    report=print,
    quick: bool = False,
    note=print,
) -> str:
    """Write the mp4. As chunks finish, `report(done_seconds, total_seconds, frames_done,
    frames_total, seconds_left)` is called; seconds_left is None until there is a rate to go by.
    `quick` makes a small clip at half the frame rate to look at in the page.
    When memory runs out, the render starts again with less (`steps`), and `note` says how (#12).
    Returns what the user should know about the video: ANIM_DROPPED and SMALLER, or "" when it is
    as asked."""
    codec = "libx264" if quick else media.encoder()
    upright = is_upright(style)
    if song.video:
        from . import overlay

        # The video is the picture: no moving picture over it.
        song = replace(song, anim=())
        if style.video_sound and not overlay.has_sound(song.video):
            raise ValueError("배경 영상에 소리가 없습니다. 노래 소리를 쓰도록 바꿉니다.")
    if upright:
        from . import tall

        # A Short is the clip at 1080x1920 without the moving picture; there is no smaller size.
        song = replace(song, anim=())
        # Only the whole clip ends with the lead, not a part of it to look at.
        lead = tall.lead(style, song, lines) if span is None else 0.0
        span = span or tall.span(style, song)
    else:
        lead = 0.0
        lines, song = padded(lines, song, style)
    smaller = not quick and not upright and not HEIGHTS.get(style.height)
    tries = steps(workers, bool(song.anim), smaller)
    for k, (count, shared, moving, small) in enumerate(tries):
        part = song if moving else replace(song, anim=())
        look = replace(style, height=720) if small else style
        try:
            try:
                encode(out, lines, part, look, count, span, report, codec, quick, shared, lead)
            except RuntimeError:
                if codec == "libx264":
                    raise
                # A graphics driver can pass the short test and still fail on a whole song.
                codec = "libx264"
                encode(out, lines, part, look, count, span, report, codec, quick, shared, lead)
            told = [ANIM_DROPPED] if song.anim and not moving else []
            return " ".join([*told, SMALLER] if small else told)
        except Exception as e:
            if k + 1 == len(tries) or not out_of_memory(e):
                raise
            count, shared, moving, small = tries[k + 1]
            how = (
                "at 720p"
                if small
                else "without the moving picture"
                if not moving
                else "the CD turn drawn on each frame, any moving picture loaded in the worker"
                if not shared
                else ""
            )
            note(
                f"memory short ({type(e).__name__}: {e}): again with {count} worker(s)"
                + (f", {how}" if how else "")
            )


ANIM_DROPPED = "메모리가 부족해 움직이는 그림 없이 만들었습니다."
SMALLER = "메모리가 부족해 720p로 만들었습니다."


def steps(
    workers: int, anim: bool = False, smaller: bool = False
) -> list[tuple[int, bool, bool, bool]]:
    """The tries when memory runs short, as (workers, shared blocks, moving picture, 720p): the
    workers halved down to one; then one worker without shared blocks, which draws the CD turn on
    each frame and loads the moving picture itself; then, when there is one, without the moving
    picture. With `smaller`, a 1080p video gets the leanest try once more at 720p, whose encoder
    needs about half the memory (a 60 s part: 1080p failed under 650 MB of commit, 720p ran in 330)."""
    counts = [max(1, workers)]
    while counts[-1] > 1:
        counts.append(counts[-1] // 2)
    tries = [(n, True, True, False) for n in counts] + [(1, False, True, False)]
    if anim:
        tries.append((1, False, False, False))
    if smaller:
        tries.append((*tries[-1][:3], True))
    return tries


# Windows: ERROR_NOT_ENOUGH_MEMORY, ERROR_COMMITMENT_LIMIT (the paging file is too small).
WIN_MEMORY = (8, 1455)


# What ffmpeg and x264 write when an allocation fails.
FFMPEG_MEMORY = ("Cannot allocate memory", "malloc of size")


def ffmpeg_failure(code: int, said: str) -> Exception:
    """The error for an ffmpeg that stopped before the last frame. Out of memory it can take the
    failed read as the end of the input and exit 0 with a short video, so a frame not taken counts
    whatever the code; an allocation failure is a MemoryError for the steps of `render` (#15)."""
    lines = said.strip().splitlines()
    text = f"ffmpeg 오류 (종료 코드 {code}): " + " / ".join(lines[-3:])
    if any(word in said for word in FFMPEG_MEMORY):
        return MemoryError(text)
    return RuntimeError(text)


def out_of_memory(e: BaseException) -> bool:
    """A failure that less memory could avoid: Python out of memory, a worker killed (on this PC
    almost always for memory), or the system refusing to commit more."""
    if isinstance(e, MemoryError | BrokenProcessPool):
        return True
    return isinstance(e, OSError) and (
        getattr(e, "winerror", None) in WIN_MEMORY or e.errno == errno.ENOMEM
    )


def room_for(mb: float) -> bool:
    """Whether shared blocks of `mb` leave half the memory that can still be committed for the
    workers and the encoder; True where that cannot be read."""
    commit = media.commit_mb()
    return commit is None or mb <= commit / 2


FADE_IN, FADE_OUT = 0.5, 1.5  # seconds


def padded(
    lines: tuple[tuple[float, str], ...], song: Song, style: Style
) -> tuple[tuple[tuple[float, str], ...], Song]:
    """The lines and the song on the video's own clock: style.lead seconds of silence first, the lines
    moved later by as much, and style.tail seconds of silence at the end. The project keeps song times."""
    if song.lead or song.tail or (style.lead <= 0 and style.tail <= 0):
        return lines, song
    lead, tail = max(0.0, style.lead), max(0.0, style.tail)
    moved = tuple((t + lead, text) for t, text in lines)
    return moved, replace(song, duration=song.duration + lead + tail, lead=lead, tail=tail)


def video_time(t: float, style: Style) -> float:
    """Where a moment of the song falls in the video. The song's start shows the video's start, so a
    preview at 0 shows the silence before the song."""
    return t + max(0.0, style.lead) if t > 0 else 0.0


def fades(style: Style, duration: float, first: float, last: float) -> tuple[list[str], list[str]]:
    """ffmpeg's video and audio filters for the fade from and to black and silence, on the part of
    the song from first to last: the fade in only when it holds the start, the fade out only when it
    holds the end. Times are within the part."""
    vf: list[str] = []
    af: list[str] = []
    if is_upright(style):
        # A Short starts on the line it is about: no fade from black, a short one in the sound so the
        # cut does not click. A loop's end blends into its start instead of fading out.
        from . import tall

        length = last - first
        af.append(f"afade=t=in:st=0:d={tall.AUDIO_FADE}")
        if not style.loop:
            af.append(
                f"afade=t=out:st={max(0.0, length - tall.AUDIO_FADE):.3f}:d={tall.AUDIO_FADE}"
            )
        return vf, af
    if not style.fade:
        return vf, af
    if first <= 0.0:
        vf.append(f"fade=t=in:st=0:d={FADE_IN}")
        af.append(f"afade=t=in:st=0:d={FADE_IN}")
    if last >= duration - 1e-3:
        start = max(0.0, last - first - FADE_OUT)
        vf.append(f"fade=t=out:st={start:.3f}:d={FADE_OUT}")
        af.append(f"afade=t=out:st={start:.3f}:d={FADE_OUT}")
    return vf, af


def encode(
    out: Path,
    lines: tuple[tuple[float, str], ...],
    song: Song,
    style: Style,
    workers: int,
    span: tuple[float, float] | None,
    report,
    codec: str,
    quick: bool = False,
    shared: bool = True,
    lead: float = 0.0,
) -> None:
    first, last = (0.0, song.duration) if span is None else span
    fps = rate(style)
    end = last
    if lead:
        from . import tall

        end = last + lead - tall.LOOP  # past the clip's end by the lead less the blend (tall.lead)
    length = end - first
    begin, total = round(first * fps), math.ceil(end * fps)
    step = QUICK_STEP if quick else 1
    vf, af = fades(style, song.duration, first, last)
    # The audio's own clock is behind the video's by song.lead; the silence before it is a delay and
    # the silence after it is padding up to the part's length.
    heard = first - song.lead
    if song.lead or song.tail:
        af[:0] = [*([f"adelay={round(-heard * 1000)}:all=1"] if heard < 0 else []), "apad"]
    size = frame_size(style)
    upright = is_upright(style)
    if not quick and not upright and HEIGHTS.get(style.height):
        vf.insert(0, "scale={}:{}".format(*HEIGHTS[style.height]))
    if quick:
        quick_w = size[0] * QUICK_SIZE[0] // W if upright else QUICK_SIZE[0]
        vf.append(f"scale={quick_w}:-2")
        codec_args = ["-c:v", "libx264", *QUICK_X264]
    else:
        codec_args = ["-c:v", codec, *media.ENCODERS[codec]]
    video = [*(["-vf", ",".join(vf)] if vf else []), *codec_args]
    audio = ["-af", ",".join(af)] if af else []
    sound, before = ["-map", "1:a"], []
    overlap = 0.0
    if upright:
        from . import tall

        overlap = tall.loop_length(style, song)
    if song.video and style.video_sound:
        overlap = 0.0  # the video's own sound has no moments before the clip to mix in
    if lead:
        from . import tall

        # The song before the clip comes in under the clip's end and plays to the sample before the
        # clip's first; no fade at the file's start or end (tall.lead_graph).
        before = ["-ss", f"{max(0.0, heard - lead):.3f}", "-t", f"{lead:.3f}", "-i", song.audio]
        graph = tall.lead_graph(last - first, lead)
        sound, audio, overlap = ["-map", "[sound]"], ["-filter_complex", graph], 0.0
    if overlap:
        # The moments before the clip, mixed into its end (tall.loop_graph); the fade in stays on
        # the start, which the end now leads into.
        before = [
            "-ss",
            f"{max(0.0, heard - overlap):.3f}",
            "-t",
            f"{overlap:.3f}",
            "-i",
            song.audio,
        ]
        graph = tall.loop_graph(last - first, overlap)
        graph = graph.replace("[1:a]", f"[1:a]{','.join(af)},") if af else graph
        sound, audio = ["-map", "[sound]"], ["-filter_complex", graph]
    shown, under = ["-map", "0:v"], []
    if song.video:
        from . import overlay

        # The video comes last; ffmpeg lays the text layer (input 0) over it, then the fades.
        n = 3 if before else 2
        opts, picture, heard_video = overlay.inputs(style, song, first, fps // step)
        under = opts
        graph = f"[{n}:v]{picture}[under];[under][0:v]overlay=0:0:format=auto:shortest=1"
        graph += ("," + ",".join(vf) if vf else "") + "[shown]"
        if style.video_sound:
            graph += f";[{n}:a]{heard_video}" + ("," + ",".join(af) if af else "") + "[sound]"
            sound, audio = ["-map", "[sound]"], []
        if audio and audio[0] == "-filter_complex":
            graph += ";" + audio[1]
        elif audio:
            graph += ";[1:a]" + audio[1] + "[sound]"
            sound = ["-map", "[sound]"]
        shown, video, audio = ["-map", "[shown]"], codec_args, ["-filter_complex", graph]
    cmd = [
        media.ffmpeg(),
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        "{}x{}".format(*size),
        "-r",
        str(fps // step),
        "-i",
        "-",
        "-ss",
        f"{max(0.0, heard):.3f}",
        "-t",
        f"{last - first:.3f}",
        "-i",
        song.audio,
        *before,
        *under,
        *shown,
        *sound,
        *video,
        "-pix_fmt",
        "yuv420p",
        *audio,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{length:.3f}",
        "-movflags",
        "+faststart",
        str(out),
    ]
    # Only `ahead` chunks are in flight, each with its own slots, so memory stays flat however long
    # the song is; a chunk's slots are free again once the main process has written them out.
    ahead = workers + 1
    ring = ahead * CHUNK * FRAME
    turning = turn_set(style) if shared and not song.video else None
    if turning and not room_for((turns_bytes(*turning) + ring) / 2**20):
        turning = None  # each worker draws the CD turn itself
    turns = pictures = moving = frames = None
    try:
        if turning:
            size, period = turns_bytes(*turning), turning[1]
            turns = shared_memory.SharedMemory(create=True, size=size)
            turns.buf[size - period : size] = bytes(period)  # no picture drawn yet
        if song.anim and shared:
            # Uncached: the parent keeps only the shared copy.
            found = anim.frames.__wrapped__(
                song.anim, anim.stamps(song.anim), style.anim_fps, style.anim_scale
            )
            if found:
                pictures = anim.share(*found)
                moving = (pictures.name, found[0])
                del found
        frames = shared_memory.SharedMemory(create=True, size=ring)
    except BaseException:
        # A block made before the one that failed would hold its memory through the next try.
        for memory in (turns, pictures):
            if memory:
                memory.close()
                memory.unlink()
        raise
    span_n = CHUNK * step
    frame_bytes = math.prod(frame_size(style)) * 4
    chunks = [
        (
            s,
            min(total, s + span_n),
            step,
            lines,
            song,
            style,
            turns and turns.name,
            moving,
            frames.name,
            0,
        )
        for s in range(begin, total, span_n)
    ]
    count = len(range(begin, total, step))
    started = time.monotonic()
    try:
        with (
            tempfile.TemporaryFile() as errors,
            subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errors, **media.quiet()) as ff,
            ProcessPoolExecutor(workers) as pool,
        ):

            def submit(k: int):
                return pool.submit(render_chunk, (*chunks[k][:-1], (k % ahead) * CHUNK))

            waiting = deque(submit(k) for k in range(min(ahead, len(chunks))))
            written = 0
            for k in range(len(chunks)):
                slots = waiting.popleft().result()
                try:
                    for slot in slots:
                        with frames.buf[slot * FRAME : slot * FRAME + frame_bytes] as view:
                            ff.stdin.write(view)
                        written += 1
                except OSError:
                    break
                if k + ahead < len(chunks):
                    waiting.append(submit(k + ahead))
                done = len(range(begin, chunks[k][1], step))
                spent = time.monotonic() - started
                left = (count - done) * spent / done if k >= 2 else None
                report((chunks[k][1] - begin) / fps, (total - begin) / fps, done, count, left)
            try:
                ff.stdin.close()
            except OSError:
                pass
            ff.wait()
            if ff.returncode or written != count:
                errors.seek(0)
                raise ffmpeg_failure(ff.returncode, errors.read().decode("utf-8", "replace"))
    finally:
        for memory in (turns, pictures, frames):
            if memory:
                memory.close()
                memory.unlink()
