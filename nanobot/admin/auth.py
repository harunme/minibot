"""Bearer Token 认证中间件"""

import secrets
from typing import Callable

from aiohttp import web

# 由 create_app() 在启动时从配置注入
ADMIN_PASSWORD: str = ""


def _unauthorized(message: str = "Unauthorized") -> web.Response:
    return web.json_response({"error": message}, status=401)


@web.middleware
async def admin_auth_middleware(
    request: web.Request,
    handler: Callable[[web.Request], web.StreamResponse],
) -> web.StreamResponse:
    """Bearer Token 认证中间件

    仅拦截 /api/admin/* 路径，其余放行。
    使用 secrets.compare_digest 做恒定时间比较，防止时序攻击。
    """
    if not request.path.startswith("/api/admin"):
        return await handler(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return _unauthorized("Missing or invalid Authorization header")

    token = auth_header[7:]  # strip "Bearer "
    if not ADMIN_PASSWORD or not secrets.compare_digest(token, ADMIN_PASSWORD):
        return _unauthorized("Invalid password")
    return await handler(request)
