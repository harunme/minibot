# V1 §3 硬件 MQTT Channel

> 摘自 `V1_DESIGN.md` §3，实现 `nanobot/channels/hardware.py` 时参考。

## 3.1 概述

作为 nanobot Channel 插件实现，文件位置 `nanobot/channels/hardware.py`，继承 `BaseChannel`。内部集成 MQTT 客户端负责设备通信，以及 WebSocket 客户端负责对接火山引擎 ASR/TTS。

## 3.2 MQTT Broker

### 选型建议

| Broker | 特点 | 推荐场景 |
|--------|------|----------|
| **EMQX** | 功能强大，支持百万连接，规则引擎、认证插件丰富 | 生产环境、规模化部署 |
| **Mosquitto** | 轻量，资源占用低，配置简单 | 开发环境、单机小规模 |

V1 推荐 **Mosquitto** 快速启动开发，后续可无缝切换到 EMQX。

### MQTT 连接参数

```
Broker: mqtt://{host}:1883 (TCP) 或 mqtts://{host}:8883 (TLS)
Client ID: device_{device_id}
Username: {device_id}
Password: {auth_token}
Clean Session: false (保持持久会话，断线重连后恢复订阅)
Keep Alive: 60s
LWT Topic: device/{device_id}/status
LWT Payload: {"status": "offline", "timestamp": "..."}
LWT QoS: 1
```

## 3.3 MQTT Topic 设计

```
device/{device_id}/
├── audio/
│   ├── up            # 上行音频帧 (设备 → 后端) [QoS 0]
│   └── down          # 下行音频帧 (后端 → 设备) [QoS 0]
├── ctrl/
│   ├── up            # 上行控制消息 (设备 → 后端) [QoS 1]
│   └── down          # 下行控制指令 (后端 → 设备) [QoS 1]
├── status            # 设备状态上报 [QoS 1]
└── ota/              # OTA 升级通道 (V4) [QoS 1]
    ├── notify        # 后端通知有新版本
    └── progress      # 设备上报升级进度
```

### QoS 策略

| Topic 类型 | QoS | 理由 |
|-----------|-----|------|
| audio/up, audio/down | **QoS 0** | 音频流追求低延迟，丢帧可接受 |
| ctrl/up, ctrl/down | **QoS 1** | 控制指令必须送达 |
| status | **QoS 1** | 状态信息需要可靠传输 |

## 3.4 MQTT 消息帧格式

### 控制消息（JSON，通过 ctrl Topic）

```jsonc
// 设备 → 后端：开始录音 (ctrl/up)
{ "type": "audio_start", "format": "opus", "sample_rate": 16000, "channels": 1, "ts": 1711526400000 }

// 设备 → 后端：结束录音 (ctrl/up)
{ "type": "audio_end", "ts": 1711526402000 }

// 后端 → 设备：开始回复语音 (ctrl/down)
{ "type": "reply_start", "format": "opus", "sample_rate": 24000, "channels": 1 }

// 后端 → 设备：回复语音结束 (ctrl/down)
{ "type": "reply_end" }

// 后端 → 设备：文本回复 (ctrl/down)
{ "type": "text", "content": "好的，我给你讲个小熊的故事..." }

// 后端 → 设备：错误 (ctrl/down)
{ "type": "error", "code": "auth_failed", "message": "设备未绑定" }

// 设备 → 后端：播放控制 (ctrl/up)
{ "type": "playback_control", "action": "pause" }
```

### 设备状态上报（JSON，通过 status Topic）

```jsonc
{ "status": "online", "battery": 85, "signal": -65, "wifi_rssi": -45, "firmware": "1.0.0", "uptime": 3600, "ts": 1711526400000 }
```

### 音频帧（二进制，通过 audio Topic）

```
Header (4 bytes) + Audio Data (variable):
- byte[0]: 帧类型标识 (0x01=上行, 0x02=下行)
- byte[1-2]: 序列号 (uint16, big-endian)
- byte[3]: 标志位 (bit0=最后一帧)
```

## 3.5 语音处理流程

```python
# 伪代码 — 硬件 MQTT Channel 核心流程

class HardwareChannel(BaseChannel):
    name = "hardware"
    
    async def start(self):
        """启动 MQTT 客户端，订阅所有设备 Topic
        
        注意：aiomqtt 通过 async with (context manager) 管理连接生命周期，
        不支持直接调用 disconnect()。使用 _running 标志控制退出。
        """
        self._running = True
        self._stop_event = asyncio.Event()
        
        async with aiomqtt.Client(
            hostname=self._mqtt_host,
            port=self._mqtt_port,
            username=self._mqtt_username,
            password=self._mqtt_password,
        ) as client:
            self._mqtt_client = client
            await client.subscribe("device/+/audio/up", qos=0)
            await client.subscribe("device/+/ctrl/up", qos=1)
            await client.subscribe("device/+/status", qos=1)
            
            async for message in client.messages:
                if not self._running:
                    break
                await self._dispatch_message(message)
    
    async def stop(self):
        """停止 MQTT Channel — 设置标志使消息循环退出，context manager 自动断开连接"""
        self._running = False
        self._stop_event.set()
    
    async def _dispatch_message(self, message):
        """分发 MQTT 消息"""
        topic_parts = str(message.topic).split("/")
        device_id = topic_parts[1]
        category = topic_parts[2]
        
        # 使用 BaseChannel.is_allowed() 进行设备白名单验证
        if not self.is_allowed(device_id):
            await self._publish_error(device_id, "auth_failed", "设备未授权")
            return
        
        if category == "ctrl":
            await self._handle_ctrl(device_id, json.loads(message.payload))
        elif category == "audio":
            await self._handle_audio(device_id, bytes(message.payload))
        elif category == "status":
            await self._handle_status(device_id, json.loads(message.payload))
    
    async def send(self, msg: OutboundMessage):
        """Agent 回复 → TTS → MQTT 音频下行"""
        # 1. 先发文本（可选）
        # 2. TTS 流式合成 + MQTT 音频下发
        # 3. 发送 reply_end 标志
```

## 3.6 连接管理

| 机制 | 说明 |
|------|------|
| 心跳 | MQTT Keep Alive = 60s，由协议层自动处理 |
| 断线重连 | MQTT 客户端库原生支持，persistent session 恢复订阅 |
| 遗嘱消息 | 设备异常断线 → Broker 自动发布 LWT 到 status Topic |
| 设备认证 | MQTT Broker 层 username/password 认证 + Channel 层 device_id 验证 |
| 并发管理 | 每设备一个 Client ID，Broker 自动踢掉旧连接 |

### 认证分层策略

| 环境 | 认证方式 | 说明 |
|------|----------|------|
| **开发环境** | Mosquitto `password_file` | 简单易配，快速启动开发。使用 `mosquitto_passwd` 工具管理账号密码 |
| **生产环境** | EMQX JWT Token 认证 | 统一 JWT 签发，支持设备级别精细权限控制。ROADMAP.md 中提到的"JWT 认证"指此场景 |

> **说明**：V1 开发阶段使用 Mosquitto + password_file 即可满足需求。生产部署时切换到 EMQX 并启用 JWT 认证插件，Channel 代码无需修改（仅 MQTT 连接参数变化）。
