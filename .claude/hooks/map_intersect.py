#!/usr/bin/env python3
"""map_intersect.py — skeleton + Hough で経線・緯線を抽出、中央部の交点を計算。

使い方:
    python map_intersect.py <map_id> [--lon-keep N] [--lat-keep N] [--debug-overlay]

処理:
    1. metadata の image_path、color_filter を読む
    2. HSV color filter で binary mask
    3. skimage.morphology.skeletonize で proper 細線化
    4. cv2.HoughLinesP で線分集合
    5. 角度で vertical（経線）/ horizontal（緯線）分類、ambiguous は捨てる
    6. vertical の中点 x で 1D clustering → 経線群
       horizontal の中点 y で 1D clustering → 緯線群
    7. 中央部のみ keep（lon-keep 本、lat-keep 本、画像中央に近い順）
    8. 各 cluster を polyline 化（線分の中点を中央 sort で並べる）
    9. 経線 polyline × 緯線 polyline の交差点を計算
    10. metadata の lon_range / step、lat_range / step から (lat, lon) を assign
    11. 出力 grid_intersections.json:
        [{"lat": 30.0, "lon": 130.0, "x": 197, "y": 320}, ...]
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
    from skimage.morphology import skeletonize
except ImportError as e:
    print(f"OpenCV / numpy / scikit-image が必要: {e}", file=sys.stderr)
    sys.exit(1)

MAPS_DIR = Path("D:/dal_geodata/maps")


def cluster_by_key(items, key, distance):
    if not items:
        return []
    sorted_items = sorted(items, key=lambda it: it[key])
    groups = [[sorted_items[0]]]
    for it in sorted_items[1:]:
        if abs(it[key] - groups[-1][-1][key]) <= distance:
            groups[-1].append(it)
        else:
            groups.append([it])
    return groups


def _angle_between_vectors(v1, v2):
    """2 ベクトルの角度（度、0-180）。"""
    n1 = (v1[0] ** 2 + v1[1] ** 2) ** 0.5
    n2 = (v2[0] ** 2 + v2[1] ** 2) ** 0.5
    if n1 * n2 == 0:
        return 0.0
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    cos = max(-1.0, min(1.0, cos))
    import math
    return math.degrees(math.acos(cos))


def chain_segments_by_endpoints(segments, max_distance, min_continuation_angle=120):
    """各 segment の 2 端点を集めて、最短ペア順にマッチング。
    マッチした端点は集合から除く。max_distance を超えるペアは採用しない。
    更に **角度条件** で鋭角折り返しを除外：A の進行方向と AB の方向、
    AB と B の進行方向の角度差が大きすぎる（180-min_continuation_angle 度超）
    なら接続しない。デフォルト 120° = 折り返し 60° 以下を許容。

    Returns: list of polylines、各 polyline は順序付き点列 [(x, y), ...]
    """
    n = len(segments)
    if n == 0:
        return []
    # 端点を flatten: ep[seg_id*2 + end_idx] = (x, y)
    eps = []
    for i, s in enumerate(segments):
        x1, y1, x2, y2 = s["seg"]
        eps.append((x1, y1))
        eps.append((x2, y2))
    n_eps = len(eps)

    # 全ペア距離 + 角度判定、適格なものを短い順
    pairs = []
    for i in range(n_eps):
        seg_i = i // 2
        for j in range(i + 1, n_eps):
            seg_j = j // 2
            if seg_i == seg_j:
                continue
            dx = eps[j][0] - eps[i][0]
            dy = eps[j][1] - eps[i][1]
            d = (dx * dx + dy * dy) ** 0.5
            if d > max_distance:
                continue
            # 角度判定: A の他端 → i (vec_a)、i → j (vec_ab)、j → B の他端 (vec_b)
            i_other = eps[i ^ 1]
            j_other = eps[j ^ 1]
            vec_a = (eps[i][0] - i_other[0], eps[i][1] - i_other[1])
            vec_ab = (dx, dy)
            vec_b = (j_other[0] - eps[j][0], j_other[1] - eps[j][1])
            ang_a_ab = _angle_between_vectors(vec_a, vec_ab)
            ang_ab_b = _angle_between_vectors(vec_ab, vec_b)
            # 両方 鈍角以下（< 60° 折り返し = 角度 > 120）であれば OK
            if ang_a_ab > (180 - min_continuation_angle):
                continue
            if ang_ab_b > (180 - min_continuation_angle):
                continue
            pairs.append((d, i, j))
    pairs.sort()

    # greedy matching: 未使用端点同士のペアを採用
    used = set()
    next_of = {}  # endpoint_id → connected endpoint_id
    for d, i, j in pairs:
        if i in used or j in used:
            continue
        next_of[i] = j
        next_of[j] = i
        used.add(i)
        used.add(j)

    # polyline 構築：各 segment の 2 端点から chain follow
    # endpoint i = seg i//2 の端点 (i%2)、segment 内では i と i^1 が同 segment
    visited_eps = set()
    polylines = []
    for start in range(n_eps):
        if start in visited_eps:
            continue
        # endpoint start を起点に chain follow
        # 「seg-internal: start ↔ start^1」と「inter-seg: next_of[*]」を交互に辿る
        chain = []
        cur = start
        # 起点を polyline 始端まで遡る（end-of-chain なら start から進む）
        # シンプル: 最初に 1 方向に進んで終端、そこから逆方向に進む
        path_a = [cur]
        visited_eps.add(cur)
        # 方向 1: cur の seg-partner → next_of → seg-partner → ...
        partner = cur ^ 1
        while partner not in visited_eps:
            path_a.append(partner)
            visited_eps.add(partner)
            nxt = next_of.get(partner)
            if nxt is None or nxt in visited_eps:
                break
            path_a.append(nxt)
            visited_eps.add(nxt)
            partner = nxt ^ 1
        # 方向 2: start の next_of → seg-partner → ...
        path_b = []
        prev = next_of.get(cur)
        if prev is not None and prev not in visited_eps:
            path_b.append(prev)
            visited_eps.add(prev)
            partner = prev ^ 1
            while partner not in visited_eps:
                path_b.append(partner)
                visited_eps.add(partner)
                nxt = next_of.get(partner)
                if nxt is None or nxt in visited_eps:
                    break
                path_b.append(nxt)
                visited_eps.add(nxt)
                partner = nxt ^ 1
        full = list(reversed(path_b)) + path_a
        polyline = [eps[k] for k in full]
        if len(polyline) >= 2:
            polylines.append(polyline)
    return polylines


def line_x_at_y(seg, y):
    """seg = (x1,y1,x2,y2) の直線パラメータで y における x を返す。"""
    x1, y1, x2, y2 = seg
    if y2 == y1:
        return (x1 + x2) / 2.0
    t = (y - y1) / (y2 - y1)
    return x1 + t * (x2 - x1)


def line_y_at_x(seg, x):
    x1, y1, x2, y2 = seg
    if x2 == x1:
        return (y1 + y2) / 2.0
    t = (x - x1) / (x2 - x1)
    return y1 + t * (y2 - y1)


def line_eq(seg):
    """seg=(x1,y1,x2,y2) → ax + by + c = 0 の (a, b, c)。"""
    x1, y1, x2, y2 = seg
    a = y2 - y1
    b = x1 - x2
    c = -(a * x1 + b * y1)
    return a, b, c


def line_intersect(seg1, seg2):
    """2 線分の **延長直線** の交点。平行なら None。"""
    a1, b1, c1 = line_eq(seg1)
    a2, b2, c2 = line_eq(seg2)
    det = a1 * b2 - a2 * b1
    if abs(det) < 1e-9:
        return None
    x = (b1 * c2 - b2 * c1) / det
    y = (a2 * c1 - a1 * c2) / det
    return (x, y)


def segments_intersect_inside(s1, s2):
    """2 線分の **内側** 交差点（両 segment の内側にある場合のみ）。なければ None。"""
    x1, y1, x2, y2 = s1
    x3, y3, x4, y4 = s2
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def line_intersect_extended(s1, s2):
    """2 線分の **延長直線** 交差（segment 内側じゃなくてもOK）。"""
    a1, b1, c1 = line_eq(s1)
    a2, b2, c2 = line_eq(s2)
    det = a1 * b2 - a2 * b1
    if abs(det) < 1e-9:
        return None
    x = (b1 * c2 - b2 * c1) / det
    y = (a2 * c1 - a1 * c2) / det
    return (x, y)


def group_pair_intersection(v_group, h_group, w_img, h_img):
    """経線 group と緯線 group の交点（最近接ペアの延長交差）。

    1. 全 (v_seg, h_seg) ペアで内側交差を試す → 見つかれば中央値
    2. 内側交差なければ、最近接ペア（segment 中心間距離最小）の延長交差
    """
    direct = []
    for v in v_group:
        for h in h_group:
            pt = segments_intersect_inside(v["seg"], h["seg"])
            if pt is not None:
                direct.append(pt)
    if direct:
        return (float(np.median([p[0] for p in direct])),
                float(np.median([p[1] for p in direct])))
    best_pair = None
    best_dist = float("inf")
    for v in v_group:
        for h in h_group:
            v_mid = ((v["seg"][0] + v["seg"][2]) / 2.0,
                     (v["seg"][1] + v["seg"][3]) / 2.0)
            h_mid = ((h["seg"][0] + h["seg"][2]) / 2.0,
                     (h["seg"][1] + h["seg"][3]) / 2.0)
            d = (v_mid[0] - h_mid[0]) ** 2 + (v_mid[1] - h_mid[1]) ** 2
            if d < best_dist:
                best_dist = d
                best_pair = (v["seg"], h["seg"])
    if best_pair is None:
        return None
    return line_intersect_extended(*best_pair)


def main() -> int:
    p = argparse.ArgumentParser(description="経線・緯線交点抽出")
    p.add_argument("map_id")
    p.add_argument("--lon-keep", type=int, default=4, help="中央 keep 経線数")
    p.add_argument("--lat-keep", type=int, default=4, help="中央 keep 緯線数")
    p.add_argument("--cluster-x-distance", type=int, default=15)
    p.add_argument("--cluster-y-distance", type=int, default=20)
    p.add_argument("--edge-margin", type=int, default=15,
                   help="画像縁からこの px 以内の cluster は枠と見なして除外")
    p.add_argument("--min-cluster-segs", type=int, default=2,
                   help="cluster 内 segments 最低数（ノイズ排除）")
    p.add_argument("--min-cluster-range", type=int, default=30,
                   help="cluster の vertical y range or horizontal x range 最低値（ノイズ排除）")
    p.add_argument("--hough-threshold", type=int, default=30)
    p.add_argument("--hough-min-length", type=int, default=30)
    p.add_argument("--hough-max-gap", type=int, default=10)
    p.add_argument("--angle-tol", type=float, default=30,
                   help="vertical: 90-tol〜90、horizontal: 0〜tol")
    p.add_argument("--debug-overlay", action="store_true")
    args = p.parse_args()

    map_dir = MAPS_DIR / args.map_id
    if not map_dir.exists():
        print(f"unknown map_id: {args.map_id}", file=sys.stderr)
        return 1
    metadata = json.loads((map_dir / "metadata.json").read_text(encoding="utf-8"))

    img = cv2.imread(metadata["image_path"])
    if img is None:
        print(f"image 読めず", file=sys.stderr)
        return 1
    h_img, w_img = img.shape[:2]

    cf = metadata.get("color_filter")
    if not cf:
        print("metadata.color_filter 必須", file=sys.stderr)
        return 1
    vals = [int(v) for v in cf.split(",")]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv,
                        np.array(vals[:3], dtype=np.uint8),
                        np.array(vals[3:], dtype=np.uint8))
    skel = (skeletonize(mask > 0).astype(np.uint8)) * 255

    lines = cv2.HoughLinesP(skel, rho=1, theta=np.pi / 180,
                             threshold=args.hough_threshold,
                             minLineLength=args.hough_min_length,
                             maxLineGap=args.hough_max_gap)
    if lines is None:
        print("no Hough lines", file=sys.stderr)
        return 1

    vert, horiz = [], []
    for ln in lines:
        x1, y1, x2, y2 = (int(v) for v in ln[0])
        a = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        a = a if a <= 90 else 180 - a
        seg_data = {"seg": (x1, y1, x2, y2), "mid_x": (x1 + x2) / 2.0,
                    "mid_y": (y1 + y2) / 2.0, "angle": a}
        if 90 - args.angle_tol <= a <= 90:
            vert.append(seg_data)
        elif a <= args.angle_tol:
            horiz.append(seg_data)
    print(f"Hough: {len(lines)} segments → vert={len(vert)} horiz={len(horiz)}")

    # 1D clustering
    v_clusters = cluster_by_key(vert, "mid_x", args.cluster_x_distance)
    h_clusters = cluster_by_key(horiz, "mid_y", args.cluster_y_distance)
    # 画像縁の枠を除外（margin px 以内）
    margin = args.edge_margin
    v_clusters = [c for c in v_clusters
                  if margin < np.mean([s["mid_x"] for s in c]) < w_img - margin]
    h_clusters = [c for c in h_clusters
                  if margin < np.mean([s["mid_y"] for s in c]) < h_img - margin]
    # ノイズ cluster 除外: n_seg >= min_seg かつ y/x range >= min_range
    def v_range(c):
        return max(s["mid_y"] for s in c) - min(s["mid_y"] for s in c)
    def h_range(c):
        return max(s["mid_x"] for s in c) - min(s["mid_x"] for s in c)
    v_clusters = [c for c in v_clusters
                  if len(c) >= args.min_cluster_segs and v_range(c) >= args.min_cluster_range]
    h_clusters = [c for c in h_clusters
                  if len(c) >= args.min_cluster_segs and h_range(c) >= args.min_cluster_range]
    print(f"clusters (edge+noise-filtered): vert={len(v_clusters)} horiz={len(h_clusters)}")

    # 中央 keep: 全 cluster を x 順 / y 順に並べ、中央 N 個の **連続** cluster を取る
    v_sorted_x = sorted(v_clusters,
                        key=lambda c: np.mean([s["mid_x"] for s in c]))
    h_sorted_y = sorted(h_clusters,
                        key=lambda c: np.mean([s["mid_y"] for s in c]))
    v_start = max(0, (len(v_sorted_x) - args.lon_keep) // 2)
    h_start = max(0, (len(h_sorted_y) - args.lat_keep) // 2)
    v_keep = v_sorted_x[v_start:v_start + args.lon_keep]
    h_keep = h_sorted_y[h_start:h_start + args.lat_keep]
    print(f"keep: vert={len(v_keep)} horiz={len(h_keep)} "
          f"(x_mids={[round(np.mean([s['mid_x'] for s in c]), 1) for c in v_keep]}, "
          f"y_mids={[round(np.mean([s['mid_y'] for s in c]), 1) for c in h_keep]})")

    # 各 cluster は segments のリストとしてそのまま保持（merge しない、生ベクトル）

    # metadata から経度・緯度値を assign
    # 中央 4 経線は中央経度範囲の 4 連続値、画像中央 cx に近い 4 本＝中央 4 経度
    lon_range = metadata.get("lon_range")
    lon_step = metadata.get("lon_step")
    lat_range = metadata.get("lat_range")
    lat_step = metadata.get("lat_step")
    if not all([lon_range, lon_step, lat_range, lat_step]):
        print("metadata に lon/lat range, step 必要", file=sys.stderr)
        return 1

    # 期待される全経線・緯線リスト
    n_lon_total = int(round((lon_range[1] - lon_range[0]) / lon_step)) + 1
    n_lat_total = int(round((lat_range[1] - lat_range[0]) / lat_step)) + 1
    all_lon = [lon_range[0] + lon_step * i for i in range(n_lon_total)]
    all_lat = [lat_range[1] - lat_step * i for i in range(n_lat_total)]

    # 中央 lon_keep 本＝中央 lon の連続値（all_lon の中央 lon_keep 個）
    lon_start_idx = (n_lon_total - args.lon_keep) // 2
    lon_values = all_lon[lon_start_idx:lon_start_idx + args.lon_keep]
    lat_start_idx = (n_lat_total - args.lat_keep) // 2
    lat_values = all_lat[lat_start_idx:lat_start_idx + args.lat_keep]
    print(f"lon assigned: {lon_values}")
    print(f"lat assigned: {lat_values}")

    # 経線 × 緯線 で交点計算（生ベクトル group ペアの内側交差 or 最近接延長交差）
    intersections = []
    for li, lon_val in enumerate(lon_values):
        for la, lat_val in enumerate(lat_values):
            pt = group_pair_intersection(v_keep[li], h_keep[la], w_img, h_img)
            if pt is None:
                print(f"  ! no intersection: lon={lon_val} lat={lat_val}", file=sys.stderr)
                continue
            x, y = pt
            intersections.append({
                "lon": lon_val, "lat": lat_val,
                "x": round(x, 2), "y": round(y, 2),
            })

    out = {
        "map_id": args.map_id,
        "image_size": [w_img, h_img],
        "lon_values": lon_values,
        "lat_values": lat_values,
        "intersections": intersections,
        "params": {
            "color_filter": cf,
            "hough_threshold": args.hough_threshold,
            "hough_min_length": args.hough_min_length,
            "hough_max_gap": args.hough_max_gap,
            "angle_tol": args.angle_tol,
            "cluster_x_distance": args.cluster_x_distance,
            "cluster_y_distance": args.cluster_y_distance,
            "lon_keep": args.lon_keep,
            "lat_keep": args.lat_keep,
        },
    }
    out_path = map_dir / "grid_intersections.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(intersections)} intersections → {out_path}")

    if args.debug_overlay:
        overlay = img.copy()
        # 生 segments を group ごとに描画（merge せず、skel_hough_debug.png と同じ精度）
        for v_group in v_keep:
            for s in v_group:
                x1, y1, x2, y2 = s["seg"]
                cv2.line(overlay, (x1, y1), (x2, y2), (0, 255, 0), 2)
        for h_group in h_keep:
            for s in h_group:
                x1, y1, x2, y2 = s["seg"]
                cv2.line(overlay, (x1, y1), (x2, y2), (0, 0, 255), 2)
        for ix in intersections:
            x, y = int(ix["x"]), int(ix["y"])
            cv2.circle(overlay, (x, y), 5, (0, 255, 255), -1)
            cv2.putText(overlay, f"{ix['lon']:.0f}/{ix['lat']:.0f}",
                        (x + 6, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        (0, 0, 0), 1, cv2.LINE_AA)
        ovl_path = map_dir / "grid_intersections_overlay.png"
        cv2.imwrite(str(ovl_path), overlay)
        print(f"overlay: {ovl_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
