#!/usr/bin/env python3
"""build_border_extended.py — JMA border_aXX.png に Natural Earth coastline を合成。

JMA の border_aXX は日本の海岸線・行政境界のみで、朝鮮半島・台湾など周辺国の
coastline が含まれていない。地名なし radar で「形だけで地理を読む」訓練を
するには周辺国の輪郭が必要。

Natural Earth 10m coastline (public domain, ne_10m_coastline.shp) を region の
bbox で切り出し、JMA border に黒線で重ねて border_aXX_extended.png を保存。

使い方:
    python build_border_extended.py 12        # 九州北部だけ
    python build_border_extended.py 15        # 宮古・八重山だけ
    python build_border_extended.py all       # 全地方 (01..19)

出力: D:/jma_archive/maps/border_aXX_extended.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import shapefile
from PIL import Image, ImageDraw
from shapely.geometry import Point, shape
from shapely.ops import unary_union

COASTLINE_SHP = Path("D:/dal_geodata/coastline/ne_10m_coastline.shp")
BBOX_JSON = Path("D:/jma_archive/maps/region_bbox.json")
MAPS_DIR = Path("D:/jma_archive/maps")
PREF_GEOJSON = Path("D:/dal_geodata/prefecture/japan_prefectures.geojson")
JAPAN_BUFFER_DEG = 0.1  # ≈10km — JMA border と二重描画される日本側を除外


_japan_excl = None


def japan_exclusion_zone():
    """日本領土 + buffer（描画除外ゾーン）を返す。lazy-load。"""
    global _japan_excl
    if _japan_excl is None:
        data = json.loads(PREF_GEOJSON.read_text(encoding="utf-8"))
        polys = [shape(f["geometry"]) for f in data["features"]]
        _japan_excl = unary_union(polys).buffer(JAPAN_BUFFER_DEG)
    return _japan_excl


def lonlat_to_pixel(lon: float, lat: float, bbox: dict, w: int, h: int) -> tuple[float, float]:
    x = (lon - bbox["lon_min"]) / (bbox["lon_max"] - bbox["lon_min"]) * w
    y = (bbox["lat_max"] - lat) / (bbox["lat_max"] - bbox["lat_min"]) * h
    return x, y


def build_for_region(area_code: str, sf: shapefile.Reader, bbox_data: dict) -> Path | None:
    """1 area の border_extended.png を生成し path を返す。"""
    if area_code not in bbox_data["regions"]:
        print(f"  unknown area: {area_code}", file=sys.stderr)
        return None
    bbox = bbox_data["regions"][area_code]
    border_path = MAPS_DIR / f"border_a{area_code}.png"
    if not border_path.exists():
        print(f"  missing border: {border_path}", file=sys.stderr)
        return None

    base = Image.open(border_path).convert("LA")
    w, h = base.size
    lon0, lon1 = bbox["lon_min"], bbox["lon_max"]
    lat0, lat1 = bbox["lat_min"], bbox["lat_max"]

    overlay = Image.new("LA", (w, h), (0, 0))
    draw = ImageDraw.Draw(overlay)

    excl = japan_exclusion_zone()

    drawn_lines = 0
    skipped_in_japan = 0
    for sh in sf.shapes():
        bb = sh.bbox  # (lon_min, lat_min, lon_max, lat_max)
        if bb[2] < lon0 or bb[0] > lon1 or bb[3] < lat0 or bb[1] > lat1:
            continue
        parts = list(sh.parts) + [len(sh.points)]
        for i in range(len(parts) - 1):
            seg = sh.points[parts[i]:parts[i + 1]]
            if len(seg) < 2:
                continue
            # Japan + buffer に入る点は除外、外側の連続点だけを polyline 化
            cur: list[tuple[float, float]] = []
            for lon, lat in seg:
                if excl.contains(Point(lon, lat)):
                    if len(cur) >= 2:
                        pix = [lonlat_to_pixel(x, y, bbox, w, h) for x, y in cur]
                        draw.line(pix, fill=(0, 255), width=1)
                        drawn_lines += 1
                    cur = []
                    skipped_in_japan += 1
                else:
                    cur.append((lon, lat))
            if len(cur) >= 2:
                pix = [lonlat_to_pixel(x, y, bbox, w, h) for x, y in cur]
                draw.line(pix, fill=(0, 255), width=1)
                drawn_lines += 1

    # 既存 border に合成（黒線同士の上書きでも視覚は変わらない）
    base_rgba = base.convert("RGBA")
    overlay_rgba = overlay.convert("RGBA")
    out = Image.alpha_composite(base_rgba, overlay_rgba)
    out_path = MAPS_DIR / f"border_a{area_code}_extended.png"
    out.convert("LA").save(out_path)
    print(f"  a{area_code} ({bbox.get('name_ja', '?')}): drew {drawn_lines} segments, skipped {skipped_in_japan} pts inside Japan+buffer → {out_path.name}")
    return out_path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: build_border_extended.py <area_code|all>", file=sys.stderr)
        return 2

    if not COASTLINE_SHP.exists():
        print(f"coastline shp not found: {COASTLINE_SHP}", file=sys.stderr)
        return 1
    if not BBOX_JSON.exists():
        print(f"bbox json not found: {BBOX_JSON}", file=sys.stderr)
        return 1

    bbox_data = json.loads(BBOX_JSON.read_text(encoding="utf-8"))
    sf = shapefile.Reader(str(COASTLINE_SHP))
    print(f"loaded coastline: {len(sf.shapes())} shapes")

    arg = sys.argv[1]
    if arg == "all":
        for code in sorted(bbox_data["regions"].keys()):
            if code == "00":
                continue
            build_for_region(code, sf, bbox_data)
    else:
        build_for_region(arg, sf, bbox_data)

    return 0


if __name__ == "__main__":
    sys.exit(main())
