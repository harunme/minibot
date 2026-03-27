# V1 §4 ASR/TTS WebSocket 客户端

> 摘自 `V1_DESIGN.md` §4，实现 `nanobot/providers/asr.py` 和 `nanobot/providers/tts.py` 时参考。

## 4.1 概述

后端内部通过 WebSocket 客户端连接火山引擎的 ASR（语音识别）和 TTS（语音合成）流式 API。这一层对上层 Channel 透明，Channel 只需调用 `asr_client.recognize()` 和 `tts_client.synthesize()`。

**V1 统一使用火山引擎**，ASR/TTS 均通过 WebSocket 流式 API 调用。抽象层（`ASRProvider` / `TTSProvider`）支持多提供商扩展，未来可接入阿里等厂商。

## 4.2 ASR 客户端（火山引擎语音识别）

```python
# nanobot/providers/asr.py

class ASRProvider(ABC):
    """ASR 语音识别提供者抽象基类 — 支持多提供商扩展"""
    
    @abstractmethod
    async def recognize(self, audio_data: bytes, *, format: str = "opus",
                        sample_rate: int = 16000, language: str = "zh-CN") -> str | None:
        """将音频转为文本"""
        ...
    
    @abstractmethod
    def recognize_stream(self, audio_stream: AsyncIterator[bytes], *,
                               format: str = "opus", sample_rate: int = 16000) -> AsyncIterator[str]:
        """流式识别：边发送音频边获取中间结果
        
        注意：子类实现时使用 async def + yield（async generator）。
        抽象基类中不能使用 yield，因此声明为普通方法返回 AsyncIterator[str]。
        """
        ...


class VolcengineASRProvider(ASRProvider):
    """火山引擎 ASR WebSocket 流式识别实现（V1 主选）"""
    
    def __init__(self, app_id: str, token: str, cluster: str = "volcengine_streaming_common"):
        self.ws_url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    
    # recognize(): WebSocket 发送完整音频，获取识别结果
    # recognize_stream(): 并行发送音频 + 接收结果

# 扩展：未来可新增 AliyunASRProvider(ASRProvider) 等
```

## 4.3 TTS 客户端（火山引擎语音合成）

```python
# nanobot/providers/tts.py

class TTSProvider(ABC):
    """TTS 语音合成提供者抽象基类 — 支持多提供商扩展"""
    
    @abstractmethod
    def synthesize(self, text: str, voice_id: str = "default", *,
                         format: str = "opus", sample_rate: int = 24000) -> AsyncIterator[bytes]:
        """将文本转为语音音频流（流式输出）
        
        注意：子类实现时使用 async def + yield（async generator）。
        抽象基类中不能使用 yield，因此声明为普通方法返回 AsyncIterator[bytes]。
        """
        ...
    
    @abstractmethod
    async def list_voices(self) -> list[dict]:
        """列出可用音色"""
        ...
    
    @abstractmethod
    async def is_available(self) -> bool:
        """检查服务可用性"""
        ...


class VolcengineTTSProvider(TTSProvider):
    """火山引擎 TTS WebSocket 流式合成实现（V1 主选）"""
    # ws_url = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"
    # 预置音色：灿灿、醇厚、爽快等

# 扩展：未来可新增其他厂商实现，只需继承 TTSProvider
```

## 4.4 ASR/TTS 配置

```jsonc
{
  "asr": {
    "provider": "volcengine",           // V1 主选；抽象层支持扩展
    "volcengine": { "appId": "xxx", "token": "xxx", "cluster": "volcengine_streaming_common", "language": "zh-CN" }
  },
  "tts": {
    "provider": "volcengine",           // V1 主选；抽象层支持扩展
    "volcengine": { "appId": "xxx", "token": "xxx", "cluster": "volcano_tts", "defaultVoice": "zh_female_cancan_mars_bigtts" }
  }
}
```
