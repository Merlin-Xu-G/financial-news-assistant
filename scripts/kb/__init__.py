"""知识库向量入库。

读取 ``data/kb/chunks.jsonl``，向量化后写入向量库。
入口：``python -m scripts.kb index``，契约见 specs/001-kb-vector-pipeline/contracts/cli.md。

数据生成（采集 / 文档 / 切分）已完成并移出本仓库，知识库冻结在 2026-09-23。
"""
