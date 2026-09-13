#!/usr/bin/env python3
"""
build.py — 无人值守构建：扫 Drive 内容目录 → 缺客观数据的剧先 fetch → sync 内容 → 有变更就 commit + push。

chat 会话只需把 route.json（含 meta.ids）写进 Drive shows/<slug>/；这台机定时跑本脚本，页面自动更新。
王彪不需要在任何对话里说"有新剧了"。

  py scraper/build.py               # 增量：只 fetch 还没有 shows/<slug>.json 的剧；全部 sync；有变更才 push
  py scraper/build.py --refresh     # 所有剧重新抓客观数据（评分会变，建议每周一次）
  py scraper/build.py --no-push     # 本地构建不推

route.json 里的 meta 块（新剧必填，老剧可省）：
  "meta": { "title": "Monster", "title_cn": "怪物", "year": 2004,
            "ids": { "mal": 19, "bangumi": 1959, "imdb": "tt0434706", "tmdb": 30981, "wiki": "List of Monster episodes" } }

日志：scraper/logs/build.log（已 gitignore）。git 网络操作走 HTTPS_PROXY（本机必需）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import content_dir  # noqa: E402
from sync import sync_one, load_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOWS = ROOT / "shows"
LOG = ROOT / "scraper" / "logs" / "build.log"
PY = sys.executable
PROXY = os.environ.get("HTTPS_PROXY") or "http://127.0.0.1:10808"


def log(msg: str):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    env = dict(os.environ, HTTPS_PROXY=PROXY, HTTP_PROXY=PROXY, PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, encoding="utf-8", errors="replace", **kw)


def fetch_args(slug: str, meta: dict) -> list[str] | None:
    ids = meta.get("ids") or {}
    if not ids:
        return None
    args = [PY, str(ROOT / "scraper" / "fetch.py"), slug]
    for k in ("mal", "bangumi", "imdb", "tmdb", "wiki"):
        if ids.get(k) not in (None, ""):
            args += [f"--{k}", str(ids[k])]
    for k, flag in (("title", "--title"), ("title_cn", "--title-cn"), ("year", "--year")):
        if meta.get(k) not in (None, ""):
            args += [flag, str(meta[k])]
    return args


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="所有剧重新抓客观数据")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()

    src_root = content_dir()
    slugs = [p.name for p in sorted(src_root.iterdir()) if p.is_dir() and not p.name.startswith("_") and (p / "route.json").exists()]
    log(f"build start — {len(slugs)} show(s) on Drive: {', '.join(slugs) or '-'}")
    failed = []
    for slug in slugs:
        try:
            content = load_json(src_root / slug / "route.json")
        except Exception as e:
            log(f"[{slug}] route.json unreadable: {e}"); failed.append(slug); continue
        meta = content.get("meta") if isinstance(content, dict) else None
        need_fetch = a.refresh or not (SHOWS / f"{slug}.json").exists()
        if need_fetch:
            args = fetch_args(slug, meta or {}) if not (SHOWS / f"{slug}.json").exists() else [PY, str(ROOT / "scraper" / "fetch.py"), slug]
            if args is None:
                log(f"[{slug}] no shows/{slug}.json and route.json has no meta.ids — skipped (add meta.ids in Drive)"); failed.append(slug); continue
            r = run(args)
            tail = (r.stdout.strip().splitlines() or [""])[-1]
            log(f"[{slug}] fetch rc={r.returncode}: {tail}")
            if r.returncode != 0:
                log(r.stderr.strip()[-400:]); failed.append(slug); continue
        try:
            ok = sync_one(slug)
        except Exception as e:
            log(f"[{slug}] sync crashed: {e}"); ok = False
        if not ok:
            failed.append(slug)

    st = run(["git", "status", "--porcelain", "--", "shows", "site/assets"]).stdout.strip()  # 无人值守只提交内容产物，不卷代码改动
    if not st:
        log("no changes");
    elif a.no_push:
        log(f"changes (not pushed):\n{st}")
    else:
        changed = sorted({l[3:].split("/")[1].replace(".json", "") for l in st.splitlines() if l[3:].startswith("shows/")})
        run(["git", "add", "-A", "--", "shows", "site/assets"])
        msg = f"build: {', '.join(changed) or 'update'} ({dt.date.today()})"
        r = run(["git", "-c", "user.name=biaowww", "-c", "user.email=wvngbvao483@gmail.com", "commit", "-q", "-m", msg])
        log(f"commit rc={r.returncode} {msg}")
        r = run(["git", "push", "-q", "origin", "main"])
        log(f"push rc={r.returncode} {r.stderr.strip()[-200:] if r.returncode else 'ok'}")
        if r.returncode:
            failed.append("push")
    log(f"build end — failed: {failed or 'none'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
