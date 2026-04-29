#!/usr/bin/env python3
"""build_chart_index.py — viewer 用 chart layer index JSON を生成

入力: D:/jma_archive/forecast/<area_slug>/YYYY/MM/DD/{wchart,mwarn}_<file_utc>_a<XX>.png
出力:
  D:/jma_archive/forecast/chart_index.json (canonical)
  D:/jma_archive/forecast/chart_index.js   (file:// viewer 用、window.CHART_INDEX = {...})

構造:
  {
    "wchart": {"japan": [{"file_utc": "20260428200900", "rel": "japan/2026/04/29/wchart_..._a00.png"}, ...]},
    "mwarn":  {"japan": [...]}
  }

viewer_layers.html はこの index を fetch し、表示時刻 T_radar に対して
「file_utc ≤ T_radar」を満たす最新 entry を選んで img.src に設定。

使い方:
    python build_chart_index.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ARCH_ROOT = Path("D:/jma_archive/forecast")
INDEX_JSON_PATH = ARCH_ROOT / "chart_index.json"
INDEX_JS_PATH = ARCH_ROOT / "chart_index.js"


def scan(prefix: str, area_slug: str = "japan", area_code: str = "00") -> list[dict]:
    """forecast/<slug>/**/<prefix>_<utc>_a<code>.png を集める"""
    pat = re.compile(rf"^{re.escape(prefix)}_(\d{{14}})_a{re.escape(area_code)}\.png$")
    base = ARCH_ROOT / area_slug
    entries = []
    if not base.exists():
        return entries
    for path in base.rglob(f"{prefix}_*_a{area_code}.png"):
        m = pat.match(path.name)
        if not m:
            continue
        file_utc = m.group(1)
        rel = path.relative_to(ARCH_ROOT).as_posix()
        entries.append({"file_utc": file_utc, "rel": rel})
    entries.sort(key=lambda e: e["file_utc"])
    return entries


def main() -> int:
    idx = {
        "wchart": {"japan": scan("wchart", "japan", "00")},
        "mwarn":  {"japan": scan("mwarn",  "japan", "00")},
    }
    ARCH_ROOT.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(idx, ensure_ascii=False, indent=2)
    INDEX_JSON_PATH.write_text(json_text, encoding="utf-8")
    INDEX_JS_PATH.write_text(f"window.CHART_INDEX = {json_text};\n", encoding="utf-8")
    nw = len(idx["wchart"]["japan"])
    nm = len(idx["mwarn"]["japan"])
    print(f"saved {INDEX_JSON_PATH}")
    print(f"saved {INDEX_JS_PATH}")
    print(f"  wchart/japan: {nw} entries")
    print(f"  mwarn/japan:  {nm} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
