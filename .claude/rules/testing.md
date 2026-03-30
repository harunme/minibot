---
description: 测试编写规范 — pytest/pytest-asyncio 约定
globs: "tests/**/*.py"
---

# 测试编写规范

## 框架

- 使用 `pytest` + `pytest-asyncio`（asyncio_mode = "auto"）
- 异步测试直接用 `async def test_xxx():`，无需 `@pytest.mark.asyncio`

## Mock 原则

- **所有外部依赖必须 Mock**：WebSocket 连接、火山引擎 API、数据库连接
- 使用 `unittest.mock.AsyncMock` 模拟异步调用
- 使用 `pytest.fixture` 提供可复用的 Mock 对象

## 命名

- 文件名：`test_<模块名>.py`
- 函数名：`test_<行为描述>()`
- Fixture 名：`<对象>_fixture` 或直接用名词

```python
# ✅ 好的命名
async def test_websocket_channel_accepts_connection(): ...
async def test_asr_provider_handles_timeout_gracefully(): ...

# ❌ 不好的命名
async def test1(): ...
async def test_it_works(): ...
```

## 禁止

- ❌ 不删除或修改现有测试用例
- ❌ 不跳过测试（`@pytest.mark.skip`）除非有明确原因和注释
- ❌ 不在测试中使用真实的外部服务
