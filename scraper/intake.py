"""intake.py — 把服务器 intake 队列里的新条目写进 Drive shows/<slug>/route.json。

LibreChat 智能体（或任何人拿 intake key）POST /api/intake 进队列；构建机每次 build 前拉一次：
  队列条目 → Drive route.json（已存在则跳过不覆盖，直接出队）→ ack 出队 → 走正常 fetch/sync 回路。
Drive 仍是唯一真相源，服务器队列只是「投递信箱」。
"""
from __future__ import annotations

import json
import os
import urllib.request

from paths import content_dir  # noqa: E402  (build.py 已把 scraper 加进 sys.path；单跑时 python3 scraper/intake.py 也能 import)

API = "https://media-digest.biaotools.site/api/intake"


def _req(path: str, key: str, body: dict | None = None) -> dict:
    r = urllib.request.Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"X-Intake-Key": key, "Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.load(resp)


def pull(log=print) -> None:
    key = os.environ.get("MD_INTAKE_KEY")
    if not key:
        return  # 未配 key 直接跳过（其他构建机不强制接入）
    try:
        items = _req("/pending", key).get("items") or {}
    except Exception as e:
        log(f"intake: 队列拉取失败（不阻断构建）: {e}")
        return
    for slug, item in items.items():
        try:
            d = content_dir() / slug
            route_path = d / "route.json"
            if route_path.exists() or (d / "intro.json").exists():
                # 已有骨架：并入缺失的 intro/route（两步投递：先 meta 后内容），绝不覆盖已有内容
                added = []
                try:
                    cur = json.loads(route_path.read_text(encoding="utf-8")) if route_path.exists() else None
                except ValueError:
                    cur = None
                if isinstance(cur, dict):
                    for k in ("intro", "route"):
                        if k not in cur and isinstance(item.get(k), (dict, list)):
                            cur[k] = item[k]
                            added.append(k)
                    if added:
                        route_path.write_text(json.dumps(cur, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                _req("/ack", key, {"slug": slug})
                log(f"intake: {slug} 已存在，并入 {('/'.join(added)) or '无新内容'}，出队")
                continue
            out = {"meta": item["meta"]}
            if isinstance(item.get("intro"), dict):
                out["intro"] = item["intro"]
            if isinstance(item.get("route"), list):
                out["route"] = item["route"]
            d.mkdir(parents=True, exist_ok=True)
            (d / "route.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            _req("/ack", key, {"slug": slug})
            log(f"intake: {slug} 已写入 Drive route.json")
        except Exception as e:
            log(f"intake: {slug} 失败 {e}")


if __name__ == "__main__":
    pull()
