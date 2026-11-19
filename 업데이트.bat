@echo off
rem Updates coverlyric. The messages are in update.ps1: cmd misreads Korean text in a batch file.
rem One line: the update replaces this file while it runs, and cmd reads a batch file line by line.
cd /d "%~dp0" & powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\update.ps1" & pause & exit /b
