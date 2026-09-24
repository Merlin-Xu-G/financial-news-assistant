# Implementation Plan: 金融知识库向量化入库流水线

**Branch**: `001-kb-vector-pipeline` | **Date**: 2026-09-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-kb-vector-pipeline/spec.md`

## Summary

把已抓取的原始接口数据，经「知识文档生成 → 片段切分 → 向量入库」三个阶段，变成可按股票代码与章节过滤的语义检索知识库。

技术路径：把现有两个可用脚本（`ingest_kb.py` / `chunk_kb.py`）与新入库环节统一到一个 `scripts/kb/` 包下，共用一套配置与 CLI 入口；向量表示通过 OpenAI 兼容的 embeddings 接口获取（同时覆盖硅基流动与阿里云百炼），写入已部署的 Milvus standalone 实例。

## Technical Context

**Language/Version**: Python 3.12+（本地 3.13.8 / 服务器 3.12.3）

**Primary Dependencies**:
- `pymilvus`（**新增**，需固定为 2.4.x 以匹配服务端 `milvusdb/milvus:v2.4.0-rc.1`）
- `openai`（已装 2.14.0，用于调用 OpenAI 兼容的 embeddings 接口）
- 标准库：`argparse` / `logging` / `json` / `sqlite3` / `pathlib` / `os` / `re`

**Storage**:
- 向量库：Milvus standalone `47.95.112.116:19530`（已部署，当前无集合）
- 文件产物：`data/kb/text/*.md`（知识文档）、`data/kb/metrics.sqlite`（结构化数值）、`data/kb/chunks.jsonl`（片段清单）

**Testing**: 无自动化测试（宪法未强制，用户明确跳过）；以 `quickstart.md` 的手工验证场景为准

**Target Platform**: Windows 开发机执行批处理；Milvus 在 Linux 服务器

**Project Type**: CLI 数据管道（非服务、非库）

**Performance Goals**:
- 单只股票全流程（文档 → 切分 → 入库）≤ 10 秒（SC-006）
- 按股票过滤的语义检索 ≤ 1 秒返回（SC-005）

**Constraints**:
- 嵌入接口有速率限制，必须限速 + 退避重试（宪法第 VI 条）
- 向量维度由所选模型决定，必须可配置
- 全流程中断后可续跑（FR-024）
- 依赖最小化：除 `pymilvus` 外不引入新依赖（宪法第 IV 条）

**Scale/Scope**: 5000+ 只股票，每只约 8–15 个片段，预计 5–8 万条向量记录

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法条款 | 本设计的落实方式 | 判定 |
| --- | --- | --- |
| **I. 数据不可信（NON-NEGOTIABLE）** | 精确数值只进 `metrics.sqlite`，**不进入向量库**；向量库仅承载定性文本。任何数值类问题走结构化查询，禁止用语义检索结果充当数值来源 | ✅ 通过 |
| **II. 可追溯** | 片段标识由「股票代码 + 章节 + 分片序号」确定性生成；向量记录携带 `symbol`/`name`/`section` 元数据，检索结果可回溯到具体文档章节 | ✅ 通过 |
| **III. 合规免责** | 本阶段为数据管道，不产出面向用户的结论；知识文档只转述原始数据，不生成判断性表述 | ✅ 通过 |
| **IV. 代码简洁（NON-NEGOTIABLE）** | 仅新增 1 个依赖（`pymilvus`）；包内 6 个文件各担一职；不引入抽象基类/插件机制/配置框架；常量具名；禁止吞异常 | ✅ 通过 |
| **V. 规范驱动** | 本 plan 由 `/speckit.specify` 产物驱动，任务清单由 `/speckit.tasks` 生成 | ✅ 通过 |
| **VI. 采集克制与可恢复** | 嵌入接口调用限速 + 429 退避（沿用 `infoway_client.py` 已验证的模式）；失败分级记录；断点续传按片段标识跳过已入库项 | ✅ 通过 |

**结论**：无违反项，无需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/001-kb-vector-pipeline/
├── plan.md              # 本文件
├── research.md          # Phase 0：技术选型决策
├── data-model.md        # Phase 1：实体与字段定义
├── quickstart.md        # Phase 1：验证指南
├── contracts/           # Phase 1：接口契约
│   ├── cli.md           #   命令行契约
│   └── milvus-schema.md #   向量库集合契约
├── checklists/
│   └── requirements.md  # 需求质量检查表
└── tasks.md             # Phase 2 产物（/speckit.tasks 生成，非本命令）
```

### Source Code (repository root)

```text
scripts/
├── kb/                      # 知识库流水线（本 feature 主体）
│   ├── __init__.py
│   ├── __main__.py          # 包入口：使 `python -m scripts.kb` 可用
│   ├── cli.py               # 命令行：参数解析、阶段调度、退出码
│   ├── config.py            # 路径常量、默认参数、环境读取与校验
│   ├── report.py            # 结果结构、摘要输出、失败清单落盘
│   ├── documents.py         # 阶段一 · E1 知识文档
│   ├── metrics.py           # 阶段一 · E2 结构化数值（sqlite）
│   ├── chunks.py            # 阶段二 · E3 知识片段
│   ├── index.py             # 阶段三：嵌入 + 幂等写入编排
│   └── store.py             # 阶段三 · E4 向量库集合与客户端
├── infoway_client.py        # 保持不变（采集层，本 feature 不动）
├── fetch_fundamentals.py    # 保持不变（采集层，本 feature 不动）
├── ingest_kb.py             # 迁移至 kb/documents.py + kb/metrics.py 后移除
├── chunk_kb.py              # 迁移至 kb/chunks.py 后移除
└── run_pipeline.ps1         # 改为调用统一入口
```

**Structure Decision**:

选择单一 `scripts/kb/` 包，模块边界对齐 `data-model.md` 的实体边界。理由：

1. **用户明确选择「重构统一」** —— 三个阶段共用路径常量、日志格式、统计输出，分散在三个顶层脚本会导致重复定义。
2. **按实体拆分而非按阶段拆分** —— 现有 `ingest_kb.py` 有 673 行，其中 `build_document()` 单函数就占 250 行，同时承担「生成知识文档」与「抽取结构化数值」两件事。这两件事对应 `data-model.md` 的 E1 与 E2，是**互不交叉的两条链路**（宪法第 I 条要求数值与文本彻底隔离）。拆成 `documents.py` / `metrics.py` 是沿着既有边界切分，不是新增抽象。
3. **`store.py` 独立于 `index.py`** —— 集合定义、索引参数、维度校验属于「基础设施关注点」，与「流水线编排」正交；且需被未来的检索工具复用。
4. **`report.py` 独立** —— 三个阶段产出同构的结果与失败记录，是真实的共用点；放在 `cli.py` 会造成「阶段模块 ← cli ← 阶段模块」的循环导入。
5. **`config.py` 独立** —— 路径与默认参数被全部模块引用，集中定义避免魔法字符串。
6. **采集层（`fetch_fundamentals.py` / `infoway_client.py`）不动** —— 已验证可用且与知识库流水线无耦合，改动它们违反 YAGNI。

**迁移策略**：`ingest_kb.py` / `chunk_kb.py` 的逻辑**平移**进 `kb/` 包，不重写算法；仅按实体边界拆函数。迁移后删除原文件，`run_pipeline.ps1` 改指向统一入口。

## Complexity Tracking

> 无宪法违反项，本节留空。
