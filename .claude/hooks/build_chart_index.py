#!/usr/bin/env python3
"""build_chart_index.py — viewer 用 chart layer index JSON を生成

入力:
  D:/jma_archive/forecast/<area_slug>/YYYY/MM/DD/{wchart,mwarn}_<file_utc>_a<XX>.png
  D:/jma_archive/weather_chart_xml/{VZSA50,VPZU52}/YYYY/MM/DD/<file_utc>.xml
出力:
  D:/jma_archive/forecast/chart_index.json (canonical)
  D:/jma_archive/forecast/chart_index.js   (file:// viewer 用、window.CHART_INDEX = {...})

構造:
  {
    "wchart": {"japan": [{"valid_utc": "...", "file_utc": "...", "rel": "..."}, ...]},
    "mwarn":  {"japan": [...]}
  }

viewer_layers.html はこの index を読み、表示時刻 T_radar に対して
**「valid_utc ≤ T_radar」** を満たす最新 entry を選ぶ（report 時刻じゃなく
**観測基準時刻（valid_at）** で切替、papa 4/30 訂正）。
file_utc は archive path 解決用の補助情報として保持。

使い方:
    python build_chart_index.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent))
from parse_weather_chart_xml import parse_chart
from parse_marine_warning_xml import parse_marine_warning

ARCH_ROOT = Path("D:/jma_archive/forecast")
XML_ROOT = Path("D:/jma_archive/weather_chart_xml")
INDEX_JSON_PATH = ARCH_ROOT / "chart_index.json"
INDEX_JS_PATH = ARCH_ROOT / "chart_index.js"


def iso_to_utc(iso_str: str | None) -> str | None:
    """ISO 8601 文字列 → YYYYMMDDhhmm00 (UTC)"""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M00")
    except (ValueError, AttributeError):
        return None


def report_iso_to_file_utc(iso_str: str) -> str | None:
    """report_at ISO → PNG file_utc 形式（YYYYMMDDhhmm00）"""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M00")
    except (ValueError, AttributeError):
        return None


def build_xml_lookup(xml_type: str, parser, valid_field: str) -> dict[str, str]:
    """XML 全 parse で {png_file_utc: valid_utc} 辞書を作る。
    XML の URL timestamp と report_at に秒レベル差異があるので、parse で正確な PNG file_utc を導出。
    """
    base = XML_ROOT / xml_type
    lookup: dict[str, str] = {}
    if not base.exists():
        return lookup
    for x in base.rglob("*.xml"):
        try:
            parsed = parser(x)
            png_file_utc = report_iso_to_file_utc(parsed.get("report_at"))
            valid_iso = parsed.get(valid_field) or parsed.get("target_at")
            valid_utc = iso_to_utc(valid_iso)
            if png_file_utc and valid_utc:
                lookup[png_file_utc] = valid_utc
        except Exception:
            continue
    return lookup


def scan_wchart() -> list[dict]:
    """wchart_*.png を集めて XML lookup から valid_utc 解決"""
    pat = re.compile(r"^wchart_(\d{14})_a00\.png$")
    base = ARCH_ROOT / "japan"
    entries = []
    if not base.exists():
        return entries
    lookup = build_xml_lookup("VZSA50", parse_chart, "valid_at")
    for path in base.rglob("wchart_*_a00.png"):
        m = pat.match(path.name)
        if not m:
            continue
        file_utc = m.group(1)
        rel = path.relative_to(ARCH_ROOT).as_posix()
        valid_utc = lookup.get(file_utc, file_utc)  # XML 解決失敗なら file_utc 自身を fallback
        entries.append({
            "valid_utc": valid_utc,
            "file_utc": file_utc,
            "rel": rel,
        })
    entries.sort(key=lambda e: e["valid_utc"])
    return entries


def scan_mwarn() -> list[dict]:
    """mwarn_*.png を集めて XML lookup から observation_at 解決"""
    pat = re.compile(r"^mwarn_(\d{14})_a00\.png$")
    base = ARCH_ROOT / "japan"
    entries = []
    if not base.exists():
        return entries
    lookup = build_xml_lookup("VPZU52", parse_marine_warning, "observation_at")
    for path in base.rglob("mwarn_*_a00.png"):
        m = pat.match(path.name)
        if not m:
            continue
        file_utc = m.group(1)
        rel = path.relative_to(ARCH_ROOT).as_posix()
        valid_utc = lookup.get(file_utc, file_utc)
        entries.append({
            "valid_utc": valid_utc,
            "file_utc": file_utc,
            "rel": rel,
        })
    entries.sort(key=lambda e: e["valid_utc"])
    return entries


def main() -> int:
    idx = {
        "wchart": {"japan": scan_wchart()},
        "mwarn":  {"japan": scan_mwarn()},
    }
    ARCH_ROOT.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(idx, ensure_ascii=False, indent=2)
    INDEX_JSON_PATH.write_text(json_text, encoding="utf-8")
    INDEX_JS_PATH.write_text(f"window.CHART_INDEX = {json_text};\n", encoding="utf-8")
    nw = len(idx["wchart"]["japan"])
    nm = len(idx["mwarn"]["japan"])
    print(f"saved {INDEX_JSON_PATH}")
    print(f"saved {INDEX_JS_PATH}")
    print(f"  wchart/japan: {nw} entries (valid_utc 由来)")
    print(f"  mwarn/japan:  {nm} entries")
    # 妥当性確認: いくつかのエントリで valid_utc と file_utc の差を出す
    if idx["wchart"]["japan"]:
        e = idx["wchart"]["japan"][-1]
        print(f"  latest wchart: valid={e['valid_utc']} file={e['file_utc']}")
    if idx["mwarn"]["japan"]:
        e = idx["mwarn"]["japan"][-1]
        print(f"  latest mwarn:  valid={e['valid_utc']} file={e['file_utc']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
