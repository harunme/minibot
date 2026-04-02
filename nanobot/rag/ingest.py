"""RAG 文档解析与入库管线

提供 PDF 文件解析、文本分块和向量入库的完整管线。
支持每租户独立 ChromaDB collection，数据完全隔离。

使用方式：
    ingestor = DocumentIngestor(tenant_id="family001")
    # 单文件入库
    ids = await ingestor.ingest_file("~/stories/westjourney.pdf", category="story")
    # 批量入库
    await ingestor.ingest_directory("~/stories/", category="story")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.schema import VectorStoreConfig
from nanobot.providers.vectorstore import (
    VectorStoreProvider,
    create_vectorstore_provider,
)

# ─── 文本分块 ──────────────────────────────────────────────────────────────────


@dataclass
class Chunk:
    """文本分块"""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def chunk_text(
    text: str,
    *,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    """将长文本切分为小块（带重叠）

    采用句子级切分，保证语义完整性：
    1. 按句子分割（。！？\n）
    2. 累积句子直到达到目标 chunk_size
    3. 相邻 chunk 之间保留 overlap 重叠，保证检索召回率

    Args:
        text: 原始文本
        chunk_size: 每个 chunk 的目标字符数
        chunk_overlap: 相邻 chunk 之间的重叠字符数

    Returns:
        Chunk 列表
    """
    # 按句子分割（中文标点为主，兼顾英文句号）
    sentences = re.split(r"(?<=[。！？\n])\s*", text)
    chunks: list[Chunk] = []
    current_text = ""
    current_start = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # 如果单个句子就超过 chunk_size，直接保留（不过度拆分）
        if len(sentence) > chunk_size:
            if current_text:
                chunks.append(Chunk(text=current_text.strip(), metadata={"start": current_start}))
            current_text = sentence
            current_start += len(current_text) + 1
            chunks.append(Chunk(text=sentence, metadata={"start": current_start - len(sentence) - 1}))
            current_text = ""
            continue

        # 累积到接近 chunk_size
        if len(current_text) + len(sentence) <= chunk_size:
            current_text += sentence + "\n"
        else:
            if current_text.strip():
                chunks.append(Chunk(text=current_text.strip(), metadata={"start": current_start}))
            # 滑动窗口：保留 overlap 字符作为下一 chunk 的开头
            overlap_text = current_text[-chunk_overlap:] if current_text else ""
            current_text = overlap_text + sentence + "\n"
            current_start += len(current_text) - chunk_overlap

    # 最后一块
    if current_text.strip():
        chunks.append(Chunk(text=current_text.strip(), metadata={"start": current_start}))

    return chunks


# ─── PDF 解析 ─────────────────────────────────────────────────────────────────


def extract_pdf(file_path: str | Path) -> str:
    """从 PDF 提取纯文本

    Args:
        file_path: PDF 文件路径

    Returns:
        提取的纯文本

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: PDF 解析失败
    """
    from pypdf import PdfReader

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {path}")

    try:
        reader = PdfReader(path)
        texts: list[str] = []
        for page_num, page in enumerate(reader.pages, 1):
            text = page.extract_text()
            if text:
                texts.append(f"[第{page_num}页]\n{text}")
        result = "\n\n".join(texts)
        logger.info("[RAG] 从 PDF 提取 {} 页，文本长度 {} 字符", len(reader.pages), len(result))
        return result
    except Exception as e:
        raise ValueError(f"PDF 解析失败: {path}: {e}") from e


def extract_text_file(file_path: str | Path) -> str:
    """从纯文本文件读取内容

    Args:
        file_path: 文本文件路径

    Returns:
        文件内容

    Raises:
        FileNotFoundError: 文件不存在
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文本文件不存在: {path}")

    # 自动检测编码（优先 UTF-8，fallback GBK）
    for encoding in ("utf-8", "gbk", "gb2312"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文本文件（尝试了 UTF-8/GBK/GB2312）: {path}")


# ─── 文档入库 ─────────────────────────────────────────────────────────────────


@dataclass
class IngestResult:
    """文档入库结果"""

    file_name: str
    total_pages: int
    chunks_created: int
    doc_ids: list[str]
    errors: list[str] = field(default_factory=list)


class DocumentIngestor:
    """文档解析与知识库入库管线

    支持 PDF 和纯文本文件，自动分块并入库到 ChromaDB。
    每租户独立 collection，数据隔离。

    使用方式：
        ingestor = DocumentIngestor(tenant_id="family001")
        result = await ingestor.ingest_file("~/stories/westjourney.pdf", category="story")
        print(f"入库成功，创建了 {result.chunks_created} 个块")
    """

    def __init__(
        self,
        vectorstore_config: VectorStoreConfig | None = None,
        tenant_id: str = "default",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ):
        self._config = vectorstore_config
        self._tenant_id = tenant_id
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._provider: VectorStoreProvider | None = None

    async def ingest_file(
        self,
        file_path: str | Path,
        *,
        category: str | None = None,
        source_name: str | None = None,
    ) -> IngestResult:
        """解析并入库单个文件

        Args:
            file_path: 文件路径（PDF 或 .txt）
            category: 文档分类（用于过滤检索）
            source_name: 知识库中显示的来源名称（默认用文件名）

        Returns:
            入库结果
        """
        path = Path(file_path)
        if not path.exists():
            return IngestResult(
                file_name=path.name,
                total_pages=0,
                chunks_created=0,
                doc_ids=[],
                errors=[f"文件不存在: {path}"],
            )

        try:
            # 根据扩展名选择解析方法
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                text = extract_pdf(path)
                total_pages = _count_pdf_pages(path)
            elif suffix in (".txt", ".md"):
                text = extract_text_file(path)
                total_pages = 1
            else:
                return IngestResult(
                    file_name=path.name,
                    total_pages=0,
                    chunks_created=0,
                    doc_ids=[],
                    errors=[f"不支持的文件格式: {suffix}（支持 .pdf, .txt, .md）"],
                )
        except Exception as e:
            logger.error("[RAG] 解析文件失败: {}: {}", path, e)
            return IngestResult(
                file_name=path.name,
                total_pages=0,
                chunks_created=0,
                doc_ids=[],
                errors=[str(e)],
            )

        # 文本分块
        chunks = chunk_text(
            text,
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )

        if not chunks:
            return IngestResult(
                file_name=path.name,
                total_pages=total_pages,
                chunks_created=0,
                doc_ids=[],
                errors=["文档内容为空"],
            )

        # 构建文档列表
        source = source_name or path.name
        documents: list[dict[str, Any]] = [
            {
                "content": chunk.text,
                "metadata": {
                    "source": source,
                    "category": category or "general",
                    "file_name": path.name,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                },
            }
            for i, chunk in enumerate(chunks)
        ]

        # 入库到向量数据库
        try:
            provider = await self._get_provider()
            doc_ids = await provider.add(documents)
            logger.info(
                "[RAG] 入库完成: {} → {} 个块 (ids={})",
                path.name,
                len(chunks),
                doc_ids[:3],
            )
            return IngestResult(
                file_name=path.name,
                total_pages=total_pages,
                chunks_created=len(chunks),
                doc_ids=doc_ids,
            )
        except Exception as e:
            logger.error("[RAG] 入库失败: {}: {}", path.name, e)
            return IngestResult(
                file_name=path.name,
                total_pages=total_pages,
                chunks_created=0,
                doc_ids=[],
                errors=[f"入库失败: {e}"],
            )

    async def ingest_directory(
        self,
        dir_path: str | Path,
        *,
        category: str | None = None,
        extensions: tuple[str, ...] = (".pdf", ".txt", ".md"),
    ) -> list[IngestResult]:
        """批量入库目录下所有支持的文件

        Args:
            dir_path: 目录路径
            category: 统一文档分类
            extensions: 要处理的文件扩展名

        Returns:
            每个文件的入库结果列表
        """
        path = Path(dir_path)
        if not path.is_dir():
            raise FileNotFoundError(f"目录不存在: {path}")

        files = []
        for ext in extensions:
            files.extend(path.rglob(f"*{ext}"))

        logger.info("[RAG] 批量入库: 发现 {} 个文件 in {}", len(files), path)

        results: list[IngestResult] = []
        for file_path in sorted(files):
            result = await self.ingest_file(file_path, category=category)
            results.append(result)

        success = sum(1 for r in results if not r.errors)
        total_chunks = sum(r.chunks_created for r in results)
        logger.info(
            "[RAG] 批量入库完成: 成功 {}/{}，共 {} 个块",
            success,
            len(results),
            total_chunks,
        )
        return results

    async def _get_provider(self) -> VectorStoreProvider:
        """延迟获取 VectorStoreProvider"""
        if self._provider is None:
            if self._config is None:
                raise RuntimeError("DocumentIngestor 需要 vectorstore_config 参数")
            self._provider = create_vectorstore_provider(self._config, tenant_id=self._tenant_id)
        return self._provider


def _count_pdf_pages(path: Path) -> int:
    """快速统计 PDF 页数（不提取文本）"""
    from pypdf import PdfReader

    try:
        return len(PdfReader(path).pages)
    except Exception:
        return 0
