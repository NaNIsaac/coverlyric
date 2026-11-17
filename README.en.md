# coverlyric

[한국어 (README.md)](README.md)

Make a lyric video from a song, a square cover and the lyrics. A double-click opens a page in your
browser; everything runs on your own computer.

![The page with the demo song](docs/screenshots/4-look.png)

- **Look:** the cover sits in a clear CD case with the disc half out and turning (both switchable),
  or as a round cover. The lyrics scroll on the right, and the current line sits on a coloured band.
- **Live still preview:** drag the album, the lyrics, the title and the playback bar to move them, and
  drag a corner to resize. Pick the font, band colour, background blur and darkness.
- **Timing, three ways:** tap along while the song plays, then nudge lines by 0.1 s; import an SRT,
  LRC or VTT file; or copy a ready prompt into your own chat AI and paste back its SRT. Imported lines
  are checked against your lyrics, and lines that differ are marked.
- **Output:** an mp4 (1920x1080, 30 fps, H.264 + AAC), a 1280x720 thumbnail, and the timing as LRC
  and SRT.

## Install and start

On Windows, download [coverlyric-main.zip](https://github.com/NaNIsaac/coverlyric/archive/refs/heads/main.zip), unzip it, open the `coverlyric-main` folder
and double-click `가사영상 만들기.bat`. The
first start downloads [uv](https://docs.astral.sh/uv/), Python, ffmpeg and the packages (about 150 MB,
about 300 MB on disk), which takes from under a minute to a few minutes. No administrator rights
are needed. Later starts take a few seconds.

With uv already installed, from the repository folder:

<!-- test -->
```sh
uv run coverlyric still src/coverlyric/demo/demo.json --at 7 --out demo-still.png
```

This draws one frame of the demo song. `uv run coverlyric` opens the page.

## Command line

```sh
uv run coverlyric                         # open the page (the default)
uv run coverlyric app --home <folder>     # keep work and videos in <folder>
uv run coverlyric still <project.json> --at 30 --out still.png
uv run coverlyric render <project.json> --out video.mp4 [--clip 10,20]
```

A project file is what the page saves in `작업 중/project.json`: paths to the song and cover, the
lines with their start times, and the style. Finished videos go to `만든 영상/`.

## Fonts

The bundled fonts are under the SIL Open Font License 1.1; each licence is next to its font in
`src/coverlyric/fonts/`:

| Font | Licence file |
|---|---|
| Noto Sans KR | `OFL-NotoSansKR.txt` |
| NanumGothic Bold | `OFL-NanumGothic.txt` |
| Do Hyeon | `OFL-DoHyeon.txt` |
| Black Han Sans | `OFL-BlackHanSans.txt` |
| Nanum Brush Script | `OFL-NanumBrushScript.txt` |
| East Sea Dokdo | `OFL-EastSeaDokdo.txt` |

The page also lists the fonts installed on the computer that can write Korean, and takes any font
file.

## Limits

- The chat-AI way sends the song to that AI service. The other two ways keep everything local.
- A render takes about one to two times the song's length on a recent laptop.
- Automatic timing on the computer itself is not in this version.

## Licence

MIT for the code (`LICENSE`); the fonts keep their own licences.
