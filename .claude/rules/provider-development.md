---
paths:
  - "nanobot/providers/**/*.py"
---

# Provider 开发规则

- 新增 Provider 继承 `LLMProvider`（LLM）或自定义抽象基类（ASR/TTS）
- 禁止修改 `base.py` 和 `registry.py`
- 参考 `docs/design/V1_DESIGN.md` §4 章节（ASR/TTS Provider）
- 所有外部 API 调用必须有重试和超时机制
- 密钥通过配置传入，禁止硬编码
- 使用 `loguru.logger` 做日志
