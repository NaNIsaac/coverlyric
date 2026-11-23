# 명령줄

[English](cli.en.md) · [처음으로](../README.md)

프로그램을 쓰기만 하려면 [README](../README.md#설치)의 설치 프로그램으로 설치합니다. 이 문서는 소스에서
실행하는 법과 페이지 없이 영상을 만드는 명령입니다.

## 소스에서 실행

[uv](https://docs.astral.sh/uv/)와 git이 있으면 저장소를 받아 그 폴더에서 실행합니다. Python과 패키지는
`uv` 가 처음 한 번 설치합니다.

```sh
git clone https://github.com/NaNIsaac/coverlyric
cd coverlyric
uv run coverlyric
```

데모 노래로 프로젝트 폴더를 만들고 한 장면을 그려 봅니다:

<!-- test -->
```sh
uv run coverlyric project new demo-song --audio src/coverlyric/demo/tone.wav --cover src/coverlyric/demo/cover.png --title "데모 노래"
uv run coverlyric still demo-song --at 7
```

테스트는 `uv run pytest` 입니다.

## 페이지

```sh
uv run coverlyric                         # 페이지 열기 (기본)
uv run coverlyric app --home <폴더>       # 작업과 영상을 <폴더>에 저장
uv run coverlyric app --port 8765 --no-browser
uv run coverlyric app <프로젝트>             # 그 프로젝트 폴더에서 페이지 열기
```

`app <프로젝트>` 는 페이지를 그 폴더의 `project.json` 위에서 엽니다. 페이지의 작업 파일은 `.cache/page/` 에,
영상은 프로젝트 폴더에 둡니다. 그 폴더에서는 새로 시작과 데모를 쓸 수 없습니다. 명령이나 다른 창이
`project.json` 을 바꾸면, 페이지는 창을 다시 누르거나 저장할 때 바뀐 내용을 읽고 이 창에서 바꾼 것을 그
위에 다시 얹습니다. 양쪽이 같은 항목을 바꿨으면 어느 쪽을 쓸지 묻습니다. 그동안 서버에 묻는 일은 없습니다
(1분에 0번).

## 한 번에 만들기

```sh
uv run --extra auto coverlyric make --audio 노래.mp3 --cover 표지.png --lyrics 가사.txt --title "제목" --out 영상
```

`영상/제목/` 폴더 하나에 노래와 표지 복사본, `project.json`, `제목.mp4`, `.srt`, `.lrc`, `.png` 가
저장됩니다. 가사는 노래를 듣고 자동으로 맞춥니다. 시간이 있는 자막이 있으면 `--lyrics` 대신
`--timing <자막>` 을 쓰고, 이때는 듣지 않습니다.

| 선택 | 뜻 |
|---|---|
| `--artist ..` | 가수 |
| `--lead 1` / `--tail 2` | 영상 앞과 뒤의 공백(초) |
| `--height 720` / `--fps 30` | 화질(1080, 720)과 1초에 장면 수(24, 30) |
| `--style <JSON 또는 파일>` | 모양 설정, 예 `'{"fade": false}'` |
| `--short 1:00,1:30` | 그 구간의 9:16 쇼츠도 두 번째 영상(`short`)으로 더해, 16:9 영상 다음에 만듦 |
| `--model small` | 듣기 모델 (`small`, `base`, `tiny`). 메모리가 모자라면 더 작은 모델로 바꿉니다. |
| `--keep-tags` | 대괄호 표시와 `#` 줄을 남김 |
| `--strict` | 찾지 못한 줄이나 확인할 줄이 있으면 종료 코드 4 |

끝나면 요약을 출력합니다: 파일 경로, 가사 줄 수(`sung`), 들어서 찾은 줄 수(`placed`), 찾지 못해
앞뒤 줄 사이에 둔 줄(`unplaced`)과 앞 줄과 1초 안인 줄(`doubtful`)의 번호와 시간, 쓴 모델, 단계별
걸린 초.

자동 맞추기는 `auto` 추가 패키지(faster-whisper)가 필요합니다. `uv run --extra auto` 가 처음 한 번
설치하고, 듣기 모델은 처음 쓸 때 내려받습니다(`small` 약 460 MB). 노래는 이 PC 안에서만 듣습니다.

## 프로젝트 폴더로 만들기

프로젝트는 폴더 하나입니다. `project.json`, 노래(`song.*`), 표지(`cover.*`)가 들어 있고, 영상과
`.srt`, `.lrc`, 썸네일 `.png` 도 같은 폴더에 저장됩니다. `<프로젝트>` 자리에는 그 폴더나
`project.json` 을 씁니다.

| 명령 | 하는 일 |
|---|---|
| `project new <폴더> --audio <노래> --cover <표지> [--lyrics <가사>] [--title ..] [--artist ..] [--keep-tags]` | 노래와 표지를 복사해 새 프로젝트를 만듭니다. 노래 자리에 영상(휴대폰 화면 녹화 등)을 주면 그 소리만 소리의 처음부터 `song.flac` 으로 저장하고, 소리가 화면보다 늦게 시작했으면 몇 초인지 알려 줍니다. 가사는 텍스트, SRT, LRC, VTT. `--keep-tags` 는 대괄호 표시와 `#` 줄을 남깁니다. |
| `project show <프로젝트>` | 제목, 바꾼 모양 설정, 줄마다 번호와 시간과 글자, 확인할 줄. |
| `project set <프로젝트> 키=값 ...` | `title`, `artist`, `album`, `released`(플레이어의 표지 위 날짜), `clean_tags` 와 모양 설정(`lead`, `tail`, `height`, `fps`, `fade`, `band` 등). 모르는 키는 쓸 수 있는 키 목록과 함께 거절합니다. 세로 영상은 `shape=tall`(9:16), `square`(1:1), `portrait`(4:5)에 `fps=30 lyric_edge=outline`, 구간은 `clip_from=42 clip_to=72`(초, `clip_to=0` 은 끝까지), 끝을 처음과 이어지게 하려면 `loop=true`(끝에 구간 앞 노래를 붙이려면 `loop_lead=3`(초) 또는 바로 앞 줄 `loop_lead_line=true`), 위아래 띠는 `bars=true bars_colour=#000000 bars_height=0.12 bars_top=.. bars_bottom=.. bars_size=48`, 가사 뒤에 도는 CD는 `upright_look=disc`(낡은 CD는 `disc_wear=worn`), 부르는 글자만 노랗게는 `highlight=letter`(로마자 낱말은 첫 글자부터 다음 낱말까지 낱말 전체, 한글은 한 글자씩). 띠가 있을 때 150 px 더 높은 위 띠에 큰 한두 줄 문구는 `hook="첫 줄|둘째 줄"`(`bars_top` 대신), 노란 단어는 `hook_hi="단어,여러 단어"`, 그림 위쪽을 잘라 올리려면 `crop_top=90`(px). 그러면 아래 띠는 150 px 줄고 `crop_top` 만큼 늘며 `bars_bottom` 은 그 안에 다시 그립니다. 반복의 끝이 처음으로 섞이는 길이(그림, 소리, 자막 모두)는 `loop_blend=0.5`(초, 같은 세기로 섞음, 최소 0.05). 16:9 의 플레이어 모양은 `layout=player`. 케이스 플라스틱이 그 아래 보이는 것을 흐리고 회색으로 덮는 정도는 `case_haze=0.15`(기본, `0` 이면 투명, 기울인 케이스는 늘 투명). 긴 전주의 제목을 손글씨 그림으로 바꾸려면 `title_image=<그림 파일>`(흰 바탕이나 투명한 바탕에 어두운 글씨, 프로젝트 폴더에 `title.png` 처럼 복사, `title_image=` 는 뺌). 표지 대신 영상 위에 가사를 얹으려면 `video=<영상 파일>`(프로젝트 폴더에 `video.mp4` 처럼 복사, `video=` 는 뺌), 시작을 옮기는 `video_offset=-1.5`(초), 짧은 영상은 `video_end=loop` 또는 `hold`, 영상 소리는 `video_sound=true`, 글자는 `video_ink=#ffffff video_lit=#ffd23f video_edge=shadow`(또는 `none`), 띠는 `video_band=paper`(`none`, `dark`)와 `video_band_alpha=0.85`, 자리는 `video_text=bottom`(또는 `middle`, 그리고 쇼츠 자막에 가릴 수 있는 더 아래 `low`). |
| `chorus <프로젝트> [--length 30] [--apply]` | 가장 많이 되풀이되는 줄 묶음을 찾아 쇼츠 구간(`from`, `to`)으로 보여 줍니다. `--apply` 는 프로젝트를 그 구간의 세로 영상으로 바꿉니다(16:9 였으면 9:16). 되풀이되는 줄이 없으면 실패합니다. |
| `sections <프로젝트> [--length 30] [--apply N]` | 마디 수가 정수인 반복 구간을 길이에 가깝게, 시작이 강한 순서로 8개까지 보여 줍니다. 구간은 줄이 시작하는 박(또는 그 앞 박)에서 시작하고, 다음 줄이 들어오기 직전에 끝나도록 한 마디 더하거나 뺍니다. `--apply N` 은 프로젝트를 N번 구간의 반복 세로 영상으로 바꿉니다(`loop=true`). `align` 추가 설치가 필요합니다. |
| `align <프로젝트> [--from 1:35] [--to 2:42]` | 그 사이에 시작하는 줄의 글자마다 부르는 시간을 정해 프로젝트의 `letters` 에 저장합니다(`highlight=letter` 가 씁니다). 처음 값은 세로 영상이면 그 구간, 아니면 노래 전체. 노래에서 목소리만 떼어(demucs) 글자 하나를 한 음절로 맞춥니다(torchaudio MMS_FA). 첫 글자가 줄 시작보다 0.6초 넘게 늦거나, 마지막 글자가 다음 줄에 닿거나, 글자들이 한 글자에 0.05초도 안 되게 몰린 줄은 다시 놓습니다: `auto` 추가 설치가 있으면 그 줄에서 들린 낱말의 시작에서, 없으면 고르게. 다시 놓은 줄 수를 알려 주고 `project show` 에 표시합니다. 처음 한 번 모델 약 1.2 GB를 내려받습니다. `align` 추가 설치가 필요합니다. |
| `project lines <프로젝트> --shift -0.3` | 시간이 있는 줄을 모두 옮깁니다. `--range 5` 나 `--range 5-9` 는 그 줄만 옮깁니다. |
| `project lines <프로젝트> --set 5=1:12.4 --text 5="고친 글자"` | 한 줄의 시간이나 글자를 바꿉니다. 시간은 `72.4`, `1:12.4` 모두 됩니다. |
| `project lines <프로젝트> --import <자막>` / `--from-lyrics <가사>` | 줄과 시간을 자막 파일에서, 또는 시간 없이 가사 파일에서 다시 넣습니다. 번호나 글자가 더는 맞지 않는 줄의 글자 시간(`letters`)은 지웁니다. |
| `project lines <프로젝트> --letters 5=72.4,72.7,73.1` | 5번 줄의 글자마다 부르는 시간을 직접 정해 `letters` 에 저장합니다(`highlight=letter` 가 씁니다). 시간은 띄어쓰기를 뺀 글자와 부호마다 하나, 또는 글자와 숫자마다 하나(부호는 앞 글자의 시간). 줄의 글자를 나중에 바꾸면 그 시간은 쓰이지 않습니다. |
| `srt <프로젝트> [--out <폴더>]` | 노래 전체의 `<제목>.srt` 를 16:9 영상의 시간으로 저장하고, 세로 프로젝트면 그 영상의 `<제목>_shorts.srt` 도 저장합니다. 세로 영상 자막은 구간의 처음부터 세고, 끝에 붙일 앞부분(`loop_lead`)이 있으면 그 줄이 마지막에 옵니다. 기본 폴더는 프로젝트 폴더. |
| `auto <프로젝트> [--model ..] [--apply] [--strict]` | 노래를 듣고 줄마다 시간을 정합니다. 결과와 확인할 줄만 보여 주고, `--apply` 를 붙이면 프로젝트에 저장합니다. |
| `words <노래 또는 프로젝트> --from 1:10 --to 1:20 [--model ..]` | 그 구간에서 들린 낱말과 시작, 끝 시간. 찾지 못한 줄의 시간을 직접 정할 때 씁니다. |
| `render <프로젝트> [--out <mp4>] [--clip 1:00,1:10] [--quick]` | 영상을 만듭니다. 영상 전체를 만들면 옆에 `.srt`, `.lrc`, `.png` 도 저장합니다. 기본 파일 이름은 프로젝트 폴더의 `<제목>.mp4`. |
| `still <프로젝트> [--at 1:05] [--out <png>]` | 한 장면을 그림으로 저장합니다. |
| `output list <프로젝트>` | 노래 하나로 만드는 영상들(출력): id, 비율, 구간, 파일 이름, 지금 고치는 영상. |
| `output show <프로젝트> [ID]` | 한 영상의 모양 설정과 줄을 `project show` 처럼 보여 줍니다. |
| `output add <프로젝트> ID [--from ID] [--shape tall]` | 다른 영상(처음 값은 지금 영상)을 복사해 비율(`wide`, `tall`, `square`, `portrait`)을 바꾼 새 영상을 더하고, 지금 영상으로 삼습니다. id 는 영어 소문자, 숫자, `-`. 같은 비율의 두 번째 영상은 파일 이름에 `-2` 가 붙습니다(`<제목>_shorts-2.mp4`). |
| `output import <프로젝트> <다른 프로젝트>` | 같은 노래로 따로 만든 프로젝트(예: 폴더를 복사해 만든 쇼츠)의 지금 영상을 새 영상으로 더하고, 지금 영상으로 삼습니다. 줄과 글자 시간이 같아야 하며, 다르면 다른 줄을 보여 주고 아무것도 바꾸지 않습니다(종료 코드 2). 움직이는 그림, 영상, 그 폴더 안의 글꼴을 복사해 오고, 있던 파일은 덮어쓰지 않습니다. 제목, 가수, 앨범, 날짜, 노래, 표지, 제목 그림은 이 프로젝트 것을 쓰고, 서로 다른 것은 `not_imported` 로 알려 줍니다. 다른 프로젝트는 그대로 둡니다. |
| `output use <프로젝트> ID` / `output remove <프로젝트> ID` | 그 영상을 지금 영상으로 삼거나 뺍니다(마지막 하나는 뺄 수 없음). 파일은 그대로 둡니다. |

줄과 글자 시간은 노래에 하나만 있어 모든 영상이 같이 쓰고, 모양 설정, 움직이는 그림, `video=` 는
영상마다 따로 있습니다. 명령은 지금 영상에 적용됩니다. `render`, `still`, `srt`, `chorus`,
`sections`, `align`, `project show`, `project set` 은 `--output ID` 로 지금 영상을 바꾸지 않고
다른 영상에 적용합니다.

`project set` 의 `video=` 와 `title_image=` 는 프로젝트에 적혀 있던 그 파일만, 다른 영상이 쓰지 않을 때
바꾸거나 지웁니다. 폴더의 다른 파일은 이름이 비슷해도 그대로 두고, 이름이 겹치면 번호를 붙여 복사합니다
(`video-2.mp4`).

모든 명령에 `--json` 을 붙이면 결과를 JSON 하나로 출력합니다. 진행 상황은 표준 오류로 나옵니다.
출력은 콘솔 설정과 상관없이 UTF-8 입니다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 됨 |
| 1 | 실패 (이유는 표준 오류와 `--json` 의 `error`) |
| 2 | 명령을 잘못 씀 (없는 키, 시간이 아닌 값, 없는 줄 번호) |
| 3 | 메모리 부족 |
| 4 | 만들었지만 확인할 줄이 있음 (`--strict` 일 때만) |

데모 노래로 해 보기 (자막 `timing.srt` 는 직접 만든 것):

```sh
uv run coverlyric project new demo-song --audio src/coverlyric/demo/tone.wav --cover src/coverlyric/demo/cover.png --title "데모 노래"
uv run coverlyric project lines demo-song --import timing.srt
uv run coverlyric project set demo-song lead=1 height=720
uv run coverlyric render demo-song
```

## AI 클라이언트에서 (MCP)

`coverlyric mcp` 는 위의 명령을 AI 클라이언트가 부르는 도구로 내놓습니다. 이 컴퓨터 안에서 stdio로만
이어지고, 따로 설치하는 `mcp` 추가 기능이 필요합니다.

```sh
uv sync --extra mcp
uv run coverlyric mcp
```

| 도구 | 하는 일 |
|---|---|
| `project_show`, `project_set` | `project show`, `project set` (`output` 으로 영상을 고름) |
| `lines_get`, `lines_set_text`, `lines_set_time`, `lines_shift` | 줄 보기, 글자, 시작 시간, 한 줄이나 여러 줄 옮기기 |
| `output_list`, `output_add`, `output_use` | `output list`, `add`, `use` |
| `still` | 그 시간의 한 장면을 PNG 그림으로 |
| `clip_render` | 그 구간의 작은 미리보기 영상, 경로를 돌려줌 |
| `render` | 영상 전체와 썸네일, SRT, LRC. 진행을 알림 |
| `open_page` | 사용자가 원할 때만 그 프로젝트의 페이지를 엶. 이미 열린 페이지가 있으면 그 페이지 |

프로젝트는 폴더 경로로 주고, 상태는 `project.json` 하나입니다. 도구 사이에 기억하는 것이 없고, 바꾼 것은 바로
저장됩니다. `still` 과 `clip_render` 가 만든 파일은 `.cache/mcp/` 에 있고 지워도 됩니다.

### 클라이언트에 연결하기

`coverlyric mcp --config` 는 이 coverlyric 의 서버를 띄우는 설정을 이 컴퓨터의 절대 경로로 찍습니다: 이
폴더에서의 `uv run`(설치된 프로그램에서 부르면 그 프로그램의 uv), 아니면 PATH의 `coverlyric` 프로그램.
클라이언트가 쓸 사본에서 실행합니다.

```sh
uv run coverlyric mcp --config
```

Claude 앱은 찍힌 `mcpServers` 항목을 설정 파일(설정, 개발자, 구성 편집)에 이미 있는 서버 옆에 넣고, 저장한
뒤 앱을 다시 켭니다. Claude Code 는 안쪽의 `coverlyric` 객체를 받습니다: `claude mcp add-json coverlyric
'<그 객체>'`.

서버가 클라이언트에 도구 쓰는 법을 알려 줍니다: 시간은 초나 m:ss 이고 쇼츠도 노래 시간 기준, 줄은 1부터,
바꾼 것은 전체 `render` 전에 `still` 과 `clip_render` 로 확인.

## 설치된 프로그램

시작 메뉴의 바로 가기가 `가사영상 만들기.bat` 을, 그것이 `tools/start.ps1` 을
실행합니다. 설치 프로그램이 넣은 `uv\uv.exe` 로 `uv run --frozen --no-dev coverlyric` 을 실행하고,
데이터 폴더는 `COVERLYRIC_HOME`, 없으면 `%LOCALAPPDATA%\coverlyric\data-folder.txt` 의 첫 줄(설치
프로그램이 씀), 없으면 문서\coverlyric 입니다.

`align` 과 `sections` 는 추가 설치 `align` 이 필요합니다. torch 2.7 이 Python 3.12, 3.13 에서만 돌기 때문에 따로 된 환경에서 실행합니다:

```powershell
uv run --isolated --python 3.13 --extra align coverlyric align <프로젝트>
```

없으면 이 명령을 알려 주고 종료 코드 1로 끝납니다.

## 프로젝트 파일

페이지는 작업을 `작업 중/project.json` 에 저장합니다. 노래와 표지 경로, 줄마다 시작 시간과 글자,
모양 설정(`style`), 자동 맞추기가 남긴 확인할 줄(`notes`)이 들어 있습니다. 만든 영상은 저장 위치
폴더(처음에는 `만든 영상/`)에 저장됩니다. 명령줄 명령은 이 폴더에도 그대로 쓸 수 있습니다.

노래 하나로 만드는 영상들은 `outputs` 에 하나씩 들어 있습니다. 항목마다 `id`, 모양 설정 `style`, 움직이는 그림
`anim`, 영상 `video` 가 있고, `current` 가 지금 고친 영상입니다. 줄과 글자 시간은 노래에 하나만 있어 모든
영상이 같이 씁니다. `outputs` 가 없는 예전 파일은 영상 하나로 열립니다.

`letters` 는 줄마다 글자를 부르는 시간으로, `highlight=letter` 가 씁니다. 항목 하나가
`{"n": 3, "text": "아리랑 아리랑", "times": [12.0, 12.3, ...]}` 처럼 줄 번호(1부터), 시간을 정할 때의
그 줄 글자, 초 단위 시간을 갖습니다. 시간은 띄어쓰기를 뺀 글자마다 하나이거나, 글자와 숫자마다 하나입니다.
뒤의 경우 문장부호는 앞 글자의 시간을 씁니다. 줄 글자가 그 뒤에 바뀌었거나 줄에 시간이 없으면 그 항목은
쓰지 않습니다.

## 환경 변수

| 변수 | 뜻 |
|---|---|
| `COVERLYRIC_HOME` | 작업과 영상 폴더 (`--home` 과 같음) |
| `COVERLYRIC_NO_BROWSER` | 값이 있으면 브라우저를 열지 않음 |
| `COVERLYRIC_ENCODER` | H.264 인코더 (`libx264`, `h264_nvenc`, `h264_qsv`, `h264_amf`). 기본은 이 PC에서 동작하는 첫 번째 |

## 글꼴

포함된 글꼴은 SIL Open Font License 1.1이며, 라이선스 파일은 `src/coverlyric/fonts/` 에 글꼴과 함께
있습니다: Noto Sans KR, NanumGothic Bold, Do Hyeon, Black Han Sans, Nanum Brush Script, East Sea
Dokdo.
