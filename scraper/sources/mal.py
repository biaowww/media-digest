"""MyAnimeList via Jikan v4（无需 key）。限速：Jikan 官方 3 req/s、60 req/min，这里保守 1 req/s。

注意：Jikan 偶尔整体返回 504 "failed to connect to MyAnimeList"（MAL 侧拒连），
属上游故障，重试无效时只能稍后再跑；fetch.py 会保留上次抓到的 mal 数据。
"""
from __future__ import annotations

JIKAN = "https://api.jikan.moe/v4"


def _flip(name: str) -> str:
    """MAL 角色名是 'Tenma, Kenzou' 式，翻成 'Kenzou Tenma'。"""
    if "," in name:
        last, first = [x.strip() for x in name.split(",", 1)]
        return f"{first} {last}".strip()
    return name


def fetch(mal_id: int | str, http) -> dict:
    a = http.get_json(f"{JIKAN}/anime/{mal_id}")["data"]
    series = {
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
        "url": a.get("url"),
    }

    episodes: dict[int, dict] = {}
    page = 1
    while True:
        d = http.get_json(f"{JIKAN}/anime/{mal_id}/episodes", params={"page": page})
        for e in d.get("data", []):
            n = int(e["mal_id"])
            episodes[n] = {
                "title_en": e.get("title"),
                "title_native": e.get("title_japanese"),
                "title_romaji": e.get("title_romanji"),
                "aired": (e.get("aired") or "")[:10] or None,
                "score": e.get("score"),
                "votes": None,  # Jikan 不给分集投票数
                "filler": bool(e.get("filler")),
                "recap": bool(e.get("recap")),
                "forum_url": e.get("forum_url"),
            }
        if not (d.get("pagination") or {}).get("has_next_page"):
            break
        page += 1
    http.log(f"mal: {len(episodes)} episodes")

    chars = http.get_json(f"{JIKAN}/anime/{mal_id}/characters").get("data", [])
    main = [c for c in chars if c.get("role") == "Main"]
    supp = sorted((c for c in chars if c.get("role") != "Main"), key=lambda c: -(c.get("favorites") or 0))[:6]
    series["characters"] = [
        {
            "name": _flip(c["character"]["name"]),
            "role": c.get("role"),
            "image": ((c["character"].get("images") or {}).get("jpg") or {}).get("image_url"),
            "mal_id": c["character"].get("mal_id"),
            "favorites": c.get("favorites"),
        }
        for c in main + supp
    ]
    return {"series": series, "episodes": episodes}


def search(query: str, http) -> list[dict]:
    d = http.get_json(f"{JIKAN}/anime", params={"q": query, "limit": 8})
    return [
        {"id": x["mal_id"], "title": x.get("title"), "title_en": x.get("title_english"),
         "year": x.get("year"), "eps": x.get("episodes"), "type": x.get("type")}
        for x in d.get("data", [])
    ]
