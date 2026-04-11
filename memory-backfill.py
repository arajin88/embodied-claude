"""memory MCPバックフィル＆バルクインジェスト（一回限りスクリプト）。

目的:
1. embedding を持たない既存memoryに対して embedding を生成・追加
2. research_notes/*.md の各エントリを memory に新規挿入（リッチコンテンツ + embedding）
3. reading_notes/*.txt の各エントリを memory に新規挿入（リッチコンテンツ + embedding）

実行: python memory-backfill.py [--dry-run]
"""
import argparse
import os
import re
import sqlite3
import struct
import sys
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

MEMORY_DB = Path.home() / ".claude" / "memories" / "memory.db"
RESEARCH_DIR = Path("D:/ComDoc/projects/embodied-claude/research_notes")
READING_DIR = Path("C:/Users/araji/.claude/reading_notes")
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
INGEST_TAG_RESEARCH = "##bulk_ingest_research##"
INGEST_TAG_READING = "##bulk_ingest_reading##"

DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
RESEARCH_HEADING_RE = re.compile(r"^##\s+(\d{1,2}:\d{2})\s*[-–—]\s*(.+?)\s*$")


def normalize_simple(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
    return _model


def encode_passages(texts: list[str]) -> list[bytes]:
    model = get_model()
    vecs = model.encode(
        [f"passage: {t}" for t in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=16,
    )
    return [struct.pack(f"{len(v)}f", *v.tolist()) for v in vecs]


# ---------------------------------------------------------------------------
# 1. backfill embeddings
# ---------------------------------------------------------------------------

def backfill_embeddings(conn: sqlite3.Connection, dry_run: bool) -> int:
    rows = conn.execute(
        """SELECT m.id, m.content FROM memories m
           WHERE NOT EXISTS (SELECT 1 FROM embeddings e WHERE e.memory_id = m.id)
           ORDER BY m.timestamp"""
    ).fetchall()

    if not rows:
        print("[backfill] no missing embeddings")
        return 0

    print(f"[backfill] generating embeddings for {len(rows)} memories...")
    if dry_run:
        return len(rows)

    BATCH = 32
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        ids = [r[0] for r in batch]
        contents = [r[1] for r in batch]
        blobs = encode_passages(contents)
        for mid, blob in zip(ids, blobs):
            conn.execute(
                "INSERT INTO embeddings (memory_id, vector) VALUES (?, ?)",
                (mid, blob),
            )
        conn.commit()
        print(f"  batch {i + len(batch)}/{len(rows)}")

    return len(rows)


# ---------------------------------------------------------------------------
# 2. ingest research_notes
# ---------------------------------------------------------------------------

def parse_research_file(path: Path) -> list[tuple[str, str, str, str]]:
    """returns [(date, time, title, body), ...]"""
    m = DATE_FILE_RE.match(path.name)
    if not m:
        return []
    date = m.group(1)

    sections: list[tuple[str, str, str, str]] = []
    current: tuple[str, str, list[str]] | None = None
    in_header = True
    for line in path.read_text(encoding="utf-8").splitlines():
        h = RESEARCH_HEADING_RE.match(line)
        if h:
            if current:
                sections.append((date, current[0], current[1], "\n".join(current[2]).strip()))
            current = (h.group(1), h.group(2), [])
            in_header = False
        else:
            if not in_header and current:
                current[2].append(line)
    if current:
        sections.append((date, current[0], current[1], "\n".join(current[2]).strip()))
    return sections


def already_ingested(conn: sqlite3.Connection, tag: str, key: str) -> bool:
    """ingest tagと一意キーで既存を検出"""
    row = conn.execute(
        "SELECT 1 FROM memories WHERE content LIKE ? LIMIT 1",
        (f"{tag} {key}%",),
    ).fetchone()
    return row is not None


def ingest_research(conn: sqlite3.Connection, dry_run: bool) -> int:
    inserted = 0
    skipped = 0
    if not RESEARCH_DIR.exists():
        print(f"[research] dir not found: {RESEARCH_DIR}")
        return 0

    all_sections: list[tuple[str, str, str, str]] = []
    for f in sorted(RESEARCH_DIR.iterdir()):
        all_sections.extend(parse_research_file(f))

    print(f"[research] found {len(all_sections)} sections")

    to_insert: list[tuple[str, str, str]] = []  # (id, content, timestamp)
    for date, time_str, title, body in all_sections:
        key = f"[{date} {time_str}] {title}"
        if already_ingested(conn, INGEST_TAG_RESEARCH, key):
            skipped += 1
            continue
        content = f"{INGEST_TAG_RESEARCH} {key}\n{body}".strip()
        # timestamp = ファイル日付 + 見出し時刻
        ts = f"{date}T{time_str}:00"
        to_insert.append((str(uuid.uuid4()), content, ts))

    print(f"[research] new={len(to_insert)} skipped={skipped}")
    if dry_run or not to_insert:
        return len(to_insert)

    contents = [c for _, c, _ in to_insert]
    blobs = encode_passages(contents)
    for (mid, content, ts), blob in zip(to_insert, blobs):
        normalized = normalize_simple(content)
        conn.execute(
            """INSERT INTO memories
               (id, content, normalized_content, timestamp, emotion, importance, category)
               VALUES (?, ?, ?, ?, 'curious', 3, 'technical')""",
            (mid, content, normalized, ts),
        )
        conn.execute(
            "INSERT INTO embeddings (memory_id, vector) VALUES (?, ?)",
            (mid, blob),
        )
        inserted += 1
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# 3. ingest reading_notes
# ---------------------------------------------------------------------------

READING_HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})(?:\s*[-–—]\s*(.+?))?\s*$")


def parse_reading_file(path: Path) -> list[tuple[str, str, str, str]]:
    """returns [(book_name, date, page_label, body), ...]"""
    book_name = path.stem.replace("_note", "")
    sections: list[tuple[str, str, str, str]] = []
    current: tuple[str, str, list[str]] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        h = READING_HEADING_RE.match(line)
        if h:
            if current:
                sections.append((book_name, current[0], current[1] or "", "\n".join(current[2]).strip()))
            current = (h.group(1), h.group(2) or "", [])
        else:
            if current:
                current[2].append(line)
    if current:
        sections.append((book_name, current[0], current[1] or "", "\n".join(current[2]).strip()))
    return sections


def ingest_reading(conn: sqlite3.Connection, dry_run: bool) -> int:
    inserted = 0
    skipped = 0
    if not READING_DIR.exists():
        print(f"[reading] dir not found: {READING_DIR}")
        return 0

    all_sections: list[tuple[str, str, str, str]] = []
    for f in sorted(READING_DIR.iterdir()):
        if f.suffix in (".txt", ".md") and f.is_file():
            all_sections.extend(parse_reading_file(f))

    print(f"[reading] found {len(all_sections)} sections")

    to_insert: list[tuple[str, str, str]] = []
    for book, date, page, body in all_sections:
        key = f"[{book} {date}] {page}"
        if already_ingested(conn, INGEST_TAG_READING, key):
            skipped += 1
            continue
        content = f"{INGEST_TAG_READING} {key}\n{body}".strip()
        ts = f"{date}T20:00:00"
        to_insert.append((str(uuid.uuid4()), content, ts))

    print(f"[reading] new={len(to_insert)} skipped={skipped}")
    if dry_run or not to_insert:
        return len(to_insert)

    contents = [c for _, c, _ in to_insert]
    blobs = encode_passages(contents)
    for (mid, content, ts), blob in zip(to_insert, blobs):
        normalized = normalize_simple(content)
        conn.execute(
            """INSERT INTO memories
               (id, content, normalized_content, timestamp, emotion, importance, category)
               VALUES (?, ?, ?, ?, 'curious', 3, 'daily')""",
            (mid, content, normalized, ts),
        )
        conn.execute(
            "INSERT INTO embeddings (memory_id, vector) VALUES (?, ?)",
            (mid, blob),
        )
        inserted += 1
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-backfill", action="store_true")
    parser.add_argument("--skip-research", action="store_true")
    parser.add_argument("--skip-reading", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(str(MEMORY_DB))
    try:
        if not args.skip_backfill:
            n = backfill_embeddings(conn, args.dry_run)
            print(f"=> backfilled {n} embeddings\n")

        if not args.skip_research:
            n = ingest_research(conn, args.dry_run)
            print(f"=> ingested {n} research entries\n")

        if not args.skip_reading:
            n = ingest_reading(conn, args.dry_run)
            print(f"=> ingested {n} reading entries\n")
    finally:
        conn.close()

    if args.dry_run:
        print("(dry-run: no changes committed)")
    else:
        print("DONE")


if __name__ == "__main__":
    main()
