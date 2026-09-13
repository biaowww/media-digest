#!/usr/bin/env python3
"""
validate.py — 校验 shows/*.json：JSON Schema（shows/_schema.json）+ 逻辑检查。

  py scraper/validate.py                 # 校验 shows/ 下全部
  py scraper/validate.py shows/x.json    # 校验指定文件

退出码非 0 = 有 error。warning 不阻断（比如 route 未覆盖到的集、watch 节点缺 why）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "shows" / "_schema.json"


def check(show: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []

    try:
        import jsonschema
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        for err in sorted(jsonschema.Draft7Validator(schema).iter_errors(show), key=lambda e: list(e.path)):
            path = "/".join(str(p) for p in err.path) or "<root>"
            errors.append(f"schema {path}: {err.message[:160]}")
    except ImportError:
        warnings.append("jsonschema not installed — schema check skipped (py -m pip install jsonschema)")

    meta = show.get("meta", {})
    total = meta.get("total_eps") or 0
    eps = show.get("episodes", [])
    ns = [e.get("n") for e in eps]
    if len(ns) != len(set(ns)):
        errors.append("episodes: duplicate n")
    if ns and ns != sorted(ns):
        errors.append("episodes: not sorted by n")
    missing = sorted(set(range(1, total + 1)) - set(ns))
    if missing:
        warnings.append(f"episodes: {len(missing)} of {total} missing (e.g. {missing[:8]})")

    route = show.get("route", [])
    covered: set[int] = set()
    last_end = 0
    for i, node in enumerate(route):
        kind, rng = node.get("kind"), node.get("eps") or [0, 0]
        a, b = rng[0], rng[1]
        tag = f"route[{i}] {kind} EP{a}-{b}"
        if a > b:
            errors.append(f"{tag}: eps start > end")
        if a < 1 or (total and b > total):
            errors.append(f"{tag}: out of range 1..{total}")
        if a <= last_end:
            errors.append(f"{tag}: overlaps previous node (ends at {last_end})")
        elif a > last_end + 1:
            warnings.append(f"{tag}: gap — EP{last_end + 1}-{a - 1} covered by nothing")
        last_end = max(last_end, b)
        covered.update(range(a, b + 1))
        if kind == "watch" and not (node.get("why") or "").strip():
            warnings.append(f"{tag}: missing why")
        if kind == "bridge" and not [p for p in node.get("paragraphs", []) if p.strip()]:
            errors.append(f"{tag}: bridge has no paragraphs")
    if route and total and last_end < total:
        warnings.append(f"route: ends at EP{last_end}, EP{last_end + 1}-{total} uncovered")
    return errors, warnings


def summary(show: dict) -> str:
    meta, route = show["meta"], show.get("route", [])
    watch = [n for x in route if x["kind"] == "watch" for n in range(x["eps"][0], x["eps"][1] + 1)]
    bridges = [x for x in route if x["kind"] == "bridge"]
    srcs = sorted({s for e in show.get("episodes", []) for s in (e.get("sources") or {})})
    return (f"{meta['slug']}: {len(show.get('episodes', []))}/{meta.get('total_eps')} eps, sources={srcs}, "
            f"route: {len(watch)} watch eps in {sum(1 for x in route if x['kind']=='watch')} blocks + {len(bridges)} bridges")


def main():
    files = [Path(a) for a in sys.argv[1:]] or [p for p in sorted((ROOT / "shows").glob("*.json"))
                                                 if not p.name.startswith("_") and p.name != "index.json"]
    bad = 0
    for p in files:
        show = json.loads(p.read_text(encoding="utf-8"))
        errors, warnings = check(show)
        print(("FAIL " if errors else "ok   ") + summary(show))
        for w in warnings:
            print("     warn:", w)
        for e in errors:
            print("     ERROR:", e)
        bad += bool(errors)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
