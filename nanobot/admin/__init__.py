"""知识库管理后台

提供文档管理 API（列表、上传、删除、搜索）和 Bearer Token 认证。

本模块由 nanobot API server 在 admin.password 配置非空时自动加载。
"""

from nanobot.admin.auth import admin_auth_middleware

__all__ = ["admin_auth_middleware"]
