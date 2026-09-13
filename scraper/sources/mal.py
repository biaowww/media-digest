"""MyAnimeList：分集 / 作品信息 / 主角头像**全部直抓 HTML**，不依赖 Jikan（Jikan 只用于 `resolve` 搜索）。

为什么不用 Jikan：它是第三方代理，MAL 一拒连它就整体 504（2026-09-13 实测一整天，走不走代理都一样）；
而且 Jikan 的分集只有 1 位小数、没有论坛回复数。三张 HTML 页给全了：
  /anime/<id>/_/episode?offset=N   两位小数投票均分（1–5）、论坛回复数（热度）、英/罗马/日文标题、首播日
  /anime/<id>                      简介（og / itemprop）、封面、总分 + 票数 + 排名、集数、类型、制作公司、别名
  /anime/<id>/_/characters         主角 / 配角、头像、人气
robots.txt 对普通 UA 不禁 /anime/；自用非商用，1 req/s，本地缓存 24h。
URL 里的 "_" 是 slug 占位：没有这一段会被重定向到作品页。

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

_META = re.compile(r'<meta property="og:(\w+)" content="([^"]*)"')
_INFO = re.compile(r'<span class="dark_text">([^<]+):</span>\s*(.*?)\s*</div>', re.S)
_SCORE = re.compile(r'itemprop="ratingValue"[^>]*>([\d.]+)<')
_VOTES = re.compile(r'itemprop="ratingCount"[^>]*>(\d+)<')
_RANK = re.compile(r'Ranked <strong>#([\d,]+)</strong>')
_SYN = re.compile(r'<p itemprop="description">(.*?)</p>', re.S)

_CHAR_ROLE = re.compile(r'js-chara-roll-and-name"[^>]*>\s*([ms])_(.*?)\s*</div>', re.S)
_CHAR_FAV = re.compile(r'js-anime-character-favorites"[^>]*>\s*([\d,]+)\s*</div>')
_CHAR_HREF = re.compile(r'href="https://myanimelist\.net/character/(\d+)/[^"]*"')
_CHAR_IMG = re.compile(r'<img[^>]*data-src="([^"]+)"')


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
    s = html.unescape(re.sub(r"<br\s*/?>", "\n", s))
    s = re.sub(r"<[^>]+>", "", s).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", s).strip() or None


# ---------------- 分集 ----------------
def fetch_episodes_html(mal_id: int | str, http) -> dict[int, dict]:
    episodes: dict[int, dict] = {}
    offset = 0
    while True:
        page = http.get_text(f"{MAL}/anime/{mal_id}/_/episode", params={"offset": offset}, headers=HTML_HEADERS)
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
            a, p, f = _AIRED.search(row), _POLL.search(row), _FORUM.search(row)
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


# ---------------- 作品 ----------------
def fetch_series_html(mal_id: int | str, http) -> dict:
    page = http.get_text(f"{MAL}/anime/{mal_id}", headers=HTML_HEADERS)
    og = dict(_META.findall(page))
    info = {k.strip(): _clean(v) for k, v in _INFO.findall(page)}
    m_score, m_votes, m_rank, m_syn = _SCORE.search(page), _VOTES.search(page), _RANK.search(page), _SYN.search(page)
    synopsis = _clean(m_syn.group(1)) if m_syn else None
    if synopsis:
        synopsis = re.sub(r"\s*\[Written by MAL Rewrite\]\s*$", "", synopsis).strip()
    year = re.search(r"\d{4}", info.get("Aired") or "")
    eps = info.get("Episodes") or ""
    split = lambda s: [x.strip() for x in (s or "").split(",") if x.strip() and x.strip() != "None found"]
    return {
        "title": info.get("English") or og.get("title"),
        "title_romaji": og.get("title"),
        "title_native": info.get("Japanese"),
        "year": year.group() if year else None,
        "eps": int(eps) if eps.isdigit() else None,
        "score": float(m_score.group(1)) if m_score else None,
        "votes": int(m_votes.group(1)) if m_votes else None,
        "rank": int(m_rank.group(1).replace(",", "")) if m_rank else None,
        "cover": og.get("image"),
        "synopsis_en": synopsis,
        "genres": list(dict.fromkeys(re.findall(r'<a href="/anime/genre/\d+/[^"]*" title="([^"]+)"', page))),  # 页面里 hidden span + 链接各一份，取链接 title 去重
        "studios": split(info.get("Studios") or info.get("Studio")),
        "url": f"{MAL}/anime/{mal_id}",
    }


# ---------------- 角色 ----------------
def fetch_characters_html(mal_id: int | str, http) -> list[dict]:
    page = http.get_text(f"{MAL}/anime/{mal_id}/_/characters", headers=HTML_HEADERS)
    out = []
    for block in re.split(r'<table[^>]*class="js-anime-character-table">', page)[1:]:
        r = _CHAR_ROLE.search(block)
        if not r:
            continue
        img, href, fav = _CHAR_IMG.search(block), _CHAR_HREF.search(block), _CHAR_FAV.search(block)
        image = img.group(1) if img else None
        if image:
            image = re.sub(r"/r/\d+x\d+/", "/", image).split("?")[0]  # 去掉缩略尺寸，拿原图
        out.append({
            "name": _flip(_clean(r.group(2)) or ""),
            "role": "Main" if r.group(1) == "m" else "Supporting",
            "image": image,
            "mal_id": int(href.group(1)) if href else None,
            "favorites": int(fav.group(1).replace(",", "")) if fav else 0,
        })
    main = [c for c in out if c["role"] == "Main"]
    supp = sorted((c for c in out if c["role"] != "Main"), key=lambda c: -c["favorites"])[:20]
    return main + supp


def fetch(mal_id: int | str, http) -> dict:
    episodes = fetch_episodes_html(mal_id, http)
    http.log(f"mal: {len(episodes)} episodes (html)")
    if not episodes:
        raise RuntimeError("mal: no episodes parsed from HTML — check the id")
    series = fetch_series_html(mal_id, http)
    try:
        series["characters"] = fetch_characters_html(mal_id, http)
        http.log(f"mal: {sum(1 for c in series['characters'] if c['role'] == 'Main')} main characters (html)")
    except Exception as e:  # 角色页失败不影响其余
        http.log(f"mal: characters page failed ({str(e)[:80]})")
    return {"series": series, "episodes": episodes}


def search(query: str, http) -> list[dict]:
    d = http.get_json(f"{JIKAN}/anime", params={"q": query, "limit": 8})
    return [
        {"id": x["mal_id"], "title": x.get("title"), "title_en": x.get("title_english"),
         "year": x.get("year"), "eps": x.get("episodes"), "type": x.get("type")}
        for x in d.get("data", [])
    ]
