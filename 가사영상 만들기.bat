@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 가사 영상 만들기
set "LYRICVIDEO_HOME=%~dp0."
set "UV_EXE=uv"
where uv >nul 2>nul
if not errorlevel 1 goto run
set "UV_EXE=%LOCALAPPDATA%\lyricvideo\uv\uv.exe"
if exist "%UV_EXE%" goto run
echo.
echo 처음 실행이에요. 필요한 프로그램을 내려받고 있어요.
echo 인터넷 속도에 따라 몇 분 걸릴 수 있어요. 이 창을 닫지 마세요.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_INSTALL_DIR = Join-Path $env:LOCALAPPDATA 'lyricvideo\uv'; $env:UV_NO_MODIFY_PATH = '1'; irm https://astral.sh/uv/0.11.32/install.ps1 | iex"
if not exist "%UV_EXE%" goto fail
:run
echo 프로그램을 여는 중이에요. 잠시 뒤 인터넷 창이 열려요.
"%UV_EXE%" run --frozen --no-dev lyricvideo
if errorlevel 1 goto fail
exit /b 0
:fail
echo.
echo 문제가 생겼어요. 이 창의 글을 사진으로 찍어서 물어봐 주세요.
pause
exit /b 1
