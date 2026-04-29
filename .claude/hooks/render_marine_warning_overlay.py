#!/usr/bin/env python3
"""render_marine_warning_overlay.py — VPZU52 海上警報を a00 透明 PNG overlay に描画

出力: D:/jma_archive/forecast/japan/<YYYY/MM/DD>/mwarn_<utc>_a00.png

色凡例:
  22 暴風 [SW]  : 濃赤 fill+outline
  21 強風 [GW]  : 橙
  23 台風 [TW]  : 紫
  24 着氷 [HSS] : 水色
  11 濃霧 [FOG] : 薄黄

警報領域:
  - Polygon (緯度経度) → 多角形 fill+outline
  - Circle (中心 + 4方位非対称半径) → 角度別 boundary をサンプリングして polygon 化
  - 海域名指定 (オホーツク海等) → 注記のみ（polygon 辞書未整備）

使い方:
    python render_marine_warning_overlay.py D:/jma_archive/maps/sample_VPZU52_20260428.xml
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from parse_marine_warning_xml import parse_marine_warning, WARNING_LABELS

bbox_data = json.loads(Path("D:/jma_archive/maps/region_bbox.json").read_text(encoding="utf-8"))["regions"]

# 警報種別 → 色 (RGBA: fill, outline)
WARNING_STYLE = {
    "22": {"fill": (220, 30, 30, 70),   "outline": (180, 0, 0, 240),    "label": "[SW]", "name_short": "暴風"},
    "21": {"fill": (240, 130, 30, 60),  "outline": (200, 80, 0, 230),   "label": "[GW]", "name_short": "強風"},
    "23": {"fill": (180, 30, 200, 70),  "outline": (140, 0, 160, 240),  "label": "[TW]", "name_short": "台風"},
    "24": {"fill": (60, 180, 200, 60),  "outline": (30, 130, 160, 220), "label": "[HSS]", "name_short": "着氷"},
    "11": {"fill": (200, 180, 60, 50),  "outline": (160, 140, 30, 200), "label": "[FOG]", "name_short": "濃霧"},
}


def latlon_to_xy(lat, lon, bbox, w, h):
    x = (lon - bbox["lon_min"]) / (bbox["lon_max"] - bbox["lon_min"]) * w
    y = (bbox["lat_max"] - lat) / (bbox["lat_max"] - bbox["lat_min"]) * h
    return (x, y)


def in_bbox(lat, lon, bbox):
    return (bbox["lat_min"] <= lat <= bbox["lat_max"] and
            bbox["lon_min"] <= lon <= bbox["lon_max"])


def sample_warning_boundary(lat0, lon0, axes, n=72):
    """JMA 規定: 2 軸の端点を結んだ線分を直径とする円を描画（台風も同方式、papa 4/29 教示）

    - 1 軸 (description=全域): BasePoint 中心の真円
    - 2 軸: 各 axis の端点を線分で結び、その中点を中心に、線分長を直径とする真円
    - 3 軸以上 (まれ): 隣接ペアで 4-quadrant 分割（未対応、線形重み fallback）
    """
    valid_axes = [a for a in axes if a.get("direction_deg") is not None and a.get("radius_nm") is not None]
    if not valid_axes:
        return []

    cos_lat0 = math.cos(math.radians(lat0))

    def offset(theta_deg, r_nm):
        """中心 (lat0, lon0) から方位 + 半径(nm) → 端点 (lat, lon)"""
        r_km = r_nm * 1.852
        rad = math.radians(theta_deg)
        dlat = (r_km / 111.0) * math.cos(rad)
        dlon = (r_km / (111.0 * max(0.1, cos_lat0))) * math.sin(rad)
        return (lat0 + dlat, lon0 + dlon)

    # 1 軸 (全域): 真円
    if len(valid_axes) == 1:
        r_nm = valid_axes[0]["radius_nm"]
        return _sample_circle(lat0, lon0, r_nm * 1.852, n)

    # 2 軸: JMA 規定の off-center 真円（線分の中点 + 線分長/2）
    if len(valid_axes) == 2:
        a, b = valid_axes
        p_a = offset(a["direction_deg"], a["radius_nm"])
        p_b = offset(b["direction_deg"], b["radius_nm"])
        mid_lat = (p_a[0] + p_b[0]) / 2
        mid_lon = (p_a[1] + p_b[1]) / 2
        cos_mid = math.cos(math.radians(mid_lat))
        # 線分長 (km)
        dlat_diff_km = (p_a[0] - p_b[0]) * 111.0
        dlon_diff_km = (p_a[1] - p_b[1]) * 111.0 * cos_mid
        diameter_km = math.sqrt(dlat_diff_km ** 2 + dlon_diff_km ** 2)
        radius_km = diameter_km / 2
        return _sample_circle(mid_lat, mid_lon, radius_km, n)

    # 3 軸以上: 線形重み fallback（旧実装相当）
    pts = []
    for i in range(n):
        theta = i * 360.0 / n
        ws, rs = [], []
        for ax in valid_axes:
            d = abs(theta - ax["direction_deg"])
            d = min(d, 360 - d)
            ws.append((180 - d) / 180.0)
            rs.append(ax["radius_nm"])
        total_w = sum(ws)
        r_nm = sum(w * r for w, r in zip(ws, rs)) / total_w if total_w > 0 else sum(rs) / len(rs)
        pts.append(offset(theta, r_nm))
    return pts


def _sample_circle(center_lat, center_lon, radius_km, n=72):
    """中心 + 半径(km) で真円を n 点サンプリング"""
    cos_lat = math.cos(math.radians(center_lat))
    pts = []
    for i in range(n):
        theta = i * 360.0 / n
        rad = math.radians(theta)
        dlat = (radius_km / 111.0) * math.cos(rad)
        dlon = (radius_km / (111.0 * max(0.1, cos_lat))) * math.sin(rad)
        pts.append((center_lat + dlat, center_lon + dlon))
    return pts


def clip_polygon_to_bbox(latlon_pts, bbox, w, h):
    """polygon の lat/lon 列を image (x, y) 列に変換。bbox 外頂点もそのままピクセル座標化、
    PIL の canvas 外描画は自動で clip される。clamp すると polygon が歪むので避ける。

    日付変更線（lon=180/-180）横断の対応:
      bbox の lon 範囲が東経内なら lon < 0 の頂点に +360 を加えて連続化
      （例: 北太平洋の polygon が 51N+156E から 51N-179E へ → 51N+181E に wrap）

    全頂点が bbox 外なら空 list（描画なし）。
    """
    pts = list(latlon_pts)
    # bbox が東経域 (lon_min > 0) で polygon に lon < 0 が混じってたら +360 で連続化
    if bbox["lon_min"] > 0 and any(lon < 0 for _, lon in pts):
        pts = [(lat, lon + 360 if lon < 0 else lon) for lat, lon in pts]
    if not any(in_bbox(lat, lon, bbox) for lat, lon in pts):
        return []
    return [latlon_to_xy(lat, lon, bbox, w, h) for lat, lon in pts]


def draw_polygon(canvas, xy, fill, outline):
    """canvas (RGBA Image) に polygon を alpha_composite で重ね描き。
    PIL の draw.polygon は上書き動作で alpha ブレンドしないので、polygon ごとに
    透明 layer を作って alpha_composite する。複数 polygon が重なる領域で fill 色が混ざる。"""
    if len(xy) < 3:
        return
    flat = [(int(p[0]), int(p[1])) for p in xy]
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.polygon(flat, fill=fill, outline=outline)
    canvas.alpha_composite(layer)


def render_marine_warnings(parsed: dict, code: str = "00") -> Image.Image:
    bbox = bbox_data[code]
    W, H = 940, 783
    canvas = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    d = ImageDraw.Draw(canvas)

    font = None
    for path in [r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\YuGothM.ttc"]:
        try:
            font = ImageFont.truetype(path, 14)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    label_positions = []  # 衝突回避用 (x, y, text)

    # Headline 警報を描画
    for w in parsed["headline_warnings"]:
        code_w = w["code"]
        style = WARNING_STYLE.get(code_w, {"fill": (100, 100, 100, 50), "outline": (60, 60, 60, 200), "label": f"[{code_w}]", "name_short": w.get("name", "?")})
        for area in w["areas"]:
            # Polygon 系
            if area.get("polygon"):
                xy = clip_polygon_to_bbox(area["polygon"], bbox, W, H)
                if xy:
                    draw_polygon(canvas, xy, style["fill"], style["outline"])
                    # ラベル位置は bbox 内頂点のみで重心、無ければ全頂点の重心、最後に canvas 内 clamp
                    in_pts = [p for p in xy if 0 <= p[0] <= W and 0 <= p[1] <= H]
                    pts_for_label = in_pts if in_pts else xy
                    cx = sum(p[0] for p in pts_for_label) / len(pts_for_label)
                    cy = sum(p[1] for p in pts_for_label) / len(pts_for_label)
                    cx = max(20, min(W - 60, cx))
                    cy = max(20, min(H - 30, cy))
                    label_positions.append((cx, cy, style["label"]))
            # Circle 系（中心 + 4方位）
            for circ in area.get("circles", []):
                if circ.get("lat") is None or circ.get("lon") is None or not circ.get("axes"):
                    continue
                base_type = circ.get("base_type") or ""
                # 予報円（12h / 24h 後位置）は実況 viewer に出さない（papa 4/29 17:27 判断:
                # 実況画面で予報検証するのは筋悪い、verification は別 view で）
                if "１２時間後" in base_type or "２４時間後" in base_type:
                    continue
                bnd = sample_warning_boundary(circ["lat"], circ["lon"], circ["axes"])
                if not bnd:
                    continue
                xy = clip_polygon_to_bbox(bnd, bbox, W, H)
                if xy:
                    fill = style["fill"]
                    outline = style["outline"]
                    draw_polygon(canvas, xy, fill, outline)
                    # ラベル位置：実況中心（予報円は描画しないので suffix なし）
                    cx, cy = latlon_to_xy(
                        max(bbox["lat_min"], min(bbox["lat_max"], circ["lat"])),
                        max(bbox["lon_min"], min(bbox["lon_max"], circ["lon"])),
                        bbox, W, H
                    )
                    if 0 <= cx <= W and 0 <= cy <= H:
                        label_positions.append((cx, cy, style["label"]))

    # ラベル描画（背景白塗り）
    for x, y, text in label_positions:
        x, y = int(x), int(y)
        # 背景白半透明
        try:
            tw = font.getlength(text)
        except Exception:
            tw = len(text) * 8
        d.rectangle([x - 2, y - 8, x + tw + 2, y + 8], fill=(255, 255, 255, 180))
        d.text((x, y - 7), text, fill=(0, 0, 0, 255), font=font)

    # 観測基準時刻のスタンプ（右下、wchart の上に積む。XML body 内 MeteorologicalInfo
    # の DateTime を使う ＝ ASAS の valid_at と揃う本物の観測時刻。target_at は発表時刻なので不採用）
    obs_at = parsed.get("observation_at") or parsed.get("target_at")
    if obs_at:
        try:
            from datetime import timedelta as _td
            dt = datetime.fromisoformat(obs_at.replace("Z", "+00:00"))
            dt_jst = dt.astimezone(timezone(_td(hours=9)))
            stamp = f"海上警報 {dt_jst.strftime('%m/%d %H:%M')} JST"
        except ValueError:
            stamp = f"海上警報 {obs_at}"
        try:
            font_stamp = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", 20)
        except Exception:
            font_stamp = font
        try:
            tw = font_stamp.getlength(stamp)
        except Exception:
            tw = len(stamp) * 12
        x = W - int(tw) - 16
        y = H - 60  # 右下、wchart (H-32) の上
        d.rectangle([x - 4, y - 2, x + int(tw) + 4, y + 24], fill=(255, 255, 255, 220))
        d.text((x, y), stamp, fill=(20, 20, 20, 255), font=font_stamp)

    return canvas


def derive_t0_utc(report_at: str | None, xml_path: Path) -> str:
    if report_at:
        try:
            dt = datetime.fromisoformat(report_at.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M00")
        except ValueError:
            pass
    m = re.search(r"(\d{14})", xml_path.stem)
    if m:
        return m.group(1)
    return "00000000000000"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("xml_path")
    p.add_argument("--area", default="00", help="地方コード、default: 00（全国）")
    args = p.parse_args()

    xml = Path(args.xml_path)
    parsed = parse_marine_warning(xml)
    t0_utc = derive_t0_utc(parsed.get("report_at"), xml)
    dt = datetime.strptime(t0_utc, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) + timedelta(hours=9)

    img = render_marine_warnings(parsed, code=args.area)
    slug_map = {"00": "japan"}
    slug = slug_map.get(args.area, f"area{args.area}")
    out_dir = Path(f"D:/jma_archive/forecast/{slug}/{dt.strftime('%Y/%m/%d')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"mwarn_{t0_utc}_a{args.area}.png"
    img.save(out)

    n_w = len(parsed["headline_warnings"])
    by_code = {}
    for w in parsed["headline_warnings"]:
        by_code[w["code"]] = by_code.get(w["code"], 0) + 1
    print(f"target: {parsed['target_at']}")
    print(f"headline warnings: {n_w}")
    for c, n in sorted(by_code.items()):
        label = WARNING_LABELS.get(c, "?")
        print(f"  [{c}] {label}: {n}")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
