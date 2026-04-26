#!/usr/bin/env python3
"""map_extract_lines.py — 地図画像から経線・緯線を OpenCV で抽出。

使い方:
    python map_extract_lines.py <image_path> [--map-id MAP_ID]
        [--method hough|contour]
        [--color-filter h_low,s_low,v_low,h_high,s_high,v_high]
        [--canny-low 50 --canny-high 150]
        [--hough-threshold 80 --hough-min-length 100 --hough-max-gap 20]
        [--angle-tol 3 --cluster-distance 5]
        [--min-contour-length 100]
        [--debug-overlay]

処理:
    method=hough（直線分の集合検出、円弧経線/緯線は分散しがち）:
        グレースケール → Canny → HoughLinesP → 角度で縦/横分類 → クラスタ統合
    method=contour（連続曲線として抽出、円弧でも 1 polyline で保存）:
        color filter → skeletonize（線中心 1px 化） → findContours
        → 長さ filter → 各 contour を polyline として保存
        → bbox 縦横比で経線（縦長）/緯線（横長 or 円弧）を仮分類

出力:
    - <map_id>/extracted_lines.json
      {
        "vertical_candidates": [{"px_start":[x,y],"px_end":[x,y],"x_mid":N,"length":L}, ...],
        "horizontal_candidates": [{"px_start":[x,y],"px_end":[x,y],"y_mid":N,"length":L}, ...]
      }
    - <image_path>_lines_debug.png（--debug-overlay 時のみ）

注意:
    緯度経度値の assign は本ツールではしない（別ステップ）。
    緯線が曲線の場合、Hough は短い直線分の集合として検出する。複数の小線分が同じ y_mid 帯
    に並ぶことがある。クラスタリングで統合される。
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


def line_angle_deg(x1, y1, x2, y2) -> float:
    a = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
    return abs(a) if a <= 90 else 180 - abs(a)  # 0-90 に正規化（180°ラップ吸収）


def line_length(x1, y1, x2, y2) -> float:
    return float(np.hypot(x2 - x1, y2 - y1))


def cluster_lines(lines: list[tuple[int, int, int, int]], orient: str, distance: int):
    """orient='vertical' → x_mid 基準、'horizontal' → y_mid 基準でクラスタ統合。

    同じクラスタの線分は端点を統合（min/max y or x）して 1 本の代表線を作る。
    """
    if not lines:
        return []
    items = []
    for (x1, y1, x2, y2) in lines:
        if orient == "vertical":
            mid = (x1 + x2) / 2.0
        else:
            mid = (y1 + y2) / 2.0
        items.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "mid": mid})

    items.sort(key=lambda it: it["mid"])

    clusters = []
    cur = [items[0]]
    for it in items[1:]:
        if abs(it["mid"] - cur[-1]["mid"]) <= distance:
            cur.append(it)
        else:
            clusters.append(cur)
            cur = [it]
    clusters.append(cur)

    out = []
    for cl in clusters:
        if orient == "vertical":
            # 全線分の上端と下端を統合
            top_y = min(min(it["y1"], it["y2"]) for it in cl)
            bot_y = max(max(it["y1"], it["y2"]) for it in cl)
            # 代表 x は cluster 内 x_mid の中央値
            mids = sorted(it["mid"] for it in cl)
            rep_x = mids[len(mids) // 2]
            out.append({
                "px_start": [int(round(rep_x)), int(top_y)],
                "px_end":   [int(round(rep_x)), int(bot_y)],
                "x_mid": float(rep_x),
                "length": int(bot_y - top_y),
                "n_segments": len(cl),
            })
        else:
            left_x = min(min(it["x1"], it["x2"]) for it in cl)
            right_x = max(max(it["x1"], it["x2"]) for it in cl)
            mids = sorted(it["mid"] for it in cl)
            rep_y = mids[len(mids) // 2]
            out.append({
                "px_start": [int(left_x),  int(round(rep_y))],
                "px_end":   [int(right_x), int(round(rep_y))],
                "y_mid": float(rep_y),
                "length": int(right_x - left_x),
                "n_segments": len(cl),
            })
    return out


def skeletonize_cv(binary: np.ndarray) -> np.ndarray:
    """OpenCV 純正の iterative skeletonize（線中心 1px 化）。

    Zhang-Suen 系の代替。Slow だが scikit-image 依存なし。
    """
    skel = np.zeros(binary.shape, dtype=np.uint8)
    img = binary.copy()
    elem = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while True:
        eroded = cv2.erode(img, elem)
        opened = cv2.dilate(eroded, elem)
        temp = cv2.subtract(img, opened)
        skel = cv2.bitwise_or(skel, temp)
        img = eroded.copy()
        if cv2.countNonZero(img) == 0:
            break
    return skel


def principal_angle_deg(points: list[tuple[int, int]]) -> float:
    """点群の PCA 主軸の角度（0-90°、0=水平、90=垂直）。"""
    pts = np.array(points, dtype=float)
    if len(pts) < 2:
        return 0.0
    centered = pts - pts.mean(axis=0)
    cov = np.cov(centered.T)
    eigvals, eigvecs = np.linalg.eig(cov)
    principal = eigvecs[:, np.argmax(eigvals)]
    angle = float(np.degrees(np.arctan2(abs(principal[1]), abs(principal[0]))))
    return angle  # 0-90


def cluster_by_key(items: list[dict], key_fn, distance: float) -> list[list[dict]]:
    """key 値でソートして近接距離内の連続要素を 1 グループにまとめる。"""
    if not items:
        return []
    sorted_items = sorted(items, key=key_fn)
    groups = [[sorted_items[0]]]
    for it in sorted_items[1:]:
        if abs(key_fn(it) - key_fn(groups[-1][-1])) <= distance:
            groups[-1].append(it)
        else:
            groups.append([it])
    return groups


def merge_polyline_group(group: list[dict], sort_key: str = "y") -> dict:
    """グループ内の全 contour 点を統合、polyline として返す。

    sort_key='y': 経線用、点列を y 昇順に並べる
    sort_key='x': 緯線用、点列を x 昇順に並べる
    """
    all_pts = []
    for c in group:
        all_pts.extend(c["points"])
    if sort_key == "y":
        all_pts.sort(key=lambda p: p[1])
    else:
        all_pts.sort(key=lambda p: p[0])
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    return {
        "points": all_pts,
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
        "x_mid": float(np.mean(xs)),
        "y_mid": float(np.mean(ys)),
        "n_raw": len(group),
    }


def contour_polyline(contour) -> list[tuple[int, int]]:
    """OpenCV contour (N,1,2) を [(x,y),...] のリストに変換。"""
    return [(int(p[0][0]), int(p[0][1])) for p in contour]


def run_contour(img, mask, img_path: Path, args) -> int:
    """contour 方式での線抽出。kind 分類はせず、全 contour を保存して
    x_mid と y_mid の両方でクラスタリングする。経線/緯線の判定と緯度経度値
    の assign は次の段階（map_assign_grid_values.py）の仕事。
    """
    if args.no_skeletonize:
        target = mask
        print("skeletonize: skipped")
    else:
        target = skeletonize_cv(mask)

    contours, _ = cv2.findContours(target, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)

    polylines = []
    for c in contours:
        if len(c) < args.min_contour_length:
            continue
        pts = contour_polyline(c)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        angle = principal_angle_deg(pts)  # 0-90°、0=水平、90=垂直
        if angle >= 60:
            hint = "vertical"
        elif angle <= 30:
            hint = "horizontal"
        else:
            hint = "ambiguous"
        polylines.append({
            "n_points": len(pts),
            "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
            "x_mid": (bbox[0] + bbox[2]) / 2.0,
            "y_mid": (bbox[1] + bbox[3]) / 2.0,
            "principal_angle": round(angle, 1),
            "hint": hint,
            "points": pts,
        })

    # PCA hint で clustering 入力を選別（早期分類でなく hint）
    x_input = [p for p in polylines if p["hint"] in ("vertical", "ambiguous")]
    y_input = [p for p in polylines if p["hint"] in ("horizontal", "ambiguous")]
    x_groups = cluster_by_key(x_input, lambda p: p["x_mid"], args.group_x_distance)
    y_groups = cluster_by_key(y_input, lambda p: p["y_mid"], args.group_y_distance)

    x_merged = [merge_polyline_group(g, sort_key="y") for g in x_groups]
    y_merged = [merge_polyline_group(g, sort_key="x") for g in y_groups]

    print(f"image: {img_path.name} ({img.shape[1]}x{img.shape[0]})")
    print(f"contours total >= {args.min_contour_length} pts: {len(polylines)}")
    print(f"  x_mid groups (経線候補): {len(x_merged)}")
    print(f"  y_mid groups (緯線候補): {len(y_merged)}")
    print()
    print("=== x_mid groups (x 順、経線候補) ===")
    for i, g in enumerate(x_merged):
        print(f"  [{i}] x_mid={g['x_mid']:.1f}  n_pts={len(g['points'])}  "
              f"y range={g['bbox'][1]}-{g['bbox'][3]}  raw_contours={g['n_raw']}")
    print("=== y_mid groups (y 順、緯線候補) ===")
    for i, g in enumerate(y_merged):
        print(f"  [{i}] y_mid={g['y_mid']:.1f}  n_pts={len(g['points'])}  "
              f"x range={g['bbox'][0]}-{g['bbox'][2]}  raw_contours={g['n_raw']}")

    if args.debug_overlay:
        overlay = img.copy()
        # x_mid groups は緑、y_mid groups は赤で重ね描き（参考表示）
        for g in x_merged:
            for x, y in g["points"]:
                cv2.circle(overlay, (x, y), 1, (0, 255, 0), -1)
        for g in y_merged:
            for x, y in g["points"]:
                cv2.circle(overlay, (x, y), 1, (0, 0, 255), -1)
        ovl_path = img_path.with_name(img_path.stem + "_lines_debug.png")
        cv2.imwrite(str(ovl_path), overlay)
        print(f"\noverlay saved: {ovl_path}")

    if args.map_id:
        map_dir = MAPS_DIR / args.map_id
        if not map_dir.exists():
            print(f"map_id not registered: {args.map_id}", file=sys.stderr)
            return 1
        out = {
            "method": "contour",
            "x_groups": x_merged,
            "y_groups": y_merged,
            "params": {
                "color_filter": args.color_filter,
                "min_contour_length": args.min_contour_length,
                "group_x_distance": args.group_x_distance,
                "group_y_distance": args.group_y_distance,
            },
        }
        ext_path = map_dir / "extracted_lines.json"
        ext_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nsaved → {ext_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="OpenCV で地図画像の経線・緯線を抽出")
    p.add_argument("image_path")
    p.add_argument("--map-id", default=None,
                   help="MAPS_DIR/<map_id>/extracted_lines.json に保存。未指定なら stdout のみ")
    p.add_argument("--canny-low", type=int, default=50)
    p.add_argument("--canny-high", type=int, default=150)
    p.add_argument("--hough-threshold", type=int, default=80)
    p.add_argument("--hough-min-length", type=int, default=100)
    p.add_argument("--hough-max-gap", type=int, default=20)
    p.add_argument("--angle-tol", type=float, default=3.0,
                   help="水平/垂直の角度許容（度）、デフォルト 3°")
    p.add_argument("--cluster-distance", type=int, default=5,
                   help="クラスタ統合距離（px）")
    p.add_argument("--color-filter", default=None,
                   help="HSV 範囲で前処理マスク (例 '35,60,30,90,255,255' = 緑系)")
    p.add_argument("--method", choices=["hough", "contour"], default="hough",
                   help="抽出方式。曲線（円錐図法の経線・緯線）は contour 推奨")
    p.add_argument("--min-contour-length", type=int, default=100,
                   help="contour 方式での polyline 最低長さ（px）")
    p.add_argument("--no-skeletonize", action="store_true",
                   help="contour 方式で skeletonize をスキップ（mask 線が既に細い時）")
    p.add_argument("--group-x-distance", type=int, default=15,
                   help="経線グルーピング距離（同 x 帯にまとめる px、default 15）")
    p.add_argument("--group-y-distance", type=int, default=20,
                   help="緯線グルーピング距離（同 y 帯にまとめる px、default 20）")
    p.add_argument("--debug-overlay", action="store_true",
                   help="検出線を上書きした overlay PNG を保存")
    args = p.parse_args()

    img_path = Path(args.image_path)
    if not img_path.exists():
        print(f"not found: {img_path}", file=sys.stderr)
        return 1

    img = cv2.imread(str(img_path))
    if img is None:
        print(f"OpenCV で読めない: {img_path}", file=sys.stderr)
        return 1

    mask = None
    if args.color_filter:
        try:
            vals = [int(v) for v in args.color_filter.split(",")]
            assert len(vals) == 6
        except Exception:
            print("--color-filter は 'h_low,s_low,v_low,h_high,s_high,v_high'", file=sys.stderr)
            return 2
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower = np.array(vals[:3], dtype=np.uint8)
        upper = np.array(vals[3:], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)
        masked = np.where(mask[:, :, None] > 0, img, 255).astype(np.uint8)
        gray = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
        print(f"color filter applied: HSV {vals[:3]} – {vals[3:]} ({int(mask.sum() / 255)} px matched)")
        if args.debug_overlay:
            mask_path = img_path.with_name(img_path.stem + "_mask_debug.png")
            cv2.imwrite(str(mask_path), masked)
            print(f"mask preview saved: {mask_path}")
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ==== method 分岐 ====
    if args.method == "contour":
        if mask is None:
            # color filter 無しの場合、グレー画像を二値化してマスク化
            _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        return run_contour(img, mask, img_path, args)

    edges = cv2.Canny(gray, args.canny_low, args.canny_high)
    lines = cv2.HoughLinesP(
        edges, rho=1, theta=np.pi / 180,
        threshold=args.hough_threshold,
        minLineLength=args.hough_min_length,
        maxLineGap=args.hough_max_gap,
    )
    if lines is None:
        print("no lines detected. Hough パラメータ調整してください", file=sys.stderr)
        return 1

    vertical_segs, horizontal_segs = [], []
    for ln in lines:
        x1, y1, x2, y2 = ln[0]
        a = line_angle_deg(x1, y1, x2, y2)
        if abs(a - 90) <= args.angle_tol:
            vertical_segs.append((int(x1), int(y1), int(x2), int(y2)))
        elif a <= args.angle_tol:
            horizontal_segs.append((int(x1), int(y1), int(x2), int(y2)))

    vertical_clusters = cluster_lines(vertical_segs, "vertical", args.cluster_distance)
    horizontal_clusters = cluster_lines(horizontal_segs, "horizontal", args.cluster_distance)

    print(f"image: {img_path.name} ({img.shape[1]}x{img.shape[0]})")
    print(f"hough segments: {len(lines)} total → "
          f"vertical={len(vertical_segs)} horizontal={len(horizontal_segs)}")
    print(f"after clustering: vertical={len(vertical_clusters)}, "
          f"horizontal={len(horizontal_clusters)}")
    print()
    print("=== vertical (経線候補) ===")
    for i, c in enumerate(vertical_clusters):
        print(f"  [{i}] x_mid={c['x_mid']:.1f}  start={c['px_start']}  end={c['px_end']}  "
              f"len={c['length']}  segs={c['n_segments']}")
    print("=== horizontal (緯線候補) ===")
    for i, c in enumerate(horizontal_clusters):
        print(f"  [{i}] y_mid={c['y_mid']:.1f}  start={c['px_start']}  end={c['px_end']}  "
              f"len={c['length']}  segs={c['n_segments']}")

    if args.debug_overlay:
        overlay = img.copy()
        for c in vertical_clusters:
            cv2.line(overlay, tuple(c["px_start"]), tuple(c["px_end"]), (0, 255, 0), 2)
        for c in horizontal_clusters:
            cv2.line(overlay, tuple(c["px_start"]), tuple(c["px_end"]), (0, 0, 255), 2)
        ovl_path = img_path.with_name(img_path.stem + "_lines_debug.png")
        cv2.imwrite(str(ovl_path), overlay)
        print(f"\noverlay saved: {ovl_path}")

    if args.map_id:
        map_dir = MAPS_DIR / args.map_id
        if not map_dir.exists():
            print(f"map_id not registered: {args.map_id}", file=sys.stderr)
            return 1
        out = {
            "vertical_candidates": vertical_clusters,
            "horizontal_candidates": horizontal_clusters,
            "params": {
                "canny": [args.canny_low, args.canny_high],
                "hough": [args.hough_threshold, args.hough_min_length, args.hough_max_gap],
                "angle_tol": args.angle_tol,
                "cluster_distance": args.cluster_distance,
            },
        }
        ext_path = map_dir / "extracted_lines.json"
        ext_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nsaved → {ext_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
