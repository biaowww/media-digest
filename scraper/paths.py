"""paths.py — 定位 Drive 上的 claude 根与本项目的内容目录（Cowork 会话写路线/介绍的地方）。

内容目录：<claude根>/domains/personal/media-digest/shows/<slug>/{intro.json, route.json, 图片}
换挂载点时设环境变量 CLAUDE_DRIVE_ROOT，或在 CANDIDATES 加一条。
"""
from __future__ import annotations

import os
from pathlib import Path

_HOME = Path(os.path.expanduser("~"))
CANDIDATES = [
    _HOME / "我的云端硬盘" / "claude",      # 2026-07 起流式挂载（家里 PC）
    Path(r"G:\我的云端硬盘\claude"),
    _HOME / "My Drive" / "claude",
    _HOME / "Google Drive" / "claude",
]
CONTENT_REL = Path("domains") / "personal" / "media-digest" / "shows"


def claude_root() -> Path:
    cands = ([Path(os.environ["CLAUDE_DRIVE_ROOT"])] if os.environ.get("CLAUDE_DRIVE_ROOT") else []) + CANDIDATES
    for c in cands:
        try:
            if (c / "domains" / "personal").is_dir():
                return c
        except OSError:
            continue
    raise SystemExit("找不到 Drive 的 claude 根；设 CLAUDE_DRIVE_ROOT 或改 scraper/paths.py CANDIDATES。已试：\n  "
                     + "\n  ".join(str(c) for c in cands))


def content_dir() -> Path:
    return claude_root() / CONTENT_REL


if __name__ == "__main__":
    print("claude_root =", claude_root())
    print("content_dir =", content_dir())
