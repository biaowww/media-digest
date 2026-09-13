@echo off
rem media-digest unattended build: Drive content -> fetch/sync -> git push.
rem Double-click: runs, prints the result and waits for a key.
rem Scheduled task media-digest-build calls it with the argument "task" (no pause).
rem ASCII only: cmd reads .bat in the OEM code page, non-ASCII comments break parsing.
cd /d "%~dp0"
set HTTPS_PROXY=http://127.0.0.1:10808
set HTTP_PROXY=http://127.0.0.1:10808
set PYTHONIOENCODING=utf-8
if /i "%~1"=="task" (
  py scraper/build.py
  exit /b %errorlevel%
)
py scraper/build.py %*
echo.
if errorlevel 1 (
  echo *** BUILD HAD ERRORS - see lines above or scraper\logs\build.log ***
) else (
  echo Done. Page updates in about 1 minute: https://biaowww.github.io/media-digest/site/
)
pause
