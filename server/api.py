#!/usr/bin/env python3
"""media-digest 站点 API —— 账号（邀请制）+ 按用户进度同步 + 智能体 intake 队列。

单文件 stdlib 服务，systemd 常驻，Caddy 反代 /api/* 到这里。

  账号：
    POST /api/auth/register  {username, password, invite}   邀请码无效/已用则拒；注册即登录
    POST /api/auth/login     {username, password}           成功设会话 cookie
    POST /api/auth/logout
    GET  /api/auth/me        → {username, admin} 或 401
  进度（需登录，按用户隔离，合并规则同页面 merge：每集取 t 最新的一次操作）：
    GET  /api/progress       返回本人全量进度
    POST /api/progress       body 为全量进度；服务端合并落库后返回合并结果——一次请求同时完成推和拉
  邀请码（仅 admin）：
    POST /api/admin/invites  → {code}
    GET  /api/admin/invites  → 最近 50 条
  智能体 intake（X-Intake-Key，与登录无关）：
    POST /api/intake         {slug, meta, intro?, route?}   → 写 intake 队列，已存在 409
    GET  /api/intake/pending → 队列全量（构建机拉取）
    POST /api/intake/ack     {slug}                         → 构建机写进 Drive 后删除
  探活：GET /api/health

数据：sqlite3 MD_DB（默认 /var/lib/media-digest/users.db）。
密钥：MD_SECRET_FILE（会话签名 +  intake key 同目录；intake key 在 MD_INTAKE_KEY_FILE）。
监听：MD_LISTEN（默认 127.0.0.1:3081）。
CLI ：--seed-admin 交互创建管理员；--passwd <username> 交互改密；--migrate-progress <file> <username> 导入旧共享进度。
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = os.environ.get("MD_LISTEN", "127.0.0.1:3081")
DB = os.environ.get("MD_DB", "/var/lib/media-digest/users.db")
SECRET_FILE = os.environ.get("MD_SECRET_FILE", "/etc/media-digest-api/session-secret")
INTAKE_KEY_FILE = os.environ.get("MD_INTAKE_KEY_FILE", "/etc/media-digest-api/intake-key")
INTAKE_DIR = os.environ.get("MD_INTAKE_DIR", "/var/lib/media-digest/intake")
COOKIE = "md_sess"
SESSION_TTL = 30 * 86400
MAX_BODY = 2 * 1024 * 1024
MAX_SHOWS = 1000
MAX_EPS_PER_SHOW = 10000
# 浏览器跨站（GitHub Pages → biaotools.site）时的允许来源；无 Origin 的服务端调用不受影响
CORS_ORIGINS = {
    "https://media-digest.biaotools.site",
    "https://anima-digest.biaotools.site",
    "https://biaowww.github.io",
    "http://localhost:8765",
}

_lock = threading.Lock()
_rl: dict[str, list[float]] = {}  # 登录/注册按 IP 限流：10 次 / 5 分钟


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY, pw TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS invites(
        code TEXT PRIMARY KEY, created_by TEXT, created INTEGER NOT NULL, used_by TEXT, used_at INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS progress(
        username TEXT PRIMARY KEY, json TEXT NOT NULL)""")
    return c


def _secret() -> bytes:
    with open(SECRET_FILE, "rb") as f:
        return f.read().strip()


def hash_pw(pw: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 260_000)
    return base64.b64encode(salt).decode() + "$" + h.hex()


def check_pw(pw: str, stored: str) -> bool:
    try:
        salt = base64.b64decode(stored.split("$", 1)[0])
        return hmac.compare_digest(hash_pw(pw, salt), stored)
    except Exception:
        return False


def make_session(username: str) -> str:
    payload = f"{username}.{int(time.time()) + SESSION_TTL}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_session(token: str) -> str | None:
    try:
        username, exp, sig = token.rsplit(".", 2)
        payload = f"{username}.{exp}"
        if not hmac.compare_digest(hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest(), sig):
            return None
        if int(exp) < time.time():
            return None
        return username
    except (ValueError, AttributeError):
        return None


def invite_code() -> str:
    return "MD-" + "-".join(secrets.token_hex(2).upper() for _ in range(2))


# ---------------- 进度（合并规则与 app/sync.js 的 merge 一致） ----------------

def sanitize_progress(d: dict) -> dict:
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


def merge_progress(a: dict, b: dict) -> dict:
    out = {"version": 1, "shows": {}}
    for slug in set(a["shows"]) | set(b["shows"]):
        sa, sb = a["shows"].get(slug, {}), b["shows"].get(slug, {})
        so = out["shows"][slug] = {}
        for n in set(sa) | set(sb):
            ea, eb = sa.get(n), sb.get(n)
            so[n] = eb if ea is None else ea if eb is None else (eb if eb["t"] > ea["t"] else ea)
    return out


# ---------------- intake 校验 ----------------

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")


def sanitize_intake(d: dict) -> dict:
    if not isinstance(d, dict) or not SLUG_RE.match(str(d.get("slug") or "")):
        raise ValueError("bad slug")
    meta = d.get("meta")
    if not isinstance(meta, dict) or not meta.get("title"):
        raise ValueError("bad meta")
    ids = {k: v for k, v in (meta.get("ids") or {}).items() if v not in (None, "")}
    if not ids and not meta.get("total_eps"):
        raise ValueError("need ids or total_eps")
    meta = dict(meta, ids=ids)
    out = {"slug": d["slug"], "meta": meta}
    if isinstance(d.get("intro"), dict):
        out["intro"] = d["intro"]
    if isinstance(d.get("route"), list):
        out["route"] = d["route"]
    if isinstance(d.get("notes"), list):  # 分集手册 → episodes.json
        notes = [x for x in d["notes"] if isinstance(x, dict) and (x.get("n") or x.get("episode"))]
        if notes:
            out["notes"] = notes
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "media-digest-api"

    def log_message(self, fmt, *args):
        pass

    # ---------------- 基础 ----------------
    def _cors(self):
        origin = self.headers.get("Origin")
        if origin in CORS_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def _send(self, code: int, obj=None, set_cookie: str | None = None):
        body = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        if self.command == "OPTIONS":
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Intake-Key")
        if set_cookie is not None:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _body(self) -> dict:
        d = json.loads(self._raw)
        if not isinstance(d, dict):
            raise ValueError("bad body")
        return d

    def _user(self) -> str | None:
        raw = self.headers.get("Cookie") or ""
        c = SimpleCookie(raw)
        m = c.get(COOKIE)
        return read_session(m.value) if m else None

    def _session_cookie(self, username: str) -> str:
        return f"{COOKIE}={make_session(username)}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; Secure; SameSite=None"

    def _clear_cookie(self) -> str:
        return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=None"

    def _rate_limited(self) -> bool:
        ip = self.client_address[0]
        now = time.time()
        with _lock:
            hits = [t for t in _rl.get(ip, []) if now - t < 300]
            _rl[ip] = hits
            if len(hits) >= 10:
                return True
            hits.append(now)
        return False

    def _intake_ok(self) -> bool:
        try:
            with open(INTAKE_KEY_FILE, encoding="utf-8") as f:
                return hmac.compare_digest(self.headers.get("X-Intake-Key", ""), f.read().strip())
        except OSError:
            return False

    # ---------------- 路由 ----------------
    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        if self.path == "/api/health":
            return self._send(200, {"ok": True})
        if self.path == "/api/auth/me":
            return self._me()
        if self.path == "/api/progress":
            return self._progress_get()
        if self.path == "/api/admin/invites":
            return self._invites_list()
        if self.path == "/api/intake/pending":
            return self._intake_pending()
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # 先一次性读掉 body：keep-alive 连接上，早退（403/429/404）不读 body 会污染下一个请求的请求行
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            self.close_connection = True
            return self._send(413, {"error": "body too large"})
        try:
            self._raw = self.rfile.read(n) if n else b"{}"
        except OSError:
            self.close_connection = True
            return
        try:
            if self.path == "/api/auth/register":
                return self._register()
            if self.path == "/api/auth/login":
                return self._login()
            if self.path == "/api/auth/logout":
                return self._send(200, {"ok": True}, set_cookie=self._clear_cookie())
            if self.path == "/api/progress":
                return self._progress_post()
            if self.path == "/api/admin/invites":
                return self._invites_create()
            if self.path == "/api/intake":
                return self._intake_post()
            if self.path == "/api/intake/ack":
                return self._intake_ack()
            self._send(404, {"error": "not found"})
        except (ValueError, UnicodeDecodeError) as e:
            self._send(400, {"error": str(e) or "bad request"})

    # ---------------- 账号 ----------------
    def _me(self):
        u = self._user()
        if not u:
            return self._send(401, {"error": "not logged in"})
        with db() as c:
            row = c.execute("SELECT admin FROM users WHERE username=?", (u,)).fetchone()
        if not row:
            return self._send(401, {"error": "not logged in"}, set_cookie=self._clear_cookie())
        self._send(200, {"username": u, "admin": bool(row[0])})

    def _register(self):
        if self._rate_limited():
            return self._send(429, {"error": "too many attempts"})
        d = self._body()
        username = str(d.get("username") or "").strip()
        password = str(d.get("password") or "")
        code = str(d.get("invite") or "").strip().upper()
        if not re.match(r"^[\w.@+-]{2,64}$", username):
            return self._send(400, {"error": "用户名需 2-64 位字母/数字/下划线/横线，或邮箱"})
        if len(password) < 8:
            return self._send(400, {"error": "密码至少 8 位"})
        with db() as c:
            inv = c.execute("SELECT used_by FROM invites WHERE code=?", (code,)).fetchone()
            if not inv or inv[0]:
                return self._send(403, {"error": "邀请码无效或已被使用"})
            try:
                c.execute("INSERT INTO users(username,pw,admin,created) VALUES(?,?,0,?)",
                          (username, hash_pw(password), int(time.time())))
            except sqlite3.IntegrityError:
                return self._send(409, {"error": "用户名已被占用"})
            c.execute("UPDATE invites SET used_by=?, used_at=? WHERE code=?", (username, int(time.time()), code))
        self._send(200, {"username": username, "admin": False}, set_cookie=self._session_cookie(username))

    def _login(self):
        if self._rate_limited():
            return self._send(429, {"error": "too many attempts"})
        d = self._body()
        username = str(d.get("username") or "").strip()
        password = str(d.get("password") or "")
        with db() as c:
            row = c.execute("SELECT pw, admin FROM users WHERE username=?", (username,)).fetchone()
        if not row or not check_pw(password, row[0]):
            return self._send(403, {"error": "用户名或密码错误"})
        self._send(200, {"username": username, "admin": bool(row[1])}, set_cookie=self._session_cookie(username))

    # ---------------- 进度 ----------------
    def _progress_get(self):
        u = self._user()
        if not u:
            return self._send(401, {"error": "not logged in"})
        with db() as c:
            row = c.execute("SELECT json FROM progress WHERE username=?", (u,)).fetchone()
        try:
            d = json.loads(row[0]) if row else {"version": 1, "shows": {}}
        except ValueError:
            d = {"version": 1, "shows": {}}
        self._send(200, d)

    def _progress_post(self):
        u = self._user()
        if not u:
            return self._send(401, {"error": "not logged in"})
        incoming = sanitize_progress(self._body())
        with _lock, db() as c:
            row = c.execute("SELECT json FROM progress WHERE username=?", (u,)).fetchone()
            try:
                cur = sanitize_progress(json.loads(row[0])) if row else {"version": 1, "shows": {}}
            except ValueError:
                cur = {"version": 1, "shows": {}}
            merged = merge_progress(cur, incoming)
            c.execute("INSERT OR REPLACE INTO progress(username,json) VALUES(?,?)",
                      (u, json.dumps(merged, ensure_ascii=False, separators=(",", ":"))))
        self._send(200, merged)

    # ---------------- 邀请码 ----------------
    def _admin(self) -> str | None:
        u = self._user()
        if not u:
            return None
        with db() as c:
            row = c.execute("SELECT admin FROM users WHERE username=?", (u,)).fetchone()
        return u if row and row[0] else None

    def _invites_create(self):
        u = self._admin()
        if not u:
            return self._send(403, {"error": "admin only"})
        code = invite_code()
        with db() as c:
            c.execute("INSERT INTO invites(code,created_by,created) VALUES(?,?,?)", (code, u, int(time.time())))
        self._send(200, {"code": code})

    def _invites_list(self):
        u = self._admin()
        if not u:
            return self._send(403, {"error": "admin only"})
        with db() as c:
            rows = c.execute("SELECT code, created, used_by, used_at FROM invites ORDER BY created DESC LIMIT 50").fetchall()
        self._send(200, {"invites": [{"code": r[0], "created": r[1], "used_by": r[2], "used_at": r[3]} for r in rows]})

    # ---------------- intake ----------------
    def _intake_post(self):
        if not self._intake_ok():
            return self._send(403, {"error": "bad key"})
        item = sanitize_intake(self._body())
        path = os.path.join(INTAKE_DIR, item["slug"] + ".json")
        with _lock:
            if os.path.exists(path):
                # 同 slug 再投：并入缺失块（智能体一条龙：先 meta 后内容，中间不等人）
                try:
                    with open(path, encoding="utf-8") as f:
                        cur = json.load(f)
                except ValueError:
                    cur = {}
                added = [k for k in ("intro", "route", "notes") if k not in cur and k in item]
                for k in added:
                    cur[k] = item[k]
                if "meta" in item:  # meta 以最新一次为准（ids 可能后补全）
                    cur["meta"] = item["meta"]
                cur["queued_at"] = item.get("queued_at", cur.get("queued_at"))
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(cur, f, ensure_ascii=False, indent=1)
                os.replace(tmp, path)
                return self._send(200, {"ok": True, "slug": item["slug"], "merged": added})
            item["queued_at"] = int(time.time())
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        self._send(200, {"ok": True, "slug": item["slug"]})

    def _intake_pending(self):
        if not self._intake_ok():
            return self._send(403, {"error": "bad key"})
        items = {}
        with _lock:
            for fn in sorted(os.listdir(INTAKE_DIR)):
                if fn.endswith(".json"):
                    try:
                        with open(os.path.join(INTAKE_DIR, fn), encoding="utf-8") as f:
                            items[fn[:-5]] = json.load(f)
                    except (OSError, ValueError):
                        continue
        self._send(200, {"items": items})

    def _intake_ack(self):
        if not self._intake_ok():
            return self._send(403, {"error": "bad key"})
        slug = str(self._body().get("slug") or "")
        if not SLUG_RE.match(slug):
            return self._send(400, {"error": "bad slug"})
        with _lock:
            try:
                os.remove(os.path.join(INTAKE_DIR, slug + ".json"))
            except FileNotFoundError:
                pass
        self._send(200, {"ok": True})


# ---------------- CLI ----------------

def seed_admin():
    username = input("admin username [biaowww]: ").strip() or "biaowww"
    pw = getpass.getpass("password (≥8): ")
    if len(pw) < 8:
        raise SystemExit("密码至少 8 位")
    with db() as c:
        c.execute("INSERT OR REPLACE INTO users(username,pw,admin,created) VALUES(?,?,1,?)",
                  (username, hash_pw(pw), int(time.time())))
    print(f"admin {username} 已创建/更新")


def passwd(username: str):
    pw = getpass.getpass(f"new password for {username} (≥8): ")
    if len(pw) < 8:
        raise SystemExit("密码至少 8 位")
    with db() as c:
        c.execute("UPDATE users SET pw=? WHERE username=?", (hash_pw(pw), username))
    print("已改密")


def migrate_progress(path: str, username: str):
    with open(path, encoding="utf-8") as f:
        d = sanitize_progress(json.load(f))
    with db() as c:
        c.execute("INSERT OR REPLACE INTO progress(username,json) VALUES(?,?)",
                  (username, json.dumps(d, ensure_ascii=False, separators=(",", ":"))))
    print(f"已把 {path} 导入为 {username} 的进度（{sum(len(v) for v in d['shows'].values())} 集）")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    os.makedirs(INTAKE_DIR, exist_ok=True)
    if args[:1] == ["--seed-admin"]:
        seed_admin()
    elif args[:1] == ["--passwd"] and len(args) == 2:
        passwd(args[1])
    elif args[:1] == ["--migrate-progress"] and len(args) == 3:
        migrate_progress(args[1], args[2])
    else:
        host, port = LISTEN.rsplit(":", 1)
        ThreadingHTTPServer((host, int(port)), Handler).serve_forever()
