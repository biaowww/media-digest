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


def pick_file(src: Path, stem: str) -> Path | None:
    """Drive 工具改不了正文，会话只能「新建同名 + 旧的移回收站」，结果常留下 `episodes (1).json`。
    所以不认死文件名：`<stem>.json` 与 `<stem> (N).json` 里取修改时间最新的一份。"""
    cands = [p for p in src.iterdir() if p.is_file() and re.fullmatch(re.escape(stem) + r"(?: \(\d+\))?\.json", p.name)]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


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


# 人定的分组 / 标注字段：从 Drive route.json 的 meta 带进 show.meta（脚本抓的客观字段不受影响）
LABEL_KEYS = ("series", "series_title", "version_label", "kind")


def read_meta_labels(src: Path) -> dict:
    rf = pick_file(src, "route")
    if rf is None:
        return {}
    data = load_json(rf)
    meta = data.get("meta") if isinstance(data, dict) else None
    return {k: meta[k] for k in LABEL_KEYS if isinstance(meta, dict) and meta.get(k) not in (None, "")}


KIND_ALIASES = {"main": "recurring", "regular": "recurring", "常驻": "recurring", "阶段": "arc", "oneoff": "one-off", "once": "one-off", "一次": "one-off"}


def read_notes(src: Path) -> tuple[dict[int, dict] | None, int | None]:
    """episodes.json → {n: notes}；也返回顶层 spoiler_gate_from（可选）。"""
    f = pick_file(src, "episodes")
    if f is None:
        return None, None
    data = load_json(f)
    gate = None
    if isinstance(data, dict):
        gate = data.get("spoiler_gate_from")
        items = data.get("episode_notes") or data.get("episodes") or data.get("notes")
        if isinstance(items, dict):  # {"1": {...}}
            items = [dict(v, n=int(k)) for k, v in items.items()]
    else:
        items = data
    if not isinstance(items, list):
        raise ValueError("episodes.json must be a list or an object with episode_notes[]")
    out: dict[int, dict] = {}
    for x in items:
        n = int(x.get("n") or x.get("episode") or 0)
        if not n:
            continue
        note = {}
        if x.get("title_cn"):
            note["title_cn"] = x["title_cn"]
        note["summary"] = (x.get("summary") or x.get("synopsis") or "").strip()
        new = []
        for c in x.get("new") or x.get("new_characters") or []:
            c = dict(c)
            k = str(c.get("kind") or "one-off").strip().lower()
            c["kind"] = KIND_ALIASES.get(k, k)
            new.append(c)
        if new:
            note["new"] = new
        out[n] = note
    return out, (int(gate) if gate else None)


def read_content(src: Path) -> tuple[dict | None, list | None]:
    intro, route = None, None
    rf, inf = pick_file(src, "route"), pick_file(src, "intro")
    if rf is not None:
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
    if inf is not None:
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
    for stem in ("route", "episodes", "intro"):
        n = [p.name for p in src.iterdir() if p.is_file() and re.fullmatch(re.escape(stem) + r"(?: \(\d+\))?\.json", p.name)]
        if len(n) > 1:
            print(f"[{slug}] note: {len(n)} copies of {stem} on Drive {sorted(n)} — using the newest: {pick_file(src, stem).name}")
    try:
        intro, route = read_content(src)
    except ValueError as e:
        print(f"[{slug}] {e}")
        return False

    try:
        notes, gate = read_notes(src)
    except ValueError as e:
        print(f"[{slug}] {e}")
        return False

    changed = []
    labels = read_meta_labels(src)
    before = {k: show["meta"].get(k) for k in LABEL_KEYS}
    for k in LABEL_KEYS:
        if k in labels:
            show["meta"][k] = labels[k]
        else:
            show["meta"].pop(k, None)
    if {k: show["meta"].get(k) for k in LABEL_KEYS} != before:
        changed.append("labels")
    if notes is not None:
        by_n = {e["n"]: e for e in show.get("episodes", [])}
        total = show["meta"].get("total_eps") or 0
        stray = [n for n in notes if n not in by_n]
        if stray:
            print(f"[{slug}] warn: episodes.json has notes for unknown episodes {stray[:8]} — ignored")
        for e in show.get("episodes", []):
            if e["n"] in notes:
                e["notes"] = notes[e["n"]]
            else:
                e.pop("notes", None)
        changed.append(f"notes({len(notes) - len(stray)})")
    if intro is not None:
        intro.pop("spoiler_gate_from", None)  # 2026-09-13 王彪定：不做二次确认门控，字段忽略
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
