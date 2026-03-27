# V1 §4 ASR/TTS WebSocket 客户端

> 摘自 `V1_DESIGN.md` §4，实现 `nanobot/providers/asr.py` 和 `nanobot/providers/tts.py` 时参考。

## 4.1 概述

后端内部通过 WebSocket 客户端连接火山引擎的 ASR（语音识别）和 TTS（语音合成）流式 API。这一层对上层 Channel 透明，Channel 只需调用 `asr_client.recognize()` 和 `tts_client.synthesize()`。

## 4.2 ASR 客户端（火山引擎语音识别）

```python
# nanobot/providers/asr.py

class ASRProvider(ABC):
    """ASR 语音识别提供者抽象基类"""
    
    @abstractmethod
    async def recognize(self, audio_data: bytes, *, format: str = "opus",
                        sample_rate: int = 16000, language: str = "zh-CN") -> str | None:
        """将音频转为文本"""
        ...
    
    @abstractmethod
    async def recognize_stream(self, audio_stream: AsyncIterator[bytes], *,
                               format: str = "opus", sample_rate: int = 16000) -> AsyncIterator[str]:
        """流式识别：边发送音频边获取中间结果"""
        ...


class VolcengineASRProvider(ASRProvider):
    """火山引擎 ASR WebSocket 流式识别实现"""
    
    def __init__(self, app_id: str, token: str, cluster: str = "volcengine_streaming_common"):
        self.ws_url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    
    # recognize(): WebSocket 发送完整音频，获取识别结果
    # recognize_stream(): 并行发送音频 + 接收结果
```

## 4.3 TTS 客户端（火山引擎语音合成 / CosyVoice2）

```python
# nanobot/providers/tts.py

class TTSProvider(ABC):
    """TTS 语音合成提供者抽象基类"""
    
    @abstractmethod
    async def synthesize(self, text: str, voice_id: str = "default", *,
                         format: str = "opus", sample_rate: int = 24000) -> AsyncIterator[bytes]:
        """将文本转为语音音频流（流式输出）"""
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
    """火山引擎 TTS WebSocket 流式合成实现"""
    # ws_url = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"
    # 预置音色：灿灿、醇厚、爽快等


class CosyVoiceTTSProvider(TTSProvider):
    """阿里 CosyVoice2 API 实现（备选）"""
    # api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # 预置音色：龙小淳、龙华、龙朔、龙婧
```

## 4.4 ASR/TTS 配置

```jsonc
{
  "asr": {
    "provider": "volcengine",           // "volcengine" | "groq_whisper"
    "volcengine": { "appId": "xxx", "token": "xxx", "cluster": "volcengine_streaming_common", "language": "zh-CN" },
    "groq_whisper": { "apiKey": "sk-xxx" }
  },
  "tts": {
    "provider": "volcengine",           // "volcengine" | "cosyvoice" | "minimax"
    "volcengine": { "appId": "xxx", "token": "xxx", "cluster": "volcano_tts", "defaultVoice": "zh_female_cancan_mars_bigtts" },
    "cosyvoice": { "apiKey": "sk-xxx", "model": "cosyvoice-v2", "defaultVoice": "longxiaochun" },
    "minimax": { "apiKey": "xxx", "groupId": "xxx", "defaultVoice": "male-qn-qingse" }
  }
}
```
