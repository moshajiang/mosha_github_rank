@echo off
setlocal
pushd "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo Project Python environment not found. Please follow README.md first.
  pause
  popd
  exit /b 1
)
chcp 65001 >nul
echo Updating due sources and Chinese project summaries...
".venv\Scripts\python.exe" -X utf8 scripts\desktop.py update
set "rankExitCode=%ERRORLEVEL%"
pause
popd
exit /b %rankExitCode%
