# coverlyric

[한국어](README.md)

A Windows program that makes a lyric video (mp4) from a song, its album cover and the lyrics. It
runs on Windows 10/11 with 4 GB of RAM or more. The page is in Korean.

## 1. Download and start

1. **[Download coverlyric (ZIP)](https://github.com/NaNIsaac/coverlyric/archive/refs/heads/main.zip)**
2. Right-click the ZIP file → **Extract All**.
3. In the extracted folder, double-click **`가사영상 만들기.bat`**.
4. The first start downloads what it needs and takes 1-3 minutes. Keep the terminal window open
   until the page opens in the browser.

If "Windows protected your PC" appears, click **More info** → **Run anyway**.

## 2. Song and cover

![Files group](docs/screenshots/1-files.png)

In **파일** (files) on the left rail, pick the song and the cover, then type the title and the artist.

## 3. Lyrics

In **가사** (lyrics), paste the lyrics and click **가사 넣기** (add lyrics). Each line becomes one line on screen.

## 4. Timing

![Auto timing](docs/screenshots/3-auto.png)

Lower in **가사**, under **타이밍**, click **자동 맞추기** → **자동으로 맞추기** (auto timing). When it ends, listen to the lines marked
with a dashed border with **▶** and fix them.

## 5. Look

![Look](docs/screenshots/4-look.png)

Drag the album, lyrics and title in the preview; drag a corner to resize. Font and album style are
in **모양** (look), band colour and background in **색** (colour).

## 6. Make the video

Click **이대로 영상 만들기** (make the video) → **확인**. When it ends, click **영상 폴더 열기** (open
the video folder). Videos are saved in `만든 영상` in the program folder.

## If something goes wrong

- **"디스크 공간 부족"** (not enough disk space): free space on the drive it names and start again.
- **"내려받기 실패"** or **"설치 실패"** (download or install failed): check the internet connection
  and start again.
- **"메모리가 부족해 자동 맞추기를 하지 못했습니다"** (not enough memory for auto timing): close other
  programs and try again; tap-along timing works meanwhile.
- **"메모리가 부족해 영상을 만들지 못했습니다"** (not enough memory to make the video): close other
  programs and make it again; 720p uses less memory.
- **"영상 만들기 실패"** (video failed): read the reason shown under the button.

The log is `coverlyric.log` in the program folder. If the problem stays, attach that file to an
[issue](https://github.com/NaNIsaac/coverlyric/issues).

## Command line

With [uv](https://docs.astral.sh/uv/), draw one frame of the demo song from the repository folder:

<!-- test -->
```sh
uv run coverlyric still src/coverlyric/demo/demo.json --at 7 --out demo-still.png
```

## More

[Full guide](docs/guide.en.md) · [Command line](docs/cli.en.md) · Licence: code MIT, fonts SIL OFL 1.1
