@echo off
rem media-digest unattended build: Drive content -> fetch/sync -> git push.
rem Called daily by scheduled task media-digest-build; double-click to run now.
rem ASCII only: cmd reads .bat in the OEM code page, non-ASCII comments break parsing.
cd /d "%~dp0"
set HTTPS_PROXY=http://127.0.0.1:10808
set HTTP_PROXY=http://127.0.0.1:10808
set PYTHONIOENCODING=utf-8
py scraper/build.py %*
