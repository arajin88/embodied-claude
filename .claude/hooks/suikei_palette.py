"""suikei_palette.py — JMA 推計気象分布 tile の RGB → 物理量/カテゴリ 変換表

各 element ごとに pixel level で **実測した** palette を集約。新 element を扱う時は
`fetch → tile sample → ここに追加 → render が参照` の順番（ground truth 鉄則 4/30）。

仮定で先に palette dict を埋めて render を書くと、mask が当たらず silent に空転する
（4/30 朝の (90,90,90) ND boundary 仮定事故）。新規 element の TEMP/SUNS1H placeholder は
明示的に raise させて、未実測のまま render 走るのを禁止する。
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# ============================================================================
# wthr — 天気（離散 5 カテゴリ + ND）
# ============================================================================
# 2026-04-29 23:00 basetime 全 192 tiles 横断 sample 結果（unique RGBA = 7）
WTHR_PALETTE: dict[tuple[int, int, int], str] = {
    (255, 170,   0): "sunny",   # 晴
    (170, 170, 170): "cloudy",  # 曇
    (  0,  65, 255): "rain",    # 雨
    (185, 235, 255): "sleet",   # みぞれ
    (242, 242, 255): "snow",    # 雪
}

# ND (alpha=0) 域の塗り色: 曇 (170,170,170) より少し濃い灰で区別 (papa 4/30 指示)
WTHR_ND_FILL: tuple[int, int, int] = (140, 140, 140)


def wthr_classify(rgb: tuple[int, int, int]) -> str:
    """RGB → 天気カテゴリ。未知色は 'unknown'。"""
    return WTHR_PALETTE.get(rgb, "unknown")


# ============================================================================
# temp — 気温 (8 段階の離散カラースケール、連続色じゃなかった)
# ============================================================================
# 2026-04-30 00:00 basetime 192 tiles 横断 sample 結果（unique RGBA = 10、内 2 つは透明）
# 寒色 4 + 暖色 4 段階。具体的な温度区間 (℃) は JMA 凡例で要確認 → ラベルだけ先に置く。
TEMP_PALETTE: dict[tuple[int, int, int], str] = {
    (  0,  32, 128): "very_cold",  # 紺
    (  0,  65, 255): "cold",       # 濃青
    (  0, 150, 255): "cool",       # 中青
    (185, 235, 255): "mild_cool",  # 水色
    (255, 255, 240): "neutral",    # 薄黄白（最頻）
    (255, 255, 150): "mild_warm",  # 薄黄
    (250, 245,   0): "warm",       # 黄
    (255, 153,   0): "hot",        # 橙
}
TEMP_ND_FILL: tuple[int, int, int] = (140, 140, 140)


def temp_label(rgb: tuple[int, int, int]) -> str:
    """RGB → 気温段階ラベル。未知色は 'unknown'。"""
    return TEMP_PALETTE.get(rgb, "unknown")


# ============================================================================
# suns1h — 1 時間日照時間（7 段階の離散カラースケール）
# ============================================================================
# 2026-04-30 00:00 basetime 192 tiles 横断 sample 結果（unique RGBA = 9、内 2 つは透明）
# 灰系 4 段階（暗→明、おそらく日照少ない側）+ 黄/橙/赤系 3 段階（日照多い側）。
# 具体的な値域 (h) は JMA 凡例で要確認 → ラベルだけ先に置く。
SUNS1H_PALETTE: dict[tuple[int, int, int], str] = {
    (120, 120, 120): "very_low",   # 暗灰
    (154, 154, 154): "low",        # 中灰
    (188, 188, 188): "medium_low", # 明灰
    (224, 224, 224): "medium",     # 薄灰
    (240, 230, 136): "medium_high",# 黄白
    (248, 176,   0): "high",       # 橙
    (244,  80,  56): "very_high",  # 赤橙
}
# suns1h は palette が灰系 4 段階を持つので、ND fill (140,140,140) は (120) と (154) の中間で衝突気味。
# とりあえず wthr と同じ値で start、papa 確認次第で別系統色に変える可能性あり。
SUNS1H_ND_FILL: tuple[int, int, int] = (140, 140, 140)


def suns1h_label(rgb: tuple[int, int, int]) -> str:
    """RGB → 日照段階ラベル。未知色は 'unknown'。"""
    return SUNS1H_PALETTE.get(rgb, "unknown")


# ============================================================================
# 共通: 透明 (alpha=0) 域を opaque で塗る
# ============================================================================
def apply_nd_fill(rgba_array: np.ndarray, fill_rgb: tuple[int, int, int]) -> np.ndarray:
    """alpha==0 の領域を fill_rgb で塗りつぶす（opaque 化、in-place）。

    JMA suikei tile では alpha=0 が ND（推計対象外＝海・海外）に対応。viewer の
    layer-stack 上で「曇り」と区別するため、element 毎の fill_rgb で再塗装する。
    """
    nd_mask = rgba_array[:, :, 3] == 0
    rgba_array[nd_mask, 0] = fill_rgb[0]
    rgba_array[nd_mask, 1] = fill_rgb[1]
    rgba_array[nd_mask, 2] = fill_rgb[2]
    rgba_array[nd_mask, 3] = 255
    return rgba_array


# ============================================================================
# element 名 → (palette, nd_fill) を返す dispatcher
# ============================================================================
ELEMENT_REGISTRY: dict[str, dict] = {
    "wthr":   {"palette": WTHR_PALETTE,   "nd_fill": WTHR_ND_FILL,   "kind": "categorical"},
    "temp":   {"palette": TEMP_PALETTE,   "nd_fill": TEMP_ND_FILL,   "kind": "categorical"},
    "suns1h": {"palette": SUNS1H_PALETTE, "nd_fill": SUNS1H_ND_FILL, "kind": "categorical"},
}


def get_nd_fill(element: str) -> tuple[int, int, int]:
    """element 名 → ND fill 色。未実測なら NotImplementedError。"""
    spec = ELEMENT_REGISTRY.get(element)
    if spec is None:
        raise ValueError(f"unknown element: {element}")
    fill = spec["nd_fill"]
    if fill is None:
        raise NotImplementedError(
            f"{element} の ND fill 色未決定。tile sample で実測後に suikei_palette.py を更新すること"
        )
    return fill


def is_palette_ready(element: str) -> bool:
    """element 名 → palette 実装済みか（render 前のガード用）"""
    spec = ELEMENT_REGISTRY.get(element)
    if spec is None:
        return False
    return spec["palette"] is not None
