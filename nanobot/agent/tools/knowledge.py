"""Knowledge Search Tool — 知识库检索工具

Agent 通过此工具主动查询 RAG 知识库，获取相关文档内容。

使用方式（在 Agent 对话中触发）：
    用户: "给我讲个西游记的故事"
    Agent 调用 knowledge_search(query="西游记", top_k=3)
    → 返回相关文档片段，Agent 结合内容回复
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.config.schema import VectorStoreConfig
from nanobot.providers.vectorstore import (
    SearchResult,
    VectorStoreProvider,
    create_vectorstore_provider,
)


class KnowledgeSearchTool(Tool):
    """知识库检索工具

    Agent 可主动查询 RAG 知识库，基于向量相似度检索相关文档片段。
    支持按类别、时间等元数据过滤。
    """

    name = "knowledge_search"
    description = "在本地知识库中检索与问题相关的文档内容。当你需要基于上传的资料（如绘本、故事书、唐诗等）回答问题时，使用此工具搜索相关内容。"

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索查询文本，建议用自然语言描述你寻找的内容，如'西游记三打白骨精'、'唐诗静夜思'",
            },
            "top_k": {
                "type": "integer",
                "description": "返回的最相关文档数量",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
            "category": {
                "type": "string",
                "description": "按文档分类过滤（如 'story', 'poem', 'book'）",
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        vectorstore_config: VectorStoreConfig | None = None,
        vectorstore_provider: VectorStoreProvider | None = None,
        tenant_id: str = "default",
    ):
        self._config = vectorstore_config
        self._provider = vectorstore_provider
        self._tenant_id = tenant_id

    async def execute(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
        **kwargs: Any,
    ) -> str:
        """执行知识库检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            category: 可选分类过滤

        Returns:
            格式化后的检索结果字符串
        """
        # 延迟初始化 provider
        if self._provider is None:
            if self._config is None:
                return "错误：知识库未配置（vectorstore config 缺失）"
            try:
                self._provider = create_vectorstore_provider(self._config, tenant_id=self._tenant_id)
            except Exception as e:
                logger.error("[KnowledgeSearch] 初始化 VectorStoreProvider 失败: {}", e)
                return f"错误：知识库初始化失败 - {e}"

        # 构建过滤条件
        meta_filter: dict[str, Any] | None = None
        if category:
            meta_filter = {"category": category}

        try:
            results: list[SearchResult] = await self._provider.search(
                query=query,
                top_k=top_k,
                filter=meta_filter,
            )

            if not results:
                return f"知识库中未找到与「{query}」相关的内容。"

            # 格式化结果供 LLM 消费
            lines: list[str] = [f"知识库检索结果（共 {len(results)} 条，相关度从高到低）：\n"]
            for i, result in enumerate(results, 1):
                # 相似度百分比（score 0-1 → 0%-100%）
                score_pct = result.score * 100
                source = result.metadata.get("source", "未知来源")
                lines.append(f"【结果 {i}】（相关度 {score_pct:.0f}%）")
                lines.append(f"来源: {source}")
                if category_label := result.metadata.get("category"):
                    lines.append(f"分类: {category_label}")
                lines.append(f"内容: {result.content}")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            logger.error("[KnowledgeSearch] 检索失败: {}", e)
            return f"错误：知识库检索失败 - {e}"
