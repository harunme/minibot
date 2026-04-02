"""RAG 模块 — 检索增强生成核心组件

V2.0 RAG 知识库：
- 文档解析（PDF → 文本 → 分块）
- 向量入库（ChromaDB）
- 知识库检索（通过 KnowledgeSearchTool）

目录结构：
    nanobot/rag/
    ├── __init__.py        # 本模块公共接口
    └── ingest.py          # 文档解析与入库管线
"""

from nanobot.rag.ingest import DocumentIngestor, chunk_text

__all__ = ["DocumentIngestor", "chunk_text"]
