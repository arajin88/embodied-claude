#!/usr/bin/env python3
"""map_extract_projection.py — 列・行 projection で経線・緯線を直接抽出。

contour ベースの問題（findContours は領域境界、線が 2px 幅で行って戻る点列、
group merge で構造破壊）を回避。**緑 pixel の各列・各行の密度を 1D 関数化**
して、ピーク位置を経線・緯線位置として直接取得する。

使い方:
    python map_extract_projection.py <image_path> [--map-id MAP_ID]
        [--color-filter h_low,s_low,v_low,h_high,s_high,v_high]
        [--smooth-window 5]
        [--peak-prominence 30]
        [--peak-distance 30]
        [--debug-overlay]

処理:
    1. HSV color filter で binary mask
    2. col_density[x] = mask の各 x 列の緑 pixel 数 → 1D signal (width)
    3. row_density[y] = mask の各 y 行の緑 pixel 数 → 1D signal (height)
    4. moving average で smooth、scipy.signal.find_peaks で局所ピーク検出
    5. 各 peak が経線（x 値）or 緯線（y 値）の位置

出力:
    extracted_projection.json:
      {
        "method": "projection",
        "longitude_peaks": [{"x": 132, "density": 87, "prominence": 65}, ...],
        "latitude_peaks":  [{"y": 95,  "density": 320, "prominence": 280}, ...],
        "params": {...}
      }
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
    from scipy.signal import find_peaks
except ImportError as e:
    print(f"OpenCV / numpy / scipy が必要: {e}", file=sys.stderr)
    sys.exit(1)

MAPS_DIR = Path("D:/dal_geodata/maps")


def smooth_1d(signal: np.ndarray, window: int) -> np.ndarray:
    """単純 moving average（境界は same サイズで返す）。"""
    if window <= 1:
        return signal.astype(float)
    kernel = np.ones(window) / window
    return np.convolve(signal.astype(float), kernel, mode="same")


def main() -> int:
    p = argparse.ArgumentParser(description="列・行 projection で経線・緯線を抽出")
    p.add_argument("image_path")
    p.add_argument("--map-id", default=None)
    p.add_argument("--color-filter", default=None,
                   help="HSV 範囲。未指定時は metadata.json から読む")
    p.add_argument("--smooth-window", type=int, default=5)
    p.add_argument("--peak-prominence", type=float, default=30,
                   help="ピーク高さ閾値（基底からの突出量）")
    p.add_argument("--peak-distance", type=int, default=30,
                   help="隣接ピーク最小距離（px）")
    p.add_argument("--debug-overlay", action="store_true")
    args = p.parse_args()

    img_path = Path(args.image_path)
    if not img_path.exists():
        print(f"not found: {img_path}", file=sys.stderr)
        return 1

    img = cv2.imread(str(img_path))
    if img is None:
        print(f"OpenCV で読めない: {img_path}", file=sys.stderr)
        return 1
    h, w = img.shape[:2]

    color_filter = args.color_filter
    if color_filter is None and args.map_id:
        meta_path = MAPS_DIR / args.map_id / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            color_filter = meta.get("color_filter")

    if color_filter is None:
        print("--color-filter or metadata.color_filter が必要", file=sys.stderr)
        return 2

    vals = [int(v) for v in color_filter.split(",")]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lower = np.array(vals[:3], dtype=np.uint8)
    upper = np.array(vals[3:], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    mask_pixels = int(mask.sum() / 255)

    # 各 x 列・各 y 行の緑 pixel 数
    col_density = (mask > 0).sum(axis=0)  # shape (w,)
    row_density = (mask > 0).sum(axis=1)  # shape (h,)

    # smooth
    col_smoothed = smooth_1d(col_density, args.smooth_window)
    row_smoothed = smooth_1d(row_density, args.smooth_window)

    # peak detection
    col_peaks, col_props = find_peaks(
        col_smoothed,
        prominence=args.peak_prominence,
        distance=args.peak_distance,
    )
    row_peaks, row_props = find_peaks(
        row_smoothed,
        prominence=args.peak_prominence,
        distance=args.peak_distance,
    )

    longitude_peaks = [
        {"x": int(x), "density": float(col_smoothed[x]),
         "prominence": float(col_props["prominences"][i])}
        for i, x in enumerate(col_peaks)
    ]
    latitude_peaks = [
        {"y": int(y), "density": float(row_smoothed[y]),
         "prominence": float(row_props["prominences"][i])}
        for i, y in enumerate(row_peaks)
    ]

    print(f"image: {img_path.name} ({w}x{h})  mask px={mask_pixels}")
    print(f"longitude peaks: {len(longitude_peaks)}")
    for i, p_ in enumerate(longitude_peaks):
        print(f"  [{i}] x={p_['x']:3d}  density={p_['density']:.0f}  prominence={p_['prominence']:.0f}")
    print(f"latitude peaks: {len(latitude_peaks)}")
    for i, p_ in enumerate(latitude_peaks):
        print(f"  [{i}] y={p_['y']:3d}  density={p_['density']:.0f}  prominence={p_['prominence']:.0f}")

    if args.debug_overlay:
        overlay = img.copy()
        for p_ in longitude_peaks:
            cv2.line(overlay, (p_["x"], 0), (p_["x"], h), (0, 255, 0), 1)
        for p_ in latitude_peaks:
            cv2.line(overlay, (0, p_["y"]), (w, p_["y"]), (0, 0, 255), 1)
        ovl_path = img_path.with_name(img_path.stem + "_projection_debug.png")
        cv2.imwrite(str(ovl_path), overlay)
        print(f"\noverlay saved: {ovl_path}")

    if args.map_id:
        map_dir = MAPS_DIR / args.map_id
        if not map_dir.exists():
            print(f"map_id not registered: {args.map_id}", file=sys.stderr)
            return 1
        out = {
            "method": "projection",
            "longitude_peaks": longitude_peaks,
            "latitude_peaks": latitude_peaks,
            "params": {
                "color_filter": color_filter,
                "smooth_window": args.smooth_window,
                "peak_prominence": args.peak_prominence,
                "peak_distance": args.peak_distance,
            },
        }
        ext_path = map_dir / "extracted_projection.json"
        ext_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nsaved → {ext_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
