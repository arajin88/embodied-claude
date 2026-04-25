#!/usr/bin/env python3
"""jma_radar_light_fetch.py - JMA 軽量版 雨雲ナウキャスト（radar_light）を取得・蓄積。

www.jma.go.jp/bosai/rain/rain.html の軽量版と同じ見た目（グレー地図＋雨雲）を再現。
- 地図: /bosai/rain/const/map/map_a{area}.png
- 境界: /bosai/rain/const/map/border_a{area}.png
- 雨雲: /bosai/rain/data/rain/{time}/rain_{time}_f00_a{area}.png
- 時刻: /bosai/rain/data/rain/time.json

使い方:
    python jma_radar_light_fetch.py                                   # sync モード default、全国、過去5日分の欠落を埋める
    python jma_radar_light_fetch.py --area 09                         # 関東ズームを sync
    python jma_radar_light_fetch.py --sync-hours 6                    # 過去6時間だけ sync
    python jma_radar_light_fetch.py --single HH:MM                    # 単発取得、HH:MM (JST)
    python jma_radar_light_fetch.py --single YYYYMMDDHHMMSS           # 単発取得、UTC 直接指定
    python jma_radar_light_fetch.py --area 13 \
      --start 202604221400 --end 202604221600                         # 範囲取得モード（JST 開始-終了）

sync モード:
    time.json の最新時刻から過去 --sync-hours 時間（デフォルト 120h = 5日、JMA archive 最大）を
    5分刻みで遡り、既存ファイルが無いスロットだけ取得する。スタンバイ後の復帰で空白を自動補填。

範囲取得モード（--start --end）:
    JST の開始-終了時刻指定で、その範囲の 5分刻み slot を取得。Discord 経由依頼の処理で使う。
    JMA archive は約 5 日上限なので、それより古い時刻は unavailable で skip される。

area 一覧（2026-04-25 時点、a00 〜 a19 の 20 個確認済み）:
    00 全国 / 09 関東地方
    残り 18 個は _jma_paths.py の AREA_DIR_MAP の placeholder で確認、Papa の visual review で finalize 予定

保存先: D:/jma_archive/radar_light/<area>/YYYY/MM/DD/radar_light_<JST時刻>.png
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow が必要: pip install pillow", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from _jma_paths import area_dir_name, get_save_dir  # noqa: E402

JST = timezone(timedelta(hours=9))
UTC = timezone.utc
USER_AGENT = "Mozilla/5.0 (dal-embodied-claude)"

MAP_URL_TMPL = "https://www.jma.go.jp/bosai/rain/const/map/map_a{area}.png"
BORDER_URL_TMPL = "https://www.jma.go.jp/bosai/rain/const/map/border_a{area}.png"
RAIN_URL_TMPL = "https://www.jma.go.jp/bosai/rain/data/rain/{time}/rain_{time}_f00_a{area}.png"
TIME_JSON_URL = "https://www.jma.go.jp/bosai/rain/data/rain/time.json"

AREA_NAMES = {
    "00": "全国",
    "01": "奄美地方",
    "02": "中国地方",
    "03": "大東島",
    "04": "北海道地方（東部）",
    "05": "北海道地方（北西部）",
    "06": "北海道地方（南西部）",
    "07": "北陸地方（東部）",
    "08": "北陸地方（西部）",
    "09": "関東地方",
    "10": "近畿地方",
    "11": "甲信地方",
    "12": "九州地方（北部）",
    "13": "九州地方（南部）",
    "14": "沖縄本島",
    "15": "宮古・八重山地方",
    "16": "四国地方",
    "17": "東北地方（北部）",
    "18": "東北地方（南部）",
    "19": "東海地方",
}

LEGEND_BINS = [
    ((242, 242, 255), "1"),
    ((160, 210, 255), "5"),
    ((33, 140, 255), "10"),
    ((0, 65, 255), "20"),
    ((255, 245, 0), "30"),
    ((255, 153, 0), "50"),
    ((255, 40, 0), "80"),
    ((180, 0, 104), ""),
]
LEGEND_UNIT = "mm/h"

JP_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
]


def load_jp_font(size: int):
    for path in JP_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def annotate(canvas: Image.Image, caption: str, position: str = "top-left") -> Image.Image:
    """caption と rain intensity legend を描画する。position: top-left / bottom-right。"""
    draw = ImageDraw.Draw(canvas)
    caption_font = load_jp_font(18)
    legend_font = load_jp_font(13)
    pad = 4
    block_w, block_h = 28, 14
    legend_total_w = block_w * len(LEGEND_BINS) + 40
    legend_total_h = block_h + 20

    cap_bbox = draw.textbbox((0, 0), caption, font=caption_font)
    cap_w = cap_bbox[2] - cap_bbox[0]
    cap_h = cap_bbox[3] - cap_bbox[1]

    if position == "bottom-right":
        margin = 10
        canvas_w, canvas_h = canvas.size
        block_right = canvas_w - margin
        block_bottom = canvas_h - margin
        legend_x0 = block_right - legend_total_w
        legend_y0 = block_bottom - legend_total_h
        x0 = block_right - cap_w
        y0 = legend_y0 - pad * 2 - cap_h - 4
    else:
        x0, y0 = 10, 8
        legend_x0 = x0
        legend_y0 = y0 + cap_h + pad * 2 + 4

    draw.rectangle(
        (x0 - pad, y0 - pad, x0 + cap_w + pad, y0 + cap_h + pad),
        fill=(255, 255, 255, 220),
    )
    draw.text((x0, y0), caption, fill=(0, 0, 0), font=caption_font)

    draw.rectangle(
        (legend_x0 - pad, legend_y0 - pad,
         legend_x0 + legend_total_w + pad, legend_y0 + legend_total_h),
        fill=(255, 255, 255, 220),
    )
    for i, (rgb, label) in enumerate(LEGEND_BINS):
        bx = legend_x0 + i * block_w
        draw.rectangle((bx, legend_y0, bx + block_w, legend_y0 + block_h), fill=rgb)
        if label:
            tw = draw.textlength(label, font=legend_font)
            draw.text((bx + block_w - tw / 2, legend_y0 + block_h + 2),
                      label, fill=(0, 0, 0), font=legend_font)
    draw.text((legend_x0 + len(LEGEND_BINS) * block_w + 4, legend_y0 + block_h + 2),
              LEGEND_UNIT, fill=(0, 0, 0), font=legend_font)

    return canvas


def fetch_bytes(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_image(url: str) -> Image.Image:
    return Image.open(BytesIO(fetch_bytes(url))).convert("RGBA")


def get_border_image(area: str) -> Image.Image:
    """border を取得。`D:/jma_archive/maps/border_a{area}_extended.png` が
    あれば優先（a12=九州北部に朝鮮半島、a15=宮古八重山に台湾を含む拡張版）。
    無ければ JMA から fetch。"""
    from pathlib import Path as _P
    ext = _P(f"D:/jma_archive/maps/border_a{area}_extended.png")
    if ext.exists():
        return Image.open(ext).convert("RGBA")
    return fetch_image(BORDER_URL_TMPL.format(area=area))


def expected_save_path(vt_utc: datetime, area: str):
    vt_jst = vt_utc.astimezone(JST)
    save_dir = get_save_dir("radar_light", vt_jst, area_code=area)
    ts = vt_jst.strftime('%Y%m%d_%H%M%S')
    # area=00 (全国 / japan) は cron が既存名で書き込んでるので変えない。
    # 他地域はフォルダ間の同名衝突を防ぐため地域名を含める。
    if area == "00":
        out_name = f"radar_light_{ts}JST.png"
    else:
        out_name = f"radar_light_{area_dir_name(area)}_{ts}JST.png"
    return save_dir / out_name


def try_fetch_rain(vt_utc: datetime, area: str) -> Image.Image | None:
    """その時刻の rain PNG を取得。404 等は None。"""
    time_str = vt_utc.strftime("%Y%m%d%H%M%S")
    url = RAIN_URL_TMPL.format(time=time_str, area=area)
    try:
        data = fetch_bytes(url, timeout=8)
        return Image.open(BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def compose_and_save(vt_utc: datetime, area: str, base_map: Image.Image,
                    border: Image.Image, rain: Image.Image):
    """地名なし 3層合成 → caption/legend → palette 保存。

    地名 anchor 排除のため base_map（地名あり）は使わず、border の輪郭線で
    陸海を識別、灰色背景 (160,160,160) で雨雲の階調を視認可能にする。
    """
    bg = Image.new("RGBA", rain.size, (160, 160, 160, 255))
    canvas = Image.alpha_composite(bg, rain)
    canvas = Image.alpha_composite(canvas, border)

    vt_jst = vt_utc.astimezone(JST)
    area_label = AREA_NAMES.get(area, f"a{area}")
    caption = f"{area_label} {vt_jst.strftime('%Y/%m/%d %H:%M')} 実況"
    # 凡例位置: 全国(00) と、地図右下に陸地・島が描かれる地域は左上配置で被り回避。
    # 02=中国, 07=北陸東部, 08=北陸西部, 12=九州北部, 15=宮古八重山
    top_left_areas = {"00", "02", "07", "08", "12", "15"}
    position = "top-left" if area in top_left_areas else "bottom-right"
    canvas = annotate(canvas, caption, position=position)

    out_path = expected_save_path(vt_utc, area)
    # atomic save: .tmp に書いて rename。途中 crash でも 0-byte 本体が残らない
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    try:
        canvas.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=256).save(
            tmp_path, format="PNG", optimize=True
        )
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return out_path


def sync_missing(area: str, hours_back: float) -> tuple[int, int, int]:
    """過去 hours_back 時間の欠落スロットを埋める。

    Returns: (fetched, skipped, unavailable)
    """
    # 地図・境界は全スロットで共通、1回だけ取得
    base_map = fetch_image(MAP_URL_TMPL.format(area=area))
    border = get_border_image(area)

    # 最新 valid time
    data = json.loads(fetch_bytes(TIME_JSON_URL, timeout=10))
    latest = datetime.fromisoformat(data["time"]).astimezone(UTC)
    # 5分刻みに floor
    latest = latest.replace(second=0, microsecond=0)
    latest = latest.replace(minute=(latest.minute // 5) * 5)

    cursor = latest
    end = latest - timedelta(hours=hours_back)
    fetched = skipped = unavailable = 0

    while cursor >= end:
        try:
            out_path = expected_save_path(cursor, area)
            # size > 0 のみ「既存」として skip。0-byte 残骸は消して再取得
            if out_path.exists() and out_path.stat().st_size > 0:
                skipped += 1
            else:
                if out_path.exists():
                    out_path.unlink()
                rain = try_fetch_rain(cursor, area)
                if rain is None:
                    unavailable += 1
                else:
                    compose_and_save(cursor, area, base_map, border, rain)
                    fetched += 1
        except Exception as e:
            # 1 slot の例外で sync 全体を止めない
            print(f"slot {cursor} failed: {e}", file=sys.stderr)
            unavailable += 1
        cursor -= timedelta(minutes=5)

    return fetched, skipped, unavailable


def range_fetch(area: str, start_jst: datetime, end_jst: datetime) -> tuple[int, int, int]:
    """[start_jst, end_jst] の 5分刻みスロットを埋める。Both bounds inclusive.

    Returns: (fetched, skipped, unavailable)
    """
    base_map = fetch_image(MAP_URL_TMPL.format(area=area))
    border = get_border_image(area)

    # JST → UTC、5分 floor
    start_utc = start_jst.astimezone(UTC).replace(second=0, microsecond=0)
    start_utc = start_utc.replace(minute=(start_utc.minute // 5) * 5)
    end_utc = end_jst.astimezone(UTC).replace(second=0, microsecond=0)
    end_utc = end_utc.replace(minute=(end_utc.minute // 5) * 5)

    cursor = start_utc
    fetched = skipped = unavailable = 0
    while cursor <= end_utc:
        try:
            out_path = expected_save_path(cursor, area)
            if out_path.exists() and out_path.stat().st_size > 0:
                skipped += 1
            else:
                if out_path.exists():
                    out_path.unlink()
                rain = try_fetch_rain(cursor, area)
                if rain is None:
                    unavailable += 1
                else:
                    compose_and_save(cursor, area, base_map, border, rain)
                    fetched += 1
        except Exception as e:
            print(f"slot {cursor} failed: {e}", file=sys.stderr)
            unavailable += 1
        cursor += timedelta(minutes=5)

    return fetched, skipped, unavailable


def resolve_single_target_utc(arg: str) -> datetime:
    if ":" in arg:
        h_str, m_str = arg.split(":")
        now_jst = datetime.now(JST)
        target_jst = now_jst.replace(hour=int(h_str), minute=int(m_str), second=0, microsecond=0)
        if target_jst > now_jst:
            target_jst -= timedelta(days=1)
        return target_jst.astimezone(UTC)
    return datetime.strptime(arg, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def find_closest_time(target_utc: datetime, area: str) -> datetime:
    """5分刻み で target に最も近い時刻。±20分までフォールバック。"""
    minutes = (target_utc.minute // 5) * 5
    rounded = target_utc.replace(minute=minutes, second=0, microsecond=0)
    for offset in [0, -5, 5, -10, 10, -15, 15, -20, 20]:
        t = rounded + timedelta(minutes=offset)
        if try_fetch_rain(t, area) is not None:
            return t
    raise RuntimeError(f"no rain image found within 20min of {target_utc}")


def single_fetch(arg: str, area: str) -> int:
    try:
        target_utc = resolve_single_target_utc(arg)
        vt_utc = find_closest_time(target_utc, area)
        base_map = fetch_image(MAP_URL_TMPL.format(area=area))
        border = get_border_image(area)
        rain = try_fetch_rain(vt_utc, area)
        if rain is None:
            print(f"rain layer fetch failed for {vt_utc}", file=sys.stderr)
            return 1
        out_path = compose_and_save(vt_utc, area, base_map, border, rain)
    except Exception as e:
        print(f"single fetch 失敗: {e}", file=sys.stderr)
        return 1
    print(str(out_path))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="JMA 軽量版 雨雲ナウキャストの取得・蓄積")
    parser.add_argument("--area", default="00", help="エリアコード（00=全国, 09=関東 など）")
    parser.add_argument("--sync-hours", type=float, default=120.0,
                        help="sync モードの遡及時間（h）。デフォルト 120h = 5日（JMA archive 最大）")
    parser.add_argument("--single", metavar="TIME",
                        help="単発取得モード。HH:MM (JST) または YYYYMMDDHHMMSS (UTC)")
    parser.add_argument("--start", metavar="YYYYMMDDHHMM",
                        help="範囲取得モード開始時刻 (JST)、--end と併用")
    parser.add_argument("--end", metavar="YYYYMMDDHHMM",
                        help="範囲取得モード終了時刻 (JST)、--start と併用")
    args = parser.parse_args()
    area = args.area.zfill(2)

    if args.single:
        return single_fetch(args.single, area)

    # 範囲取得モード
    if args.start or args.end:
        if not (args.start and args.end):
            print("--start と --end は両方指定してください", file=sys.stderr)
            return 2
        try:
            start_jst = datetime.strptime(args.start, "%Y%m%d%H%M").replace(tzinfo=JST)
            end_jst = datetime.strptime(args.end, "%Y%m%d%H%M").replace(tzinfo=JST)
        except ValueError as e:
            print(f"--start/--end は YYYYMMDDHHMM 形式: {e}", file=sys.stderr)
            return 2
        if start_jst > end_jst:
            print("--start は --end より前", file=sys.stderr)
            return 2
        try:
            fetched, skipped, unavail = range_fetch(area, start_jst, end_jst)
        except Exception as e:
            print(f"range fetch 失敗: {e}", file=sys.stderr)
            return 1
        total = fetched + skipped + unavail
        print(
            f"range area={area} {args.start}-{args.end} JST total_slots={total} "
            f"fetched={fetched} skipped={skipped} unavailable={unavail}",
            file=sys.stderr,
        )
        return 0

    # default: sync mode
    try:
        fetched, skipped, unavail = sync_missing(area, args.sync_hours)
    except Exception as e:
        print(f"sync 失敗: {e}", file=sys.stderr)
        return 1

    total = fetched + skipped + unavail
    print(
        f"sync area={area} hours={args.sync_hours} total_slots={total} "
        f"fetched={fetched} skipped={skipped} unavailable={unavail}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
