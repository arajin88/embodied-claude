#!/usr/bin/env python3
"""map_set_meridians.py — 地図画像の経線（縦線、直線想定）を端点で保存。

使い方:
    python map_set_meridians.py <map_id> --lines '[{"value":130,"px_start":[x1,y1],"px_end":[x2,y2]},...]'
    python map_set_meridians.py <map_id> --append --lines '[...]'

例:
    python map_set_meridians.py spas_jma --lines \
        '[{"value":130,"px_start":[228,90],"px_end":[218,500]},
          {"value":140,"px_start":[335,90],"px_end":[335,500]}]'

処理:
    D:/dal_geodata/maps/<map_id>/grid_lines.json に保存。
    経線は直線想定（円錐図法でも経線は画像内で直線、僅かに傾く）。
    緯線は曲線なので別ツール（map_set_grid_points.py）で交差点群として保存。

逆引き手順:
    1. このツールで経線を確定
    2. 各経線に沿って画像を trace、緯線との交差点を vision で読む
    3. map_set_grid_points.py で交差点群を保存
    4. map_pixel_to_latlon.py で多点 affine fit
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MAPS_DIR = Path("D:/dal_geodata/maps")


def main() -> int:
    p = argparse.ArgumentParser(description="経線データの保存")
    p.add_argument("map_id")
    p.add_argument("--lines", required=True,
                   help='JSON: [{"value":130,"px_start":[x,y],"px_end":[x,y]},...]')
    p.add_argument("--append", action="store_true")
    args = p.parse_args()

    map_dir = MAPS_DIR / args.map_id
    if not map_dir.exists():
        print(f"unknown map_id: {args.map_id}", file=sys.stderr)
        return 1

    try:
        new_lines = json.loads(args.lines)
    except json.JSONDecodeError as e:
        print(f"--lines の JSON parse エラー: {e}", file=sys.stderr)
        return 2

    if not isinstance(new_lines, list):
        print("--lines は list", file=sys.stderr)
        return 2

    for i, ln in enumerate(new_lines):
        if not (isinstance(ln, dict) and "value" in ln and "px_start" in ln and "px_end" in ln):
            print(f"line {i} 不正: {ln}", file=sys.stderr)
            return 2
        if not (len(ln["px_start"]) == 2 and len(ln["px_end"]) == 2):
            print(f"line {i} px_start/px_end は 2 要素", file=sys.stderr)
            return 2

    gl_path = map_dir / "grid_lines.json"
    if gl_path.exists():
        existing = json.loads(gl_path.read_text(encoding="utf-8"))
    else:
        existing = {"longitudes": [], "latitudes": []}

    if args.append:
        existing["longitudes"].extend(new_lines)
    else:
        existing["longitudes"] = new_lines

    gl_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(existing['longitudes'])} meridians → {gl_path}")
    for ln in existing["longitudes"]:
        print(f"  {ln['value']}°E: {ln['px_start']} → {ln['px_end']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
