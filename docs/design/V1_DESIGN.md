# MiniBot 语音伴侣 — V1.0 详细设计文档

> **版本**：V1.0 — 核心对话链路（MVP）  
> **状态**：实现中（M4 全链路已打通）  
> **最后更新**：2026-03-30

---

## 目录

1. [概述](#1-概述)
2. [系统架构](#2-系统架构)
3. [WebSocket 语音通道](#3-websocket-语音通道)
4. [ASR/TTS Provider](#4-asrtts-provider)
5. [配置设计](#5-配置设计)
6. [目录结构](#6-目录结构)
7. [部署方案](#7-部署方案)
8. [测试计划](#8-测试计划)
9. [开放问题](#9-开放问题)

---

## 1. 概述

### 1.1 目标

打通 **"语音输入 → STT → Agent → TTS → 语音输出"** 完整链路，实现一个可工作的最小可用产品。

### 1.2 核心用户故事

```
作为小朋友，我对着设备说"给我讲个故事"，设备用温柔的声音给我讲故事。
```

### 1.3 V1 范围

**包含（M1-M4）**：
- WebSocket 语音通道（面向 Tauri/Web 客户端，参考 xiaozhi-esp32-server 架构）
- ASR 语音识别（火山引擎 ASR WebSocket 流式）
- TTS 语音合成（火山引擎 TTS WebSocket 流式）
- 全链路对话管道（WebSocket → ASR → Agent → TTS → WebSocket）
- 管道延迟埋点（M4 验收指标：首字节 <2s，完整回复 <5s）
- 测试客户端（WebSocket CLI 工具）

**不包含（详见 ROADMAP.md / DECISIONS.md）**：
- 基础多租户（V3.5）
- 管理后台 MVP（V3.5）
- Kids-Chat Skill（V2.0）
- RAG 知识库（V2）
- 硬件固件（V3）
- 音色克隆（V4）
- 移动端 App（V5b）

---

## 2. 系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           客户端层                                           │
├──────────────┬──────────────────┬──────────────┬───────────────────────────┤
│  Tauri 桌面端 │  Web 测试客户端    │  ESP32 硬件   │  管理后台 (React)          │
│  (WebSocket) │  (WebSocket)     │  (WebSocket)  │  (HTTP)                   │
└──────┬───────┴────────┬─────────┴──────┬───────┴──────┬────────────────────┘
       │                │                │              │
       │  WebSocket     │  WebSocket     │  WebSocket   │  HTTP
       ▼                ▼                ▼              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MiniBot 服务端                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │           WebSocket Channel (:9000)                                   │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │  │
│  │  │ 连接管理      │  │ 设备白名单    │  │ 会话管理      │               │  │
│  │  │(WebSocket)   │  │ (allow_from) │  │(session_id)  │               │  │
│  │  └──────┬───────┘  └──────────────┘  └──────▲───────┘               │  │
│  │         │                                   │                        │  │
│  │         ▼                                   │                        │  │
│  │  ┌──────────────┐                   ┌──────────────┐                │  │
│  │  │ ASR Provider  │                   │ TTS Provider  │                │  │
│  │  │(WebSocket)   │                   │(WebSocket)   │                │  │
│  │  └──────┬───────┘                   └──────▲───────┘                │  │
│  └─────────┼──────────────────────────────────┼────────────────────────┘  │
│            │                                  │                           │
│            │  WebSocket                       │  WebSocket                │
│            ▼                                  │                           │
│  ┌─────────────────────┐  ┌───────────────────┴───────────┐              │
│  │火山引擎 ASR           │  │火山引擎 TTS                    │              │
│  │音频流 → 文本          │  │文本 → 音频流                   │              │
│  └─────────────────────┘  └───────────────────────────────┘              │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────────┐│
│  │             nanobot 核心 (复用)                                         ││
│  │  ┌────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ ┌──────────────────┐ ││
│  │  │消息总线 │ │Agent Loop│ │Context │ │记忆系统 │ │Channel Manager  │ ││
│  │  │(Bus)   │ │(Loop)    │ │Builder │ │(Memory)│ │(路由 + 分发)     │ ││
│  │  └────────┘ └──────────┘ └────────┘ └────────┘ └──────────────────┘ ││
│  └───────────────────────────────────────────────────────────────────────┘│
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
完整语音对话流程（M4 全链路）：

上行链路（语音输入）：
1. 客户端 WebSocket 连接 → hello 握手（device_id + token）
2. 客户端 listen(start) → ConnectionHandler 开始监听
3. 客户端发送二进制音频帧 → ConnectionHandler._asr_audio_queue
4. ASR Provider 流式识别 → 实时发送 stt 中间结果给客户端
5. ASR 最终结果 → BaseChannel._handle_message() → InboundMessage → 消息总线

处理链路（Agent 思考）：
6. AgentLoop: bus.consume_inbound() → Context Builder → LLM → 文本回复
7. AgentLoop: bus.publish_outbound(OutboundMessage)

下行链路（语音输出）：
8. ChannelManager._dispatch_outbound() → WebSocketChannel.send(msg)
9. ConnectionHandler.send_reply() → 发送 reply JSON（文本回复）
10. TTS Provider 流式合成 → WebSocket 二进制音频帧 → 客户端播放

延迟埋点（对应 M4 验收指标）：
- t0: listen(start) 时刻
- t1: ASR 首字（<500ms）
- t2: ASR 完成
- t3: Agent 回复到达 Channel（全链路首字节 <2s）
- t4: TTS 首帧（<300ms from t3）
- t5: TTS 完成（全链路 <5s）
```

### 2.3 协议策略

| 层面 | 协议 | 职责 | 优势 |
|------|------|------|------|
| 客户端 ↔ 服务端 | **WebSocket** | 音频流传输、控制消息、状态管理 | 无 Broker 依赖、直连、全双工流式、架构简洁 |
| 服务端 ↔ 火山引擎 | **WebSocket** | ASR 音频流实时识别、TTS 文本流实时合成 | 高实时性、与火山引擎 API 天然匹配 |

### 2.4 与 nanobot 的集成方式

| 扩展点 | 方式 | 说明 |
|--------|------|------|
| WebSocket Channel | `BaseChannel` 子类 | `channels/websocket_voice.py`，内嵌 WebSocket 服务器 |
| ASR Provider | `websockets` 客户端 | Channel 内部创建，流式调用火山引擎 ASR |
| TTS Provider | 独立 Provider 模块 + WebSocket | `providers/tts.py`，内部通过 WebSocket 调用火山引擎 TTS |
| 消息总线 | `MessageBus` 双队列 | `bus/queue.py`，解耦 Channel 与 AgentLoop |
| 出站路由 | `ChannelManager` | `channels/manager.py`，消费 outbound 队列，路由到正确 Channel |

---

## 3. WebSocket 语音通道

### 3.1 概述

WebSocket 语音通道面向 Tauri 桌面客户端和 Web 浏览器，客户端通过 WebSocket 直连服务端，无需中间件（Broker）。文件位置 `nanobot/channels/websocket_voice.py`，继承 `BaseChannel`。内部集成 ASR/TTS Provider 负责语音识别和合成。

> 详细协议规范：`docs/design/v1/websocket-channel.md`

### 3.2 连接参数

```
URL: ws://{host}:{port}/
默认端口: 9000
认证: hello 消息中携带 device_id + token
超时: 120 秒无活动自动断开
最大连接数: 100（可配置）
```

### 3.3 消息协议

WebSocket 上传输两类数据：
- **文本帧（JSON）**：控制消息，通过 `type` 字段路由
- **二进制帧（bytes）**：音频数据（Opus/PCM）

#### 客户端 → 服务端

| type | 说明 | 示例 |
|------|------|------|
| `hello` | 握手认证 | `{"type":"hello","device_id":"dev001","token":"xxx","audio_params":{"format":"opus","sample_rate":16000}}` |
| `listen` | 语音监听控制 | `{"type":"listen","mode":"start"}` / `{"type":"listen","mode":"stop"}` |
| `abort` | 中止当前 TTS | `{"type":"abort"}` |
| `ping` | 心跳 | `{"type":"ping"}` |
| *(binary)* | 音频帧 | 原始 Opus/PCM 音频数据 |

#### 服务端 → 客户端

| type | 说明 | 示例 |
|------|------|------|
| `hello` | 握手响应 | `{"type":"hello","session_id":"xxx","audio_params":{"format":"opus","sample_rate":24000}}` |
| `stt` | ASR 识别结果 | `{"type":"stt","text":"给我讲个故事","is_final":true}` |
| `tts` | TTS 状态 | `{"type":"tts","state":"start"}` / `{"type":"tts","state":"end"}` |
| `reply` | Agent 文本回复 | `{"type":"reply","text":"好的，我给你讲一个..."}` |
| `error` | 错误 | `{"type":"error","code":"auth_failed","message":"认证失败"}` |
| `pong` | 心跳响应 | `{"type":"pong"}` |
| *(binary)* | TTS 音频帧 | 合成的 Opus/PCM 音频数据 |

### 3.4 连接管理

| 机制 | 说明 |
|------|------|
| 心跳 | 客户端定期发送 `ping`，服务端回复 `pong`；超时 120s 无活动自动断开 |
| 断线重连 | 客户端自行实现（WebSocket 标准无自动重连） |
| 认证 | hello 消息中 `token` 验证 + `device_id` 白名单检查 |
| 并发管理 | 每连接独立 `ConnectionHandler`，`max_connections` 限制总连接数 |

### 3.5 语音处理流程

```
客户端连接 → hello 握手
              ↓
客户端 listen(start) → 开始监听（记录 t0 时间戳）
              ↓
客户端二进制音频帧 → _asr_audio_queue
              ↓
ASR Provider 流式识别 → stt 中间结果 → 客户端
              ↓ (最终结果)
BaseChannel._handle_message() → InboundMessage → 消息总线
              ↓
AgentLoop → LLM 处理 → OutboundMessage → 消息总线
              ↓
ChannelManager → WebSocketChannel.send(msg)
              ↓
ConnectionHandler.send_reply():
  1. 发送 reply JSON（文本回复）
  2. 发送 tts(start) 通知
  3. TTS Provider 流式合成 → 二进制音频帧 → 客户端播放
  4. 发送 tts(end) 通知
```

### 3.6 核心实现

```python
# nanobot/channels/websocket_voice.py（简化伪代码）

class WebSocketVoiceChannel(BaseChannel):
    name = "websocket_voice"
    display_name = "WebSocket Voice"

    def __init__(self, config: dict, bus: MessageBus):
        super().__init__(config, bus)
        self._asr_provider = self._create_asr_provider()
        self._tts_provider = self._create_tts_provider()
        self._connections: dict[str, ConnectionHandler] = {}

    async def start(self) -> None:
        """启动 WebSocket 服务器，监听客户端连接"""
        async with websockets.serve(
            self._handle_connection,
            host=self._cfg("host", "0.0.0.0"),
            port=self._cfg("port", 9000),
        ):
            await asyncio.Future()  # 永久运行

    async def send(self, msg: OutboundMessage) -> None:
        """Agent 回复 → 查找设备连接 → 发送回复 + TTS 音频"""
        handler = self._connections.get(msg.chat_id)
        if handler:
            await handler.send_reply(msg)


class ConnectionHandler:
    """每个 WebSocket 连接的处理器"""

    async def _handle_hello(self, msg: dict) -> None:
        """握手认证：验证 token + 设备白名单"""

    async def _handle_listen(self, msg: dict) -> None:
        """语音监听控制：start/stop"""
        # start: 记录 t0 时间戳，清空队列，启动 ASR 任务
        # stop: 发送结束标志到 ASR 队列

    async def _run_asr(self) -> None:
        """ASR 流式识别 + 管道延迟埋点
        - 从 _asr_audio_queue 读取音频
        - 流式送入 ASR Provider
        - 实时发送 stt 中间结果
        - 最终结果 → _handle_message() → 消息总线
        """

    async def send_reply(self, msg: OutboundMessage) -> None:
        """发送回复 + TTS 流式音频 + 延迟埋点
        - 发送 reply JSON
        - TTS 流式合成 → 二进制音频帧
        - 支持 abort 中止
        """

    async def _handle_abort(self, msg: dict) -> None:
        """中止当前 TTS 播放"""

    async def _handle_binary(self, data: bytes) -> None:
        """接收客户端音频帧 → ASR 队列"""
```

### 3.7 认证流程

```python
# hello 消息认证
if config.auth_key:
    # 需要验证 token
    if msg["token"] != config.auth_key:
        send_error("auth_failed", "认证失败")
        close()
else:
    # auth_key 为空则跳过认证（开发模式）
    pass

# 设备白名单验证（复用 BaseChannel.is_allowed()）
if not is_allowed(device_id):
    send_error("auth_failed", "设备未授权")
    close()
```

---

## 4. ASR/TTS Provider

### 4.1 概述

后端通过独立的 ASR/TTS Provider 模块对接火山引擎的语音识别和语音合成流式 API（WebSocket）。这一层对上层 Channel 透明，Channel 只需调用 `asr_provider.recognize_stream()` 和 `tts_provider.synthesize()`。

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
    def recognize_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        *,
        format: str = "opus",
        sample_rate: int = 16000,
    ) -> AsyncIterator[str]:
        """流式识别：边发送音频边获取中间结果
        
        注意：此方法应实现为 async generator（使用 async def + yield），
        但抽象基类中不能使用 yield（否则会把方法变成 generator 而非抽象签名）。
        因此这里声明为普通方法返回 AsyncIterator[str]，子类实现时使用 async def + yield。
        
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
    def synthesize(
        self,
        text: str,
        voice_id: str = "default",
        *,
        format: str = "opus",        # "opus" | "pcm" | "mp3"
        sample_rate: int = 24000,
    ) -> AsyncIterator[bytes]:
        """将文本转为语音音频流（流式输出）
        
        注意：此方法应实现为 async generator（使用 async def + yield），
        但抽象基类中不能使用 yield。子类实现时使用 async def + yield。
        
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

## 5. 配置设计

### 5.1 config.json 扩展

```jsonc
{
  // ... 现有 nanobot 配置 ...
  
  "channels": {
    // ... 现有渠道 ...
    "websocket_voice": {
      "enabled": true,
      "host": "0.0.0.0",                // WebSocket 监听地址
      "port": 9000,                      // WebSocket 监听端口
      "authKey": "",                     // 认证密钥（空=跳过认证，开发模式）
      "maxConnections": 100,             // 最大同时连接数
      "timeoutSeconds": 120,             // 连接超时（秒）
      "audioFormat": "opus",             // 默认音频格式
      "allowFrom": ["*"]                // 设备白名单（"*" 允许所有; 生产环境改为具体设备 ID）
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
  }
}
```

### 5.2 Pydantic Schema 扩展

在 `nanobot/config/schema.py` 中：

```python
class WebSocketChannelConfig(Base):
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 9000
    auth_key: str = ""
    max_connections: int = 100
    timeout_seconds: int = 120
    audio_format: str = "opus"
    allow_from: list[str] = ["*"]  # 设备白名单; "*" 允许所有

class ASRConfig(Base):
    provider: str = "volcengine"
    volcengine: VolcengineASRConfig = Field(default_factory=VolcengineASRConfig)

class TTSConfig(Base):
    provider: str = "volcengine"
    volcengine: VolcengineTTSConfig = Field(default_factory=VolcengineTTSConfig)
```

---

## 6. 目录结构

```
project-root/
├── docs/
│   ├── CLAUDE.md                   # docs 子目录规则（按需加载）
│   ├── DECISIONS.md                # 技术决策记录
│   ├── ROADMAP.md                  # 版本路线图
│   └── design/
│       ├── CLAUDE.md               # 设计文档子目录规则
│       ├── V1_DESIGN.md           # 本文档
│       └── v1/
│           ├── overview-and-architecture.md  # 概述与架构
│           └── websocket-channel.md          # WebSocket 协议规范
│
├── nanobot/                        # nanobot 框架
│   ├── channels/
│   │   ├── base.py                # BaseChannel 抽象基类
│   │   ├── manager.py             # ChannelManager（路由 + 分发）
│   │   ├── registry.py            # 通道自动发现
│   │   ├── websocket_voice.py        # WebSocket 语音通道（V1 核心）
│   │   └── ... (其他渠道)
│   ├── providers/
│   │   ├── asr.py                 # ASR Provider（火山引擎 WebSocket）
│   │   ├── tts.py                 # TTS Provider（火山引擎 WebSocket）
│   │   └── ... (LLM Provider 等)
│   ├── agent/
│   │   ├── loop.py                # AgentLoop（消息处理引擎）
│   │   ├── runner.py              # AgentRunner（LLM 迭代循环）
│   │   └── context.py             # ContextBuilder（上下文组装）
│   ├── bus/
│   │   ├── queue.py               # MessageBus（双队列）
│   │   └── events.py              # InboundMessage / OutboundMessage
│   ├── session/
│   │   └── manager.py             # SessionManager（JSONL 持久化）
│   └── config/
│       ├── schema.py              # Pydantic 配置模型
│       └── loader.py              # 配置加载 / 保存
│
├── tests/                          # 测试
│   ├── conftest.py                # 全局 fixtures（MessageBus 等）
│   ├── channels/
│   │   └── test_websocket_voice_channel.py  # WebSocket 通道单元测试（27个）
│   ├── integration/
│   │   └── test_conversation_pipeline.py # M4 全链路集成测试（11个）
│   └── providers/
│       ├── test_asr_provider.py
│       └── test_tts_provider.py
│
└── tools/                          # 开发工具
    └── ws_test_client.py           # WebSocket 测试客户端（模拟 Tauri/Web）
```

---

## 7. 部署方案

### 7.1 开发环境

```bash
# 1. 安装 nanobot（开发模式）
cd minibot
uv sync            # 使用 uv 管理依赖
# 或: pip install -e ".[dev]"

# 2. 配置
cp config.example.json ~/.minibot/config.json
# 编辑配置：填入 LLM API Key、火山引擎 ASR/TTS AppId/Token
# 启用 WebSocket 通道：channels.websocket_voice.enabled = true

# 3. 启动网关（WebSocket Channel + AgentLoop）
nanobot gateway

# 4. 测试（使用 WebSocket 测试客户端）
python tools/ws_test_client.py   # 模拟 Tauri/Web 客户端通过 WebSocket 发送语音
```

### 7.2 Docker 部署

```yaml
# docker-compose.yml
services:
  # MiniBot 网关（nanobot + WebSocket Channel）
  minibot-gateway:
    build: .
    command: ["gateway"]
    ports:
      - "9000:9000"     # WebSocket Channel
      - "18790:18790"   # nanobot gateway API
    volumes:
      - ~/.minibot:/root/.minibot
      - minibot-data:/root/.minibot/data
    restart: unless-stopped

volumes:
  minibot-data:
```

### 7.3 生产环境

| 组件 | 建议配置 |
|------|----------|
| 服务器 | 2C4G 起步（无 GPU） |
| WebSocket | 端口 9000，建议通过 Nginx 反向代理 + TLS |
| SSL | Let's Encrypt（Nginx TLS 终止） |
| 监控 | 日志：loguru → 文件轮转；管道延迟：内置埋点；指标：Prometheus (可选) |
| 备份 | 会话数据（JSONL）定期备份 |

Nginx 反向代理配置（WebSocket）：

```nginx
# WebSocket Channel 代理
location /ws {
    proxy_pass http://127.0.0.1:9000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
}
```

---

## 8. 测试计划

### 8.1 单元测试

| 模块 | 测试文件 | 覆盖内容 | 数量 |
|------|----------|----------|------|
| WebSocket Channel | `test_websocket_voice_channel.py` | 连接握手、设备认证/白名单、消息路由、listen 控制、abort、send reply | 27 |
| ASR Provider | `test_asr_provider.py` | 火山引擎 WebSocket 连接、流式识别、错误处理 | — |
| TTS Provider | `test_tts_provider.py` | 火山引擎 WebSocket 合成、流式输出、错误处理 | — |

### 8.2 集成测试

| 阶段 | 测试 | 验证内容 |
|------|------|----------|
| Stage 1 | ASR 产出 + Bus 发布 | 音频 → ASR 流式识别 → STT 消息 → InboundMessage 到达消息总线 |
| Stage 2 | 出站路由 | OutboundMessage → Channel.send() → reply + TTS 音频 |
| Stage 3 | **全链路** | hello → listen → 音频 → ASR → Bus → 模拟回复 → TTS → 客户端 |
| Stage 4 | 优雅降级 | ASR 不可用 → 错误消息 / TTS 不可用 → 纯文本 |
| Stage 5 | TTS 中止 | abort → 停止音频流 |
| Stage 6 | 多连接 | 两设备独立收发 |
| Stage 7 | **完整轮次** | 握手 → 监听 → ASR → Bus → Agent 回复 → TTS → 验证 |

集成测试文件：`tests/integration/test_conversation_pipeline.py`（11 个测试，全部通过）

### 8.3 端到端验证

| 场景 | 步骤 | 期望结果 |
|------|------|----------|
| 端到端语音对话 | `ws_test_client.py` 录音 → WebSocket → 后端 ASR → Agent → TTS → 客户端播放 | 收到合成语音回复 |
| 设备白名单验证 | 不在 allow_from 列表中的设备连接 WebSocket | 收到 auth_failed 错误，连接被关闭 |
| TTS 降级 | 模拟火山引擎 TTS 失败 | 返回友好错误提示，日志记录异常 |
| ASR 降级 | 发送空白/噪音音频 | 返回友好提示 |
| 连接超时 | 客户端 120s 无活动 | 服务端自动断开连接 |

### 8.4 测试客户端

`tools/ws_test_client.py` — 基于 `websockets` 的命令行工具，模拟 Tauri/Web 客户端：

```bash
# 连接 WebSocket 并发送麦克风录音
python tools/ws_test_client.py --device dev001 --token xxx --host localhost --port 9000

# 交互命令
# mic    — 开始/停止录音
# abort  — 中止 TTS 播放
# ping   — 发送心跳
# quit   — 断开连接
```

---

## 9. 开放问题

| 编号 | 问题 | 状态 | 备注 |
|------|------|------|------|
| Q1 | 火山引擎 ASR/TTS WebSocket API 具体接入方式和定价 | 待验证 | 需注册火山引擎获取 AppId/Token 实际测试 |
| Q2 | ~~MQTT Broker 选型~~ | ✅ 已废弃 | V1 统一使用 WebSocket 直连，无需 Broker |
| Q3 | ~~MQTT QoS 策略~~ | ✅ 已废弃 | WebSocket 基于 TCP，天然可靠传输 |
| Q4 | 音频编解码库选择 | 待定 | opuslib（C 绑定）vs pyogg vs 纯 Python 方案 |
| Q5 | ~~MQTT payload 大小限制~~ | ✅ 已废弃 | WebSocket 无此限制 |
| Q6 | 设备 ID 生成方案 | 待定 | 客户端生成 UUID / 用户绑定 |
| Q7 | 唤醒词检测是否在端侧完成 | ✅ 已决定 | 推荐端侧，节省带宽和服务端算力 |
| Q8 | ASR 多提供商扩展时机 | 待定 | V1 仅实现火山引擎；抽象层已预留，未来可扩展 |
| Q9 | WebSocket 断线重连策略 | 待定 | 客户端实现指数退避重连 + 会话恢复 |
| Q10 | 全链路延迟优化 | 进行中 | M4 埋点已就位，需实际联调验证 <2s 首字节目标 |

---

*文档维护人：项目团队*  
*最后更新：2026-03-30*
