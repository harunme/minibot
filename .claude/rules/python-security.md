---
description: Python 安全编码约束 — SQL注入防护、密钥管理、输入校验
globs: "**/*.py"
---

# Python 安全编码规则

## SQL 注入防护（CRITICAL）

- **100% 使用参数化查询**，绝对禁止字符串拼接 SQL
- 所有数据库操作使用 `?` 占位符（SQLite）或 `:param`（SQLAlchemy）

```python
# ✅ 正确
cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,))

# ❌ 禁止
cursor.execute(f"SELECT * FROM devices WHERE id = '{device_id}'")
```

## 密钥管理

- API Key、Token、密码**不允许硬编码**在源码中
- 必须来自 `config.json`（权限 0600）或环境变量
- 密码使用 `bcrypt` 哈希，不使用 MD5/SHA 直接存储

## 输入校验

- 所有 MQTT payload 必须校验格式和长度
- 所有 HTTP 请求参数必须校验类型和范围
- 使用 Pydantic 模型做输入校验

## 异步安全

- 不允许在 asyncio 事件循环中使用阻塞调用
- 禁止 `time.sleep()`，使用 `asyncio.sleep()`
- 外部 API 调用必须设置超时：`asyncio.wait_for(coro, timeout=N)`
