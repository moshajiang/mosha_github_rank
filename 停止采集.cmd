@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Project Python environment not found. Please follow README.md first.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\desktop_scheduler.py" stop %*
