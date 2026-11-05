@echo off
rem Plex PS4 revive - Windows starter. Double-click this file,
rem or drag the Plex .pkg file onto it.
cd /d "%~dp0"
set PLEX_REVIVE_NO_PAUSE=1

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 revive.py %*
    goto done
)
python --version >nul 2>nul
if %errorlevel%==0 (
    python revive.py %*
    goto done
)
echo.
echo Python is not installed.
echo Get it from https://www.python.org/downloads/ and install it,
echo then double-click this file again.

:done
echo.
pause
