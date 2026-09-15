#!/usr/bin/env python3
"""
build.py — 无人值守构建：扫 Drive 内容目录 → 缺客观数据的剧先 fetch → sync 内容 → 有变更就 commit + push。

chat 会话只需把 route.json（含 meta.ids）写进 Drive shows/<slug>/；这台机定时跑本脚本，页面自动更新。
王彪不需要在任何对话里说"有新剧了"。

  py scraper/build.py               # 增量：只 fetch 还没有 shows/<slug>.json 的剧；全部 sync；有变更才 push
  py scraper/build.py --refresh     # 所有剧重新抓客观数据（评分会变，建议每周一次）
  py scraper/build.py --no-push     # 本地构建不推
  py scraper/build.py --quiet       # 计划任务每 10 分钟调用：无变化不写日志

route.json 里的 meta 块（新剧必填，老剧可省）：
  "meta": { "title": "Monster", "title_cn": "怪物", "year": 2004,
            "ids": { "mal": 19, "bangumi": 1959, "imdb": "tt0434706", "tmdb": 30981, "wiki": "List of Monster episodes" } }

日志：scraper/logs/build.log（已 gitignore）。git 网络操作走 HTTPS_PROXY（本机必需）。
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
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
PROXY = os.environ.get("HTTPS_PROXY") or ("http://127.0.0.1:10808" if os.name == "nt" else "")  # 家里 PC 必须走代理；Mac 默认直连


def log(msg: str):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if PROXY:
        env.update(HTTPS_PROXY=PROXY, HTTP_PROXY=PROXY)
    return subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, encoding="utf-8", errors="replace", **kw)


def fetch_args(slug: str, meta: dict) -> list[str] | None:
    ids = {k: v for k, v in (meta.get("ids") or {}).items() if v not in (None, "")}
    if not ids and not meta.get("total_eps"):
        return None
    args = [PY, str(ROOT / "scraper" / "fetch.py"), slug]
    for k in ("mal", "bangumi", "imdb", "tmdb", "wiki"):
        if ids.get(k) not in (None, ""):
            args += [f"--{k}", str(ids[k])]
    if not ids:  # 无评分源（小说等）：按 meta.total_eps 建骨架
        args += ["--total", str(meta["total_eps"])]
    for k, flag in (("title", "--title"), ("title_cn", "--title-cn"), ("year", "--year"), ("season", "--season"), ("unit", "--unit")):
        if meta.get(k) not in (None, ""):
            args += [flag, str(meta[k])]
    return args


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="所有剧重新抓客观数据")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="每 10 分钟的静默巡检：没变化、没失败时不写 build.log，只更新 logs/last-run.txt")
    a = ap.parse_args()
    if a.quiet:  # 先缓冲日志，结束时决定要不要落盘
        global log
        _buf: list[str] = []
        def log(msg: str):  # noqa: F811
            _buf.append(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}")
            print(_buf[-1], flush=True)

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
                log(f"[{slug}] no shows/{slug}.json and route.json has neither meta.ids nor meta.total_eps — skipped (add them in Drive)"); failed.append(slug); continue
            r = run(args)
            tail = (r.stdout.strip().splitlines() or [""])[-1]
            log(f"[{slug}] fetch rc={r.returncode}: {tail}")
            if r.returncode != 0:
                log(r.stderr.strip()[-400:]); failed.append(slug); continue
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                ok = sync_one(slug)
        except Exception as e:
            buf.write(f"[{slug}] sync crashed: {e}\n"); ok = False
        for line in buf.getvalue().strip().splitlines():
            log(line)
        if not ok:
            failed.append(slug)

    paths = [x for x in ("shows", "site/assets") if (ROOT / x).exists()]  # 无人值守只提交内容产物，不卷代码改动
    st = run(["git", "status", "--porcelain", "--", *paths]).stdout.strip()
    if not st:
        log("no changes");
    elif a.no_push:
        log(f"changes (not pushed):\n{st}")
    else:
        changed = sorted({l[3:].split("/")[1].replace(".json", "") for l in st.splitlines() if l[3:].startswith("shows/")})
        r = run(["git", "add", "-A", "--", *paths])
        if r.returncode:
            log(f"git add failed: {r.stderr.strip()[-200:]}"); failed.append("commit")
        else:
            # 多机（home-pc / mac）都在跑巡检：先把别人推的拉下来，避免 push 被拒
            pr = run(["git", "pull", "--rebase", "--autostash", "-q", "origin", "main"])
            if pr.returncode:
                log(f"git pull --rebase failed: {pr.stderr.strip()[-200:]}")
            msg = f"build: {', '.join(changed) or 'update'} ({dt.date.today()})"
            r = run(["git", "-c", "user.name=biaowww", "-c", "user.email=wvngbvao483@gmail.com", "commit", "-q", "-m", msg])
            if r.returncode:
                log(f"commit FAILED rc={r.returncode}: {(r.stderr or r.stdout).strip()[-200:]}"); failed.append("commit")
            else:
                log(f"commit ok: {msg}")
                r = run(["git", "push", "-q", "origin", "main"])
                if r.returncode:  # 刚好撞上另一台机的 push：再拉一次重推
                    run(["git", "pull", "--rebase", "-q", "origin", "main"])
                    r = run(["git", "push", "-q", "origin", "main"])
                log(f"push rc={r.returncode} {r.stderr.strip()[-200:] if r.returncode else 'ok'}")
                if r.returncode:
                    failed.append("push")
    log(f"build end — failed: {failed or 'none'}")
    if not a.no_push and st:
        log("page: https://biaowww.github.io/media-digest/site/  (GitHub Pages 部署约 1 分钟)")
    if a.quiet:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        (LOG.parent / "last-run.txt").write_text(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} failed={failed or 'none'} changes={'yes' if st else 'no'}\n", encoding="utf-8")
        if st or failed:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write("\n".join(_buf) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
