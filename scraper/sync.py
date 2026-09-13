#!/usr/bin/env python3
"""
sync.py — 把 Drive 上各会话写的主观内容（intro / route）同步进仓库的 shows/<slug>.json。

内容源：<Drive claude根>/domains/personal/media-digest/shows/<slug>/
  intro.json   作品介绍（头图 / 无剧透简介 / 人物动机 / 亮点 / 地位）
  route.json   路线（watch / bridge 节点数组，或 {"route": [...]}）
  *.jpg/png/webp  可选图片；intro.cover 写文件名即可，同步时复制到 site/assets/<slug>/ 并改写路径

用法：
  py scraper/sync.py monster-2004
  py scraper/sync.py --all          # Drive 目录下所有有内容的 slug
  py scraper/sync.py x --dry-run    # 只校验不写

只改 intro / route（以及封面图），meta / about / episodes 原样保留。写前必过校验。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate  # noqa: E402
from fetch import ROOT, SHOWS, write_index  # noqa: E402
from paths import content_dir  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))  # 容忍 BOM


def sync_one(slug: str, dry_run: bool = False) -> bool:
    src = content_dir() / slug
    dst = SHOWS / f"{slug}.json"
    if not src.is_dir():
        print(f"[{slug}] no content folder on Drive: {src}")
        return False
    if not dst.exists():
        print(f"[{slug}] shows/{slug}.json missing — run `py scraper/fetch.py {slug} --mal ... ` first")
        return False
    show = load_json(dst)

    intro_f, route_f = src / "intro.json", src / "route.json"
    changed = []
    if intro_f.exists():
        intro = load_json(intro_f)
        if not isinstance(intro, dict):
            print(f"[{slug}] intro.json must be an object"); return False
        cover = intro.get("cover")
        if cover and "://" not in cover and (src / cover).is_file():
            assets = ROOT / "site" / "assets" / slug
            if not dry_run:
                assets.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / cover, assets / Path(cover).name)
            intro["cover"] = f"assets/{slug}/{Path(cover).name}"
        show["intro"] = intro
        changed.append("intro")
    if route_f.exists():
        route = load_json(route_f)
        if isinstance(route, dict):
            route = route.get("route")
        if not isinstance(route, list):
            print(f"[{slug}] route.json must be an array (or {{\"route\": [...]}})"); return False
        show["route"] = route
        changed.append("route")
    if not changed:
        print(f"[{slug}] nothing to sync (no intro.json / route.json in {src})")
        return False

    errors, warnings = validate.check(show)
    for w in warnings:
        print(f"[{slug}] warn: {w}")
    if errors:
        for e in errors:
            print(f"[{slug}] ERROR: {e}")
        print(f"[{slug}] not written — fix the Drive files above")
        return False
    if dry_run:
        print(f"[{slug}] dry-run ok: {', '.join(changed)} — {validate.summary(show)}")
        return True
    ordered = {k: show[k] for k in ("meta", "about", "intro", "episodes", "route") if k in show}
    dst.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_index()
    print(f"[{slug}] synced {', '.join(changed)} — {validate.summary(show)}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.all:
        slugs = [p.name for p in sorted(content_dir().iterdir()) if p.is_dir() and not p.name.startswith("_")]
    elif a.slug:
        slugs = [a.slug]
    else:
        ap.error("give a slug or --all")
    ok = [sync_one(s, a.dry_run) for s in slugs]
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    main()
