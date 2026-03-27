# design/ 目录规则

本目录包含各版本的详细设计文档。

## 当前文档

- `V1_DESIGN.md` — V1.0 完整设计文档（供人工阅读，1396行）
- `v1/` — V1 按章节拆分版本（供 AI 按需读取，每个文件 50-200 行）

## AI 使用规则

**实现具体模块时，只需读取 `v1/` 下对应文件**（而非完整的 `V1_DESIGN.md`）：

| 实现模块 | 读取文件 | 对应代码 |
|----------|---------|---------|
| 概述与架构 | `v1/overview-and-architecture.md` | 整体理解用 |
| 硬件 MQTT Channel | `v1/mqtt-channel.md` | `channels/hardware.py` |
| ASR/TTS Provider | `v1/asr-tts.md` | `providers/asr.py`, `providers/tts.py` |
| 多租户模块 | `v1/tenant.md` | `tenant/` |
| 管理后台 | `v1/admin.md` | `admin/` |
| Kids-Chat Skill | `v1/kids-chat.md` | `skills/kids-chat/` |
| 配置扩展 | `v1/config.md` | `config/schema.py` |

## 人工阅读

如需查看完整上下文，请阅读 `V1_DESIGN.md`（包含 §9 目录结构、§10 部署方案、§11 测试计划、§12 开放问题）。

## 后续版本

后续版本设计文档命名：`V2_DESIGN.md`, `V3_DESIGN.md`, `V4_DESIGN.md`，并同步拆分到 `v2/`, `v3/`, `v4/`。
