# coverlyric

[한국어](README.md)

A Windows program that makes a lyric video (mp4) from a song, its album cover and the lyrics. It
runs on Windows 10/11 with 4 GB of RAM or more. The page is in Korean.

## Install

1. [Download coverlyric (ZIP)](https://github.com/NaNIsaac/coverlyric/archive/refs/heads/main.zip)
2. Right-click the ZIP file → **Extract All**.
3. In the extracted folder, double-click `가사영상 만들기.bat`.
4. The first start downloads what it needs and takes 1-3 minutes. The terminal window stays open
   until the page opens in the browser.

If "Windows protected your PC" appears, click **More info** → **Run anyway**.

## Files

![Files group](docs/screenshots/1-files.png)

In **파일** (files) on the left rail, click **노래 파일 고르기** and **앨범 표지 고르기** (pick song,
pick cover), then type the title and the artist.

## Lyrics

In **가사** (lyrics), paste the lyrics and click **가사 넣기** (add lyrics). Each line becomes one line
on screen. Blank lines are left out; with **대괄호 표시와 # 줄 빼기** (drop bracket marks and # lines)
on, lines starting with `#` and square-bracket marks such as `[Verse 1]` are left out too.

## Timing

![Auto timing](docs/screenshots/3-auto.png)

Lower in **가사**, under **타이밍**, click **자동 맞추기** → **자동으로 맞추기** (auto timing). Lines
with a dashed border are checked with **▶** and fixed.

On a PC with little memory, pick **채팅 AI로 맞추기** (time it with a chat AI): copy the prompt,
give it to a chat AI with the song file, and paste the subtitles it returns. The song file goes to
that AI service.

## Look

![Look](docs/screenshots/4-look.png)

Drag the album, lyrics and title in the preview; drag a corner to resize. Font and album style are
in **모양** (look), band colour and background in **색** (colour).

## Video

Click **이대로 영상 만들기** (make the video) → **확인**. The video and its subtitle files (SRT, LRC)
are saved in the **저장 위치** (save folder): `만든 영상` in the program folder at first; **바꾸기**
(change) picks another folder and **열기** (open) opens it. If the song starts on its very
first sound, put a number of seconds such as 1 in **앞 공백** (silence before).

## Shorts

![Shorts](docs/screenshots/6-shorts.png)

In **만들기** (make), set **화면** (frame) to **세로 (쇼츠)** (upright, Shorts) for an upright video for
YouTube Shorts: 1080x1920 at 30 frames a second. The title and the cover are at the top, the line
being sung large in the middle and the next line small under it. The bottom fifth and the right edge
are left empty, as Shorts covers them with its buttons and caption. The file is `title_shorts.mp4`,
saved apart from the wide video.

## Troubleshooting

- "디스크 공간 부족" (not enough disk space): free space on the drive it names and start again.
- "내려받기 실패", "설치 실패" (download or install failed): check the internet connection and start
  again.
- "메모리가 부족해 자동 맞추기를 하지 못했습니다" (not enough memory for auto timing): click
  **채팅 AI로 맞추기** (chat AI) or **재생하며 직접 맞추기** (tap along) under the message. With other
  programs closed, auto timing can run again.
- "메모리가 부족해 영상을 만들지 못했습니다" (not enough memory to make the video): close other
  programs and make it again. 720p uses less memory.
- "영상 만들기 실패" (video failed): the reason is shown under the button.

The log is `coverlyric.log` in the program folder. If the problem stays, attach that file to an
[issue](https://github.com/NaNIsaac/coverlyric/issues).

## Command line

With [uv](https://docs.astral.sh/uv/), videos can also be made by commands, without the page. This
makes a project folder from the demo song and draws one frame. All commands are in
[Command line](docs/cli.en.md).

<!-- test -->
```sh
uv run coverlyric project new demo-song --audio src/coverlyric/demo/tone.wav --cover src/coverlyric/demo/cover.png --title "Demo song"
uv run coverlyric still demo-song --at 7
```

To make the video in one go from a song, a cover and a lyrics file:

```sh
uv run --extra auto coverlyric make --audio song.mp3 --cover cover.png --lyrics lyrics.txt --title "Title" --out videos
```

## More

[Full guide](docs/guide.en.md) · [Command line](docs/cli.en.md) · [For agents](docs/agents.md) · Licence: code MIT, fonts SIL OFL 1.1
