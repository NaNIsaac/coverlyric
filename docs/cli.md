# 명령줄

[English](cli.en.md) · [처음으로](../README.md)

[uv](https://docs.astral.sh/uv/)가 있으면 저장소 폴더에서 바로 실행할 수 있습니다.

## 페이지

```sh
uv run coverlyric                         # 페이지 열기 (기본)
uv run coverlyric app --home <폴더>       # 작업과 영상을 <폴더>에 저장
uv run coverlyric app --port 8765 --no-browser
```

## 프로젝트 폴더로 만들기

프로젝트는 폴더 하나입니다. `project.json`, 노래(`song.*`), 표지(`cover.*`)가 들어 있고, 영상과
`.srt`, `.lrc`, 썸네일 `.png` 도 같은 폴더에 저장됩니다. `<프로젝트>` 자리에는 그 폴더나
`project.json` 을 씁니다.

| 명령 | 하는 일 |
|---|---|
| `project new <폴더> --audio <노래> --cover <표지> [--lyrics <가사>] [--title ..] [--artist ..] [--keep-tags]` | 노래와 표지를 복사해 새 프로젝트를 만듭니다. 가사는 텍스트, SRT, LRC, VTT. `--keep-tags` 는 대괄호 표시와 `#` 줄을 남깁니다. |
| `project show <프로젝트>` | 제목, 바꾼 모양 설정, 줄마다 번호와 시간과 글자, 확인할 줄. |
| `project set <프로젝트> 키=값 ...` | `title`, `artist`, `clean_tags` 와 모양 설정(`lead`, `tail`, `height`, `fps`, `fade`, `band` 등). 모르는 키는 쓸 수 있는 키 목록과 함께 거절합니다. |
| `project lines <프로젝트> --shift -0.3` | 시간이 있는 줄을 모두 옮깁니다. |
| `project lines <프로젝트> --set 5=1:12.4 --text 5="고친 글자"` | 한 줄의 시간이나 글자를 바꿉니다. 시간은 `72.4`, `1:12.4` 모두 됩니다. |
| `project lines <프로젝트> --import <자막>` / `--from-lyrics <가사>` | 줄과 시간을 자막 파일에서, 또는 시간 없이 가사 파일에서 다시 넣습니다. |
| `render <프로젝트> [--out <mp4>] [--clip 1:00,1:10] [--quick]` | 영상을 만듭니다. 영상 전체를 만들면 옆에 `.srt`, `.lrc`, `.png` 도 저장합니다. 기본 파일 이름은 프로젝트 폴더의 `<제목>.mp4`. |
| `still <프로젝트> [--at 1:05] [--out <png>]` | 한 장면을 그림으로 저장합니다. |

모든 명령에 `--json` 을 붙이면 결과를 JSON 하나로 출력합니다. 진행 상황은 표준 오류로 나옵니다.
출력은 콘솔 설정과 상관없이 UTF-8 입니다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 됨 |
| 1 | 실패 (이유는 표준 오류와 `--json` 의 `error`) |
| 2 | 명령을 잘못 씀 (없는 키, 시간이 아닌 값, 없는 줄 번호) |
| 3 | 메모리 부족 |

예 (데모 노래):

```sh
uv run coverlyric project new demo-song --audio src/coverlyric/demo/tone.wav --cover src/coverlyric/demo/cover.png --title "데모 노래"
uv run coverlyric project lines demo-song --import timing.srt
uv run coverlyric project set demo-song lead=1 height=720
uv run coverlyric render demo-song
```

`가사영상 만들기.bat` 은 `tools/start.ps1` 을 실행합니다. uv가 없으면 `%LOCALAPPDATA%\coverlyric\uv`
에 설치한 뒤 `uv run --frozen --no-dev coverlyric` 으로 페이지를 엽니다.

## 프로젝트 파일

페이지는 작업을 `작업 중/project.json` 에 저장합니다. 노래와 표지 경로, 줄마다 시작 시간과 글자,
모양 설정(`style`), 자동 맞추기가 남긴 확인할 줄(`notes`)이 들어 있습니다. 만든 영상은 저장 위치
폴더(처음에는 `만든 영상/`)에 저장됩니다. 명령줄 명령은 이 폴더에도 그대로 쓸 수 있습니다.

## 환경 변수

| 변수 | 뜻 |
|---|---|
| `COVERLYRIC_HOME` | 작업과 영상 폴더 (`--home` 과 같음) |
| `COVERLYRIC_NO_BROWSER` | 값이 있으면 브라우저를 열지 않음 |
| `COVERLYRIC_ENCODER` | H.264 인코더 (`libx264`, `h264_nvenc`, `h264_qsv`, `h264_amf`). 기본은 이 PC에서 동작하는 첫 번째 |
| `COVERLYRIC_WORKERS` | 영상을 그리는 작업 프로세스 수 (1~8). 기본은 여유 메모리로 정함 |

## 글꼴

포함된 글꼴은 SIL Open Font License 1.1이며, 라이선스 파일은 `src/coverlyric/fonts/` 에 글꼴과 함께
있습니다: Noto Sans KR, NanumGothic Bold, Do Hyeon, Black Han Sans, Nanum Brush Script, East Sea
Dokdo.

## 테스트

```sh
uv run pytest
```
