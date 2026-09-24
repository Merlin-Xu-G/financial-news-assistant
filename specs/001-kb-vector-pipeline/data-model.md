# Phase 1 Data Model: 金融知识库向量化入库流水线

**Feature**: `001-kb-vector-pipeline` | **Date**: 2026-09-21

本文件定义流水线涉及的四个实体、字段约束与它们之间的流转关系。字段结构以**现有产物的实际结构**为准（已核对 `data/kb/` 真实产物），不假设上游格式。

---

## 实体关系总览

```text
data/raw/**/*.json
      │
      │  阶段一 documents
      ▼
┌─────────────────────────┐        ┌──────────────────────────┐
│ 知识文档                 │        │ 结构化数值记录            │
│ data/kb/text/{symbol}.md │        │ data/kb/metrics.sqlite   │
└───────────┬─────────────┘        └──────────────────────────┘
            │                            （不进入向量库）
            │  阶段二 chunks
            ▼
┌─────────────────────────┐
│ 知识片段                 │
│ data/kb/chunks.jsonl     │
└───────────┬─────────────┘
            │  阶段三 index
            ▼
┌─────────────────────────┐
│ 向量记录                 │
│ Milvus collection fin_kb │
└─────────────────────────┘
```

**关键约束（宪法第 I 条）**：结构化数值记录与向量记录是**两条互不交叉的链路**。数值永不进入向量库，向量检索结果永不用作数值来源。

---

## E1. 知识文档（Knowledge Document）

**载体**：`data/kb/text/{symbol}.md`，一只股票一个文件，UTF-8

**结构**：

| 层级 | 格式 | 说明 |
| --- | --- | --- |
| 标题 | `# {公司名}（{symbol}）` | 公司名缺失时退化为 `# {symbol}` |
| 章节 | `## {章节名}` | 固定集合，顺序固定，无数据的章节整体省略 |
| 正文 | Markdown | 键值列表或自然段落 |

**章节集合**（顺序固定，来自现有产物实测）：

```text
基本信息 / 公司简介 / 注册地址 / 行业与概念 / 关键财务指标
营收结构（公司披露分部口径）/ 公司大事 / 机构评级 / 业务驱动分析 / 数据来源
```

**约束**：

- 标题中的公司名与代码必须来自 `companies` 表，不得臆造（FR-004）
- 无数据的章节**整体不出现**，不得输出空章节或占位符（FR-004）
- 同一输入重复执行产出完全一致（FR-005，SC-003）
- 文件写入必须原子（FR-027）

---

## E2. 结构化数值记录（Metric Record）

**载体**：`data/kb/metrics.sqlite`，6 张表，以 `symbol` 为关联键

| 表 | 主键 | 字段 | 用途 |
| --- | --- | --- | --- |
| `companies` | `symbol` | name_cn, name_en, exchange, currency, board, industry, sector, founded, headquarters, employees, website, market_cap, total_shares, circulating_shares, isin, figi_composite, updated_at | 公司基础档案 |
| `metrics` | `(symbol, source, item_id, period_type, period_date)` | item_name, group_name, value, ttm, current_value | 财务与估值指标 |
| `events` | `(symbol, date, date_type, act_type)` | act_desc | 分红、财报日等事件 |
| `ratings` | `(symbol, date)` | buy, over_count, hold, under_count, sell, no_opinion, total | 机构评级分布 |
| `revenue_breakdown` | `(symbol, date, dimension, name)` | percent, value | 营收结构 |
| `earnings` | `(symbol, period_key, period_type)` | eps_actual, eps_estimate, eps_percent, revenue_actual, revenue_estimate, revenue_percent, is_reported | 业绩预期与实际 |

**约束**：

- **本实体不进入向量库**（宪法第 I 条）
- 数值缺失时保留 NULL 并标注来源，不得臆造单位或数值（spec Edge Case）
- 同一输入重复执行结果一致（幂等，FR-005）

---

## E3. 知识片段（Chunk）

**载体**：`data/kb/chunks.jsonl`，一行一条 JSON

**字段**：

| 字段 | 类型 | 约束 | 来源 |
| --- | --- | --- | --- |
| `id` | string | 非空、全库唯一、确定性生成 | `{symbol}::{section}` 或 `{symbol}::{section}（{part}/{parts}）` |
| `symbol` | string | 非空，格式 `6位数字.交易所后缀` | E1 标题 |
| `name` | string | 可为空（缺失时降级） | E1 标题 |
| `section` | string | 非空 | E1 章节名 |
| `part` | int | ≥ 1 | 分片序号 |
| `parts` | int | ≥ `part` | 该章节总分片数 |
| `chars` | int | > 0 | 正文字符数 |
| `text` | string | 非空，自带上下文头 | `{name}（{symbol}）｜{section}\n{正文}` |

**标识生成规则**（确定性，FR-007）：

```text
单分片章节：  {symbol}::{section}
多分片章节：  {symbol}::{section}（{part}/{parts}）
```

**约束**：

- 切分只在语义边界（句子）处进行，禁止句中硬截断（FR-010）
- 超长章节拆分后相邻片保留重叠内容（FR-011）
- 长度上限与重叠长度可配置，有合理默认（FR-012）
- 空章节不产出片段（FR-009 边界）
- 同一输入重复执行产出片段集合完全一致（FR-013，SC-003）

---

## E4. 向量记录（Vector Record）

**载体**：Milvus collection `fin_kb`（契约详见 [`contracts/milvus-schema.md`](./contracts/milvus-schema.md)）

| 字段 | 类型 | 约束 | 用途 |
| --- | --- | --- | --- |
| `id` | VARCHAR(128) | **主键**，等于 E3 的 `id` | 幂等写入的键 |
| `vector` | FLOAT_VECTOR(dim) | dim 由配置决定 | 语义检索 |
| `symbol` | VARCHAR(16) | 非空 | **标量过滤** |
| `name` | VARCHAR(64) | 可空 | 结果展示 |
| `section` | VARCHAR(64) | 非空 | **标量过滤** |
| `part` | INT16 | ≥ 1 | 结果展示 |
| `parts` | INT16 | ≥ 1 | 结果展示 |
| `text` | VARCHAR(8192) | 非空 | 结果正文 |
| `content_hash` | VARCHAR(64) | 非空 | 内容指纹，支撑「未变则跳过、已变则更新」 |

**约束**：

- 以 `id` 为键 `upsert`，重复写入不增记录、内容变更则更新（FR-015、FR-016）
- 维度与集合定义不符时**明确报错**，不得删除重建（FR-021）
- 写入分批进行，单批失败不中断整体（FR-018）
- 向量库不可达时明确失败并停止（FR-020）

**字段裁剪说明**：E3 的 `chars` **不进入**向量记录——它既不参与过滤也不参与展示，仅用于阶段二的统计输出。保留它是无用的存储负担（宪法第 IV 条）。

---

## 状态流转

三个阶段各自维护独立进度，互不阻塞：

| 阶段 | 输入存在判定 | 已完成判定 | 中断后续跑方式 |
| --- | --- | --- | --- |
| 一 `documents` | `data/raw/{endpoint}/{symbol}.json` 存在 | 目标文档已生成 | 重跑覆盖，天然幂等 |
| 二 `chunks` | `data/kb/text/{symbol}.md` 存在 | 清单已包含该股票的片段 | 全量重建清单（片段集合由文档确定性推导） |
| 三 `index` | `data/kb/chunks.jsonl` 存在 | 向量库中已存在该 `id` | **按批查询向量库，已存在的跳过**（不重复调用嵌入接口） |

**阶段三的续跑是本设计的成本关键点**：嵌入接口按调用计费，跳过已入库片段既满足 FR-024，也避免重复计费（见 `research.md` R7）。

---

## 校验规则汇总

| 规则 | 来源 | 违反时的行为 |
| --- | --- | --- |
| `id` 唯一且确定性生成 | FR-007 | 生成阶段即保证，无需运行时校验 |
| `symbol` 格式合法 | spec Assumptions | 跳过该股票并记录 |
| `part ≤ parts` 且均 ≥ 1 | E3 | 生成阶段即保证 |
| `text` 非空 | FR-006 | 空章节不产出片段 |
| `vector` 长度 == 集合维度 | FR-021 | 明确报错并停止 |
| 数值字段不得来自向量检索 | 宪法第 I 条 | 架构上隔离：两条链路无交叉 |
