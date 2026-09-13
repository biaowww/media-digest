#!/usr/bin/env python3
"""
sync.py — 把 Drive 上各会话写的主观内容（intro / route）同步进仓库的 shows/<slug>.json。

内容源（唯一真相）：<Drive claude根>/domains/personal/media-digest/shows/<slug>/
  route.json   路线 + 介绍。两种写法都收：
                 ① 对象 {"intro": {...}, "route": [...], "route_note": "..."}（chat 会话产出的样子）
                 ② 纯数组 [ {kind, eps, ...}, ... ]（只有路线）
  intro.json   可选，单独的介绍；存在时覆盖 route.json 里的 intro
  *.jpg/png/webp  可选图片；intro.cover 写文件名即可，同步时复制到 site/assets/<slug>/ 并改写路径

键名归一化（内容不改，只改键名）：
  intro.spoiler_free_summary → intro.synopsis
  intro.character_motivations ["名：动机", ...] → intro.characters [{name_cn, motivation}]
  intro.route_note / 顶层 route_note → intro.route_note
  route[].eps [4] → [4, 4]

用法：
  py scraper/sync.py monster-2004
  py scraper/sync.py --all          # Drive 目录下所有 slug
  py scraper/sync.py x --dry-run    # 只校验不写

只改 intro / route（以及封面图），meta / about / episodes 原样保留。写前必过校验。
"""
from __future__ import annotations

import argparse
import json
import re
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


def normalize_intro(intro: dict) -> dict:
    out = dict(intro)
    if "spoiler_free_summary" in out and "synopsis" not in out:
        out["synopsis"] = out.pop("spoiler_free_summary")
    if "character_motivations" in out and "characters" not in out:
        chars = []
        for item in out.pop("character_motivations") or []:
            if isinstance(item, dict):
                chars.append(item)
                continue
            m = re.match(r"\s*([^：:]+?)\s*[：:]\s*(.+)$", str(item))
            chars.append({"name_cn": m.group(1), "motivation": m.group(2)} if m else {"name_cn": str(item)})
        out["characters"] = chars
    for c in out.get("characters") or []:
        if "name" not in c and "name_cn" in c:
            pass  # schema 允许只有 name_cn
    return out


def normalize_route(route: list) -> list:
    out = []
    for node in route:
        node = dict(node)
        eps = node.get("eps")
        if isinstance(eps, list) and len(eps) == 1:
            node["eps"] = [eps[0], eps[0]]
        elif isinstance(eps, int):
            node["eps"] = [eps, eps]
        out.append(node)
    return out


def read_content(src: Path) -> tuple[dict | None, list | None]:
    intro, route = None, None
    rf, inf = src / "route.json", src / "intro.json"
    if rf.exists():
        data = load_json(rf)
        if isinstance(data, list):
            route = data
        elif isinstance(data, dict):
            route = data.get("route")
            intro = data.get("intro")
            note = data.get("route_note")
            if note and intro is not None and "route_note" not in intro:
                intro = dict(intro, route_note=note)
        else:
            raise ValueError("route.json must be an array or an object with route/intro")
    if inf.exists():
        intro = load_json(inf)
        if not isinstance(intro, dict):
            raise ValueError("intro.json must be an object")
    return (normalize_intro(intro) if intro is not None else None,
            normalize_route(route) if route is not None else None)


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
    try:
        intro, route = read_content(src)
    except ValueError as e:
        print(f"[{slug}] {e}")
        return False

    changed = []
    if intro is not None:
        cover = intro.get("cover")
        if cover and "://" not in cover and (src / cover).is_file():
            assets = ROOT / "site" / "assets" / slug
            if not dry_run:
                assets.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / cover, assets / Path(cover).name)
            intro["cover"] = f"assets/{slug}/{Path(cover).name}"
        show["intro"] = intro
        changed.append("intro")
    if route is not None:
        show["route"] = route
        changed.append("route")
    if not changed:
        print(f"[{slug}] nothing to sync (no route.json / intro.json in {src})")
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
    dst.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
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
