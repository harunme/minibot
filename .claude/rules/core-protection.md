---
description: nanobot 框架核心文件保护 — 禁止修改，只能通过扩展点扩展
globs: "nanobot/agent/**,nanobot/bus/**,nanobot/channels/base.py,nanobot/channels/manager.py,nanobot/channels/registry.py,nanobot/providers/base.py,nanobot/providers/registry.py,nanobot/session/**,nanobot/cli/**,nanobot/command/**,nanobot/cron/**,nanobot/heartbeat/**,nanobot/utils/**"
---

# ⛔ 核心文件保护

**你正在编辑的文件属于 nanobot 框架核心，禁止修改。**

## 规则

1. **不修改**此文件的任何现有代码
2. **不添加**新的函数、类或逻辑到此文件
3. **不删除**任何现有代码

## 应该怎么做

如果你需要新功能，请通过以下扩展点实现：

| 需求 | 正确方式 |
|------|----------|
| 新聊天渠道 | 创建 `nanobot/channels/<name>.py`，继承 `BaseChannel` |
| 新 LLM 提供者 | 创建 `nanobot/providers/<name>.py`，继承 `LLMProvider` |
| 新工具 | 创建 `nanobot/agent/tools/<name>.py`，继承 `Tool` |
| 新技能 | 创建 `nanobot/skills/<name>/SKILL.md` |
| 新配置字段 | 在 `config/schema.py` **追加**新类（不修改已有字段） |
| 新独立模块 | 创建 `nanobot/<module>/` 新包 |

## 唯一例外

`config/schema.py` 允许**追加**新的配置字段和新类，但不允许修改已有字段的类型或默认值。
