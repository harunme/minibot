# CLAUDE.md — AI 辅助开发约束文档

> **适用范围**：本项目（MiniBot / nanobot-ai）所有 AI 辅助开发  
> **最后更新**：2026-03-27

## 0. 上下文引用

@docs/ROADMAP.md

> 设计文档和决策记录通过 `docs/CLAUDE.md` 和 `docs/design/CLAUDE.md` 按需加载，不在此全量引用。

---

## 1. 项目身份

| 字段 | 值 |
|------|------|
| **项目名** | MiniBot 语音伴侣 — 基于 nanobot-ai 框架 |
| **框架版本** | nanobot-ai 0.1.4.post5 |
| **Python** | ≥ 3.11 |
| **代码风格** | Ruff（line-length=100, rules E/F/I/N/W, E501 忽略） |
| **异步运行时** | asyncio（全异步架构） |
| **测试框架** | pytest + pytest-asyncio（asyncio_mode = "auto"） |
| **当前目标** | V1.0 — 核心对话链路 MVP |

---

## 2. 核心原则 — ⚠️ 不可违反

### 2.1 扩展不改核心

**绝对不允许修改 nanobot 框架核心文件。** 所有功能通过扩展点接入。

禁止修改的范围：`nanobot/agent/`、`nanobot/bus/`、`nanobot/channels/base.py`、`nanobot/channels/manager.py`、`nanobot/channels/registry.py`、`nanobot/providers/base.py`、`nanobot/providers/registry.py`、`nanobot/session/`、`nanobot/cli/`、`nanobot/command/`、`nanobot/cron/`、`nanobot/heartbeat/`、`nanobot/utils/`、`nanobot/templates/`、`nanobot/skills/**/SKILL.md`。

`nanobot/config/schema.py` **仅允许追加字段/新类，不允许修改已有字段**。

### 2.2 允许的扩展方式

| 扩展方式 | 说明 |
|----------|------|
| 新增 Channel | 继承 `BaseChannel`，放 `nanobot/channels/` |
| 新增 Provider | 继承 `LLMProvider`，放 `nanobot/providers/` |
| 新增 Tool | 继承 `Tool`，`ToolRegistry.register()` 注册 |
| 新增 Skill | 创建 `skills/<name>/SKILL.md` |
| 追加配置字段 | 在 `config/schema.py` 追加新的 Config 子类 |
| 新增独立模块 | 在 `nanobot/` 下新建包（如 `tenant/`、`admin/`） |

---

## 3. 代码规范

- **类型标注**：所有公开接口必须有类型标注，使用 `from __future__ import annotations`
- **异步**：所有 I/O 使用 `async/await`，禁止阻塞调用（`time.sleep`、同步 HTTP）
- **日志**：使用 `loguru.logger`，禁止 `print()` 和 `logging` 标准库
- **数据类**：优先 `dataclass(slots=True)` 或 Pydantic `BaseModel`
- **配置模型**：继承项目中的 `Base` 类（支持 camelCase/snake_case 双向兼容）
- **命名**：模块 snake_case、类 PascalCase、常量 UPPER_SNAKE_CASE、MQTT Topic 小写/斜杠分隔
- **错误处理**：捕获具体异常，禁止裸 `except Exception`；外部 API 必须有重试和超时
- **安全**：参数化查询（禁止拼接 SQL）、输入校验、密钥不硬编码
- **依赖**：在 `pyproject.toml` 声明，必须有版本约束，优先复用已有依赖

---

## 4. V1 开发范围

**里程碑**：M1 设计评审 → M2 MQTT通道 → M3 ASR/TTS → M4 对话链路 → M5 多租户 → M6 管理后台 → M7 集成验收

**V1 包含**：硬件 MQTT Channel、ASR/TTS WebSocket 客户端、MQTT Broker 部署、多租户框架、管理后台 MVP、Kids-Chat Skill、测试客户端。

**V1 不包含 ⚠️**：RAG 知识库（V2）、音色克隆（V3）、硬件固件（V4）、移动端 App。

> 详细设计见 `docs/design/V1_DESIGN.md`，按模块章节参考。

---

## 5. 测试约束

- 每个新模块必须有对应测试文件，放 `tests/` 对应子目录
- 使用 pytest + pytest-asyncio，Mock 所有外部依赖
- 运行：`pytest tests/` 或 `pytest --cov=nanobot tests/`

---

## 6. Git 与协作

- 当前分支：`develop`，不直接推送 `main` 或 `nightly`
- 提交格式：`<type>(<scope>): <description>`（type: feat/fix/docs/refactor/test/chore）
- 开发新模块前必须先读 `docs/design/V1_DESIGN.md` 对应章节

---

## 7. AI 行为约束

### 开发前

1. 读设计文档对应章节 → 2. 看框架扩展点实际代码 → 3. 确认在 V1 范围内 → 4. 确认不改核心文件

### 禁止行为

- ❌ 修改 nanobot 核心框架文件
- ❌ 在 V1 实现 V2-V4 功能
- ❌ `print()` 做日志 / 阻塞 I/O / 硬编码密钥 / 拼接 SQL / 裸 `except`
- ❌ 删除或修改现有测试 / 添加无版本约束依赖
- ❌ 一次性重写大文件（用精确替换编辑）

---

*本文档随项目演进更新。任何对核心原则的变更需经过团队讨论。*
