# Command line

[한국어](cli.md) · [Back](../README.en.md)

With [uv](https://docs.astral.sh/uv/) installed, run it from the repository folder.

## Commands

```sh
uv run coverlyric                         # open the page (default)
uv run coverlyric app --home <folder>     # keep work and videos in <folder>
uv run coverlyric app --port 8765 --no-browser
uv run coverlyric still <project.json> --at 30 --out still.png
uv run coverlyric render <project.json> --out video.mp4 [--clip 10,20]
```

`가사영상 만들기.bat` runs `tools/start.ps1`. It installs uv into `%LOCALAPPDATA%\coverlyric\uv` if
it is missing, then opens the page with `uv run --frozen --no-dev coverlyric`.

## Project file

The page saves the work in `작업 중/project.json`: the song and cover paths, each line's start time
and text, and the look (`style`). Videos go to `만든 영상/`.

## Environment variables

| Variable | Meaning |
|---|---|
| `COVERLYRIC_HOME` | folder for work and videos (same as `--home`) |
| `COVERLYRIC_NO_BROWSER` | any value: do not open the browser |
| `COVERLYRIC_ENCODER` | H.264 encoder (`libx264`, `h264_nvenc`, `h264_qsv`, `h264_amf`); default: the first that works on this PC |
| `COVERLYRIC_WORKERS` | processes that draw the frames (1-8); default: set from free memory |

## Fonts

The bundled fonts are under the SIL Open Font License 1.1; each licence file is next to its font in
`src/coverlyric/fonts/`:

| Font | Licence file |
|---|---|
| Noto Sans KR | `OFL-NotoSansKR.txt` |
| NanumGothic Bold | `OFL-NanumGothic.txt` |
| Do Hyeon | `OFL-DoHyeon.txt` |
| Black Han Sans | `OFL-BlackHanSans.txt` |
| Nanum Brush Script | `OFL-NanumBrushScript.txt` |
| East Sea Dokdo | `OFL-EastSeaDokdo.txt` |

The page also lists the fonts installed on the PC that can write Korean, and takes any font file.

## Tests

```sh
uv run pytest
```
