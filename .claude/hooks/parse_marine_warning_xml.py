#!/usr/bin/env python3
"""parse_marine_warning_xml.py — 全般海上警報 VPZU52 / 地方海上警報 VPCU51 を構造化 JSON へ

警報種別 Code:
  11 = 海上濃霧警報 [FOG]
  21 = 海上強風警報 [GW]
  22 = 海上暴風警報 [SW]
  23 = 海上台風警報 [TW]
  24 = 海上着氷警報 [HSS]

各 Item は警報種別 + Area:
  - Area.Code 9014 等の海域名指定（海域 polygon は別途辞書要）
  - Area の Polygon（緯度経度領域）
  - Area の Circle（中心 + 4方位非対称半径、影響範囲）
    BasePoint type ∈ {実況位置（度）, １２時間後位置（度）, ２４時間後位置（度）}

Body 側は MeteorologicalInfos type=全般海上警報 が複数、
各々が低気圧 / 前線情報、WindPart（最大風速）、Areas（影響範囲）持つ。

使い方:
    python parse_marine_warning_xml.py D:/jma_archive/maps/sample_VPZU52_20260428.xml --pretty
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

WARNING_LABELS = {
    "11": "海上濃霧警報",
    "21": "海上強風警報",
    "22": "海上暴風警報",
    "23": "海上台風警報",
    "24": "海上着氷警報",
}

DIRECTION_DEG = {  # ８方位漢字 → 度
    "北": 0, "北東": 45, "東": 90, "南東": 135,
    "南": 180, "南西": 225, "西": 270, "北西": 315,
}


def parse_coords(text: str) -> list[list[float]]:
    """+lat+lon/+lat+lon/... → [[lat, lon], ...]"""
    if not text:
        return []
    pts = []
    for tok in text.strip().split("/"):
        tok = tok.strip()
        if not tok:
            continue
        m = re.match(r"([+-]\d+\.?\d*)([+-]\d+\.?\d*)", tok)
        if m:
            pts.append([float(m.group(1)), float(m.group(2))])
    return pts


def get_local_tag(elem):
    return elem.tag.split("}")[-1]


def parse_circle(circle_elem) -> dict | None:
    """jmx_eb:Circle → {base_type, lat, lon, axes:[{dir, dir_deg, radius_nm}]}"""
    out = {"base_type": None, "lat": None, "lon": None, "axes": []}
    for child in circle_elem:
        ct = get_local_tag(child)
        if ct == "BasePoint":
            btype = child.get("type", "")
            pts = parse_coords(child.text or "")
            if pts:
                out["base_type"] = btype
                out["lat"], out["lon"] = pts[0]
            elif out["base_type"] is None:
                out["base_type"] = btype
        elif ct == "Axes":
            for axis in child:
                if get_local_tag(axis) != "Axis":
                    continue
                ax = {"direction": None, "direction_deg": None, "radius_nm": None}
                for sub in axis:
                    st = get_local_tag(sub)
                    if st == "Direction":
                        ax["direction"] = (sub.text or "").strip()
                        ax["direction_deg"] = DIRECTION_DEG.get(ax["direction"])
                    elif st == "Radius" and sub.text:
                        try:
                            ax["radius_nm"] = float(sub.text)
                        except ValueError:
                            pass
                out["axes"].append(ax)
    if out["base_type"] is None:
        return None
    return out


def parse_polygon(poly_elem) -> list[list[float]]:
    return parse_coords(poly_elem.text or "")


def parse_warning(item_elem) -> dict | None:
    """Headline 内 Item → {code, name, cause, areas:[]}"""
    code, name = None, None
    areas = []
    cur_area = None
    for child in item_elem.iter():
        tag = get_local_tag(child)
        if tag == "Kind":
            for sub in child:
                if get_local_tag(sub) == "Code" and sub.text:
                    code = sub.text.strip()
                elif get_local_tag(sub) == "Name" and sub.text:
                    name = sub.text.strip()
        elif tag == "Area":
            cur_area = {"name": None, "code": None, "circles": [], "polygon": None}
            areas.append(cur_area)
        elif cur_area is not None:
            if tag == "Name" and child.text:
                cur_area["name"] = child.text.strip()
            elif tag == "Code" and child.text:
                cur_area["code"] = child.text.strip()
            elif tag == "Circle":
                ctype = child.get("type", "")
                circle = parse_circle(child)
                if circle:
                    circle["type"] = ctype
                    cur_area["circles"].append(circle)
            elif tag == "Polygon":
                cur_area["polygon"] = parse_polygon(child)
    if code is None:
        return None
    return {"code": code, "name": name, "areas": areas}


def parse_body_info(meteo_info_elem) -> dict:
    """Body 内 MeteorologicalInfo → {warning_code, dt, low/front 情報}"""
    out = {
        "datetime": None,
        "warning_code": None,
        "warning_name": None,
        "wind_max_kt": None,
        "wind_warning_circle": None,  # 強風域 Circle
        "low": None,  # {lat, lon, hPa, dir, speed, location, condition}
        "fronts": [],  # [{type, polyline}]
        "areas": [],  # 影響範囲 Circles per area
    }
    for elem in meteo_info_elem.iter():
        tag = get_local_tag(elem)
        if tag == "DateTime" and out["datetime"] is None:
            out["datetime"] = elem.text
            break
    # Item 単位で再帰せず Kind/Area を直下走査
    item = None
    for c in meteo_info_elem:
        if get_local_tag(c) == "Item":
            item = c
            break
    if item is None:
        return out
    for kind in item:
        kt = get_local_tag(kind)
        if kt == "Kind":
            for sub in kind.iter():
                st = get_local_tag(sub)
                if st == "Code" and sub.text and out["warning_code"] is None:
                    out["warning_code"] = sub.text.strip()
                elif st == "Name" and sub.text and out["warning_name"] is None:
                    out["warning_name"] = sub.text.strip()
                elif st == "WindSpeed" and sub.get("type") == "最大風速" and sub.text:
                    try:
                        v = float(sub.text)
                        if out["wind_max_kt"] is None or v > out["wind_max_kt"]:
                            out["wind_max_kt"] = v
                    except ValueError:
                        pass
                elif st == "Coordinate" and sub.get("type") == "中心位置（度）":
                    pts = parse_coords(sub.text or "")
                    if pts:
                        out["low"] = out["low"] or {}
                        out["low"]["lat"] = pts[0][0]
                        out["low"]["lon"] = pts[0][1]
                elif st == "Pressure" and sub.get("type") == "中心気圧" and sub.text:
                    try:
                        out["low"] = out["low"] or {}
                        out["low"]["hPa"] = float(sub.text)
                    except ValueError:
                        pass
                elif st == "Speed" and sub.get("type") == "移動速度" and sub.text:
                    try:
                        out["low"] = out["low"] or {}
                        out["low"]["speed_kt"] = float(sub.text)
                    except ValueError:
                        pass
                elif st == "Direction" and sub.get("type") == "移動方向" and sub.text:
                    out["low"] = out["low"] or {}
                    out["low"]["direction"] = (sub.text or "").strip()
                elif st == "Location" and sub.text:
                    out["low"] = out["low"] or {}
                    out["low"]["location"] = sub.text.strip()
                elif st == "Condition" and sub.text:
                    out["low"] = out["low"] or {}
                    out["low"]["condition"] = sub.text.strip()
                elif st == "Line" and sub.get("type") == "位置（度）":
                    # 親 Property の Type を探す
                    parent = sub
                    # 雑だが OK：Type tag を search
                    pass
            # 前線は Property/Type で分岐
            for prop in kind.iter():
                if get_local_tag(prop) != "Property":
                    continue
                ptype = None
                line_pts = None
                for c2 in prop:
                    ct2 = get_local_tag(c2)
                    if ct2 == "Type" and c2.text:
                        ptype = c2.text.strip()
                    elif ct2 == "CoordinatePart":
                        for c3 in c2:
                            if get_local_tag(c3) == "Line" and c3.text:
                                line_pts = parse_coords(c3.text)
                if ptype in ("寒冷前線", "温暖前線", "停滞前線", "閉塞前線") and line_pts:
                    out["fronts"].append({"type": ptype, "polyline": line_pts})
        elif kt == "Area":
            area = {"name": None, "circles": []}
            for sub in kind.iter():
                st = get_local_tag(sub)
                if st == "Name" and sub.text:
                    area["name"] = sub.text.strip()
                elif st == "Circle":
                    ctype = sub.get("type", "")
                    circ = parse_circle(sub)
                    if circ:
                        circ["type"] = ctype
                        area["circles"].append(circ)
            out["areas"].append(area)
    return out


def parse_marine_warning(xml_path: Path) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Control / Head
    title = report_at = info_kind = target_dt = None
    for elem in root.iter():
        tag = get_local_tag(elem)
        if tag == "Title" and title is None:
            title = elem.text
        elif tag == "InfoKind" and info_kind is None:
            info_kind = elem.text
        elif tag == "ReportDateTime" and report_at is None:
            report_at = elem.text
        elif tag == "TargetDateTime" and target_dt is None:
            target_dt = elem.text

    out = {
        "title": title,
        "info_kind": info_kind,
        "report_at": report_at,    # XML が発表された時刻
        "target_at": target_dt,    # 警報の対象時刻（多くは発表時刻と同じ）
        "observation_at": None,    # 観測基準時刻（ASAS の valid_at と揃う、body 内 DateTime）
        "headline_warnings": [],
        "body_infos": [],
    }

    # Headline / Information / Item
    for elem in root.iter():
        if get_local_tag(elem) != "Information":
            continue
        for child in elem:
            if get_local_tag(child) == "Item":
                w = parse_warning(child)
                if w:
                    out["headline_warnings"].append(w)

    # Body / MeteorologicalInfos / MeteorologicalInfo
    for minfos in root.iter():
        if get_local_tag(minfos) != "MeteorologicalInfos":
            continue
        infos_type = minfos.get("type", "")
        for minfo in minfos:
            if get_local_tag(minfo) != "MeteorologicalInfo":
                continue
            info = parse_body_info(minfo)
            info["info_type"] = infos_type
            out["body_infos"].append(info)

    # observation_at: 警報 body の最初の DateTime（観測基準時刻、ASAS の valid_at と揃う）
    for b in out["body_infos"]:
        if b.get("warning_code") and b.get("datetime"):
            out["observation_at"] = b["datetime"]
            break
    if out["observation_at"] is None and out["body_infos"]:
        # フォールバック: 任意の body datetime
        for b in out["body_infos"]:
            if b.get("datetime"):
                out["observation_at"] = b["datetime"]
                break

    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("xml_path")
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--summary", action="store_true")
    args = p.parse_args()

    xml = Path(args.xml_path)
    result = parse_marine_warning(xml)

    if args.summary:
        print(f"title: {result['title']}")
        print(f"report_at: {result['report_at']}")
        print(f"target_at: {result['target_at']}")
        print(f"\nHeadline warnings: {len(result['headline_warnings'])}")
        for w in result["headline_warnings"]:
            print(f"  [{w['code']}] {w['name']}")
            for a in w["areas"]:
                if a.get("polygon"):
                    print(f"    polygon n={len(a['polygon'])} ({a.get('name')})")
                if a.get("circles"):
                    for c in a["circles"]:
                        if c.get("lat") is not None:
                            print(f"    circle ({c['base_type']}) lat={c['lat']:.1f} lon={c['lon']:.1f} axes={len(c['axes'])}")
                        else:
                            print(f"    circle ({c['base_type']}) [position pending]")
                if a.get("name") and not a.get("polygon") and not a.get("circles"):
                    print(f"    area: {a['name']} code={a.get('code')}")
        print(f"\nBody infos: {len(result['body_infos'])}")
        for b in result["body_infos"]:
            tag = f"[{b.get('warning_code')}] {b.get('warning_name')}" if b.get("warning_code") else b.get("info_type")
            extras = []
            if b.get("wind_max_kt"):
                extras.append(f"wind_max={int(b['wind_max_kt'])}kt")
            if b.get("low") and b["low"].get("hPa"):
                low = b["low"]
                extras.append(f"L {low.get('hPa')}hPa @{low.get('lat'):.1f},{low.get('lon'):.1f} {low.get('direction', '')} {low.get('speed_kt', '')}kt")
            if b.get("fronts"):
                extras.append(f"fronts={[f['type'] for f in b['fronts']]}")
            if extras:
                print(f"  {tag}: {' | '.join(extras)}")
            else:
                print(f"  {tag}")
        return 0

    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
