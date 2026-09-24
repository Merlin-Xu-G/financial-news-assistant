"""命令行入口：参数解析、阶段调度、退出码。

契约见 specs/001-kb-vector-pipeline/contracts/cli.md。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from . import index
from .config import (
    BATCH_SIZE,
    MAX_RETRIES,
    QPS,
    ConfigError,
    DependencyError,
    Paths,
    resolve_paths,
)
from .report import StageResult, summary, write_failures

EXIT_OK = 0
EXIT_INPUT = 1
EXIT_DEPENDENCY = 2
EXIT_PARTIAL = 3
EXIT_INTERRUPTED = 130

STAGES = ("index",)


class Parser(argparse.ArgumentParser):
    """把参数错误的退出码从 argparse 默认的 2 改成契约要求的 1。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"参数错误：{message}", file=sys.stderr)
        raise SystemExit(EXIT_INPUT)


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", help="数据根目录，默认 <项目根>/data")
    parser.add_argument("--symbols", help="逗号分隔的股票代码子集")
    parser.add_argument("--limit", type=int, help="只处理排序后的前 N 条")
    parser.add_argument("--verbose", action="store_true", help="输出 DEBUG 级日志")


def add_index_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help=f"每批提交的片段数（默认 {BATCH_SIZE}）")
    parser.add_argument("--qps", type=float, default=QPS, help=f"嵌入接口限速（默认 {QPS}）")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES, help=f"单批重试上限（默认 {MAX_RETRIES}）")


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="python -m scripts.kb", description="知识库向量入库")
    stages = parser.add_subparsers(dest="stage", required=True)

    stage_index = stages.add_parser("index", help="把片段向量化并写入向量库")
    add_common_options(stage_index)
    add_index_options(stage_index)

    return parser


def parse_symbols(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def execute(stage: str, paths: Paths, args: argparse.Namespace) -> StageResult:
    symbols = parse_symbols(args.symbols)
    if stage == "index":
        return index.run(
            paths,
            symbols=symbols,
            limit=args.limit,
            batch_size=args.batch_size,
            qps=args.qps,
            max_retries=args.max_retries,
        )
    raise AssertionError(f"未注册的阶段：{stage}")


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_stage(stage: str, paths: Paths, args: argparse.Namespace) -> int:
    """执行单个阶段，打印摘要、落盘失败清单，返回退出码。"""
    started = time.monotonic()
    try:
        result = execute(stage, paths, args)
    except ConfigError as exc:
        print(f"[{stage}] 输入或配置错误：{exc}", file=sys.stderr)
        return EXIT_INPUT
    except DependencyError as exc:
        print(f"[{stage}] 依赖不可用：{exc}", file=sys.stderr)
        return EXIT_DEPENDENCY
    except KeyboardInterrupt:
        print(f"\n[{stage}] 已中断，进度已保存，重跑同一命令即可续跑", file=sys.stderr)
        return EXIT_INTERRUPTED

    print(summary(stage, result, time.monotonic() - started))
    write_failures(paths.failures, stage, result)
    return EXIT_PARTIAL if result.failed else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    if args.limit is not None and args.limit <= 0:
        print("参数错误：--limit 必须大于 0", file=sys.stderr)
        return EXIT_INPUT

    try:
        paths = resolve_paths(args.data_dir)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return EXIT_INPUT

    return run_stage(args.stage, paths, args)
