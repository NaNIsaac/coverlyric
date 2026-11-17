"""Draw lyric-video frames with Pillow and pipe them to ffmpeg.

The left side holds the cover, either in a clear jewel case with a CD half out (the print turns, the case
stays still) or as a still round disc. The right side holds the lyric list, which moves one row per line
with a quintic ease and keeps the current line on a coloured band. Title, artist and an optional playback
bar sit on a blurred, darkened copy of the cover. Every element can be moved and scaled through `Style`;
the default style is the original look.
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, fields, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import fonts, media

W, H, FPS = 1920, 1080, 30
CHUNK = 8  # frames a worker renders at a time; one frame is 6 MB of raw pixels
SS = 2  # the lyric panel and title are drawn at twice the size and scaled down
DIM_WEIGHT, NOW_WEIGHT = 350, 600
DIM_SIZE, NOW_SIZE = 34, 44
TRACKING = 0.04  # extra space between letters, in em

DISC_C, DISC_R = (560, 610), 330
CASE = (110, 318, 714, 902)
HINGE = 40
INSET = 12  # between the case edge and the printed cover inside it
CASE_DISC_R = 262
HOLE = 0.075  # centre hole radius, as a fraction of the disc radius
SLIDE = (0.3, 1.9)  # seconds: the disc slides out of the case once
PANEL = (1010, 250, 1850, 970)
ROW = 92
SCROLL = 0.45
ENTER = 1.2  # seconds the list takes to rise into the empty panel for the first line
VISIBLE = 3.4
EDGE = 70
BAND_ALPHA = 165
TITLE_Y, ARTIST_Y, TITLE_BOX = 100, 162, 240
BAR = (110, 1000, 1850, 1040)


@dataclass(frozen=True)
class Style:
    """Everything the user can change. Offsets are in pixels of the 1920x1080 frame; scales are factors."""

    layout: str = "case"  # case | disc
    font: str = fonts.DEFAULT
    band: str = "#c49668"
    blur: int = 30
    dim: float = 0.5
    spin: float = 7.0  # seconds per turn of the case's CD; 0 keeps it still
    show_cd: bool = True  # the case layout's CD half out of the case
    album_x: int = 0
    album_y: int = 0
    album_scale: float = 1.0
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


def band_rgb(style: Style) -> tuple[int, int, int]:
    h = style.band.lstrip("#")
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
        panel=scaled_box(PANEL, style.panel_scale, style.panel_x, style.panel_y),
        row=ROW * style.panel_scale,
        title=(W // 2 + style.title_x, style.title_y, style.title_scale),
        bar=scaled_box(BAR, style.bar_scale, style.bar_x, style.bar_y),
    )


def disc_centre_x(g: Geometry, t: float) -> float:
    """Where the case CD's centre is at time t: inside the case until SLIDE, then sliding out."""
    inside = (g.case[0] + g.case[2]) // 2
    return inside + (g.disc_x - inside) * ease((t - SLIDE[0]) / (SLIDE[1] - SLIDE[0]))


def boxes(style: Style, t: float = SLIDE[1]) -> dict[str, tuple[int, ...]]:
    """The frame area of each movable element at time t, for the drag handles on the preview."""
    g = geometry(style)
    if style.layout == "case":
        right = (
            max(g.case[2], round(disc_centre_x(g, t)) + g.disc_r) if style.show_cd else g.case[2]
        )
        album = (g.case[0], g.case[1], right, g.case[3])
    else:
        cx, cy = g.round_c
        album = (cx - g.round_r, cy - g.round_r, cx + g.round_r, cy + g.round_r)
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
    return out


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
) -> None:
    """Text centred on ``centre`` with ``tracking`` em between letters (Pillow has no letter spacing)."""
    gap = f.size * tracking
    widths = [f.getlength(ch) for ch in text]
    x = centre[0] - (sum(widths) + gap * (len(text) - 1)) / 2
    for ch, w in zip(text, widths, strict=True):
        draw.text((x, centre[1]), ch, font=f, fill=fill, anchor="lm")
        x += w + gap


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


@lru_cache(maxsize=2)
def backdrop(path: str, art_stamp: float, blur: int, dim: float) -> Image.Image:
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
    return Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), dim).convert("RGBA")


def background(song: Song, style: Style, art_stamp: float = 0.0) -> Image.Image:
    g = geometry(style)
    face = fonts.resolve(style.font)
    bg = backdrop(song.art, art_stamp, style.blur, style.dim).copy()
    cx, top, s = g.title
    if not style.show_title:
        return Image.alpha_composite(bg, panel_layer(g, style))
    box = round(TITLE_BOX * s)
    text = Image.new("RGBA", (W * SS, box * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(text)
    tracked(
        d,
        (W * SS / 2, TITLE_Y * s * SS),
        song.title,
        font(face, 58 * s * SS, 600),
        (255, 255, 255, 255),
        0.06,
    )
    if song.artist:
        tracked(
            d,
            (W * SS / 2, ARTIST_Y * s * SS),
            song.artist,
            font(face, 26 * s * SS, 400),
            (255, 255, 255, 165),
            0.18,
        )
    place(bg, text.resize((W, box), Image.LANCZOS), cx - W // 2, top)
    return Image.alpha_composite(bg, panel_layer(g, style))


def panel_layer(g: Geometry, style: Style) -> Image.Image:
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle(
        g.panel, radius=round(20 * style.panel_scale), fill=(0, 0, 0, 105)
    )
    return panel


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


def printed_disc(face: Image.Image, radius: int, turn: float = 0.0) -> Image.Image:
    """A CD: silver, the print from disc_print turned by `turn` degrees clockwise, a clear inner ring, a
    centre hole and a thin silver rim."""
    size = radius * 2
    disc = silver(radius).copy()
    disc.alpha_composite(face.rotate(-turn, Image.BICUBIC))
    d = ImageDraw.Draw(disc)
    for frac, colour, width in (
        (0.36, (225, 228, 235, 160), 2),
        (0.33, (120, 124, 132, 120), 1),
        (0.17, (235, 238, 244, 140), 2),
    ):
        r = radius * frac
        d.ellipse((radius - r, radius - r, radius + r, radius + r), outline=colour, width=width)
    rim = Image.new("RGBA", (size, size), (206, 210, 218, 255))
    rim.putalpha(circle_mask(size, 0.982, 1.0))
    disc.alpha_composite(rim)
    disc.putalpha(ImageChops.multiply(disc.getchannel("A"), circle_mask(size, HOLE, 1.0)))
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
        drop = (x0 + round(8 * s), y0 + round(16 * s), x1 + round(8 * s), y1 + round(22 * s))
        bg = Image.alpha_composite(bg, shadow(drop, round(18 * s), 140))
        return bg, disc_print(art, g.disc_r), jewel_case(art, g, s)
    r = g.round_r
    disc = art.resize((r * 2, r * 2), Image.LANCZOS).convert("RGBA")
    disc.putalpha(circle_mask(r * 2))
    cx, cy = g.round_c
    drop = (
        cx - r - round(6 * s),
        cy - r + round(4 * s),
        cx + r + round(6 * s),
        cy + r + round(16 * s),
    )
    bg = Image.alpha_composite(bg, shadow(drop, round(14 * s), 120, True))
    place(bg, disc, cx - r, cy - r)
    return bg, None, None


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


def lyric_panel(t: float, lines: tuple[tuple[float, str], ...], style: Style) -> Image.Image:
    g = geometry(style)
    k_scale = style.panel_scale
    x0, y0, x1, y1 = g.panel
    pw, ph = (x1 - x0) * SS, (y1 - y0) * SS
    layer = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    row = g.row
    intro = -((y1 - y0) / 2 / row) - 0.1  # every line below the panel
    pos = position(t, tuple(s for s, _ in lines), intro)
    mid = ph / 2
    face = fonts.resolve(style.font)

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
        size = round((DIM_SIZE + (NOW_SIZE - DIM_SIZE) * near) * k_scale * SS * 2) / 2
        weight = round((DIM_WEIGHT + (NOW_WEIGHT - DIM_WEIGHT) * near) / 25) * 25
        tracked(d, (pw / 2, y), text, font(face, size, weight), (255, 255, 255, alpha))
    return layer.resize((x1 - x0, y1 - y0), Image.LANCZOS)


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
    for cached in (square, backdrop, scene):
        cached.cache_clear()


def stamp(path: str) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def frame(t: float, lines: tuple[tuple[float, str], ...], song: Song, style: Style) -> Image.Image:
    bg, disc, case = scene(song, style, stamp(song.art))
    img = bg.copy()
    g = geometry(style)
    if case is not None and not style.show_cd:
        img.alpha_composite(case)
    elif case is not None:
        cy = (g.case[1] + g.case[3]) // 2
        x = disc_centre_x(g, t)
        turn = 360 * t / style.spin if style.spin > 0 else 0.0
        turned = printed_disc(disc, g.disc_r, turn)
        place(img, turned, round(x) - g.disc_r, cy - g.disc_r)
        img.alpha_composite(case)
    place(img, lyric_panel(t, lines, style), *g.panel[:2])
    if style.bar:
        place(img, progress_bar(t, song, style), *g.bar[:2])
    return img.convert("RGB")


def render_chunk(args) -> list[bytes]:
    start, stop, lines, song, style = args
    return [frame(n / FPS, lines, song, style).tobytes() for n in range(start, stop)]


def render(
    out: Path,
    lines: tuple[tuple[float, str], ...],
    song: Song,
    style: Style,
    workers: int,
    span: tuple[float, float] | None = None,
    report=print,
) -> None:
    """Write the mp4. `report(done_seconds, total_seconds)` is called as chunks finish."""
    first, last = (0.0, song.duration) if span is None else span
    begin, total = round(first * FPS), math.ceil(last * FPS)
    cmd = [
        media.ffmpeg(),
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-ss",
        f"{first:.3f}",
        "-t",
        f"{last - first:.3f}",
        "-i",
        song.audio,
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-threads",
        "2",
        "-rc-lookahead",
        "10",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(out),
    ]
    chunks = [(s, min(total, s + CHUNK), lines, song, style) for s in range(begin, total, CHUNK)]
    ahead = workers + 1
    with (
        tempfile.TemporaryFile() as errors,
        subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errors, **media.quiet()) as ff,
        ProcessPoolExecutor(workers) as pool,
    ):
        # Only a few chunks are in flight, so memory stays flat however long the song is, even
        # when the encoder is slower than the workers.
        waiting = deque(pool.submit(render_chunk, c) for c in chunks[:ahead])
        for k in range(len(chunks)):
            frames = waiting.popleft().result()
            if k + ahead < len(chunks):
                waiting.append(pool.submit(render_chunk, chunks[k + ahead]))
            try:
                for raw in frames:
                    ff.stdin.write(raw)
            except OSError:
                break
            del frames
            report((chunks[k][1] - begin) / FPS, (total - begin) / FPS)
        try:
            ff.stdin.close()
        except OSError:
            pass
        ff.wait()
        if ff.returncode:
            errors.seek(0)
            said = errors.read().decode("utf-8", "replace").strip().splitlines()[-3:]
            raise RuntimeError(f"ffmpeg 오류 (종료 코드 {ff.returncode}): " + " / ".join(said))
