#!/usr/bin/env python3
"""render_suikei_overlay.py — 推計気象分布 tile を a00 (japan) view に貼り合わせ

入力: D:/jma_archive/suikei/{element}/{basetime}/{z}/{x}_{y}.png （fetch_suikei.py 出力）
出力: D:/jma_archive/forecast/japan/<YYYY/MM/DD>/suikei_<element>_<basetime>_a00.png

a00 view (940x783, linear cylindrical bbox) に WM XYZ tile を投影。
JMA z=N の tile は WM z=(N-1) の x/y を使う。

palette PNG をそのまま read → a00 サイズ canvas に projection で paste。

使い方:
    python render_suikei_overlay.py --element wthr
    python render_suikei_overlay.py --element wthr --basetime 20260429220000 --z 8
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image

SUIKEI_ROOT = Path("D:/jma_archive/suikei")
FORECAST_ROOT = Path("D:/jma_archive/forecast")
BBOX_PATH = Path("D:/jma_archive/maps/region_bbox.json")

# a00 (japan) bbox 読み込み
bbox_data = json.loads(BBOX_PATH.read_text(encoding="utf-8"))["regions"]
A00 = bbox_data["00"]
W, H = 940, 783


def wm_tile_to_latlon(x: int, y: int, wm_z: int) -> tuple[float, float, float, float]:
    """WM tile 座標 → bbox (lat_max, lon_min, lat_min, lon_max)"""
    n = 2 ** wm_z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    # y=0 が北極側、y増加で南
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lat_max, lon_min, lat_min, lon_max


def latlon_to_a00_xy(lat: float, lon: float) -> tuple[float, float]:
    x = (lon - A00["lon_min"]) / (A00["lon_max"] - A00["lon_min"]) * W
    y = (A00["lat_max"] - lat) / (A00["lat_max"] - A00["lat_min"]) * H
    return x, y


def render(element: str, basetime: str, jma_z: int) -> Path | None:
    tile_dir = SUIKEI_ROOT / element / basetime / str(jma_z)
    if not tile_dir.exists():
        print(f"tile dir missing: {tile_dir}", file=sys.stderr)
        return None

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wm_z = jma_z - 1

    # 全 tile の x, y 集合を集めて、各境界の a00 pixel 位置を pre-compute
    # （隣接 tile を独立に round すると 1 px gap が出るので、共通 pixel grid で連続化）
    tiles = []
    for png in sorted(tile_dir.glob("*.png")):
        try:
            x_str, y_str = png.stem.split("_")
            tx, ty = int(x_str), int(y_str)
        except ValueError:
            continue
        tiles.append((tx, ty, png))
    if not tiles:
        return None

    xs = sorted(set(t[0] for t in tiles))
    ys = sorted(set(t[1] for t in tiles))
    # 境界 (n+1 個) を pixel 位置にマップ（上端は tile x、下端は次 tile x+1）
    n = 2 ** wm_z
    def x_boundary_to_lon(tx_):
        return tx_ / n * 360.0 - 180.0
    def y_boundary_to_lat(ty_):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty_ / n))))

    x_px = {tx: int(round(latlon_to_a00_xy(0, x_boundary_to_lon(tx))[0])) for tx in xs + [xs[-1] + 1]}
    y_px = {ty: int(round(latlon_to_a00_xy(y_boundary_to_lat(ty), 0)[1])) for ty in ys + [ys[-1] + 1]}

    n_paste = 0
    for tx, ty, png in tiles:
        x_l = x_px[tx]
        x_r = x_px[tx + 1]
        y_t = y_px[ty]
        y_b = y_px[ty + 1]
        target_w = max(1, x_r - x_l)
        target_h = max(1, y_b - y_t)
        if x_r < 0 or x_l > W or y_b < 0 or y_t > H:
            continue
        tile_img = Image.open(png).convert("RGBA")
        tile_resized = tile_img.resize((target_w, target_h), Image.NEAREST)
        canvas.paste(tile_resized, (x_l, y_t), tile_resized)
        n_paste += 1

    # JST date for output path
    dt_utc = datetime.strptime(basetime, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    dt_jst = dt_utc + timedelta(hours=9)
    out_dir = FORECAST_ROOT / "japan" / dt_jst.strftime("%Y/%m/%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"suikei_{element}_{basetime}_a00.png"
    canvas.save(out_path)
    print(f"  rendered {n_paste} tiles → {out_path}")
    return out_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--element", default="wthr")
    p.add_argument("--basetime", default=None, help="省略時は SUIKEI_ROOT/{element}/ 最新")
    p.add_argument("--z", type=int, default=8)
    args = p.parse_args()

    basetime = args.basetime
    if not basetime:
        # 最新 basetime を ARCHIVE から取得
        elem_dir = SUIKEI_ROOT / args.element
        if not elem_dir.exists():
            print(f"no archive: {elem_dir}", file=sys.stderr)
            return 1
        bt_dirs = sorted([d for d in elem_dir.iterdir() if d.is_dir()])
        if not bt_dirs:
            return 1
        basetime = bt_dirs[-1].name

    print(f"render element={args.element}, basetime={basetime}, z={args.z}")
    out = render(args.element, basetime, args.z)
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
