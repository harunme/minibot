# design/ 目录规则

本目录包含各版本的详细设计文档。

## 目录结构

```
design/
├── CLAUDE.md              # 本文件（AI 路由表）
├── V1_DESIGN.md           # V1.0 完整设计文档（供人工阅读，含历史 MQTT 设计）
├── v1/                    # V1.0 按章节拆分（供 AI 按需读取）
│   ├── overview-and-architecture.md
│   ├── websocket-channel.md
│   ├── asr-tts.md
│   └── config.md
├── v2/                    # V2.0 设计文档
│   └── kids-chat.md
└── v3.5/                  # V3.5 设计文档
    ├── tenant.md
    └── admin.md
```

## AI 使用规则

**实现具体模块时，只需读取对应版本目录下的文件**（而非完整的 `V1_DESIGN.md`）：

### V1.0 — 核心对话链路

| 实现模块 | 读取文件 | 对应代码 |
|----------|---------|---------|
| 概述与架构 | `v1/overview-and-architecture.md` | 整体理解用 |
| WebSocket 语音通道 | `v1/websocket-channel.md` | `channels/websocket_hw.py` |
| ASR/TTS Provider | `v1/asr-tts.md` | `providers/asr.py`, `providers/tts.py` |
| 配置扩展 | `v1/config.md` | `config/schema.py` |

### V2.0 — 知识库与内容管理

| 实现模块 | 读取文件 | 对应代码 |
|----------|---------|---------|
| Kids-Chat Skill | `v2/kids-chat.md` | `skills/kids-chat/` |

### V3.5 — 多租户 + 管理后台

| 实现模块 | 读取文件 | 对应代码 |
|----------|---------|---------|
| 多租户模块 | `v3.5/tenant.md` | `tenant/` |
| 管理后台 | `v3.5/admin.md` | `admin/` |

## 人工阅读

如需查看完整上下文，请阅读 `V1_DESIGN.md`（包含 §9 目录结构、§10 部署方案、§11 测试计划、§12 开放问题）。

## 后续版本

后续版本设计文档命名：`V2_DESIGN.md`, `V3_DESIGN.md`/`V3.5_DESIGN.md`, `V4_DESIGN.md`，并同步拆分到对应版本目录。
