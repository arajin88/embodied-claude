#!/usr/bin/env python3
"""map_auto_assign.py — extracted_lines.json から自動 assign + validation。

使い方:
    python map_auto_assign.py <map_id>

処理:
    1. metadata.json から lon_range, lon_step, lat_range, lat_step を読む
    2. extracted_lines.json から x_groups, y_groups を読む
    3. 期待される経線数 N_lon = (lon_max - lon_min) / step + 1、緯線数 N_lat も同様
    4. x_groups を n_pts 上位 N_lon 本選び、x_mid 順に並べて lon_min, +step, ... を assign
    5. y_groups を n_pts 上位 N_lat 本選び、y_mid 順に並べて lat_max, -step, ... を assign
       （y は画像内で上が高緯度なので、y_mid 小さい順 = 緯度大きい順）
    6. validation 計算: spacing_std, n_assigned vs n_expected, etc.
    7. confidence = 1.0 - normalized_irregularity（0-1）
    8. grid_lines.json に validation 付きで保存

出力:
    grid_lines.json:
      {
        "longitudes": [{"value": 100.0, "x_mid": 36.7, "points": [[x,y],...]}, ...],
        "latitudes":  [{"value": 50.0,  "y_mid": 95.0, "points": [...]}, ...],
        "validation": {
          "verified": bool,
          "confidence": 0.0-1.0,
          "issues": [...],
          "metrics": {...},
          "checked_at": "..."
        }
      }
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
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
CONFIDENCE_THRESHOLD = 0.7  # この値以上で verified=true


def auto_assign(groups: list[dict], expected_n: int, value_min: float, value_step: float,
                ascending_value: bool, sort_key: str) -> tuple[list[dict], list[str]]:
    """groups の上位 expected_n を選び、sort_key 順に並べて値を割り当てる。

    ascending_value: True なら sort_key 順に値が増加（経線：左 x 小 → lon 小）。
                     False なら sort_key 順に値が減少（緯線：上 y 小 → lat 大）。
    """
    issues = []
    if len(groups) < expected_n:
        issues.append(f"only {len(groups)} groups < expected {expected_n}")
    # n_pts で sort、上位を取る
    by_size = sorted(groups, key=lambda g: -len(g["points"]))
    selected = by_size[:expected_n]
    # sort_key で並べ直す
    selected.sort(key=lambda g: g[sort_key])
    out = []
    for i, g in enumerate(selected):
        if ascending_value:
            v = value_min + value_step * i
        else:
            v = value_min - value_step * i
        out.append({
            "value": v,
            "x_mid": g["x_mid"],
            "y_mid": g["y_mid"],
            "n_points": len(g["points"]),
            "bbox": g["bbox"],
            "points": g["points"],
        })
    return out, issues


def compute_validation(longitudes: list[dict], latitudes: list[dict],
                       expected_n_lon: int, expected_n_lat: int,
                       lon_step: float, lat_step: float) -> dict:
    """spacing 等から validation metric を計算。"""
    issues = []

    # n assigned vs expected
    if len(longitudes) < expected_n_lon:
        issues.append(f"n_lon_assigned {len(longitudes)} < expected {expected_n_lon}")
    if len(latitudes) < expected_n_lat:
        issues.append(f"n_lat_assigned {len(latitudes)} < expected {expected_n_lat}")

    # 経線 x_mid の間隔の分散
    lon_x = sorted([g["x_mid"] for g in longitudes])
    lon_diffs = [lon_x[i + 1] - lon_x[i] for i in range(len(lon_x) - 1)]
    lon_spacing_std = float(np.std(lon_diffs)) if lon_diffs else 0.0
    lon_spacing_mean = float(np.mean(lon_diffs)) if lon_diffs else 0.0
    lon_irreg = lon_spacing_std / lon_spacing_mean if lon_spacing_mean > 0 else 1.0

    # 緯線 y_mid の間隔（y は画像内で増、緯度は減）
    lat_y = sorted([g["y_mid"] for g in latitudes])
    lat_diffs = [lat_y[i + 1] - lat_y[i] for i in range(len(lat_y) - 1)]
    lat_spacing_std = float(np.std(lat_diffs)) if lat_diffs else 0.0
    lat_spacing_mean = float(np.mean(lat_diffs)) if lat_diffs else 0.0
    # 緯線は円錐図法で間隔不揃い、std/mean が小さいほど良いが、緯線の場合は緩く判定
    lat_irreg = lat_spacing_std / lat_spacing_mean if lat_spacing_mean > 0 else 1.0

    if lon_irreg > 0.3:
        issues.append(f"lon_spacing_irregular: std/mean={lon_irreg:.2f} > 0.3")
    if lat_irreg > 0.5:
        issues.append(f"lat_spacing_irregular: std/mean={lat_irreg:.2f} > 0.5 (円錐図法 OK)")

    # confidence: 1.0 から irregularity と n 不足を引く
    confidence = 1.0
    confidence -= max(0, expected_n_lon - len(longitudes)) * 0.1
    confidence -= max(0, expected_n_lat - len(latitudes)) * 0.1
    confidence -= min(0.4, lon_irreg)
    confidence -= min(0.2, lat_irreg)
    confidence = max(0.0, min(1.0, confidence))

    verified = (confidence >= CONFIDENCE_THRESHOLD) and (len(issues) == 0)

    return {
        "verified": verified,
        "confidence": round(confidence, 3),
        "issues": issues,
        "metrics": {
            "n_lon_assigned": len(longitudes),
            "n_lon_expected": expected_n_lon,
            "n_lat_assigned": len(latitudes),
            "n_lat_expected": expected_n_lat,
            "lon_spacing_std": round(lon_spacing_std, 2),
            "lon_spacing_mean": round(lon_spacing_mean, 2),
            "lon_irregularity": round(lon_irreg, 3),
            "lat_spacing_std": round(lat_spacing_std, 2),
            "lat_spacing_mean": round(lat_spacing_mean, 2),
            "lat_irregularity": round(lat_irreg, 3),
        },
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: map_auto_assign.py <map_id>", file=sys.stderr)
        return 2
    map_id = sys.argv[1]
    map_dir = MAPS_DIR / map_id
    if not map_dir.exists():
        print(f"unknown map_id: {map_id}", file=sys.stderr)
        return 1

    metadata = json.loads((map_dir / "metadata.json").read_text(encoding="utf-8"))
    extracted_path = map_dir / "extracted_lines.json"
    if not extracted_path.exists():
        print(f"extracted_lines.json not found, run map_extract_lines.py first", file=sys.stderr)
        return 1
    extracted = json.loads(extracted_path.read_text(encoding="utf-8"))

    lon_range = metadata.get("lon_range")
    lon_step = metadata.get("lon_step")
    lat_range = metadata.get("lat_range")
    lat_step = metadata.get("lat_step")
    if not all([lon_range, lon_step, lat_range, lat_step]):
        print("metadata.json に lon_range/lon_step/lat_range/lat_step が必要", file=sys.stderr)
        return 1

    expected_n_lon = int(round((lon_range[1] - lon_range[0]) / lon_step)) + 1
    expected_n_lat = int(round((lat_range[1] - lat_range[0]) / lat_step)) + 1

    x_groups = extracted.get("x_groups", [])
    y_groups = extracted.get("y_groups", [])

    longitudes, lon_issues = auto_assign(
        x_groups, expected_n_lon, lon_range[0], lon_step,
        ascending_value=True, sort_key="x_mid",
    )
    latitudes, lat_issues = auto_assign(
        y_groups, expected_n_lat, lat_range[1], lat_step,
        ascending_value=False, sort_key="y_mid",
    )

    validation = compute_validation(
        longitudes, latitudes, expected_n_lon, expected_n_lat, lon_step, lat_step,
    )
    validation["issues"] = lon_issues + lat_issues + validation["issues"]

    out = {
        "longitudes": longitudes,
        "latitudes": latitudes,
        "validation": validation,
    }
    grid_path = map_dir / "grid_lines.json"
    grid_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"assigned {len(longitudes)} lon × {len(latitudes)} lat → {grid_path}")
    print(f"  confidence: {validation['confidence']}  verified: {validation['verified']}")
    if validation["issues"]:
        print(f"  issues:")
        for iss in validation["issues"]:
            print(f"    - {iss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
