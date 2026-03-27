---
description: 核心框架文件保护 — 禁止修改 agent/bus/session/cli 等核心模块，所有功能通过扩展点接入
paths:
  - "nanobot/agent/**"
  - "nanobot/bus/**"
  - "nanobot/session/**"
  - "nanobot/cli/**"
  - "nanobot/command/**"
  - "nanobot/cron/**"
  - "nanobot/heartbeat/**"
  - "nanobot/utils/**"
  - "nanobot/templates/**"
  - "nanobot/channels/base.py"
  - "nanobot/channels/manager.py"
  - "nanobot/channels/registry.py"
  - "nanobot/providers/base.py"
  - "nanobot/providers/registry.py"
---

# ⚠️ 核心文件保护

**禁止修改这些文件！** 所有功能通过扩展点接入。

如需扩展功能，请使用以下方式：
- 新增 Channel → 继承 `BaseChannel`
- 新增 Provider → 继承 `LLMProvider`
- 新增 Tool → `ToolRegistry.register()`
- 新增 Skill → 创建 `skills/<name>/SKILL.md`
- 追加配置 → 在 `config/schema.py` 追加新类（不修改已有字段）
- 新增模块 → 在 `nanobot/` 下新建包
