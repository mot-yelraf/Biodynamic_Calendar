@echo off
setlocal
set "BD_CALENDAR_RUNTIME=%~dp0"
if not exist "%BD_CALENDAR_RUNTIME%.venv\Scripts\python.exe" (
  echo Biodynamic Calendar virtual environment is missing. Run the installer again. 1>&2
  exit /b 1
)
cd /d "%BD_CALENDAR_RUNTIME%"
"%BD_CALENDAR_RUNTIME%.venv\Scripts\python.exe" -m biodynamic_calendar_app %*
exit /b %ERRORLEVEL%
