# Command line

[한국어](cli.md) · [Back](../README.en.md)

To just use the program, install it with the setup in the [README](../README.en.md#install). This
page is for running it from source and for the commands that make a video without the page.

## Run from source

With [uv](https://docs.astral.sh/uv/) and git, get the repository and run it from its folder. `uv`
installs Python and the packages the first time.

```sh
git clone https://github.com/NaNIsaac/coverlyric
cd coverlyric
uv run coverlyric
```

Make a project folder from the demo song and draw one frame:

```sh
uv run coverlyric project new demo-song --audio src/coverlyric/demo/tone.wav --cover src/coverlyric/demo/cover.png --title "데모 노래"
uv run coverlyric still demo-song --at 7
```

The tests run with `uv run pytest`.

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
| `project new <folder> --audio <song> --cover <cover> [--lyrics <file>] [--title ..] [--artist ..] [--keep-tags]` | Copies the song and cover into a new project. Given a video as the song (a phone's screen recording, say), it keeps only the sound, from the sound's own start, as `song.flac`, and says how late the sound started after the picture. Lyrics as text, SRT, LRC or VTT. `--keep-tags` keeps square-bracket marks and `#` lines. |
| `project show <project>` | Title, the look settings that differ from the default, each line with number, time and text, and the lines to check. |
| `project set <project> key=value ...` | `title`, `artist`, `album`, `released` (the player's date on the cover), `clean_tags` and the look settings (`lead`, `tail`, `height`, `fps`, `fade`, `band`, ...). An unknown key is refused with the list of keys. An upright video is `shape=tall` (9:16), `square` (1:1) or `portrait` (4:5) with `fps=30 lyric_edge=outline`, its part `clip_from=42 clip_to=72` (seconds, `clip_to=0` for the end), `loop=true` joins its end to its start (`loop_lead=3` seconds, or `loop_lead_line=true` for the line before, ends it with the song just before the part), and the bands are `bars=true bars_colour=#000000 bars_height=0.12 bars_top=.. bars_bottom=.. bars_size=48`, the turning CD behind the lyrics `upright_look=disc` (worn with `disc_wear=worn`), and lighting the letter being sung `highlight=letter`. The 16:9 player look is `layout=player`. How much the case's plastic softens and greys what shows through it: `case_haze=0.15` (the default; `0` is clear, and a tilted case is always clear). A title lettered by hand in place of the typed one in a long intro: `title_image=<picture>` (dark lettering on white or on clear, copied in as `title.png` and so on; `title_image=` drops it). Lyrics over a video in place of the cover: `video=<video file>` (copied into the project folder as `video.mp4` and so on; `video=` drops it), `video_offset=-1.5` (seconds) moves its start, a shorter video `video_end=loop` or `hold`, its own sound `video_sound=true`, the text `video_ink=#ffffff video_lit=#ffd23f video_edge=shadow` (or `none`), a band `video_band=paper` (`none`, `dark`) with `video_band_alpha=0.85`, the place `video_text=bottom` (or `middle`, or `low`: lower, where a Short's caption can cover it). |
| `chorus <project> [--length 30] [--apply]` | The block of lines repeated most, as a Short's part (`from`, `to`). `--apply` makes the project an upright video of that part (9:16 if it was 16:9). Fails when no line comes back. |
| `sections <project> [--length 30] [--apply N]` | Up to 8 loop sections a whole number of bars long, near the length, the strongest opening first. A section starts on the beat a line starts on (or the beat before it) and gets one bar more or less when that ends it just before the next line comes in. `--apply N` makes the project a looping upright video of section N (`loop=true`). Needs the `align` extra. |
| `align <project> [--from 1:35] [--to 2:42]` | When each letter of the lines starting in that stretch is sung, saved as the project's `letters` (used by `highlight=letter`). By default an upright project's part, else the whole song. The vocals are separated from the song (demucs) and each letter is placed as one syllable (torchaudio MMS_FA). A line whose first letter comes more than 0.6 s after the line starts, whose last letter reaches the next line, or whose letters are bunched into less than 0.05 s each is placed again: from the starts of the words heard in it when the `auto` extra is installed, else evenly. It says how many lines it placed again, and `project show` marks them. The first run downloads the models, about 1.2 GB, once. Needs the `align` extra. |
| `project lines <project> --shift -0.3` | Moves every timed line. |
| `project lines <project> --set 5=1:12.4 --text 5="new words"` | Changes one line's time or text. Times take `72.4` or `1:12.4`. |
| `project lines <project> --import <subtitles>` / `--from-lyrics <file>` | Lines and times again from a subtitle file, or lines without times from a lyrics file. Letter times (`letters`) of lines whose number or text no longer match are dropped. |
| `project lines <project> --letters 5=72.4,72.7,73.1` | Sets when each letter of line 5 is sung, saved in `letters` (used by `highlight=letter`). One time per letter or mark but spaces, or one per letter and digit (a mark takes the time of the letter before it). Once the line's text changes, the times are no longer used. |
| `srt <project> [--out <folder>]` | Saves the whole song's `<title>.srt` on the 16:9 video's clock and, for an upright project, that video's `<title>_shorts.srt`. The upright video's times count from the start of its part; with a lead-in at the end (`loop_lead`) its line comes last. The default folder is the project folder. |
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

## The installed program

The Start menu shortcut runs `가사영상 만들기.bat`, which runs `tools/start.ps1`. It runs
`uv run --frozen --no-dev coverlyric` with the `uv\uv.exe` the installer ships. The data folder is
`COVERLYRIC_HOME`, else the first line of `%LOCALAPPDATA%\coverlyric\data-folder.txt` (written by the
installer), else `Documents\coverlyric`.

`align` and `sections` need the `align` extra. torch 2.7 runs on Python 3.12 and 3.13 only, so they run in an environment of their own:

```powershell
uv run --isolated --python 3.13 --extra align coverlyric align <project>
```

Without it they print this command and exit 1.

## Project file

The page saves the work in `작업 중/project.json`: the song and cover paths, each line's start time
and text, the look (`style`) and the lines automatic timing asked to check (`notes`). Videos go to
the save folder (`만든 영상/` at first). The command-line commands work on that folder too.

The videos made from the song are listed in `outputs`, each with its `id`, look (`style`), moving
picture (`anim`) and video (`video`); `current` is the one being worked on. Lines and letter times
belong to the song, once, and every output uses them. An older file without `outputs` opens as one
output.

`letters` holds when each letter of a line is sung, for `highlight=letter`. An entry is
`{"n": 3, "text": "아리랑 아리랑", "times": [12.0, 12.3, ...]}`: the line number from 1, the line's
text when it was timed, and seconds, one per letter but spaces or one per letter and digit. In the
second case a punctuation mark takes the time of the letter before it. An entry whose line text has
changed since, or whose line has no time, is not used.

## Environment variables

| Variable | Meaning |
|---|---|
| `COVERLYRIC_HOME` | folder for work and videos (same as `--home`) |
| `COVERLYRIC_NO_BROWSER` | any value: do not open the browser |
| `COVERLYRIC_ENCODER` | H.264 encoder (`libx264`, `h264_nvenc`, `h264_qsv`, `h264_amf`); default: the first that works on this PC |

## Fonts

The bundled fonts are under the SIL Open Font License 1.1; each licence file is next to its font in
`src/coverlyric/fonts/`: Noto Sans KR, NanumGothic Bold, Do Hyeon, Black Han Sans, Nanum Brush Script,
East Sea Dokdo.
