#!/usr/bin/env python3
"""map_register.py — 緯度経度ラベル付き地図画像を登録、grid_points 入力の起点。

使い方:
    python map_register.py <image_path> <map_id> [--name NAME] [--source SOURCE]

例:
    python map_register.py D:/jma_archive/chart/japan/2026/04/25/spas_20260425_210000UTC.png \
        spas_jma --name "JMA SPAS 速報天気図" --source "気象庁"

処理:
    D:/dal_geodata/maps/<map_id>/ を作成
    - metadata.json (name, source, image_path, image_size, registered_at)
    - grid_points.json (空配列、Dal が後で埋める)
    - registry.json (D:/dal_geodata/maps/registry.json) に追記

次に: Dal が image を Read で観察、緯線・経線とラベル（30°N、150°E 等）を identify、
代表ピクセル座標を 4+ 点ピックアップ → map_set_grid_points.py で保存。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from PIL import Image
except ImportError:
    print("Pillow が必要", file=sys.stderr)
    sys.exit(1)

MAPS_DIR = Path("D:/dal_geodata/maps")
REGISTRY = MAPS_DIR / "registry.json"


def load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"maps": {}}


def save_registry(reg: dict):
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="緯度経度ラベル付き地図画像の登録")
    p.add_argument("image_path")
    p.add_argument("map_id", help="識別子（半角英数+_）")
    p.add_argument("--name", default=None)
    p.add_argument("--source", default=None)
    p.add_argument("--lon-range", default=None,
                   help="経度範囲 'min,max' (例 '100,170')。auto-assign 用")
    p.add_argument("--lon-step", type=float, default=None,
                   help="経線刻み (例 10)。auto-assign 用")
    p.add_argument("--lat-range", default=None,
                   help="緯度範囲 'min,max' (例 '10,50')")
    p.add_argument("--lat-step", type=float, default=None,
                   help="緯線刻み")
    p.add_argument("--color-filter", default=None,
                   help="格子線抽出用の HSV filter (例 '55,110,30,75,255,200' = 緑系)")
    args = p.parse_args()

    img_path = Path(args.image_path)
    if not img_path.exists():
        print(f"not found: {img_path}", file=sys.stderr)
        return 1

    map_dir = MAPS_DIR / args.map_id
    if map_dir.exists():
        print(f"already registered: {args.map_id} at {map_dir}", file=sys.stderr)
        print("update する場合は metadata.json / grid_points.json を直接 edit してください", file=sys.stderr)
        return 2

    map_dir.mkdir(parents=True)

    with Image.open(img_path) as im:
        w, h = im.size

    def parse_range(s):
        if s is None:
            return None
        parts = [float(v) for v in s.split(",")]
        if len(parts) != 2:
            raise ValueError(f"range は 'min,max': {s}")
        return parts

    metadata = {
        "map_id": args.map_id,
        "name": args.name or args.map_id,
        "source": args.source or "",
        "image_path": str(img_path).replace("\\", "/"),
        "image_size": [w, h],
        "registered_at": datetime.now().isoformat(timespec="seconds"),
        "lon_range": parse_range(args.lon_range),
        "lon_step": args.lon_step,
        "lat_range": parse_range(args.lat_range),
        "lat_step": args.lat_step,
        "color_filter": args.color_filter,
    }
    (map_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (map_dir / "grid_points.json").write_text("[]", encoding="utf-8")

    reg = load_registry()
    reg["maps"][args.map_id] = {
        "name": metadata["name"],
        "source": metadata["source"],
        "registered_at": metadata["registered_at"],
        "image_path": metadata["image_path"],
        "image_size": [w, h],
    }
    save_registry(reg)

    print(f"registered: {args.map_id}")
    print(f"  dir: {map_dir}")
    print(f"  image: {img_path} ({w}x{h})")
    print(f"  next: Read で画像観察 → grid_points を読み取り → map_set_grid_points.py で保存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
