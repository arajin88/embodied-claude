#!/usr/bin/env python3
"""fetch_weather_chart_xml.py — 気象庁 防災情報 atom feed から
天気図 (VZSA50) + 海上警報 (VPZU52) XML を自動取得 + render + index 更新

仕組み:
  1. atom feed 2 種類を fetch:
     - regular_l.xml: 天気図系 (VZSA50 = 地上実況図 ASAS)
     - other_l.xml:   海上警報 (VPZU52 = 全般海上警報)
  2. 取得済 XML は skip、新規のみ download
  3. 新規 XML に対し対応する renderer を呼び透明 PNG overlay 生成
  4. build_chart_index.py で chart_index.{json,js} 更新

保存先:
  XML: D:/jma_archive/weather_chart_xml/<TYPE>/YYYY/MM/DD/<file_utc>.xml
       (file_utc = atom id URL の 14-digit 報告時刻、UTC)
  PNG: 各 renderer の規定パス（D:/jma_archive/forecast/japan/YYYY/MM/DD/...）

使い方:
    python fetch_weather_chart_xml.py
    python fetch_weather_chart_xml.py --types VZSA50  # 一部の型だけ
    python fetch_weather_chart_xml.py --no-render      # XML pull のみ、render skip
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ATOM_FEEDS = [
    ("regular_l", "https://www.data.jma.go.jp/developer/xml/feed/regular_l.xml"),
    ("other_l",   "https://www.data.jma.go.jp/developer/xml/feed/other_l.xml"),
]

# 取得対象の type code → 用途タグ
INTERESTING = {
    "VZSA50": "weather_chart",    # 地上実況図 ASAS
    "VPZU52": "marine_warning",   # 全般海上警報
    # 将来候補: VZSF50 (FSAS24), VZSF51 (FSAS48), VPCU51 (地方海上警報)
}

XML_ARCHIVE_ROOT = Path("D:/jma_archive/weather_chart_xml")
HOOKS_DIR = Path(__file__).parent
PYEXE = sys.executable
USER_AGENT = "Mozilla/5.0 (dal-embodied-claude)"

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_atom(feed_xml: bytes, allowed_types: set[str]) -> list[tuple[str, str, str, str]]:
    """atom feed → [(url, type_code, file_utc, title), ...]"""
    root = ET.fromstring(feed_xml)
    entries = []
    pat = re.compile(r"/(\d{14})_\d+_([A-Z]{3,6}\d{0,3})_\d+\.xml$")
    for entry in root.findall("a:entry", ATOM_NS):
        id_elem = entry.find("a:id", ATOM_NS)
        if id_elem is None or not id_elem.text:
            continue
        url = id_elem.text.strip()
        m = pat.search(url)
        if not m:
            continue
        file_utc = m.group(1)
        type_code = m.group(2)
        if type_code not in allowed_types:
            continue
        title_elem = entry.find("a:title", ATOM_NS)
        title = (title_elem.text or "").strip() if title_elem is not None else ""
        entries.append((url, type_code, file_utc, title))
    return entries


def xml_archive_path(type_code: str, file_utc: str) -> Path:
    """XML 保存先パス (JST 基準の年月日)"""
    dt = datetime.strptime(file_utc, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    jst = dt + timedelta(hours=9)
    return (XML_ARCHIVE_ROOT / type_code
            / jst.strftime("%Y") / jst.strftime("%m") / jst.strftime("%d")
            / f"{file_utc}.xml")


def fetch_and_save(url: str, type_code: str, file_utc: str) -> Path | None:
    out_path = xml_archive_path(type_code, file_utc)
    if out_path.exists():
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = http_get(url)
    except Exception as e:
        print(f"  fail {type_code} {file_utc}: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    out_path.write_bytes(data)
    print(f"  saved {type_code} {file_utc}: {len(data)} bytes")
    return out_path


def render_for(type_code: str, xml_path: Path) -> bool:
    """type に応じた renderer を呼ぶ。成功なら True"""
    if type_code == "VZSA50":
        cmd = [PYEXE, str(HOOKS_DIR / "render_weather_chart_overlay.py"),
               str(xml_path), "--area", "00"]
    elif type_code == "VPZU52":
        cmd = [PYEXE, str(HOOKS_DIR / "render_marine_warning_overlay.py"),
               str(xml_path), "--area", "00"]
    else:
        # 未対応 type は skip（XML だけ保存）
        return False
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
        print(f"  rendered {type_code} {xml_path.name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  render failed {xml_path.name}:\n{e.stderr}", file=sys.stderr)
        return False


def update_chart_index() -> None:
    cmd = [PYEXE, str(HOOKS_DIR / "build_chart_index.py")]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
        print(f"  chart_index updated")
    except subprocess.CalledProcessError as e:
        print(f"  index update failed: {e.stderr}", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--types", nargs="+", default=None,
                   help=f"取得対象 type code（default: {' '.join(INTERESTING.keys())}）")
    p.add_argument("--no-render", action="store_true",
                   help="XML pull のみ、render と index 更新を skip")
    args = p.parse_args()

    allowed_types = set(args.types) if args.types else set(INTERESTING.keys())
    saved: list[tuple[str, Path]] = []

    for feed_name, feed_url in ATOM_FEEDS:
        try:
            feed_xml = http_get(feed_url)
        except Exception as e:
            print(f"feed {feed_name} fetch fail: {e}", file=sys.stderr)
            continue
        entries = parse_atom(feed_xml, allowed_types)
        print(f"feed {feed_name}: {len(entries)} interesting entries")
        for url, type_code, file_utc, title in entries:
            path = fetch_and_save(url, type_code, file_utc)
            if path is not None:
                saved.append((type_code, path))

    if not saved:
        print("no new XMLs")
        return 0

    if args.no_render:
        print(f"saved {len(saved)} XMLs (render skipped)")
        return 0

    print(f"rendering {len(saved)} new XMLs...")
    for type_code, xml_path in saved:
        render_for(type_code, xml_path)

    update_chart_index()
    print(f"done. {len(saved)} new XMLs processed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
