# CLAUDE.md — AI 辅助开发约束文档

> **适用范围**：本项目（MiniBot / nanobot-ai）的所有 AI 辅助开发  
> **最后更新**：2026-03-27

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
| **构建系统** | Hatchling |
| **当前版本目标** | V1.0 — 核心对话链路（MVP） |

---

## 2. 核心原则 — ⚠️ 不可违反

### 2.1 扩展不改核心

**绝对不允许修改 nanobot 框架的核心文件。** 所有功能通过扩展点接入。

#### 🔒 禁止修改的文件

```
nanobot/agent/loop.py          # 核心处理循环
nanobot/agent/runner.py        # 通用工具调用 LLM 循环
nanobot/agent/context.py       # 上下文构建器
nanobot/agent/memory.py        # 记忆系统
nanobot/agent/skills.py        # 技能加载器
nanobot/agent/subagent.py      # 子代理管理器
nanobot/agent/tools/*.py       # 所有内置工具
nanobot/bus/*.py               # 消息总线
nanobot/channels/base.py       # 渠道基类
nanobot/channels/manager.py    # 渠道管理器
nanobot/channels/registry.py   # 渠道自动发现
nanobot/providers/base.py      # LLM Provider 基类
nanobot/providers/registry.py  # Provider 注册表
nanobot/config/schema.py       # 配置 Schema（仅允许追加字段，不允许修改已有字段）
nanobot/session/*.py           # 会话管理
nanobot/cli/*.py               # CLI 命令
nanobot/command/*.py           # 内置命令路由
nanobot/cron/*.py              # 定时任务
nanobot/heartbeat/*.py         # 心跳服务
nanobot/utils/*.py             # 工具函数
nanobot/templates/*.md         # 模板文件
nanobot/skills/**/SKILL.md     # 内置技能
```

#### ✅ 允许的扩展方式

| 扩展方式 | 说明 | 示例 |
|----------|------|------|
| **新增 Channel** | 继承 `BaseChannel`，放在 `nanobot/channels/` | `channels/hardware.py` |
| **新增 Provider** | 继承 `LLMProvider`，放在 `nanobot/providers/` | `providers/asr.py`, `providers/tts.py` |
| **新增 Tool** | 继承 `Tool`，在 `loop.py` 初始化时注册 | — |
| **新增 Skill** | 创建 `skills/<name>/SKILL.md` | `skills/kids-chat/SKILL.md` |
| **追加配置字段** | 在 `config/schema.py` 追加新的 Config 子类 | `HardwareConfig`, `TenantConfig` |
| **新增独立模块** | 在 `nanobot/` 下新建包 | `nanobot/tenant/`, `nanobot/admin/` |
| **新增测试** | 在 `tests/` 对应目录下新增 | `tests/channels/test_hardware_channel.py` |

### 2.2 分层边界

```
nanobot/                     # 框架层 — 不改
├── channels/hardware.py     # 新增扩展 — Channel 插件
├── providers/asr.py         # 新增扩展 — ASR Provider
├── providers/tts.py         # 新增扩展 — TTS Provider  
├── tenant/                  # 新增模块 — 多租户（完全新增）
├── admin/                   # 新增模块 — 管理后台（完全新增）
└── skills/kids-chat/        # 新增技能 — Kids-Chat Skill
```

---

## 3. 架构约束

### 3.1 通信协议

| 通信路径 | 协议 | 原因 |
|----------|------|------|
| ESP32 硬件 ↔ 后端 | **MQTT** | 轻量、低功耗、适合嵌入式 |
| 后端 ↔ 火山引擎 ASR/TTS | **WebSocket** | 火山引擎流式 API 要求 |
| 管理后台前端 ↔ 后端 | **HTTP REST** | 标准管理操作 |
| Channel ↔ Agent | **MessageBus**（内部 asyncio 队列） | nanobot 框架已有解耦机制 |

### 3.2 消息流

```
ESP32 → MQTT → HardwareChannel → MessageBus → AgentLoop → LLM
                                                    ↕
                                              ASR(WebSocket) / TTS(WebSocket)
                                                    ↕
ESP32 ← MQTT ← HardwareChannel ← MessageBus ← AgentLoop
```

### 3.3 数据存储

| 数据 | 存储方式 | 说明 |
|------|----------|------|
| 主库（租户/设备/用户） | SQLite `main.db` | 全局管理数据 |
| 租户数据 | SQLite `tenant_{id}.db` | 每租户独立数据库，物理隔离 |
| Agent 会话 | JSONL（nanobot 已有） | 不改变现有会话机制 |
| Agent 记忆 | MEMORY.md / HISTORY.md（nanobot 已有） | 不改变现有记忆机制 |

---

## 4. 代码规范

### 4.1 Python 风格

- **行宽**：100 字符（Ruff 检查，E501 已忽略）
- **目标版本**：Python 3.11+，可使用 `match`、`ExceptionGroup`、`tomllib` 等
- **类型标注**：所有公开接口必须有类型标注，使用 `from __future__ import annotations`
- **异步**：所有 I/O 操作使用 `async/await`，不允许在 asyncio 循环中使用阻塞调用
- **日志**：使用 `loguru.logger`，不使用 `print()` 或 `logging` 标准库
- **导入排序**：按 Ruff I 规则（isort 兼容）
- **数据类**：优先使用 `dataclass(slots=True)` 或 Pydantic `BaseModel`
- **配置模型**：继承项目中的 `Base` 类（支持 camelCase/snake_case 双向兼容）

### 4.2 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 模块/文件 | snake_case | `hardware.py`, `asr.py` |
| 类 | PascalCase | `HardwareChannel`, `ASRProvider` |
| 函数/方法 | snake_case | `async def start_listening()` |
| 常量 | UPPER_SNAKE_CASE | `MQTT_QOS_DEFAULT = 1` |
| 私有 | 前缀 `_` | `_running`, `_handle_message()` |
| MQTT Topic | 小写/斜杠分隔 | `device/{id}/audio/up` |
| 配置键 | 支持 camelCase 和 snake_case | `mqttBroker` / `mqtt_broker` |

### 4.3 错误处理

- 外部 API 调用（MQTT、WebSocket、HTTP）必须有重试和超时
- 捕获具体异常，不允许裸 `except Exception`（除非是最外层兜底）
- 设备离线/断连属于正常状态，用 `logger.info` 而非 `logger.error`
- 所有外部凭据（API Key、Token）不允许硬编码，必须来自配置或环境变量

### 4.4 安全约束

- **SQL 注入防护**：所有数据库操作使用参数化查询，绝对禁止字符串拼接 SQL
- **MQTT 认证**：设备接入必须验证 Token，不允许匿名连接（生产环境）
- **API 认证**：管理后台 API 使用 JWT，密码使用 bcrypt 哈希
- **输入校验**：所有外部输入（MQTT payload、HTTP 请求）必须校验
- **密钥管理**：API Key 存放在 `config.json`（权限 0600）或环境变量

---

## 5. 测试约束

### 5.1 测试要求

- 每个新模块必须有对应的测试文件
- 测试放在 `tests/` 对应子目录下
- 使用 pytest + pytest-asyncio
- Mock 所有外部依赖（MQTT Broker、火山引擎 API、数据库）

### 5.2 测试命名

```
tests/
├── channels/test_hardware_channel.py    # Channel 测试
├── providers/test_asr_provider.py       # ASR Provider 测试
├── providers/test_tts_provider.py       # TTS Provider 测试
├── tenant/test_tenant_manager.py        # 多租户测试
└── admin/test_admin_api.py              # 管理后台测试
```

### 5.3 运行测试

```bash
# 运行全部测试
pytest tests/

# 运行指定模块
pytest tests/channels/test_hardware_channel.py

# 带覆盖率
pytest --cov=nanobot tests/
```

---

## 6. 文件新增/修改决策树

在编写或修改任何代码前，遵循以下决策流程：

```
需要改动？
  │
  ├── 是 nanobot/ 核心文件？
  │     ├── 是 → ❌ 停止！不允许修改
  │     │         → 思考：能否通过新增文件实现？
  │     │         → 思考：能否通过配置/插件机制实现？
  │     └── 否 → 继续
  │
  ├── 是新增文件？
  │     ├── Channel → 放 nanobot/channels/
  │     ├── Provider → 放 nanobot/providers/
  │     ├── Skill → 放 nanobot/skills/<name>/
  │     ├── 独立模块 → 放 nanobot/<module>/
  │     └── 测试 → 放 tests/<module>/
  │
  ├── 是修改 config/schema.py？
  │     ├── 追加新字段/新类 → ✅ 允许
  │     └── 修改已有字段 → ❌ 不允许
  │
  └── 是修改 pyproject.toml？
        ├── 追加依赖 → ✅ 允许（附带版本约束）
        └── 修改构建配置 → ⚠️ 需要明确说明原因
```

---

## 7. V1 开发范围约束

### 7.1 里程碑顺序

```
M1 设计评审 → M2 MQTT通道 → M3 ASR/TTS → M4 对话链路 → M5 多租户 → M6 管理后台 → M7 集成验收
```

### 7.2 V1 包含

- ✅ 硬件 MQTT Channel（`channels/hardware.py`）
- ✅ ASR WebSocket 客户端（`providers/asr.py`）
- ✅ TTS WebSocket 客户端（`providers/tts.py`）
- ✅ MQTT Broker 部署配置
- ✅ 多租户框架（`tenant/` 包）
- ✅ 管理后台 MVP（`admin/` 包）
- ✅ Kids-Chat Skill
- ✅ 测试客户端

### 7.3 V1 不包含 — ⚠️ 不要实现

- ❌ RAG 知识库（V2 范围）
- ❌ 音色克隆（V3 范围）
- ❌ 硬件固件（V4 范围）
- ❌ 移动端 App
- ❌ GPS 定位 / SIM 卡功能

---

## 8. 依赖管理

### 8.1 新增依赖规则

- 必须在 `pyproject.toml` 的 `dependencies` 或 `[project.optional-dependencies]` 中声明
- 必须有版本约束（`>=x.y.z,<a.b.c` 格式）
- 优先使用已有依赖解决问题（如 `httpx`、`websockets`、`pydantic`）

### 8.2 V1 新增依赖

```toml
# 以下是 V1 可能新增的依赖（实际添加时遵循上述格式）
# aiomqtt        — MQTT 异步客户端
# fastapi        — 管理后台 HTTP API
# uvicorn        — ASGI 服务器
# python-jose    — JWT 认证
# bcrypt         — 密码哈希
# aiosqlite      — 异步 SQLite
```

---

## 9. 接口实现约束

### 9.1 Channel 实现模板

新增 Channel 必须继承 `BaseChannel` 并实现以下方法：

```python
from nanobot.channels.base import BaseChannel

class HardwareChannel(BaseChannel):
    name = "hardware"
    display_name = "Hardware MQTT"

    async def login(self, force: bool = False) -> bool: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, msg: OutboundMessage) -> None: ...
```

### 9.2 Provider 抽象约束

ASR 和 TTS 必须定义抽象基类，支持未来切换实现：

```python
# ASR 抽象基类
class ASRProvider(ABC):
    @abstractmethod
    async def recognize_stream(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]: ...

# TTS 抽象基类  
class TTSProvider(ABC):
    @abstractmethod
    async def synthesize_stream(self, text: str, voice: str) -> AsyncIterator[bytes]: ...
```

### 9.3 配置扩展约束

扩展配置时，继承项目中的 `Base` 类：

```python
from nanobot.config.schema import Base

class HardwareChannelConfig(Base):
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
```

---

## 10. Git 与协作约束

### 10.1 分支策略

- 当前工作分支：`develop`
- 新功能基于 `develop` 创建特性分支
- 不直接推送到 `main` 或 `nightly`

### 10.2 提交规范

```
<type>(<scope>): <description>

# type: feat / fix / docs / refactor / test / chore
# scope: channel / provider / tenant / admin / config / test

# 示例：
feat(channel): add HardwareChannel with MQTT support
feat(provider): implement VolcEngine ASR WebSocket client
test(channel): add unit tests for HardwareChannel
docs: update V1_DESIGN with implementation details
```

### 10.3 文档引用

每次开发新模块前，必须先阅读对应设计文档：

| 模块 | 参考文档 | 关键章节 |
|------|----------|----------|
| 整体架构 | `docs/v1/V1_DESIGN.md` | §2 系统架构 |
| MQTT Channel | `docs/v1/V1_DESIGN.md` | §3 硬件 MQTT Channel |
| ASR/TTS | `docs/v1/V1_DESIGN.md` | §4 ASR/TTS WebSocket 客户端 |
| 多租户 | `docs/v1/V1_DESIGN.md` | §5 多租户模块 |
| 管理后台 | `docs/v1/V1_DESIGN.md` | §6 管理后台 |
| Kids-Chat | `docs/v1/V1_DESIGN.md` | §7 Kids-Chat Skill |
| 配置设计 | `docs/v1/V1_DESIGN.md` | §8 配置设计 |
| 目录结构 | `docs/v1/V1_DESIGN.md` | §9 目录结构 |
| 路线图 | `docs/ROADMAP.md` | V1.0 章节 |
| 沟通记录 | `docs/PROJECT_COMMUNICATION.md` | 全文 |

---

## 11. AI 行为约束

### 11.1 开发前必做

1. **读文档**：开发任何模块前，先读 `docs/v1/V1_DESIGN.md` 对应章节
2. **看现有代码**：了解 nanobot 框架的扩展点实际实现
3. **确认范围**：确认要做的事在 V1 范围内
4. **确认不改核心**：确认实现方式不需要修改禁止修改的文件

### 11.2 开发中必做

1. **类型标注**：所有公开接口必须有类型标注
2. **docstring**：所有类和公开方法必须有 docstring
3. **异步**：所有 I/O 用 async/await
4. **日志**：使用 loguru.logger
5. **测试**：新代码必须有对应测试
6. **安全**：参数化查询、输入校验、密钥不硬编码

### 11.3 禁止行为

- ❌ 修改 `nanobot/` 下的核心框架文件
- ❌ 在 V1 中实现 V2-V4 的功能
- ❌ 使用 `print()` 做日志
- ❌ 使用阻塞 I/O（`time.sleep`、同步 HTTP 等）
- ❌ 硬编码 API Key、密码、Token
- ❌ 字符串拼接 SQL
- ❌ 裸 `except Exception`（无 re-raise 或日志）
- ❌ 删除或修改现有测试用例
- ❌ 添加没有版本约束的依赖

### 11.4 大文件处理

- 不要一次性重写整个大文件，使用**精确替换**编辑
- 如需修改已有文件（限允许修改的），先读取理解再做最小化修改
- 新建文件优于修改已有文件

---

## 12. 快速参考

### 框架扩展点速查

| 要做什么 | 扩展点 | 基类/接口 | 注册方式 |
|----------|--------|-----------|----------|
| 接入新聊天渠道 | `channels/` | `BaseChannel` | pkgutil 自动发现 |
| 接入新 LLM | `providers/` | `LLMProvider` | `providers/registry.py` 注册 |
| 添加新工具 | `agent/tools/` | `Tool` | `ToolRegistry.register()` |
| 添加新技能 | `skills/<name>/` | YAML frontmatter + Markdown | 自动扫描 |
| 添加配置 | `config/schema.py` | `Base` (Pydantic) | 追加字段 |

### 关键 import 路径

```python
from nanobot.channels.base import BaseChannel
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Base, Config
from loguru import logger
```

---

*本文档随项目演进更新。任何对核心原则的变更需经过团队讨论。*
