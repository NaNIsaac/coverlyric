"""Upright frames for phones: 9:16 for YouTube Shorts (1080x1920), 1:1 (1080x1080) and 4:5
(1080x1350). The title and the artist small at the top, the cover under them, the line being sung
large in the middle on a band and the next one small under it. In 9:16 the bottom fifth and the right
edge stay empty, as Shorts covers them with its own buttons and caption. Solid bands across the top
and the bottom, each with a short text, are optional; the rest fits between them."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from functools import lru_cache

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import fonts, render, timing

SHAPES = render.UPRIGHT
SUFFIX = {
    "tall": "_shorts",
    "square": "_1x1",
    "portrait": "_4x5",
}  # after the title in the file name
MIN_PIECE = 0.5  # seconds: a line cut this short at the clip's edge stays out of its subtitles
SAFE_BOTTOM = 0.2  # share of a Short's height covered by the caption and the music line
SAFE_RIGHT = 120  # px of a Short covered by the like, comment and share buttons
MARGIN = 60
REF = 1536  # the room the sizes below are for: a 9:16 frame less its bottom fifth
TITLE_Y, ARTIST_Y = 112, 162
COVER_SIDE, COVER_TOP = 440, 196
NOW_Y = 1040  # centre of the line being sung
NOW_PX, NEXT_PX, MIN_PX = 84, 48, 44
NEXT_GAP = 44
GONE_RISE = 160
MAX_ROWS = 3
PITCH = 1.18  # row distance in em
BAND_PAD = (30, 16)
BARS_MOST = 0.25  # a band takes at most this share of the height
CHANGE = 0.3  # seconds a new line takes to move up into the middle
LEAD_OUT, LEAD_IN = 0.9, 0.45  # loop_lead: the clip's fade out and the lead's fade in, seconds
MAX_BLOCK = 8  # the longest block of lines 후렴 찾기 compares
AUDIO_FADE = 0.3
START_RAMP = 0.01  # a looping Short's fade in: enough that the first play does not click
# highlight=letter: only the letter being sung is lit, in HIGHLIGHT and LETTER_POP times its size,
# growing over POP_IN seconds and going back as the next letter starts. The line is drawn at
# LETTER_PX with a shadow and no band; an outline and a band were too heavy around the lit letter.
HIGHLIGHT = "#ffd23f"
LETTER_PX = 106
LETTER_POP, POP_IN = 1.3, 0.1
# upright_look=disc: the 16:9 video's CD behind the line being sung, darkened by DISC_DIM so white
# letters read on its silver hub.
DISC_SIDE = 860
DISC_DIM = 0.4
WEAR_SEED = 11
MIN_BLEND = 0.05  # a loop blend shorter than this is none
# hook: the caption's px, weight and row pitch in em, and how much taller the top band gets; the
# picture moves down by that much and the bottom band gives the room.
HOOK_PX, HOOK_WEIGHT, HOOK_PITCH = 84, 800, 1.28
HOOK_SHIFT = 150

# What an upright shape sets; the colours, font and background stay as the user made them.
SHORTS = {"shape": "tall", "fps": 30, "lyric_edge": "outline", "intro": 0.0}


def shorts(style: render.Style, shape: str = "tall") -> render.Style:
    return replace(style, **{**SHORTS, "shape": shape})


def wide(style: render.Style) -> render.Style:
    return replace(style, shape="wide", fps=render.FPS)


@dataclass(frozen=True)
class Frame:
    """Where an upright frame's parts go: the room between the bands and a Short's covered edges
    (top to bottom, margin to right), and how much the 9:16 sizes above shrink to fit it."""

    w: int
    h: int
    top: int
    bottom: int
    margin: int
    right: int
    bar: int
    scale: float  # places and the cover
    text: float  # type, which shrinks half as much so it stays readable on a phone

    @property
    def cx(self) -> int:
        return (self.margin + self.right) // 2

    def y(self, v: float) -> float:
        return self.top + v * self.scale


@lru_cache(maxsize=16)
def _frame(shape: str, bars: bool, bars_height: float) -> Frame:
    w, h = SHAPES.get(shape, SHAPES["tall"])
    bar = round(h * min(max(bars_height, 0.0), BARS_MOST)) if bars else 0
    covered = round(h * SAFE_BOTTOM) if shape == "tall" else 0
    top, bottom = bar, h - max(bar, covered)
    right = w - (SAFE_RIGHT if shape == "tall" else MARGIN)
    scale = min(1.0, (bottom - top) / REF)
    return Frame(w, h, top, bottom, MARGIN, right, bar, scale, (1 + scale) / 2)


def frame_of(style: render.Style) -> Frame:
    return _frame(style.shape, style.bars, style.bars_height)


def span(style: render.Style, song: render.Song) -> tuple[float, float]:
    """The part of the song the video holds: clip_from to clip_to, a clip_to of 0 meaning the end,
    both kept inside the song."""
    end = song.duration
    first = min(max(0.0, style.clip_from), end)
    last = style.clip_to if style.clip_to > 0 else end
    last = min(max(first, last), end)
    return (first, last) if last > first else (0.0, end)


def cues(
    style: render.Style, song: render.Song, lines: list[timing.Line]
) -> tuple[list[timing.Cue], float]:
    """The upright video's subtitles on its own clock, and its length: the clip's lines, then with a
    loop lead the lead's lines from the blend on, as the picture shows them. A line cut to
    MIN_PIECE seconds or less at either edge is left out."""
    timed = sorted((t, text) for t, text in lines if t is not None)
    first, last = span(style, song)
    before = lead(style, song, tuple(timed))
    parts = [(first, last, 0.0)]
    if before:
        end = last - first - blend(style)
        parts = [(first, last - blend(style), 0.0), (first - before, first, end)]
    out = []
    for start, stop, at in parts:
        for a, b, text in timing.cues(timed, song.duration):
            a1, b1 = max(a, start), min(b, stop)
            if b1 - a1 > MIN_PIECE + 1e-6:
                out.append((round(a1 - start + at, 3), round(b1 - start + at, 3), text))
    start, stop, at = parts[-1]
    return sorted(out), at + stop - start


def blend(style: render.Style) -> float:
    """Seconds of a looping Short's end that blend into what comes before its start (loop_blend),
    for the picture, the sound and the subtitles alike; at least MIN_BLEND, so a loop lead always
    has a blend to come in under."""
    return max(MIN_BLEND, style.loop_blend)


def loop_length(style: render.Style, song: render.Song) -> float:
    """How much of the end blends into what comes before the start: loop_blend, less when the clip
    starts sooner than that, 0 without a loop."""
    if not style.loop:
        return 0.0
    first, _ = span(style, song)
    length = min(blend(style), first)
    return length if length >= MIN_BLEND else 0.0


def lead(style: render.Style, song: render.Song, lines: tuple[tuple[float, str], ...]) -> float:
    """How much of the song before the clip a looping Short ends with (loop_lead): loop_lead
    seconds, or with loop_lead_line the line sung just before the clip (from its start to the
    clip's), kept inside the song. 0 without a loop, over the user's video, or when it would be no
    longer than the blend, which then joins the end to the start as before."""
    if not style.loop or song.video:
        return 0.0
    first, _ = span(style, song)
    length = style.loop_lead
    if style.loop_lead_line:
        before = [start for start, text in lines if start < first - 1e-3 and text]
        length = first - before[-1] if before else 0.0
    length = min(max(0.0, length), first)
    return length if length > blend(style) + 1e-3 else 0.0


def lead_graph(length: float, lead: float, blend: float) -> str:
    """ffmpeg's audio filter for a loop lead-in: input 1 is the clip, `length` seconds, input 2
    the `lead` seconds before it. The clip fades out over its last LEAD_OUT seconds; the lead comes
    in `blend` seconds before the clip's end, fading in over LEAD_IN, and plays to its end, which is the
    sample before the clip's first. Neither the file's start nor its end fades."""
    start = length - blend
    return (
        f"[1:a]afade=t=out:st={max(0.0, length - LEAD_OUT):.3f}:d={LEAD_OUT}[end];"
        f"[2:a]afade=t=in:st=0:d={LEAD_IN},adelay={round(start * 1000)}:all=1[before];"
        "[end][before]amix=inputs=2:duration=longest:normalize=0[sound]"
    )


def loop_graph(length: float, overlap: float) -> str:
    """ffmpeg's audio filter for a loop: input 1 is the clip, input 2 the `overlap` seconds before
    it. The clip's end fades out while the moments before its start fade in, so the last sample
    leads into the first. The fades are equal power (a quarter sine each way): two different moments
    of the song add in power, and straight fades left the seam quieter."""
    start = length - overlap
    return (
        f"[1:a]afade=t=out:st={start:.3f}:d={overlap:.3f}:curve=qsin[end];"
        f"[2:a]afade=t=in:st=0:d={overlap:.3f}:curve=qsin,adelay={round(start * 1000)}:all=1[before];"
        "[end][before]amix=inputs=2:duration=first:normalize=0[sound]"
    )


@lru_cache(maxsize=2)
def _backdrop(
    path: str, art_stamp: float, blur: int, dim: float, tone: str, w: int, h: int
) -> Image.Image:
    art = render.square(path, art_stamp)
    scale = max(w / art.width, h / art.height)
    bg = art.resize((math.ceil(art.width * scale), math.ceil(art.height * scale)), Image.LANCZOS)
    left, top = (bg.width - w) // 2, (bg.height - h) // 2
    bg = bg.crop((left, top, left + w, top + h))
    if blur > 0:
        bg = bg.filter(ImageFilter.GaussianBlur(blur))
    bg = render.toned(bg.convert("RGB"), tone, path, art_stamp)
    return Image.blend(bg, Image.new("RGB", (w, h), (0, 0, 0)), dim).convert("RGBA")


def backdrop(song: render.Song, style: render.Style) -> Image.Image:
    """The cover filling the upright frame, blurred, toned and darkened, with nothing on it."""
    w, h = SHAPES.get(style.shape, SHAPES["tall"])
    return _backdrop(song.art, render.stamp(song.art), style.blur, style.dim, style.tone, w, h)


def rows_of(text: str, f, room: float) -> list[str]:
    """Words in rows no wider than room; a word wider than a row is split between letters."""
    rows: list[str] = []
    for word in text.split():
        while render.text_width(word, f) > room and len(word) > 1:
            cut = len(word)
            while cut > 1 and render.text_width(word[:cut], f) > room:
                cut -= 1
            rows.append(word[:cut])
            word = word[cut:]
        if rows and render.text_width(f"{rows[-1]} {word}", f) <= room:
            rows[-1] = f"{rows[-1]} {word}"
        else:
            rows.append(word)
    return rows or [""]


@lru_cache(maxsize=256)
def fitted(
    text: str, face: str, size: float, weight: int, most: int, fr: Frame
) -> tuple[float, tuple[str, ...]]:
    """The size a line is drawn at and its rows: `size`, smaller when it needs more than `most` rows."""
    room = fr.right - fr.margin - 2 * BAND_PAD[0] * fr.text
    least = MIN_PX * fr.text
    while True:
        rows = rows_of(text, render.font(face, size, weight), room)
        if len(rows) <= most or size <= least:
            return size, tuple(rows[:most])
        size = max(least, round(size * 0.9))


def block(
    text: str,
    face: str,
    size: float,
    weight: int,
    most: int,
    centre: float,
    fr: Frame,
    rows: tuple[str, ...] | None = None,
) -> dict:
    """A line laid out at `size` around `centre`; given rows are kept as they are, at that size."""
    if rows is None:
        size, rows = fitted(text, face, size, weight, most, fr)
    f = render.font(face, size, weight)
    width = max(render.text_width(r, f) for r in rows)
    height = len(rows) * size * PITCH
    box = (
        round(fr.cx - width / 2),
        round(centre - height / 2),
        round(fr.cx + width / 2),
        round(centre + height / 2),
    )
    return {
        "text": text,
        "rows": rows,
        "size": size,
        "weight": weight,
        "box": box,
        "centre": centre,
    }


def ease(u: float) -> float:
    return u * u * (3 - 2 * u)


def current(t: float, lines: tuple[tuple[float, str], ...]) -> int:
    k = -1
    for i, (start, _) in enumerate(lines):
        if start <= t:
            k = i
    return k


def moved(t: float, k: int, lines: tuple[tuple[float, str], ...], first: float) -> float:
    """How far line k has moved into the middle at t, 0 to 1. A line that starts on the clip's first
    moment, or less than CHANGE before it, is already in place there: a Short opens on its line."""
    if k < 0:
        return 1.0
    start = lines[k][0]
    begin = min(start, first - CHANGE) if start <= first else start
    return min(1.0, max(0.0, (t - begin) / CHANGE))


def following(k: int, lines: tuple[tuple[float, str], ...]) -> int | None:
    return next((i for i in range(k + 1, len(lines)) if lines[i][1]), None)


def layout(
    t: float, lines: tuple[tuple[float, str], ...], song: render.Song, style: render.Style
) -> dict:
    """Where everything is at t: the title, the cover, and the lines as blocks with their rows,
    size, box and how visible they are (alpha 0 to 1). The new line moves up from the next line's
    place over CHANGE seconds while the one before it leaves upwards."""
    face = fonts.resolve(style.font)
    fr = frame_of(style)
    side = round(COVER_SIDE * fr.scale)
    cover_top = round(fr.y(COVER_TOP))
    cover = (fr.cx - side // 2, cover_top, fr.cx - side // 2 + side, cover_top + side)
    title = (
        fr.margin,
        round(fr.y(TITLE_Y - 40)),
        fr.right,
        round(fr.y((ARTIST_Y if song.artist else TITLE_Y) + 30)),
    )
    now_y, gap = fr.y(NOW_Y), NEXT_GAP * fr.scale
    now_px = (LETTER_PX if style.highlight == "letter" else NOW_PX) * fr.text
    next_px = NEXT_PX * fr.text
    pad_x, pad_y = BAND_PAD[0] * fr.text, BAND_PAD[1] * fr.text
    k = current(t, lines)
    p = ease(moved(t, k, lines, span(style, song)[0]))
    now = None
    if k >= 0 and lines[k][1]:
        rest = block(lines[k][1], face, now_px, 700, MAX_ROWS, now_y, fr)
        below = rest["box"][3]
    else:
        rest, below = None, now_y
    n = following(k, lines)
    nxt = None
    if n is not None:
        size, rows = fitted(lines[n][1], face, next_px, 500, 2, fr)
        centre = below + gap + len(rows) * size * PITCH / 2
        nxt = block(lines[n][1], face, next_px, 500, 2, centre, fr)
        # It waits until the new line has nearly left its place.
        nxt["alpha"] = 0.6 * (max(0.0, (p - 0.6) / 0.4) if rest else 1.0)
    if rest:
        if p < 1.0:
            # From the place it had as the next line to the middle, growing on the way.
            size0, rows0 = fitted(lines[k][1], face, next_px, 500, 2, fr)
            start = (
                now_y + gap + len(rows0) * size0 * PITCH / 2 + (rest["box"][3] - rest["box"][1]) / 2
            )
            centre = start + (now_y - start) * p
            size = next_px + (rest["size"] - next_px) * p
            # The rows it ends in, so the line grows without breaking anew on the way.
            now = block(lines[k][1], face, size, 700, MAX_ROWS, centre, fr, rest["rows"])
        else:
            now = rest
        now["alpha"] = 0.6 + 0.4 * p
        bx0, by0, bx1, by1 = now["box"]
        now["band"] = (
            max(fr.margin, round(bx0 - pad_x)),
            round(by0 - pad_y),
            min(fr.right, round(bx1 + pad_x)),
            round(by1 + pad_y),
        )
        now["band_alpha"] = p
    gone = None
    before = k - 1
    if rest and p < 1.0 and before >= 0 and lines[before][1]:
        gone = block(
            lines[before][1], face, now_px, 700, MAX_ROWS, now_y - GONE_RISE * fr.scale * p, fr
        )
        gone["alpha"] = 1.0 - p
    return {"title": title, "cover": cover, "now": now, "next": nxt, "gone": gone, "progress": p}


def bar_ink(colour: str) -> tuple[int, int, int]:
    """Dark text on a light band, white on a dark one."""
    r, g, b = render.hex_rgb(colour)
    return (24, 24, 24) if 0.299 * r + 0.587 * g + 0.114 * b > 150 else (255, 255, 255)


def titled(style: render.Style) -> bool:
    """The title and the artist are drawn in the frame unless a top band carries a text, which
    would say the same thing twice."""
    return style.show_title and not (style.bars and style.bars_top.strip())


def draw_bars(img: Image.Image, style: render.Style, fr: Frame) -> None:
    """The bands across the top and the bottom, and their texts on one line each, made smaller when
    a text is wider than the frame or taller than its band. The texts are centred on the whole
    width, as the bands are, not on the room the lyrics keep clear of a Short's buttons."""
    d = ImageDraw.Draw(img)
    fill = (*render.hex_rgb(style.bars_colour), 255)
    d.rectangle((0, 0, fr.w, fr.bar - 1), fill=fill)
    d.rectangle((0, fr.h - fr.bar, fr.w, fr.h), fill=fill)
    for text, y in ((style.bars_top, fr.bar / 2), (style.bars_bottom, fr.h - fr.bar / 2)):
        band_text(d, style, fr, text, y, fr.bar)


def band_text(
    d: ImageDraw.ImageDraw, style: render.Style, fr: Frame, text: str, y: float, height: float
) -> None:
    """One band's text on one line, centred at y, made smaller when wider than the frame or taller
    than the band."""
    text = " ".join(text.split())
    if not text or height <= 0:
        return
    face = fonts.resolve(style.font)
    f = render.font(face, min(style.bars_size, height * 0.6), 650)
    while render.text_width(text, f) > fr.w - 2 * fr.margin and f.size > 12:
        f = render.font(face, f.size * 0.92, 650)
    render.tracked(d, (fr.w / 2, y), text, f, (*bar_ink(style.bars_colour), 255))


def later(times: tuple[float, ...], j: int) -> float:
    """When letter j stops being sung: the next later time. A punctuation mark shares its letter's
    time, so it does not end it."""
    return next((x for x in times[j + 1 :] if x > times[j]), math.inf)


def pop(t: float, times: tuple[float, ...], j: int) -> float:
    """How big letter j is at t: 1, rising to LETTER_POP as it is sung and back as the next starts."""
    start, end = times[j], later(times, j)
    if t < start:
        return 1.0
    u = min(1.0, (t - start) / POP_IN) if t < end else max(0.0, 1 - (t - end) / POP_IN)
    return round(1 + (LETTER_POP - 1) * ease(u), 2)


def marked_by(row: str, first: int) -> list[int | None]:
    """For each character of `row`, the number (counted from `first`, spaces left out) of the letter
    whose time and size it takes: a letter or digit its own; a mark the letter before it in the same
    word, or for an opening mark the one after it; a mark standing alone between spaces None."""
    numbers, j = [], first
    for ch in row:
        numbers.append(None if ch == " " else j)
        j += ch != " "
    out: list[int | None] = []
    for k, ch in enumerate(row):
        if ch == " " or ch.isalnum():
            out.append(numbers[k])
            continue
        left = k - 1
        while left >= 0 and row[left] != " " and not row[left].isalnum():
            left -= 1
        right = k + 1
        while right < len(row) and row[right] != " " and not row[right].isalnum():
            right += 1
        if left >= 0 and row[left] != " ":
            out.append(numbers[left])
        elif right < len(row) and row[right] != " ":
            out.append(numbers[right])
        else:
            out.append(None)
    return out


def letters(
    d: ImageDraw.ImageDraw,
    part: dict,
    alpha: int,
    times: tuple[float, ...],
    t: float,
    cx: float,
    ink: render.Style,
    lit: render.Style,
) -> None:
    """A line letter by letter, centred on cx: the letter being sung in `lit` and grown, the rest in
    `ink`. A mark touching a letter goes with it (marked_by). Rows are centred on their width at that
    moment, so a grown letter pushes the others aside."""
    face = fonts.resolve(ink.font)
    f = render.font(face, part["size"], part["weight"])
    track = f.size * render.TRACKING
    pitch = part["size"] * PITCH
    j = 0
    for r, row in enumerate(part["rows"]):
        y = part["centre"] + (r - (len(part["rows"]) - 1) / 2) * pitch
        owner = marked_by(row, j)
        cells = []
        for k, ch in enumerate(row):
            if ch == " ":
                cells.append((ch, f, f.getlength(ch), False))
                continue
            n = owner[k]
            sung = n is not None and n < len(times)
            s = pop(t, times, n) if sung else 1.0
            cf = render.font(face, part["size"] * s, part["weight"]) if s > 1 else f
            cells.append((ch, cf, cf.getlength(ch), sung and times[n] <= t < later(times, n)))
            j += 1
        x = cx - (sum(c[2] for c in cells) + track * (len(cells) - 1)) / 2
        for ch, cf, width, on in cells:
            if ch != " ":
                render.lettered(d, (x + width / 2, y), ch, cf, alpha, lit if on else ink)
            x += width + track


def disc_place(fr: Frame) -> tuple[int, int, int]:
    """The disc look's disc: centre x and y, and side. Centred on the line being sung and moved up
    when its lower edge would go under the bottom band."""
    side = min(DISC_SIDE, round(0.8 * fr.w), round(0.75 * (fr.bottom - fr.top)))
    return fr.cx, min(round(fr.y(NOW_Y)), fr.h - fr.bar - side // 2), side


def worn(face: Image.Image, radius: int) -> tuple[Image.Image, Image.Image]:
    """An old disc: the print with its paint come off in a few places (short stretches of its outer
    and inner edge, and two or three small flakes, the silver showing through), and seven very faint
    scratches along the tracks on a layer that turns with it. Colours and brightness stay; the same
    seed every time, so every frame and every render wears alike."""
    side = radius * 2
    rng = np.random.default_rng(WEAR_SEED)
    y, x = np.mgrid[0:side, 0:side] - (side - 1) / 2
    dist, ang = np.hypot(x, y) / radius, np.arctan2(y, x)
    blot = Image.fromarray((rng.random((side // 8, side // 8)) * 255).astype(np.uint8))
    blot = blot.resize((side, side), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2))
    blot = np.asarray(blot, np.float32) / 255
    where = np.zeros_like(dist, dtype=np.float32)
    for centre, width in [(rng.uniform(-np.pi, np.pi), rng.uniform(0.25, 0.5)) for _ in range(3)]:
        off = np.angle(np.exp(1j * (ang - centre)))
        where = np.maximum(where, np.clip(1 - np.abs(off) / width, 0, 1))
    outer = np.clip(1 - (0.975 - dist) / 0.05, 0, 1)
    inner = np.clip(1 - (dist - 0.36) / 0.035, 0, 1) * (dist > 0.36)
    near = (outer + inner * 0.8) * where
    for _ in range(3):
        a, r0 = rng.uniform(0, 2 * np.pi), rng.uniform(0.5, 0.88)
        fx, fy = r0 * np.cos(a), r0 * np.sin(a)
        flake = np.hypot(x / radius - fx, y / radius - fy) / rng.uniform(0.02, 0.04)
        near = np.maximum(near, np.clip(1 - flake, 0, 1))
    kept = np.asarray(face.getchannel("A"), np.float32) * (blot * near <= 0.3)
    face = face.copy()
    face.putalpha(Image.fromarray(kept.astype(np.uint8), "L"))
    wear = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    d = ImageDraw.Draw(wear)
    for _ in range(7):
        r = radius * rng.uniform(0.45, 0.95)
        a0 = rng.uniform(0, 360)
        d.arc(
            (radius - r, radius - r, radius + r, radius + r),
            a0,
            a0 + rng.uniform(15, 50),
            fill=(255, 255, 255, int(rng.uniform(22, 38))),
            width=1,
        )
    ring = render.circle_mask(side, render.HOLE, 0.975)
    wear.putalpha(ImageChops.multiply(wear.getchannel("A"), ring))
    return face, wear


def hook_rows(style: render.Style) -> list[str]:
    """The hook's rows when the frame has bands to hold it, else none."""
    rows = [" ".join(r.split()) for r in style.hook.split("|")] if style.bars else []
    return [r for r in rows if r][:2]


def hook_band(style: render.Style, fr: Frame) -> Image.Image:
    """The top band made taller by HOOK_SHIFT, its one or two rows centred in it, the words of
    hook_hi in the highlight colour; a row too wide for the frame is drawn smaller."""
    rows = hook_rows(style)
    band = Image.new("RGBA", (fr.w, fr.bar + HOOK_SHIFT), (*render.hex_rgb(style.bars_colour), 255))
    d = ImageDraw.Draw(band)
    face = fonts.resolve(style.font)
    lit = [w.strip() for w in style.hook_hi.split(",") if w.strip()]
    ink, yellow = (*bar_ink(style.bars_colour), 255), (*render.hex_rgb(HIGHLIGHT), 255)
    f = render.font(face, HOOK_PX, HOOK_WEIGHT)
    while max(f.getlength(r) for r in rows) > fr.w - 2 * fr.margin and f.size > 24:
        f = render.font(face, f.size * 0.92, HOOK_WEIGHT)
    pitch = f.size * HOOK_PITCH
    top = (band.height - pitch * (len(rows) - 1)) / 2
    for r, row in enumerate(rows):
        parts = re.split("(" + "|".join(map(re.escape, lit)) + ")", row) if lit else [row]
        parts = [p for p in parts if p]
        x = (fr.w - sum(f.getlength(p) for p in parts)) / 2
        for p in parts:
            d.text((x, top + r * pitch), p, font=f, fill=yellow if p in lit else ink, anchor="lm")
            x += f.getlength(p)
    return band


class Painter:
    """The upright frames of one song and style. The background, title, cover and bands are drawn
    once; a frame adds the lines, and a frame whose lines stand where they stood is the last one
    again. With the disc look the disc turns under the bands on every frame."""

    def __init__(
        self, lines: tuple[tuple[float, str], ...], song: render.Song, style: render.Style
    ):
        self.song, self.style = song, style
        self.letter = style.highlight == "letter"
        given = {(start, text): times for start, text, times in song.letters}
        # Per line, its letter times; a line comes in no later than its first letter.
        self.times = [given.get(line) if self.letter else None for line in lines]
        self.lines = tuple(
            (min(start, times[0]) if times else start, text)
            for (start, text), times in zip(lines, self.times, strict=True)
        )
        self.ink = replace(style, lyric_edge="shadow") if self.letter else style
        self.lit = replace(self.ink, lyric_colour=HIGHLIGHT)
        self.frame = frame_of(style)
        self.span = span(style, song)
        self.disc = style.upright_look == "disc"
        self.base = self.disc_layer() if self.disc else self.still_layer()
        if self.disc:
            self.make_disc()
        self.overlap = loop_length(style, song)
        # With a lead the clip goes on past its end into the song before its start, `lead` seconds
        # less the blend; lines after the clip never show, not even as the next line.
        self.lead = lead(style, song, lines)
        if self.lead:
            self.overlap = blend(style)
            self.lines = tuple(
                (start, text) if start < self.span[1] else (start, "") for start, text in self.lines
            )
        self.lead = self.lead or self.overlap
        self.last: tuple = (None, b"")
        self.fps = render.rate(style)
        self.hook = hook_band(style, self.frame) if hook_rows(style) else None
        self.crop = max(0, style.crop_top) if style.bars else 0
        if self.disc:
            # Whole turns over the whole video, so a loop meets itself.
            first, last = self.span
            whole = last - first + self.lead - self.overlap
            self.turns = max(1, round(whole / style.spin)) if style.spin > 0 else 0

    def length(self) -> float:
        """The video's length: the clip, and the lead less the blend."""
        first, last = self.span
        return last - first + self.lead - self.overlap

    def before(self, t: float) -> float:
        """The song time shown after t in the blend at the clip's end: from `lead` seconds before the
        clip, reaching the clip's start at the video's end."""
        first, last = self.span
        return first - self.lead + (t - (last - self.overlap))

    def make_disc(self) -> None:
        """The disc, its shadow and veil, and the bands drawn over it, made once."""
        song, style, fr = self.song, self.style, self.frame
        cx, cy, side = disc_place(fr)
        radius = side // 2
        face = render.disc_print(render.square(song.art, render.stamp(song.art)), radius)
        self.wear = None
        if style.disc_wear == "worn":
            face, self.wear = worn(face, radius)
        self.cd = render.Disc(face, radius)
        self.veil = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        self.veil.putalpha(self.cd.at(0).getchannel("A").point(lambda v: round(v * DISC_DIM)))
        self.shade = Image.new("RGBA", (side + 160, side + 160), (0, 0, 0, 0))
        ImageDraw.Draw(self.shade).ellipse((80, 100, side + 80, side + 100), fill=(0, 0, 0, 150))
        self.shade = self.shade.filter(ImageFilter.GaussianBlur(28))
        self.disc_at = (cx - radius, cy - radius)
        self.bars = None
        if fr.bar:
            self.bars = Image.new("RGBA", (fr.w, fr.h), (0, 0, 0, 0))
            draw_bars(self.bars, style, fr)

    def turn(self, t: float) -> float:
        """The disc's turn at the video's own time t (song time while the clip plays)."""
        first, _ = self.span
        return 360 * self.turns * (t - first) / self.length() if self.turns else 0.0

    def disc_layer(self) -> Image.Image:
        """The disc look's background: the blurred cover, and the title and the artist in the room
        between the top band and the disc."""
        song, style, fr = self.song, self.style, self.frame
        img = backdrop(song, style).copy()
        if style.show_title:
            _, cy, side = disc_place(fr)
            mid = (fr.top + cy - side / 2) / 2
            face = fonts.resolve(style.font)
            d = ImageDraw.Draw(img)
            title = render.font(face, 64, 600)
            while (
                render.text_width(song.title, title, 0.06) > fr.w - 2 * fr.margin
                and title.size > 28
            ):
                title = render.font(face, title.size * 0.92, 600)
            y = mid - 24 if song.artist else mid
            render.lettered(d, (fr.w / 2, y), song.title, title, 255, self.ink, 0.06)
            if song.artist:
                artist = render.font(face, 30, 400)
                render.lettered(d, (fr.w / 2, mid + 40), song.artist, artist, 175, self.ink, 0.18)
        return img

    def background(self, t: float, clock: float | None = None) -> Image.Image:
        img = self.base.copy()
        if not self.disc:
            return img
        x, y = self.disc_at
        img.alpha_composite(self.shade, (x - 80, y - 80))
        turn = self.turn(t if clock is None else clock)
        cd = self.cd.at(turn)
        cd.alpha_composite(self.veil)
        # The wear catches the light over the darkened disc, so it stays visible.
        if self.wear is not None:
            cd.alpha_composite(self.wear.rotate(-turn, Image.BICUBIC))
        img.alpha_composite(cd, (x, y))
        if self.bars is not None:
            img.alpha_composite(self.bars)
        return img

    def still_layer(self) -> Image.Image:
        song, style, fr = self.song, self.style, self.frame
        img = backdrop(song, style).copy()
        spots = layout(-1.0, (), song, style)
        x0, y0, x1, y1 = spots["cover"]
        shade = Image.new("RGBA", (fr.w, fr.h), (0, 0, 0, 0))
        ImageDraw.Draw(shade).rectangle((x0 + 6, y0 + 14, x1 + 6, y1 + 14), fill=(0, 0, 0, 150))
        img.alpha_composite(shade.filter(ImageFilter.GaussianBlur(18)))
        art = render.square(song.art, render.stamp(song.art)).resize(
            (x1 - x0, y1 - y0), Image.LANCZOS
        )
        img.paste(art.convert("RGB"), (x0, y0))
        if titled(style):
            face = fonts.resolve(style.font)
            d = ImageDraw.Draw(img)
            title = render.font(face, 40 * fr.text, 650)
            while (
                render.text_width(song.title, title, 0.04) > fr.right - fr.margin
                and title.size > 24 * fr.text
            ):
                title = render.font(face, title.size * 0.92, 650)
            render.lettered(d, (fr.cx, fr.y(TITLE_Y)), song.title, title, 255, style, 0.04)
            if song.artist:
                artist = render.font(face, 28 * fr.text, 400)
                render.lettered(d, (fr.cx, fr.y(ARTIST_Y)), song.artist, artist, 190, style, 0.12)
        if fr.bar:
            draw_bars(img, style, fr)
        return img

    def lyric_state(self, t: float) -> tuple:
        k = current(t, self.lines)
        p = moved(t, k, self.lines, self.span[0])
        times = self.times[k] if k >= 0 else None
        letters = (
            tuple((pop(t, times, j), times[j] <= t < later(times, j)) for j in range(len(times)))
            if times
            else ()
        )
        return (k, round(p * self.fps), letters)

    def state(self, t: float) -> tuple:
        state = self.lyric_state(t)
        if self.overlap:
            _, last = self.span
            if t >= last:
                state = ((), self.lyric_state(self.before(t)), self.fps)
            elif t > last - self.overlap:
                u = round((t - (last - self.overlap)) / self.overlap * self.fps)
                state = (state, self.lyric_state(self.before(t)), u)
        if self.disc and self.turns:
            return (state, round(t * self.fps))
        return state

    def plain(self, t: float, clock: float | None = None) -> Image.Image:
        fr = self.frame
        img = self.background(t, clock)
        spots = layout(t, self.lines, self.song, self.style)
        layer = Image.new("RGBA", (fr.w, fr.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        now = spots["now"]
        if now and now["band_alpha"] > 0 and not self.letter:
            d.rounded_rectangle(
                now["band"],
                radius=round(14 * fr.text),
                fill=(*render.band_rgb(self.style), round(render.BAND_ALPHA * now["band_alpha"])),
            )
        face = fonts.resolve(self.style.font)
        k = current(t, self.lines)
        for part in (spots["gone"], now, spots["next"]):
            if not part or part["alpha"] <= 0:
                continue
            alpha = round(255 * part["alpha"])
            times = self.times[k] if part is now else None
            if times:
                letters(d, part, alpha, times, t, fr.cx, self.ink, self.lit)
                continue
            f = render.font(face, part["size"], part["weight"])
            pitch = part["size"] * PITCH
            for i, row in enumerate(part["rows"]):
                y = part["centre"] + (i - (len(part["rows"]) - 1) / 2) * pitch
                render.lettered(d, (fr.cx, y), row, f, alpha, self.ink)
        img.alpha_composite(layer)
        return img

    def image(self, t: float, state: tuple | None = None) -> Image.Image:
        """The frame at the video's own time t: the song's moment t while the clip plays, then in
        the blend and the lead the moment before the clip that leads into its start."""
        if self.overlap:
            _, last = self.span
            if t >= last:
                return self.finish(self.plain(self.before(t), t))
            if t > last - self.overlap:
                u = min(1.0, (t - (last - self.overlap)) / self.overlap)
                return self.finish(Image.blend(self.plain(t), self.plain(self.before(t), t), u))
        return self.finish(self.plain(t))

    def finish(self, img: Image.Image) -> Image.Image:
        """The picture between the bands without its top crop_top px, moved down under the hook's
        taller band. The bottom band takes what is left: crop_top - HOOK_SHIFT px more or less than
        bars_height gave it, with bars_bottom drawn again in the middle of it."""
        if self.hook is None and not self.crop:
            return img
        fr = self.frame
        shift = HOOK_SHIFT if self.hook is not None else 0
        out = Image.new("RGBA", (fr.w, fr.h), (*render.hex_rgb(self.style.bars_colour), 255))
        # Pasted, not composited: faint lettering leaves the frame's alpha under 255, which the
        # video ignores and a composite over the band colour would darken.
        out.paste(img.crop((0, fr.bar + self.crop, fr.w, fr.h - fr.bar)), (0, fr.bar + shift))
        if self.hook is not None:
            out.alpha_composite(self.hook, (0, 0))
        bottom = self.bottom_band()
        if self.style.bars_bottom.strip() and bottom > 0:
            band_text(
                ImageDraw.Draw(out),
                self.style,
                fr,
                self.style.bars_bottom,
                fr.h - bottom / 2,
                bottom,
            )
        return out

    def bottom_band(self) -> int:
        """The bottom band's height after the hook and crop_top."""
        shift = HOOK_SHIFT if self.hook is not None else 0
        return self.frame.bar - shift + self.crop

    def raw(self, t: float) -> bytes:
        state = self.state(t)
        if state == self.last[0]:
            return self.last[1]
        raw = self.image(t, state).tobytes()
        self.last = (state, raw)
        return raw


_painters: dict = {}


def painter(
    lines: tuple[tuple[float, str], ...], song: render.Song, style: render.Style
) -> Painter:
    key = (lines, song, style, render.stamp(song.art))
    found = _painters.get(key)
    if found is None:
        if len(_painters) >= 2:
            _painters.pop(next(iter(_painters)))
        found = _painters[key] = Painter(lines, song, style)
    return found


def _key(text: str) -> str:
    """A line as it is sung: no case, spaces or punctuation, so "Oh, my love!" is "oh my love"."""
    return re.sub(r"[\W_]+", "", text.casefold())


def chorus(
    lines: tuple[tuple[float | None, str], ...], duration: float, length: float
) -> tuple[float, float] | None:
    """The part a Short should hold: from the first time the most repeated block of lines is sung,
    `length` seconds or to the end of the song. A block weighs its repeats times its lines, so a
    four-line chorus sung three times wins over one word sung five; then the longer block, then the
    earlier. None when no line comes back."""
    sung = [(t, _key(text)) for t, text in lines if t is not None and _key(text)]
    keys = [k for _, k in sung]
    best: tuple[tuple[int, int, int], int] | None = None
    for size in range(1, min(MAX_BLOCK, len(sung) // 2) + 1):
        found: dict[tuple[str, ...], list[int]] = {}
        for i in range(len(sung) - size + 1):
            found.setdefault(tuple(keys[i : i + size]), []).append(i)
        for starts in found.values():
            count, after = 0, -1
            for s in starts:
                if s >= after:
                    count, after = count + 1, s + size
            if count < 2:
                continue
            score = (count * size, size, -starts[0])
            if best is None or score > best[0]:
                best = (score, starts[0])
    if best is None:
        return None
    start = sung[best[1]][0]
    return start, min(duration, start + length)
