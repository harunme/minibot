---
description: Channel 开发规范 — 继承 BaseChannel，MQTT Topic 命名，异步 I/O 约束
paths:
  - "nanobot/channels/**/*.py"
---

# Channel 开发规则

- 必须继承 `BaseChannel`，放置于 `nanobot/channels/` 目录
- 禁止修改 `base.py`、`manager.py`、`registry.py`
- 参考 `docs/design/v1/mqtt-channel.md`（硬件 MQTT Channel 设计）
- 所有 I/O 使用 `async/await`，禁止阻塞调用
- 使用 `loguru.logger` 做日志，禁止 `print()`
- MQTT 相关 Topic 统一小写/斜杠分隔
