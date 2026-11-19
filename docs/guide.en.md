# Full guide

[한국어](guide.md) · [Back](../README.en.md)

The page is in Korean; English names follow the Korean labels in brackets.

## What you need

- Windows 10/11 64-bit, 4 GB of RAM, 500 MB of free disk (0.7 GB more for auto timing)
- Song: mp3, wav, m4a, flac, ogg
- Cover: png, jpg, webp (square works best)
- The lyrics as text

## The page

The controls sit in four groups on the left rail: **파일** (files), **가사** (lyrics and timing),
**모양** (look) and **색** (colour). Only the chosen group is open, and **이대로 영상 만들기** (make)
shows in every group. A red dot marks a group that still lacks something (no song or cover, or a
line without a time).

## First start

- `가사영상 만들기.bat` downloads uv, Python, ffmpeg and the packages once (about 150 MB, about 300 MB
  on disk). It needs no administrator rights.
- If the extracted folder holds another folder of the same name, run the `.bat` inside it.
- If antivirus blocks it, add the folder to its exceptions or click **Allow** on its notice.
- **데모 불러오기** (load demo) fills in a practice song, a cover and four lines.

## Song and cover

![Files group](screenshots/1-files.png)

- **앨범 표지 고르기** (pick cover) opens **표지 자르기** (crop cover). Drag the square, resize it from
  a corner, set **확대** (zoom), then click **확인**.
- Leave the artist empty to keep it off the video.

## Lyrics

![Lyrics group](screenshots/2-lyrics.png)

- Each line becomes one line on screen. A line wider than the band is drawn smaller, and if it is
  still too wide, on two rows. Such lines are underlined in the timing list, and the count shows
  above it.
- Blank lines, lines starting with `#` and square-bracket marks such as `[후렴]` or
  `[Verse 1 — Conversational, rhythmic]` are dropped. A mark inside a line is removed and the rest of
  the line stays. Round brackets such as `(echo)` stay. The same applies to pasted and loaded
  subtitles.
- **대괄호 표시와 # 줄 빼기** (drop bracket marks and # lines), next to **가사 넣기**, turns this on and
  off (on at first, saved with the work). Off, the lyrics go in as typed, with only blank lines left
  out. It applies to pasted lyrics, the pasted chat-AI answer and subtitle files alike.

## Timing

Pick the way under **타이밍**, lower in the **가사** group. The times go into the timing list under
the preview, where they can be edited.

### Auto timing (자동 맞추기)

![Auto timing](screenshots/3-auto.png)

- With the song and lyrics in, click **자동 맞추기** → **자동으로 맞추기**. The bar shows the phase,
  the percentage and the time left, and the list fills in as lines are found.
- A 4-minute song takes about 2-5 minutes. The first run downloads the listening model (464 MB).
- At the start it picks the largest model that fits in the free memory (small, base, then tiny)
  and says under the bar when it uses a smaller one. When not even tiny fits, the memory message
  comes at once. When memory runs short while listening, it tries again with a smaller model. A smaller model places lines less exactly, so check the result once more.
- The song is processed on this PC only.
- Lines to check get a dashed border and a note: lines not found (given a time between their
  neighbours), lines within 1 second of the line before, and lines heard differently from the lyrics.
- **취소** (cancel) brings back the list as it was.

### Tap along (재생하며 직접 맞추기)

![Tap along](screenshots/3-tap.png)

- **재생하며 맞추기** plays the song from the start and shows the next line large.
- Press <kbd>Space</kbd> (or **지금**) as each line starts. <kbd>Backspace</kbd> undoes the last one,
  <kbd>Esc</kbd> stops.
- Fine-tune with **−0.1** / **+0.1** and listen from just before a line with **▶**.
- The time box takes `10`, `10.5`, `1:05`, `1:05.3` or `0:01:05`.

### Subtitle file (자막 파일 불러오기)

![Subtitle file](screenshots/3-file.png)

- Open an SRT, LRC or VTT file with **자막 파일 고르기**.
- Lines whose text differs from the lyrics are outlined; **내 가사로** replaces their text with yours.

### Chat AI (채팅 AI로 맞추기)

- It uses almost no memory on this PC, so it suits a PC with little memory.
- **채팅 AI용 프롬프트 복사** copies the prompt; give it to a chat AI with the song file, paste the
  SRT it returns into **받은 자막** and click **넣기**.
- The song file is sent to that AI service. Its times are often wrong, so check the list.

### Saving the timing

**LRC로 저장** and **SRT로 저장** save the timing as a file in the save folder and show the path.
When automatic timing finishes, **SRT로 저장** next to its result line does the same. The same files
are saved next to each video.

## Look and colour (모양, 색)

![Look group](screenshots/4-look.png)

The preview is one frame of the video and redraws on every change. Band, background and lyric colours
are in the **색** group, the rest in **모양**.

- Move and resize: drag the dashed boxes in the preview; drag the lower-right corner to resize.
  The **위치와 크기** table takes numbers; **위치·크기 처음대로** resets the layout.
- **Album:** **CD 케이스** (CD half out, spinning) or **둥근 표지** (round cover). **CD 보이기** and
  **CD 돌기** hide or stop the CD. **기울기** (tilt, -40° to 40°) turns the album about its upright axis.
- **Font:** a bundled font, a Korean font installed on the PC, or **다른 글꼴 파일...** (ttf, otf).
- **띠 색:** colour of the band behind the current line and of the progress bar. **표지 색으로**
  beside it takes the cover's most telling colour, darkened (light lyrics) or lightened (dark lyrics) a
  little if needed so the lyric colour stays readable on it.
- **바닥 그림자** (floor shadow): a soft shadow on the floor under the album, case or round cover.
- **바닥에 비친 모습** (reflection): the case mirrored on the floor under it, fading out (case only;
  the CD out of the case is not mirrored).
- **배경 흐림 / 배경 어둡게:** blur and darkness of the cover in the background.
- **가장자리 어둡게** (vignette): darkens the background towards the edges and corners, which draws
  the eye to the album and the lyrics.
- **배경 색감** (background tone): **그대로** (as is), **따뜻하게** (warm), **차갑게** (cool), **흑백**
  (black and white) or **표지 색** (tinted with the cover's most telling colour).
- **글자 색**, **테두리** (none, outline, shadow), **테두리 색:** colour of the lyrics, title and artist, with an outline or
  shadow that keeps them readable on a light cover.
- **움직이는 그림** (moving picture): one GIF or several images (png, jpg, webp) loop over the video.
  Reorder with ↑ ↓, remove with ✕, set the speed with **1초에 N장** (frames per second). Turn off
  **앨범과 가사 위에 보이기** to draw it below them.
- **제목과 가수 보이기**, **재생 바 넣기:** title and progress bar on or off.
- **시작 제목 화면** (opening title card): for the first 2-5 seconds the title and the artist fill the
  middle of the frame, then fade into the usual frame over 0.8 s; the first lyric ends it sooner. It uses
  the lyric colour and edge.
- **시작·끝 페이드** (fade in and out): the video fades in from black over 0.5 s and out to black
  over the last 1.5 s, with the sound. On by default.
- **Preview time:** the slider under the preview picks the frame; while the song plays the preview
  follows it.

## Making the video

![Make](screenshots/5-make.png)

- **화질** (1080p or 720p) and **1초에 장면** (24 or 30 frames a second): size and frame rate of the
  video. A 720p file is smaller and a little faster to make.
- **앞 공백** and **뒤 공백** (silence before and after, 0 to 10 s in 0.5 s steps): silent time
  before and after the song. During the silence before, only the cover and the title show, and the
  song and the lyrics start that much later. During the silence after, the last frame stays. The
  fade is at the start and the end of the whole video, silence included. The saved lyric times do
  not change; only the LRC and SRT files saved next to the video are moved to the video's clock.
- **10초 미리보기** (10-second preview) makes 10 seconds from the preview time at small size and
  plays it in place of the still; **미리보기 닫기** closes it.
- **이대로 영상 만들기** → **확인**. While it runs, the page shows how far into the song the video is
  made, the lyric there and the time left. **그만 만들기** stops it.
- It usually takes no longer than the song.
- If a video of the same name is open in a player, the new one is saved as `title (2).mp4`.
- **저장 위치** (save folder): where videos and timing files go. A folder picked with **바꾸기**
  (change) stays for the next run; **기본으로** (default) goes back to `만든 영상`. If the picked folder
  is gone (an unplugged USB drive), files go to `만든 영상`. When the video is done, the done line
  names the files it made.

Files in the save folder:

| File | Content |
|---|---|
| `title.mp4` | video (1920x1080 and 24 fps by default, H.264 + AAC) |
| `title.png` | thumbnail (1280x720) |
| `title.lrc`, `title.srt` | timing |

## Shorts

![Shorts](screenshots/6-shorts.png)

In **만들기** (make), set **화면** (frame) to **세로 (쇼츠)** (upright, Shorts) for a YouTube Shorts video.

- 1080x1920, 30 frames a second, H.264. The quality and silence fields do not apply and are hidden.
- The title and the artist at the top, the cover under them, the line being sung large on a band in
  the middle and the next line small under it. The lyrics get an outline (changeable in **색과 배경**).
- The bottom fifth and the right 120 pixels stay empty: Shorts covers them with its buttons and
  caption.
- The picture starts at once, without rising from black; only the sound fades in and out over 0.3 s.
- Album style, start and end, moving picture and place and size apply to the wide video only and are
  hidden in **꾸미기** (decorate).
- The file is `title_shorts.mp4`, with an upright thumbnail and the subtitle files beside it.

Choosing **가로** (wide) again goes back to the wide video at 24 frames a second.

## Quitting and coming back

- **끝내기** on the page, or closing the terminal window, quits.
- Work is saved as you go and comes back on the next start.
- **새로 시작** (start over) clears the current work. Finished videos stay.

## Keys and tips

- Each group's title shows its state (for example 노래 ✓ 표지 ✓, 4줄, 4/4 ✓).
- <kbd>Space</kbd> plays and pauses, <kbd>←</kbd> <kbd>→</kbd> move 5 seconds (outside text boxes).
- Clicking a row in the timing list moves the preview to its time.
- Files can be dropped anywhere on the page: song, cover, SRT/LRC/VTT, TXT lyrics, font files. Images
  dropped on the moving-picture box become moving pictures.
- Deleting a line shows **되돌리기** (undo) in a notice for a few seconds.

## Problems

| Symptom | What to do |
|---|---|
| Nothing happens on double-click | Run it from the extracted folder, not from inside the ZIP. |
| "디스크 공간 부족" (not enough disk) | Free space on the drive it names and start again. |
| "내려받기 실패", "설치 실패" (download or install failed) | Check the internet connection and start again. |
| "프로그램이 오류로 끝났습니다" (program ended with an error) | Post the error from the terminal window as an [issue](https://github.com/NaNIsaac/coverlyric/issues). |
| The browser does not open | Paste the `http://127.0.0.1:...` address from the terminal window into the browser. |
| Letters show as boxes | The font has no Korean; pick another. |
| "N번째 줄에 시간이 없습니다" (line N has no time) | Give that line a time in the list or remove it with ✕. |
| "메모리가 부족해 자동 맞추기를 하지 못했습니다" (not enough memory for auto timing) | Click **채팅 AI로 맞추기** (chat AI) or **재생하며 직접 맞추기** (tap along) under the message. With other programs closed, auto timing can run again. |
| "자동 맞추기를 하지 못했습니다" (auto timing failed) | Check the internet connection and try again. The details are in `coverlyric.log`. |
| "노래 파일을 읽을 수 없습니다", "그림 파일을 읽을 수 없습니다" (file cannot be read) | Pick another file. The song and cover already in place stay. |
| "메모리가 부족해 영상을 만들지 못했습니다" (not enough memory to make the video) | Close other programs and make it again; 720p uses less memory. |
| "메모리가 부족해 움직이는 그림 없이 만들었습니다" (made without the moving picture) | The video is made. To keep the moving picture, close other programs and make it again. |
| "메모리가 부족해 720p로 만들었습니다" (made at 720p) | The video is made at 720p. For 1080p, close other programs and make it again. |
| "영상 만들기 실패" (video failed) | Read the reason under the button. |
| Sound and lyrics drift apart | Move that line with −0.1 / +0.1 and make it again. |

The log is `coverlyric.log` in the program folder.
