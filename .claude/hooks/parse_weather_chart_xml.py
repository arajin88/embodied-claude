#!/usr/bin/env python3
"""parse_weather_chart_xml.py — 気象庁 防災情報 XML（VZSA50 / VZSF50 / VZSF51）を構造化 JSON に変換

入力: 天気図 XML ファイル
出力: 標準出力に JSON
  {
    "chart_type": "VZSA50",
    "title": "地上実況図",
    "valid_at": "2026-04-28T21:00:00+09:00",
    "report_at": "2026-04-28T20:09:08Z",
    "lows":   [{"hPa": 990, "lat": 42.2, "lon": 153.9, "movement": {"speed_kt": ..., "direction_deg": ...}}],
    "highs":  [...],
    "fronts": [{"type": "cold", "polyline": [[lat, lon], ...]}, ...],
    "isobars": [{"hPa": 1012, "polyline": [...]}]
  }

使い方:
    python parse_weather_chart_xml.py D:/jma_archive/maps/sample_VZSA50_20260428.xml
    python parse_weather_chart_xml.py <path> --pretty
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NS = {
    "jmx": "http://xml.kishou.go.jp/jmaxml1/",
    "ib": "http://xml.kishou.go.jp/jmaxml1/informationBasis1/",
    "body": "http://xml.kishou.go.jp/jmaxml1/body/meteorology1/",
    "eb": "http://xml.kishou.go.jp/jmaxml1/elementBasis1/",
}

# Type 文字列 → 内部分類
TYPE_MAP = {
    "等圧線": "isobar",
    "低気圧": "low",
    "高気圧": "high",
    "熱帯低気圧": "tropical_low",
    "台風": "typhoon",
    "寒冷前線": "front_cold",
    "温暖前線": "front_warm",
    "停滞前線": "front_stationary",
    "閉塞前線": "front_occluded",
}


def parse_line_coords(text: str) -> list[list[float]]:
    """`+57.28+115.10/+57.22+115.12/...` → [[lat, lon], ...]"""
    if not text:
        return []
    points = []
    for token in text.strip().split("/"):
        token = token.strip()
        if not token:
            continue
        # 形式: +/-NN.NN+/-NN.NN
        m = re.match(r"([+-]\d+\.?\d*)([+-]\d+\.?\d*)", token)
        if m:
            lat = float(m.group(1))
            lon = float(m.group(2))
            points.append([lat, lon])
    return points


def find_text(elem, *paths):
    """namespace 込みの相対 path を順に試して最初に見つかった text を返す"""
    for p in paths:
        e = elem.find(p, NS)
        if e is not None and e.text:
            return e.text.strip()
    return None


def find_attr(elem, path, attr):
    e = elem.find(path, NS)
    if e is not None:
        return e.get(attr)
    return None


def parse_chart(xml_path: Path) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Control / Head（namespace なし or jmx）
    title = None
    report_at = None
    chart_type = None
    for ctrl in root.iter():
        tag = ctrl.tag.split("}")[-1]
        if tag == "Title" and title is None:
            title = ctrl.text
        elif tag == "DateTime" and report_at is None:
            report_at = ctrl.text
        elif tag == "InfoType" and chart_type is None:
            chart_type = ctrl.text

    # ファイル名から chart_type 推定 (VZSA50 等)
    m = re.search(r"VZS[A-Z]\d+", str(xml_path))
    if m:
        chart_type = m.group(0)

    out = {
        "chart_type": chart_type,
        "title": title,
        "report_at": report_at,
        "valid_at": None,
        "lows": [],
        "highs": [],
        "tropical_lows": [],
        "typhoons": [],
        "fronts": [],
        "isobars": [],
    }

    # MeteorologicalInfo（複数 = 複数 valid time）
    for minfo in root.iter():
        tag = minfo.tag.split("}")[-1]
        if tag != "MeteorologicalInfo":
            continue
        # DateTime
        valid = None
        for child in minfo.iter():
            ct = child.tag.split("}")[-1]
            if ct == "DateTime" and valid is None:
                valid = child.text
                break
        if valid and out["valid_at"] is None:
            out["valid_at"] = valid

        # Item を全部まわる
        for item in minfo.iter():
            it = item.tag.split("}")[-1]
            if it != "Item":
                continue
            # Property（複数あり得る、Property/Type で分岐）
            for prop in item.iter():
                pt = prop.tag.split("}")[-1]
                if pt != "Property":
                    continue
                type_text = None
                for c in prop:
                    if c.tag.split("}")[-1] == "Type":
                        type_text = c.text
                        break
                category = TYPE_MAP.get(type_text)
                if not category:
                    continue
                entry = parse_property(prop, category, type_text, valid)
                if entry is None:
                    continue
                if category == "isobar":
                    out["isobars"].append(entry)
                elif category == "low":
                    out["lows"].append(entry)
                elif category == "high":
                    out["highs"].append(entry)
                elif category == "tropical_low":
                    out["tropical_lows"].append(entry)
                elif category == "typhoon":
                    out["typhoons"].append(entry)
                elif category.startswith("front"):
                    entry["type"] = category.replace("front_", "")
                    out["fronts"].append(entry)

    return out


def parse_property(prop, category: str, type_text: str, valid_at: str) -> dict | None:
    """Property element を分類別に dict 化"""
    entry = {"type_jp": type_text, "valid_at": valid_at}

    # 全 Line を集める
    polylines = []
    points = []
    pressures = []
    movements = []

    for child in prop.iter():
        tag = child.tag.split("}")[-1]
        if tag == "Line":
            # 「位置（度）」「前線（度）」など type 属性に依らず座標取れたら採用
            coords = parse_line_coords(child.text or "")
            if coords:
                polylines.append(coords)
        elif tag == "Coordinate":
            if child.text:
                pts = parse_line_coords(child.text)
                if pts:
                    points.extend(pts)
        elif tag == "Pressure":
            ptype = child.get("type", "")
            if child.text:
                try:
                    pressures.append((ptype, float(child.text)))
                except ValueError:
                    pass
        elif tag == "WindSpeed":
            speed_unit = child.get("unit", "")
            if child.text:
                try:
                    movements.append({"max_wind_speed": float(child.text), "unit": speed_unit})
                except ValueError:
                    pass
        elif tag == "Direction":
            if child.text:
                try:
                    entry["direction_deg"] = float(child.text)
                except ValueError:
                    pass
        elif tag == "Speed":
            if child.text:
                unit = child.get("unit", "")
                try:
                    entry["speed_value"] = float(child.text)
                    entry["speed_unit"] = unit
                except ValueError:
                    pass

    if pressures:
        # 「中心気圧」優先、次に「気圧」
        for ptype, pval in pressures:
            if "中心" in ptype:
                entry["hPa"] = pval
                break
        else:
            entry["hPa"] = pressures[0][1]

    if movements:
        entry["movement_extras"] = movements

    if polylines:
        entry["polyline"] = polylines[0] if len(polylines) == 1 else polylines
    if points:
        # Center 系は 1 点
        if category in ("low", "high", "tropical_low", "typhoon"):
            entry["lat"] = points[0][0]
            entry["lon"] = points[0][1]
        else:
            entry["points"] = points

    if not (polylines or points or pressures):
        return None
    return entry


def main() -> int:
    p = argparse.ArgumentParser(description="天気図 XML → 構造化 JSON")
    p.add_argument("xml_path")
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--summary", action="store_true",
                   help="JSON 出力せず件数サマリのみ")
    args = p.parse_args()

    xml = Path(args.xml_path)
    if not xml.exists():
        print(f"not found: {xml}", file=sys.stderr)
        return 1
    result = parse_chart(xml)

    if args.summary:
        print(f"chart_type: {result['chart_type']}")
        print(f"title:      {result['title']}")
        print(f"valid_at:   {result['valid_at']}")
        print(f"  lows:    {len(result['lows'])}")
        print(f"  highs:   {len(result['highs'])}")
        print(f"  trop_lows: {len(result['tropical_lows'])}")
        print(f"  typhoons:  {len(result['typhoons'])}")
        print(f"  fronts:    {len(result['fronts'])}")
        print(f"  isobars:   {len(result['isobars'])}")
        # 詳細サマリ
        if result["lows"]:
            print("  lows detail:")
            for L in result["lows"]:
                p = f"{L.get('hPa', '?')} hPa" if "hPa" in L else "?"
                pos = f"({L.get('lat', '?')}, {L.get('lon', '?')})"
                mv = ""
                if "direction_deg" in L:
                    mv = f"  → {int(L['direction_deg'])}°"
                    if "speed_value" in L:
                        mv += f" / {int(L['speed_value'])} {L.get('speed_unit', '')}"
                print(f"    {p} {pos}{mv}")
        if result["highs"]:
            print("  highs detail:")
            for H_ in result["highs"]:
                p = f"{H_.get('hPa', '?')} hPa" if "hPa" in H_ else "?"
                pos = f"({H_.get('lat', '?')}, {H_.get('lon', '?')})"
                mv = ""
                if "direction_deg" in H_:
                    mv = f"  → {int(H_['direction_deg'])}°"
                    if "speed_value" in H_:
                        mv += f" / {int(H_['speed_value'])} {H_.get('speed_unit', '')}"
                print(f"    {p} {pos}{mv}")
        if result["fronts"]:
            print("  fronts detail:")
            for f in result["fronts"]:
                pl = f.get("polyline", [])
                pts = pl if pl and isinstance(pl[0], list) and not isinstance(pl[0][0], list) else (pl[0] if pl else [])
                print(f"    {f['type']:<12} polyline n={len(pts)}")
        return 0

    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
