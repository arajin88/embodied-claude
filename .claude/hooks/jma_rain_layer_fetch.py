#!/usr/bin/env python3
"""jma_rain_layer_fetch.py — JMA bosai/rain の rain layer (素材 PNG) のみ取得。

合成済み画像（jma_radar_light_fetch.py）と並列に、素材 layer を保存する。
palette indexed PNG（mode=P）で alpha blend 劣化なく原色保存される、数値解析向き。

URL:
    https://www.jma.go.jp/bosai/rain/data/rain/{time_utc}/rain_{time_utc}_f00_a{area}.png
    time_utc = YYYYMMDDhhmm00 (UTC)。最新時刻は time.json から取得。

保存先:
    D:/jma_archive/radar_layers/rain/{area_name}/YYYY/MM/DD/rain_{time_utc}_a{area}.png
    area_name は jma_radar_light_fetch.py の AREA_NAMES 系統と同じ key（japan, kanto 等）。

使い方:
    python jma_rain_layer_fetch.py                # 全 20 area の最新を一括取得
    python jma_rain_layer_fetch.py 09             # 関東のみ
    python jma_rain_layer_fetch.py 00 --time 20260428044500  # 過去時刻
    python jma_rain_layer_fetch.py 00 --auto-backfill         # japan 最新 + 過去12h gap 自動補完
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

USER_AGENT = "Mozilla/5.0 (dal-embodied-claude)"
TIME_JSON_URL = "https://www.jma.go.jp/bosai/rain/data/rain/time.json"
RAIN_URL_TMPL = "https://www.jma.go.jp/bosai/rain/data/rain/{time}/rain_{time}_f00_a{area}.png"
ARCHIVE_ROOT = Path("D:/jma_archive/radar_layers/rain")
COVERAGE_STATE_PATH = Path("D:/jma_archive/.coverage_state.json")
RETENTION_HOURS = 120  # JMA bosai/rain server side retention (~5 days)

# AREA name 命名は jma_radar_light_fetch.py と同じ slug を使用
AREA_SLUGS = {
    "00": "japan",
    "01": "amami",
    "02": "chugoku",
    "03": "daito",
    "04": "hokkaido_east",
    "05": "hokkaido_northwest",
    "06": "hokkaido_southwest",
    "07": "hokuriku_east",
    "08": "hokuriku_west",
    "09": "kanto",
    "10": "kinki",
    "11": "koushin",
    "12": "kyushu_north",
    "13": "kyushu_south",
    "14": "okinawa_main",
    "15": "miyako_yaeyama",
    "16": "shikoku",
    "17": "tohoku_north",
    "18": "tohoku_south",
    "19": "tokai",
}


def http_get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def latest_time_utc() -> str:
    """time.json の ISO8601 (UTC) を YYYYMMDDhhmm00 形式に。"""
    info = json.loads(http_get(TIME_JSON_URL))
    iso = info["time"]  # 例: "2026-04-28T04:45:00+00:00"
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y%m%d%H%M00")


def utc_to_jst_path(time_utc: str) -> tuple[str, str, str]:
    """time_utc (YYYYMMDDhhmm00) を JST の YYYY, MM, DD に。"""
    dt = datetime.strptime(time_utc, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    # JST = UTC+9
    from datetime import timedelta
    jst = dt + timedelta(hours=9)
    return jst.strftime("%Y"), jst.strftime("%m"), jst.strftime("%d")


def fetch_one(area_code: str, time_utc: str, force: bool = False) -> int:
    slug = AREA_SLUGS.get(area_code)
    if slug is None:
        print(f"unknown area code: a{area_code}", file=sys.stderr)
        return 1
    yyyy, mm, dd = utc_to_jst_path(time_utc)
    out_dir = ARCHIVE_ROOT / slug / yyyy / mm / dd
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"rain_{time_utc}_a{area_code}.png"
    if out_path.exists() and not force:
        print(f"  skip {area_code}/{slug} (exists)")
        return 0

    url = RAIN_URL_TMPL.format(time=time_utc, area=area_code)
    try:
        data = http_get(url)
    except Exception as e:
        print(f"  fail a{area_code}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    out_path.write_bytes(data)
    print(f"  saved a{area_code}/{slug}: {len(data)} bytes  -> {out_path.name}")
    return 0


def time_range_utc(end_utc: str, hours_back: float) -> list[str]:
    """end_utc から hours_back 時間さかのぼった 5 分刻みの time_utc リスト（古い→新しい）。"""
    from datetime import timedelta
    dt = datetime.strptime(end_utc, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    n = int(hours_back * 12)  # 5 min steps
    times = []
    for i in range(n + 1):
        t = dt - timedelta(minutes=5 * (n - i))
        times.append(t.strftime("%Y%m%d%H%M00"))
    return times


def fetch_one_quiet(area_code: str, time_utc: str) -> bool:
    """quiet 版 fetch_one。成功なら True、失敗なら False。エラー出力は stderr にだけ。"""
    slug = AREA_SLUGS.get(area_code)
    if slug is None:
        return False
    yyyy, mm, dd = utc_to_jst_path(time_utc)
    out_dir = ARCHIVE_ROOT / slug / yyyy / mm / dd
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"rain_{time_utc}_a{area_code}.png"
    if out_path.exists():
        return True
    url = RAIN_URL_TMPL.format(time=time_utc, area=area_code)
    try:
        data = http_get(url)
    except Exception:
        return False
    out_path.write_bytes(data)
    return True


def file_exists_for(area_code: str, time_utc: str) -> bool:
    slug = AREA_SLUGS.get(area_code)
    if slug is None:
        return False
    yyyy, mm, dd = utc_to_jst_path(time_utc)
    return (ARCHIVE_ROOT / slug / yyyy / mm / dd / f"rain_{time_utc}_a{area_code}.png").exists()


def now_utc_aligned_5min(lag_minutes: int = 10) -> datetime:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    cur = now.replace(second=0, microsecond=0)
    cur = cur.replace(minute=(cur.minute // 5) * 5)
    return cur - timedelta(minutes=lag_minutes)


def fmt_iso_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def parse_iso_utc(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_t_utc(t_utc: str) -> datetime:
    return datetime.strptime(t_utc, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def load_coverage_state() -> dict:
    if not COVERAGE_STATE_PATH.exists():
        return {"areas": {}}
    try:
        return json.loads(COVERAGE_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"areas": {}}


def save_coverage_state(state: dict) -> None:
    COVERAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def smart_backfill(area_code: str, retry_interval_h: float = 1.0) -> int:
    """watermark + pending_holes 駆動の効率的 backfill。

    state file 構造 (D:/jma_archive/.coverage_state.json):
      {"areas": {"00": {"continuous_through": ISO, "pending_holes": [
          {"time_utc": "...", "first_seen": ISO, "last_attempt": ISO}
      ]}}}

    動作:
      Step 1: tail scan (continuous_through+5min → now-10min)
              既存 → 進める, pending → 止める, 不在 → fetch 試行
              成功で進める, 404/err で新規 hole として pending 追加し止める
      Step 2: pending retry (last_attempt < now - retry_interval_h)
              成功 → pending から除去, age > 120h → 諦め drop
      Step 3: pending 解消で連続化したぶん watermark を再前進
    """
    from datetime import timedelta

    slug = AREA_SLUGS.get(area_code)
    if slug is None:
        print(f"unknown area: a{area_code}", file=sys.stderr)
        return 1

    state = load_coverage_state()
    area_state = state["areas"].get(area_code, {
        "continuous_through": None,
        "pending_holes": [],
    })

    end = now_utc_aligned_5min(lag_minutes=10)
    retention_start = end - timedelta(hours=RETENTION_HOURS)

    if area_state["continuous_through"] is None:
        cont = retention_start
    else:
        cont = parse_iso_utc(area_state["continuous_through"])
        if cont < retention_start:
            cont = retention_start  # 5 日より古いものは諦め

    pending = list(area_state["pending_holes"])
    pending_set = set(h["time_utc"] for h in pending)

    # Step 1: tail scan
    new_holes = []
    new_cont = cont
    fetches = 0
    t = cont + timedelta(minutes=5)
    while t <= end:
        t_utc = t.strftime("%Y%m%d%H%M00")
        if t_utc in pending_set:
            break  # 既知 hole に到達、watermark 止める
        if file_exists_for(area_code, t_utc):
            new_cont = t
            t += timedelta(minutes=5)
            continue
        # 不在 → fetch 試行
        if fetch_one_quiet(area_code, t_utc):
            new_cont = t
            fetches += 1
            t += timedelta(minutes=5)
        else:
            new_holes.append({
                "time_utc": t_utc,
                "first_seen": fmt_iso_utc(end),
                "last_attempt": fmt_iso_utc(end),
            })
            pending_set.add(t_utc)
            break

    if fetches:
        print(f"  smart-backfill a{area_code} tail: filled {fetches} new frames")
    if new_holes:
        print(f"  smart-backfill a{area_code} tail: added {len(new_holes)} new pending holes")
    pending.extend(new_holes)

    # Step 2: pending retry
    fresh_pending = []
    retried = filled = aged = 0
    for hole in pending:
        h_time = parse_t_utc(hole["time_utc"])
        if h_time < retention_start:
            aged += 1
            continue
        last_att = parse_iso_utc(hole["last_attempt"])
        if last_att < end - timedelta(hours=retry_interval_h):
            retried += 1
            if fetch_one_quiet(area_code, hole["time_utc"]):
                filled += 1
                continue
            hole["last_attempt"] = fmt_iso_utc(end)
        fresh_pending.append(hole)
    pending = fresh_pending
    if retried or aged:
        print(f"  smart-backfill a{area_code} pending: {retried} retried, {filled} filled, {aged} aged out, {len(pending)} remaining")

    # Step 3: re-advance watermark
    pending_set = set(h["time_utc"] for h in pending)
    cont2 = new_cont
    while True:
        nxt = cont2 + timedelta(minutes=5)
        if nxt > end:
            break
        nxt_utc = nxt.strftime("%Y%m%d%H%M00")
        if nxt_utc in pending_set:
            break
        if file_exists_for(area_code, nxt_utc):
            cont2 = nxt
        else:
            break
    if cont2 > new_cont:
        print(f"  smart-backfill a{area_code} watermark: advanced past previously-pending holes")

    state["areas"][area_code] = {
        "continuous_through": fmt_iso_utc(cont2),
        "pending_holes": pending,
    }
    save_coverage_state(state)
    print(f"  smart-backfill a{area_code} done: continuous_through={fmt_iso_utc(cont2)}, pending={len(pending)}")
    return 0


def detect_gaps(area_code: str, hours_back: float, lag_minutes: int = 10) -> list[str]:
    """archive を走査、過去 hours_back 時間の欠損 time_utc list を返す（古い→新しい順）。

    lag_minutes 以内（直近）は配信遅延の可能性ありスキップ。
    JMA サーバ側 retention は約 116h（5 日）なので hours_back > 116 は無意味。
    """
    from datetime import timedelta
    slug = AREA_SLUGS.get(area_code)
    if slug is None:
        return []
    now = datetime.now(timezone.utc)
    cur = now.replace(second=0, microsecond=0)
    cur = cur.replace(minute=(cur.minute // 5) * 5)
    end = cur - timedelta(minutes=lag_minutes)
    start = cur - timedelta(hours=hours_back)

    missing = []
    t = start
    while t <= end:
        t_utc = t.strftime("%Y%m%d%H%M00")
        yyyy, mm, dd = utc_to_jst_path(t_utc)
        out_path = ARCHIVE_ROOT / slug / yyyy / mm / dd / f"rain_{t_utc}_a{area_code}.png"
        if not out_path.exists():
            missing.append(t_utc)
        t += timedelta(minutes=5)
    return missing


def main() -> int:
    p = argparse.ArgumentParser(description="JMA rain layer (素材 PNG) を取得")
    p.add_argument("area_code", nargs="?", default=None,
                   help="地方コード 00=全国 / 01-19、または area1,area2 でカンマ区切り。省略時は全 20 個")
    p.add_argument("--time", default=None,
                   help="時刻 YYYYMMDDhhmm00 (UTC)。省略時は最新")
    p.add_argument("--hours-back", type=float, default=None,
                   help="--time（または最新）から N 時間さかのぼって 5 分刻みで一括取得")
    p.add_argument("--auto-backfill", action="store_true",
                   help="[legacy] 最新 fetch 後、--gap-window 時間内の欠損 frame を一括補完")
    p.add_argument("--gap-window", type=float, default=12.0,
                   help="--auto-backfill のスキャン時間（hours、default 12）")
    p.add_argument("--smart-backfill", action="store_true",
                   help="watermark + pending_holes 駆動の効率的 backfill（指定 area のみ）。"
                        "5 日以内の穴は 1 回/時間 retry、retention 切れは諦め。state は "
                        "D:/jma_archive/.coverage_state.json")
    p.add_argument("--retry-interval-h", type=float, default=1.0,
                   help="--smart-backfill の pending hole 再試行間隔（hours、default 1）")
    p.add_argument("--force", action="store_true", help="既存上書き")
    args = p.parse_args()

    end_time = args.time or latest_time_utc()
    if args.hours_back:
        time_list = time_range_utc(end_time, args.hours_back)
        print(f"fetch range: {time_list[0]} .. {time_list[-1]}  ({len(time_list)} frames)")
    else:
        time_list = [end_time]
        print(f"time_utc: {end_time}")

    # area 解決
    if args.area_code:
        codes = args.area_code.split(",")
    else:
        codes = sorted(AREA_SLUGS.keys())

    rc = 0
    total = len(codes) * len(time_list)
    done = 0
    for t in time_list:
        for code in codes:
            done += 1
            if fetch_one(code, t, force=args.force) != 0:
                rc = 1
    print(f"done: {done}/{total}")

    # auto-backfill (legacy): 指定 area の archive 走査で欠損補完
    if args.auto_backfill:
        for code in codes:
            missing = detect_gaps(code, args.gap_window)
            if not missing:
                print(f"  a{code}: no gaps in last {args.gap_window}h")
                continue
            print(f"  a{code}: backfilling {len(missing)} missing frames")
            for t in missing:
                if fetch_one(code, t) != 0:
                    rc = 1
            print(f"  a{code}: backfill done")

    # smart-backfill: watermark + pending_holes 駆動
    if args.smart_backfill:
        for code in codes:
            if smart_backfill(code, retry_interval_h=args.retry_interval_h) != 0:
                rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
