"""WebSocket 硬件语音通道 — 客户端接入方案

参考 xiaozhi-esp32-server 架构，通过 WebSocket 直连客户端（Tauri/Web）。
文本消息（JSON）走控制流，二进制消息走音频流。

消息协议：
- hello: 握手认证（device_id + token）
- listen: 语音监听控制（start/stop）
- abort: 中止当前 TTS 播放
- ping/pong: 心跳保活
- stt: ASR 识别结果（服务端 → 客户端）
- tts: TTS 状态通知（服务端 → 客户端）
- reply: Agent 文本回复（服务端 → 客户端）
- error: 错误信息（服务端 → 客户端）

设计文档：docs/design/v1/websocket-channel.md
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from enum import Enum
from typing import Any, AsyncIterator

import websockets
from websockets.protocol import State as WsState
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebSocketChannelConfig
from nanobot.providers.vad import VADState


class MessageType(str, Enum):
    """WebSocket 消息类型枚举"""

    HELLO = "hello"
    LISTEN = "listen"
    ABORT = "abort"
    PING = "ping"
    PONG = "pong"
    STT = "stt"
    TTS = "tts"
    REPLY = "reply"
    ERROR = "error"


class ConnectionHandler:
    """WebSocket 连接处理器 — 每个客户端连接对应一个实例

    管理单个连接的生命周期：认证、音频缓冲、ASR 流式识别、TTS 下行。
    参考 xiaozhi-server 的 ConnectionHandler 模式。
    """

    def __init__(
        self,
        websocket: websockets.WebSocketServerProtocol,
        channel: WebSocketHardwareChannel,
    ):
        self._ws = websocket
        self._channel = channel

        # 连接状态
        self.session_id: str = uuid.uuid4().hex[:12]
        self.device_id: str | None = None
        self.authenticated: bool = False

        # 活动时间追踪（用于超时检测）
        self._last_activity: float = time.monotonic()
        self._timeout_seconds: int = channel._cfg("timeout_seconds", 120)

        # ASR 流式识别相关
        self._asr_audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._listening: bool = False
        self._asr_task: asyncio.Task | None = None
        self._listen_start_time: float = 0.0  # listen(start) 时刻，用于管道延迟埋点

        # VAD 状态（duplex 模式下由 VADProvider.create_state() 创建）
        self._vad_state: VADState | None = None

        # TTS 中止标志
        self._tts_abort: bool = False

        # 超时检查任务
        self._timeout_task: asyncio.Task | None = None

    async def handle(self) -> None:
        """处理 WebSocket 连接的完整生命周期"""
        logger.info("[{}] 新连接: {}", self.session_id, self._ws.remote_address)

        # 启动超时检查
        self._timeout_task = asyncio.create_task(self._check_timeout())

        try:
            async for message in self._ws:
                self._last_activity = time.monotonic()

                if isinstance(message, str):
                    await self._handle_text(message)
                elif isinstance(message, bytes):
                    await self._handle_binary(message)
        except websockets.ConnectionClosed as e:
            logger.info("[{}] 连接关闭: {}", self.session_id, e)
        except Exception as e:
            logger.exception("[{}] 连接异常: {}", self.session_id, e)
        finally:
            await self._cleanup()

    async def _handle_text(self, message: str) -> None:
        """处理文本消息（JSON 控制消息）"""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("[{}] 无效 JSON: {}", self.session_id, message[:100])
            return

        msg_type = data.get("type", "")
        logger.debug("[{}] 收到消息: type={}", self.session_id, msg_type)

        # hello 消息不需要预先认证
        if msg_type == MessageType.HELLO:
            await self._handle_hello(data)
            return

        # 其他消息需要先完成认证
        if not self.authenticated:
            await self._send_error("not_authenticated", "请先发送 hello 消息完成认证")
            return

        if msg_type == MessageType.LISTEN:
            await self._handle_listen(data)
        elif msg_type == MessageType.ABORT:
            await self._handle_abort()
        elif msg_type == MessageType.PING:
            await self._send_json({"type": MessageType.PONG})
        else:
            logger.warning("[{}] 未知消息类型: {}", self.session_id, msg_type)

    async def _handle_binary(self, data: bytes) -> None:
        """处理二进制消息（上行音频帧）

        duplex 模式（有 VAD）：
            - VAD 检测有声 → 追加到 state.audio_buffer
            - VAD 检测说完 → 触发 _flush_asr()（ASR recognize）
        无 VAD（降级）：
            - 音频直接入 ASR 队列，由 _run_asr() 处理
        """
        if not self.authenticated:
            return

        if not self._listening:
            logger.debug("[{}] 收到音频但未在监听状态，忽略", self.session_id)
            return

        vad_provider = self._channel._vad_provider
        vad_state = self._vad_state

        if vad_provider is not None and vad_state is not None:
            # duplex 模式：VAD 检测
            have_voice = vad_provider.is_vad(vad_state, data)
            logger.debug("[{}] VAD have_voice={}", self.session_id, have_voice)

            # VAD 检测到说完，触发 ASR 识别
            if vad_state.client_voice_stop:
                asyncio.create_task(self._flush_asr())
                # client_voice_stop 由 _flush_asr() 处理后重置

            # 有声帧已由 VAD 追加到 state.audio_buffer，无需额外操作
        else:
            # 无 VAD（降级模式）：音频直接入 ASR 队列
            await self._asr_audio_queue.put(data)

    async def _handle_hello(self, data: dict[str, Any]) -> None:
        """处理握手消息：认证 + 初始化"""
        device_id = data.get("device_id", "")
        token = data.get("token", "")

        if not device_id:
            await self._send_error("invalid_hello", "缺少 device_id")
            await self._close()
            return

        # 认证：如果配置了 auth_key，需要验证 token
        auth_key = self._channel._cfg("auth_key", "")
        if auth_key and token != auth_key:
            await self._send_error("auth_failed", "认证失败")
            await self._close()
            return

        # 设备白名单验证
        if not self._channel.is_allowed(device_id):
            await self._send_error("auth_failed", "设备未授权")
            await self._close()
            return

        self.device_id = device_id
        self.authenticated = True

        # 注册连接到 Channel（踢掉同设备旧连接）
        self._channel._register_connection(device_id, self)

        # 发送握手响应
        audio_format = self._channel._cfg("audio_format", "pcm")
        tts_sample_rate = self._channel._cfg("tts_sample_rate", 24000)
        await self._send_json({
            "type": MessageType.HELLO,
            "session_id": self.session_id,
            "audio_params": {
                "format": audio_format,
                "sample_rate": tts_sample_rate,
            },
        })
        logger.info("[{}] 设备 {} 认证成功", self.session_id, device_id)

    async def _handle_listen(self, data: dict[str, Any]) -> None:
        """处理语音监听控制

        mode=start: 启动 ASR 流式识别
        mode=stop: 停止发送音频，等待最终识别结果
        """
        mode = data.get("mode", "")

        if mode == "start":
            if self._listening:
                logger.debug("[{}] 已在监听状态", self.session_id)
                return
            self._listening = True
            self._listen_start_time = time.monotonic()

            # 初始化 VAD 状态（duplex 模式）
            vad_provider = self._channel._vad_provider
            if vad_provider is not None:
                self._vad_state = vad_provider.create_state()
                logger.info("[{}] 开始语音监听（duplex + VAD）", self.session_id)
            else:
                self._vad_state = None
                # 无 VAD（降级模式）：清空队列 + 启动 ASR 流式识别任务
                while not self._asr_audio_queue.empty():
                    self._asr_audio_queue.get_nowait()
                self._asr_task = asyncio.create_task(self._run_asr())
                logger.info("[{}] 开始语音监听（无 VAD，降级模式）", self.session_id)

        elif mode == "stop":
            if not self._listening:
                return
            self._listening = False

            # duplex 模式：释放 VAD 资源
            if self._vad_state is not None and self._channel._vad_provider is not None:
                # 如果有缓冲音频，先取走再释放（避免 _flush_asr 读到 None）
                if self._vad_state.audio_buffer:
                    audio_data = bytes(self._vad_state.audio_buffer)
                    vad_provider = self._channel._vad_provider
                    self._channel._vad_provider.release_state(self._vad_state)
                    self._vad_state = None
                    asyncio.create_task(self._flush_asr_from_buffer(audio_data))
                else:
                    self._channel._vad_provider.release_state(self._vad_state)
                    self._vad_state = None
            # 降级模式：发送 None 强制 ASR task 退出
            elif self._asr_task is not None:
                await self._asr_audio_queue.put(None)

            logger.info("[{}] 停止语音监听", self.session_id)

        else:
            logger.warning("[{}] 无效的 listen mode: {}", self.session_id, mode)

    async def _handle_abort(self) -> None:
        """处理中止命令：停止当前 TTS 播放"""
        self._tts_abort = True
        logger.info("[{}] TTS 中止", self.session_id)

    async def _run_asr(self) -> None:
        """运行 ASR 流式识别

        从音频队列读取数据，送入 ASR Provider 流式识别，
        将识别结果实时发送给客户端，最终结果发到消息总线。

        延迟埋点：
        - t0: listen(start) 收到时刻（由 _handle_listen 设置）
        - t1: ASR 首次返回文本
        - t2: ASR 最终结果，发布到消息总线
        """
        asr_provider = self._channel._asr_provider
        if not asr_provider:
            await self._send_error("asr_unavailable", "ASR 服务不可用")
            return

        final_text = ""
        t0 = self._listen_start_time or time.monotonic()
        t_first_text = 0.0
        try:
            async def audio_stream() -> AsyncIterator[bytes]:
                """从队列生成音频流"""
                while True:
                    chunk = await self._asr_audio_queue.get()
                    if chunk is None:
                        break
                    yield chunk

            # 流式识别，实时发送中间结果
            async for text in asr_provider.recognize_stream(
                audio_stream(),
                audio_format=self._channel._cfg("audio_format", "opus"),
                sample_rate=16000,
            ):
                if text:
                    if not t_first_text:
                        t_first_text = time.monotonic()
                        logger.info(
                            "[{}] ⏱ ASR 首字 {:.0f}ms",
                            self.session_id,
                            (t_first_text - t0) * 1000,
                        )
                    final_text = text
                    await self._send_json({
                        "type": MessageType.STT,
                        "text": text,
                        "is_final": False,
                    })

            # 发送最终结果
            if final_text:
                t_asr_done = time.monotonic()
                await self._send_json({
                    "type": MessageType.STT,
                    "text": final_text,
                    "is_final": True,
                })
                logger.info(
                    "[{}] ⏱ ASR 完成 {:.0f}ms | 结果: {}",
                    self.session_id,
                    (t_asr_done - t0) * 1000,
                    final_text,
                )

                # 发送到消息总线，触发 Agent 处理
                logger.info("[{}] ⏱ ASR 完成 {:.0f}ms | 结果: {} | 正在发布到消息总线",
                    self.session_id,
                    (t_asr_done - t0) * 1000,
                    final_text,
                )
                await self._channel._handle_message(
                    sender_id=self.device_id or "",
                    chat_id=self.device_id or "",
                    content=final_text,
                    metadata={
                        "device_id": self.device_id,
                        "session_id": self.session_id,
                        "_pipeline_t0": t0,
                    },
                )
                logger.info("[{}] 消息已发布到总线，等待 Agent 回复...", self.session_id)

        except Exception as e:
            logger.exception("[{}] ASR 流式识别失败: {}", self.session_id, e)
            await self._send_error("asr_failed", f"语音识别失败: {e}")

    async def _flush_asr(self) -> None:
        """VAD 检测到说完，触发 ASR 单次识别

        将 VAD 缓冲的音频送入 ASR recognize()，识别完成后：
        1. 发送 stt 结果给客户端
        2. 发布到消息总线触发 Agent
        3. 清空缓冲并重置 VAD 状态，继续接收下一轮音频
        """
        vad_state = self._vad_state
        if vad_state is None or not vad_state.audio_buffer:
            return

        # 提取并清空缓冲
        audio_data = bytes(vad_state.audio_buffer)
        vad_state.audio_buffer.clear()
        # 重置 VAD 说完标志（允许继续接收音频）
        vad_state.client_voice_stop = False

        await self._do_asr_and_publish(audio_data)

    async def _flush_asr_from_buffer(self, audio_data: bytes) -> None:
        """listen(stop) 时将缓冲音频送 ASR（用于 VAD 模式下强制结束）"""
        await self._do_asr_and_publish(audio_data)

    async def _do_asr_and_publish(self, audio_data: bytes) -> None:
        """将音频送 ASR 识别并发布到消息总线"""
        asr_provider = self._channel._asr_provider
        if not asr_provider:
            logger.warning("[{}] ASR Provider 不可用，跳过识别", self.session_id)
            return

        t0 = self._listen_start_time or time.monotonic()
        try:
            text = await asr_provider.recognize(
                audio_data,
                audio_format=self._channel._cfg("audio_format", "opus"),
                sample_rate=16000,
            )
            if text:
                t_asr_done = time.monotonic()
                await self._send_json({
                    "type": MessageType.STT,
                    "text": text,
                    "is_final": True,
                })
                logger.info(
                    "[{}] ⏱ ASR 完成 {:.0f}ms | 结果: {}",
                    self.session_id,
                    (t_asr_done - t0) * 1000,
                    text,
                )
                await self._channel._handle_message(
                    sender_id=self.device_id or "",
                    chat_id=self.device_id or "",
                    content=text,
                    metadata={
                        "device_id": self.device_id,
                        "session_id": self.session_id,
                        "_pipeline_t0": t0,
                    },
                )
                logger.info("[{}] 消息已发布到总线，等待 Agent 回复...", self.session_id)
            else:
                logger.debug("[{}] ASR 未能识别出文本（音频可能无效）", self.session_id)
        except Exception as e:
            logger.warning("[{}] ASR 识别失败: {}", self.session_id, e)
            await self._send_error("asr_failed", str(e))

    async def send_reply(self, msg: OutboundMessage) -> None:
        """发送 Agent 回复给客户端

        1. 发送文本回复
        2. TTS 流式合成 + 下行音频

        延迟埋点：
        - t_reply: Agent 回复到达 Channel
        - t_tts_first: TTS 首个音频帧发出
        - t_tts_done: TTS 发送完成
        """
        logger.info("[{}] send_reply 被调用: channel={}, chat_id={}, content={}",
            self.session_id, msg.channel, msg.chat_id,
            (msg.content or "")[:80])
        if self._ws.state != WsState.OPEN:
            logger.warning("[{}] WebSocket 已关闭，跳过发送", self.session_id)
            return

        self._tts_abort = False
        t_reply = time.monotonic()
        pipeline_t0 = msg.metadata.get("_pipeline_t0") if msg.metadata else None

        # 1. 发送文本回复
        if msg.content:
            await self._send_json({
                "type": MessageType.REPLY,
                "text": msg.content,
            })
            if pipeline_t0:
                logger.info(
                    "[{}] ⏱ Agent→Reply {:.0f}ms (全链路 {:.0f}ms)",
                    self.session_id,
                    (t_reply - pipeline_t0) * 1000,
                    (time.monotonic() - pipeline_t0) * 1000,
                )

        # 2. TTS 流式合成
        tts_provider = self._channel._tts_provider
        if tts_provider and msg.content:
            try:
                await self._send_json({"type": MessageType.TTS, "state": "start"})

                t_tts_first = 0.0
                audio_format = self._channel._cfg("audio_format", "pcm")
                tts_sample_rate = self._channel._cfg("tts_sample_rate", 24000)
                logger.info("[{}] TTS 开始合成: format={}, sample_rate={}", self.session_id, audio_format, tts_sample_rate)
                audio_stream = tts_provider.synthesize(
                    msg.content, audio_format=audio_format, sample_rate=tts_sample_rate
                )
                sent_chunks = 0
                sent_bytes = 0
                async for audio_chunk in audio_stream:
                    if self._tts_abort:
                        logger.info("[{}] TTS 被中止", self.session_id)
                        break
                    if self._ws.state != WsState.OPEN:
                        break
                    sent_chunks += 1
                    sent_bytes += len(audio_chunk)
                    if not t_tts_first:
                        t_tts_first = time.monotonic()
                        logger.info(
                            "[{}] ⏱ TTS 首帧 {:.0f}ms, chunk={} bytes, 前4字节hex={}",
                            self.session_id,
                            (t_tts_first - t_reply) * 1000,
                            len(audio_chunk),
                            audio_chunk[:4].hex(),
                        )
                    await self._ws.send(audio_chunk)
                    await asyncio.sleep(0.001)  # 控制发送速率

                logger.info("[{}] TTS 发送完成: 共 {} 帧, {} bytes", self.session_id, sent_chunks, sent_bytes)
                t_tts_done = time.monotonic()
                await self._send_json({"type": MessageType.TTS, "state": "end"})

                if pipeline_t0:
                    logger.info(
                        "[{}] ⏱ 全链路完成 {:.0f}ms (TTS {:.0f}ms)",
                        self.session_id,
                        (t_tts_done - pipeline_t0) * 1000,
                        (t_tts_done - t_reply) * 1000,
                    )
            except Exception as e:
                logger.exception("[{}] TTS 合成失败: {}", self.session_id, e)

    async def _send_json(self, data: dict[str, Any]) -> None:
        """发送 JSON 消息"""
        if self._ws.state == WsState.OPEN:
            try:
                await self._ws.send(json.dumps(data, ensure_ascii=False))
            except websockets.ConnectionClosed:
                pass

    async def _send_error(self, code: str, message: str) -> None:
        """发送错误消息"""
        await self._send_json({
            "type": MessageType.ERROR,
            "code": code,
            "message": message,
        })

    async def _close(self) -> None:
        """关闭 WebSocket 连接"""
        try:
            await self._ws.close()
        except Exception:
            pass

    async def _check_timeout(self) -> None:
        """定期检查连接活动时间，超时则断开"""
        while True:
            try:
                await asyncio.sleep(30)  # 每 30 秒检查一次
                elapsed = time.monotonic() - self._last_activity
                if elapsed > self._timeout_seconds:
                    logger.info(
                        "[{}] 连接超时（{:.0f}s 无活动），断开",
                        self.session_id, elapsed,
                    )
                    await self._close()
                    break
            except asyncio.CancelledError:
                break

    async def _cleanup(self) -> None:
        """清理连接资源"""
        self._listening = False

        # 释放 VAD 资源（duplex 模式）
        if self._vad_state is not None and self._channel._vad_provider is not None:
            self._channel._vad_provider.release_state(self._vad_state)
            self._vad_state = None

        # 取消 ASR 任务（降级模式）
        if self._asr_task and not self._asr_task.done():
            self._asr_task.cancel()
            try:
                await self._asr_task
            except asyncio.CancelledError:
                pass

        # 取消超时检查
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass

        # 从 Channel 注销
        if self.device_id:
            self._channel._unregister_connection(self.device_id)

        logger.info("[{}] 连接清理完成", self.session_id)


class WebSocketHardwareChannel(BaseChannel):
    """WebSocket 硬件语音通道 — 继承 nanobot BaseChannel

    通过 WebSocket 直连客户端，实现语音双向通信。
    参考 xiaozhi-esp32-server 架构，WebSocket 直连无需中间件。
    """

    name = "websocket_hw"
    display_name = "WebSocket Hardware"

    def __init__(self, config: Any, bus: MessageBus):
        """初始化 WebSocket Channel

        Args:
            config: Channel 配置（dict 或 WebSocketChannelConfig）
        """
        super().__init__(config, bus)

        logger.info("WebSocketHardwareChannel.__init__ 开始，创建 ASR/TTS/VAD Provider...")

        # ASR/TTS/VAD Provider（Channel 内部自建）
        self._asr_provider = self._create_asr_provider()
        self._tts_provider = self._create_tts_provider()
        self._vad_provider = self._create_vad_provider()
        logger.info("ASR Provider: {}, TTS Provider: {}, VAD Provider: {}",
            type(self._asr_provider).__name__ if self._asr_provider else 'None',
            type(self._tts_provider).__name__ if self._tts_provider else 'None',
            type(self._vad_provider).__name__ if self._vad_provider else 'None')

        # 活跃连接映射（device_id -> ConnectionHandler）
        self._connections: dict[str, ConnectionHandler] = {}

        # WebSocket 服务器引用
        self._server: websockets.WebSocketServer | None = None

    def _cfg(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持 dict 和对象两种格式

        Args:
            key: snake_case 格式的键名
            default: 默认值
        """
        if isinstance(self.config, dict):
            parts = key.split("_")
            camel_key = parts[0] + "".join(p.capitalize() for p in parts[1:])
            return self.config.get(key, self.config.get(camel_key, default))
        return getattr(self.config, key, default)

    def is_allowed(self, sender_id: str) -> bool:
        """检查设备是否在白名单中（支持 dict 配置格式）

        覆写 BaseChannel.is_allowed()，因为 dict 配置中键名为 allowFrom（camelCase），
        而 BaseChannel 使用 getattr(config, "allow_from") 只能读 snake_case。
        """
        allow_list = self._cfg("allow_from", [])
        if not allow_list:
            logger.warning("{}: allow_from is empty — all access denied", self.name)
            return False
        if "*" in allow_list:
            return True
        return str(sender_id) in allow_list

    def _create_asr_provider(self) -> Any | None:
        """从全局配置创建 ASR Provider"""
        try:
            from nanobot.config.loader import load_config
            from nanobot.providers.asr import create_asr_provider
            config = load_config()
            logger.info("ASR config: provider={}, app_key={}", config.asr.provider, config.asr.volcengine.app_key)
            provider = create_asr_provider(config.asr)
            logger.info("ASR Provider 创建成功")
            return provider
        except Exception as e:
            logger.warning("ASR Provider 创建失败: {}", e)
            return None

    def _create_tts_provider(self) -> Any | None:
        """从全局配置创建 TTS Provider"""
        try:
            from nanobot.config.loader import load_config
            from nanobot.providers.tts import create_tts_provider
            config = load_config()
            return create_tts_provider(config.tts)
        except Exception as e:
            logger.warning("TTS Provider 创建失败: {}", e)
            return None

    def _create_vad_provider(self) -> Any | None:
        """从全局配置创建 VAD Provider（duplex 模式）"""
        try:
            from nanobot.config.loader import load_config
            from nanobot.providers.vad import create_vad_provider
            config = load_config()
            vad = create_vad_provider(config.vad)
            logger.info("VAD Provider: {}", type(vad).__name__ if vad else "None")
            return vad
        except Exception as e:
            logger.warning("VAD Provider 创建失败: {}", e)
            return None

    async def start(self) -> None:
        """启动 WebSocket 服务器"""
        self._running = True
        host = self._cfg("host", "0.0.0.0")
        port = self._cfg("port", 9000)

        logger.info("WebSocket Channel 启动: ws://{}:{}/", host, port)

        try:
            self._server = await websockets.serve(
                self._handle_connection,
                host,
                port,
                # 连接限制
                max_size=262144,  # 256KB 最大消息大小
            )
            logger.info("WebSocket 服务器已启动，监听 {}:{}", host, port)

            # 保持运行直到被停止
            stop_event = asyncio.Event()
            self._stop_event = stop_event
            await stop_event.wait()

        except Exception as e:
            logger.exception("WebSocket Channel 异常: {}", e)
            raise
        finally:
            self._running = False
            if self._server:
                self._server.close()
                await self._server.wait_closed()

    async def stop(self) -> None:
        """停止 WebSocket 服务器"""
        logger.info("WebSocket Channel 停止中...")
        self._running = False

        # 关闭所有活跃连接
        for device_id, handler in list(self._connections.items()):
            try:
                await handler._close()
            except Exception:
                pass
        self._connections.clear()

        # 通知 start() 退出
        if hasattr(self, "_stop_event"):
            self._stop_event.set()

    async def send(self, msg: OutboundMessage) -> None:
        """发送 Agent 回复到客户端

        Args:
            msg: OutboundMessage，chat_id 即 device_id
        """
        device_id = msg.chat_id
        handler = self._connections.get(device_id)
        if not handler:
            logger.warning("设备 {} 无活跃连接，无法发送", device_id)
            return

        await handler.send_reply(msg)

    async def _handle_connection(
        self,
        websocket: websockets.WebSocketServerProtocol,
    ) -> None:
        """处理新的 WebSocket 连接"""
        # 检查连接数限制
        max_conn = self._cfg("max_connections", 100)
        if len(self._connections) >= max_conn:
            logger.warning("连接数已达上限 {}，拒绝新连接", max_conn)
            await websocket.close(1013, "连接数已满")
            return

        handler = ConnectionHandler(websocket, self)

        try:
            await handler.handle()
        except Exception as e:
            logger.exception("连接处理异常: {}", e)
        finally:
            # 确保连接被清理
            if handler.device_id and handler.device_id in self._connections:
                del self._connections[handler.device_id]

    def _register_connection(self, device_id: str, handler: ConnectionHandler) -> None:
        """注册设备连接（hello 认证成功后调用）"""
        # 如果设备已有连接，踢掉旧连接
        old = self._connections.get(device_id)
        if old:
            logger.info("设备 {} 重复连接，断开旧连接", device_id)
            asyncio.create_task(old._close())
        self._connections[device_id] = handler

    def _unregister_connection(self, device_id: str) -> None:
        """注销设备连接"""
        self._connections.pop(device_id, None)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """返回默认配置（用于 onboard）"""
        return {
            "enabled": False,
            "host": "0.0.0.0",
            "port": 9000,
            "authKey": "",
            "maxConnections": 100,
            "timeoutSeconds": 120,
            "ttsSampleRate": 24000,
            "audioFormat": "pcm",
            "allowFrom": ["*"],
        }
