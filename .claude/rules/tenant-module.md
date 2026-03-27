---
description: 多租户模块开发规范 — SQLite 多数据库方案，参数化查询，租户数据隔离
paths:
  - "nanobot/tenant/**/*.py"
---

# 多租户模块开发规则

- 参考 `docs/design/v1/tenant.md`（多租户模块设计）
- 使用 SQLite 多数据库方案（每租户一个文件）
- 所有 SQL 使用参数化查询，禁止拼接 SQL
- 数据模型使用 `dataclass(slots=True)` 或 Pydantic `BaseModel`
- 确保租户数据隔离
