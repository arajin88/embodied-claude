"""
軽量記憶保存スクリプト（autonomous-action用）

memory-mcp を起動せずに SQLite に直接記憶を書き込む。
embedding（intfloat/multilingual-e5-base）も同時に生成して保存する。
これによりベクトル検索（recall, search_memories）の対象になる。

使い方:
  python save-memory.py --content "##browse_curiosity## 調べた内容" \
      --category technical --emotion curious --importance 3

  # embedding生成をスキップしたい場合（高速化）:
  python save-memory.py --content "..." --no-embedding
"""

import argparse
import os
import sqlite3
import struct
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

# ネットワークアクセス防止（embedding.pyと同じ）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


MEMORY_DB = Path.home() / ".claude" / "memories" / "memory.db"
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"


def normalize_simple(text: str) -> str:
    """簡易正規化（NFKC + 小文字化）"""
    return unicodedata.normalize("NFKC", text).lower()


def encode_passage(text: str) -> bytes:
    """e5モデルで passage 埋め込みを生成して BLOB(float32) として返す。"""
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
    vec = model.encode(
        [f"passage: {text}"],
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    # float32 BLOB（memory-mcpのstore.pyと同じ形式）
    return struct.pack(f"{len(vec)}f", *vec.tolist())


def save_memory(
    content: str,
    category: str = "daily",
    emotion: str = "neutral",
    importance: int = 3,
    with_embedding: bool = True,
) -> str:
    memory_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    normalized = normalize_simple(content)

    embedding_blob: bytes | None = None
    if with_embedding:
        embedding_blob = encode_passage(content)

    conn = sqlite3.connect(str(MEMORY_DB))
    try:
        conn.execute(
            """INSERT INTO memories
               (id, content, normalized_content, timestamp, emotion, importance, category)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (memory_id, content, normalized, timestamp, emotion, importance, category),
        )
        if embedding_blob is not None:
            conn.execute(
                "INSERT INTO embeddings (memory_id, vector) VALUES (?, ?)",
                (memory_id, embedding_blob),
            )
        conn.commit()
    finally:
        conn.close()

    return memory_id


def main():
    parser = argparse.ArgumentParser(description="Save memory to SQLite directly")
    parser.add_argument("--content", required=True, help="Memory content")
    parser.add_argument("--category", default="daily")
    parser.add_argument("--emotion", default="neutral")
    parser.add_argument("--importance", type=int, default=3)
    parser.add_argument("--no-embedding", action="store_true",
                        help="embedding生成をスキップ（高速化、ただしベクトル検索不可）")
    args = parser.parse_args()

    memory_id = save_memory(
        args.content, args.category, args.emotion, args.importance,
        with_embedding=not args.no_embedding,
    )
    print(f"Memory saved! ID: {memory_id}")


if __name__ == "__main__":
    main()
