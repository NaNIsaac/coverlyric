"""Shorts: the song's frame turned upright for a phone, 1080x1920. The title and the artist small at
the top, the cover in the top third, the line being sung large in the middle on a band and the next
one small under it. The bottom fifth and the right edge stay empty, as YouTube Shorts covers them
with its own buttons and caption."""

from __future__ import annotations

import math
from dataclasses import replace
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from . import fonts, render

TW, TH = 1080, 1920
SAFE_BOTTOM = 0.2  # share of the height Shorts covers with the caption and the music line
SAFE_RIGHT = 120  # px Shorts covers with the like, comment and share buttons
MARGIN = 60
RIGHT = TW - SAFE_RIGHT
CX = (MARGIN + RIGHT) // 2
TITLE_Y, ARTIST_Y = 112, 162
COVER_SIDE, COVER_TOP = 440, 196
NOW_Y = 1040  # centre of the line being sung
NOW_PX, NEXT_PX, MIN_PX = 84, 48, 44
MAX_ROWS = 3
PITCH = 1.18  # row distance in em
BAND_PAD = (30, 16)
CHANGE = 0.3  # seconds a new line takes to move up into the middle
LOOP = 0.5  # seconds of the end that blend into the moments before the start
AUDIO_FADE = 0.3

# What 세로 (Shorts) sets; the colours, font and background stay as the user made them.
SHORTS = {"shape": "tall", "fps": 30, "lyric_edge": "outline", "intro": 0.0}


def shorts(style: render.Style) -> render.Style:
    return replace(style, **SHORTS)


def wide(style: render.Style) -> render.Style:
    return replace(style, shape="wide", fps=render.FPS)


def span(style: render.Style, song: render.Song) -> tuple[float, float]:
    """The part of the song the Shorts video holds: clip_from to clip_to, a clip_to of 0 meaning the
    end, both kept inside the song."""
    end = song.duration
    first = min(max(0.0, style.clip_from), end)
    last = style.clip_to if style.clip_to > 0 else end
    last = min(max(first, last), end)
    return (first, last) if last > first else (0.0, end)


def loop_length(style: render.Style, song: render.Song) -> float:
    """How much of the end blends into what comes before the start: LOOP, less when the clip starts
    sooner than that, 0 without a loop."""
    if not style.loop:
        return 0.0
    first, _ = span(style, song)
    length = min(LOOP, first)
    return length if length >= 0.05 else 0.0


def loop_graph(length: float, overlap: float) -> str:
    """ffmpeg's audio filter for a loop: input 1 is the clip, input 2 the `overlap` seconds before
    it. The clip's end fades out while the moments before its start fade in, so the last sample
    leads into the first."""
    start = length - overlap
    return (
        f"[1:a]afade=t=out:st={start:.3f}:d={overlap:.3f}[end];"
        f"[2:a]afade=t=in:st=0:d={overlap:.3f},adelay={round(start * 1000)}:all=1[before];"
        "[end][before]amix=inputs=2:duration=first:normalize=0[sound]"
    )


@lru_cache(maxsize=2)
def _backdrop(path: str, art_stamp: float, blur: int, dim: float, tone: str) -> Image.Image:
    art = render.square(path, art_stamp)
    scale = max(TW / art.width, TH / art.height)
    bg = art.resize((math.ceil(art.width * scale), math.ceil(art.height * scale)), Image.LANCZOS)
    left, top = (bg.width - TW) // 2, (bg.height - TH) // 2
    bg = bg.crop((left, top, left + TW, top + TH))
    if blur > 0:
        bg = bg.filter(ImageFilter.GaussianBlur(blur))
    bg = render.toned(bg.convert("RGB"), tone, path, art_stamp)
    return Image.blend(bg, Image.new("RGB", (TW, TH), (0, 0, 0)), dim).convert("RGBA")


def backdrop(song: render.Song, style: render.Style) -> Image.Image:
    """The cover filling the upright frame, blurred, toned and darkened, with nothing on it."""
    return _backdrop(song.art, render.stamp(song.art), style.blur, style.dim, style.tone)


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
    text: str, face: str, size: float, weight: int, most: int
) -> tuple[float, tuple[str, ...]]:
    """The size a line is drawn at and its rows: `size`, smaller when it needs more than `most` rows."""
    room = RIGHT - MARGIN - 2 * BAND_PAD[0]
    while True:
        rows = rows_of(text, render.font(face, size, weight), room)
        if len(rows) <= most or size <= MIN_PX:
            return size, tuple(rows[:most])
        size = max(MIN_PX, round(size * 0.9))


def block(
    text: str,
    face: str,
    size: float,
    weight: int,
    most: int,
    centre: float,
    rows: tuple[str, ...] | None = None,
) -> dict:
    """A line laid out at `size` around `centre`; given rows are kept as they are, at that size."""
    if rows is None:
        size, rows = fitted(text, face, size, weight, most)
    f = render.font(face, size, weight)
    width = max(render.text_width(r, f) for r in rows)
    height = len(rows) * size * PITCH
    box = (
        round(CX - width / 2),
        round(centre - height / 2),
        round(CX + width / 2),
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


def following(k: int, lines: tuple[tuple[float, str], ...]) -> int | None:
    return next((i for i in range(k + 1, len(lines)) if lines[i][1]), None)


def layout(
    t: float, lines: tuple[tuple[float, str], ...], song: render.Song, style: render.Style
) -> dict:
    """Where everything is at t: the title, the cover, and the lines as blocks with their rows,
    size, box and how visible they are (alpha 0 to 1). The new line moves up from the next line's
    place over CHANGE seconds while the one before it leaves upwards."""
    face = fonts.resolve(style.font)
    side = COVER_SIDE
    cover = (CX - side // 2, COVER_TOP, CX - side // 2 + side, COVER_TOP + side)
    title = (MARGIN, TITLE_Y - 40, RIGHT, (ARTIST_Y if song.artist else TITLE_Y) + 30)
    k = current(t, lines)
    p = ease(min(1.0, (t - lines[k][0]) / CHANGE)) if k >= 0 else 1.0
    now = None
    if k >= 0 and lines[k][1]:
        rest = block(lines[k][1], face, NOW_PX, 700, MAX_ROWS, NOW_Y)
        below = rest["box"][3]
    else:
        rest, below = None, NOW_Y
    n = following(k, lines)
    nxt = None
    if n is not None:
        size, rows = fitted(lines[n][1], face, NEXT_PX, 500, 2)
        centre = below + 44 + len(rows) * size * PITCH / 2
        nxt = block(lines[n][1], face, NEXT_PX, 500, 2, centre)
        # It waits until the new line has nearly left its place.
        nxt["alpha"] = 0.6 * (max(0.0, (p - 0.6) / 0.4) if rest else 1.0)
    if rest:
        if p < 1.0:
            # From the place it had as the next line to the middle, growing on the way.
            size0, rows0 = fitted(lines[k][1], face, NEXT_PX, 500, 2)
            start = (
                NOW_Y + 44 + len(rows0) * size0 * PITCH / 2 + (rest["box"][3] - rest["box"][1]) / 2
            )
            centre = start + (NOW_Y - start) * p
            size = NEXT_PX + (rest["size"] - NEXT_PX) * p
            # The rows it ends in, so the line grows without breaking anew on the way.
            now = block(lines[k][1], face, size, 700, MAX_ROWS, centre, rest["rows"])
        else:
            now = rest
        now["alpha"] = 0.6 + 0.4 * p
        bx0, by0, bx1, by1 = now["box"]
        now["band"] = (
            max(MARGIN, bx0 - BAND_PAD[0]),
            by0 - BAND_PAD[1],
            min(RIGHT, bx1 + BAND_PAD[0]),
            by1 + BAND_PAD[1],
        )
        now["band_alpha"] = p
    gone = None
    before = k - 1
    if rest and p < 1.0 and before >= 0 and lines[before][1]:
        gone = block(lines[before][1], face, NOW_PX, 700, MAX_ROWS, NOW_Y - 160 * p)
        gone["alpha"] = 1.0 - p
    return {"title": title, "cover": cover, "now": now, "next": nxt, "gone": gone, "progress": p}


class Painter:
    """The upright frames of one song and style. The background, title and cover are drawn once; a
    frame adds the lines, and a frame whose lines stand where they stood is the last one again."""

    def __init__(
        self, lines: tuple[tuple[float, str], ...], song: render.Song, style: render.Style
    ):
        self.lines, self.song, self.style = lines, song, style
        self.base = self.still_layer()
        self.span = span(style, song)
        self.overlap = loop_length(style, song)
        self.last: tuple = (None, b"")
        self.fps = render.rate(style)

    def still_layer(self) -> Image.Image:
        song, style = self.song, self.style
        img = backdrop(song, style).copy()
        spots = layout(-1.0, (), song, style)
        x0, y0, x1, y1 = spots["cover"]
        shade = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        ImageDraw.Draw(shade).rectangle((x0 + 6, y0 + 14, x1 + 6, y1 + 14), fill=(0, 0, 0, 150))
        img.alpha_composite(shade.filter(ImageFilter.GaussianBlur(18)))
        art = render.square(song.art, render.stamp(song.art)).resize(
            (x1 - x0, y1 - y0), Image.LANCZOS
        )
        img.paste(art.convert("RGB"), (x0, y0))
        if style.show_title:
            face = fonts.resolve(style.font)
            d = ImageDraw.Draw(img)
            title = render.font(face, 40, 650)
            while render.text_width(song.title, title, 0.04) > RIGHT - MARGIN and title.size > 24:
                title = render.font(face, title.size * 0.92, 650)
            render.lettered(d, (CX, TITLE_Y), song.title, title, 255, style, 0.04)
            if song.artist:
                render.lettered(
                    d, (CX, ARTIST_Y), song.artist, render.font(face, 28, 400), 190, style, 0.12
                )
        return img

    def lyric_state(self, t: float) -> tuple:
        k = current(t, self.lines)
        p = min(1.0, (t - self.lines[k][0]) / CHANGE) if k >= 0 else 1.0
        return (k, round(p * self.fps))

    def state(self, t: float) -> tuple:
        state = self.lyric_state(t)
        if self.overlap:
            first, last = self.span
            if t > last - self.overlap:
                u = round((t - (last - self.overlap)) / self.overlap * self.fps)
                return (state, self.lyric_state(first - (last - t)), u)
        return state

    def plain(self, t: float) -> Image.Image:
        img = self.base.copy()
        spots = layout(t, self.lines, self.song, self.style)
        layer = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        now = spots["now"]
        if now and now["band_alpha"] > 0:
            d.rounded_rectangle(
                now["band"],
                radius=14,
                fill=(*render.band_rgb(self.style), round(render.BAND_ALPHA * now["band_alpha"])),
            )
        face = fonts.resolve(self.style.font)
        for part in (spots["gone"], now, spots["next"]):
            if not part or part["alpha"] <= 0:
                continue
            f = render.font(face, part["size"], part["weight"])
            pitch = part["size"] * PITCH
            for i, row in enumerate(part["rows"]):
                y = part["centre"] + (i - (len(part["rows"]) - 1) / 2) * pitch
                render.lettered(d, (CX, y), row, f, round(255 * part["alpha"]), self.style)
        img.alpha_composite(layer)
        return img

    def image(self, t: float, state: tuple | None = None) -> Image.Image:
        img = self.plain(t)
        if self.overlap:
            first, last = self.span
            if t > last - self.overlap:
                u = min(1.0, (t - (last - self.overlap)) / self.overlap)
                img = Image.blend(img, self.plain(first - (last - t)), u)
        return img

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
