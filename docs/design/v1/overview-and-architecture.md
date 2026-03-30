# V1 §1-2 概述与系统架构

> 摘自 `V1_DESIGN.md` §1-§2，供 AI 开发时按需参考。
> **注意**：V1 已统一使用 WebSocket 通道，原 MQTT Channel 设计已废弃（历史记录见 `DECISIONS.md`）。

## 1. 概述

### 1.1 目标

打通 **"语音输入 → STT → Agent → TTS → 语音输出"** 完整链路，实现一个可工作的最小可用产品。

### 1.2 核心用户故事

```
作为小朋友，我对着设备说"给我讲个故事"，设备用温柔的声音给我讲故事。
作为家长，我在后台注册账号，绑定设备，让孩子可以开始使用。
```

### 1.3 V1 范围

**包含（M1-M4）**：
- **WebSocket 语音通道（面向 Tauri/Web 客户端，参考 xiaozhi-esp32-server 架构）**
- 后端 WebSocket 客户端（对接火山引擎 ASR/TTS 流式 API）
- TTS 语音合成（火山引擎 TTS WebSocket 流式）
- STT 语音识别（火山引擎 ASR WebSocket 流式）
- 测试客户端（WebSocket）

> 其他版本的功能范围详见 `ROADMAP.md` 和对应版本设计目录（`v2/`、`v3.5/` 等）。

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
│  WebSocket Channel (:9000)                              │  nanobot 核心      │
│  ← 所有客户端直连（Tauri/Web/ESP32）                      │  Agent + Bus      │
├─────────────────────────────────────────────────────────┴─────────────────┤
│  ASR Provider (火山引擎 WebSocket)  │  TTS Provider (火山引擎 WebSocket)       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 通道策略

| 通道 | 协议 | 适用客户端 | 特点 |
|------|------|-----------|------|
| **WebSocket Channel** | WebSocket | Tauri 桌面端、Web 浏览器、ESP32（未来通过网关） | 无 Broker 依赖、直连、架构简洁 |
| 后端 ↔ 火山引擎 | WebSocket | — | ASR/TTS 流式调用 |

> WebSocket Channel 设计详见 `websocket-channel.md`。

### 2.3 与 nanobot 的集成方式

| 扩展点 | 方式 | 说明 |
|--------|------|------|
| WebSocket Channel | `BaseChannel` 子类 | `channels/websocket_hw.py`，内嵌 WebSocket 服务器 |
| ASR WebSocket | `websockets` 客户端 | Channel 内部实现，流式调用火山引擎 ASR |
| TTS | 独立 Provider 模块 + WebSocket | `providers/tts.py`，内部通过 WebSocket 调用火山引擎 TTS |
