#!/usr/bin/env python3
"""
fetch.py — 抓一部剧的客观数据，写进 shows/<slug>.json 的 meta / about / episodes。
**绝不触碰 route 与 intro**（那是 session 里人写的主观内容）；写盘前做深比较断言，保证幂等。

用法：
  # 第一次：给出各源 ID（缺哪个跳哪个，至少一个）
  py scraper/fetch.py monster-2004 --mal 19 --bangumi 1959 --imdb tt0434706 --wiki "List of Monster episodes" \
        --title "Monster" --title-cn 怪物 --year 2004

  # 之后重跑：ID 已存在 meta.ids 里，一条命令刷新
  py scraper/fetch.py monster-2004
  py scraper/fetch.py monster-2004 --only mal,imdb --no-cache
  py scraper/fetch.py frieren-season-2-2026 --season 2 --mal ... --imdb ...   # 一季一个 slug 的剧

  # 找 ID（Jikan / Bangumi / TMDB 搜索，人工确认后再填）
  py scraper/fetch.py resolve "Monster"

各源字段合并优先级见 PREFER；评分分源并存在 episodes[].sources{}，不加权、不算综合分。
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_cache import Http  # noqa: E402
from sources import bangumi, imdb, mal, tmdb, wiki  # noqa: E402
import validate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOWS = ROOT / "shows"
SCHEMA_VERSION = 1

SOURCES = {"mal": mal, "bangumi": bangumi, "imdb": imdb, "tmdb": tmdb, "wiki": wiki}

# 分集字段：从哪些源、按什么顺序取第一个非空值
PREFER = {
    "title_native": ["mal", "bangumi", "wiki"],
    "title_en": ["wiki", "mal", "tmdb"],
    "title_cn": ["bangumi", "tmdb"],
    "aired": ["mal", "bangumi", "tmdb", "wiki"],
    "synopsis_en": ["wiki", "tmdb"],
    "synopsis_zh": ["tmdb", "bangumi"],
}
# 作品级字段
PREFER_SERIES = {
    "title": ["mal", "tmdb"],
    "title_cn": ["bangumi", "tmdb"],
    "title_native": ["mal", "bangumi"],
    "year": ["mal", "bangumi", "tmdb"],
    "eps": ["mal", "bangumi", "tmdb"],
    "cover": ["mal", "tmdb", "bangumi"],
    "backdrop": ["tmdb"],
    "synopsis_en": ["mal", "tmdb"],
    "synopsis_zh": ["bangumi", "tmdb"],
    "genres": ["mal", "tmdb"],
    "studios": ["mal"],
}
# 每源写进 episodes[].sources.<src> 的字段
SOURCE_FIELDS = {
    "mal": ["score", "votes", "forum_replies", "url"],
    "imdb": ["rating", "votes", "tconst", "season", "episode"],
    "tmdb": ["vote_average", "vote_count", "still", "season", "episode"],
    "bangumi": ["score", "votes", "comments", "url"],
}
KPI_ORDER = ["imdb", "mal", "tmdb", "bangumi"]  # 页面默认 KPI；不合并、不加权（2026-09-13 定）


def load_show(slug: str) -> dict:
    p = SHOWS / f"{slug}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"meta": {"slug": slug, "schema_version": SCHEMA_VERSION, "ids": {}},
            "about": {}, "intro": {}, "episodes": [], "route": []}


def pick(fetched: dict, prefs: list[str], key: str, n: int | None = None):
    for src in prefs:
        f = fetched.get(src)
        if not f:
            continue
        d = f["episodes"].get(n) if n is not None else f["series"]
        v = (d or {}).get(key)
        if v not in (None, "", []):
            return v
    return None


def merge(show: dict, fetched: dict, args) -> dict:
    meta = show["meta"]
    about = show.get("about") or {}
    old_by_n = {e["n"]: e for e in show.get("episodes", [])}

    # ---- meta ----
    ids = dict(meta.get("ids") or {})
    for src in SOURCES:
        v = getattr(args, src, None)
        if v:
            ids[src] = v
    meta["ids"] = ids
    if args.season:
        meta["season"] = int(args.season)
    if args.unit:
        meta["unit"] = args.unit
    for k, cli in (("title", args.title), ("title_cn", args.title_cn), ("title_native", None), ("year", args.year)):
        v = cli or meta.get(k) or pick(fetched, PREFER_SERIES[k], k)
        if v not in (None, ""):
            meta[k] = int(v) if k == "year" else v

    # ---- episodes ----
    all_n = set(old_by_n) | {n for f in fetched.values() for n in f["episodes"]}
    episodes = []
    for n in sorted(all_n):
        ep = copy.deepcopy(old_by_n.get(n) or {"n": n})
        ep.setdefault("sources", {})
        ep.setdefault("synopsis", {})
        for field, prefs in PREFER.items():
            v = pick(fetched, prefs, field, n)
            if v is None:
                continue
            if field.startswith("synopsis_"):
                ep["synopsis"][field.split("_")[1]] = v
            else:
                ep[field] = v
        for src, keys in SOURCE_FIELDS.items():
            f = fetched.get(src)
            if f and n in f["episodes"]:
                ep["sources"][src] = {k: f["episodes"][n].get(k) for k in keys if f["episodes"][n].get(k) is not None}
        # heat：「这集让多少人想说话」，与评分是两个维度，单列、不进 sources 评分位
        heat = {}
        s = ep["sources"]
        if (s.get("mal") or {}).get("forum_replies") is not None:
            heat["mal_replies"] = s["mal"]["forum_replies"]
        if (s.get("bangumi") or {}).get("comments") is not None:
            heat["bangumi_comments"] = s["bangumi"]["comments"]
        if (s.get("imdb") or {}).get("votes") is not None:
            heat["imdb_votes"] = s["imdb"]["votes"]
        if heat:
            ep["heat"] = heat
        episodes.append(ep)
    # 数据源脏数据：两集梗概一字不差（TMDB 常见复制错），全部置空，页面回退另一语言
    for lang in ("zh", "en"):
        seen: dict[str, list[int]] = {}
        for e in episodes:
            v = (e.get("synopsis") or {}).get(lang)
            if v and len(v) > 40:
                seen.setdefault(v.strip(), []).append(e["n"])
        dup_ns = {n for ns in seen.values() if len(ns) > 1 for n in ns}
        if dup_ns:
            print(f"  note: synopsis.{lang} identical across episodes {sorted(dup_ns)} — dropped (source copy error)")
            for e in episodes:
                if e["n"] in dup_ns:
                    e["synopsis"][lang] = None
    show["episodes"] = episodes

    # 总集数：优先各源声明的集数（mal/bangumi/tmdb），没有才用抓到的最大集号
    declared = pick(fetched, PREFER_SERIES["eps"], "eps")
    meta["total_eps"] = int(declared) if declared else (meta.get("total_eps") or (episodes[-1]["n"] if episodes else 0))
    # 超出总集数、且本轮没有任何源报告的旧条目 = 上次抓错的残留（如 IMDb 特别篇），清掉
    reported = {n for f in fetched.values() for n in f["episodes"]}
    stale = [e["n"] for e in episodes if e["n"] > meta["total_eps"] and e["n"] not in reported]
    if stale:
        print(f"  note: dropping stale episodes beyond total {meta['total_eps']}: {stale}")
        episodes = [e for e in episodes if e["n"] not in stale]
        show["episodes"] = episodes
    # 多季剧：IMDb / TMDB / 维基常把后续季也列进来（顺序编号），按声明的本季集数截断
    extra = [e["n"] for e in episodes if e["n"] > meta["total_eps"]]
    if extra:
        print(f"  note: dropping {len(extra)} episodes beyond declared total {meta['total_eps']} (n={extra[0]}..{extra[-1]}) — later seasons leaking in")
        episodes = [e for e in episodes if e["n"] <= meta["total_eps"]]
        show["episodes"] = episodes
    if not meta.get("primary_kpi") or args.primary_kpi:
        meta["primary_kpi"] = args.primary_kpi or "imdb"
    meta["updated"] = dt.date.today().isoformat()
    meta["schema_version"] = SCHEMA_VERSION

    # ---- about（scraper 自有，主观 intro 另存）----
    for k, prefs in PREFER_SERIES.items():
        if k in ("title", "title_cn", "title_native", "year", "eps"):
            continue
        v = pick(fetched, prefs, k)
        if v is not None:
            if k.startswith("synopsis_"):
                about.setdefault("synopsis", {})[k.split("_")[1]] = v
            else:
                about[k] = v
    scores = dict(about.get("scores") or {})
    links = dict(about.get("links") or {})
    for src, f in fetched.items():
        s = f["series"]
        if s.get("score") is not None or s.get("votes") is not None:
            scores[src] = {k: s[k] for k in ("score", "votes", "rank") if s.get(k) is not None}
        if s.get("url"):
            links[src] = s["url"]
    about["scores"], about["links"] = scores, links
    if fetched.get("mal", {}).get("series", {}).get("characters"):
        about["characters"] = fetched["mal"]["series"]["characters"]
    if fetched.get("bangumi", {}).get("series", {}).get("characters"):
        about["characters_bangumi"] = fetched["bangumi"]["series"]["characters"]
    show["about"] = about

    # 顺序固定，diff 友好
    return {"meta": meta, "about": about, "intro": show.get("intro") or {},
            "episodes": episodes, "route": show.get("route") or []}


def write_index():
    items = []
    for p in sorted(SHOWS.glob("*.json")):
        if p.name.startswith("_") or p.name == "index.json":
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        m, r = d["meta"], d.get("route") or []
        items.append({
            "slug": m["slug"], "title": m.get("title"), "title_cn": m.get("title_cn"), "year": m.get("year"),
            "total_eps": m.get("total_eps"), "unit": m.get("unit") or "集", "updated": m.get("updated"),
            "cover": (d.get("intro") or {}).get("cover") or (d.get("about") or {}).get("cover"),
            "watch_eps": sum(x["eps"][1] - x["eps"][0] + 1 for x in r if x["kind"] == "watch"),
            "bridges": sum(1 for x in r if x["kind"] == "bridge"),
        })
    (SHOWS / "index.json").write_text(json.dumps({"shows": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return items


def cmd_fetch(args):
    show = load_show(args.slug)
    before_route, before_intro = copy.deepcopy(show.get("route") or []), copy.deepcopy(show.get("intro") or {})
    http = Http(use_cache=not args.no_cache)
    ids = dict(show["meta"].get("ids") or {})
    for src in SOURCES:
        if getattr(args, src, None):
            ids[src] = getattr(args, src)
    only = set(args.only.split(",")) if args.only else set(SOURCES)
    if not ids:
        if not args.total:
            sys.exit("no source ids — pass at least one of --mal/--bangumi/--imdb/--tmdb/--wiki, or --total N for content with no rating source (novels)")
        # 无数据源的内容（小说 / 冷门剧）：只建骨架，标题等后面由 episodes.json 的 notes 补
        show["meta"].update({k: v for k, v in (("title", args.title), ("title_cn", args.title_cn)) if v})
        if args.year:
            show["meta"]["year"] = int(args.year)
        show["meta"]["total_eps"] = int(args.total)
        show["meta"]["unit"] = args.unit or show["meta"].get("unit") or "集"
        show["meta"].setdefault("title", args.slug)
        show["meta"].setdefault("primary_kpi", "imdb")
        show["meta"]["updated"] = dt.date.today().isoformat()
        show["meta"]["schema_version"] = SCHEMA_VERSION
        old = {e["n"]: e for e in show.get("episodes", [])}
        show["episodes"] = [old.get(n) or {"n": n, "sources": {}, "synopsis": {}} for n in range(1, int(args.total) + 1)]
        errors, warnings = validate.check(show)
        for e in errors:
            print("  ERROR:", e)
        if errors:
            sys.exit("validation failed; not written")
        out = SHOWS / f"{args.slug}.json"
        out.write_text(json.dumps(show, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        write_index()
        print(f"wrote {out.relative_to(ROOT)} — {args.total} {show['meta']['unit']} skeleton, no rating sources; route preserved ({len(show.get('route') or [])} nodes)")
        return

    fetched = {}
    for src, mod in SOURCES.items():
        if src not in ids or src not in only:
            continue
        print(f"[{src}] id={ids[src]}")
        try:
            season = args.season or (show["meta"].get("season"))
            fetched[src] = mod.fetch(ids[src], http, season=int(season)) if src in ("imdb", "tmdb") and season else mod.fetch(ids[src], http)
        except Exception as e:  # 单源失败不拖垮整体；保留上次数据
            print(f"  !! {src} failed, keeping previous data: {e}")

    if not fetched:
        sys.exit("all sources failed; nothing written")

    before_notes = {e["n"]: e.get("notes") for e in show.get("episodes", []) if e.get("notes")}
    new = merge(show, fetched, args)
    assert new["route"] == before_route and new["intro"] == before_intro, "route/intro must never change here"
    after_notes = {e["n"]: e.get("notes") for e in new["episodes"] if e.get("notes")}
    assert after_notes == before_notes, "episodes[].notes (human-written) must never change here"

    errors, warnings = validate.check(new)
    for w in warnings:
        print("  warn:", w)
    if errors:
        for e in errors:
            print("  ERROR:", e)
        sys.exit("validation failed; not written")

    out = SHOWS / f"{args.slug}.json"
    out.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    write_index()
    srcs = ", ".join(f"{s}={len(f['episodes'])}" for s, f in fetched.items())
    print(f"wrote {out.relative_to(ROOT)} — {len(new['episodes'])} episodes ({srcs}); route preserved ({len(new['route'])} nodes)")


def cmd_resolve(args):
    http = Http()
    for name, mod in (("mal", mal), ("bangumi", bangumi), ("tmdb", tmdb)):
        try:
            rows = mod.search(args.query, http)
        except Exception as e:
            print(f"[{name}] search failed: {e}")
            continue
        print(f"[{name}]" + ("  (no key)" if name == "tmdb" and not rows else ""))
        for r in rows:
            print("   ", json.dumps(r, ensure_ascii=False))
    print("\nIMDb: 搜 https://www.imdb.com/find/?q=... 取剧集主条目 ttXXXXXXX（注意是系列不是单集）")
    print("Wiki: 页面名通常是 'List of <Title> episodes'，没有独立列表页时试主条目名")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("fetch", help="抓取/刷新一部剧（默认子命令）")
    f.add_argument("slug")
    for src in SOURCES:
        f.add_argument(f"--{src}")
    f.add_argument("--title"); f.add_argument("--title-cn", dest="title_cn"); f.add_argument("--year")
    f.add_argument("--primary-kpi", dest="primary_kpi", choices=KPI_ORDER)
    f.add_argument("--season", help="一季一个 slug 时指定季号：imdb/tmdb 只取该季，集号=本季集号")
    f.add_argument("--total", help="没有任何评分源时（小说等）：直接给总数，只建骨架")
    f.add_argument("--unit", help="计数单位，默认「集」；小说写「章」")
    f.add_argument("--only", help="只跑这些源，逗号分隔，如 mal,imdb")
    f.add_argument("--no-cache", action="store_true")
    r = sub.add_parser("resolve", help="按名字搜各源 ID")
    r.add_argument("query")

    argv = sys.argv[1:]
    if argv and argv[0] not in ("fetch", "resolve", "-h", "--help"):
        argv = ["fetch"] + argv
    args = ap.parse_args(argv)
    if args.cmd == "resolve":
        cmd_resolve(args)
    elif args.cmd == "fetch":
        cmd_fetch(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
