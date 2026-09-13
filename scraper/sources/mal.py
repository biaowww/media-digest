"""MyAnimeList：分集数据**直抓 HTML**（主路），作品级信息 / 角色走 Jikan v4（尽力而为）。

为什么不只用 Jikan：Jikan 是第三方代理，MAL 一拒连它就整体 504（2026-09-13 实测一整天）；
而且 Jikan 的分集只有 1 位小数、没有论坛回复数。HTML 的 episode 列表页有：
  data-raw 两位小数的投票均分（1–5）、论坛回复数（热度）、英/罗马/日文标题、首播日。
robots.txt 对普通 UA 不禁 /anime/；自用非商用，1 req/s，本地缓存。

MAL 分集投票是 1–5 分制，分布极窄（Monster 全 74 集 4.3–4.9），仅作参考维度，不做主 KPI。
"""
from __future__ import annotations

import datetime as dt
import html
import re

JIKAN = "https://api.jikan.moe/v4"
MAL = "https://myanimelist.net"
HTML_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) media-digest/0.1 (private, non-commercial)"}

_ROW = re.compile(r'<tr class="episode-list-data">(.*?)</tr>', re.S)
_NUM = re.compile(r'class="episode-number[^"]*" data-raw="(\d+)"')
_TITLE = re.compile(r'class="episode-title[^"]*">\s*<a href="([^"]+)"[^>]*>(.*?)</a>(?:\s*<br>\s*<span class="di-ib">(.*?)</span>)?', re.S)
_AIRED = re.compile(r'class="episode-aired[^"]*">(.*?)</td>', re.S)
_POLL = re.compile(r'class="episode-poll[^"]*"[^>]*data-raw="([\d.]+)"')
_FORUM = re.compile(r'class="episode-forum[^"]*" data-raw="(\d+)"')


def _flip(name: str) -> str:
    """MAL 角色名是 'Tenma, Kenzou' 式，翻成 'Kenzou Tenma'。"""
    if "," in name:
        last, first = [x.strip() for x in name.split(",", 1)]
        return f"{first} {last}".strip()
    return name


def _date(s: str):
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    for fmt in ("%b %d, %Y", "%b %Y", "%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _clean(s: str | None) -> str | None:
    if not s:
        return None
    return html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ").strip() or None


def fetch_episodes_html(mal_id: int | str, http) -> dict[int, dict]:
    episodes: dict[int, dict] = {}
    offset = 0
    while True:
        page = http.get_text(f"{MAL}/anime/{mal_id}/_/episode", params={"offset": offset}, headers=HTML_HEADERS)  # 没有 slug 段会被重定向到作品页；"_" 占位可用
        rows = _ROW.findall(page)
        if not rows:
            break
        for row in rows:
            m = _NUM.search(row)
            if not m:
                continue
            n = int(m.group(1))
            t = _TITLE.search(row)
            title_en, sub = (_clean(t.group(2)), _clean(t.group(3))) if t else (None, None)
            romaji, native = None, None
            if sub:
                mm = re.match(r"(.*?)\s*\((.*)\)\s*$", sub)
                romaji, native = (mm.group(1).strip() or None, mm.group(2).strip() or None) if mm else (sub, None)
            a = _AIRED.search(row)
            p = _POLL.search(row)
            f = _FORUM.search(row)
            episodes[n] = {
                "title_en": title_en,
                "title_romaji": romaji,
                "title_native": native,
                "aired": _date(a.group(1)) if a else None,
                "score": float(p.group(1)) if p else None,
                "forum_replies": int(f.group(1)) if f else None,
                "url": t.group(1) if t else None,
            }
        if len(rows) < 100:
            break
        offset += 100
    return episodes


def fetch(mal_id: int | str, http) -> dict:
    episodes = fetch_episodes_html(mal_id, http)
    http.log(f"mal: {len(episodes)} episodes (html)")
    series: dict = {"url": f"{MAL}/anime/{mal_id}"}
    try:
        a = http.get_json(f"{JIKAN}/anime/{mal_id}")["data"]
        series.update({
            "title": a.get("title_english") or a.get("title"),
            "title_romaji": a.get("title"),
            "title_native": a.get("title_japanese"),
            "year": a.get("year") or ((a.get("aired") or {}).get("from") or "")[:4] or None,
            "eps": a.get("episodes"),
            "score": a.get("score"),
            "votes": a.get("scored_by"),
            "rank": a.get("rank"),
            "cover": ((a.get("images") or {}).get("jpg") or {}).get("large_image_url"),
            "synopsis_en": (a.get("synopsis") or "").replace("\n\n[Written by MAL Rewrite]", "").strip() or None,
            "genres": [g["name"] for g in (a.get("genres") or [])],
            "studios": [s["name"] for s in (a.get("studios") or [])],
        })
        chars = http.get_json(f"{JIKAN}/anime/{mal_id}/characters").get("data", [])
        main = [c for c in chars if c.get("role") == "Main"]
        supp = sorted((c for c in chars if c.get("role") != "Main"), key=lambda c: -(c.get("favorites") or 0))[:6]
        series["characters"] = [
            {"name": _flip(c["character"]["name"]), "role": c.get("role"),
             "image": ((c["character"].get("images") or {}).get("jpg") or {}).get("image_url"),
             "mal_id": c["character"].get("mal_id"), "favorites": c.get("favorites")}
            for c in main + supp
        ]
    except Exception as e:  # Jikan 挂了不影响分集数据
        http.log(f"mal: jikan unavailable ({str(e)[:80]}) — series info/characters skipped this run")
    if not episodes:
        raise RuntimeError("mal: no episodes parsed from HTML")
    return {"series": series, "episodes": episodes}


def search(query: str, http) -> list[dict]:
    d = http.get_json(f"{JIKAN}/anime", params={"q": query, "limit": 8})
    return [
        {"id": x["mal_id"], "title": x.get("title"), "title_en": x.get("title_english"),
         "year": x.get("year"), "eps": x.get("episodes"), "type": x.get("type")}
        for x in d.get("data", [])
    ]
