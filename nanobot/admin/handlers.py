"""管理后台 API 路由处理器

所有处理器接收 web.Request，返回 web.Response。
VectorStoreProvider 通过 request.app["vectorstore_provider"] 访问。
"""

from __future__ import annotations

import tempfile
from typing import Any

from aiohttp import web
from loguru import logger

# ─── 辅助 ─────────────────────────────────────────────────────────────────────


def _json(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _bad_request(message: str) -> web.Response:
    return _json({"error": message}, status=400)


def _not_found(message: str = "Document not found") -> web.Response:
    return _json({"error": message}, status=404)


def _error(message: str, status: int = 500) -> web.Response:
    return _json({"error": message}, status=status)


def _get_provider(request: web.Request) -> Any:
    return request.app.get("vectorstore_provider")


def _get_config(request: web.Request) -> Any:
    return request.app.get("vectorstore_config")


# ─── 文档列表 ─────────────────────────────────────────────────────────────────


async def handle_admin_documents_list(request: web.Request) -> web.Response:
    """GET /api/admin/documents

    Query params:
        category: str | None  — 按分类过滤
        limit:   int (default 50, max 200)
        offset:  int (default 0)
    """
    provider = _get_provider(request)
    if not provider:
        return _error("VectorStore provider not configured", 503)

    try:
        category = request.query.get("category") or None
        limit = min(int(request.query.get("limit", 50)), 200)
        offset = max(int(request.query.get("offset", 0)), 0)
    except ValueError:
        return _bad_request("Invalid limit or offset parameter")

    documents, total = await provider.list_documents(
        limit=limit,
        offset=offset,
        category=category,
    )
    return _json({
        "documents": documents,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


# ─── 单文档 ───────────────────────────────────────────────────────────────────


async def handle_admin_document_get(request: web.Request) -> web.Response:
    """GET /api/admin/documents/{id}"""
    doc_id = request.match_info["id"]
    provider = _get_provider(request)
    if not provider:
        return _error("VectorStore provider not configured", 503)

    # ChromaDB collection.get() 支持按 ID 获取
    try:
        await provider._ensure_initialized()
    except Exception:
        return _error("VectorStore provider initialization failed", 503)

    result = provider._collection.get(ids=[doc_id], include=["documents", "metadatas"])
    ids = result.get("ids", [])
    if not ids or ids[0] != doc_id:
        return _not_found()

    docs = result.get("documents", [])
    metas = result.get("metadatas", [])
    content = docs[0] if docs else ""
    metadata = metas[0] if metas and metas[0] else {}

    return _json({
        "id": doc_id,
        "content": content,
        "metadata": metadata,
    })


# ─── 删除文档 ────────────────────────────────────────────────────────────────


async def handle_admin_document_delete(request: web.Request) -> web.Response:
    """DELETE /api/admin/documents/{id}"""
    doc_id = request.match_info["id"]
    provider = _get_provider(request)
    if not provider:
        return _error("VectorStore provider not configured", 503)

    await provider.delete(ids=[doc_id])
    logger.info("[Admin] 删除文档: {}", doc_id)
    return _json({"deleted": True, "id": doc_id})


async def handle_admin_documents_batch_delete(request: web.Request) -> web.Response:
    """DELETE /api/admin/documents  (body: {ids: []})"""
    try:
        body = await request.json()
    except Exception:
        return _bad_request("Invalid JSON body")

    ids: list[str] = body.get("ids", [])
    if not ids:
        return _bad_request("ids is required and must be non-empty")

    provider = _get_provider(request)
    if not provider:
        return _error("VectorStore provider not configured", 503)

    await provider.delete(ids=ids)
    logger.info("[Admin] 批量删除 {} 篇文档", len(ids))
    return _json({"deleted": len(ids), "ids": ids})


# ─── 上传文件 ────────────────────────────────────────────────────────────────


ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}


async def handle_admin_documents_upload(request: web.Request) -> web.Response:
    """POST /api/admin/documents/upload

    Multipart form:
        file:     binary  — 上传的文件
        category: string  — 文档分类（可选，默认 "general"）
    """
    provider = _get_provider(request)
    if not provider:
        return _error("VectorStore provider not configured", 503)

    config = _get_config(request)
    if not config:
        return _error("VectorStore config not available", 503)

    try:
        form = await request.post()
    except Exception as e:
        return _bad_request(f"Failed to parse form data: {e}")

    uploaded_file = form.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return _bad_request("No file uploaded")

    filename = uploaded_file.filename
    category = form.get("category", "general")

    # 检查扩展名
    import os as _os
    ext = _os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return _json({
            "error": f"Unsupported file type: {ext} (supported: .pdf, .txt, .md)"
        }, status=415)

    # 流式写入临时文件
    tmp_path: str | None = None
    try:
        suffix = ext
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            # uploaded_file.file 是 BytesIO，直接读取写入临时文件
            tmp.write(uploaded_file.file.read())
        del form  # 提前释放 FieldStorage

        # 入库
        from nanobot.rag.ingest import DocumentIngestor

        tenant_id = request.app.get("admin_tenant_id", "default")
        ingestor = DocumentIngestor(
            vectorstore_config=config,
            tenant_id=tenant_id,
        )
        result = await ingestor.ingest_file(
            tmp_path,
            category=category,
            source_name=filename,
        )
    except Exception as e:
        logger.error("[Admin] 入库失败: {}", e)
        return _error(f"Document ingestion failed: {e}")
    finally:
        # 确保临时文件被清理
        if tmp_path:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass

    if result.errors:
        return _json({
            "error": result.errors[0],
            "file_name": filename,
        }, status=422)

    logger.info(
        "[Admin] 上传入库: {} → {} 个块 (ids={})",
        filename,
        result.chunks_created,
        result.doc_ids[:3],
    )
    return _json({
        "file_name": filename,
        "total_pages": result.total_pages,
        "chunks_created": result.chunks_created,
        "doc_ids": result.doc_ids,
    })


# ─── 统计 ────────────────────────────────────────────────────────────────────


async def handle_admin_documents_stats(request: web.Request) -> web.Response:
    """GET /api/admin/documents/stats"""
    provider = _get_provider(request)
    if not provider:
        return _error("VectorStore provider not configured", 503)

    stats = await provider.get_stats()
    return _json({
        "count": stats.count,
        "categories": stats.categories,
        "storage_bytes": stats.storage_bytes,
    })


# ─── 搜索 ─────────────────────────────────────────────────────────────────────


async def handle_admin_search(request: web.Request) -> web.Response:
    """GET /api/admin/search

    Query params:
        q:        str (required) — 搜索文本
        top_k:    int (default 5, max 20)
        category: str | None
    """
    q = request.query.get("q", "").strip()
    if not q:
        return _bad_request("q parameter is required")

    provider = _get_provider(request)
    if not provider:
        return _error("VectorStore provider not configured", 503)

    try:
        top_k = min(int(request.query.get("top_k", 5)), 20)
    except ValueError:
        return _bad_request("Invalid top_k parameter")

    category = request.query.get("category") or None
    meta_filter: dict[str, Any] | None = {"category": category} if category else None

    try:
        results = await provider.search(
            query=q,
            top_k=top_k,
            filter=meta_filter,
        )
    except Exception as e:
        logger.error("[Admin] 搜索失败: {}", e)
        return _error(f"Search failed: {e}")

    return _json({
        "results": [
            {
                "id": r.id,
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in results
        ],
        "query": q,
        "total": len(results),
    })
