---
description: "Task list for 金融知识库向量化入库流水线"
---

# Tasks: 金融知识库向量化入库流水线

**Input**: Design documents from `/specs/001-kb-vector-pipeline/`

**Prerequisites**: plan.md ✅、spec.md ✅、research.md ✅、data-model.md ✅、contracts/ ✅

**Tests**: 本 feature 不含自动化测试任务（宪法未强制、用户明确跳过）。每个用户故事以 `quickstart.md` 的对应场景作为验收方式。

**Organization**: 任务按用户故事分组，每个故事可独立实现与验收。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1 / US2 / US3）
- 每条任务含确切文件路径

## Path Conventions

项目根目录为仓库根，源码在 `scripts/`，设计文档在 `specs/001-kb-vector-pipeline/`。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 依赖与包骨架

- [ ] T001 安装并锁定向量库客户端依赖：执行 `python -m pip install "pymilvus>=2.4.0,<2.5.0"`，并把该约束写入 `requirements.txt`（服务端为 `milvusdb/milvus:v2.4.0-rc.1`，跨大版本会导致协议不兼容）
- [ ] T002 创建包骨架：`scripts/kb/__init__.py`（仅包声明与一行模块说明）与 `scripts/kb/__main__.py`（转调 `cli.main()` 并以 `raise SystemExit` 结束），使 `python -m scripts.kb` 可用

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 被全部三个阶段共用的基础模块

**⚠️ CRITICAL**: 本阶段完成前，任何用户故事都无法开始

- [ ] T003 实现 `scripts/kb/config.py`：定义路径常量（`DATA_DIR`、`RAW_DIR`、`KB_TEXT_DIR`、`METRICS_DB`、`CHUNKS_JSONL`、`META_DIR`、`FAILURES_JSONL`）、默认参数（`MAX_CHARS=600`、`OVERLAP=80`、`BATCH_SIZE=16`、`QPS=1.0`、`MAX_RETRIES=4`）、`.env` 读取（复用 `infoway_client.load_dotenv`），以及嵌入与向量库配置的读取与**必填校验**（缺失必需变量时在发起任何网络请求前报错）
- [ ] T004 [P] 实现 `scripts/kb/report.py`：`StageResult` 结构（字段 `processed` / `skipped` / `failed` / `failures`）、摘要行格式化（固定格式 `[{stage}] 处理={n} 跳过={n} 失败={n} 耗时={s}s`，见 `contracts/cli.md`）、失败清单追加写入 `data/kb/_meta/failures.jsonl`（每行 `{time, stage, key, reason}`）

**Checkpoint**: `config.py` 与 `report.py` 可独立导入并通过基本调用验证

---

## Phase 3: User Story 1 - 原始采集数据生成结构化知识文档 (Priority: P1) 🎯 MVP

**Goal**: 把原始接口响应转成每只股票一份、按固定章节组织的知识文档，同时把精确数值抽成结构化记录

**Independent Test**: 执行 `python -m scripts.kb documents --symbols 000001.SZ`，检查 `data/kb/text/000001.SZ.md` 章节齐全、无空章节、`metrics.sqlite` 中 `companies` 表出现该股票记录

### Implementation for User Story 1

- [ ] T005 [US1] 在 `scripts/kb/documents.py` 中迁移 `scripts/ingest_kb.py` 的格式化与数据辅助函数：`money` / `shares` / `number` / `percent` / `fmt` / `clean` / `load` / `latest_by_item` / `date_from_unix` / `date_from_compact`，以及中文映射常量 `EXCHANGE_CN` / `BOARD_CN` / `PERIOD_CN`。**逻辑平移，不重写算法**
- [ ] T006 [US1] 在 `scripts/kb/documents.py` 中把 `ingest_kb.py:193` 的 `build_document()`（现 250 行）按章节拆成独立构造函数：`基本信息` / `公司简介` / `注册地址` / `行业与概念` / `关键财务指标` / `营收结构（公司披露分部口径）` / `公司大事` / `机构评级` / `业务驱动分析` / `数据来源`（共 10 个，以 `scripts/ingest_kb.py` 中 `lines.append("## ...")` 的 10 处为准），再由一个 `build_document()` 组装。**章节顺序固定**，无数据的章节**整体省略**（不得输出空章节或占位符，FR-004），标题格式 `# {公司名}（{symbol}）`，公司名缺失时退化为 `# {symbol}`
- [ ] T007 [P] [US1] 实现 `scripts/kb/metrics.py`：迁移 `ingest_kb.py:447` 起的 sqlite 层（`init_db` / `as_float` / `as_int` / `write_metrics`）与指标常量（`STAT_METRICS` / `INCOME_METRICS` / `CASHFLOW_METRICS` / `BALANCE_METRICS`），建表语句须与现有 `data/kb/metrics.sqlite` **完全一致**（6 张表：`companies` / `metrics` / `events` / `ratings` / `revenue_breakdown` / `earnings`，字段定义见 `data-model.md` E2）
- [ ] T008 [US1] 在 `scripts/kb/documents.py` 中实现 `run()` 编排：发现股票（`discover_symbols`）、逐只生成文档并写入 `data/kb/text/{symbol}.md`、调用 `metrics.write()` 写库、返回 `StageResult`。**知识文档必须原子写入**（临时文件 + `os.replace`，FR-027）；同一输入重复执行产出完全一致（FR-005）
- [ ] T009 [US1] 实现 `scripts/kb/cli.py`：argparse 子命令框架（`documents` / `chunks` / `index` / `all`，本阶段只需 `documents` 可跑）、通用参数（`--data-dir` / `--symbols` / `--limit` / `--verbose`）、退出码映射（`0` 成功 / `1` 输入配置错误 / `2` 依赖不可用 / `3` 部分失败 / `130` 用户中断，见 `contracts/cli.md`）
- [ ] T010 [US1] 按 `quickstart.md` **场景 1** 验证：单只股票生成文档、边界（缺数据的股票不产出空章节）、幂等（重复执行 `git diff` 无变化）

**Checkpoint**: `python -m scripts.kb documents --symbols 000001.SZ` 可独立跑通，US1 即为可交付 MVP

---

## Phase 4: User Story 2 - 知识文档切成可检索片段 (Priority: P2)

**Goal**: 把知识文档按业务章节切成语义完整的片段，每片自带出处信息

**Independent Test**: 执行 `python -m scripts.kb chunks --limit 10`，检查 `data/kb/chunks.jsonl` 每行含完整元数据、`text` 以 `{公司名}（{代码}）｜{章节}` 开头、超长章节被正确拆分

### Implementation for User Story 2

- [ ] T011 [US2] 实现 `scripts/kb/chunks.py`：迁移 `scripts/chunk_kb.py` 的切分逻辑（`split_sentences` / `pack_sentences` / `chunk_document`）。约束：只在句子边界切分（禁止句中硬截断，FR-010）；长度上限与重叠可配置且默认 `max_chars=600`、`overlap=80`（FR-012）；空章节不产出片段；**标识生成规则**（FR-007）—— 单分片 `{symbol}::{section}`，多分片 `{symbol}::{section}（{part}/{parts}）`
- [ ] T012 [US2] 在 `scripts/kb/chunks.py` 中实现 `run()`：读取 `data/kb/text/*.md`、全量重建 `data/kb/chunks.jsonl`、返回 `StageResult`。**原子写入**（临时文件 + `os.replace`，FR-027）；同一输入重复执行产出片段集合完全一致（FR-013）
- [ ] T013 [US2] 在 `scripts/kb/cli.py` 中注册 `chunks` 子命令及其专有参数 `--max-chars`（默认 600，须 > 0）与 `--overlap`（默认 80，须 ≥ 0 且 < `--max-chars`）
- [ ] T014 [US2] 按 `quickstart.md` **场景 2** 验证：片段独立性（脱离原文可判断归属）、参数生效（`--max-chars 200 --overlap 40` 片段数增多且有重叠）、语义边界（无半句截断）

**Checkpoint**: US1 + US2 均可独立跑通

---

## Phase 5: User Story 3 - 分片写入向量库并可检索 (Priority: P3)

**Goal**: 把片段向量化并写入向量库，支持按股票代码与章节过滤

**Independent Test**: 执行 `python -m scripts.kb index --limit 10`，检查 Milvus 中自动出现集合 `fin_kb`（含向量索引与两个标量索引）、记录数与摘要一致；重复执行 `跳过` 计数递增且总数不变

### Implementation for User Story 3

- [ ] T015 [US3] 实现 `scripts/kb/store.py`：集合定义、索引创建、客户端获取、维度校验。**字段定义必须逐字遵守 `contracts/milvus-schema.md`**：`id` VARCHAR(max_length=128, is_primary=True)、`vector` FLOAT_VECTOR(dim=EMBEDDING_DIM)、`symbol` VARCHAR(max_length=16)、`name` VARCHAR(max_length=64) 可空、`section` VARCHAR(max_length=64)、`part` INT16、`parts` INT16、`text` VARCHAR(max_length=8192)；**不含 `chars` 字段**。**索引**：向量索引 `HNSW`（`M=16`、`efConstruction=200`、`metric_type=COSINE`），标量索引 `INVERTED` 建在 `symbol` 与 `section` 上。**硬性规则**：集合已存在时绝不删除或重建（FR-021）；维度不匹配时明确报错并以退出码 2 结束
- [ ] T016 [US3] 在 `scripts/kb/index.py` 中实现嵌入客户端：用已装的 `openai` SDK 指向 `EMBEDDING_BASE_URL`（OpenAI 兼容接口，同时覆盖硅基流动与百炼）、批量提交、限速（默认 1.0 QPS）、429 指数退避重试（默认上限 4 次）、`EMBEDDING_DIM` 留空时用单条样本探测实际维度
- [ ] T017 [US3] 在 `scripts/kb/index.py` 中实现 `run()` 编排：读取 `chunks.jsonl` → 按 `--batch-size`（默认 16）分批 → **每批先查向量库中已存在的 `id` 并跳过**（避免重复调用计费接口，FR-024）→ 对剩余片段嵌入 → `upsert` 写入。**失败分级**：向量库不可达 → 明确报错并停止（FR-020，退出码 2）；单批嵌入最终失败 → 记录到失败清单并继续后续批次（FR-018，退出码 3）
- [ ] T018 [US3] 在 `scripts/kb/cli.py` 中注册 `index` 子命令（专有参数 `--batch-size` 默认 16、`--qps` 默认 1.0、`--max-retries` 默认 4）与 `all` 子命令（依次执行 `documents` → `chunks` → `index`，任一步失败即停止后续阶段并以该步退出码结束）
- [ ] T019 [US3] 按 `quickstart.md` **场景 3、4、5、6** 验证：入库成功、幂等（重复执行总数不变）、断点续传（中断重跑 `跳过` 递增）、失败隔离（存储侧退出码 2、接口侧退出码 3）

**Checkpoint**: 三个用户故事全部可独立跑通，`python -m scripts.kb all` 可一键跑完

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 收尾与旧结构清理

- [ ] T020 更新 `scripts/run_pipeline.ps1`：把 `ingest_kb.py` / `chunk_kb.py` 的两次调用改为统一入口 `python -m scripts.kb all`，保留既有的分阶段日志写入 `data/raw/_meta/pipeline.log`
- [ ] T021 删除已迁移的旧脚本 `scripts/ingest_kb.py` 与 `scripts/chunk_kb.py`（迁移完成且 T010/T014 验证通过后方可执行）
- [ ] T022 [P] 清理 `scripts/__pycache__/` 中 `ingest_kb` / `chunk_kb` 的 `.pyc` 残留文件
- [ ] T023 按 `quickstart.md` **场景 7** 执行全量验证（`python -m scripts.kb all`）。⚠️ 前置条件：采集任务已跑完，`data/raw/` 覆盖全部股票
- [ ] T024 [P] 在 `README.md` 中补充知识库流水线的入口说明与三步命令，指向 `specs/001-kb-vector-pipeline/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，可立即开始
- **Foundational (Phase 2)**: 依赖 Phase 1，**阻塞全部用户故事**
- **User Stories (Phase 3–5)**: 均依赖 Phase 2
  - US1 → US2 → US3 顺序执行（后者的输入是前者的产物，属于数据依赖而非代码依赖）
  - 三个故事均可独立执行与验收（FR-022）
- **Polish (Phase 6)**: 依赖 US1 / US2 / US3 全部完成

### User Story Dependencies

- **US1 (P1)**: Phase 2 完成后即可开始，无其他故事依赖
- **US2 (P2)**: 代码上独立（只依赖 `config.py` / `report.py`），但验收需要 US1 产出的 `data/kb/text/*.md`
- **US3 (P3)**: 代码上独立（只依赖 `config.py` / `report.py` / `store.py`），但验收需要 US2 产出的 `chunks.jsonl`

### 同文件触点（需顺序执行）

`scripts/kb/cli.py` 被 T009（创建）、T013、T018 依次修改 —— 三条任务**不可并行**。

### Within Each User Story

- 辅助函数 → 核心构造 → 编排 → CLI 注册 → 验证
- 每个故事结束时必须通过对应的 quickstart 场景

### Parallel Opportunities

- T004 与 T003 可并行（不同文件）
- T007 与 T005 / T006 可并行（`metrics.py` 与 `documents.py` 不同文件）
- T011（chunks.py）与 T015 / T016（store.py / index.py）可并行 —— 前提是 Phase 2 已完成
- T022 与 T024 可并行（不同文件）

---

## Parallel Example: User Story 1

```bash
# T007 与 T005/T006 落在不同文件，可同时进行：
Task: "实现 scripts/kb/metrics.py：迁移 sqlite 层与指标常量"
Task: "在 scripts/kb/documents.py 中迁移格式化辅助函数与章节构造函数"
```

## Parallel Example: US2 与 US3 的代码实现

```bash
# Phase 2 完成后，两个故事的实现任务可并行（验收仍需按序）：
Task: "实现 scripts/kb/chunks.py 的切分逻辑与 run()"
Task: "实现 scripts/kb/store.py 的集合定义与维度校验"
Task: "实现 scripts/kb/index.py 的嵌入客户端"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（**关键，阻塞全部故事**）
3. 完成 Phase 3: User Story 1
4. **停下来验收**：跑 `quickstart.md` 场景 1
5. 此时已产出可读、可审计的公司档案，本身即有独立价值

### Incremental Delivery

1. Setup + Foundational → 基础就位
2. US1 → 验收场景 1 → 知识文档产出（**MVP**）
3. US2 → 验收场景 2 → 片段清单产出
4. US3 → 验收场景 3–6 → 向量库可检索
5. Polish → 旧脚本清理、全量验证

### 关键风险提示

- **T015 的字段定义不可自行发挥** —— 集合一旦建错维度，只能删库重建，会丢失已入库数据
- **T021 删除旧脚本前必须确认 T010 / T014 通过** —— 否则回退无路
- **T023 全量验证必须等采集完成** —— 采集未完成时执行 `all` 只会处理已有部分，属预期行为而非缺陷

---

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- [Story] 标签用于把任务追溯到 `spec.md` 的用户故事
- 每条任务都标注了对应的 FR 编号，便于 `/speckit.analyze` 做一致性核对
- 建议每个任务或每组逻辑任务完成后提交一次
- 每个 Checkpoint 都可停下来独立验收
