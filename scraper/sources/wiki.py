"""英文维基百科分集列表 → 分集英文标题 / 首播日期 / ShortSummary（写桥接摘要的主要原料）。

走 MediaWiki API 取 wikitext，解析 {{Episode list}} / {{Japanese episode list}} 模板。
括号深度感知，能正确处理摘要里嵌套的 {{nihongo}} / [[链接|文字]] / <ref>。
"""
from __future__ import annotations

import html
import re

API = "https://en.wikipedia.org/w/api.php"
TEMPLATE_RE = re.compile(r"\{\{\s*(?:Japanese |Multi-?)?[Ee]pisode list(?:/sublist\|[^|}]*)?\s*(?=\|)")


def _split_top_level(s: str, sep: str = "|") -> list[str]:
    """按顶层分隔符切分，忽略 {{ }} / [[ ]] 内部的分隔符。"""
    parts, depth_t, depth_l, buf = [], 0, 0, []
    i = 0
    while i < len(s):
        two = s[i:i + 2]
        if two == "{{":
            depth_t += 1; buf.append(two); i += 2; continue
        if two == "}}":
            depth_t -= 1; buf.append(two); i += 2; continue
        if two == "[[":
            depth_l += 1; buf.append(two); i += 2; continue
        if two == "]]":
            depth_l -= 1; buf.append(two); i += 2; continue
        c = s[i]
        if c == sep and depth_t == 0 and depth_l == 0:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def _find_templates(text: str) -> list[str]:
    """返回每个 episode list 模板的内部文本（不含最外层 {{ }}）。"""
    out = []
    for m in TEMPLATE_RE.finditer(text):
        start = m.start()
        depth, i = 0, start
        while i < len(text):
            if text.startswith("{{", i):
                depth += 1; i += 2; continue
            if text.startswith("}}", i):
                depth -= 1; i += 2
                if depth == 0:
                    out.append(text[start + 2:i - 2])
                    break
                continue
            i += 1
    return out


def _clean(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    # 日期模板
    s = re.sub(r"\{\{\s*[Ss]tart date[^}]*?\|(\d{4})\|(\d{1,2})\|(\d{1,2})[^}]*\}\}",
               lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", s)
    # 其余模板：取第一个位置参数（nihongo / lang / transl 等）
    for _ in range(4):
        def repl(m):
            parts = _split_top_level(m.group(1))
            pos = [p for p in parts[1:] if "=" not in p.split("|")[0][:20]] or [""]
            return pos[0]
        new = re.sub(r"\{\{((?:[^{}]|\{\{[^{}]*\}\})*)\}\}", repl, s)
        if new == s:
            break
        s = new
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://[^\s\]]+\s*([^\]]*)\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<br\s*/?>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_wikitext(text: str) -> dict[int, dict]:
    episodes: dict[int, dict] = {}
    seq = 0
    for body in _find_templates(text):
        fields: dict[str, str] = {}
        for part in _split_top_level(body)[1:]:
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            fields[k.strip()] = v.strip()
        seq += 1
        num = _clean(fields.get("EpisodeNumber", "")) or str(seq)
        try:
            n = int(re.match(r"\d+", num).group())
        except Exception:
            n = seq
        title_en = _clean(fields.get("Title") or fields.get("EnglishTitle") or "")
        native = _clean(fields.get("NativeTitle") or fields.get("KanjiTitle") or "")
        romaji = _clean(fields.get("TranslitTitle") or fields.get("RomajiTitle") or "")
        aired = _clean(fields.get("OriginalAirDate") or fields.get("FirstJpnAirDate") or "")
        aired = aired if re.fullmatch(r"\d{4}-\d{2}-\d{2}", aired) else None
        episodes[n] = {
            "title_en": title_en or None,
            "title_native": native or None,
            "title_romaji": romaji or None,
            "aired": aired,
            "synopsis_en": _clean(fields.get("ShortSummary", "")) or None,
        }
    return episodes


def fetch(page: str, http) -> dict:
    d = http.get_json(API, params={"action": "parse", "page": page, "prop": "wikitext",
                                    "format": "json", "formatversion": 2}, min_interval=0.5)
    if "error" in d:
        raise RuntimeError(f"wiki: {d['error'].get('info')}")
    episodes = parse_wikitext(d["parse"]["wikitext"])
    http.log(f"wiki: {len(episodes)} episodes parsed from '{page}'")
    series = {"url": "https://en.wikipedia.org/wiki/" + page.replace(" ", "_")}
    return {"series": series, "episodes": episodes}
