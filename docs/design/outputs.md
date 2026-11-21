# Design note: one song, many outputs

Status: reviewed and accepted; code follows in the four pull requests below. This is phase 1 of the restructure. Phase 2 adds looks and
presets, phase 3 effect layers, and phase 4 the page.

## Problem

A project today is one song with one `Style`. A 16:9 video and a Short of the same song are two project
folders: the Short is made by copying the project and changing its style. Line times or letter
times fixed in one copy are not fixed in the other, so the two drift apart.

## Model

`project.json` holds the song once and a list of outputs.

```json
{
  "format": 2,
  "audio": "song.flac", "art": "cover.png", "title": "...", "artist": "...",
  "album": "", "released": "", "duration": 182.4, "clean_tags": true,
  "title_image": "",
  "lines": [[12.3, "..."]], "letters": [], "notes": [],
  "outputs": [
    {"id": "wide", "style": {"shape": "wide", "...": "..."}, "anim": [], "video": ""},
    {"id": "short", "style": {"shape": "tall", "clip_from": 42.0, "clip_to": 72.0}, "anim": [], "video": ""}
  ],
  "current": "wide"
}
```

- Song level, kept once: audio, cover, title, artist, album, released, duration, `clean_tags`,
  `title_image`, lines, letters, notes. These are all timing and identity data. A Short windows the
  same lines through its clip and never copies them.
- Output level: `style`, plus the moving picture `anim` and the `video` under the lyrics. These two
  belong to one output's look: a picture added to a Short should not appear on the 16:9 video.
- `id` is a short name unique in the project (`wide`, `short`, `short-2`, ...). It also names the
  file (below).
- `current` is the output the page and the CLI work on when none is named.
- In phase 1, `style` stays the flat `Style` dictionary, written as today. Phase 2 replaces it with
  `{"look": ..., "preset": ..., "set": {overrides}}`. The output list does not change then.

What kind an output is (16:9, upright, over a video) is read from its style (`shape`, `video`), as now.
Phase 1 adds no kind field, so there is nothing that could disagree with the style.

## Migration

- A file without `format` is format 1. It loads as one output: `id` is `wide` for a 16:9 shape,
  otherwise `short`, `square` or `portrait`. `style`, `anim` and `video` move into that output, and
  `current` is that id. The frames rendered from it are identical (test: render the demo and an upright
  demo before and after loading, and compare the bytes).
- Saving writes format 2. For one release it also writes the current output's `style`, `anim` and
  `video` at the top level. A coverlyric one release older can then still open the file and render
  that output. This mirror is dropped in the release after phase 2.
- Two existing folders of one song, a 16:9 and its Short copy, can be joined with
  `output import <project> <other project>`. The other project's output is added, and its lines and
  letters are kept only when they equal this project's (otherwise the command refuses and lists the
  lines that differ).

## Files

Each output renders to `<title><suffix>.mp4` next to the others. The suffix is as now (`_shorts`, `_1x1`,
`_4x5`, none for 16:9) for the first output of a shape. Another output of the same shape adds its id:
`<title>_shorts-2.mp4`. Thumbnails, LRC and SRT files follow the video's name, as `jobs.beside` does
now.

## Command line

- `output list <project>`: id, shape, clip, file name, and which one is current.
- `output show <project> [ID]`: the output's style and files, like `project show` for one output.
- `output add <project> ID [--from ID] [--shape tall|square|portrait|wide]`: a new output, copied from
  another one (default: the current one) with the shape changed. It becomes current.
- `output use <project> ID`, `output remove <project> ID` (the last output cannot be removed).
- `output import <project> <other project>` (above).
- `--output ID` on `render`, `still`, `srt`, `project set`, `chorus --apply` and `sections --apply`;
  without it, the current output. `project show` lists the outputs and keeps the current one's style
  where it is now, so scripts that read it do not break.
- `make` makes a project with one output, as now. Adding `--short 42,72` also adds a Short of that part.

## Page and jobs

- The server state gains `outputs` (id, shape, clip, file) and `current`. `update` writes style changes
  into the current output. `POST /api/output` takes `{"use": ID}`, `{"add": {"from": ID, "shape": ...}}`
  or `{"remove": ID}`.
- A render job carries the song and one output resolved to a style. `render-job` and the workers do not
  change. Rendering several outputs runs them one after another, in the same queue.
- Where outputs appear in 일반: the 만들기 step lists the outputs, one row each (shape, clip, file name),
  with the current one selected and one 만들기 button for it. The 화면 비율 choice becomes the way to add
  an output (choosing a shape the song has no output for adds one). Picking a row makes that output
  current for the whole page, so 꾸미기 shows its look. 일반 shows nothing more for outputs: no ids, no
  `import`, no file suffixes. Renaming and removing an output are in 고급.
- Phase 1 changes only the 만들기 step. The full layout, with outputs side by side and the look and
  preset picker, comes from the phase 4 design pass.

## Presets (phase 2, named now so the ids are stable)

The product ships neutral ids with plain Korean labels:

| id | label | look |
|---|---|---|
| `case-beat` | 케이스, 박자 | case, CD moved by the beat, letter fill, plastic haze |
| `case-quiet` | 조용한 케이스 | case, turning CD, line band |
| `round` | 둥근 표지 | the cover as a still round disc |
| `player` | 플레이어 | the music player look |
| `short` | 기본 쇼츠 | worn disc, letter highlight, hook lines on top |
| `short-quiet` | 조용한 쇼츠 | the cover behind the lyrics, line highlight |
| `video-captions` | 영상 자막 | lyrics over the user's own video |

The user's own names for these live in a local file outside the repository: `presets.json` in the
user's coverlyric config folder (`%APPDATA%\coverlyric` on Windows, `~/.config/coverlyric` elsewhere),
mapping an id to a label (`{"case-beat": "..."}`). The page shows that label in place of the shipped one
when the file has one. The file is read only, never written by coverlyric, and never needed. New songs
start from `case-beat` (phase 2).

## Automatic, never a setting

Precomputing, caches and the number of render workers are chosen by coverlyric from the machine (cores,
free memory) and the song. There is no setting, checkbox or command-line flag for them. Caches
(onsets, loudness, from phase 3) live in the project folder under `.cache/`, keyed by the audio file's
size and modification time. Everything in `.cache/` is derived from the project's own files and is
rebuilt when missing, so the folder is safe to delete at any time; the user docs say so. The
`COVERLYRIC_WORKERS` variable, documented today, becomes test-only and leaves the user docs.

## 일반 and 고급

Every key added in phases 1 to 3 goes to 고급 unless the owner places it in 일반. Phase 1 adds no style
keys. 일반 gains only the outputs list on 만들기 (above).

## Pull requests for phase 1

1. Model and migration: `Project` with outputs, format 2 save with the mirror, load of format 1.
   Tests: frames identical, round trip, older-reader mirror. No CLI or page change. `COVERLYRIC_WORKERS`
   leaves the cli docs (ko, en).
2. CLI: `output` commands and `--output`, `make --short`. Docs cli (ko, en).
3. Page: outputs on 만들기, `/api/output`, 화면 비율 adds or switches. Captures at 1366x768 and 900.
4. `output import` for existing Short copies, with the line check.

## Decided in review

- `anim` and `video` belong to each output.
- The top-level mirror is written for one release, then dropped.
- `COVERLYRIC_WORKERS` leaves the user docs.
- `.cache/` is derived and rebuildable, safe to delete.
