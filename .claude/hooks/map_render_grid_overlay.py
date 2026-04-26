#!/usr/bin/env python3
"""map_render_grid_overlay.py — 検出された経線・緯線を数字付きでオーバーレイ描画。

人間による検証用。grid_lines.json の assignment が画像のどこにどう乗ってるかを
visualize して、ずれや誤 assign を視認できるようにする。

使い方:
    python map_render_grid_overlay.py <map_id> [--output PATH]

入力:
    metadata.json (image_path)
    grid_lines.json (longitudes, latitudes, validation)

出力（default: <map_dir>/grid_overlay.png）:
    元画像 + 経線（赤 polyline）+ 緯線（青 polyline）+ 数字ラベル
    + validation 情報（左上、verified/confidence/issues）
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
    import cv2
    import numpy as np
except ImportError as e:
    print(f"OpenCV / numpy が必要: {e}", file=sys.stderr)
    sys.exit(1)

MAPS_DIR = Path("D:/dal_geodata/maps")

# BGR
COLOR_LON = (0, 0, 255)   # 経線：赤
COLOR_LAT = (255, 0, 0)   # 緯線：青
COLOR_LABEL_BG = (255, 255, 255)
COLOR_LABEL_TEXT = (0, 0, 0)
COLOR_VALIDATION_BAD = (0, 0, 200)
COLOR_VALIDATION_OK = (0, 150, 0)


def draw_polyline(img, points, color, thickness=2):
    if len(points) < 2:
        return
    pts = np.array([(int(x), int(y)) for x, y in points], dtype=np.int32)
    sort_idx = np.argsort(pts[:, 1]) if abs(pts[-1, 0] - pts[0, 0]) < abs(pts[-1, 1] - pts[0, 1]) else np.argsort(pts[:, 0])
    pts = pts[sort_idx]
    cv2.polylines(img, [pts], isClosed=False, color=color, thickness=thickness)


def draw_label(img, text, x, y, fg=COLOR_LABEL_TEXT, bg=COLOR_LABEL_BG):
    """白背景 + 黒文字でラベル描画。"""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.45
    thick = 1
    (w, h), baseline = cv2.getTextSize(text, font, scale, thick)
    pad = 2
    x = max(0, min(img.shape[1] - w - pad * 2, x))
    y = max(h + pad, min(img.shape[0] - pad, y))
    cv2.rectangle(img, (x - pad, y - h - pad), (x + w + pad, y + baseline + pad), bg, -1)
    cv2.putText(img, text, (x, y), font, scale, fg, thick, cv2.LINE_AA)


def main() -> int:
    p = argparse.ArgumentParser(description="経線・緯線オーバーレイ描画")
    p.add_argument("map_id")
    p.add_argument("--output", default=None,
                   help="保存先（default: <map_dir>/grid_overlay.png）")
    args = p.parse_args()

    map_dir = MAPS_DIR / args.map_id
    if not map_dir.exists():
        print(f"unknown map_id: {args.map_id}", file=sys.stderr)
        return 1

    metadata = json.loads((map_dir / "metadata.json").read_text(encoding="utf-8"))
    grid_path = map_dir / "grid_lines.json"
    if not grid_path.exists():
        print(f"grid_lines.json not found, run map_auto_assign.py first", file=sys.stderr)
        return 1
    grid = json.loads(grid_path.read_text(encoding="utf-8"))

    img = cv2.imread(metadata["image_path"])
    if img is None:
        print(f"image 読めず: {metadata['image_path']}", file=sys.stderr)
        return 1

    # 経線描画（赤、polyline + 上下端にラベル）
    for ln in grid.get("longitudes", []):
        pts = ln["points"]
        if len(pts) < 2:
            continue
        # y で sort して polyline
        pts_sorted = sorted(pts, key=lambda p: p[1])
        np_pts = np.array(pts_sorted, dtype=np.int32)
        cv2.polylines(img, [np_pts], False, COLOR_LON, 2)
        # ラベル位置：polyline の y 最大点（画像下端寄り）の x で
        bottom_pt = pts_sorted[-1]
        label = f"{ln['value']:.0f}°E"
        draw_label(img, label, bottom_pt[0] - 15, min(bottom_pt[1] + 15, img.shape[0] - 5))

    # 緯線描画（青、polyline + 左右端にラベル）
    for ln in grid.get("latitudes", []):
        pts = ln["points"]
        if len(pts) < 2:
            continue
        pts_sorted = sorted(pts, key=lambda p: p[0])
        np_pts = np.array(pts_sorted, dtype=np.int32)
        cv2.polylines(img, [np_pts], False, COLOR_LAT, 2)
        # ラベル位置：polyline の x 最小点（画像左端寄り）の y で
        left_pt = pts_sorted[0]
        label = f"{ln['value']:.0f}°N"
        draw_label(img, label, max(2, left_pt[0] - 40), left_pt[1] + 4)

    # validation 情報を左上に
    val = grid.get("validation", {})
    verified = val.get("verified", False)
    conf = val.get("confidence", 0.0)
    bg = COLOR_VALIDATION_OK if verified else COLOR_VALIDATION_BAD
    cv2.rectangle(img, (5, 5), (300, 30), bg, -1)
    text = f"{'VERIFIED' if verified else 'LOW CONFIDENCE'}  conf={conf}"
    cv2.putText(img, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA)

    issues = val.get("issues", [])
    y = 50
    for iss in issues[:5]:
        draw_label(img, iss[:80], 10, y)
        y += 20

    out_path = Path(args.output) if args.output else map_dir / "grid_overlay.png"
    cv2.imwrite(str(out_path), img)
    print(f"overlay saved: {out_path}")
    print(f"  validation: {'verified' if verified else 'LOW'} confidence={conf}")
    print(f"  longitudes: {len(grid.get('longitudes', []))}")
    print(f"  latitudes:  {len(grid.get('latitudes', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
