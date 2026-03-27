---
description: Provider 开发规范 — 继承基类，外部 API 重试/超时，密钥禁止硬编码
paths:
  - "nanobot/providers/**/*.py"
---

# Provider 开发规则

- 新增 Provider 继承 `LLMProvider`（LLM）或自定义抽象基类（ASR/TTS）
- 禁止修改 `base.py` 和 `registry.py`
- 参考 `docs/design/v1/asr-tts.md`（ASR/TTS Provider 设计）
- 所有外部 API 调用必须有重试和超时机制
- 密钥通过配置传入，禁止硬编码
- 使用 `loguru.logger` 做日志
