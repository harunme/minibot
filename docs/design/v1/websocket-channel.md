# V1 §3b WebSocket 语音通道

> 参考 xiaozhi-esp32-server 架构，通过 WebSocket 直连客户端。
> 实现 `nanobot/channels/websocket_hw.py` 时参考。

## 1. 概述

WebSocket 语音通道面向 Tauri 桌面客户端和 Web 浏览器，客户端通过 WebSocket 直连服务端，无需中间件。

### 特点

| 维度 | 说明 |
|------|------|
| Broker 依赖 | 无，直连 |
| 协议帧 | WebSocket 原生文本/二进制帧 |
| 适用客户端 | Tauri 桌面端 / Web 浏览器 / 未来 ESP32（通过网关） |
| 可靠性 | TCP 可靠传输 |
| 断线重连 | 客户端自行实现 |

## 2. 连接参数

```
URL: ws://{host}:{port}/
默认端口: 9000
认证: hello 消息中携带 device_id + token
超时: 120 秒无活动自动断开
```

## 3. 消息协议

WebSocket 上传输两类数据：

- **文本帧（JSON）**：控制消息，通过 `type` 字段路由
- **二进制帧（bytes）**：音频数据

### 3.1 文本消息类型

#### 客户端 → 服务端

| type | 说明 | 示例 |
|------|------|------|
| `hello` | 握手 | `{"type":"hello","device_id":"dev001","token":"xxx","audio_params":{"format":"opus","sample_rate":16000}}` |
| `listen` | 语音监听控制 | `{"type":"listen","mode":"start"}` 或 `{"type":"listen","mode":"stop"}` |
| `abort` | 中止当前 TTS | `{"type":"abort"}` |
| `ping` | 心跳 | `{"type":"ping"}` |

#### 服务端 → 客户端

| type | 说明 | 示例 |
|------|------|------|
| `hello` | 握手响应 | `{"type":"hello","session_id":"xxx","audio_params":{"format":"opus","sample_rate":24000}}` |
| `stt` | ASR 识别结果 | `{"type":"stt","text":"给我讲个故事","is_final":true}` |
| `tts` | TTS 状态 | `{"type":"tts","state":"start"}` 或 `{"type":"tts","state":"end"}` |
| `reply` | Agent 文本回复 | `{"type":"reply","text":"好的，我给你讲一个..."}` |
| `error` | 错误 | `{"type":"error","code":"auth_failed","message":"认证失败"}` |
| `pong` | 心跳响应 | `{"type":"pong"}` |

### 3.2 二进制消息

- **上行**（客户端 → 服务端）：音频数据（Opus/PCM），直接入 ASR 流式队列
- **下行**（服务端 → 客户端）：TTS 合成的音频数据

WebSocket 协议本身保证消息完整性和顺序，不需要自定义帧头。

## 4. 连接生命周期

```
1. 客户端连接 WebSocket
2. 客户端发送 hello（device_id + token）
3. 服务端验证 → 返回 hello 响应（session_id）
4. 客户端发送 listen(start) → 开始语音监听
5. 客户端发送二进制音频帧 → ASR 流式识别
6. 服务端发送 stt 结果
7. 客户端发送 listen(stop) → 结束语音
8. ASR 最终结果 → 消息总线 → Agent 处理
9. Agent 回复 → 服务端发送 reply + TTS 音频
10. 连接保持，等待下一轮对话
```

## 5. 认证流程

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

# 设备白名单验证
if not is_allowed(device_id):
    send_error("auth_failed", "设备未授权")
    close()
```

## 6. 语音处理流程

```
客户端音频帧 → ConnectionHandler → ASR Provider (流式)
                                        ↓
                                   识别文本
                                        ↓
                              BaseChannel._handle_message()
                                        ↓
                                   消息总线
                                        ↓
                                   Agent 处理
                                        ↓
                              Channel.send(OutboundMessage)
                                        ↓
                              TTS Provider (流式合成)
                                        ↓
                              WebSocket 二进制音频帧 → 客户端
```

## 7. 配置

```json
{
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
  }
}
```
