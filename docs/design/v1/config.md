# V1 §8 配置设计

> 摘自 `V1_DESIGN.md` §8，扩展 `nanobot/config/schema.py` 时参考。

## 8.1 config.json 扩展

```jsonc
{
  // ... 现有 nanobot 配置 ...
  
  "channels": {
    "hardware": {
      "enabled": true,
      "mqtt_host": "localhost",
      "mqtt_port": 1883,
      "mqtt_username": "minibot",
      "mqtt_password": "xxx",
      "mqtt_tls": false,
      "audio_format": "opus",
      "max_devices": 100
    }
  },
  
  "asr": { /* 见 asr-tts.md §4.4 */ },
  "tts": { /* 见 asr-tts.md §4.4 */ },
  
  "tenant": {
    "dataDir": "~/.minibot/data",
    "maxFamilies": 1000,
    "maxDevicesPerFamily": 10
  },
  
  "admin": {
    "enabled": true,
    "port": 8080,
    "jwtSecret": "change-me-in-production",
    "jwtExpireHours": 24
  }
}
```

## 8.2 Pydantic Schema 扩展

在 `nanobot/config/schema.py` 中新增：

```python
class HardwareChannelConfig(Base):
    enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_tls: bool = False
    audio_format: str = "opus"
    max_devices: int = 100

class ASRConfig(Base):
    provider: str = "volcengine"
    volcengine: VolcengineASRConfig = Field(default_factory=VolcengineASRConfig)
    # 抽象层预留扩展，未来可追加阿里等厂商配置

class TTSConfig(Base):
    provider: str = "volcengine"
    volcengine: VolcengineTTSConfig = Field(default_factory=VolcengineTTSConfig)
    # 抽象层预留扩展，未来可追加其他厂商配置

class TenantConfig(Base):
    data_dir: str = "~/.minibot/data"
    max_families: int = 1000
    max_devices_per_family: int = 10

class AdminConfig(Base):
    enabled: bool = False
    port: int = 8080
    jwt_secret: str = "change-me"
    jwt_expire_hours: int = 24
```
