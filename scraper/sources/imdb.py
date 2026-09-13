"""IMDb 官方批量数据集（datasets.imdbws.com），**不爬页面**（robots 禁止）。

用两张表：
- title.episode.tsv.gz  (~55 MB)  tconst / parentTconst / seasonNumber / episodeNumber
- title.ratings.tsv.gz  (~7 MB)   tconst / averageRating / numVotes

集号策略：只有一季 → n = episodeNumber；多季 → 按 (season, episode) 排序后顺序编号，
并在分集里保留 season / episode 原值。缓存 7 天。

授权：数据集仅限个人非商用；商用须另行确认（brief 备注已提）。
"""
from __future__ import annotations

import gzip
from pathlib import Path

DATASETS = "https://datasets.imdbws.com/"
CACHE = Path(__file__).resolve().parent.parent / "cache"


def _int(x: str):
    return None if x == "\\N" else int(x)


def fetch(imdb_id: str, http, season: int | None = None) -> dict:
    ep_file = http.download(DATASETS + "title.episode.tsv.gz", CACHE / "title.episode.tsv.gz")
    rt_file = http.download(DATASETS + "title.ratings.tsv.gz", CACHE / "title.ratings.tsv.gz")

    rows = []
    with gzip.open(ep_file, "rt", encoding="utf-8") as f:
        next(f)
        for line in f:
            tconst, parent, season, ep = line.rstrip("\n").split("\t")
            if parent == imdb_id:
                rows.append((_int(season), _int(ep), tconst))
    if not rows:
        raise RuntimeError(f"imdb: no episodes under {imdb_id} — is it the series id (not an episode / movie)?")

    wanted = {t for _, _, t in rows} | {imdb_id}
    ratings: dict[str, tuple[float, int]] = {}
    with gzip.open(rt_file, "rt", encoding="utf-8") as f:
        next(f)
        for line in f:
            tconst, avg, votes = line.rstrip("\n").split("\t")
            if tconst in wanted:
                ratings[tconst] = (float(avg), int(votes))

    # 无季/集号的条目（特别篇、总集篇）不进正片序列，单独记在 series.extras
    extras = [t for s, e, t in rows if e is None]
    if extras and len(extras) < len(rows):
        rows = [r for r in rows if r[1] is not None]
    if season is not None:  # 只要这一季，集号 = 本季集号（一季一个 slug 的剧）
        rows = [r for r in rows if r[0] == season]
        if not rows:
            raise RuntimeError(f"imdb: no episodes for season {season} under {imdb_id}")
    rows.sort(key=lambda r: (r[0] if r[0] is not None else 10**6, r[1] if r[1] is not None else 10**6))
    seasons = {s for s, _, _ in rows if s is not None}
    single = len(seasons) <= 1

    episodes: dict[int, dict] = {}
    for i, (sn, ep, tconst) in enumerate(rows, 1):
        n = ep if (single and ep is not None) else i
        rating, votes = ratings.get(tconst, (None, None))
        episodes[n] = {"rating": rating, "votes": votes, "tconst": tconst, "season": sn, "episode": ep}
    http.log(f"imdb: {len(episodes)} episodes across {len(seasons) or 1} season(s), {sum(1 for e in episodes.values() if e['rating'])} rated")

    s_rating, s_votes = ratings.get(imdb_id, (None, None))
    series = {"score": s_rating, "votes": s_votes, "url": f"https://www.imdb.com/title/{imdb_id}/",
              "extras": [{"tconst": t, "rating": ratings.get(t, (None, None))[0], "votes": ratings.get(t, (None, None))[1]} for t in extras]}
    return {"series": series, "episodes": episodes}
