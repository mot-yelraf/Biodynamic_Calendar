@echo off
setlocal
set "BD_CALENDAR_RUNTIME=%~dp0"
set "BD_CALENDAR_LOCAL_PYTHON=%BD_CALENDAR_RUNTIME%.venv\Scripts\python.exe"
set "BD_CALENDAR_INSTALLED_RUNTIME=%USERPROFILE%\Biodynamic_Calendar\"
if defined BD_CALENDAR_INSTALL_DIR set "BD_CALENDAR_INSTALLED_RUNTIME=%BD_CALENDAR_INSTALL_DIR%\"
set "BD_CALENDAR_INSTALLED_PYTHON=%BD_CALENDAR_INSTALLED_RUNTIME%.venv\Scripts\python.exe"
if exist "%BD_CALENDAR_LOCAL_PYTHON%" (
  "%BD_CALENDAR_LOCAL_PYTHON%" -c "import webview" >nul 2>&1
  if not errorlevel 1 goto runtime_ready
)
if /i not "%BD_CALENDAR_RUNTIME%"=="%BD_CALENDAR_INSTALLED_RUNTIME%" if exist "%BD_CALENDAR_INSTALLED_PYTHON%" (
  "%BD_CALENDAR_INSTALLED_PYTHON%" -c "import webview" >nul 2>&1
  if not errorlevel 1 (
    set "BD_CALENDAR_RUNTIME=%BD_CALENDAR_INSTALLED_RUNTIME%"
    echo Using installed Biodynamic Calendar runtime: %BD_CALENDAR_INSTALLED_RUNTIME%
  )
)
:runtime_ready
if not exist "%BD_CALENDAR_RUNTIME%.venv\Scripts\python.exe" (
  echo Biodynamic Calendar virtual environment is missing. Run the installer again. 1>&2
  exit /b 1
)
cd /d "%BD_CALENDAR_RUNTIME%"
"%BD_CALENDAR_RUNTIME%.venv\Scripts\python.exe" "%BD_CALENDAR_RUNTIME%Biodynamic_Calendar.py" %*
exit /b %ERRORLEVEL%
