"""OpenAI-compatible HTTP API server for a fixed nanobot session.

Provides /v1/chat/completions and /v1/models endpoints.
All requests route to a single persistent API session.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from aiohttp import web
from loguru import logger

API_SESSION_KEY = "api:default"
API_CHAT_ID = "default"


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _error_json(status: int, message: str, err_type: str = "invalid_request_error") -> web.Response:
    return web.json_response(
        {"error": {"message": message, "type": err_type, "code": status}},
        status=status,
    )


def _chat_completion_response(content: str, model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _response_text(value: Any) -> str:
    """Normalize process_direct output to plain assistant text."""
    if value is None:
        return ""
    if hasattr(value, "content"):
        return str(getattr(value, "content") or "")
    return str(value)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_chat_completions(request: web.Request) -> web.Response:
    """POST /v1/chat/completions"""

    # --- Parse body ---
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        return _error_json(400, "Only a single user message is supported")

    # Stream not yet supported
    if body.get("stream", False):
        return _error_json(400, "stream=true is not supported yet. Set stream=false or omit it.")

    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user":
        return _error_json(400, "Only a single user message is supported")
    user_content = message.get("content", "")
    if isinstance(user_content, list):
        # Multi-modal content array — extract text parts
        user_content = " ".join(
            part.get("text", "") for part in user_content if part.get("type") == "text"
        )

    agent_loop = request.app["agent_loop"]
    timeout_s: float = request.app.get("request_timeout", 120.0)
    model_name: str = request.app.get("model_name", "nanobot")
    if (requested_model := body.get("model")) and requested_model != model_name:
        return _error_json(400, f"Only configured model '{model_name}' is available")

    session_key = f"api:{body['session_id']}" if body.get("session_id") else API_SESSION_KEY
    session_locks: dict[str, asyncio.Lock] = request.app["session_locks"]
    session_lock = session_locks.setdefault(session_key, asyncio.Lock())

    logger.info("API request session_key={} content={}", session_key, user_content[:80])

    _FALLBACK = "I've completed processing but have no response to give."

    try:
        async with session_lock:
            try:
                response = await asyncio.wait_for(
                    agent_loop.process_direct(
                        content=user_content,
                        session_key=session_key,
                        channel="api",
                        chat_id=API_CHAT_ID,
                    ),
                    timeout=timeout_s,
                )
                response_text = _response_text(response)

                if not response_text or not response_text.strip():
                    logger.warning(
                        "Empty response for session {}, retrying",
                        session_key,
                    )
                    retry_response = await asyncio.wait_for(
                        agent_loop.process_direct(
                            content=user_content,
                            session_key=session_key,
                            channel="api",
                            chat_id=API_CHAT_ID,
                        ),
                        timeout=timeout_s,
                    )
                    response_text = _response_text(retry_response)
                    if not response_text or not response_text.strip():
                        logger.warning(
                            "Empty response after retry for session {}, using fallback",
                            session_key,
                        )
                        response_text = _FALLBACK

            except asyncio.TimeoutError:
                return _error_json(504, f"Request timed out after {timeout_s}s")
            except Exception:
                logger.exception("Error processing request for session {}", session_key)
                return _error_json(500, "Internal server error", err_type="server_error")
    except Exception:
        logger.exception("Unexpected API lock error for session {}", session_key)
        return _error_json(500, "Internal server error", err_type="server_error")

    return web.json_response(_chat_completion_response(response_text, model_name))


async def handle_models(request: web.Request) -> web.Response:
    """GET /v1/models"""
    model_name = request.app.get("model_name", "nanobot")
    return web.json_response({
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "created": 0,
                "owned_by": "nanobot",
            }
        ],
    })


async def handle_health(request: web.Request) -> web.Response:
    """GET /health"""
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    agent_loop,
    model_name: str = "nanobot",
    request_timeout: float = 120.0,
    admin_password: str = "",
    vectorstore_config=None,
    admin_tenant_id: str = "default",
) -> web.Application:
    """Create the aiohttp application.

    Args:
        agent_loop: An initialized AgentLoop instance.
        model_name: Model name reported in responses.
        request_timeout: Per-request timeout in seconds.
        admin_password: Bearer token for /api/admin/* endpoints. Empty = admin disabled.
        vectorstore_config: VectorStoreConfig for admin knowledge base management.
        admin_tenant_id: Tenant ID for admin knowledge base operations.
    """
    import os

    from nanobot.admin import handlers as admin_handlers
    from nanobot.admin.auth import admin_auth_middleware

    app = web.Application()
    app["agent_loop"] = agent_loop
    app["model_name"] = model_name
    app["request_timeout"] = request_timeout
    app["session_locks"] = {}  # per-user locks, keyed by session_key

    # Admin backend (知识库管理)
    if admin_password:
        from nanobot.admin import auth as admin_auth

        admin_auth.ADMIN_PASSWORD = admin_password
        app.middlewares.append(admin_auth_middleware)

        app["vectorstore_config"] = vectorstore_config
        app["admin_tenant_id"] = admin_tenant_id

        if vectorstore_config and vectorstore_config.provider != "none":
            from nanobot.providers.vectorstore import create_vectorstore_provider

            app["vectorstore_provider"] = create_vectorstore_provider(
                vectorstore_config,
                tenant_id=admin_tenant_id,
            )

        # Register admin routes
        app.router.add_get("/api/admin/documents", admin_handlers.handle_admin_documents_list)
        app.router.add_get("/api/admin/documents/{id}", admin_handlers.handle_admin_document_get)
        app.router.add_delete("/api/admin/documents/{id}", admin_handlers.handle_admin_document_delete)
        app.router.add_delete("/api/admin/documents", admin_handlers.handle_admin_documents_batch_delete)
        app.router.add_post("/api/admin/documents/upload", admin_handlers.handle_admin_documents_upload)
        app.router.add_get("/api/admin/documents/stats", admin_handlers.handle_admin_documents_stats)
        app.router.add_get("/api/admin/search", admin_handlers.handle_admin_search)

        # Serve built frontend at /admin/*
        static_dir = os.path.join(os.path.dirname(__file__), "admin", "static")
        if os.path.isdir(static_dir):
            app.router.add_static("/admin", static_dir)

            async def serve_spa(request: web.Request) -> web.Response:
                """SPA fallback: serve index.html for non-file paths under /admin/*"""
                path = request.match_info["path"]
                file_path = os.path.join(static_dir, path)
                if os.path.isfile(file_path):
                    return web.FileResponse(file_path)
                return web.FileResponse(os.path.join(static_dir, "index.html"))

            app.router.add_get("/admin/{path:.*}", serve_spa)

    app.router.add_post("/v1/chat/completions", handle_chat_completions)
    app.router.add_get("/v1/models", handle_models)
    app.router.add_get("/health", handle_health)
    return app
