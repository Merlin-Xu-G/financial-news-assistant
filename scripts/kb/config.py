"""路径解析、默认参数与环境配置读取。

所有路径由数据根目录派生，避免各模块各自拼接字符串。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
ENV_FILE = PROJECT_ROOT / ".env"

MAX_CHARS = 600
OVERLAP = 80
BATCH_SIZE = 16
QPS = 1.0
MAX_RETRIES = 4

DEFAULT_MILVUS_URI = "http://47.95.112.116:19530"
DEFAULT_MILVUS_COLLECTION = "fin_kb"


class ConfigError(Exception):
    """配置缺失、参数非法或输入为空，对应退出码 1。"""


class DependencyError(Exception):
    """外部依赖不可用（向量库、嵌入接口），对应退出码 2。"""


class Paths(NamedTuple):
    """流水线用到的文件位置。"""

    chunks: Path
    failures: Path


class EmbeddingConfig(NamedTuple):
    base_url: str
    api_key: str
    model: str
    dim: int | None


class MilvusConfig(NamedTuple):
    uri: str
    collection: str


def load_dotenv() -> None:
    """把项目根 .env 的键值读入 os.environ。

    已存在的环境变量不覆盖，便于用命令行临时指定。
    """
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_paths(data_dir: str | None = None) -> Paths:
    """把数据根目录展开成流水线用到的路径。相对路径按当前工作目录解析。"""
    data = Path(data_dir).resolve() if data_dir else DEFAULT_DATA_DIR
    kb = data / "kb"
    return Paths(
        chunks=kb / "chunks.jsonl",
        failures=kb / "_meta" / "failures.jsonl",
    )


def embedding_config() -> EmbeddingConfig:
    """读取嵌入接口配置，缺失必需项时抛 ConfigError。"""
    load_dotenv()
    values = {
        "EMBEDDING_BASE_URL": os.environ.get("EMBEDDING_BASE_URL", "").strip(),
        "EMBEDDING_API_KEY": os.environ.get("EMBEDDING_API_KEY", "").strip(),
        "EMBEDDING_MODEL": os.environ.get("EMBEDDING_MODEL", "").strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigError(f"缺少环境变量：{', '.join(missing)}（写入项目根 .env）")

    raw_dim = os.environ.get("EMBEDDING_DIM", "").strip()
    if raw_dim and not raw_dim.isdigit():
        raise ConfigError(f"EMBEDDING_DIM 必须是正整数或留空，当前为 {raw_dim!r}")

    return EmbeddingConfig(
        base_url=values["EMBEDDING_BASE_URL"],
        api_key=values["EMBEDDING_API_KEY"],
        model=values["EMBEDDING_MODEL"],
        dim=int(raw_dim) if raw_dim else None,
    )


def milvus_config() -> MilvusConfig:
    """读取向量库配置，未配置时回落到项目默认实例。"""
    load_dotenv()
    return MilvusConfig(
        uri=os.environ.get("MILVUS_URI", "").strip() or DEFAULT_MILVUS_URI,
        collection=os.environ.get("MILVUS_COLLECTION", "").strip() or DEFAULT_MILVUS_COLLECTION,
    )
