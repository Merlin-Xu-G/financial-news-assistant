"""阶段三：把片段向量化并写入向量库。

失败分级（见 contracts/cli.md）：向量库不可用 → 停止；单批嵌入失败 → 记录后继续。
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Iterator

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from .config import (
    BATCH_SIZE,
    MAX_RETRIES,
    QPS,
    ConfigError,
    DependencyError,
    Paths,
    embedding_config,
    milvus_config,
)
from .report import Failure, StageResult
from .store import Store


class EmbeddingError(Exception):
    """单批嵌入调用失败，记录后可继续后续批次。"""


class Embedder:
    """OpenAI 兼容的嵌入客户端，带限速与退避重试。"""

    def __init__(self, base_url: str, api_key: str, model: str, qps: float, max_retries: int) -> None:
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.max_retries = max_retries
        self.min_interval = 1.0 / qps if qps > 0 else 0.0
        self._last_call = 0.0

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, 2.0 ** (attempt - 1)) + random.uniform(0.0, 0.5)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """一次请求完成一批文本的向量化。鉴权失败直接抛出，临时错误退避重试。"""
        attempt = 0
        while True:
            attempt += 1
            self._throttle()
            try:
                response = self.client.embeddings.create(model=self.model, input=texts)
                return [item.embedding for item in response.data]
            except AuthenticationError as exc:
                raise DependencyError(f"嵌入接口鉴权失败，请检查 EMBEDDING_API_KEY：{exc}") from exc
            except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
                if attempt > self.max_retries:
                    raise EmbeddingError(f"{type(exc).__name__}：已重试 {attempt} 次仍失败") from exc
                delay = self._backoff(attempt)
                logging.warning(
                    "嵌入接口临时错误（%s），第 %d/%d 次重试，%.1fs 后",
                    type(exc).__name__,
                    attempt,
                    self.max_retries,
                    delay,
                )
                time.sleep(delay)
            except APIStatusError as exc:
                raise DependencyError(f"嵌入接口返回错误 {exc.status_code}：{exc}") from exc

    def detect_dim(self) -> int:
        """用一条样本文本探测向量维度。"""
        vectors = self.embed(["维度探测"])
        if not vectors:
            raise DependencyError("嵌入接口未返回向量，无法探测维度")
        return len(vectors[0])


def load_chunks(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def select(chunks: list[dict[str, Any]], symbols: list[str] | None, limit: int | None) -> list[dict[str, Any]]:
    if symbols:
        wanted = set(symbols)
        chunks = [row for row in chunks if row.get("symbol") in wanted]
    if limit:
        chunks = chunks[:limit]
    return chunks


def batches(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


HASH_FIELDS = ("symbol", "name", "section", "part", "parts", "text")


def content_hash(chunk: dict[str, Any]) -> str:
    """片段内容指纹，用于区分「内容未变可跳过」与「内容已变需更新」。"""
    payload = json.dumps({key: chunk.get(key) for key in HASH_FIELDS}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_record(chunk: dict[str, Any], vector: list[float]) -> dict[str, Any]:
    """片段 + 向量 → 向量库记录。chars 不进向量库（见 data-model.md E4）。"""
    return {
        "id": chunk["id"],
        "vector": vector,
        "symbol": chunk["symbol"],
        "name": chunk.get("name") or "",
        "section": chunk["section"],
        "part": int(chunk["part"]),
        "parts": int(chunk["parts"]),
        "text": chunk["text"],
        "content_hash": content_hash(chunk),
    }


def run(
    paths: Paths,
    symbols: list[str] | None = None,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
    qps: float = QPS,
    max_retries: int = MAX_RETRIES,
) -> StageResult:
    """阶段三入口：把片段向量化并幂等写入向量库。"""
    if batch_size <= 0:
        raise ConfigError(f"--batch-size 必须大于 0，当前为 {batch_size}")
    if qps <= 0:
        raise ConfigError(f"--qps 必须大于 0，当前为 {qps}")
    if not paths.chunks.exists():
        raise ConfigError(f"片段清单不存在：{paths.chunks}（先执行 chunks 阶段）")

    chunks = select(load_chunks(paths.chunks), symbols, limit)
    if not chunks:
        raise ConfigError("没有可入库的片段")

    config = embedding_config()
    embedder = Embedder(config.base_url, config.api_key, config.model, qps, max_retries)
    dim = config.dim if config.dim else embedder.detect_dim()
    logging.info("嵌入模型=%s 维度=%d 片段数=%d", config.model, dim, len(chunks))

    store = Store(milvus_config(), dim)
    created = store.ensure_collection()
    logging.info("集合 %s %s", store.collection, "已新建" if created else "已存在，复用")

    processed = skipped = failed = 0
    failures: list[Failure] = []
    checked_dim = False

    for batch in batches(chunks, batch_size):
        known = store.existing([row["id"] for row in batch])
        pending = [row for row in batch if known.get(row["id"]) != content_hash(row)]
        skipped += len(batch) - len(pending)
        if not pending:
            continue

        try:
            vectors = embedder.embed([row["text"] for row in pending])
        except EmbeddingError as exc:
            failed += len(pending)
            failures.extend(Failure(row["id"], str(exc)) for row in pending)
            logging.warning("本批 %d 条嵌入失败：%s", len(pending), exc)
            continue

        if not checked_dim:
            actual = len(vectors[0]) if vectors else 0
            if actual != dim:
                raise DependencyError(
                    f"嵌入接口返回的向量维度为 {actual}，与配置/集合的 {dim} 不一致。"
                    "请修正 EMBEDDING_DIM 或更换集合名。"
                )
            checked_dim = True

        store.upsert([to_record(row, vector) for row, vector in zip(pending, vectors)])
        processed += len(pending)

    return StageResult(processed=processed, skipped=skipped, failed=failed, failures=tuple(failures))
