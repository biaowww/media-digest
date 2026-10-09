"""Bangumi (bgm.tv) v0 API，中文源。需要自定义 User-Agent（官方要求）。

已实测：v0 API 的分集对象**没有评分字段**，只有 `comment`（讨论数）。
所以 bangumi 的分集 KPI = 讨论热度；作品级评分 / 投票数在 series 里。

漫画（kind="manga"）：书籍条目没有分集列表，但系列条目的关联里有各卷**单行本**条目
（如 ベルセルク (1)…），每个单行本有自己的评分/票数——漫画的「分卷评分」由此来。
"""
from __future__ import annotations

import re

API = "https://api.bgm.tv/v0"
HEADERS = {"User-Agent": "biaowww/media-digest (private research; https://github.com/biaowww)"}

_VOL_NUM = re.compile(r"\((\d+)\)\s*$")


def fetch_volumes(subject_id: int | str, http) -> dict[int, dict]:
    """系列条目的关联单行本 → {卷号: {score, votes, ...}}。每卷一次 API 调用（有缓存）。"""
    rel = http.get_json(f"{API}/subjects/{subject_id}/subjects", headers=HEADERS)
    volumes: dict[int, dict] = {}
    for r in rel:
        m = _VOL_NUM.search(r.get("name") or "")
        if r.get("relation") != "单行本" or not m:
            continue
        v = http.get_json(f"{API}/subjects/{r['id']}", headers=HEADERS)
        rating = v.get("rating") or {}
        n = int(m.group(1))
        volumes[n] = {
            "title_native": v.get("name") or None,
            "title_cn": v.get("name_cn") or None,
            "aired": v.get("date") or None,
            "score": rating.get("score"),
            "votes": rating.get("total"),
            "url": f"https://bgm.tv/subject/{v.get('id')}",
        }
    http.log(f"bangumi: {len(volumes)} volume subjects (单行本)")
    return volumes


def fetch(subject_id: int | str, http, kind: str = "anime") -> dict:
    s = http.get_json(f"{API}/subjects/{subject_id}", headers=HEADERS)
    rating = s.get("rating") or {}
    series = {
        "title_native": s.get("name"),
        "title_cn": s.get("name_cn") or None,
        "year": (s.get("date") or "")[:4] or None,
        "eps": s.get("eps") or s.get("total_episodes"),
        "score": rating.get("score"),
        "votes": rating.get("total"),
        "rank": rating.get("rank"),
        "cover": (s.get("images") or {}).get("large"),
        "synopsis_zh": (s.get("summary") or "").strip() or None,
        "url": f"https://bgm.tv/subject/{subject_id}",
    }

    if kind == "manga":
        episodes = fetch_volumes(subject_id, http)
    else:
        episodes: dict[int, dict] = {}
        offset = 0
        while True:
            d = http.get_json(f"{API}/episodes", headers=HEADERS,
                              params={"subject_id": subject_id, "type": 0, "limit": 100, "offset": offset})
            data = d.get("data", [])
            for e in data:
                n = int(e.get("ep") or e.get("sort"))
                episodes[n] = {
                    "title_native": e.get("name") or None,
                    "title_cn": e.get("name_cn") or None,
                    "aired": e.get("airdate") or None,
                    "synopsis_zh": (e.get("desc") or "").strip() or None,
                    "score": None,
                    "votes": None,
                    "comments": e.get("comment"),
                    "url": f"https://bgm.tv/ep/{e.get('id')}",
                }
            offset += len(data)
            if not data or offset >= (d.get("total") or 0):
                break
        http.log(f"bangumi: {len(episodes)} episodes")

    chars = http.get_json(f"{API}/subjects/{subject_id}/characters", headers=HEADERS)
    series["characters"] = [
        {"name_native": c.get("name"), "relation": c.get("relation"),
         "image": (c.get("images") or {}).get("grid"), "bangumi_id": c.get("id")}
        for c in chars if c.get("relation") == "主角"
    ]
    return {"series": series, "episodes": episodes}


def search(query: str, http, types=(2,)) -> list[dict]:
    import requests
    r = requests.post(f"{API}/search/subjects", params={"limit": 8}, headers=HEADERS, timeout=40,
                      json={"keyword": query, "filter": {"type": list(types)}}, proxies=http.session.proxies or None)
    r.raise_for_status()
    return [
        {"id": x["id"], "title": x.get("name"), "title_cn": x.get("name_cn"),
         "year": (x.get("date") or "")[:4], "eps": x.get("eps"), "type": x.get("type")}
        for x in r.json().get("data", [])
    ]
