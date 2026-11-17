@echo off
rem Starts coverlyric. The messages are in start.ps1: cmd misreads Korean text in a batch file.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start.ps1"
if errorlevel 1 pause
