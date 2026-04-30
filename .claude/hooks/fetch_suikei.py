#!/usr/bin/env python3
"""fetch_suikei.py — JMA 推計気象分布タイル取得

仕様（papa 4/30 確認の URL から逆解読）:
  URL: https://www.jma.go.jp/bosai/jmatile/data/suikeikishou/{basetime}/none/{validtime}/surf/{element}/{z}/{x}/{y}.png
  - basetime == validtime（実況のみ、forecast なし）
  - elements: wthr (天気), temp (気温), suns1h (日照時間)
  - z: 4-12 (even のみ raster あり、maxNativeZoom=10)
  - tileSize: 512x512、palette indexed PNG
  - **JMA z=N の x/y は Web Mercator z=(N-1) で計算**（tileSize=512 のため 1 zoom shift）
  - basetime は targetTimes.json 最新の 1 時間毎更新
  - 過去 47 時間ぶん保持

保存先: D:/jma_archive/suikei/{element}/{basetime}/{z}/{x}_{y}.png

使い方:
    python fetch_suikei.py                              # 最新 basetime / wthr / z=8 で日本範囲一括
    python fetch_suikei.py --z 8 --elem wthr temp
    python fetch_suikei.py --basetime 20260429220000    # 特定 basetime
    python fetch_suikei.py --backfill                   # targetTimes 47 件全 scan、既存 skip
    python fetch_suikei.py --render                     # fetch 後に render + chart_index 更新
    python fetch_suikei.py --backfill --render          # 完全自動運用 (cron 用)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ARCHIVE_ROOT = Path("D:/jma_archive/suikei")
TARGETTIMES_URL = "https://www.jma.go.jp/bosai/jmatile/data/suikeikishou/targetTimes.json"
TILE_URL_TMPL = "https://www.jma.go.jp/bosai/jmatile/data/suikeikishou/{basetime}/none/{validtime}/surf/{element}/{z}/{x}/{y}.png"
USER_AGENT = "Mozilla/5.0 (dal-embodied-claude)"

# 日本範囲 bbox (a00 と同じ範囲)
JAPAN_BBOX = {
    "lat_min": 21.4, "lat_max": 46.6,
    "lon_min": 114.7, "lon_max": 155.3,
}


def http_get(url: str, timeout: int = 15) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        print(f"  fail {url}: {type(e).__name__}", file=sys.stderr)
        return None


def latlon_to_wm_tile(lat: float, lon: float, wm_z: int) -> tuple[int, int]:
    """Web Mercator XYZ tile 座標を計算"""
    n = 2 ** wm_z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def jma_tile_range(jma_z: int, bbox: dict = JAPAN_BBOX) -> list[tuple[int, int]]:
    """JMA z での tile 座標範囲を返す（x/y は WM z=jma_z-1 で計算）"""
    wm_z = jma_z - 1
    # NW corner (lat_max, lon_min) → (x_min, y_min)
    x_min, y_min = latlon_to_wm_tile(bbox["lat_max"], bbox["lon_min"], wm_z)
    # SE corner (lat_min, lon_max) → (x_max, y_max)
    x_max, y_max = latlon_to_wm_tile(bbox["lat_min"], bbox["lon_max"], wm_z)
    return [(x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)]


def get_latest_basetime() -> str | None:
    data = http_get(TARGETTIMES_URL)
    if not data:
        return None
    try:
        info = json.loads(data)
        return info[0]["basetime"]  # 最新は先頭
    except Exception as e:
        print(f"targetTimes parse fail: {e}", file=sys.stderr)
        return None


def get_all_basetimes() -> list[str]:
    """targetTimes.json から全 basetime list を返す（最新 → 古い 順）"""
    data = http_get(TARGETTIMES_URL)
    if not data:
        return []
    try:
        info = json.loads(data)
        return [e["basetime"] for e in info if "basetime" in e]
    except Exception:
        return []


def fetch_tile(element: str, basetime: str, z: int, x: int, y: int, force: bool = False) -> bool:
    out_dir = ARCHIVE_ROOT / element / basetime / str(z)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{x}_{y}.png"
    if out_path.exists() and not force:
        return True
    url = TILE_URL_TMPL.format(basetime=basetime, validtime=basetime, element=element, z=z, x=x, y=y)
    data = http_get(url)
    if data is None:
        return False
    out_path.write_bytes(data)
    return True


def fetch_one_basetime(basetime: str, z: int, elements: list[str], force: bool) -> dict[str, int]:
    """1 basetime ぶんを全 element fetch、{element: new_count} を返す"""
    tiles = jma_tile_range(z)
    counts = {}
    for elem in elements:
        new = 0
        for x, y in tiles:
            out_path = ARCHIVE_ROOT / elem / basetime / str(z) / f"{x}_{y}.png"
            if out_path.exists() and not force:
                continue
            if fetch_tile(elem, basetime, z, x, y, force=force):
                new += 1
        counts[elem] = new
    return counts


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--basetime", default=None, help="basetime YYYYMMDDhhmm00 (UTC)、省略時は最新")
    p.add_argument("--z", type=int, default=8, help="JMA zoom level (even: 4/6/8/10、default 8)")
    p.add_argument("--elem", nargs="+", default=["wthr"], help="element id（wthr / temp / suns1h）")
    p.add_argument("--force", action="store_true")
    p.add_argument("--backfill", action="store_true",
                   help="targetTimes 47 件全 scan、既存 skip")
    p.add_argument("--render", action="store_true",
                   help="fetch 後 render_suikei_overlay.py + build_chart_index.py 自動実行")
    args = p.parse_args()

    if args.z % 2 != 0 or args.z < 4 or args.z > 10:
        print(f"warn: JMA suikei は z=4/6/8/10 even のみ raster あり、{args.z} は noisy fallback", file=sys.stderr)

    # basetime list 決定
    if args.backfill:
        basetimes = get_all_basetimes()
        print(f"backfill mode: targetTimes 取得 {len(basetimes)} 件")
    else:
        bt = args.basetime or get_latest_basetime()
        if not bt:
            print("basetime 取得失敗", file=sys.stderr)
            return 1
        basetimes = [bt]

    # fetch
    new_basetimes = []  # 新規 fetch あった basetime のみ render 対象
    for bt in basetimes:
        counts = fetch_one_basetime(bt, args.z, args.elem, args.force)
        total_new = sum(counts.values())
        if total_new > 0 or args.force:
            new_basetimes.append(bt)
            print(f"  {bt}: {counts}")

    if not args.render:
        return 0

    # render 段
    import subprocess
    HOOKS = Path(__file__).parent
    PYEXE = sys.executable

    rendered = 0
    for bt in new_basetimes:
        for elem in args.elem:
            cmd = [PYEXE, str(HOOKS / "render_suikei_overlay.py"),
                   "--element", elem, "--basetime", bt, "--z", str(args.z)]
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            if r.returncode == 0:
                rendered += 1
            else:
                print(f"  render fail {elem}/{bt}: {r.stderr}", file=sys.stderr)

    if rendered > 0:
        print(f"rendered {rendered} suikei mosaics")
        # index update
        cmd = [PYEXE, str(HOOKS / "build_chart_index.py")]
        subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        print("  chart_index updated")

    return 0


if __name__ == "__main__":
    sys.exit(main())
