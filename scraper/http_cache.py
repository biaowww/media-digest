"""
http_cache.py — 所有数据源共用的 HTTP 层：本地缓存 + 每主机限速 + 重试退避。

- 缓存目录 scraper/cache/（已 gitignore）。key = sha1(url + params)。
- 本机代理会有 SSL 瞬断（youtube-digest 同款教训），所以连接错误一律退避重试。
- 代理：requests 自动读 HTTPS_PROXY / HTTP_PROXY 环境变量；没有则回退本机 127.0.0.1:10808。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).resolve().parent / "cache"
UA = "media-digest/0.1 (private, non-commercial; github.com/biaowww)"
FALLBACK_PROXY = "http://127.0.0.1:10808"


class Http:
    def __init__(self, use_cache: bool = True, verbose: bool = True):
        self.use_cache = use_cache
        self.verbose = verbose
        self._last: dict[str, float] = {}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        if os.name == "nt" and not (os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")):
            self.session.proxies = {"https": FALLBACK_PROXY, "http": FALLBACK_PROXY}  # 家里 PC 必须走代理；Mac 直连
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- helpers ----------
    def log(self, *a):
        if self.verbose:
            print("  ", *a, flush=True)

    @staticmethod
    def _key(url: str, params: dict | None) -> str:
        raw = url + "?" + json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _throttle(self, url: str, min_interval: float):
        host = url.split("/")[2]
        wait = self._last.get(host, 0) + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.time()

    # ---------- public ----------
    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None,
                 ttl: float = 86400, min_interval: float = 1.0, retries: int = 4):
        return self._get(url, params, headers, ttl, min_interval, retries, as_json=True)

    def get_text(self, url: str, params: dict | None = None, headers: dict | None = None,
                 ttl: float = 86400, min_interval: float = 1.0, retries: int = 4) -> str:
        return self._get(url, params, headers, ttl, min_interval, retries, as_json=False)

    def _get(self, url, params, headers, ttl, min_interval, retries, as_json):
        cf = CACHE_DIR / (self._key(url, params) + (".json" if as_json else ".txt"))
        if self.use_cache and cf.exists() and time.time() - cf.stat().st_mtime < ttl:
            txt = cf.read_text(encoding="utf-8")
            return json.loads(txt) if as_json else txt

        last_err: Exception | None = None
        for attempt in range(retries):
            self._throttle(url, min_interval)
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=60)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}: {r.text[:160]}")
                r.raise_for_status()
                if as_json:
                    data = r.json()
                    # Jikan 把上游错误包成 200/504 JSON，统一当失败处理
                    if isinstance(data, dict) and data.get("status") in (429, 500, 502, 503, 504):
                        raise requests.HTTPError(f"upstream {data.get('status')}: {data.get('message')}")
                    cf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    return data
                cf.write_text(r.text, encoding="utf-8")
                return r.text
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError, ValueError) as e:
                last_err = e
                back = 2 ** attempt * 1.5
                self.log(f"retry {attempt + 1}/{retries} in {back:.0f}s — {type(e).__name__}: {str(e)[:120]}")
                time.sleep(back)
        raise RuntimeError(f"GET failed after {retries} tries: {url} — {last_err}")

    def download(self, url: str, dest: Path, ttl: float = 7 * 86400, retries: int = 4) -> Path:
        """大文件（IMDb 数据集）流式下载到 dest；ttl 内不重下。"""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.use_cache and dest.exists() and time.time() - dest.stat().st_mtime < ttl:
            self.log(f"cached {dest.name} ({dest.stat().st_size // 1024} KB)")
            return dest
        last_err = None
        for attempt in range(retries):
            try:
                self.log(f"downloading {url}")
                tmp = dest.with_suffix(dest.suffix + ".part")
                with self.session.get(url, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                tmp.replace(dest)
                self.log(f"saved {dest.name} ({dest.stat().st_size // 1024} KB)")
                return dest
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                last_err = e
                time.sleep(2 ** attempt * 2)
        raise RuntimeError(f"download failed: {url} — {last_err}")
