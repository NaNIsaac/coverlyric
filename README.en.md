# coverlyric

[한국어](README.md)

A Windows program that makes a lyric video (mp4) from a song, its album cover and the lyrics. The
lyrics scroll in time with the song, and the album sits beside them as a CD case or a round cover.
The lyric times come from listening to the song on this PC. It makes 16:9 videos and Shorts (9:16),
1:1 and 4:5 videos. The page is in Korean.

![Decorate step](docs/screenshots/4-deco.png)

## Install

It needs Windows 10/11 64-bit and 4 GB of RAM or more.

1. Download `coverlyric-setup.exe` from the [latest release](https://github.com/neurin-ocha/coverlyric/releases/latest)
   and run it. No administrator rights are needed. If "Windows protected your PC" shows, click
   **More info** → **Run anyway**.
2. Choose the data folder (where videos, the song in progress, settings and the log are kept;
   `Documents\coverlyric` at first) and install.
3. Open **coverlyric** from the Start menu. The first start downloads what it needs and takes 1-3
   minutes.

A newer version installs the same way, over the old one, and keeps the data folder. Uninstalling from
Windows Settings > **Apps** also keeps the data folder.

## First video

1. **노래·표지** (song and cover): pick the song and the cover, and type the title and the artist.
2. **가사** (lyrics): paste the lyrics and click **가사 넣기**. Each line is one line on screen.
3. **타이밍** (timing): click **자동으로 맞추기** (time automatically). Listen to and fix only the
   lines with a dotted border.
4. **꾸미기** (decorate): drag the album and the lyrics on the preview, and pick the album shape, the
   font and the colours.
5. **만들기** (make): **영상 만들기** → **확인**. The video and its subtitles (SRT, LRC) go to the
   **저장 위치** (save folder).

**데모로 둘러보기** (try the demo), in the empty preview, starts with a practice song, cover and
lyrics.

## Picking a Short's part

On **만들기** (make), choose **9:16 쇼츠**; the part shows on a waveform.

- Drag either end, or move it with **−마디 −박 +박 +마디** (a bar or a beat back or on). On the
  keyboard `,` `.` move the start and `[` `]` the end by a beat; with Shift, by a bar.
- Under the waveform: the length in seconds and bars, the first and last sung lines, and a red
  note when an end falls while a line is sung.
- **▶ 구간 듣기** (play the part) plays it on repeat until pressed again, joined at the seam as the
  video is.
- The waveform zooms to the part (**전체** shows the whole song) and draws bar lines counted from the
  part's start.
- **후보로 저장** (keep as a candidate) keeps the part under a name. Press a candidate to hear it on
  repeat, **구간으로** to make it the part, **×** to remove it. Candidates are saved in the project.

## More

- [Guide](docs/guide.en.md): every setting on each step, Shorts and upright videos, troubleshooting
- [Command line](docs/cli.en.md): run from source, make videos without the page
- [For agents](docs/agents.md): the commands to make a video, in order
- [Issues](https://github.com/neurin-ocha/coverlyric/issues): if a problem stays, attach
  `coverlyric.log` from the data folder.

Licence: code MIT, fonts SIL OFL 1.1.
