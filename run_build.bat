@echo off
rem media-digest 无人值守构建：Drive 内容 → fetch/sync → push。计划任务 media-digest-build 每天调用。
cd /d "%~dp0"
set HTTPS_PROXY=http://127.0.0.1:10808
set HTTP_PROXY=http://127.0.0.1:10808
set PYTHONIOENCODING=utf-8
py scraper\build.py %*
