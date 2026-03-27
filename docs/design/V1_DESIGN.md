# MiniBot 语音伴侣 — V1.0 详细设计文档

> **版本**：V1.0 — 核心对话链路（MVP）  
> **状态**：设计阶段  
> **最后更新**：2026-03-27

---

## 目录

1. [概述](#1-概述)
2. [系统架构](#2-系统架构)
3. [硬件 MQTT Channel](#3-硬件-mqtt-channel)
4. [ASR/TTS WebSocket 客户端](#4-asrtts-websocket-客户端)
5. [多租户模块](#5-多租户模块)
6. [管理后台](#6-管理后台)
7. [Kids-Chat Skill](#7-kids-chat-skill)
8. [配置设计](#8-配置设计)
9. [目录结构](#9-目录结构)
10. [部署方案](#10-部署方案)
11. [测试计划](#11-测试计划)
12. [开放问题](#12-开放问题)

---

## 1. 概述

### 1.1 目标

打通 **"语音输入 → STT → Agent → TTS → 语音输出"** 完整链路，实现一个可工作的最小可用产品。

### 1.2 核心用户故事

```
作为小朋友，我对着设备说"给我讲个故事"，设备用温柔的声音给我讲故事。
作为家长，我在后台注册账号，绑定设备，让孩子可以开始使用。
```

### 1.3 V1 范围

**包含**：
- 硬件 MQTT 双向语音通道（设备接入层）
- 后端 WebSocket 客户端（对接火山引擎 ASR/TTS 流式 API）
- TTS 语音合成（火山引擎 TTS WebSocket 流式）
- STT 语音识别（火山引擎 ASR WebSocket 流式）
- MQTT Broker 部署（EMQX / Mosquitto）
- 基础多租户（SQLite 多数据库）
- 管理后台 MVP（注册/登录/设备绑定）
- 测试客户端（模拟硬件）

**不包含**：
- RAG 知识库（V2）
- 音色克隆（V3）
- 硬件固件（V4）
- 移动端 App

---

## 2. 系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           客户端层                                           │
├──────────────┬──────────────────┬────────────────────────────────────────────┤
│  ESP32 硬件   │  测试客户端        │  管理后台 (React)                          │
│  (MQTT)      │  (MQTT)           │  (HTTP)                                   │
└──────┬───────┴────────┬──────────┴──────────┬────────────────────────────────┘
       │                │                     │
       │  MQTT          │  MQTT               │  HTTP
       ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MQTT Broker (EMQX / Mosquitto)                       │
│  Topic: device/{id}/audio/up, device/{id}/audio/down, device/{id}/ctrl ...   │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MiniBot 服务端                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │              硬件 MQTT Channel                                         │  │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐              │  │
│  │  │ MQTT 订阅     │   │ 设备认证      │   │ MQTT 发布     │              │  │
│  │  │ (音频/状态上行)│   │ (Token 验证) │   │ (音频/指令下行)│              │  │
│  │  └──────┬───────┘   └──────────────┘   └──────▲───────┘              │  │
│  │         │                                      │                      │  │
│  │         ▼                                      │                      │  │
│  │  ┌──────────────┐                       ┌──────────────┐              │  │
│  │  │ ASR 客户端    │                       │ TTS 客户端    │              │  │
│  │  │ (WebSocket)  │                       │ (WebSocket)  │              │  │
│  │  └──────┬───────┘                       └──────▲───────┘              │  │
│  └─────────┼──────────────────────────────────────┼──────────────────────┘  │
│            │                                      │                         │
│            │  WebSocket                           │  WebSocket              │
│            ▼                                      │                         │
│  ┌─────────────────────────────┐   ┌──────────────┴────────────────────┐    │
│  │ 火山引擎 ASR (Streaming)    │   │ 火山引擎 TTS (Streaming)          │    │
│  │ 音频流 → 文本               │   │ 文本 → 音频流                     │    │
│  └─────────────────────────────┘   └───────────────────────────────────┘    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                   nanobot 核心 (复用)                                    │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐              │  │
│  │  │消息总线   │  │Agent Loop│  │Context   │  │记忆系统   │              │  │
│  │  │(Bus)     │  │(Loop)    │  │Builder   │  │(Memory)  │              │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘              │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────┐  ┌──────────────────────────────────┐            │
│  │    多租户层             │  │    管理后台 API (FastAPI)        │            │
│  │  ┌────────┐ ┌────────┐│  │  ┌──────┐ ┌──────┐ ┌──────────┐│            │
│  │  │租户路由 │ │SQLite  ││  │  │认证   │ │设备   │ │内容(V2) ││            │
│  │  │        │ │多数据库 ││  │  │(JWT) │ │管理   │ │管理     ││            │
│  │  └────────┘ └────────┘│  │  └──────┘ └──────┘ └──────────┘│            │
│  └───────────────────────┘  └──────────────────────────────────┘            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
完整语音对话流程（双协议）：

上行链路（语音输入）：
1. ESP32 硬件 →[MQTT: device/{id}/audio/up]→ MQTT Broker
2. 硬件 MQTT Channel: 订阅 topic，接收音频分片，组装完整音频帧
3. 硬件 MQTT Channel →[WebSocket]→ 火山引擎 ASR：流式发送音频，实时接收识别文本
4. 识别完成：文本 → InboundMessage → nanobot 消息总线

处理链路（Agent 思考）：
5. Agent Loop: 消息总线 → Context Builder → LLM → 文本回复

下行链路（语音输出）：
6. 硬件 MQTT Channel: OutboundMessage → 文本
7. 硬件 MQTT Channel →[WebSocket]→ 火山引擎 TTS：流式发送文本，实时接收合成音频
8. 硬件 MQTT Channel →[MQTT: device/{id}/audio/down]→ MQTT Broker → ESP32 播放

设备管控：
- 设备状态上报：ESP32 →[MQTT: device/{id}/status]→ 后端（在线/离线/电量/信号）
- 控制指令下发：后端 →[MQTT: device/{id}/ctrl]→ ESP32（音量/唤醒词/OTA）
- 遗嘱消息：设备异常断线 → MQTT Broker 自动发布 LWT → 后端感知设备离线
```

### 2.3 双协议分工

| 层面 | 协议 | 职责 | 优势 |
|------|------|------|------|
| 设备 ↔ 后端 | **MQTT** | 音频分片传输、设备状态上报、控制指令下发 | 轻量（2字节头）、低功耗、弱网 QoS 保证、断线自动重连、Topic 路由 |
| 后端 ↔ 火山引擎 | **WebSocket** | ASR 音频流实时识别、TTS 文本流实时合成 | 全双工流式、高实时性、与火山引擎 API 天然匹配 |

### 2.4 与 nanobot 的集成方式

| 扩展点 | 方式 | 说明 |
|--------|------|------|
| 硬件 Channel | `BaseChannel` 子类 | 注册到 `channels/registry.py`，通过 `config.json` 启用 |
| MQTT 客户端 | `asyncio-mqtt` / `paho-mqtt` | Channel 内部实现，订阅/发布设备 Topic |
| ASR WebSocket | `websockets` 客户端 | Channel 内部实现，流式调用火山引擎 ASR |
| TTS | 独立 Provider 模块 + WebSocket | 新增 `providers/tts.py`，内部通过 WebSocket 调用火山引擎 TTS |
| 多租户 | 独立模块 | 新增 `tenant/` 包，Channel 和 Admin 调用 |
| 管理后台 | 独立 FastAPI 服务 | 与 nanobot gateway 并行运行 |
| Kids Skill | SKILL.md 文件 | 放入 workspace/skills/ 目录 |

---

## 3. 硬件 MQTT Channel

### 3.1 概述

作为 nanobot Channel 插件实现，文件位置 `nanobot/channels/hardware.py`，继承 `BaseChannel`。内部集成 MQTT 客户端负责设备通信，以及 WebSocket 客户端负责对接火山引擎 ASR/TTS。

### 3.2 MQTT Broker

#### 选型建议

| Broker | 特点 | 推荐场景 |
|--------|------|----------|
| **EMQX** | 功能强大，支持百万连接，规则引擎、认证插件丰富 | 生产环境、规模化部署 |
| **Mosquitto** | 轻量，资源占用低，配置简单 | 开发环境、单机小规模 |

V1 推荐 **Mosquitto** 快速启动开发，后续可无缝切换到 EMQX。

#### MQTT 连接参数

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

### 3.3 MQTT Topic 设计

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

#### QoS 策略

| Topic 类型 | QoS | 理由 |
|-----------|-----|------|
| audio/up, audio/down | **QoS 0** | 音频流追求低延迟，丢帧可接受（人耳对轻微丢帧不敏感） |
| ctrl/up, ctrl/down | **QoS 1** | 控制指令必须送达（音量调节、播放控制等） |
| status | **QoS 1** | 状态信息需要可靠传输 |

### 3.4 MQTT 消息帧格式

#### 控制消息（JSON，通过 ctrl Topic）

```jsonc
// 设备 → 后端：开始录音
// Topic: device/{device_id}/ctrl/up
{
  "type": "audio_start",
  "format": "opus",         // "opus" | "pcm"
  "sample_rate": 16000,
  "channels": 1,
  "ts": 1711526400000       // 毫秒时间戳
}

// 设备 → 后端：结束录音
// Topic: device/{device_id}/ctrl/up
{
  "type": "audio_end",
  "ts": 1711526402000
}

// 后端 → 设备：开始回复语音
// Topic: device/{device_id}/ctrl/down
{
  "type": "reply_start",
  "format": "opus",
  "sample_rate": 24000,
  "channels": 1
}

// 后端 → 设备：回复语音结束
// Topic: device/{device_id}/ctrl/down
{
  "type": "reply_end"
}

// 后端 → 设备：文本回复（可选，用于屏幕显示）
// Topic: device/{device_id}/ctrl/down
{
  "type": "text",
  "content": "好的，我给你讲个小熊的故事..."
}

// 后端 → 设备：错误
// Topic: device/{device_id}/ctrl/down
{
  "type": "error",
  "code": "auth_failed",     // "auth_failed" | "asr_error" | "tts_error" | "server_error"
  "message": "设备未绑定"
}

// 设备 → 后端：播放控制
// Topic: device/{device_id}/ctrl/up
{
  "type": "playback_control",
  "action": "pause"          // "pause" | "resume" | "stop" | "next"
}
```

#### 设备状态上报（JSON，通过 status Topic）

```jsonc
// Topic: device/{device_id}/status
{
  "status": "online",       // "online" | "offline" | "charging" | "low_battery"
  "battery": 85,            // 电池百分比
  "signal": -65,            // 信号强度 dBm（SIM 卡）
  "wifi_rssi": -45,         // WiFi 信号强度
  "firmware": "1.0.0",      // 固件版本
  "uptime": 3600,           // 运行时长（秒）
  "ts": 1711526400000
}
```

#### 音频帧（二进制，通过 audio Topic）

```
上行音频帧（设备 → 后端）：
Topic: device/{device_id}/audio/up
Payload (binary):
┌──────────┬──────────────────┐
│ Header   │ Audio Data       │
│ (4 bytes)│ (variable)       │
├──────────┼──────────────────┤
│ 0x01     │ Opus/PCM payload │
│ seq (2B) │                  │
│ flags(1B)│                  │
└──────────┴──────────────────┘

下行音频帧（后端 → 设备）：
Topic: device/{device_id}/audio/down
Payload (binary):
┌──────────┬──────────────────┐
│ Header   │ Audio Data       │
│ (4 bytes)│ (variable)       │
├──────────┼──────────────────┤
│ 0x02     │ Opus/PCM payload │
│ seq (2B) │                  │
│ flags(1B)│                  │
└──────────┴──────────────────┘

Header 字段说明：
- byte[0]: 帧类型标识 (0x01=上行, 0x02=下行)
- byte[1-2]: 序列号 (uint16, big-endian)
- byte[3]: 标志位 (bit0=最后一帧)
```

### 3.5 语音处理流程

```python
# 伪代码 — 硬件 MQTT Channel 核心流程

class HardwareChannel(BaseChannel):
    name = "hardware"
    
    async def start(self):
        """启动 MQTT 客户端，订阅所有设备 Topic"""
        self.mqtt_client = aiomqtt.Client(
            hostname=self._mqtt_host,
            port=self._mqtt_port,
            username=self._mqtt_username,
            password=self._mqtt_password,
        )
        async with self.mqtt_client:
            # 订阅所有设备的上行 Topic
            await self.mqtt_client.subscribe("device/+/audio/up", qos=0)
            await self.mqtt_client.subscribe("device/+/ctrl/up", qos=1)
            await self.mqtt_client.subscribe("device/+/status", qos=1)
            
            async for message in self.mqtt_client.messages:
                await self._dispatch_message(message)
    
    async def _dispatch_message(self, message):
        """分发 MQTT 消息"""
        topic_parts = str(message.topic).split("/")
        # topic_parts: ["device", "{device_id}", "audio|ctrl|status", "up|down"]
        device_id = topic_parts[1]
        category = topic_parts[2]
        
        # 验证设备
        tenant = self.tenant_manager.get_by_device(device_id)
        if not tenant:
            await self._publish_error(device_id, "auth_failed", "设备未绑定")
            return
        
        if category == "ctrl":
            await self._handle_ctrl(device_id, json.loads(message.payload))
        elif category == "audio":
            await self._handle_audio(device_id, bytes(message.payload))
        elif category == "status":
            await self._handle_status(device_id, json.loads(message.payload))
    
    async def _handle_ctrl(self, device_id: str, frame: dict):
        """处理控制消息"""
        if frame["type"] == "audio_start":
            self._audio_buffers[device_id] = bytearray()
            
        elif frame["type"] == "audio_end":
            # 音频收集完毕，送入 ASR
            audio_data = self._audio_buffers.pop(device_id, None)
            if audio_data:
                text = await self.asr_client.recognize(audio_data)
                if text:
                    await self._handle_message(
                        sender_id=device_id,
                        chat_id=device_id,
                        content=text,
                    )
    
    async def _handle_audio(self, device_id: str, payload: bytes):
        """接收音频帧，追加到缓冲区"""
        if device_id in self._audio_buffers:
            self._audio_buffers[device_id].extend(payload[4:])  # 跳过 4 字节头
    
    async def send(self, msg: OutboundMessage):
        """Agent 回复 → TTS → MQTT 音频下行"""
        device_id = msg.chat_id
        
        # 1. 先发文本（可选）
        await self.mqtt_client.publish(
            f"device/{device_id}/ctrl/down",
            json.dumps({"type": "text", "content": msg.content}),
            qos=1,
        )
        
        # 2. TTS 流式合成 + MQTT 音频下发
        await self.mqtt_client.publish(
            f"device/{device_id}/ctrl/down",
            json.dumps({"type": "reply_start", "format": "opus", "sample_rate": 24000}),
            qos=1,
        )
        
        seq = 0
        async for audio_chunk in self.tts_client.synthesize(msg.content, voice_id):
            header = struct.pack(">BHB", 0x02, seq, 0x00)
            await self.mqtt_client.publish(
                f"device/{device_id}/audio/down",
                header + audio_chunk,
                qos=0,
            )
            seq += 1
        
        # 发送最后一帧标志
        await self.mqtt_client.publish(
            f"device/{device_id}/ctrl/down",
            json.dumps({"type": "reply_end"}),
            qos=1,
        )
```

### 3.6 连接管理

| 机制 | 说明 |
|------|------|
| 心跳 | MQTT Keep Alive = 60s，由协议层自动处理 |
| 断线重连 | MQTT 客户端库原生支持，persistent session 恢复订阅 |
| 遗嘱消息 | 设备异常断线 → Broker 自动发布 LWT 到 status Topic |
| 设备认证 | MQTT Broker 层 username/password 认证 + Channel 层 device_id 验证 |
| 并发管理 | 每设备一个 Client ID，Broker 自动踢掉旧连接 |

### 3.7 nanobot 集成

```python
# nanobot/channels/hardware.py

class HardwareChannel(BaseChannel):
    name = "hardware"
    display_name = "Hardware (MQTT)"
    
    def __init__(self, config: dict, bus: MessageBus):
        super().__init__(config, bus)
        self._mqtt_host = config.get("mqtt_host", "localhost")
        self._mqtt_port = config.get("mqtt_port", 1883)
        self._mqtt_username = config.get("mqtt_username", "")
        self._mqtt_password = config.get("mqtt_password", "")
        self._audio_buffers: dict[str, bytearray] = {}
        self._asr_client = None   # 火山引擎 ASR WebSocket 客户端
        self._tts_client = None   # 火山引擎 TTS WebSocket 客户端
        self._tenant_manager = None
    
    async def start(self) -> None:
        """启动 MQTT 客户端，订阅设备 Topic"""
        # ... 见上方伪代码
    
    async def stop(self) -> None:
        """断开 MQTT 连接"""
        if self.mqtt_client:
            await self.mqtt_client.disconnect()
    
    async def send(self, msg: OutboundMessage) -> None:
        """Agent 回复 → TTS → MQTT 音频推送"""
        # ... 见上方伪代码
    
    @classmethod
    def default_config(cls) -> dict:
        return {
            "enabled": False,
            "mqtt_host": "localhost",
            "mqtt_port": 1883,
            "mqtt_username": "",
            "mqtt_password": "",
            "audio_format": "opus",
        }
```

---

## 4. ASR/TTS WebSocket 客户端

### 4.1 概述

后端内部通过 WebSocket 客户端连接火山引擎的 ASR（语音识别）和 TTS（语音合成）流式 API。这一层对上层 Channel 透明，Channel 只需调用 `asr_client.recognize()` 和 `tts_client.synthesize()`。

### 4.2 ASR 客户端（火山引擎语音识别）

```python
# nanobot/providers/asr.py

from abc import ABC, abstractmethod
from typing import AsyncIterator

class ASRProvider(ABC):
    """ASR 语音识别提供者抽象基类"""
    
    @abstractmethod
    async def recognize(
        self,
        audio_data: bytes,
        *,
        format: str = "opus",
        sample_rate: int = 16000,
        language: str = "zh-CN",
    ) -> str | None:
        """将音频转为文本
        
        Args:
            audio_data: 完整音频数据
            format: 音频格式
            sample_rate: 采样率
            language: 语言
            
        Returns:
            识别到的文本，或 None（识别失败）
        """
        ...
    
    @abstractmethod
    async def recognize_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        *,
        format: str = "opus",
        sample_rate: int = 16000,
    ) -> AsyncIterator[str]:
        """流式识别：边发送音频边获取中间结果
        
        Args:
            audio_stream: 音频数据流
            
        Yields:
            str: 中间识别结果和最终结果
        """
        ...


class VolcengineASRProvider(ASRProvider):
    """火山引擎 ASR WebSocket 流式识别实现"""
    
    def __init__(self, app_id: str, token: str, cluster: str = "volcengine_streaming_common"):
        self.app_id = app_id
        self.token = token
        self.cluster = cluster
        self.ws_url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    
    async def recognize(self, audio_data: bytes, **kwargs) -> str | None:
        """通过 WebSocket 发送完整音频，获取识别结果
        
        流程：
        1. 建立 WebSocket 连接
        2. 发送 full_client_request（包含音频配置）
        3. 分片发送音频数据
        4. 接收并返回最终识别结果
        """
        import websockets
        
        async with websockets.connect(self.ws_url) as ws:
            # 发送初始请求（配置）
            await ws.send(self._build_request(audio_data, **kwargs))
            
            # 接收结果
            result_text = ""
            async for message in ws:
                resp = json.loads(message)
                if resp.get("is_final"):
                    result_text = resp.get("text", "")
                    break
            
            return result_text or None
    
    async def recognize_stream(self, audio_stream, **kwargs):
        """流式识别：实时发送音频帧，实时获取中间结果"""
        import websockets
        
        async with websockets.connect(self.ws_url) as ws:
            # 并行：发送音频 + 接收结果
            async def sender():
                async for chunk in audio_stream:
                    await ws.send(chunk)
                await ws.send(b"")  # 发送结束标志
            
            async def receiver():
                async for message in ws:
                    resp = json.loads(message)
                    text = resp.get("text", "")
                    if text:
                        yield text
                    if resp.get("is_final"):
                        break
            
            # 启动发送协程
            sender_task = asyncio.create_task(sender())
            async for text in receiver():
                yield text
            await sender_task


# 扩展说明：
# ASRProvider 抽象层支持多提供商扩展。V1 实现火山引擎，未来可新增：
#   class AliyunASRProvider(ASRProvider):  # 阿里云 ASR
#   class XXXASRProvider(ASRProvider):     # 其他厂商
# 新增 Provider 只需继承 ASRProvider 并实现抽象方法，配置中切换 provider 即可。
```

### 4.3 TTS 客户端（火山引擎语音合成）

```python
# nanobot/providers/tts.py

from abc import ABC, abstractmethod
from typing import AsyncIterator

class TTSProvider(ABC):
    """TTS 语音合成提供者抽象基类"""
    
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str = "default",
        *,
        format: str = "opus",        # "opus" | "pcm" | "mp3"
        sample_rate: int = 24000,
    ) -> AsyncIterator[bytes]:
        """将文本转为语音音频流（流式输出）
        
        Args:
            text: 待合成文本
            voice_id: 音色标识
            format: 输出音频格式
            sample_rate: 采样率
            
        Yields:
            bytes: 音频数据块
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
    """火山引擎 TTS WebSocket 流式合成实现"""
    
    def __init__(self, app_id: str, token: str, cluster: str = "volcano_tts"):
        self.app_id = app_id
        self.token = token
        self.cluster = cluster
        self.ws_url = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"
    
    async def synthesize(self, text, voice_id="zh_female_cancan_mars_bigtts", **kwargs):
        """通过 WebSocket 流式合成语音
        
        流程：
        1. 建立 WebSocket 连接
        2. 发送合成请求（文本 + 音色 + 格式）
        3. 流式接收音频数据块
        """
        import websockets
        
        async with websockets.connect(self.ws_url) as ws:
            await ws.send(self._build_request(text, voice_id, **kwargs))
            
            async for message in ws:
                if isinstance(message, bytes):
                    # 解析火山引擎协议，提取音频数据
                    audio_chunk = self._parse_audio_response(message)
                    if audio_chunk:
                        yield audio_chunk
                else:
                    resp = json.loads(message)
                    if resp.get("is_end"):
                        break
    
    async def list_voices(self):
        return [
            {"id": "zh_female_cancan_mars_bigtts", "name": "灿灿", "language": "zh-CN", "gender": "female"},
            {"id": "zh_male_chunhou_mars_bigtts", "name": "醇厚", "language": "zh-CN", "gender": "male"},
            {"id": "zh_female_shuangkuai_mars_bigtts", "name": "爽快", "language": "zh-CN", "gender": "female"},
            # ... 更多火山引擎预置音色
        ]
    
    async def is_available(self) -> bool:
        # 尝试建立 WebSocket 连接测试
        ...


# 扩展说明：
# TTSProvider 抽象层支持多提供商扩展。未来可新增其他厂商实现：
#   class AliyunTTSProvider(TTSProvider):  # 阿里云 TTS
#   class XXXTTSProvider(TTSProvider):     # 其他厂商
# 新增 Provider 只需继承 TTSProvider 并实现抽象方法，配置中切换 provider 即可。
```

### 4.4 ASR/TTS 配置

```jsonc
// config.json 中的 ASR 和 TTS 配置
{
  "asr": {
    "provider": "volcengine",           // V1 主选；抽象层支持扩展（未来可接阿里等）
    "volcengine": {
      "appId": "xxx",
      "token": "xxx",
      "cluster": "volcengine_streaming_common",
      "language": "zh-CN"
    }
  },
  "tts": {
    "provider": "volcengine",           // V1 主选；抽象层支持扩展
    "volcengine": {
      "appId": "xxx",
      "token": "xxx",
      "cluster": "volcano_tts",
      "defaultVoice": "zh_female_cancan_mars_bigtts"
    }
  }
}
```

---

## 5. 多租户模块

### 5.1 数据模型

#### 主库 (master.db)

全局共享，存储租户索引和设备映射。

```sql
-- 家庭（租户）表
CREATE TABLE families (
    id          TEXT PRIMARY KEY,      -- UUID
    name        TEXT NOT NULL,         -- 家庭名称
    created_at  TEXT NOT NULL,         -- ISO 8601
    updated_at  TEXT NOT NULL,
    status      TEXT DEFAULT 'active'  -- active | suspended
);

-- 设备表
CREATE TABLE devices (
    id          TEXT PRIMARY KEY,      -- 设备唯一ID（硬件烧录）
    family_id   TEXT NOT NULL,         -- 所属家庭
    name        TEXT,                  -- 设备昵称
    auth_token  TEXT NOT NULL,         -- 设备认证 token
    status      TEXT DEFAULT 'active', -- active | disabled
    last_seen   TEXT,                  -- 最后在线时间
    created_at  TEXT NOT NULL,
    FOREIGN KEY (family_id) REFERENCES families(id)
);

-- 设备ID → 家庭ID 快速查询索引
CREATE INDEX idx_devices_family ON devices(family_id);
```

#### 租户库 ({family_id}.db)

每个家庭独立数据库文件。

```sql
-- 家庭成员表
CREATE TABLE members (
    id          TEXT PRIMARY KEY,      -- UUID
    name        TEXT NOT NULL,         -- 成员名称
    role        TEXT NOT NULL,         -- parent | child
    phone       TEXT,                  -- 手机号（家长）
    password    TEXT,                  -- 密码哈希（家长登录用）
    avatar      TEXT,                  -- 头像路径
    created_at  TEXT NOT NULL
);

-- 内容元数据表
CREATE TABLE contents (
    id          TEXT PRIMARY KEY,      -- UUID
    type        TEXT NOT NULL,         -- story | music | document
    title       TEXT NOT NULL,
    file_path   TEXT NOT NULL,         -- 相对于租户存储目录的路径
    file_size   INTEGER,
    mime_type   TEXT,
    duration    INTEGER,              -- 音频时长（秒）
    metadata    TEXT,                  -- JSON 扩展字段
    uploaded_by TEXT,                  -- 上传者 member_id
    created_at  TEXT NOT NULL
);

-- 设备配置表
CREATE TABLE device_configs (
    device_id   TEXT PRIMARY KEY,
    voice_id    TEXT DEFAULT 'zh_female_cancan_mars_bigtts',  -- 默认音色（火山引擎）
    volume      INTEGER DEFAULT 70,           -- 音量 0-100
    wake_word   TEXT DEFAULT '你好小伙伴',     -- 唤醒词
    config      TEXT,                          -- JSON 扩展配置
    updated_at  TEXT NOT NULL
);
```

### 5.2 租户路由

```python
class TenantManager:
    """多租户管理器"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.master_db = data_dir / "master.db"
        self._tenant_dbs: dict[str, sqlite3.Connection] = {}
    
    def get_family_by_device(self, device_id: str) -> Family | None:
        """设备 ID → 家庭（核心路由方法）"""
        ...
    
    def get_tenant_db(self, family_id: str) -> sqlite3.Connection:
        """获取租户数据库连接（带缓存）"""
        ...
    
    def create_family(self, name: str) -> Family:
        """创建新家庭（自动初始化租户库 + 文件目录 + workspace）"""
        ...
    
    def bind_device(self, device_id: str, family_id: str) -> Device:
        """绑定设备到家庭"""
        ...
    
    def unbind_device(self, device_id: str) -> None:
        """解绑设备"""
        ...
```

### 5.3 文件存储结构

```
{data_dir}/
├── master.db                    # 主库
├── families/
│   ├── {family_id_1}/
│   │   ├── tenant.db            # 租户库
│   │   ├── workspace/           # nanobot workspace（会话、记忆）
│   │   │   ├── sessions/
│   │   │   ├── memory/
│   │   │   └── skills/
│   │   ├── content/             # 上传内容
│   │   │   ├── stories/         # 故事音频
│   │   │   ├── music/           # 音乐
│   │   │   └── documents/       # PDF/文本
│   │   └── voices/              # 音色数据（V3）
│   └── {family_id_2}/
│       └── ...
```

---

## 6. 管理后台

### 6.1 后端 API (FastAPI)

#### 认证 API

```
POST /api/auth/register
  Body: { "phone": "138xxx", "password": "xxx", "familyName": "张家" }
  Response: { "token": "jwt...", "familyId": "uuid", "memberId": "uuid" }

POST /api/auth/login
  Body: { "phone": "138xxx", "password": "xxx" }
  Response: { "token": "jwt...", "familyId": "uuid" }

POST /api/auth/refresh
  Headers: Authorization: Bearer {token}
  Response: { "token": "new_jwt..." }
```

#### 设备管理 API

```
GET /api/devices
  Headers: Authorization: Bearer {token}
  Response: { "devices": [{ "id": "dev001", "name": "客厅设备", "status": "active", "lastSeen": "..." }] }

POST /api/devices/bind
  Body: { "deviceId": "dev001", "name": "客厅设备" }
  Response: { "device": { "id": "dev001", "authToken": "xxx" } }

DELETE /api/devices/{deviceId}
  Response: { "ok": true }

GET /api/devices/{deviceId}/config
  Response: { "voiceId": "longxiaochun", "volume": 70, "wakeWord": "你好小伙伴" }

PUT /api/devices/{deviceId}/config
  Body: { "voiceId": "longhua", "volume": 80 }
  Response: { "ok": true }
```

#### 家庭成员 API

```
GET /api/members
  Response: { "members": [{ "id": "...", "name": "小明", "role": "child" }] }

POST /api/members
  Body: { "name": "小明", "role": "child" }
  Response: { "member": { "id": "uuid", ... } }
```

### 6.2 前端 (React)

V1 MVP 页面：

| 页面 | 路由 | 功能 |
|------|------|------|
| 登录 | `/login` | 手机号 + 密码登录 |
| 注册 | `/register` | 创建家庭账号 |
| 首页/设备列表 | `/` | 显示已绑定设备列表和在线状态 |
| 绑定设备 | `/devices/bind` | 输入设备 ID 绑定 |
| 设备配置 | `/devices/:id` | 修改音色、音量、唤醒词 |

### 6.3 管理后台部署

管理后台作为独立 FastAPI 服务运行，与 nanobot gateway 共享数据目录：

```bash
# 启动 nanobot gateway（端口 18790）
nanobot gateway

# 启动管理后台（端口 8080）
cd admin/backend
uvicorn main:app --port 8080
```

---

## 7. Kids-Chat Skill

### 7.1 SKILL.md 定义

放置于 workspace `skills/kids-chat/SKILL.md`，Agent 启动时自动加载。

```markdown
---
description: "儿童友好对话技能，提供温暖安全的聊天体验"
always: true
metadata: '{"nanobot": {"always": true}}'
---

# Kids-Chat Skill

你正在和一个小朋友聊天。请遵循以下规则：

## 对话风格
- 使用简单、温暖、有趣的语言
- 语气亲切友好，像一个耐心的大朋友
- 回复简短（通常不超过 3 句话），适合语音播放
- 适当使用拟声词和语气词增加趣味性

## 安全规则
- 绝不讨论暴力、恐怖、成人内容
- 遇到不适当问题时温和引导到其他话题
- 不透露任何个人隐私信息
- 不鼓励危险行为

## 内容偏好
- 优先使用知识库中的故事和内容（当知识库可用时）
- 鼓励好奇心和学习探索
- 适当融入简单的知识科普
- 支持讲故事、唱儿歌、猜谜语、做游戏

## 播放指令（V2）
当小朋友要求播放故事或音乐时，使用 knowledge_search 工具查找内容。
```

---

## 8. 配置设计

### 8.1 config.json 扩展

```jsonc
{
  // ... 现有 nanobot 配置 ...
  
  "channels": {
    // ... 现有渠道 ...
    "hardware": {
      "enabled": true,
      "mqtt_host": "localhost",          // MQTT Broker 地址
      "mqtt_port": 1883,                 // MQTT Broker 端口
      "mqtt_username": "minibot",        // MQTT 连接用户名
      "mqtt_password": "xxx",            // MQTT 连接密码
      "mqtt_tls": false,                 // 是否启用 TLS（生产环境建议 true）
      "audio_format": "opus",            // 默认音频格式
      "max_devices": 100                 // 最大同时在线设备数
    }
  },
  
  "asr": {
    "provider": "volcengine",
    "volcengine": {
      "appId": "xxx",
      "token": "xxx",
      "cluster": "volcengine_streaming_common",
      "language": "zh-CN"
    }
  },
  
  "tts": {
    "provider": "volcengine",
    "volcengine": {
      "appId": "xxx",
      "token": "xxx",
      "cluster": "volcano_tts",
      "defaultVoice": "zh_female_cancan_mars_bigtts"
    }
  },
  
  "tenant": {
    "dataDir": "~/.minibot/data",  // 多租户数据根目录
    "maxFamilies": 1000,           // 最大家庭数
    "maxDevicesPerFamily": 10      // 每家庭最大设备数
  },
  
  "admin": {
    "enabled": true,
    "port": 8080,
    "jwtSecret": "change-me-in-production",
    "jwtExpireHours": 24
  }
}
```

### 8.2 Pydantic Schema 扩展

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

---

## 9. 目录结构

```
project-root/
├── docs/
│   ├── CLAUDE.md                   # docs 子目录规则（按需加载）
│   ├── DECISIONS.md                # 技术决策记录
│   ├── ROADMAP.md                  # 版本路线图
│   └── design/
│       ├── CLAUDE.md               # 设计文档子目录规则
│       └── V1_DESIGN.md           # 本文档
│
├── nanobot/                        # nanobot 框架（扩展）
│   ├── channels/
│   │   ├── hardware.py            # [NEW] 硬件 MQTT Channel
│   │   └── ... (现有渠道)
│   ├── providers/
│   │   ├── asr.py                 # [NEW] ASR Provider（火山引擎 WebSocket；抽象层支持多厂商扩展）
│   │   ├── tts.py                 # [NEW] TTS Provider（火山引擎 WebSocket；抽象层支持多厂商扩展）
│   │   └── ... (现有 Provider)
│   ├── tenant/                    # [NEW] 多租户模块
│   │   ├── __init__.py
│   │   ├── models.py              # 数据模型
│   │   ├── manager.py             # 租户管理器
│   │   └── storage.py             # 文件存储
│   └── config/
│       └── schema.py              # [MODIFY] 扩展配置
│
├── admin/                          # [NEW] 管理后台
│   ├── backend/
│   │   ├── main.py                # FastAPI 入口
│   │   ├── auth.py                # JWT 认证
│   │   ├── devices.py             # 设备管理
│   │   └── requirements.txt
│   └── frontend/
│       ├── package.json
│       └── src/
│
├── deploy/                         # [NEW] 部署配置
│   └── mosquitto/
│       └── mosquitto.conf         # MQTT Broker 配置
│
├── tests/                          # 测试
│   ├── channels/
│   │   └── test_hardware_channel.py
│   ├── providers/
│   │   ├── test_asr_provider.py
│   │   └── test_tts_provider.py
│   └── tenant/
│       └── test_tenant_manager.py
│
└── tools/                          # [NEW] 开发工具
    └── hardware_test_client.py     # MQTT 测试客户端（模拟 ESP32）
```

---

## 10. 部署方案

### 10.1 开发环境

```bash
# 1. 安装 nanobot（开发模式）
cd minibot
pip install -e ".[dev]"

# 2. 安装管理后台依赖
cd admin/backend
pip install -r requirements.txt

# 3. 启动 MQTT Broker（Mosquitto）
# macOS:
brew install mosquitto
mosquitto -c deploy/mosquitto/mosquitto.conf

# 或使用 Docker:
docker run -d --name mosquitto -p 1883:1883 -p 9001:9001 eclipse-mosquitto:2

# 4. 配置
cp config.example.json ~/.minibot/config.json
# 编辑配置：填入 LLM API Key、火山引擎 ASR/TTS AppId/Token、MQTT 信息

# 5. 启动
nanobot gateway                        # 启动 nanobot + 硬件 MQTT Channel
cd admin/backend && uvicorn main:app   # 启动管理后台

# 6. 测试
python tools/hardware_test_client.py   # 模拟 ESP32 通过 MQTT 发送语音
```

### 10.2 Docker 部署

```yaml
# docker-compose.yml (扩展)
services:
  # MQTT Broker
  mosquitto:
    image: eclipse-mosquitto:2
    ports:
      - "1883:1883"     # MQTT TCP
      - "8883:8883"     # MQTT TLS (生产环境)
      - "9001:9001"     # MQTT WebSocket (调试用)
    volumes:
      - ./deploy/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf
      - mosquitto-data:/mosquitto/data
      - mosquitto-log:/mosquitto/log
    restart: unless-stopped
  
  # MiniBot 网关（nanobot + 硬件 MQTT Channel）
  minibot-gateway:
    build: .
    command: ["gateway"]
    ports:
      - "18790:18790"   # nanobot gateway API
    volumes:
      - ~/.minibot:/root/.minibot
      - minibot-data:/root/.minibot/data
    environment:
      - MQTT_HOST=mosquitto
      - MQTT_PORT=1883
    depends_on:
      - mosquitto
  
  # 管理后台
  minibot-admin:
    build:
      context: ./admin/backend
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
    ports:
      - "8080:8080"
    volumes:
      - minibot-data:/data
    depends_on:
      - minibot-gateway

volumes:
  minibot-data:
  mosquitto-data:
  mosquitto-log:
```

### 10.3 Mosquitto 配置

```conf
# deploy/mosquitto/mosquitto.conf

# 基础配置
listener 1883
protocol mqtt
allow_anonymous false
password_file /mosquitto/config/pwfile

# WebSocket 监听（调试/Web 客户端使用）
listener 9001
protocol websockets

# 持久化
persistence true
persistence_location /mosquitto/data/

# 日志
log_dest file /mosquitto/log/mosquitto.log
log_type all

# TLS (生产环境取消注释)
# listener 8883
# cafile /mosquitto/certs/ca.crt
# certfile /mosquitto/certs/server.crt
# keyfile /mosquitto/certs/server.key
```

### 10.4 生产环境

| 组件 | 建议配置 |
|------|----------|
| 服务器 | 2C4G 起步（无 GPU） |
| MQTT Broker | EMQX（生产）或 Mosquitto（小规模），端口 1883/8883(TLS) |
| 反向代理 | Nginx（HTTP 路由 + MQTT TCP 代理可选） |
| SSL | Let's Encrypt（MQTT 需 TLS，管理后台需 HTTPS） |
| 监控 | 日志：loguru → 文件轮转；MQTT：EMQX Dashboard；指标：Prometheus (可选) |
| 备份 | SQLite 文件 + Mosquitto 持久化数据定期备份 |

Nginx 配置示例：

```nginx
# API — 管理后台
location /api/ {
    proxy_pass http://127.0.0.1:8080;
}

# 前端 — 管理后台
location / {
    root /var/www/minibot-admin;
    try_files $uri /index.html;
}

# 注意：MQTT 不走 Nginx，ESP32 直连 MQTT Broker（1883/8883 端口）
# 如需 MQTT over WebSocket（Web 调试），可配置：
location /mqtt {
    proxy_pass http://127.0.0.1:9001;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}
```

---

## 11. 测试计划

### 11.1 单元测试

| 模块 | 测试文件 | 覆盖内容 |
|------|----------|----------|
| 硬件 Channel | `test_hardware_channel.py` | MQTT 订阅/发布、音频帧解析、设备认证、消息分发 |
| ASR Provider | `test_asr_provider.py` | 火山引擎 WebSocket 连接、流式识别、错误处理、降级逻辑 |
| TTS Provider | `test_tts_provider.py` | 火山引擎 WebSocket 合成、流式输出、错误处理、Provider 切换 |
| 多租户 | `test_tenant_manager.py` | 家庭 CRUD、设备绑定/解绑、路由查询、数据隔离 |

### 11.2 集成测试

| 场景 | 步骤 | 期望结果 |
|------|------|----------|
| 端到端语音对话 | 测试客户端 MQTT 发语音 → 后端 ASR → Agent → TTS → MQTT 回音频 | 收到合成语音回复 |
| 设备认证 | 未绑定设备 MQTT 连接 | 收到 auth_failed 错误 |
| 多租户隔离 | 两设备绑定不同家庭，同时对话 | 各自独立会话、互不影响 |
| TTS 降级 | 模拟火山引擎 TTS 失败 | 返回友好错误提示，日志记录异常 |
| ASR 降级 | 发送空白/噪音音频 | 返回友好错误提示 |
| MQTT 断线重连 | 模拟网络中断后恢复 | 设备自动重连，会话恢复 |
| 遗嘱消息 | 模拟设备异常断线 | 后端收到 LWT，设备状态更新为 offline |

### 11.3 测试客户端

`tools/hardware_test_client.py` — 基于 `paho-mqtt` 的命令行工具，模拟 ESP32 设备：

```bash
# 连接 MQTT Broker 并发送麦克风录音
python tools/hardware_test_client.py --device dev001 --token xxx --broker localhost

# 发送预录音频文件
python tools/hardware_test_client.py --device dev001 --file test.wav --broker localhost

# 模拟设备状态上报
python tools/hardware_test_client.py --device dev001 --status --battery 85
```

---

## 12. 开放问题

| 编号 | 问题 | 状态 | 备注 |
|------|------|------|------|
| Q1 | 火山引擎 ASR/TTS WebSocket API 具体接入方式和定价 | 待验证 | 需注册火山引擎获取 AppId/Token 实际测试 |
| Q2 | MQTT Broker 选型：EMQX vs Mosquitto | ✅ 已决定 | V1 用 Mosquitto 快速开发，生产切 EMQX |
| Q3 | MQTT QoS 级别：音频数据 QoS 0（速度优先）vs QoS 1（可靠优先） | ✅ 已决定 | 音频流 QoS 0 优先低延迟，控制/状态 QoS 1 |
| Q4 | 音频编解码库选择 | 待定 | opuslib（C 绑定）vs pyogg vs 纯 Python 方案 |
| Q5 | MQTT payload 大小限制与音频分片策略 | 待测试 | Mosquitto 默认 max_packet_size 约 256MB，但建议单帧 ≤ 4KB |
| Q6 | 管理后台是否需要国际化 | 待定 | V1 仅支持中文 |
| Q7 | 设备 ID 生成方案 | 待定 | 硬件烧录 vs 首次配网时生成 |
| Q8 | 唤醒词检测是否在端侧完成 | ✅ 已决定 | 推荐端侧，节省带宽和服务端算力 |
| ~~Q9~~ | ~~CosyVoice2 API 作为 TTS 备选方案的优先级~~ | ✅ 已关闭 | V1 统一使用火山引擎 TTS，不再需要备选 |
| Q10 | ASR 多提供商扩展时机 | 待定 | V1 仅实现火山引擎；抽象层已预留，未来可扩展阿里等 |

---

*文档维护人：项目团队*  
*最后更新：2026-03-27*
