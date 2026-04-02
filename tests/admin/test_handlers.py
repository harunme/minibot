"""Admin API 测试"""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from nanobot.admin.auth import admin_auth_middleware, ADMIN_PASSWORD


class TestAdminAuthMiddleware:
    """认证中间件测试"""

    async def test_passes_through_non_admin_paths(self):
        """非 /api/admin 路径直接放行"""
        handler = AsyncMock(return_value=web.Response(text="ok"))
        request = MagicMock()
        request.path = "/v1/chat/completions"
        result = await admin_auth_middleware(request, handler)
        handler.assert_called_once_with(request)
        assert result.status == 200

    async def test_missing_bearer_returns_401(self):
        """缺少 Authorization header 返回 401"""
        handler = AsyncMock()
        request = MagicMock()
        request.path = "/api/admin/documents"
        request.headers.get = MagicMock(return_value="")  # 空 header，返回空字符串而非 MagicMock
        import nanobot.admin.auth as admin_auth
        admin_auth.ADMIN_PASSWORD = "secret123"

        result = await admin_auth_middleware(request, handler)
        assert result.status == 401
        import json
        body = json.loads(result.body)
        assert "Authorization" in body["error"]

    async def test_wrong_token_returns_401(self):
        """错误 token 返回 401"""
        import nanobot.admin.auth as admin_auth
        admin_auth.ADMIN_PASSWORD = "correct-token"
        handler = AsyncMock()
        request = MagicMock()
        request.path = "/api/admin/documents"
        request.headers.get.return_value = "Bearer wrong-token"

        result = await admin_auth_middleware(request, handler)
        assert result.status == 401

    async def test_correct_token_passes_through(self):
        """正确的 token 放行"""
        import nanobot.admin.auth as admin_auth
        admin_auth.ADMIN_PASSWORD = "my-secret"
        handler = AsyncMock(return_value=web.Response(text="ok"))
        request = MagicMock()
        request.path = "/api/admin/documents"
        request.headers.get.return_value = "Bearer my-secret"

        result = await admin_auth_middleware(request, handler)
        handler.assert_called_once_with(request)


class TestAdminHandlers:
    """API 处理器测试"""

    def _make_app(self, provider=None, config=None):
        """创建带 admin 路由的测试 app"""
        from nanobot.admin import handlers as h

        app = web.Application()
        app["vectorstore_provider"] = provider
        app["vectorstore_config"] = config
        app["admin_tenant_id"] = "default"

        # 注册路由（不使用 auth 中件间，在测试中单独测试）
        app.router.add_get("/api/admin/documents", h.handle_admin_documents_list)
        app.router.add_get("/api/admin/documents/stats", h.handle_admin_documents_stats)
        app.router.add_get("/api/admin/search", h.handle_admin_search)
        return app

    async def test_list_documents_returns_correct_format(self):
        """GET /api/admin/documents 返回正确格式"""
        mock_provider = AsyncMock()
        mock_provider.list_documents = AsyncMock(return_value=(
            [
                {
                    "id": "doc1",
                    "content_preview": "内容预览...",
                    "metadata": {"source": "test.pdf", "category": "story"},
                }
            ],
            1,
        ))
        app = self._make_app(provider=mock_provider)

        client = TestClient(TestServer(app))
        async with client as c:
            resp = await c.get("/api/admin/documents")
            assert resp.status == 200
            body = await resp.json()
            assert body["total"] == 1
            assert body["limit"] == 50
            assert len(body["documents"]) == 1
            assert body["documents"][0]["id"] == "doc1"

    async def test_list_documents_with_category_filter(self):
        """GET /api/admin/documents?category=story 正确传递过滤参数"""
        mock_provider = AsyncMock()
        mock_provider.list_documents = AsyncMock(return_value=([], 0))
        app = self._make_app(provider=mock_provider)

        client = TestClient(TestServer(app))
        async with client as c:
            resp = await c.get("/api/admin/documents?category=story&limit=10&offset=5")
            assert resp.status == 200
            mock_provider.list_documents.assert_called_once_with(
                limit=10,
                offset=5,
                category="story",
            )

    async def test_list_documents_no_provider_returns_503(self):
        """未配置 provider 时返回 503"""
        app = self._make_app(provider=None)
        client = TestClient(TestServer(app))
        async with client as c:
            resp = await c.get("/api/admin/documents")
            assert resp.status == 503

    async def test_stats_returns_correct_format(self):
        """GET /api/admin/documents/stats 返回正确格式"""
        mock_stats = MagicMock()
        mock_stats.count = 42
        mock_stats.categories = {"story": 30, "poem": 12}
        mock_stats.storage_bytes = 102400

        mock_provider = AsyncMock()
        mock_provider.get_stats = AsyncMock(return_value=mock_stats)
        app = self._make_app(provider=mock_provider)

        client = TestClient(TestServer(app))
        async with client as c:
            resp = await c.get("/api/admin/documents/stats")
            assert resp.status == 200
            body = await resp.json()
            assert body["count"] == 42
            assert body["categories"] == {"story": 30, "poem": 12}
            assert body["storage_bytes"] == 102400

    async def test_search_returns_results(self):
        """GET /api/admin/search 返回搜索结果"""
        from nanobot.providers.vectorstore import SearchResult

        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(return_value=[
            SearchResult(
                id="r1",
                content="孙悟空三打白骨精",
                score=0.95,
                metadata={"source": "westjourney.pdf"},
            )
        ])
        app = self._make_app(provider=mock_provider)

        client = TestClient(TestServer(app))
        async with client as c:
            resp = await c.get("/api/admin/search?q=西游记&top_k=5")
            assert resp.status == 200
            body = await resp.json()
            assert body["total"] == 1
            assert body["results"][0]["content"] == "孙悟空三打白骨精"
            assert body["results"][0]["score"] == 0.95

    async def test_search_missing_q_returns_400(self):
        """缺少 q 参数返回 400"""
        app = self._make_app(provider=AsyncMock())
        client = TestClient(TestServer(app))
        async with client as c:
            resp = await c.get("/api/admin/search")
            assert resp.status == 400

    async def test_batch_delete_returns_deleted_count(self):
        """DELETE /api/admin/documents 批量删除"""
        from nanobot.admin import handlers as h

        mock_provider = AsyncMock()
        mock_provider.delete = AsyncMock()
        app = self._make_app(provider=mock_provider)
        app.router.add_delete("/api/admin/documents", h.handle_admin_documents_batch_delete)

        client = TestClient(TestServer(app))
        async with client as c:
            resp = await c.request(
                "DELETE",
                "/api/admin/documents",
                json={"ids": ["id1", "id2", "id3"]},
            )
            assert resp.status == 200
            body = await resp.json()
            assert body["deleted"] == 3
            assert body["ids"] == ["id1", "id2", "id3"]

    async def test_batch_delete_empty_ids_returns_400(self):
        """空 ids 列表返回 400"""
        from nanobot.admin import handlers as h

        app = self._make_app(provider=AsyncMock())
        app.router.add_delete("/api/admin/documents", h.handle_admin_documents_batch_delete)

        client = TestClient(TestServer(app))
        async with client as c:
            resp = await c.request("DELETE", "/api/admin/documents", json={"ids": []})
            assert resp.status == 400
