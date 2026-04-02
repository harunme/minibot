"""VectorStore Provider — 向量数据库抽象层

VectorStoreProvider 抽象基类定义知识库检索的标准接口，
支持多提供商扩展（V2 默认 ChromaDB）。

使用方式：
    # 检索知识库
    provider = ChromaDBVectorStoreProvider(data_dir="~/.nanobot/vectorstore", tenant_id="family001")
    results = await provider.search("小朋友喜欢的故事", top_k=5)

    # 添加文档
    ids = await provider.add([{"content": "内容文本", "metadata": {"source": "book.pdf"}}])
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.schema import VectorStoreConfig


@dataclass
class SearchResult:
    """知识库检索结果"""

    id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectionStats:
    """向量数据库 collection 统计信息"""

    count: int
    categories: dict[str, int]  # category → doc count（按文件去重）
    storage_bytes: int | None  # SQLite 文件大小估算


class EmbeddingProvider(ABC):
    """Embedding 生成器抽象基类"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """将文本转为向量

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个元素对应输入文本的 embedding
        """
        ...

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """将单个查询文本转为向量

        Args:
            query: 查询文本

        Returns:
            文本向量
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """检查服务可用性"""
        ...


class VectorStoreProvider(ABC):
    """向量数据库抽象基类 — 支持多提供商扩展"""

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filter: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """检索知识库

        Args:
            query: 查询文本
            top_k: 返回结果数量
            filter: 元数据过滤条件

        Returns:
            检索结果列表
        """
        ...

    @abstractmethod
    async def add(
        self,
        documents: list[dict[str, Any]],
        *,
        ids: list[str] | None = None,
    ) -> list[str]:
        """添加文档到知识库

        Args:
            documents: 文档列表，每项需包含 "content" 字段，可选 "metadata"
            ids: 文档 ID 列表（不指定则自动生成）

        Returns:
            文档 ID 列表
        """
        ...

    @abstractmethod
    async def delete(self, ids: list[str]) -> bool:
        """删除文档

        Args:
            ids: 文档 ID 列表

        Returns:
            是否删除成功
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """检查服务可用性"""
        ...

    @abstractmethod
    async def list_documents(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        category: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """列出文档（支持分类过滤和分页）

        Args:
            limit: 最大返回数量
            offset: 跳过数量（分页偏移）
            category: 可选，按文档分类过滤

        Returns:
            (文档列表, 总数) — 文档格式: {id, content_preview, metadata}
        """
        ...

    @abstractmethod
    async def get_stats(self) -> CollectionStats:
        """返回 collection 统计信息"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """释放资源"""
        ...


# ─── Sentence Transformers Embedding ─────────────────────────────────────────


class SentenceTransformersEmbedding(EmbeddingProvider):
    """Sentence Transformers Embedding 实现（默认，CPU 友好）

    使用 paraphrase-multilingual-MiniLM-L12-v2，支持 50+ 语言含中文，
    CPU 推理，速度快，适合知识库场景。
    """

    def __init__(self, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        self._model_name = model_name
        self._model: Any = None  # 类型待确定，延迟加载

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = await self._get_model()
        embeddings = model.encode(texts, convert_to_numpy=True)
        return [emb.tolist() for emb in embeddings]

    async def embed_query(self, query: str) -> list[float]:
        model = await self._get_model()
        embedding = model.encode(query, convert_to_numpy=True)
        return embedding.tolist()

    async def is_available(self) -> bool:
        try:
            await self._get_model()
            return True
        except Exception as e:
            logger.warning("[Embedding] SentenceTransformers 不可用: {}", e)
            return False

    async def _get_model(self) -> Any:
        if self._model is None:
            # 延迟导入，sentence-transformers 是可选依赖
            from sentence_transformers import SentenceTransformer

            logger.info("[Embedding] 加载 SentenceTransformer 模型: {}", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model


class DashScopeEmbedding(EmbeddingProvider):
    """DashScope Embedding 实现（阿里云，API 调用）

    使用阿里云 DashScope text-embedding API，需要配置 api_key。
    """

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client: Any = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        client = await self._get_client()
        embeddings = []
        for text in texts:
            response = client.embeddings.create(
                model="text-embedding-v3",
                input=text,
            )
            embeddings.append(response.data[0].embedding)
        return embeddings

    async def embed_query(self, query: str) -> list[float]:
        return (await self.embed([query]))[0]

    async def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            await self._get_client()
            return True
        except Exception as e:
            logger.warning("[Embedding] DashScope 不可用: {}", e)
            return False

    async def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self._api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
        return self._client


def create_embedding_provider(config: VectorStoreConfig) -> EmbeddingProvider:
    """基于配置创建 Embedding Provider"""
    emb_cfg = config.embedding
    provider_name = emb_cfg.provider.lower()

    if provider_name == "sentence_transformers":
        return SentenceTransformersEmbedding(model_name=emb_cfg.sentence_transformers)
    elif provider_name == "dashscope":
        if not emb_cfg.dashscope_api_key:
            raise ValueError("DashScope Embedding 需要配置 dashscope_api_key")
        return DashScopeEmbedding(api_key=emb_cfg.dashscope_api_key)
    else:
        raise ValueError(f"不支持的 Embedding Provider: {provider_name}")


# ─── ChromaDB 实现 ────────────────────────────────────────────────────────────


class ChromaDBVectorStoreProvider(VectorStoreProvider):
    """ChromaDB 向量数据库实现（V2 默认）

    特点：
    - 嵌入式向量数据库，零运维，SQLite 后端
    - 按租户隔离 collection（tenant_id 体现在 collection 名中）
    - 支持批量添加、过滤检索、重置 collection
    """

    def __init__(
        self,
        data_dir: str = "~/.nanobot/vectorstore",
        tenant_id: str = "default",
        collection_name: str = "knowledge",
        embedding_provider: EmbeddingProvider | None = None,
        allow_reset: bool = False,
    ):
        self._data_dir = Path(data_dir).expanduser()
        self._tenant_id = tenant_id
        self._collection_name = collection_name
        self._embedding_provider = embedding_provider
        self._allow_reset = allow_reset
        self._client: Any = None
        self._collection: Any = None
        # collection 名中加入 tenant 前缀实现数据隔离
        self._qualified_collection_name = f"{tenant_id}_{collection_name}"

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filter: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        await self._ensure_initialized()
        collection = self._collection

        # 生成查询向量
        query_embedding = await self._embedding_provider.embed_query(query)

        # ChromaDB 查询
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=filter,
            include=["documents", "metadatas", "distances"],
        )

        search_results: list[SearchResult] = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[None] * len(ids)])[0]

        for i, doc_id in enumerate(ids):
            # ChromaDB 距离为余弦距离（越小越相似）
            # 转换为相似度分数（0-1，越大越相似）
            distance = distances[i] if i < len(distances) else 1.0
            score = max(0.0, 1.0 - distance / 2.0)
            search_results.append(
                SearchResult(
                    id=doc_id,
                    content=documents[i] if i < len(documents) else "",
                    score=score,
                    metadata=metadatas[i] if i < len(metadatas) and metadatas[i] else {},
                )
            )
        return search_results

    async def add(
        self,
        documents: list[dict[str, Any]],
        *,
        ids: list[str] | None = None,
    ) -> list[str]:
        await self._ensure_initialized()
        collection = self._collection

        import uuid

        doc_ids: list[str] = ids or [str(uuid.uuid4()) for _ in documents]
        contents: list[str] = [doc.get("content", "") for doc in documents]
        metadatas: list[dict[str, Any]] = [doc.get("metadata", {}) for doc in documents]

        collection.add(ids=doc_ids, documents=contents, metadatas=metadatas)
        logger.info(
            "[VectorStore] 添加 {} 篇文档到 collection '{}' (tenant={})",
            len(documents),
            self._qualified_collection_name,
            self._tenant_id,
        )
        return doc_ids

    async def delete(self, ids: list[str]) -> bool:
        await self._ensure_initialized()
        self._collection.delete(ids=ids)
        logger.info("[VectorStore] 从 collection '{}' 删除 {} 篇文档", self._qualified_collection_name, len(ids))
        return True

    async def list_documents(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        category: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """列出文档（支持分类过滤和分页）"""
        await self._ensure_initialized()
        collection = self._collection

        # ChromaDB 的 where 过滤是 AND 语义，category 精确匹配
        where_filter: dict[str, Any] | None = {"category": category} if category else None

        # 获取过滤后的所有文档（ChromaDB 不支持 offset，需手动切片）
        all_results = collection.get(where=where_filter, include=["documents", "metadatas"])
        all_ids = all_results.get("ids", [])
        all_docs = all_results.get("documents", [])
        all_metas = all_results.get("metadatas", [None] * len(all_ids))

        total = len(all_ids)
        page_ids = all_ids[offset:offset + limit]
        page_docs = all_docs[offset:offset + limit]
        page_metas = all_metas[offset:offset + limit]

        documents: list[dict[str, Any]] = []
        for i, doc_id in enumerate(page_ids):
            content = page_docs[i] if i < len(page_docs) else ""
            meta = page_metas[i] if i < len(page_metas) and page_metas[i] else {}
            # content_preview 截取前 200 字符，避免列表返回过长
            preview = content[:200] + ("..." if len(content) > 200 else "")
            documents.append({
                "id": doc_id,
                "content_preview": preview,
                "metadata": meta,
            })
        return documents, total

    async def get_stats(self) -> CollectionStats:
        """返回 collection 统计信息"""
        await self._ensure_initialized()
        collection = self._collection

        total_count = collection.count()

        # 遍历 metadata 统计分类（按 source 文件去重计数）
        categories: dict[str, int] = {}
        seen_files: set[str] = set()

        try:
            # peek 返回所有文档（受 ChromaDB 内部限制，limit 默认 1000）
            all_results = collection.peek(limit=10000, include=["metadatas"])
            metadatas = all_results.get("metadatas", [])
            for meta in metadatas:
                if not meta:
                    continue
                source = meta.get("source", "unknown")
                category = meta.get("category", "general")
                # 按 (source, category) 唯一键去重
                key = f"{source}::{category}"
                if key not in seen_files:
                    seen_files.add(key)
                    categories[category] = categories.get(category, 0) + 1
        except Exception as e:
            logger.warning("[VectorStore] 统计分类时出错: {}", e)

        # 估算存储大小：ChromaDB SQLite 文件
        storage_bytes: int | None = None
        try:
            chroma_sqlite = self._data_dir / "chroma.sqlite"
            if chroma_sqlite.exists():
                storage_bytes = chroma_sqlite.stat().st_size
        except Exception:
            pass

        return CollectionStats(
            count=total_count,
            categories=categories,
            storage_bytes=storage_bytes,
        )

    async def is_available(self) -> bool:
        try:
            await self._ensure_initialized()
            return True
        except Exception as e:
            logger.warning("[VectorStore] ChromaDB 不可用: {}", e)
            return False

    async def close(self) -> None:
        """ChromaDB 是嵌入式数据库，无需主动关闭，仅清理 Python 对象"""
        self._client = None
        self._collection = None

    async def reset(self) -> None:
        """重置 collection（删除所有文档）"""
        if not self._allow_reset:
            raise PermissionError("reset 需要在配置中设置 allow_reset=True")
        await self._ensure_initialized()
        self._collection.delete(where={})
        logger.warning("[VectorStore] Collection '{}' 已重置", self._qualified_collection_name)

    async def _ensure_initialized(self) -> None:
        """延迟初始化 ChromaDB client 和 collection"""
        if self._collection is not None:
            return

        import chromadb
        from chromadb.config import Settings

        # ChromaDB 持久化存储
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self._data_dir),
            settings=Settings(anonymized_telemetry=False),
        )

        # 获取或创建 collection（ChromaDB 会在内部创建）
        try:
            self._collection = self._client.get_collection(name=self._qualified_collection_name)
            logger.debug(
                "[VectorStore] 连接 collection '{}' (现有文档数={})",
                self._qualified_collection_name,
                self._collection.count(),
            )
        except Exception:
            # collection 不存在，创建新的
            self._collection = self._client.create_collection(
                name=self._qualified_collection_name,
                metadata={"tenant_id": self._tenant_id},
            )
            logger.info("[VectorStore] 创建新 collection '{}'", self._qualified_collection_name)


def create_vectorstore_provider(config: VectorStoreConfig, tenant_id: str = "default") -> VectorStoreProvider:
    """基于配置创建 VectorStore Provider

    Args:
        config: VectorStoreConfig 配置对象
        tenant_id: 租户 ID（用于 collection 隔离）
    """
    provider_name = config.provider.lower()

    if provider_name == "chromadb":
        embedding_provider = create_embedding_provider(config)
        chroma_cfg = config.chromadb
        return ChromaDBVectorStoreProvider(
            data_dir=chroma_cfg.data_dir,
            tenant_id=tenant_id,
            collection_name=chroma_cfg.collection_name,
            embedding_provider=embedding_provider,
            allow_reset=chroma_cfg.allow_reset,
        )
    elif provider_name == "milvus":
        raise NotImplementedError("Milvus VectorStore Provider 尚未实现")
    elif provider_name == "none":
        return _NoOpVectorStoreProvider()
    else:
        raise ValueError(f"不支持的 VectorStore Provider: {provider_name}")


class _NoOpVectorStoreProvider(VectorStoreProvider):
    """空实现：未配置向量数据库时的占位实现"""

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filter: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        return []

    async def add(
        self,
        documents: list[dict[str, Any]],
        *,
        ids: list[str] | None = None,
    ) -> list[str]:
        return []

    async def delete(self, ids: list[str]) -> bool:
        return True

    async def is_available(self) -> bool:
        return False

    async def list_documents(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        category: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        return [], 0

    async def get_stats(self) -> CollectionStats:
        return CollectionStats(count=0, categories={}, storage_bytes=None)

    async def close(self) -> None:
        pass
