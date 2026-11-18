# coverlyric for agents

Exact commands for the common jobs. Run them from the repository folder with `uv run`, or with
`coverlyric` once installed. Add `--json` to get one JSON object on stdout; progress goes to stderr.
Exit codes: 0 done, 1 failed (`error` in the JSON), 2 wrong arguments, 3 not enough memory.

A project is a folder: `project.json`, `song.*`, `cover.*`, and after a render `<title>.mp4`, `.srt`,
`.lrc`, `.png`.

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
