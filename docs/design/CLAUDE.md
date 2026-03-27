# design/ 目录规则

本目录包含各版本的详细设计文档。

## 当前文档

- `V1_DESIGN.md` — V1.0 核心对话链路 MVP 详细设计（1394行）

## 使用规则

- 实现具体模块时，只需阅读对应章节（而非全文）：
  - §3 硬件 MQTT Channel → 实现 `channels/hardware.py` 时参考
  - §4 ASR/TTS WebSocket → 实现 `providers/asr.py`, `providers/tts.py` 时参考
  - §5 多租户模块 → 实现 `tenant/` 时参考
  - §6 管理后台 → 实现 `admin/` 时参考
  - §7 Kids-Chat Skill → 实现 `skills/kids-chat/` 时参考
  - §8 配置设计 → 扩展 `config/schema.py` 时参考
- 后续版本设计文档命名：`V2_DESIGN.md`, `V3_DESIGN.md`, `V4_DESIGN.md`
