#!/usr/bin/env python3
"""media-digest 进度同步 API —— 替代原 GitHub Gist 方案的自建端。

单文件 stdlib 服务，systemd 常驻，Caddy 反代 /api/progress 到这里。

  GET  /api/progress   返回当前全量进度
  POST /api/progress   body 为客户端全量进度；服务端按集合并（同页面 merge：每集取 t 最新的一次操作），
                       落盘后返回合并结果——一次请求同时完成推和拉
  GET  /api/health     探活

数据：MD_DATA（默认 /var/lib/media-digest/progress.json），原子写。
Key ：MD_KEY_FILE（默认 /etc/media-digest-api/key）里的字符串须等于请求头 X-MD-Key。
      它只是反爬虫噪音——页面 JS 里明文下发，不防有心人；数据只有观看进度。
监听：MD_LISTEN（默认 127.0.0.1:3081）。
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = os.environ.get("MD_LISTEN", "127.0.0.1:3081")
DATA = os.environ.get("MD_DATA", "/var/lib/media-digest/progress.json")
KEY_FILE = os.environ.get("MD_KEY_FILE", "/etc/media-digest-api/key")
MAX_BODY = 2 * 1024 * 1024
MAX_SHOWS = 1000
MAX_EPS_PER_SHOW = 10000

_lock = threading.Lock()


def load_key() -> str:
    with open(KEY_FILE, encoding="utf-8") as f:
        return f.read().strip()


def load_progress() -> dict:
    try:
        with open(DATA, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("shows"), dict) else {"version": 1, "shows": {}}
    except (OSError, ValueError):
        return {"version": 1, "shows": {}}


def save_progress(d: dict) -> None:
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DATA)


def sanitize(d: dict) -> dict:
    """只接受 {shows: {slug: {n: {v, t}}}} 结构；超量/畸形直接拒绝，字段类型强制归一。"""
    if not isinstance(d, dict) or not isinstance(d.get("shows"), dict):
        raise ValueError("bad shape")
    shows = {}
    for slug, eps in d["shows"].items():
        if not isinstance(slug, str) or not isinstance(eps, dict):
            raise ValueError("bad shape")
        if len(shows) >= MAX_SHOWS:
            raise ValueError("too many shows")
        out = {}
        for n, e in eps.items():
            if len(out) >= MAX_EPS_PER_SHOW:
                raise ValueError("too many eps")
            if not (isinstance(e, dict) and isinstance(e.get("v"), (int, float)) and isinstance(e.get("t"), (int, float))):
                raise ValueError("bad entry")
            out[str(int(str(n)))] = {"v": 1 if e["v"] else 0, "t": int(e["t"])}
        if out:
            shows[slug] = out
    return {"version": 1, "shows": shows}


def merge(a: dict, b: dict) -> dict:
    """与 site/sync.js 的 merge 同规则：按集取 t 最新的一次操作。"""
    out = {"version": 1, "shows": {}}
    for slug in set(a["shows"]) | set(b["shows"]):
        sa, sb = a["shows"].get(slug, {}), b["shows"].get(slug, {})
        so = out["shows"][slug] = {}
        for n in set(sa) | set(sb):
            ea, eb = sa.get(n), sb.get(n)
            so[n] = eb if ea is None else ea if eb is None else (eb if eb["t"] > ea["t"] else ea)
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "media-digest-progress"

    def log_message(self, fmt, *args):  # 静默；接入层有日志
        pass

    def _send(self, code: int, obj=None):
        body = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-MD-Key")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _auth_ok(self) -> bool:
        return self.headers.get("X-MD-Key", "") == load_key()

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        if self.path == "/api/health":
            return self._send(200, {"ok": True})
        if self.path != "/api/progress":
            return self._send(404, {"error": "not found"})
        if not self._auth_ok():
            return self._send(403, {"error": "bad key"})
        with _lock:
            self._send(200, load_progress())

    def do_POST(self):
        if self.path != "/api/progress":
            return self._send(404, {"error": "not found"})
        if not self._auth_ok():
            return self._send(403, {"error": "bad key"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self._send(413, {"error": "bad length"})
        try:
            incoming = sanitize(json.loads(self.rfile.read(n)))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "bad body"})
        with _lock:
            merged = merge(load_progress(), incoming)
            save_progress(merged)
            self._send(200, merged)


if __name__ == "__main__":
    host, port = LISTEN.rsplit(":", 1)
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    ThreadingHTTPServer((host, int(port)), Handler).serve_forever()
