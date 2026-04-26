#!/usr/bin/env python3
"""map_set_grid_points.py — Dal が画像を見て読み取った grid points を保存。

使い方:
    python map_set_grid_points.py <map_id> --points '[[x,y,lat,lon],...]'
    python map_set_grid_points.py <map_id> --append --points '[[x,y,lat,lon],...]'

例:
    # 4 点（2 経線 × 2 緯線の交点）で affine fit 可能
    python map_set_grid_points.py spas_jma --points \
        '[[100,200,40.0,130.0],[300,200,40.0,140.0],[100,400,30.0,130.0],[300,400,30.0,140.0]]'

    # 既存に追加
    python map_set_grid_points.py spas_jma --append --points '[[400,500,25.0,150.0]]'

処理:
    D:/dal_geodata/maps/<map_id>/grid_points.json に保存。
    各点: [pixel_x, pixel_y, latitude, longitude] の 4 要素 list。
    affine fit には最低 3 点必要（6 自由度を 6 制約で）、4+ 点推奨で過剰決定 least squares。
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
    p = argparse.ArgumentParser(description="grid points の保存")
    p.add_argument("map_id")
    p.add_argument("--points", required=True, help="JSON: [[x,y,lat,lon],...]")
    p.add_argument("--append", action="store_true", help="既存 list に追加")
    args = p.parse_args()

    map_dir = MAPS_DIR / args.map_id
    if not map_dir.exists():
        print(f"unknown map_id: {args.map_id}", file=sys.stderr)
        print(f"先に map_register.py で登録してください", file=sys.stderr)
        return 1

    try:
        new_pts = json.loads(args.points)
    except json.JSONDecodeError as e:
        print(f"--points の JSON parse エラー: {e}", file=sys.stderr)
        return 2

    if not isinstance(new_pts, list):
        print("--points は list of [x,y,lat,lon]", file=sys.stderr)
        return 2

    for i, pt in enumerate(new_pts):
        if not (isinstance(pt, list) and len(pt) == 4 and all(isinstance(v, (int, float)) for v in pt)):
            print(f"point {i} 不正: {pt}, 期待: [x, y, lat, lon] 数値4要素", file=sys.stderr)
            return 2

    gp_path = map_dir / "grid_points.json"
    if args.append:
        existing = json.loads(gp_path.read_text(encoding="utf-8"))
        merged = existing + new_pts
    else:
        merged = new_pts

    gp_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(merged)} grid points → {gp_path}")
    if len(merged) < 3:
        print(f"warning: affine fit には最低 3 点必要、現在 {len(merged)} 点", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
