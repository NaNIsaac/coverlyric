# coverlyric for agents

Exact commands for the common jobs. Run them with `uv run` from a source folder
([run from source](cli.en.md#run-from-source)). Add `--json` to get one JSON object on stdout;
progress goes to stderr. Every option and the exit codes are in the [command line](cli.en.md) page.

A project is a folder: `project.json`, `song.*`, `cover.*`, and after a render `<title>.mp4`, `.srt`,
`.lrc`, `.png`.

## Make a video in one go

```sh
uv run --extra auto coverlyric make --audio song.wav --cover cover.png --lyrics lyrics.txt --title "Demo" --lead 1 --out videos --json
```

Everything goes into `videos/Demo/`. The summary has `video`, `srt`, `lrc`, `png`, `project`,
`model`, `sung`, `placed`, `unplaced` and `doubtful` (each `[{"n", "time", "text"}]`) and `seconds`
per step. With subtitles that already have times, `--timing file.srt` replaces `--lyrics` and nothing
is listened to.

## Fix a line that was not found

```sh
uv run --extra auto coverlyric words videos/Demo --from 1:10 --to 1:20 --json
uv run coverlyric project lines videos/Demo --set 12=1:11.8 --json
uv run coverlyric render videos/Demo --json
```

`words` lists `{"word", "start", "end", "prob"}` in song time. Find the line's first word and set its
start.

## Time an existing project again

```sh
uv run --extra auto coverlyric auto videos/Demo --apply --json
```

Without `--apply` it only shows the times. The notes are saved with the project, so `project show`
lists them later.

## Make a project

```sh
uv run coverlyric project new songs/demo --audio song.wav --cover cover.png --lyrics lyrics.txt --title "Demo" --json
```

Square-bracket marks (`[Verse 1]`) and `#` lines are dropped from the lyrics; `--keep-tags` keeps
them.

## Look at it

```sh
uv run coverlyric project show songs/demo --json
```

`lines` holds `{"n", "time", "text"}` and, for lines automatic timing was unsure of, `note`
(`unplaced`, `doubtful`, `differs`) and `heard`. `time` is `null` until the line has one.

## Put times in

```sh
uv run coverlyric project lines songs/demo --import timing.srt --json
```

## Fix lines

```sh
uv run coverlyric project lines songs/demo --set 12=1:11.8 --json     # one line's start
uv run coverlyric project lines songs/demo --shift -0.2 --json        # every timed line
uv run coverlyric project lines songs/demo --text 12="new words" --json
```

Setting a line's time removes its note.

## Change the look or the output

```sh
uv run coverlyric project set songs/demo lead=1 tail=2 height=720 fps=30 fade=on --json
```

`lead` and `tail` are seconds of silence before and after the song in the video; the lyric times in
the project stay song times. An unknown key fails with exit 2 and lists the keys.

## Check one frame, then render

```sh
uv run coverlyric still songs/demo --at 1:05 --json
uv run coverlyric render songs/demo --clip 1:00,1:10 --quick --out check.mp4 --json
uv run coverlyric render songs/demo --json
```

The full render answers with `video`, `srt`, `lrc`, `png` and `seconds`. A render refuses lines
without a time (exit 1, the first such line in `error`).

## Make a Short

```sh
uv run coverlyric chorus songs/demo --length 30 --apply --json
uv run coverlyric render songs/demo --json
```

`chorus` finds the block of lines repeated most and, with `--apply`, makes the project a Short
(1080x1920, 30 fps; an upright project keeps its ratio) of `from` to `to`; without a repeated line it
fails with exit 1. To pick the part and the look by hand:
`project set songs/demo shape=square fps=30 lyric_edge=outline clip_from=42 clip_to=72 loop=true
bars=true "bars_top=Title - Artist"`. `shape` is `tall` (9:16), `square` (1:1) or `portrait` (4:5);
the video is `<title>_shorts.mp4`, `_1x1.mp4` or `_4x5.mp4`. `upright_look=disc disc_wear=worn
highlight=letter` gives the turning CD and the lit letter; letter times are `letters` in the project
file ([command line](cli.en.md)). `project set songs/demo video=clip.mp4` puts the lyrics over that
video in any shape; the `video_*` keys set its start, end, sound and the text's colours, band and
place.
`sections songs/demo --length 30` lists loop sections a whole number of bars long and
`--apply N` makes the project a looping Short of one; `align songs/demo` saves when each letter is
sung, for `highlight=letter`. Both need the `align` extra ([command line](cli.en.md)).
