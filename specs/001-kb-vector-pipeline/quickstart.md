# Quickstart: 金融知识库向量化入库流水线

**Feature**: `001-kb-vector-pipeline` | **Date**: 2026-09-21

本文件是**验证指南**——按场景逐条执行，即可证明 feature 按规范工作。接口细节见 [`contracts/cli.md`](./contracts/cli.md) 与 [`contracts/milvus-schema.md`](./contracts/milvus-schema.md)，字段定义见 [`data-model.md`](./data-model.md)。

---

## 前置条件

| 项 | 要求 | 检查方式 |
| --- | --- | --- |
| Python | 3.12+ | `python --version` |
| 已装依赖 | `openai`、`numpy` | `python -m pip show openai` |
| 待装依赖 | `pymilvus>=2.4.0,<2.5.0` | `python -m pip install "pymilvus>=2.4.0,<2.5.0"` |
| 原始数据 | `data/raw/` 下已有抓取产物 | `ls data/raw` |
| Milvus | 可达且健康 | `curl http://47.95.112.116:19530/v2/vectordb/collections/list` |

**环境变量**（写入项目根 `.env`）：

```bash
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=<你的密钥>
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
EMBEDDING_DIM=                       # 留空则自动探测
MILVUS_URI=http://47.95.112.116:19530
MILVUS_COLLECTION=fin_kb
```

> 所有命令均在**项目根目录**执行。

---

## 场景 1：阶段一 — 单只股票生成知识文档

**目的**：验证用户故事 1（P1）与 FR-001～FR-005、FR-027。

```bash
python -m scripts.kb documents --symbols 000001.SZ
```

**预期结果**：

1. 标准输出打印摘要：`[documents] 处理=1 跳过=0 失败=0 耗时=…s`
2. 生成 `data/kb/text/000001.SZ.md`，首行为 `# 平安银行（000001.SZ）`
3. 文档含固定章节，且**无空章节、无占位符**
4. `data/kb/metrics.sqlite` 中 `companies` 表出现 `000001.SZ` 记录

**边界验证**：

```bash
# 取一只只有部分接口数据的股票
python -m scripts.kb documents --symbols <缺数据的代码>
```

预期：缺失章节**整体不出现**，其余章节正常产出，摘要 `失败=0`。

**幂等验证**：

```bash
python -m scripts.kb documents --symbols 000001.SZ
git diff --stat data/kb/text/000001.SZ.md
```

预期：`git diff` 无输出（产出与首次完全一致，FR-005）。

---

## 场景 2：阶段二 — 切分知识文档

**目的**：验证用户故事 2（P2）与 FR-006～FR-013。

```bash
python -m scripts.kb chunks --limit 10
```

**预期结果**：

1. 摘要：`[chunks] 处理=N 跳过=0 失败=0 耗时=…s`
2. 生成 `data/kb/chunks.jsonl`，每行含 `id / symbol / name / section / part / parts / chars / text`
3. 每条 `text` 以 `{公司名}（{代码}）｜{章节}` 开头（FR-009）

**片段独立性验证**（SC-002）：

随机取一条片段，单独阅读其 `text`，应能判断出所属公司与章节。

**参数生效验证**（FR-012）：

```bash
python -m scripts.kb chunks --limit 1 --max-chars 200 --overlap 40
```

预期：片段数明显增多，相邻片内容存在重叠，且 `parts` 标注正确。

**语义边界验证**（FR-010）：

检查产出片段，任意片段结尾不应出现被截断的半句话。

---

## 场景 3：阶段三 — 向量入库

**目的**：验证用户故事 3（P3）与 FR-014～FR-021。

```bash
python -m scripts.kb index --limit 10
```

**预期结果**：

1. 摘要：`[index] 处理=N 跳过=0 失败=0 耗时=…s`
2. Milvus 中自动出现集合 `fin_kb`，含向量索引与两个标量索引
3. 集合记录数与摘要 `处理` 数一致（SC-007）

**核对方式**：

```bash
curl -X POST http://47.95.112.116:19530/v2/vectordb/collections/list \
  -H "Content-Type: application/json" -d '{}'
```

或通过 Attu（`http://47.95.112.116:8000`）查看集合与索引。

---

## 场景 4：幂等性验证

**目的**：验证 FR-015 / FR-016 / SC-004。

```bash
# 记录当前总数
python -m scripts.kb index --limit 10
```

**预期**：

1. 摘要中 `跳过=N`、`处理=0`（全部已入库，不重复调用嵌入接口）
2. 集合记录总数与上一次完全一致

**内容更新验证**（FR-016）：

修改某只股票的原始数据 → 重跑 `documents` → `chunks` → `index`，集合总数不变，但对应片段内容已更新。

---

## 场景 5：断点续传验证

**目的**：验证 FR-024 / FR-026 / SC-003 / SC-006。

```bash
# 处理较大样本，中途 Ctrl+C
python -m scripts.kb index --limit 200
# 按 Ctrl+C

# 重新执行同一命令
python -m scripts.kb index --limit 200
```

**预期**：

1. 中断时打印已完成的进度摘要（退出码 130）
2. 重跑时 `跳过` 计数 > 0，`处理` 计数 < 首次
3. 最终集合记录总数与「一次性跑完」的结果一致（SC-003）

---

## 场景 6：失败隔离验证

**目的**：验证 FR-018 / FR-020 / SC-007。

**存储侧不可用**（应整体停止）：

```bash
MILVUS_URI=http://127.0.0.1:1 python -m scripts.kb index --limit 5
```

预期：明确报错，**退出码 2**，不产生半截数据。

**接口侧临时失败**（应隔离继续）：

临时将 `EMBEDDING_API_KEY` 改为非法值后执行。

预期：鉴权类错误**退出码 2**（整体不可继续）；若为速率类错误则退避重试，单批最终失败时记录到 `data/kb/_meta/failures.jsonl` 并以**退出码 3** 结束，其余批次正常入库。

---

## 场景 7：全量运行

> ⚠️ **前置条件**：采集任务已跑完（`data/raw/` 覆盖全部股票）。采集未完成时执行全量只会处理已有部分，属预期行为。

```bash
python -m scripts.kb all
```

**预期**：

1. 三个阶段依次执行，各自打印摘要
2. 全程无需人工干预（SC-001）
3. 结束后 Milvus 记录数 = `chunks.jsonl` 行数

---

## 故障排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `EMBEDDING_API_KEY` 缺失报错 | `.env` 未配置 | 补齐三个 `EMBEDDING_*` 变量 |
| 退出码 2 且提示维度不匹配 | `EMBEDDING_DIM` 与集合实际维度不一致 | 修正配置，**不要删除集合**；确认无误后再决定是否重建 |
| 大量 429 | `--qps` 过高 | 降低 `--qps`，或减小 `--batch-size` |
| `跳过` 计数异常高 | 该数据此前已入库 | 正常行为（幂等），如需重算请先清理集合 |
| 摘要 `失败` > 0 | 查看 `data/kb/_meta/failures.jsonl` | 按 `reason` 分类处理，可单独重试 |
| 集合不存在 | 首次运行 | 正常，自动创建 |

---

## 验收清单

| # | 场景 | 对应 spec | 通过标准 |
| --- | --- | --- | --- |
| 1 | 单只股票生成文档 | US1 / FR-001~005 | 章节齐全、无空章节、重复执行结果一致 |
| 2 | 切分文档 | US2 / FR-006~013 | 片段自带上下文头、超长章节正确拆分、参数可调 |
| 3 | 向量入库 | US3 / FR-014~021 | 集合自动创建、记录数与摘要一致 |
| 4 | 幂等性 | FR-015 / FR-016 / SC-004 | 重复执行总数不变、内容可更新 |
| 5 | 断点续传 | FR-024 / SC-003 / SC-006 | 重跑跳过已完成、最终结果一致 |
| 6 | 失败隔离 | FR-018 / FR-020 / SC-007 | 存储侧停止、接口侧隔离继续 |
| 7 | 全量运行 | SC-001 | 无需人工干预跑完全部 |
