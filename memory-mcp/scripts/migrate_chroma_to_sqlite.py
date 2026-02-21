#!/usr/bin/env python3
"""ChromaDB → SQLite+numpy migration script.

Usage:
    uv run python scripts/migrate_chroma_to_sqlite.py \
        --source ~/.claude/memories/chroma \
        --dest ~/.claude/memories/memory.db

What it does:
    1. Read all memories + metadata from ChromaDB's internal chroma.sqlite3
    2. Re-compute embeddings using E5EmbeddingFunction (768-dim)
    3. Insert into SQLite memories + embeddings tables
    4. Expand coactivation JSON → coactivation table
    5. Migrate episodes collection → episodes table

Note: chromadb library is NOT required. Reads chroma.sqlite3 directly.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def _ddl(conn: sqlite3.Connection) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        normalized_content TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        emotion TEXT NOT NULL DEFAULT 'neutral',
        importance INTEGER NOT NULL DEFAULT 3,
        category TEXT NOT NULL DEFAULT 'daily',
        access_count INTEGER NOT NULL DEFAULT 0,
        last_accessed TEXT NOT NULL DEFAULT '',
        linked_ids TEXT NOT NULL DEFAULT '',
        episode_id TEXT,
        sensory_data TEXT NOT NULL DEFAULT '',
        camera_position TEXT,
        tags TEXT NOT NULL DEFAULT '',
        links TEXT NOT NULL DEFAULT '',
        novelty_score REAL NOT NULL DEFAULT 0.0,
        prediction_error REAL NOT NULL DEFAULT 0.0,
        activation_count INTEGER NOT NULL DEFAULT 0,
        last_activated TEXT NOT NULL DEFAULT '',
        reading TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_memories_emotion    ON memories(emotion);
    CREATE INDEX IF NOT EXISTS idx_memories_category   ON memories(category);
    CREATE INDEX IF NOT EXISTS idx_memories_timestamp  ON memories(timestamp);
    CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);

    CREATE TABLE IF NOT EXISTS embeddings (
        memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
        vector BLOB NOT NULL
    );

    CREATE TABLE IF NOT EXISTS coactivation (
        source_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
        target_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
        weight REAL NOT NULL CHECK(weight >= 0.0 AND weight <= 1.0),
        PRIMARY KEY (source_id, target_id)
    );
    CREATE INDEX IF NOT EXISTS idx_coactivation_source ON coactivation(source_id);
    CREATE INDEX IF NOT EXISTS idx_coactivation_target ON coactivation(target_id);

    CREATE TABLE IF NOT EXISTS episodes (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        memory_ids TEXT NOT NULL DEFAULT '',
        participants TEXT NOT NULL DEFAULT '',
        location_context TEXT,
        summary TEXT NOT NULL DEFAULT '',
        emotion TEXT NOT NULL DEFAULT 'neutral',
        importance INTEGER NOT NULL DEFAULT 3
    );
    """
    for stmt in ddl.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()


def _read_chroma_collection(
    chroma_conn: sqlite3.Connection, collection_name: str
) -> list[dict]:
    """ChromaDB の内部 SQLite から記憶データを直接読み取る。

    Returns:
        list of dicts with keys: id, document, metadata
    """
    # コレクション ID を取得
    col_row = chroma_conn.execute(
        "SELECT id FROM collections WHERE name = ?", (collection_name,)
    ).fetchone()
    if not col_row:
        return []
    collection_id = col_row[0]

    # METADATA セグメント ID を取得
    seg_row = chroma_conn.execute(
        "SELECT id FROM segments WHERE collection = ? AND scope = 'METADATA'",
        (collection_id,),
    ).fetchone()
    if not seg_row:
        return []
    segment_id = seg_row[0]

    # このセグメントの全 embedding（記憶）を取得
    emb_rows = chroma_conn.execute(
        "SELECT id, embedding_id FROM embeddings WHERE segment_id = ?",
        (segment_id,),
    ).fetchall()

    results = []
    for row_id, embedding_id in emb_rows:
        # 各記憶のメタデータを取得
        meta_rows = chroma_conn.execute(
            "SELECT key, string_value, int_value, float_value "
            "FROM embedding_metadata WHERE id = ?",
            (row_id,),
        ).fetchall()

        metadata: dict = {}
        document: str = ""
        for key, str_val, int_val, float_val in meta_rows:
            if key == "chroma:document":
                document = str_val or ""
            elif str_val is not None:
                metadata[key] = str_val
            elif int_val is not None:
                metadata[key] = int_val
            elif float_val is not None:
                metadata[key] = float_val

        results.append(
            {
                "id": embedding_id,
                "document": document,
                "metadata": metadata,
            }
        )

    return results


def migrate(source: str, dest: str) -> None:
    try:
        import numpy as np
    except ImportError as e:
        print(f"Error: {e}")
        print("Install numpy: uv add numpy")
        sys.exit(1)

    source_path = Path(source).expanduser()
    dest_path = Path(dest).expanduser()

    chroma_sqlite = source_path / "chroma.sqlite3"
    if not chroma_sqlite.exists():
        print(f"Error: chroma.sqlite3 not found in {source_path}")
        sys.exit(1)

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Source: {chroma_sqlite}")
    print(f"Dest:   {dest_path}")
    print()

    # ChromaDB の内部 SQLite を直接読む
    chroma_conn = sqlite3.connect(str(chroma_sqlite))

    col_rows = chroma_conn.execute("SELECT name FROM collections").fetchall()
    collection_names = [r[0] for r in col_rows]
    print(f"Collections found: {collection_names}")
    print()

    # Prompt
    answer = input("Proceed with migration? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        sys.exit(0)

    # E5 embedding function（768次元）
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from memory_mcp.config import MemoryConfig
    from memory_mcp.embedding import E5EmbeddingFunction
    from memory_mcp.normalizer import normalize_japanese
    from memory_mcp.vector import encode_vector

    config = MemoryConfig.from_env()
    print(f"Loading embedding model: {config.embedding_model} ...")
    ef = E5EmbeddingFunction(config.embedding_model)
    ef._load_model()
    print("Model loaded.\n")

    # Open SQLite
    conn = sqlite3.connect(str(dest_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _ddl(conn)

    memory_ids_in_dest: set[str] = set()

    # ── Migrate memories collection ────────────────────
    memories_collection_name = next(
        (n for n in collection_names if n != "episodes"), None
    )
    if memories_collection_name:
        records = _read_chroma_collection(chroma_conn, memories_collection_name)
        print(f"Migrating {len(records)} memories from '{memories_collection_name}'...")

        coactivation_entries: list[tuple[str, str, float]] = []
        docs_to_embed: list[str] = []
        valid_records: list[dict] = []

        for rec in records:
            memory_id = rec["id"]
            meta = dict(rec["metadata"])
            doc = rec["document"]

            # Extract coactivation before insert
            coact_raw = meta.pop("coactivation", "") or ""
            if coact_raw:
                try:
                    coact_dict = (
                        json.loads(coact_raw) if isinstance(coact_raw, str) else coact_raw
                    )
                    if isinstance(coact_dict, dict):
                        for target_id, weight in coact_dict.items():
                            try:
                                w = float(weight)
                                w = max(0.0, min(1.0, w))
                                coactivation_entries.append((memory_id, target_id, w))
                            except (TypeError, ValueError):
                                pass
                except (json.JSONDecodeError, TypeError):
                    pass

            # original content は metadata["content"] または document
            original_content = meta.get("content") or doc
            episode_id = meta.get("episode_id") or None
            if episode_id == "":
                episode_id = None

            normalized = normalize_japanese(doc) if doc else ""

            try:
                conn.execute(
                    """INSERT OR IGNORE INTO memories (
                        id, content, normalized_content, timestamp,
                        emotion, importance, category, access_count, last_accessed,
                        linked_ids, episode_id, sensory_data, camera_position,
                        tags, links, novelty_score, prediction_error,
                        activation_count, last_activated, reading
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        memory_id,
                        original_content,
                        normalized,
                        meta.get("timestamp", ""),
                        meta.get("emotion", "neutral"),
                        int(meta.get("importance", 3)),
                        meta.get("category", "daily"),
                        int(meta.get("access_count", 0)),
                        meta.get("last_accessed", ""),
                        meta.get("linked_ids", ""),
                        episode_id,
                        meta.get("sensory_data", ""),
                        meta.get("camera_position") or None,
                        meta.get("tags", ""),
                        meta.get("links", ""),
                        float(meta.get("novelty_score", 0.0)),
                        float(meta.get("prediction_error", 0.0)),
                        int(meta.get("activation_count", 0)),
                        meta.get("last_activated", ""),
                        meta.get("reading") or None,
                    ),
                )
                memory_ids_in_dest.add(memory_id)
                valid_records.append(rec)
                docs_to_embed.append(normalized or original_content)
            except Exception as e:
                print(f"  Warning: failed to insert memory {memory_id}: {e}")
                continue

        conn.commit()
        print(f"  Inserted {len(memory_ids_in_dest)} memories.")

        # E5 で embedding を再計算（768次元）
        print(f"  Re-computing embeddings ({config.embedding_model}) ...")
        batch_size = 32
        total = len(valid_records)
        for i in range(0, total, batch_size):
            batch_recs = valid_records[i : i + batch_size]
            batch_docs = docs_to_embed[i : i + batch_size]
            batch_vecs = ef(batch_docs)
            for rec, vec in zip(batch_recs, batch_vecs):
                memory_id = rec["id"]
                if memory_id in memory_ids_in_dest:
                    vec_bytes = encode_vector(np.array(vec, dtype=np.float32))
                    conn.execute(
                        "INSERT OR IGNORE INTO embeddings (memory_id, vector) VALUES (?,?)",
                        (memory_id, vec_bytes),
                    )
            conn.commit()
            done = min(i + batch_size, total)
            print(f"  {done}/{total} embeddings done", end="\r", flush=True)
        print(f"\n  Embeddings computed: {total}")

        # Insert coactivation (only where both sides exist)
        coa_inserted = 0
        for source_id, target_id, weight in coactivation_entries:
            if source_id in memory_ids_in_dest and target_id in memory_ids_in_dest:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO coactivation (source_id, target_id, weight)
                           VALUES (?,?,?)""",
                        (source_id, target_id, weight),
                    )
                    coa_inserted += 1
                except Exception:
                    pass
        conn.commit()
        print(f"  Inserted {coa_inserted} coactivation weights.")

    # ── Migrate episodes collection ────────────────────
    if "episodes" in collection_names:
        ep_records = _read_chroma_collection(chroma_conn, "episodes")
        print(f"\nMigrating {len(ep_records)} episodes...")
        ep_inserted = 0
        for rec in ep_records:
            ep_id = rec["id"]
            meta = dict(rec["metadata"])
            summary = rec["document"]
            end_time = meta.get("end_time") or None
            if end_time == "":
                end_time = None
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO episodes
                       (id, title, start_time, end_time, memory_ids, participants,
                        location_context, summary, emotion, importance)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        ep_id,
                        meta.get("title", ""),
                        meta.get("start_time", ""),
                        end_time,
                        meta.get("memory_ids", ""),
                        meta.get("participants", ""),
                        meta.get("location_context") or None,
                        summary,
                        meta.get("emotion", "neutral"),
                        int(meta.get("importance", 3)),
                    ),
                )
                ep_inserted += 1
            except Exception as e:
                print(f"  Warning: failed to insert episode {ep_id}: {e}")
        conn.commit()
        print(f"  Inserted {ep_inserted} episodes.")

    chroma_conn.close()
    conn.close()
    print("\nMigration complete!")
    print(f"SQLite database: {dest_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate ChromaDB memories to SQLite+numpy")
    parser.add_argument(
        "--source",
        default=str(Path.home() / ".claude" / "memories" / "chroma"),
        help="Path to ChromaDB directory (default: ~/.claude/memories/chroma)",
    )
    parser.add_argument(
        "--dest",
        default=str(Path.home() / ".claude" / "memories" / "memory.db"),
        help="Path to SQLite output file (default: ~/.claude/memories/memory.db)",
    )
    args = parser.parse_args()
    migrate(source=args.source, dest=args.dest)


if __name__ == "__main__":
    main()
