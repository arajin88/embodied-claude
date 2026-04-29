#!/usr/bin/env python3
"""render_weather_chart_overlay.py — 天気図 XML から各地方の overlay PNG を生成（透明背景）

入力: VZSA50 / VZSF50 / VZSF51 XML
出力: D:/jma_archive/forecast/<slug>/<YYYY/MM/DD>/wchart_<utc>_a<XX>.png
      （透明背景、等圧線 + L/H 中心 + 前線 polyline、border / 凡例 抜き）

viewer に重ねる layer として使う。色凡例:
- 等圧線: 細い黒線
- 低気圧: 赤い「低」+ hPa
- 高気圧: 青い「高」+ hPa
- 寒冷前線: 青系太線
- 温暖前線: 赤系太線
- 停滞前線: 緑系太線
- 閉塞前線: 紫系太線

使い方:
    python render_weather_chart_overlay.py D:/jma_archive/maps/sample_VZSA50_20260428.xml
    python render_weather_chart_overlay.py <path> --area 14
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from parse_weather_chart_xml import parse_chart
from jma_rain_layer_fetch import AREA_SLUGS

bbox_data = json.loads(Path("D:/jma_archive/maps/region_bbox.json").read_text(encoding="utf-8"))["regions"]

# 描画スタイル
ISOBAR_COLOR = (40, 40, 40, 200)        # 等圧線：濃灰
ISOBAR_WIDTH = 1
LOW_COLOR    = (200, 30, 30, 255)       # 低気圧：赤
HIGH_COLOR   = (30, 60, 200, 255)       # 高気圧：青
FRONT_COLORS = {
    "cold":       (30, 60, 220, 255),    # 青
    "warm":       (220, 30, 30, 255),    # 赤
    "stationary": (30, 160, 60, 255),    # 緑
    "occluded":   (160, 30, 200, 255),   # 紫
    "tropical_low": (220, 80, 30, 255),  # オレンジ
    "typhoon":    (220, 30, 80, 255),    # 濃赤
}
FRONT_WIDTH = 3


def latlon_to_xy(lat, lon, bbox, w, h):
    """linear cylindrical bbox lookup"""
    if not (bbox["lat_min"] <= lat <= bbox["lat_max"] and
            bbox["lon_min"] <= lon <= bbox["lon_max"]):
        return None
    x = (lon - bbox["lon_min"]) / (bbox["lon_max"] - bbox["lon_min"]) * w
    y = (bbox["lat_max"] - lat) / (bbox["lat_max"] - bbox["lat_min"]) * h
    return (x, y)


def clip_polyline_to_bbox(polyline, bbox, w, h):
    """polyline を bbox 内 segment に分割（外に出る部分は break して polyline list で返す）"""
    segs = []
    cur = []
    for lat, lon in polyline:
        xy = latlon_to_xy(lat, lon, bbox, w, h)
        if xy is None:
            if len(cur) >= 2:
                segs.append(cur)
            cur = []
        else:
            cur.append(xy)
    if len(cur) >= 2:
        segs.append(cur)
    return segs


def draw_polyline(draw, points, color, width):
    if len(points) < 2:
        return
    flat = [(int(p[0]), int(p[1])) for p in points]
    draw.line(flat, fill=color, width=width)


def render_for_area(chart: dict, code: str) -> Image.Image:
    bbox = bbox_data[code]
    W, H = 940, 783
    canvas = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    d = ImageDraw.Draw(canvas)

    # 等圧線
    for iso in chart.get("isobars", []):
        polylines = iso.get("polyline")
        if not polylines:
            continue
        # polyline 単一 or list of polylines（XML 内に複数 Line ある時）
        if isinstance(polylines[0][0], list):
            for pl in polylines:
                for seg in clip_polyline_to_bbox(pl, bbox, W, H):
                    draw_polyline(d, seg, ISOBAR_COLOR, ISOBAR_WIDTH)
        else:
            for seg in clip_polyline_to_bbox(polylines, bbox, W, H):
                draw_polyline(d, seg, ISOBAR_COLOR, ISOBAR_WIDTH)

    # 前線
    for fr in chart.get("fronts", []):
        ftype = fr.get("type", "stationary")
        color = FRONT_COLORS.get(ftype, (60, 60, 60, 255))
        polylines = fr.get("polyline")
        if not polylines:
            continue
        if isinstance(polylines[0][0], list):
            for pl in polylines:
                for seg in clip_polyline_to_bbox(pl, bbox, W, H):
                    draw_polyline(d, seg, color, FRONT_WIDTH)
        else:
            for seg in clip_polyline_to_bbox(polylines, bbox, W, H):
                draw_polyline(d, seg, color, FRONT_WIDTH)

    # 低気圧 / 高気圧 / 熱帯低気圧 / 台風
    font = None
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", 20)
    except Exception:
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\YuGothM.ttc", 20)
        except Exception:
            font = ImageFont.load_default()
    font_small = None
    try:
        font_small = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", 14)
    except Exception:
        font_small = font

    def draw_arrow_from(x, y, direction_deg, speed_kt, color):
        """L/H 中心 (x, y) から direction (北=0、時計回り) と速度に応じた矢印"""
        import math
        rad = math.radians(direction_deg)
        scale = 2.0  # 2 px/kt（30 kt なら 60 px）
        Lpx = speed_kt * scale
        dx = Lpx * math.sin(rad)
        dy = -Lpx * math.cos(rad)  # 画像 y 下向き
        x2, y2 = x + dx, y + dy
        d.line([(x, y), (x2, y2)], fill=color, width=2)
        # 矢頭（末端から逆方向に ±23°、長さ 8）
        head_len, head_angle = 9, 0.4
        line_angle = math.atan2(y2 - y, x2 - x)
        for da in (-head_angle, head_angle):
            a = line_angle + math.pi - da
            hx = x2 + head_len * math.cos(a)
            hy = y2 + head_len * math.sin(a)
            d.line([(x2, y2), (hx, hy)], fill=color, width=2)
        # 速度ラベル（矢印先端のすぐ脇）
        d.text((x2 + 4, y2 - 6), f"{int(speed_kt)}kt", fill=color, font=font_small)

    def draw_center(label, lat, lon, hPa, color, direction_deg=None, speed_kt=None):
        xy = latlon_to_xy(lat, lon, bbox, W, H)
        if xy is None:
            return
        x, y = int(xy[0]), int(xy[1])
        # 移動矢印を最初に（中心マークの下に来るように）
        if direction_deg is not None and speed_kt is not None:
            draw_arrow_from(x, y, direction_deg, speed_kt, color)
        # ⊗ 風の小円 + 漢字 + hPa
        d.ellipse([x-7, y-7, x+7, y+7], outline=color, width=2)
        d.line([(x-7, y), (x+7, y)], fill=color, width=1)
        d.line([(x, y-7), (x, y+7)], fill=color, width=1)
        # 漢字を上にオフセット
        d.text((x+10, y-10), label, fill=color, font=font)
        if hPa is not None:
            d.text((x+10, y+10), f"{int(hPa)}", fill=color, font=font_small)

    for L in chart.get("lows", []):
        lat, lon = L.get("lat"), L.get("lon")
        if lat is None or lon is None:
            continue
        draw_center("低", lat, lon, L.get("hPa"), LOW_COLOR,
                    direction_deg=L.get("direction_deg"),
                    speed_kt=L.get("speed_value"))
    for H_ in chart.get("highs", []):
        lat, lon = H_.get("lat"), H_.get("lon")
        if lat is None or lon is None:
            continue
        draw_center("高", lat, lon, H_.get("hPa"), HIGH_COLOR,
                    direction_deg=H_.get("direction_deg"),
                    speed_kt=H_.get("speed_value"))
    for tl in chart.get("tropical_lows", []):
        lat, lon = tl.get("lat"), tl.get("lon")
        if lat is None or lon is None:
            continue
        draw_center("熱低", lat, lon, tl.get("hPa"), FRONT_COLORS["tropical_low"])
    for ty in chart.get("typhoons", []):
        lat, lon = ty.get("lat"), ty.get("lon")
        if lat is None or lon is None:
            continue
        draw_center("台", lat, lon, ty.get("hPa"), FRONT_COLORS["typhoon"])

    return canvas


def derive_t0_utc(chart, xml_path: Path) -> str:
    """XML の DateTime から t0 UTC 文字列 (YYYYMMDDhhmm00)"""
    dt_str = chart.get("report_at") or chart.get("valid_at")
    if dt_str:
        # ISO8601 to YYYYMMDDhhmm00
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            dt_utc = dt.astimezone(timezone.utc)
            return dt_utc.strftime("%Y%m%d%H%M00")
        except ValueError:
            pass
    # ファイル名から YYYYMMDDhhmm パターン
    import re
    m = re.search(r"(\d{14})", xml_path.stem)
    if m:
        return m.group(1)
    return "00000000000000"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("xml_path")
    p.add_argument("--area", default=None, help="地方コード 01-19、省略時は全地方")
    args = p.parse_args()

    xml = Path(args.xml_path)
    chart = parse_chart(xml)
    t0_utc = derive_t0_utc(chart, xml)
    dt = datetime.strptime(t0_utc, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) + timedelta(hours=9)

    print(f"chart_type: {chart['chart_type']}, title: {chart['title']}")
    print(f"valid_at: {chart['valid_at']}, report: {chart['report_at']}")
    print(f"  lows={len(chart['lows'])}, highs={len(chart['highs'])}, "
          f"fronts={len(chart['fronts'])}, isobars={len(chart['isobars'])}")
    print(f"saving overlays as wchart_{t0_utc}_a<XX>.png ...")

    codes = [args.area] if args.area else sorted(AREA_SLUGS.keys())  # "00" 全国も含める
    saved = []
    for code in codes:
        slug = AREA_SLUGS[code]
        img = render_for_area(chart, code)
        out_dir = Path(f"D:/jma_archive/forecast/{slug}/{dt.strftime('%Y/%m/%d')}")
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"wchart_{t0_utc}_a{code}.png"
        img.save(out)
        saved.append(out)
    print(f"saved {len(saved)} overlay images")
    if saved:
        print(f"  example: {saved[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
