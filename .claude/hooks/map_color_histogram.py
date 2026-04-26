#!/usr/bin/env python3
"""map_color_histogram.py — 画像の HSV histogram で指定色帯の S/V 分布を確認。

格子線色を pin する前段階。アンチエイリアスがかかった線は中心と縁で S/V が広く分布
するので、分布の min-max（あるいは percentile 5-95）を見て幅を決める。

使い方:
    # 緑帯（H=35-90）の S/V 分布を見る
    python map_color_histogram.py <image_path> --hue-range 35,90

    # 全 hue の peak top-N
    python map_color_histogram.py <image_path> --top 8

出力:
    - hue histogram の top peak（緑帯絞り込みの目安）
    - 指定 hue 範囲内の S/V の percentile（5, 50, 95）と min-max
    - 推奨フィルタ範囲（"--color-filter で使える文字列"）
"""
from __future__ import annotations

import argparse
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


def main() -> int:
    p = argparse.ArgumentParser(description="画像の HSV histogram から色フィルタ範囲を提案")
    p.add_argument("image_path")
    p.add_argument("--hue-range", default=None,
                   help="絞り込む hue 範囲 'low,high' (OpenCV の H は 0-180)")
    p.add_argument("--top", type=int, default=8,
                   help="hue histogram の peak top-N を表示（--hue-range 未指定時）")
    p.add_argument("--margin-s", type=int, default=20,
                   help="推奨 S 範囲の min/max にこの値を margin として加える")
    p.add_argument("--margin-v", type=int, default=20,
                   help="推奨 V 範囲の min/max にこの値を margin として加える")
    args = p.parse_args()

    img = cv2.imread(args.image_path)
    if img is None:
        print(f"image 読めず: {args.image_path}", file=sys.stderr)
        return 1

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    # Hue histogram (saturation > 30 のみ、塗りつぶし白・黒は除外)
    valid = s > 30
    hue_hist = np.bincount(h[valid].ravel(), minlength=180)

    if args.hue_range is None:
        print(f"image: {Path(args.image_path).name}  total px={h.size}  with-color={valid.sum()}")
        print(f"\n=== Hue peaks (top {args.top}, S>30) ===")
        peaks = np.argsort(hue_hist)[::-1][:args.top]
        for hue in sorted(peaks):
            print(f"  H={hue:3d}: {hue_hist[hue]:6d} px  (1°色相目安：{hue*2}-{hue*2+1}°)")
        return 0

    # 指定 hue 範囲内の S/V 分布
    try:
        h_lo, h_hi = (int(v) for v in args.hue_range.split(","))
    except Exception:
        print("--hue-range は 'low,high'", file=sys.stderr)
        return 2

    in_range = (h >= h_lo) & (h <= h_hi) & (s > 30)
    n = int(in_range.sum())
    if n == 0:
        print(f"hue {h_lo}-{h_hi} に該当する pixel なし", file=sys.stderr)
        return 1

    s_in = s[in_range]
    v_in = v[in_range]

    s_p = np.percentile(s_in, [5, 25, 50, 75, 95])
    v_p = np.percentile(v_in, [5, 25, 50, 75, 95])

    print(f"image: {Path(args.image_path).name}  hue {h_lo}-{h_hi}: {n} px")
    print(f"\n=== Saturation 分布 ===")
    print(f"  min={s_in.min()}  p5={s_p[0]:.0f}  p25={s_p[1]:.0f}  median={s_p[2]:.0f}  p75={s_p[3]:.0f}  p95={s_p[4]:.0f}  max={s_in.max()}")
    print(f"=== Value 分布 ===")
    print(f"  min={v_in.min()}  p5={v_p[0]:.0f}  p25={v_p[1]:.0f}  median={v_p[2]:.0f}  p75={v_p[3]:.0f}  p95={v_p[4]:.0f}  max={v_in.max()}")

    # 推奨フィルタ範囲（p5-p95 + margin）
    s_lo = max(0, int(s_p[0]) - args.margin_s)
    s_hi = min(255, int(s_p[4]) + args.margin_s)
    v_lo = max(0, int(v_p[0]) - args.margin_v)
    v_hi = min(255, int(v_p[4]) + args.margin_v)
    print(f"\n=== 推奨 --color-filter（p5-p95 + margin） ===")
    print(f"  --color-filter \"{h_lo},{s_lo},{v_lo},{h_hi},{s_hi},{v_hi}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
