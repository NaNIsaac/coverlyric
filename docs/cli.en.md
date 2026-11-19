# Command line

[한국어](cli.md) · [Back](../README.en.md)

With [uv](https://docs.astral.sh/uv/) installed, run it from the repository folder.

## The page

```sh
uv run coverlyric                         # open the page (default)
uv run coverlyric app --home <folder>     # keep work and videos in <folder>
uv run coverlyric app --port 8765 --no-browser
```

## Everything at once

```sh
uv run --extra auto coverlyric make --audio song.mp3 --cover cover.png --lyrics lyrics.txt --title "Title" --out videos
```

One folder, `videos/Title/`, gets copies of the song and cover, `project.json`, `Title.mp4`, `.srt`,
`.lrc` and `.png`. The lyrics are timed by listening to the song. With subtitles that already have
times, use `--timing <subtitles>` in place of `--lyrics`; then nothing is listened to.

| Option | Means |
|---|---|
| `--artist ..` | the artist |
| `--lead 1` / `--tail 2` | seconds of silence before and after the song in the video |
| `--height 720` / `--fps 30` | picture height (1080, 720) and frames per second (24, 30) |
| `--style <JSON or file>` | look settings, e.g. `'{"fade": false}'` |
| `--model small` | the listening model (`small`, `base`, `tiny`); a smaller one is used when memory is short |
| `--keep-tags` | keep square-bracket marks and `#` lines |
| `--strict` | exit code 4 when a line was not found or needs a check |

At the end it prints a summary: the file paths, the number of lyric lines (`sung`), the lines found
by listening (`placed`), the number and time of each line not found and put between its neighbours
(`unplaced`) and of each line within 1 s of the one before (`doubtful`), the model used and the
seconds each step took.

Automatic timing needs the `auto` extra (faster-whisper). `uv run --extra auto` installs it the first
time, and the listening model is downloaded the first time it is used (`small` about 460 MB). The
song is listened to on this computer only.

## Making a video from a project folder

A project is one folder: `project.json`, the song (`song.*`) and the cover (`cover.*`). The video
and its `.srt`, `.lrc` and `.png` thumbnail are saved in the same folder. Where a command takes
`<project>`, give the folder or its `project.json`.

| Command | Does |
|---|---|
| `project new <folder> --audio <song> --cover <cover> [--lyrics <file>] [--title ..] [--artist ..] [--keep-tags]` | Copies the song and cover into a new project. Lyrics as text, SRT, LRC or VTT. `--keep-tags` keeps square-bracket marks and `#` lines. |
| `project show <project>` | Title, the look settings that differ from the default, each line with number, time and text, and the lines to check. |
| `project set <project> key=value ...` | `title`, `artist`, `clean_tags` and the look settings (`lead`, `tail`, `height`, `fps`, `fade`, `band`, ...). An unknown key is refused with the list of keys. A Short is `shape=tall fps=30 lyric_edge=outline`, its part `clip_from=42 clip_to=72` (seconds, `clip_to=0` for the end), and `loop=true` joins its end to its start. |
| `project lines <project> --shift -0.3` | Moves every timed line. |
| `project lines <project> --set 5=1:12.4 --text 5="new words"` | Changes one line's time or text. Times take `72.4` or `1:12.4`. |
| `project lines <project> --import <subtitles>` / `--from-lyrics <file>` | Lines and times again from a subtitle file, or lines without times from a lyrics file. |
| `auto <project> [--model ..] [--apply] [--strict]` | Listens to the song and times each line. Shows the result and the lines to check; `--apply` saves it into the project. |
| `words <song or project> --from 1:10 --to 1:20 [--model ..]` | The words heard in that stretch with their start and end times, for timing a line that was not found. |
| `render <project> [--out <mp4>] [--clip 1:00,1:10] [--quick]` | Makes the video. A whole video also gets `.srt`, `.lrc` and `.png` beside it. The default name is `<title>.mp4` in the project folder. |
| `still <project> [--at 1:05] [--out <png>]` | Saves one frame as an image. |

Every command takes `--json` and then prints one JSON object. Progress goes to standard error.
Output is UTF-8 whatever the console is set to.

| Exit code | Meaning |
|---|---|
| 0 | done |
| 1 | failed (the reason on standard error, and as `error` with `--json`) |
| 2 | the command was given wrong (unknown key, a value that is not a time, no such line) |
| 3 | not enough memory |
| 4 | made, but some lines need a check (only with `--strict`) |

Trying it on the demo song (`timing.srt` is your own subtitle file):

```sh
uv run coverlyric project new demo-song --audio src/coverlyric/demo/tone.wav --cover src/coverlyric/demo/cover.png --title "Demo song"
uv run coverlyric project lines demo-song --import timing.srt
uv run coverlyric project set demo-song lead=1 height=720
uv run coverlyric render demo-song
```

`가사영상 만들기.bat` runs `tools/start.ps1`. It installs uv into `%LOCALAPPDATA%\coverlyric\uv` if
it is missing, then opens the page with `uv run --frozen --no-dev coverlyric`.

## Project file

The page saves the work in `작업 중/project.json`: the song and cover paths, each line's start time
and text, the look (`style`) and the lines automatic timing asked to check (`notes`). Videos go to
the save folder (`만든 영상/` at first). The command-line commands work on that folder too.

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
