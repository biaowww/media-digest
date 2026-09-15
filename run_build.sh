#!/usr/bin/env bash
# media-digest unattended build for macOS / Linux: Drive content -> fetch/sync -> git push.
# Same job as run_build.bat on the Windows PC. Any machine that is on picks up new shows.
#   ./run_build.sh          interactive: prints result
#   ./run_build.sh task     quiet: for launchd every minute (no log line unless something changed/failed)
cd "$(dirname "$0")" || exit 1
export PYTHONIOENCODING=utf-8
PY=$(command -v python3 || command -v python)
if [ "$1" = "task" ]; then
  exec "$PY" scraper/build.py --quiet
fi
"$PY" scraper/build.py "$@"
rc=$?
echo
if [ $rc -ne 0 ]; then
  echo "*** BUILD HAD ERRORS - see above or scraper/logs/build.log ***"
else
  echo "Done. Page updates in about 1 minute: https://biaowww.github.io/media-digest/site/"
fi
exit $rc
