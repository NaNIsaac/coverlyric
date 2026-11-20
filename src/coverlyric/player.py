"""The music player look for the 16:9 video (layout=player). On the left the cover with rounded
corners and a see-through CD half out behind it, an optional date badge on the cover, the title, a
line of artist and album, a progress bar with the time played and the time left, and a row of
player buttons. On the right the lyric list, left aligned: the line being sung white, the others
grey, fading and blurring towards the top and the bottom. The buttons are drawn here and stand for
no app in particular; the background, the CD, the list's scroll and the title in a long intro are
the wide video's own."""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import anim, fonts, render
from .render import SS, Song, Style

# Frame pixels at album_scale 1, before album_x and album_y move them.
COVER = (158, 197, 704, 743)
COVER_RADIUS = 24
DISC_C, DISC_R = (672, 470), 248
DISC_ALPHA = 0.72  # the CD lets the background through, as a clear disc would
BADGE = (16, 14, 66)  # from the cover's top left: x, y, height
BADGE_PX = 26
TEXT_X, TEXT_RIGHT = 144, 816
TITLE_Y, ALBUM_Y = 814, 848
TITLE_PX, ALBUM_PX = 28, 22
BUTTONS = ((750, 830), (798, 830))  # the two small round buttons beside the title: star, more
BUTTON_R = 18
BAR_Y, BAR_H = 892, 6
TIMES_Y, TIMES_PX = 920, 19
CONTROLS_Y = 972
CONTROLS = (("shuffle", 165), ("previous", 358), ("pause", 480), ("next", 598), ("repeat", 797))
ICON = 24  # half the size of a control icon
GREY = (255, 255, 255, 120)

NOW_PX, OTHER_PX = 46, 46
NOW_WEIGHT, OTHER_WEIGHT = 700, 600
OTHER_LEVEL = 130  # the other lines' alpha on 255: grey on the dark background
VISIBLE = 5.5  # rows each way from the line being sung
# px at the top and the bottom of the list where lines fade and blur: little at the top, where the
# coming lines are read, more at the bottom.
SOFT = (50, 170)
SOFT_BLUR = 5


def scaled(x: float, y: float, style: Style) -> tuple[float, float]:
    """A left-column point of the 1920x1080 plan, scaled about the cover's centre and moved."""
    s = style.album_scale
    cx, cy = (COVER[0] + COVER[2]) / 2, (COVER[1] + COVER[3]) / 2
    return cx + (x - cx) * s + style.album_x, cy + (y - cy) * s + style.album_y


def box(b: tuple[float, ...], style: Style) -> tuple[int, int, int, int]:
    x0, y0 = scaled(b[0], b[1], style)
    x1, y1 = scaled(b[2], b[3], style)
    return round(x0), round(y0), round(x1), round(y1)


def column(style: Style) -> tuple[int, int, int, int]:
    """The frame box of everything on the left, for the drag handle."""
    return box(
        (
            TEXT_X,
            COVER[1],
            DISC_C[0] + DISC_R if style.show_cd else TEXT_RIGHT,
            CONTROLS_Y + ICON + 4,
        ),
        style,
    )


def subtitle(song: Song) -> str:
    """The line under the title: artist, then the album, or the title as a single."""
    album = song.album or f"{song.title} - Single"
    return f"{song.artist} — {album}" if song.artist else album


def times(t: float, song: Song) -> tuple[str, str]:
    """The time played and the time left at video time t, of the song between its silences. The
    time left is rounded up, so the two add up to the song's length."""
    length = max(0.0, song.duration - song.lead - song.tail)
    played = min(length, max(0.0, t - song.lead))
    left = max(0, math.ceil(length - played - 1e-6))
    return render.clock(played), "-" + render.clock(left)


def share(t: float, song: Song) -> float:
    length = song.duration - song.lead - song.tail
    return min(1.0, max(0.0, (t - song.lead) / length)) if length > 0 else 0.0


def rounded_cover(art: Image.Image, side: int, radius: int) -> Image.Image:
    face = art.resize((side, side), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (side * 2, side * 2), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side * 2 - 1, side * 2 - 1), radius * 2, 255)
    face.putalpha(mask.resize((side, side), Image.LANCZOS))
    return face


def icon(d: ImageDraw.ImageDraw, name: str, cx: float, cy: float, k: float) -> None:
    """One control, drawn at SS times the frame size around (cx, cy); k is the icon's half size."""
    white = (255, 255, 255, 235)
    line = max(2, round(k * 0.14))
    if name in ("previous", "next"):
        sign = 1 if name == "next" else -1
        for off in (-0.55, 0.45):
            x = cx + sign * off * k
            d.polygon(
                [
                    (x - sign * 0.5 * k, cy - 0.5 * k),
                    (x + sign * 0.5 * k, cy),
                    (x - sign * 0.5 * k, cy + 0.5 * k),
                ],
                fill=white,
            )
    elif name == "pause":
        for x in (cx - 0.32 * k, cx + 0.18 * k):
            d.rounded_rectangle(
                (x, cy - 0.62 * k, x + 0.16 * k, cy + 0.62 * k), 0.05 * k, fill=white
            )
    elif name == "shuffle":
        a, b = 0.55 * k, 0.32 * k
        d.line(
            [(cx - a, cy - b), (cx - 0.1 * k, cy - b), (cx + 0.2 * k, cy + b), (cx + a, cy + b)],
            white,
            line,
        )
        d.line(
            [(cx - a, cy + b), (cx - 0.1 * k, cy + b), (cx + 0.2 * k, cy - b), (cx + a, cy - b)],
            white,
            line,
        )
        for y in (cy - b, cy + b):
            tip = 0.2 * k
            d.polygon(
                [(cx + a + tip, y), (cx + a - 0.05 * k, y - tip), (cx + a - 0.05 * k, y + tip)],
                fill=white,
            )
    elif name == "repeat":
        d.ellipse((cx - k, cy - k, cx + k, cy + k), fill=(255, 255, 255, 40))
        d.arc((cx - 0.45 * k, cy - 0.45 * k, cx + 0.45 * k, cy + 0.45 * k), 200, 520, white, line)
        tip = 0.18 * k
        x, y = (
            cx + 0.45 * k * math.cos(math.radians(200)),
            cy + 0.45 * k * math.sin(math.radians(200)),
        )
        d.polygon([(x - tip, y), (x + tip, y), (x, y - 1.3 * tip)], fill=white)


def star(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, width: int) -> None:
    pts = []
    for k in range(10):
        a = math.radians(-90 + 36 * k)
        rr = r if k % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.line([*pts, pts[0]], fill=(255, 255, 255, 230), width=width, joint="curve")


@lru_cache(maxsize=2)
def chrome(song: Song, style: Style, art_stamp: float = 0.0) -> tuple[Image.Image, tuple[int, int]]:
    """Everything in the left column that stays still and lies over the CD: the cover with its badge,
    the title lines, the two buttons, the bar's track and the controls; and where it goes."""
    s = style.album_scale
    x0, y0, x1, y1 = column(style)
    pad = round(20 * s)
    x0, y0 = x0 - pad, y0 - pad
    layer = Image.new("RGBA", ((x1 + pad - x0) * SS, (y1 + pad - y0) * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def at(x: float, y: float) -> tuple[float, float]:
        px, py = scaled(x, y, style)
        return (px - x0) * SS, (py - y0) * SS

    face = fonts.resolve(style.font)
    cover = box(COVER, style)
    side = cover[2] - cover[0]
    shade = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sx, sy = at(COVER[0], COVER[1])
    ImageDraw.Draw(shade).rounded_rectangle(
        (sx, sy + 14 * s * SS, sx + side * SS, sy + (side + 18 * s) * SS),
        COVER_RADIUS * s * SS,
        fill=(0, 0, 0, 120),
    )
    layer.alpha_composite(shade.filter(ImageFilter.GaussianBlur(22 * s * SS)))
    art = render.square(song.art, art_stamp)
    layer.alpha_composite(
        rounded_cover(art, side * SS, round(COVER_RADIUS * s * SS)), (round(sx), round(sy))
    )
    if song.released:
        f = render.font(face, BADGE_PX * s * SS, 700)
        bx, by, bh = BADGE
        left, top = at(COVER[0] + bx, COVER[1] + by)
        height = bh * s * SS
        width = f.getlength(song.released) + height
        d.rounded_rectangle(
            (left, top, left + width, top + height), height / 2, fill=(30, 30, 34, 190)
        )
        d.text(
            (left + width / 2, top + height / 2),
            song.released,
            font=f,
            fill=(255, 255, 255, 240),
            anchor="mm",
        )
    room = (BUTTONS[0][0] - BUTTON_R - 16 - TEXT_X) * s * SS
    for text, y, size, weight, fill in (
        (song.title, TITLE_Y, TITLE_PX, 700, (255, 255, 255, 240)),
        (subtitle(song), ALBUM_Y, ALBUM_PX, 400, (255, 255, 255, 150)),
    ):
        f = render.font(face, size * s * SS, weight)
        while f.getlength(text) > room and f.size > size * s * SS * 0.7:
            f = render.font(face, f.size * 0.94, weight)
        if f.getlength(text) > room:
            while text and f.getlength(text + "…") > room:
                text = text[:-1]
            text += "…"
        d.text(at(TEXT_X, y), text, font=f, fill=fill, anchor="lm")
    for k, (bx, by) in enumerate(BUTTONS):
        cx, cy = at(bx, by)
        r = BUTTON_R * s * SS
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 46))
        if k == 0:
            star(d, cx, cy, r * 0.55, max(2, round(r * 0.1)))
        else:
            for dx in (-0.42, 0, 0.42):
                dot = r * 0.1
                d.ellipse(
                    (cx + dx * r - dot, cy - dot, cx + dx * r + dot, cy + dot),
                    fill=(255, 255, 255, 230),
                )
    left, mid = at(TEXT_X, BAR_Y)
    right, _ = at(TEXT_RIGHT, BAR_Y)
    half = BAR_H * s * SS / 2
    d.rounded_rectangle((left, mid - half, right, mid + half), half, fill=(255, 255, 255, 70))
    for name, x in CONTROLS:
        icon(d, name, *at(x, CONTROLS_Y), ICON * s * SS)
    return layer.reduce(SS), (x0, y0)


def progress(t: float, song: Song, style: Style) -> tuple[Image.Image, tuple[int, int]]:
    """The bar's filled part and the two times, which change with t."""
    s = style.album_scale
    x0, y0 = (round(v) for v in scaled(TEXT_X - 4, BAR_Y - BAR_H, style))
    x1, y1 = (round(v) for v in scaled(TEXT_RIGHT + 4, TIMES_Y + TIMES_PX, style))
    layer = Image.new("RGBA", ((x1 - x0) * SS, (y1 - y0) * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def at(x: float, y: float) -> tuple[float, float]:
        px, py = scaled(x, y, style)
        return (px - x0) * SS, (py - y0) * SS

    left, mid = at(TEXT_X, BAR_Y)
    right, _ = at(TEXT_RIGHT, BAR_Y)
    half = BAR_H * s * SS / 2
    done = share(t, song)
    if done > 0:
        d.rounded_rectangle(
            (left, mid - half, max(left + 2 * half, left + (right - left) * done), mid + half),
            half,
            fill=(255, 255, 255, 235),
        )
    f = render.font(fonts.resolve(style.font), TIMES_PX * s * SS, 500)
    played, left_text = times(t, song)
    d.text(at(TEXT_X, TIMES_Y), played, font=f, fill=(255, 255, 255, 170), anchor="lm")
    d.text(at(TEXT_RIGHT, TIMES_Y), left_text, font=f, fill=(255, 255, 255, 170), anchor="rm")
    return layer.reduce(SS), (x0, y0)


@lru_cache(maxsize=2)
def disc(song: Song, style: Style, art_stamp: float = 0.0) -> render.Disc | None:
    if not style.show_cd:
        return None
    r = round(DISC_R * style.album_scale)
    return render.Disc(render.disc_print(render.square(song.art, art_stamp), r), r)


def disc_at(found: render.Disc, turn: float) -> Image.Image:
    out = found.at(turn)
    out.putalpha(out.getchannel("A").point(lambda v: round(v * DISC_ALPHA)))
    return out


@lru_cache(maxsize=4)
def panel_at(pos: float, lines: tuple[tuple[float, str], ...], style: Style) -> Image.Image:
    """The lyric list with row `pos` on the panel's middle row, left aligned."""
    g = render.geometry(style)
    k = style.panel_scale
    x0, y0, x1, y1 = g.panel
    pw, ph = (x1 - x0) * SS, (y1 - y0) * SS
    layer = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    face = fonts.resolve(style.font)
    row = g.row * SS
    mid = ph / 2
    room = pw - 8 * k * SS
    top, bottom = SOFT[0] * k * SS, SOFT[1] * k * SS
    lo = math.floor(pos)
    for n in range(max(0, lo - math.ceil(VISIBLE)), min(len(lines), lo + math.ceil(VISIBLE) + 2)):
        text = lines[n][1]
        if not text:
            continue
        off = n - pos
        near = max(0.0, 1 - abs(off))
        y = mid + off * row
        edge = min(1.0, max(0.0, y / top), max(0.0, (ph - y) / bottom))
        alpha = round((OTHER_LEVEL + (255 - OTHER_LEVEL) * near) * edge)
        if alpha <= 0:
            continue
        factor, rows = render.fit(text, face, NOW_PX * k * SS, room, row)
        size = round(NOW_PX * k * SS * factor * 2) / 2
        weight = round((OTHER_WEIGHT + (NOW_WEIGHT - OTHER_WEIGHT) * near) / 50) * 50
        f = render.font(face, size, weight)
        for m, part in enumerate(rows):
            at = y + (m - (len(rows) - 1) / 2) * size * render.ROW_PITCH
            d.text(
                (0, at),
                part,
                font=f,
                fill=(*render.hex_rgb(style.lyric_colour), alpha),
                anchor="lm",
            )
    out = layer.reduce(SS)
    return softened(out, round(SOFT[0] * k), round(SOFT[1] * k))


def softened(layer: Image.Image, top: int, bottom: int) -> Image.Image:
    """The top `top` and the bottom `bottom` pixels blurred more the nearer they are to the edge."""
    if top <= 0 or bottom <= 0 or layer.height < top + bottom:
        return layer
    blurred = layer.filter(ImageFilter.GaussianBlur(SOFT_BLUR))
    ramp = Image.linear_gradient("L")  # 0 at the top to 255 at the bottom
    mask = Image.new("L", layer.size, 0)
    mask.paste(ImageChops.invert(ramp).resize((layer.width, top)), (0, 0))
    mask.paste(ramp.resize((layer.width, bottom)), (0, layer.height - bottom))
    return Image.composite(blurred, layer, mask)


@lru_cache(maxsize=2)
def base(song: Song, style: Style, art_stamp: float = 0.0) -> Image.Image:
    """The background: the cover blurred and darkened, as the wide video's, without its title."""
    return render.backdrop(
        song.art, art_stamp, style.blur, style.dim, style.tone, style.vignette
    ).copy()


class Painter:
    """The frames of one song and style in the player look. The CD turns, the bar and the times move
    and the list scrolls; the rest is drawn once."""

    def __init__(
        self,
        lines: tuple[tuple[float, str], ...],
        song: Song,
        style: Style,
        moving: tuple[str, anim.Timing] | None = None,
    ):
        self.lines, self.song, self.style = lines, song, style
        self.g = render.geometry(style)
        stamped = render.stamp(song.art)
        self.bg = base(song, style, stamped)
        self.front, self.front_at = chrome(song, style, stamped)
        self.disc = disc(song, style, stamped)
        s = style.album_scale
        cx, cy = scaled(*DISC_C, style)
        r = round(DISC_R * s)
        self.disc_xy = (round(cx) - r, round(cy) - r)
        self.turning = self.disc is not None and style.spin > 0
        if self.disc is not None and not self.turning:
            render.place(self.bg, disc_at(self.disc, 0.0), *self.disc_xy)
        if not self.turning:
            render.place(self.bg, self.front, *self.front_at)
        self.timing = self.pictures = None
        if moving:
            self.timing, self.pictures = moving[1], anim.Shared(*moving)
        elif song.anim and (found := anim.at(song.anim, style.anim_fps, style.anim_scale)):
            self.timing, self.pictures = found
        if self.timing:
            self.anim_box = anim.box(self.timing.size, style.anim_x, style.anim_y)
        self.intro = render.intro_end(lines, style)
        self.card = render.intro_card(song, style, stamped) if self.intro > 0 else None
        self.steps = render.opening_steps(lines, style)
        self.opening = render.opening_panel(song, style) if self.steps else None
        self.last: tuple = (None, b"")

    def state(self, t: float) -> tuple:
        cover = render.veil(t, self.intro)
        if cover == 1:
            return (None, None, None, None, 1.0, 0.0, None)
        turn = round(360 * t / self.style.spin, 2) if self.turning else None
        # The bar's fill moves by a fraction of a pixel on each frame; the times change each second.
        bar = round(share(t, self.song) * 4000), times(t, self.song)
        picture = self.timing.index(t) if self.timing else None
        title = render.opening_at(t, self.steps)
        glow = render.light_at(t) if self.style.drift else None
        pos = render.panel_position(t, self.lines, self.style)
        return turn, pos, bar, picture, cover, title, glow

    def image(self, t: float, state: tuple | None = None) -> Image.Image:
        turn, pos, _, picture, cover, title, glow = state or self.state(t)
        if cover == 1:
            return self.card.copy()
        img = self.bg.copy()
        if picture is not None and not self.style.anim_above:
            render.place(img, self.pictures[picture], *self.anim_box[:2])
        if turn is not None:
            render.place(img, disc_at(self.disc, turn), *self.disc_xy)
            render.place(img, self.front, *self.front_at)
        bar, at = progress(t, self.song, self.style)
        render.place(img, bar, *at)
        render.place(img, panel_at(pos, self.lines, self.style), *self.g.panel[:2])
        if title > 0:
            render.place(img, render.faded(self.opening, title), *self.g.panel[:2])
        if picture is not None and self.style.anim_above:
            render.place(img, self.pictures[picture], *self.anim_box[:2])
        if cover > 0:
            img = Image.blend(img, self.card, cover)
        if glow is not None:
            img = ImageChops.add(img, render.light(glow))
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
    lines: tuple[tuple[float, str], ...],
    song: Song,
    style: Style,
    moving: tuple[str, anim.Timing] | None = None,
) -> Painter:
    key = (lines, song, style, moving, render.stamp(song.art), anim.stamps(song.anim))
    found = _painters.get(key)
    if found is None:
        if len(_painters) >= 2:
            _painters.pop(next(iter(_painters)))
        panel_at.cache_clear()  # a font file replaced under the same name
        found = _painters[key] = Painter(lines, song, style, moving)
    return found


def forget() -> None:
    for cached in (chrome, disc, base, panel_at):
        cached.cache_clear()
    _painters.clear()


def boxes(style: Style) -> dict[str, tuple[int, ...]]:
    return {"album": column(style), "panel": render.geometry(style).panel}
