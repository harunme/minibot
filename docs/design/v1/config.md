# V1 §8 配置设计

> 摘自 `V1_DESIGN.md` §8，扩展 `nanobot/config/schema.py` 时参考。
> **注意**：V1 已使用 WebSocket Channel 替代原 MQTT Channel。

## 8.1 config.json 扩展

```jsonc
{
  // ... 现有 nanobot 配置 ...
  
  "channels": {
    "websocket_hw": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 9000,
      "authKey": "",
      "maxConnections": 100,
      "timeoutSeconds": 120,
      "audioFormat": "opus",
      "allowFrom": ["*"]
    }
  },
  
  "asr": { /* 见 asr-tts.md §4.4 */ },
  "tts": { /* 见 asr-tts.md §4.4 */ }
}
```

## 8.2 Pydantic Schema 扩展

在 `nanobot/config/schema.py` 中新增：

```python
class WebSocketChannelConfig(Base):
    """WebSocket 语音通道配置 — 面向 Tauri/Web 客户端"""
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 9000
    auth_key: str = ""
    max_connections: int = 100
    timeout_seconds: int = 120
    audio_format: str = "opus"
    allow_from: list[str] = ["*"]  # 设备白名单; "*" 允许所有; 生产环境改为具体设备 ID

class ASRConfig(Base):
    provider: str = "volcengine"
    volcengine: VolcengineASRConfig = Field(default_factory=VolcengineASRConfig)

class TTSConfig(Base):
    provider: str = "volcengine"
    volcengine: VolcengineTTSConfig = Field(default_factory=VolcengineTTSConfig)
```
