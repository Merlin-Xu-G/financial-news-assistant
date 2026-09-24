# financial-news-assistant

Financial news assistant.

## 知识库

知识库由 **5,260 只 A 股**的公司档案构成，数据冻结于 **2026-09-23**（采集与文档生成脚本已移出本仓库，不再更新）。

```
data/kb/
├── text/            5,260 份知识文档（Markdown，一只股票一份）
├── chunks.jsonl     48,823 条检索片段（带来源元数据）
├── metrics.sqlite   结构化财务数值（本地保留，未纳入版本管理）
└── _meta/           股票代码表等辅助数据
```

每份知识文档按固定章节组织：

```
基本信息 / 公司简介 / 注册地址 / 行业与概念 / 关键财务指标
营收结构（公司披露分部口径）/ 公司大事 / 机构评级 / 业务驱动分析 / 数据来源
```

无数据的章节整体省略，不输出空章节。

## 向量入库

把 `chunks.jsonl` 向量化后写入 Milvus：

```bash
python -m scripts.kb index
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--symbols` | 全部 | 逗号分隔的股票代码子集 |
| `--limit` | 无 | 只处理前 N 条片段 |
| `--batch-size` | 16 | 每批提交嵌入接口的片段数 |
| `--qps` | 1.0 | 嵌入接口限速 |
| `--max-retries` | 4 | 单批重试上限 |

重复执行会自动跳过未变更的片段（按内容哈希判断），中断后重跑可续。

### 环境变量

写入项目根 `.env`：

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `EMBEDDING_BASE_URL` | 是 | OpenAI 兼容接口基址 |
| `EMBEDDING_API_KEY` | 是 | 嵌入接口密钥 |
| `EMBEDDING_MODEL` | 是 | 模型名 |
| `EMBEDDING_DIM` | 否 | 向量维度；留空则自动探测 |
| `MILVUS_URI` | 否 | 默认 `http://47.95.112.116:19530` |
| `MILVUS_COLLECTION` | 否 | 默认 `fin_kb` |

> 若 Milvus 端口未对公网开放，先用 SSH 隧道：
> `ssh -i <key> -N -L 19530:localhost:19530 root@47.95.112.116`

### 依赖

```bash
python -m pip install -r requirements.txt
```

## 文档

- Milvus 部署：[`docs/milvus-configuration.md`](docs/milvus-configuration.md)
- 向量入库规格：[`specs/001-kb-vector-pipeline/`](specs/001-kb-vector-pipeline/)（spec / plan / tasks / quickstart）
- 项目准则：[`.specify/memory/constitution.md`](.specify/memory/constitution.md)
