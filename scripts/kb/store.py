"""阶段三 · E4：向量库集合定义与客户端封装。

字段、索引与写入语义见 specs/001-kb-vector-pipeline/contracts/milvus-schema.md。
"""

from __future__ import annotations

from typing import Any

from pymilvus import DataType, MilvusClient

from .config import DependencyError, MilvusConfig

ID_FIELD = "id"
VECTOR_FIELD = "vector"
TEXT_FIELD = "text"
CONTENT_HASH_FIELD = "content_hash"
FILTER_FIELDS = ("symbol", "section")

MAX_ID_LENGTH = 128
MAX_SYMBOL_LENGTH = 16
MAX_NAME_LENGTH = 64
MAX_SECTION_LENGTH = 64
MAX_TEXT_LENGTH = 8192
MAX_HASH_LENGTH = 64

HNSW_M = 16
HNSW_EF_CONSTRUCTION = 200
METRIC_TYPE = "COSINE"

UPSERT_BATCH = 500


def build_schema(dim: int):
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(ID_FIELD, DataType.VARCHAR, max_length=MAX_ID_LENGTH, is_primary=True)
    schema.add_field(VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("symbol", DataType.VARCHAR, max_length=MAX_SYMBOL_LENGTH)
    schema.add_field("name", DataType.VARCHAR, max_length=MAX_NAME_LENGTH)
    schema.add_field("section", DataType.VARCHAR, max_length=MAX_SECTION_LENGTH)
    schema.add_field("part", DataType.INT16)
    schema.add_field("parts", DataType.INT16)
    schema.add_field(TEXT_FIELD, DataType.VARCHAR, max_length=MAX_TEXT_LENGTH)
    schema.add_field(CONTENT_HASH_FIELD, DataType.VARCHAR, max_length=MAX_HASH_LENGTH)
    return schema


def build_index_params():
    params = MilvusClient.prepare_index_params()
    params.add_index(
        field_name=VECTOR_FIELD,
        index_type="HNSW",
        metric_type=METRIC_TYPE,
        params={"M": HNSW_M, "efConstruction": HNSW_EF_CONSTRUCTION},
    )
    for field in FILTER_FIELDS:
        params.add_index(field_name=field, index_type="INVERTED")
    return params


class Store:
    """向量库封装：集合生命周期、已存在判定、幂等写入。"""

    def __init__(self, config: MilvusConfig, dim: int) -> None:
        self.collection = config.collection
        self.dim = dim
        try:
            self.client = MilvusClient(uri=config.uri)
        except Exception as exc:
            raise DependencyError(f"无法连接向量库 {config.uri}：{exc}") from exc

    def ensure_collection(self) -> bool:
        """集合不存在则创建，存在则校验维度。返回是否新建。"""
        try:
            exists = self.client.has_collection(self.collection)
        except Exception as exc:
            raise DependencyError(f"查询集合 {self.collection} 失败：{exc}") from exc

        if exists:
            actual = self.vector_dim()
            if actual != self.dim:
                raise DependencyError(
                    f"集合 {self.collection} 的向量维度为 {actual}，与配置的 {self.dim} 不一致。"
                    "禁止删除重建，请修正 EMBEDDING_DIM 或改用其他集合名。"
                )
            return False

        try:
            self.client.create_collection(
                collection_name=self.collection,
                schema=build_schema(self.dim),
                index_params=build_index_params(),
            )
        except Exception as exc:
            raise DependencyError(f"创建集合 {self.collection} 失败：{exc}") from exc
        return True

    def vector_dim(self) -> int | None:
        try:
            desc = self.client.describe_collection(self.collection)
        except Exception as exc:
            raise DependencyError(f"读取集合 {self.collection} 定义失败：{exc}") from exc
        for field in desc.get("fields") or []:
            if field.get("name") == VECTOR_FIELD:
                dim = (field.get("params") or {}).get("dim")
                return int(dim) if dim is not None else None
        return None

    def existing(self, ids: list[str]) -> dict[str, str]:
        """返回已入库的 {id: content_hash}。

        有了哈希才能区分「内容未变，可跳过」与「内容已变，需更新」（FR-016）。
        """
        if not ids:
            return {}
        quoted = ",".join(f'"{value}"' for value in ids)
        try:
            rows = self.client.query(
                collection_name=self.collection,
                filter=f"{ID_FIELD} in [{quoted}]",
                output_fields=[ID_FIELD, CONTENT_HASH_FIELD],
            )
        except Exception as exc:
            raise DependencyError(f"查询已入库片段失败：{exc}") from exc
        return {row[ID_FIELD]: row.get(CONTENT_HASH_FIELD) or "" for row in rows}

    def upsert(self, rows: list[dict[str, Any]]) -> int:
        """按 id 幂等写入，返回写入条数。"""
        written = 0
        for start in range(0, len(rows), UPSERT_BATCH):
            batch = rows[start : start + UPSERT_BATCH]
            try:
                self.client.upsert(collection_name=self.collection, data=batch)
            except Exception as exc:
                raise DependencyError(f"写入向量库失败：{exc}") from exc
            written += len(batch)
        return written

    def count(self) -> int:
        """精确统计记录数。

        不用 ``get_collection_stats``——它返回的 row_count 在 flush 前不准，
        无法用于校验写入结果。
        """
        try:
            rows = self.client.query(
                collection_name=self.collection,
                filter=f'{ID_FIELD} != ""',
                output_fields=["count(*)"],
            )
        except Exception as exc:
            raise DependencyError(f"统计集合行数失败：{exc}") from exc
        return int(rows[0]["count(*)"]) if rows else 0
