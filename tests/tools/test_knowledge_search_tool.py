"""Knowledge Search Tool 测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.tools.knowledge import KnowledgeSearchTool
from nanobot.config.schema import VectorStoreConfig
from nanobot.providers.vectorstore import SearchResult


class TestKnowledgeSearchTool:
    """KnowledgeSearchTool 测试"""

    def test_tool_name(self):
        """测试工具名称"""
        tool = KnowledgeSearchTool()
        assert tool.name == "knowledge_search"

    def test_tool_description(self):
        """测试工具描述"""
        tool = KnowledgeSearchTool()
        assert "知识库" in tool.description
        assert "检索" in tool.description

    def test_parameters_schema(self):
        """测试参数 schema"""
        tool = KnowledgeSearchTool()
        params = tool.parameters
        assert params["type"] == "object"
        assert "query" in params["required"]
        assert "query" in params["properties"]
        assert "top_k" in params["properties"]
        assert "category" in params["properties"]
        assert params["properties"]["top_k"]["default"] == 5

    def test_init_with_config(self):
        """测试使用配置初始化"""
        config = VectorStoreConfig(provider="chromadb")
        tool = KnowledgeSearchTool(vectorstore_config=config, tenant_id="family001")
        assert tool._config is not None
        assert tool._tenant_id == "family001"
        assert tool._provider is None  # 延迟初始化

    @pytest.mark.asyncio
    async def test_execute_without_config_returns_error(self):
        """测试未配置时返回错误提示"""
        tool = KnowledgeSearchTool(vectorstore_config=None)
        result = await tool.execute(query="测试查询")
        assert "未配置" in result or "错误" in result

    @pytest.mark.asyncio
    async def test_execute_with_no_results(self):
        """测试检索结果为空"""
        tool = KnowledgeSearchTool()

        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(return_value=[])
        tool._provider = mock_provider

        result = await tool.execute(query="不存在的查询")
        assert "未找到" in result

    @pytest.mark.asyncio
    async def test_execute_with_results(self):
        """测试检索到结果"""
        tool = KnowledgeSearchTool()

        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(
            return_value=[
                SearchResult(
                    id="doc1",
                    content="孙悟空大闹天宫的故事",
                    score=0.95,
                    metadata={"source": "西游记.pdf", "category": "story"},
                ),
                SearchResult(
                    id="doc2",
                    content="唐僧取经的历程",
                    score=0.88,
                    metadata={"source": "西游记.pdf", "category": "story"},
                ),
            ]
        )
        tool._provider = mock_provider

        result = await tool.execute(query="西游记", top_k=5)

        # 验证结果格式
        assert "西游记" in result  # 查询词出现在结果描述中
        assert "doc1" not in result  # ID 不应暴露给 LLM
        assert "孙悟空大闹天宫的故事" in result  # 内容应该包含在结果中
        assert "相关度" in result  # 包含相关度信息
        assert "来源:" in result  # 包含来源信息

    @pytest.mark.asyncio
    async def test_execute_with_category_filter(self):
        """测试带分类过滤的检索"""
        tool = KnowledgeSearchTool()

        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(return_value=[])
        tool._provider = mock_provider

        await tool.execute(query="测试", category="poem")
        mock_provider.search.assert_called_once()
        call_kwargs = mock_provider.search.call_args
        assert call_kwargs.kwargs["filter"] == {"category": "poem"}

    @pytest.mark.asyncio
    async def test_execute_error_handling(self):
        """测试检索异常处理"""
        tool = KnowledgeSearchTool()

        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(side_effect=Exception("ChromaDB 连接失败"))
        tool._provider = mock_provider

        result = await tool.execute(query="测试")
        assert "错误" in result
        assert "ChromaDB" in result
