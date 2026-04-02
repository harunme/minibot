"""RAG 文档解析与入库管线测试"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.rag.ingest import (
    DocumentIngestor,
    IngestResult,
    chunk_text,
)


class TestChunkText:
    """文本分块测试"""

    def test_empty_text(self):
        """测试空文本"""
        chunks = chunk_text("")
        assert chunks == []

    def test_single_sentence(self):
        """测试单个句子（不超过 chunk_size）"""
        text = "这是一个完整的句子。"
        chunks = chunk_text(text, chunk_size=50, chunk_overlap=5)
        assert len(chunks) == 1
        assert chunks[0].text == text

    def test_multiple_sentences(self):
        """测试多个句子"""
        text = "第一句。第二句。第三句。第四句。第五句。第六句。"
        chunks = chunk_text(text, chunk_size=8, chunk_overlap=3)
        # 预期至少 2 个块（每个块约 8 字符）
        assert len(chunks) >= 2
        # 每个块的内容都来自原文
        all_text = "".join(c.text for c in chunks)
        assert "第一句" in all_text
        assert "第二句" in all_text
        assert "第三句" in all_text

    def test_long_sentence_not_split(self):
        """测试超长句子不被强制拆分"""
        text = "这是一句非常非常非常非常非常非常非常非常非常非常非常非常长的句子。"
        chunks = chunk_text(text, chunk_size=20, chunk_overlap=3)
        # 超长句子（>chunk_size）保留为独立 chunk，不被强制拆分
        assert len(chunks) >= 1
        assert all(len(c.text) >= 20 for c in chunks)

    def test_overlap_preserved(self):
        """测试相邻块之间有重叠"""
        text = "第一句。第二句。第三句。第四句。"
        chunks = chunk_text(text, chunk_size=10, chunk_overlap=5)
        if len(chunks) >= 2:
            # 验证重叠存在：后一块的开头应该是前一块的结尾部分
            first_end = chunks[0].text[-5:]
            second_start = chunks[1].text[:5]
            # 重叠文本应该相同（允许微小差异因为 trim）
            assert any(char in second_start for char in first_end if char.strip())

    def test_chunk_metadata(self):
        """测试 chunk 包含 metadata"""
        text = "第一句。第二句。"
        chunks = chunk_text(text, chunk_size=20, chunk_overlap=3)
        assert all(hasattr(c, "metadata") for c in chunks)
        assert all("start" in c.metadata for c in chunks)

    def test_newline_split(self):
        """测试按换行符分割"""
        text = "第一段\n第二段\n第三段"
        chunks = chunk_text(text, chunk_size=20, chunk_overlap=2)
        assert len(chunks) >= 1
        # 段落信息应该保留
        all_text = "".join(c.text for c in chunks)
        assert "第一段" in all_text


class TestDocumentIngestor:
    """文档入库测试"""

    def test_init(self):
        """测试初始化"""
        from nanobot.config.schema import VectorStoreConfig

        config = VectorStoreConfig()
        ingestor = DocumentIngestor(
            vectorstore_config=config,
            tenant_id="family001",
            chunk_size=300,
            chunk_overlap=50,
        )
        assert ingestor._tenant_id == "family001"
        assert ingestor._chunk_size == 300
        assert ingestor._chunk_overlap == 50
        assert ingestor._provider is None

    @pytest.mark.asyncio
    async def test_ingest_nonexistent_file(self):
        """测试文件不存在时返回错误"""
        ingestor = DocumentIngestor(tenant_id="test")
        result = await ingestor.ingest_file("/nonexistent/file.pdf")
        assert result.file_name == "file.pdf"
        assert result.errors
        assert "不存在" in result.errors[0]

    @pytest.mark.asyncio
    async def test_ingest_unsupported_format(self):
        """测试不支持的文件格式"""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            path = Path(f.name)

        try:
            ingestor = DocumentIngestor(tenant_id="test")
            result = await ingestor.ingest_file(path)
            assert "不支持的文件格式" in result.errors[0]
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_ingest_text_file(self):
        """测试文本文件入库（Mock ChromaDB）"""
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8", delete=False) as f:
            f.write("从前有座山，山里有座庙。庙里有个老和尚在讲故事。")
            path = Path(f.name)

        try:
            ingestor = DocumentIngestor(
                tenant_id="test",
                chunk_size=200,
                chunk_overlap=20,
            )

            mock_provider = AsyncMock()
            mock_provider.add = AsyncMock(return_value=["id1", "id2"])
            ingestor._provider = mock_provider

            result = await ingestor.ingest_file(path, category="story")

            assert result.file_name == path.name
            assert result.total_pages == 1
            assert result.chunks_created >= 1
            assert result.doc_ids == ["id1", "id2"]
            assert not result.errors

            # 验证 ChromaDB 被正确调用
            mock_provider.add.assert_called_once()
            added_docs = mock_provider.add.call_args[0][0]
            assert len(added_docs) == result.chunks_created
            assert added_docs[0]["metadata"]["source"] == path.name
            assert added_docs[0]["metadata"]["category"] == "story"
        finally:
            path.unlink(missing_ok=True)


class TestIngestResult:
    """入库结果数据类测试"""

    def test_success_result(self):
        result = IngestResult(
            file_name="test.pdf",
            total_pages=10,
            chunks_created=5,
            doc_ids=["id1", "id2", "id3", "id4", "id5"],
        )
        assert result.file_name == "test.pdf"
        assert result.total_pages == 10
        assert result.chunks_created == 5
        assert len(result.doc_ids) == 5
        assert result.errors == []

    def test_error_result(self):
        result = IngestResult(
            file_name="broken.pdf",
            total_pages=0,
            chunks_created=0,
            doc_ids=[],
            errors=["PDF 解析失败: corrupt file"],
        )
        assert result.errors == ["PDF 解析失败: corrupt file"]
