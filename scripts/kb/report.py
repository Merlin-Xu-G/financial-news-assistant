"""阶段结果结构与失败清单落盘。

摘要格式与失败记录字段定义见 specs/001-kb-vector-pipeline/contracts/cli.md。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple


class Failure(NamedTuple):
    """单条失败记录。"""

    key: str
    reason: str


class StageResult(NamedTuple):
    """单个阶段的执行结果。"""

    processed: int = 0
    skipped: int = 0
    failed: int = 0
    failures: tuple[Failure, ...] = ()


def summary(stage: str, result: StageResult, elapsed: float) -> str:
    """生成固定格式的单行摘要。"""
    return (
        f"[{stage}] 处理={result.processed} 跳过={result.skipped} "
        f"失败={result.failed} 耗时={elapsed:.1f}s"
    )


def write_failures(path: Path, stage: str, result: StageResult) -> None:
    """把失败项追加写入 failures.jsonl，每行含 time / stage / key / reason。"""
    if not result.failures:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for failure in result.failures:
            record = {
                "time": datetime.now(timezone.utc).isoformat(),
                "stage": stage,
                "key": failure.key,
                "reason": failure.reason,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
