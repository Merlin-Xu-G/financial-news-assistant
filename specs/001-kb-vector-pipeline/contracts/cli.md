# Contract: 知识库流水线命令行接口

**Feature**: `001-kb-vector-pipeline` | **Date**: 2026-09-21

本契约定义统一入口的命令形态、参数语义与退出码。实现必须与此一致。

---

## 调用形式

```bash
python -m scripts.kb <stage> [options]
```

`scripts/kb/` 为常规包（含 `__init__.py`）；`scripts/` 作为隐式命名空间包无需额外标记文件。此形式避免在代码中插入 `sys.path` 操作，也避免依赖「脚本所在目录自动入路径」这一隐式行为。

---

## 阶段（stage）

| stage | 输入 | 输出 | 对应 spec |
| --- | --- | --- | --- |
| `documents` | `data/raw/{endpoint}/{symbol}.json` | `data/kb/text/{symbol}.md`、`data/kb/metrics.sqlite` | 用户故事 1 |
| `chunks` | `data/kb/text/{symbol}.md` | `data/kb/chunks.jsonl` | 用户故事 2 |
| `index` | `data/kb/chunks.jsonl` | Milvus collection `fin_kb` | 用户故事 3 |
| `all` | 同上（链式） | 同上（全部） | FR-022 |

**约定**：

- `all` 等价于依次执行 `documents` → `chunks` → `index`；任一步失败则**停止后续阶段**并以该步退出码结束。
- 每个 stage 必须可独立执行（FR-022），且不隐式触发上下游。

---

## 通用参数

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--data-dir` | path | `data` | 数据根目录，所有产物路径基于此展开 |
| `--symbols` | string | 全部 | 逗号分隔的股票代码子集，如 `000001.SZ,600519.SH` |
| `--limit` | int | 无 | 只处理排序后的前 N 只，用于小样本验证 |
| `--verbose` | flag | off | 输出 DEBUG 级日志 |

---

## 各阶段专有参数

### `documents`

无专有参数。输入路径由 `--data-dir` 推导为 `{data-dir}/raw`。

### `chunks`

| 参数 | 类型 | 默认 | 约束 |
| --- | --- | --- | --- |
| `--max-chars` | int | `600` | 必须 > 0 |
| `--overlap` | int | `80` | 必须 ≥ 0 且 < `--max-chars` |

### `index`

| 参数 | 类型 | 默认 | 约束 |
| --- | --- | --- | --- |
| `--batch-size` | int | `16` | 每批提交嵌入接口的片段数，必须 > 0 |
| `--qps` | float | `1.0` | 嵌入接口调用速率上限，必须 > 0 |
| `--max-retries` | int | `4` | 单批重试上限 |

---

## 配置来源

环境变量从项目根目录 `.env` 读取（沿用 `infoway_client.load_dotenv` 的既有实现）。

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `EMBEDDING_BASE_URL` | 是（`index` 阶段） | OpenAI 兼容接口基址 |
| `EMBEDDING_API_KEY` | 是（`index` 阶段） | 密钥 |
| `EMBEDDING_MODEL` | 是（`index` 阶段） | 模型名 |
| `EMBEDDING_DIM` | 否 | 向量维度；留空则自动探测 |
| `MILVUS_URI` | 否 | 默认 `http://47.95.112.116:19530` |
| `MILVUS_COLLECTION` | 否 | 默认 `fin_kb` |

缺失必需变量时，必须在**发起任何网络请求之前**报错退出。

---

## 输出摘要

每个阶段结束必须向标准输出打印一行可读摘要（FR-019、FR-025），格式固定为：

```text
[{stage}] 处理={n} 跳过={n} 失败={n} 耗时={s}s
```

- `处理`：本次实际产出的条目数
- `跳过`：因已存在或已入库而未处理的条目数
- `失败`：记录到失败清单的条目数

失败清单落盘位置：`{data-dir}/kb/_meta/failures.jsonl`，一行一条，字段 `{time, stage, key, reason}`。

---

## 退出码

| 码 | 含义 | 触发场景 |
| --- | --- | --- |
| `0` | 全部成功 | 无失败项 |
| `1` | 输入/配置错误 | 参数非法、输入目录为空、必需环境变量缺失 |
| `2` | 依赖不可用 | 嵌入接口鉴权失败、向量库不可达、集合维度不匹配 |
| `3` | 部分失败 | 有失败项但流程完成（对应 FR-018） |
| `130` | 用户中断 | `Ctrl+C`；必须打印已完成的进度摘要 |

**注意**：`3` 与 `2` 的区分是刻意的——`2` 表示「整体不可继续」，`3` 表示「大部分成功但有可重试的失败项」。

---

## 验收要点

| 契约点 | 验证方式 | 对应 spec |
| --- | --- | --- |
| `all` 链式执行 | 一条命令跑完三个阶段，摘要依次打印 | FR-022 |
| 单阶段可独立执行 | 只跑 `chunks` 不触发 `documents` | FR-022 |
| `--symbols` 过滤生效 | 指定单只股票，产物只含该股票 | FR-022 |
| 中断可续跑 | `Ctrl+C` 后重跑，`跳过` 计数递增、`处理` 递减 | FR-024、SC-006 |
| 退出码语义正确 | 断开向量库跑 `index`，退出码为 `2` 而非 `3` | FR-020 |
| 摘要数字与产物一致 | 摘要 `处理=N` 与产物实际条数相等 | SC-007 |
