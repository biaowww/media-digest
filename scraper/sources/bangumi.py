"""Bangumi (bgm.tv) v0 API，中文源。需要自定义 User-Agent（官方要求）。

已实测：v0 API 的分集对象**没有评分字段**，只有 `comment`（讨论数）。
所以 bangumi 的分集 KPI = 讨论热度；作品级评分 / 投票数在 series 里。
"""
from __future__ import annotations

API = "https://api.bgm.tv/v0"
HEADERS = {"User-Agent": "biaowww/media-digest (private research; https://github.com/biaowww)"}


def fetch(subject_id: int | str, http) -> dict:
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


def search(query: str, http) -> list[dict]:
    import requests
    r = requests.post(f"{API}/search/subjects", params={"limit": 8}, headers=HEADERS, timeout=40,
                      json={"keyword": query, "filter": {"type": [2]}}, proxies=http.session.proxies or None)
    r.raise_for_status()
    return [
        {"id": x["id"], "title": x.get("name"), "title_cn": x.get("name_cn"),
         "year": (x.get("date") or "")[:4], "eps": x.get("eps")}
        for x in r.json().get("data", [])
    ]
