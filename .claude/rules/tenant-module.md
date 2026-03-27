---
paths:
  - "nanobot/tenant/**/*.py"
---

# 多租户模块开发规则

- 参考 `docs/design/V1_DESIGN.md` §5 章节
- 使用 SQLite 多数据库方案（每租户一个文件）
- 所有 SQL 使用参数化查询，禁止拼接 SQL
- 数据模型使用 `dataclass(slots=True)` 或 Pydantic `BaseModel`
- 确保租户数据隔离
