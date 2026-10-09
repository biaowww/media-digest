"""paths.py — 定位 Drive 上的 PM 根目录与本项目的内容目录（Cowork 会话写路线/介绍的地方）。

内容目录：<Drive根>/domains/personal/media-digest/shows/<slug>/{intro.json, route.json, 图片}
Drive 里的根目录 2026-10 起叫 biaoOS（旧名 claude，未改名的机器兜底两个都试）。
换挂载点时设环境变量 BIAOOS_DRIVE_ROOT（旧名 CLAUDE_DRIVE_ROOT 仍认），或在 BASES 加一条。
"""
from __future__ import annotations

import os
from pathlib import Path

_HOME = Path(os.path.expanduser("~"))
BASES = [
    _HOME / "我的云端硬盘",                 # 2026-07 起流式挂载（家里 PC）
    Path(r"G:\我的云端硬盘"),
    _HOME / "My Drive",
    _HOME / "Google Drive",
    # macOS Google Drive for desktop：~/Library/CloudStorage/GoogleDrive-<账号>/{My Drive|我的云端硬盘}
    *[p / sub for p in sorted((_HOME / "Library" / "CloudStorage").glob("GoogleDrive-*")) for sub in ("My Drive", "我的云端硬盘")],
]
ROOT_NAMES = ("biaoOS", "claude")          # 新名优先，旧名兜底
CANDIDATES = [b / r for b in BASES for r in ROOT_NAMES]
CONTENT_REL = Path("domains") / "personal" / "media-digest" / "shows"


def drive_root() -> Path:
    env = os.environ.get("BIAOOS_DRIVE_ROOT") or os.environ.get("CLAUDE_DRIVE_ROOT")
    cands = ([Path(env)] if env else []) + CANDIDATES
    for c in cands:
        try:
            if (c / "domains" / "personal").is_dir():
                return c
        except OSError:
            continue
    raise SystemExit("找不到 Drive 的 PM 根（biaoOS / claude）；设 BIAOOS_DRIVE_ROOT 或改 scraper/paths.py BASES。已试：\n  "
                     + "\n  ".join(str(c) for c in cands))


def content_dir() -> Path:
    return drive_root() / CONTENT_REL


if __name__ == "__main__":
    print("drive_root =", drive_root())
    print("content_dir =", content_dir())
