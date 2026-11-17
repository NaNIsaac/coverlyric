# 명령줄

[English](cli.en.md) · [처음으로](../README.md)

[uv](https://docs.astral.sh/uv/)가 있으면 저장소 폴더에서 바로 실행할 수 있습니다.

## 명령

```sh
uv run coverlyric                         # 페이지 열기 (기본)
uv run coverlyric app --home <폴더>       # 작업과 영상을 <폴더>에 저장
uv run coverlyric app --port 8765 --no-browser
uv run coverlyric still <project.json> --at 30 --out still.png
uv run coverlyric render <project.json> --out video.mp4 [--clip 10,20]
```

`가사영상 만들기.bat` 은 `tools/start.ps1` 을 실행합니다. uv가 없으면 `%LOCALAPPDATA%\coverlyric\uv`
에 설치한 뒤 `uv run --frozen --no-dev coverlyric` 으로 페이지를 엽니다.

## 프로젝트 파일

페이지는 작업을 `작업 중/project.json` 에 저장합니다. 노래와 표지 경로, 줄마다 시작 시간과 글자,
모양 설정(`style`)이 들어 있습니다. 만든 영상은 `만든 영상/` 에 저장됩니다.

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
