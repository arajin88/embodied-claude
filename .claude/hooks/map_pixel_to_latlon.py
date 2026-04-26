#!/usr/bin/env python3
"""map_pixel_to_latlon.py — 登録済み地図の (x, y) → (lat, lon) を変換。

使い方:
    python map_pixel_to_latlon.py <map_id> <x> <y> [--json]

入力:
    grid_lines.json (map_auto_assign.py の出力):
      longitudes: [{value, x_mid, points: [[x,y],...]}, ...]  経線群
      latitudes:  [{value, y_mid, points: [[x,y],...]}, ...]  緯線群
      validation: {verified, confidence, issues, metrics}

処理（経線・緯線とも曲線に対応）:
    1. 入力 (x_in, y_in) を含む隣接 2 経線を選ぶ（x_in を挟む）
    2. 各経線 polyline で y_in における x（経線が y_in でどこを通るか）を内挿で取得
    3. x_left_at_y, x_right_at_y で x_in を比例補間 → lon
    4. 緯線も同様：隣接 2 緯線で x_in における y を内挿し、y_in を比例補間 → lat

出力（json 時）:
    {map_id, pixel, lat, lon, validation: {verified, confidence, ...}}

利用側の責務:
    validation.verified=false or confidence < 閾値の時は、結果を信頼度低として扱うこと。
    text mode は警告マークを付ける。json mode は validation を必ず含める。
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

try:
    import numpy as np
except ImportError:
    print("numpy が必要", file=sys.stderr)
    sys.exit(1)

MAPS_DIR = Path("D:/dal_geodata/maps")


def interpolate_x_at_y(points: list[list[int]], y_query: float) -> float | None:
    """polyline (経線) の (x, y) 点列で、y=y_query における x を線形補間。
    y_query が polyline の y 範囲外なら None。"""
    pts = np.array(points, dtype=float)
    if len(pts) < 2:
        return None
    ys = pts[:, 1]
    xs = pts[:, 0]
    sort_idx = np.argsort(ys)
    ys_sorted = ys[sort_idx]
    xs_sorted = xs[sort_idx]
    if y_query < ys_sorted[0] or y_query > ys_sorted[-1]:
        return None
    return float(np.interp(y_query, ys_sorted, xs_sorted))


def interpolate_y_at_x(points: list[list[int]], x_query: float) -> float | None:
    """polyline (緯線) の (x, y) 点列で、x=x_query における y を線形補間。"""
    pts = np.array(points, dtype=float)
    if len(pts) < 2:
        return None
    xs = pts[:, 0]
    ys = pts[:, 1]
    sort_idx = np.argsort(xs)
    xs_sorted = xs[sort_idx]
    ys_sorted = ys[sort_idx]
    if x_query < xs_sorted[0] or x_query > xs_sorted[-1]:
        return None
    return float(np.interp(x_query, xs_sorted, ys_sorted))


def find_neighbor_lines(lines: list[dict], query: float, key: str) -> tuple[dict, dict] | None:
    """lines を key 値順に並べ、query を挟む隣接 2 本を返す。範囲外なら None。"""
    sorted_lines = sorted(lines, key=lambda l: l[key])
    for i in range(len(sorted_lines) - 1):
        if sorted_lines[i][key] <= query <= sorted_lines[i + 1][key]:
            return sorted_lines[i], sorted_lines[i + 1]
    return None


def lookup(grid: dict, x_in: float, y_in: float) -> dict | None:
    """(x_in, y_in) → (lat, lon)。失敗時 None。"""
    longs = grid.get("longitudes", [])
    lats = grid.get("latitudes", [])
    if len(longs) < 2 or len(lats) < 2:
        return None

    # 経線 lookup: 入力 y_in における各経線の x を計算
    long_at_y = []
    for ln in longs:
        x_at = interpolate_x_at_y(ln["points"], y_in)
        if x_at is not None:
            long_at_y.append({"value": ln["value"], "x_at_y": x_at})
    if len(long_at_y) < 2:
        return None
    long_at_y.sort(key=lambda l: l["x_at_y"])
    pair_lon = None
    for i in range(len(long_at_y) - 1):
        if long_at_y[i]["x_at_y"] <= x_in <= long_at_y[i + 1]["x_at_y"]:
            pair_lon = (long_at_y[i], long_at_y[i + 1])
            break
    if pair_lon is None:
        return None
    a, b = pair_lon
    # 比例補間
    span_x = b["x_at_y"] - a["x_at_y"]
    t = (x_in - a["x_at_y"]) / span_x if span_x > 0 else 0.0
    lon = a["value"] + t * (b["value"] - a["value"])

    # 緯線 lookup: 入力 x_in における各緯線の y を計算
    lat_at_x = []
    for ln in lats:
        y_at = interpolate_y_at_x(ln["points"], x_in)
        if y_at is not None:
            lat_at_x.append({"value": ln["value"], "y_at_x": y_at})
    if len(lat_at_x) < 2:
        return None
    lat_at_x.sort(key=lambda l: l["y_at_x"])
    pair_lat = None
    for i in range(len(lat_at_x) - 1):
        if lat_at_x[i]["y_at_x"] <= y_in <= lat_at_x[i + 1]["y_at_x"]:
            pair_lat = (lat_at_x[i], lat_at_x[i + 1])
            break
    if pair_lat is None:
        return None
    c, d = pair_lat
    span_y = d["y_at_x"] - c["y_at_x"]
    t = (y_in - c["y_at_x"]) / span_y if span_y > 0 else 0.0
    lat = c["value"] + t * (d["value"] - c["value"])

    return {"lat": lat, "lon": lon}


def main() -> int:
    p = argparse.ArgumentParser(description="登録済み地図の pixel → lat/lon 変換")
    p.add_argument("map_id")
    p.add_argument("x", type=float)
    p.add_argument("y", type=float)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    map_dir = MAPS_DIR / args.map_id
    if not map_dir.exists():
        print(f"unknown map_id: {args.map_id}", file=sys.stderr)
        return 1

    grid_path = map_dir / "grid_lines.json"
    if not grid_path.exists():
        print(f"grid_lines.json not found, run map_auto_assign.py first", file=sys.stderr)
        return 1

    grid = json.loads(grid_path.read_text(encoding="utf-8"))
    validation = grid.get("validation", {})

    result = lookup(grid, args.x, args.y)
    if result is None:
        if args.json:
            print(json.dumps({
                "map_id": args.map_id,
                "pixel": [args.x, args.y],
                "lat": None,
                "lon": None,
                "error": "lookup failed (out of grid range or insufficient lines)",
                "validation": validation,
            }, ensure_ascii=False))
        else:
            print(f"map: {args.map_id}  pixel=({args.x},{args.y})")
            print(f"  lookup failed (out of grid range or insufficient lines)")
            print(f"  validation: confidence={validation.get('confidence')} verified={validation.get('verified')}")
        return 1

    if args.json:
        out = {
            "map_id": args.map_id,
            "pixel": [args.x, args.y],
            "lat": round(result["lat"], 4),
            "lon": round(result["lon"], 4),
            "validation": validation,
        }
        print(json.dumps(out, ensure_ascii=False))
    else:
        verified = validation.get("verified")
        conf = validation.get("confidence", 0.0)
        marker = "✓" if verified else "⚠"
        print(f"map: {args.map_id}  pixel=({args.x},{args.y})")
        print(f"  → lat={result['lat']:.4f}  lon={result['lon']:.4f}")
        print(f"  validation: {marker} confidence={conf} verified={verified}")
        if validation.get("issues"):
            for iss in validation["issues"]:
                print(f"    - {iss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
