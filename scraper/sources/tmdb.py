"""TMDB 官方 API v3（需免费 key）。key 来源：环境变量 TMDB_API_KEY，或 scraper/tmdb_api_key.txt（已 gitignore）。

亮点：支持 language=zh-CN，能拿到**中文分集标题 + 中文分集梗概**，是非动画剧集最省事的中文源。
集号策略与 imdb 相同：单季用 episode_number，多季顺序编号。
"""
from __future__ import annotations

import os
from pathlib import Path

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w500"
KEY_FILE = Path(__file__).resolve().parent.parent / "tmdb_api_key.txt"


def api_key() -> str | None:
    k = os.environ.get("TMDB_API_KEY")
    if not k and KEY_FILE.exists():
        k = KEY_FILE.read_text(encoding="utf-8").strip()
    return k or None


def _img(path):
    return IMG + path if path else None


def fetch(tv_id: int | str, http) -> dict:
    key = api_key()
    if not key:
        raise RuntimeError("tmdb: no API key (set TMDB_API_KEY or write scraper/tmdb_api_key.txt)")

    def get(path, lang):
        return http.get_json(f"{API}{path}", params={"api_key": key, "language": lang}, min_interval=0.3)

    tv = get(f"/tv/{tv_id}", "en-US")
    tv_zh = get(f"/tv/{tv_id}", "zh-CN")
    series = {
        "title": tv.get("name"),
        "title_cn": tv_zh.get("name") if tv_zh.get("name") != tv.get("name") else None,
        "year": (tv.get("first_air_date") or "")[:4] or None,
        "eps": tv.get("number_of_episodes"),
        "score": tv.get("vote_average"),
        "votes": tv.get("vote_count"),
        "cover": _img(tv.get("poster_path")),
        "backdrop": _img(tv.get("backdrop_path")),
        "synopsis_en": (tv.get("overview") or "").strip() or None,
        "synopsis_zh": (tv_zh.get("overview") or "").strip() or None,
        "genres": [g["name"] for g in tv.get("genres", [])],
        "url": f"https://www.themoviedb.org/tv/{tv_id}",
    }

    seasons = [s["season_number"] for s in tv.get("seasons", []) if s.get("season_number", 0) > 0]
    single = len(seasons) <= 1
    episodes: dict[int, dict] = {}
    i = 0
    for sn in seasons:
        se = get(f"/tv/{tv_id}/season/{sn}", "en-US")
        se_zh = get(f"/tv/{tv_id}/season/{sn}", "zh-CN")
        zh_by_num = {e["episode_number"]: e for e in se_zh.get("episodes", [])}
        for e in se.get("episodes", []):
            i += 1
            n = e["episode_number"] if single else i
            z = zh_by_num.get(e["episode_number"], {})
            episodes[n] = {
                "title_en": e.get("name") or None,
                "title_cn": (z.get("name") if z.get("name") != e.get("name") else None) or None,
                "aired": e.get("air_date") or None,
                "synopsis_en": (e.get("overview") or "").strip() or None,
                "synopsis_zh": (z.get("overview") or "").strip() or None,
                "vote_average": e.get("vote_average"),
                "vote_count": e.get("vote_count"),
                "still": _img(e.get("still_path")),
                "season": sn,
                "episode": e.get("episode_number"),
            }
    http.log(f"tmdb: {len(episodes)} episodes across {len(seasons)} season(s)")
    return {"series": series, "episodes": episodes}


def search(query: str, http) -> list[dict]:
    key = api_key()
    if not key:
        return []
    d = http.get_json(f"{API}/search/tv", params={"api_key": key, "query": query}, min_interval=0.3)
    return [{"id": x["id"], "title": x.get("name"), "year": (x.get("first_air_date") or "")[:4]}
            for x in d.get("results", [])[:8]]
