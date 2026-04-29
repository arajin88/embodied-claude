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
    """中心 + axes (direction_deg + radius_nm) → 境界 (lat, lon) を n 点サンプリング"""
    pts = []
    valid_axes = [a for a in axes if a.get("direction_deg") is not None and a.get("radius_nm") is not None]
    if not valid_axes:
        return pts
    for i in range(n):
        theta = i * 360.0 / n  # deg from N, clockwise
        if len(valid_axes) == 1:
            r_nm = valid_axes[0]["radius_nm"]
        else:
            ws, rs = [], []
            for ax in valid_axes:
                d = abs(theta - ax["direction_deg"])
                d = min(d, 360 - d)  # ∈ [0, 180]
                w = (180 - d) / 180.0  # 近いほど大
                ws.append(w)
                rs.append(ax["radius_nm"])
            total_w = sum(ws)
            r_nm = sum(w * r for w, r in zip(ws, rs)) / total_w if total_w > 0 else sum(rs) / len(rs)
        r_km = r_nm * 1.852
        rad = math.radians(theta)
        dlat = (r_km / 111.0) * math.cos(rad)
        cos_lat = math.cos(math.radians(lat0))
        dlon = (r_km / (111.0 * max(0.1, cos_lat))) * math.sin(rad)
        pts.append((lat0 + dlat, lon0 + dlon))
    return pts


def clip_polygon_to_bbox(latlon_pts, bbox, w, h):
    """polygon の lat/lon 列を image (x, y) 列に変換、bbox 外は除外（端は近似クリップ）"""
    xy = []
    for lat, lon in latlon_pts:
        # 緯度・経度をクランプ（bbox 端で切り捨て近似）
        lat_c = max(bbox["lat_min"], min(bbox["lat_max"], lat))
        lon_c = max(bbox["lon_min"], min(bbox["lon_max"], lon))
        xy.append(latlon_to_xy(lat_c, lon_c, bbox, w, h))
    # すべてが bbox 外なら描かない
    if all(not in_bbox(lat, lon, bbox) for lat, lon in latlon_pts):
        return []
    return xy


def draw_polygon(draw, xy, fill, outline):
    if len(xy) < 3:
        return
    flat = [(int(p[0]), int(p[1])) for p in xy]
    draw.polygon(flat, fill=fill, outline=outline)


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
                    draw_polygon(d, xy, style["fill"], style["outline"])
                    cx = sum(p[0] for p in xy) / len(xy)
                    cy = sum(p[1] for p in xy) / len(xy)
                    label_positions.append((cx, cy, style["label"]))
            # Circle 系（中心 + 4方位）
            for circ in area.get("circles", []):
                if circ.get("lat") is None or circ.get("lon") is None or not circ.get("axes"):
                    continue
                bnd = sample_warning_boundary(circ["lat"], circ["lon"], circ["axes"])
                if not bnd:
                    continue
                xy = clip_polygon_to_bbox(bnd, bbox, W, H)
                if xy:
                    # 12h/24h 後は薄く
                    fill = style["fill"]
                    outline = style["outline"]
                    if "１２時間後" in (circ.get("base_type") or "") or "２４時間後" in (circ.get("base_type") or ""):
                        # alpha を半分に
                        fill = (fill[0], fill[1], fill[2], fill[3] // 2)
                        outline = (outline[0], outline[1], outline[2], outline[3] // 2)
                    draw_polygon(d, xy, fill, outline)
                    # ラベル位置：中心
                    cx, cy = latlon_to_xy(
                        max(bbox["lat_min"], min(bbox["lat_max"], circ["lat"])),
                        max(bbox["lon_min"], min(bbox["lon_max"], circ["lon"])),
                        bbox, W, H
                    )
                    if 0 <= cx <= W and 0 <= cy <= H:
                        suffix = ""
                        if "１２時間後" in (circ.get("base_type") or ""):
                            suffix = "+12h"
                        elif "２４時間後" in (circ.get("base_type") or ""):
                            suffix = "+24h"
                        label_positions.append((cx, cy, f"{style['label']}{suffix}"))

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
