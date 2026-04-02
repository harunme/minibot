"""VectorStore Provider 测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import ChromaDBConfig, VectorStoreConfig
from nanobot.providers.vectorstore import (
    ChromaDBVectorStoreProvider,
    EmbeddingProvider,
    SentenceTransformersEmbedding,
    VectorStoreProvider,
    create_embedding_provider,
    create_vectorstore_provider,
    SearchResult,
    _NoOpVectorStoreProvider,
)


class TestSearchResult:
    """检索结果数据类测试"""

    def test_creation(self):
        result = SearchResult(id="doc1", content="测试内容", score=0.95, metadata={"source": "test.pdf"})
        assert result.id == "doc1"
        assert result.content == "测试内容"
        assert result.score == 0.95
        assert result.metadata == {"source": "test.pdf"}

    def test_default_metadata(self):
        result = SearchResult(id="doc1", content="内容", score=0.8)
        assert result.metadata == {}


class TestSentenceTransformersEmbedding:
    """Sentence Transformers Embedding 测试"""

    def test_init(self):
        emb = SentenceTransformersEmbedding(model_name="test-model")
        assert emb._model_name == "test-model"
        assert emb._model is None

    @pytest.mark.asyncio
    async def test_embed_query_without_model(self):
        """测试 embed_query 延迟加载（模型未初始化时不报错）"""
        emb = SentenceTransformersEmbedding()
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.encode.return_value = MagicMock(tolist=MagicMock(return_value=[0.1, 0.2]))
            mock_st.return_value = mock_model

            result = await emb.embed_query("测试查询")
            assert result == [0.1, 0.2]
            mock_model.encode.assert_called_once()


class TestNoOpVectorStoreProvider:
    """空实现 Provider 测试"""

    @pytest.mark.asyncio
    async def test_search_returns_empty(self):
        provider = _NoOpVectorStoreProvider()
        results = await provider.search("测试查询")
        assert results == []

    @pytest.mark.asyncio
    async def test_is_available_returns_false(self):
        provider = _NoOpVectorStoreProvider()
        assert await provider.is_available() is False

    @pytest.mark.asyncio
    async def test_add_returns_empty_ids(self):
        provider = _NoOpVectorStoreProvider()
        ids = await provider.add([{"content": "测试"}])
        assert ids == []


class TestCreateVectorStoreProvider:
    """工厂函数测试"""

    def test_create_chromadb_provider(self):
        """测试创建 ChromaDB Provider"""
        config = VectorStoreConfig(provider="chromadb")
        provider = create_vectorstore_provider(config, tenant_id="test-tenant")
        assert isinstance(provider, ChromaDBVectorStoreProvider)
        assert provider._tenant_id == "test-tenant"

    def test_create_none_provider(self):
        """测试创建空 Provider"""
        config = VectorStoreConfig(provider="none")
        provider = create_vectorstore_provider(config)
        assert isinstance(provider, _NoOpVectorStoreProvider)

    def test_create_unsupported_provider_raises(self):
        """测试不支持的 Provider 抛出异常"""
        config = VectorStoreConfig(provider="unsupported")
        with pytest.raises(ValueError, match="不支持的 VectorStore Provider"):
            create_vectorstore_provider(config)


class TestCreateEmbeddingProvider:
    """Embedding Provider 工厂函数测试"""

    def test_create_sentence_transformers(self):
        """测试创建 Sentence Transformers Provider"""
        config = VectorStoreConfig()
        provider = create_embedding_provider(config)
        assert isinstance(provider, SentenceTransformersEmbedding)

    def test_create_dashscope_without_key_raises(self):
        """测试 DashScope 未配置 api_key 时抛出异常"""
        from nanobot.config.schema import EmbeddingConfig

        config = VectorStoreConfig(embedding=EmbeddingConfig(provider="dashscope", dashscope_api_key=""))
        with pytest.raises(ValueError, match="DashScope Embedding 需要配置"):
            create_embedding_provider(config)


class TestChromaDBVectorStoreProvider:
    """ChromaDB Provider 测试"""

    def test_init(self):
        """测试初始化"""
        provider = ChromaDBVectorStoreProvider(
            data_dir="/tmp/test_vectors",
            tenant_id="tenant001",
            collection_name="docs",
            allow_reset=True,
        )
        assert provider._data_dir.name == "test_vectors"
        assert provider._tenant_id == "tenant001"
        assert provider._qualified_collection_name == "tenant001_docs"
        assert provider._allow_reset is True
        # 延迟加载，client 初始为 None
        assert provider._client is None
        assert provider._collection is None

    @pytest.mark.asyncio
    async def test_add_without_init(self):
        """测试添加文档时延迟初始化 ChromaDB"""
        provider = ChromaDBVectorStoreProvider()

        with patch("chromadb.PersistentClient") as mock_pc:
            mock_client = MagicMock()
            mock_collection = MagicMock()
            mock_client.get_collection.return_value = mock_collection
            mock_pc.return_value = mock_client

            # 触发延迟初始化
            await provider._ensure_initialized()
            mock_pc.assert_called_once()
            mock_client.get_collection.assert_called_once()
