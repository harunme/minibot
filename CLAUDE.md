# CLAUDE.md — AI 辅助开发约束文档

> **适用范围**：本项目（MiniBot / nanobot-ai）所有 AI 辅助开发  
> **最后更新**：2026-03-30  
> **优先级**：本文件中的规则优先于 `docs/` 下任何文档。如有冲突，以本文件为准。

<!-- 
维护者注意：
- 根 CLAUDE.md 目标行数 ≤ 200 行，超出请考虑外移到 docs/ 或 .claude/rules/
- 下方的禁止修改列表需要随框架版本更新，当前 nanobot 版本为 0.1.4.post5
- 路径特定规则已拆分到 .claude/rules/ 目录，见 channel-development.md 和 core-protection.md
- 「当前进度」节(§0.1)需随开发推进及时更新
-->

## 0. 上下文引用

- 版本路线图详见 `docs/ROADMAP.md`（V1-V5 范围和里程碑）
- 技术决策详见 `docs/DECISIONS.md`
- 详细设计按版本拆分在 `docs/design/v1/` 下（开发具体模块时只读对应文件，见 `docs/design/CLAUDE.md` 路由表）

## 0.1 当前进度

> V1.0 范围为 M1-M4（核心对话链路），多租户+管理后台已推迟到 V3.5，Kids-Chat 推迟到 V2.0。详见 ROADMAP.md 和 DECISIONS.md。

| 里程碑 | 状态 | 说明 |
|--------|------|------|
| M1 - 设计评审 | ✅ 完成 | V1_DESIGN.md 已评审通过 |
| M2 - WebSocket 通道 | ✅ 完成 | WebSocket Channel（面向 Tauri/Web）+ 测试客户端 |
| M3 - ASR/TTS | ✅ 完成 | 火山引擎 WebSocket 客户端（ASRProvider + TTSProvider） |
| M4 - 对话链路 | ⏳ 未开始 | 全链路打通（单租户） |

---

## 1. 常用命令

```bash
# 安装（开发模式）
pip install -e ".[dev]"

# 运行测试
pytest tests/
pytest --cov=nanobot tests/

# 代码检查
ruff check nanobot/ tests/

# 启动网关
nanobot gateway

# WebSocket 测试客户端
python tools/ws_test_client.py --device dev001 --url ws://localhost:9000 --mic --play
```

---

## 2. 项目身份

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

## 3. 核心原则 — ⚠️ 不可违反

### 3.1 扩展不改核心

**绝对不允许修改 nanobot 框架核心文件。** 所有功能通过扩展点接入。

> 详细的路径保护规则见 `.claude/rules/core-protection.md`（自动生效）。

### 3.2 允许的扩展方式

| 扩展方式 | 说明 |
|----------|------|
| 新增 Channel | 继承 `BaseChannel`，放 `nanobot/channels/` |
| 新增 Provider | 继承 `LLMProvider`，放 `nanobot/providers/` |
| 新增 Tool | 继承 `Tool`，`ToolRegistry.register()` 注册 |
| 新增 Skill | 创建 `skills/<name>/SKILL.md` |
| 新增/修改配置字段 | 在 `config/schema.py` 中新增或修改 Config 类字段 |
| 新增独立模块 | 在 `nanobot/` 下新建包（如 `tenant/`、`admin/`） |

---

## 4. 代码规范

- **类型标注**：所有公开接口必须有类型标注，使用 `from __future__ import annotations`
- **异步**：所有 I/O 使用 `async/await`，禁止阻塞调用（`time.sleep`、同步 HTTP）
- **日志**：使用 `loguru.logger`，禁止 `print()` 和 `logging` 标准库
- **数据类**：优先 `dataclass(slots=True)` 或 Pydantic `BaseModel`
- **配置模型**：继承项目中的 `Base` 类（支持 camelCase/snake_case 双向兼容）
- **命名**：模块 snake_case、类 PascalCase、常量 UPPER_SNAKE_CASE
- **错误处理**：捕获具体异常，禁止裸 `except Exception`；外部 API 必须有重试和超时
- **安全**：参数化查询（禁止拼接 SQL）、输入校验、密钥不硬编码
- **依赖**：在 `pyproject.toml` 声明，必须有版本约束，优先复用已有依赖
- **注释**：每段代码必须在必要的地方加上中文注释。具体要求：
  - 每个模块文件顶部必须有 docstring，说明该模块的职责和用途
  - 每个类必须有 docstring，说明其作用、关键属性和使用方式
  - 每个公开方法/函数必须有 docstring，说明参数、返回值和异常
  - 复杂逻辑、非显而易见的算法、workaround、魔法数字必须有行内注释
  - 注释语言统一使用**中文**
  - 禁止无意义的废话注释（如 `# 设置 x 为 1` 对应 `x = 1`），注释应解释 **为什么** 而非 **是什么**

---

## 5. V1 开发范围

**里程碑**：M1 设计评审 → M2 WebSocket 通道 → M3 ASR/TTS → M4 对话链路

**V1 包含**：**WebSocket Channel（面向 Tauri/Web 客户端）**、火山引擎 ASR/TTS WebSocket 客户端（抽象层支持多厂商扩展）、测试客户端。

**V1 不包含 ⚠️**：多租户（V3.5）、管理后台（V3.5）、Kids-Chat Skill（V2.0）、RAG 知识库（V2）、硬件固件（V3）、音色克隆（V4）、移动端 App（V5b）。

> 详细设计见 `docs/design/v1/` 目录（按模块拆分，路由表见 `docs/design/CLAUDE.md`）。
> 决策变更记录见 `docs/DECISIONS.md`。

---

## 6. 测试约束

- 每个新模块必须有对应测试文件，放 `tests/` 对应子目录
- 使用 pytest + pytest-asyncio，Mock 所有外部依赖
- 运行：`pytest tests/` 或 `pytest --cov=nanobot tests/`

---

## 7. Git 与协作

- 当前分支：`develop`，不直接推送 `main` 或 `nightly`
- 提交格式：`<type>(<scope>): <description>`（type: feat/fix/docs/refactor/test/chore）
- 开发新模块前必须先读 `docs/design/v1/` 对应章节文件（路由表见 `docs/design/CLAUDE.md`）

---

## 8. AI 行为约束

### 开发前

1. 读设计文档对应章节 → 2. 看框架扩展点实际代码 → 3. 确认在 V1 范围内 → 4. 确认不改核心文件

### 禁止行为

- ❌ 修改 nanobot 核心框架文件
- ❌ 在 V1 实现 V2-V5 功能
- ❌ `print()` 做日志 / 阻塞 I/O / 硬编码密钥 / 拼接 SQL / 裸 `except`
- ❌ 删除或修改现有测试 / 添加无版本约束依赖
- ❌ 一次性重写大文件（用精确替换编辑）

---

## 9. 常见陷阱

- `pytest-asyncio` 需要 `asyncio_mode = "auto"`（已在 `pyproject.toml` 配置），否则异步测试会被静默跳过
- `config/schema.py` 修改后运行 `pytest tests/test_config.py` 验证兼容性
- 火山引擎 WebSocket API 有连接超时限制，测试中务必 Mock

---

## 10. 环境变量（开发环境）

| 变量 | 用途 | 示例 |
|------|------|------|
| `VOLC_ASR_APPID` | 火山引擎 ASR App ID | `xxxxxx` |
| `VOLC_ASR_TOKEN` | 火山引擎 ASR Token | `xxxxxx` |
| `VOLC_TTS_APPID` | 火山引擎 TTS App ID | `xxxxxx` |
| `VOLC_TTS_TOKEN` | 火山引擎 TTS Token | `xxxxxx` |

> 密钥也可放在 `config.json`（权限 0600），详见 `SECURITY.md`。

---

*本文档随项目演进更新。任何对核心原则的变更需经过团队讨论。*
