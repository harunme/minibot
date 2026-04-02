"""V2 向量数据库配置测试"""

from __future__ import annotations

from nanobot.config.schema import (
    ChromaDBConfig,
    EmbeddingConfig,
    MilvusConfig,
    VectorStoreConfig,
)


class TestChromaDBConfig:
    """ChromaDB 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = ChromaDBConfig()
        assert config.data_dir == "~/.nanobot/vectorstore"
        assert config.collection_name == "knowledge"
        assert config.allow_reset is False

    def test_camel_case_parsing(self):
        """测试 camelCase 解析"""
        config = ChromaDBConfig(**{"dataDir": "/tmp/vectors", "collectionName": "my_docs"})
        assert config.data_dir == "/tmp/vectors"
        assert config.collection_name == "my_docs"


class TestEmbeddingConfig:
    """Embedding 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = EmbeddingConfig()
        assert config.provider == "sentence_transformers"
        assert "paraphrase-multilingual-MiniLM-L12-v2" in config.sentence_transformers
        assert config.dashscope_api_key == ""


class TestMilvusConfig:
    """Milvus 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = MilvusConfig()
        assert config.uri == "http://localhost:19530"
        assert config.token == ""


class TestVectorStoreConfig:
    """向量数据库配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = VectorStoreConfig()
        assert config.provider == "chromadb"
        assert isinstance(config.chromadb, ChromaDBConfig)
        assert isinstance(config.milvus, MilvusConfig)
        assert isinstance(config.embedding, EmbeddingConfig)

    def test_provider_none(self):
        """测试禁用向量数据库"""
        config = VectorStoreConfig(provider="none")
        assert config.provider == "none"
