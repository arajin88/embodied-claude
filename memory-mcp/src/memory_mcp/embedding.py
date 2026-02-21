"""カスタム埋め込み関数モジュール。

intfloat/multilingual-e5-base の SentenceTransformer ラッパー。
e5 モデルはクエリと文書で異なるプレフィックスが必要。
"""

from __future__ import annotations

import logging
import os
from typing import Any, ClassVar

# ネットワークアクセスを防止してローカルキャッシュのみ使用
# MCP の env 設定に依存せずプロセス起動直後に適用する
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

logger = logging.getLogger(__name__)


class E5EmbeddingFunction:
    """intfloat/multilingual-e5-base 用埋め込み関数。

    e5 モデルの仕様:
    - 文書（passage）保存時: "passage: {text}" としてエンコード
    - クエリ検索時: "query: {text}" としてエンコード

    モデルはクラスレベルでキャッシュされ、インスタンス間で共有される。
    これにより main() でのプリロードが MemoryStore のインスタンスにも反映される。

    Args:
        model_name: SentenceTransformer モデル名
    """

    # クラスレベルのモデルキャッシュ（model_name → SentenceTransformer）
    _model_cache: ClassVar[dict[str, Any]] = {}

    def __init__(self, model_name: str = "intfloat/multilingual-e5-base") -> None:
        self._model_name = model_name

    @property
    def _model(self) -> Any:
        return E5EmbeddingFunction._model_cache.get(self._model_name)

    def _load_model(self) -> None:
        """モデルを遅延ロード（クラスレベルキャッシュ使用）。"""
        if self._model_name not in E5EmbeddingFunction._model_cache:
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(self._model_name, local_files_only=True)
                E5EmbeddingFunction._model_cache[self._model_name] = model
                logger.info("E5EmbeddingFunction: loaded model %s", self._model_name)
            except ImportError as e:
                raise ImportError(
                    "sentence-transformers が必要です。"
                    "`uv add sentence-transformers` を実行してください。"
                ) from e

    def __call__(self, input: list[str]) -> list[list[float]]:
        """文書保存用埋め込み（passage: プレフィックス）。

        Args:
            input: エンコードするテキストのリスト

        Returns:
            埋め込みベクトルのリスト（各要素は float のリスト）
        """
        self._load_model()
        prefixed = [f"passage: {doc}" for doc in input]
        embeddings = self._model.encode(
            prefixed,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def encode_query(self, texts: list[str]) -> list[list[float]]:
        """クエリ検索用埋め込み（query: プレフィックス）。

        Args:
            texts: クエリテキストのリスト

        Returns:
            埋め込みベクトルのリスト
        """
        self._load_model()
        prefixed = [f"query: {t}" for t in texts]
        embeddings = self._model.encode(
            prefixed,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()
