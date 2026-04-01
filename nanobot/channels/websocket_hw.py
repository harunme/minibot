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
from typing import Any

import websockets
from loguru import logger
from websockets.protocol import State as WsState

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.music_player import MusicPlayer
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
    MUSIC = "music"


class ConnectionHandler:
    """WebSocket 连接处理器 — 每个客户端连接对应一个实例

    管理单个连接的生命周期：认证、音频缓冲、ASR流式识别、TTS下行。
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
        # ASR flush 锁，防止并发多次 _flush_asr 耗尽并发配额
        self._asr_flush_lock: asyncio.Lock = asyncio.Lock()
        # 静默超时兜底：记录最后有声帧时刻，用于静默超时强制送 ASR
        self._last_voice_frame_time: float = 0.0

        # VAD 状态（duplex 模式下由 VADProvider.create_state() 创建）
        self._vad_state: VADState | None = None
        # VAD 已发送结束信号（防止重复触发）
        self._vad_sent_end: bool = False

        # ASR Provider（每个 ConnectionHandler 独立实例，避免多连接结果串扰）
        self._asr_provider = self._channel._create_asr_provider()
        # TTS Provider（Channel 级别共享）
        self._tts_provider = self._channel._tts_provider

        # TTS 中止标志
        self._tts_abort: bool = False
        # TTS 播放中标志（用于打断检测，与 xiaozhi client_is_speaking 对齐）
        self._client_is_speaking: bool = False
        # 打断标志（由用户说话触发或客户端 abort 命令触发）
        self._client_abort: bool = False

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

        xiaozhi STREAM 模式对齐：每帧解码后直接送 ASR WebSocket，
        不等待 buffer 积累。VAD 只负责打断检测（client_voice_stop）。
        """
        if not self.authenticated:
            return

        if not self._listening:
            logger.debug("[{}] 收到音频但未在监听状态，忽略", self.session_id)
            return

        # ASR task 自重启：上一轮完成后，新音频帧进来时拉起下一轮
        # 主动建立 ASR 连接，确保 receive_audio 调用时连接已就绪，
        # 消除"旧 task 退出 → 新音频帧到达 → receive_audio 因 _stream_ws=None
        # 静默跳过 → 音频丢失"的竞争窗口。
        if self._asr_task is not None and self._asr_task.done():
            self._vad_sent_end = False
            if self._vad_state is not None:
                self._vad_state.client_voice_stop = False
                self._vad_state.client_have_voice = False
                self._vad_state.last_is_voice = False
                self._vad_state.voice_window.clear()
                self._vad_state.audio_buffer.clear()
                self._vad_state.last_activity_time_ms = time.monotonic() * 1000
            # 先主动建连，再启动 task（receive_audio 的双检查机制保证不重复建连）
            try:
                await self._asr_provider._stream_ws_connect()
            except Exception:
                pass
            self._asr_task = asyncio.create_task(self._run_asr())

        vad_provider = self._channel._vad_provider
        vad_state = self._vad_state

        if self._asr_provider is None:
            return

        audio_format = self._channel._cfg("audio_format", "pcm")

        if vad_provider is not None and vad_state is not None:
            # VAD 实时推理：更新 client_have_voice / client_voice_stop
            vad_provider.is_vad(vad_state, data, audio_format=audio_format)

            # 打断检测：用户开始说话 + TTS 正在播放 → 触发打断（与 xiaozhi 对齐）
            if vad_state.client_have_voice and self._client_is_speaking:
                logger.info("[{}] 检测到用户说话打断 TTS", self.session_id)
                self._client_abort = True
                self._client_is_speaking = False
                self._tts_abort = True
                await self._send_json({"type": MessageType.TTS, "state": "stop"})

        # 每帧直接送 ASR（xiaozhi 风格：帧到即发）
        await self._asr_provider.receive_audio(data, audio_format=audio_format)

        # VAD 检测到说完时：发结束帧触发 ASR 最终结果
        if vad_provider is not None and vad_state is not None:
            if vad_state.client_voice_stop and not self._vad_sent_end:
                if not self._asr_flush_lock.locked():
                    async with self._asr_flush_lock:
                        if vad_state.client_voice_stop and not self._vad_sent_end:
                            self._vad_sent_end = True
                            logger.debug("[{}] VAD 检测到说完，发送 ASR 结束帧", self.session_id)
                            await self._asr_provider._send_stop()
                            # 重置 VAD 状态，为下一轮做准备
                            vad_state.client_voice_stop = False

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

        # 发送握手响应（告知客户端 TTS 输出格式及 VAD 配置）
        tts_sample_rate = self._channel._cfg("tts_sample_rate", 24000)
        vad_enabled = self._channel._vad_provider is not None
        await self._send_json({
            "type": MessageType.HELLO,
            "session_id": self.session_id,
            "audio_params": {
                # TTS 输出固定为 PCM 格式（浏览器可原生播放）
                "format": "pcm",
                "sample_rate": tts_sample_rate,
            },
            "vad": vad_enabled,
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

            # 等待上一次 ASR 任务完成
            if self._asr_task and not self._asr_task.done():
                logger.info("[{}] 等待上一次 ASR 任务结束...", self.session_id)
                try:
                    await asyncio.wait_for(self._asr_task, timeout=3.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    logger.warning("[{}] 上一次 ASR 任务超时，强制取消", self.session_id)
                    self._asr_task.cancel()
                    try:
                        await self._asr_task
                    except asyncio.CancelledError:
                        pass

            self._listening = True
            self._listen_start_time = time.monotonic()
            self._vad_sent_end = False

            # 清空 ASR 结果队列（遗留）
            while not self._asr_audio_queue.empty():
                try:
                    self._asr_audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            # 启动 ASR 结果消费任务（从持久 WebSocket 接收流式结果）
            self._asr_task = asyncio.create_task(self._run_asr())

            # 初始化 VAD 状态
            vad_provider = self._channel._vad_provider
            if vad_provider is not None:
                self._vad_state = vad_provider.create_state()
                logger.info("[{}] 开始语音监听（VAD 流式模式）", self.session_id)
            else:
                self._vad_state = None
                logger.info("[{}] 开始语音监听（无 VAD）", self.session_id)

        elif mode == "stop":
            if not self._listening:
                return

            # 发 ASR 结束帧，触发最终结果；并将 _listening 置 False，
            # 防止客户端在等待结果期间继续发音频被错误处理。
            self._listening = False
            asr_provider = self._asr_provider
            if asr_provider is not None:
                await asr_provider._send_stop()

            logger.info("[{}] 停止语音监听（等待 ASR 最终结果）", self.session_id)

        else:
            logger.warning("[{}] 无效的 listen mode: {}", self.session_id, mode)

    async def _handle_abort(self) -> None:
        """处理中止命令：停止当前 TTS 播放（与 xiaozhi handleAbortMessage 对齐）"""
        logger.info("[{}] 收到 abort 命令", self.session_id)
        self._client_abort = True
        self._client_is_speaking = False
        self._tts_abort = True
        await self._send_json({"type": MessageType.TTS, "state": "stop"})
        logger.info("[{}] abort 处理完成", self.session_id)

    async def _run_asr(self) -> None:
        """消费 ASR 流式结果（xiaozhi STREAM 模式）

        通过 asr_provider.stream_results() 异步迭代器，监听 ASR 持久 WebSocket 的结果。
        - is_final=True 的 utterance（definite）→ 发送最终 STT + 发布到消息总线
        - is_final=False 的中间结果 → 发送 partial STT 给客户端（可选）
        """
        asr_provider = self._asr_provider
        if not asr_provider:
            await self._send_error("asr_unavailable", "ASR 服务不可用")
            return

        t0 = self._listen_start_time or time.monotonic()
        result_received = False

        try:
            async for result in asr_provider.stream_results():
                text = result.get("text", "")
                is_final = result.get("is_final", False)

                if not text:
                    continue

                if not is_final:
                    # 中间结果：实时推送 partial STT
                    await self._send_json({
                        "type": MessageType.STT,
                        "text": text,
                        "is_final": False,
                    })
                else:
                    # 最终结果（definite）：发送 STT + 发布消息总线
                    result_received = True
                    t_asr_done = time.monotonic()
                    await self._send_json({
                        "type": MessageType.STT,
                        "text": text,
                        "is_final": True,
                    })
                    logger.info(
                        "[{}] ⏱ ASR 最终结果 {:.0f}ms | text={}",
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
                    # 新一轮对话开始，清除打断状态，防止上一轮的 _client_abort 残留导致 skip TTS
                    self._client_abort = False
                    self._client_is_speaking = False
                    logger.info("[{}] 消息已发布到总线，等待 Agent 回复...", self.session_id)
                    # 最终结果收到后退出，ASR WS 连接由下一轮 listen(start) 重建
                    break

        except asyncio.CancelledError:
            logger.debug("[{}] ASR 任务被取消", self.session_id)
        except Exception as e:
            logger.exception("[{}] ASR 结果消费失败: {}", self.session_id, e)
            if not result_received:
                await self._send_error("asr_failed", f"语音识别失败: {e}")

    async def _flush_asr(self) -> None:
        """VAD 检测到说完，触发 ASR 单次识别（调用方已持有 _asr_flush_lock）"""
        vad_state = self._vad_state
        if vad_state is None or not vad_state.audio_buffer:
            return

        audio_data = bytes(vad_state.audio_buffer)
        vad_state.audio_buffer.clear()

        # 最小音频阈值：低于512 bytes不送ASR
        # 修复：统一代码/注释/日志阈值，消除逻辑混乱
        if len(audio_data) < 512:
            logger.debug(
                "[{}] 音频太短（{} bytes < 512），跳过 ASR",
                self.session_id,
                len(audio_data),
            )
            return

        await self._do_asr_and_publish(audio_data)

    async def _flush_asr_from_buffer(self, audio_data: bytes) -> None:
        """listen(stop) 时将缓冲音频送 ASR（用于 VAD 模式下强制结束）"""
        await self._do_asr_and_publish(audio_data)

    async def _do_asr_and_publish(self, audio_data: bytes) -> None:
        """将音频送 ASR 识别并发布到消息总线"""
        asr_provider = self._asr_provider
        if not asr_provider:
            logger.warning("[{}] ASR Provider 不可用，跳过识别", self.session_id)
            return

        audio_format = self._channel._cfg("audio_format", "pcm")
        logger.debug(
            "[{}] ASR 送识: len={} bytes, format={}",
            self.session_id,
            len(audio_data),
            audio_format,
        )

        t0 = self._listen_start_time or time.monotonic()
        # 修复：提前初始化last_err，防止未定义变量错误
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                text = await asr_provider.recognize(
                    audio_data,
                    audio_format=audio_format,
                    _sample_rate=16000,
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
                return
            except Exception as e:
                err_str = str(e)
                # 45000292 = 火山引擎 ASR 并发配额超限，等待后重试
                if "45000292" in err_str or "quota" in err_str.lower():
                    wait = 2 ** attempt
                    logger.warning(
                        "[{}] ASR 并发配额超限（{}/3），等待 {}s 后重试",
                        self.session_id,
                        attempt + 1,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    last_err = e
                    continue
                else:
                    last_err = e
                    break

        # 所有重试均失败
        logger.warning("[{}] ASR 识别失败: {}", self.session_id, last_err)
        await self._send_error("asr_failed", str(last_err))

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
        # 如果被用户打断过，跳过 TTS
        if self._client_abort:
            logger.info("[{}] TTS 被跳过（已收到打断信号）", self.session_id)
            self._client_abort = False
            return
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
            # 通知客户端 TTS 开始，客户端进入说话中状态
            await self._send_json({"type": MessageType.TTS, "state": "start"})
            self._client_is_speaking = True
            self._tts_abort = False
            try:

                t_tts_first = 0.0
                tts_sample_rate = self._channel._cfg("tts_sample_rate", 24000)
                logger.info("[{}] TTS 开始合成: format=pcm, sample_rate={}", self.session_id, tts_sample_rate)
                audio_stream = tts_provider.synthesize(
                    msg.content, audio_format="pcm", sample_rate=tts_sample_rate
                )
                sent_chunks = 0
                sent_bytes = 0
                async for audio_chunk in audio_stream:
                    if self._tts_abort:
                        logger.info("[{}] TTS 被中止", self.session_id)
                        self._client_is_speaking = False
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
                    # 修复：调整TTS发送间隔，1ms过短→5ms，避免网络拥塞
                    await asyncio.sleep(0.005)

                logger.info("[{}] TTS 发送完成: 共 {} 帧, {} bytes", self.session_id, sent_chunks, sent_bytes)
                t_tts_done = time.monotonic()
                self._client_is_speaking = False
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

        # 3. 音乐播放（msg.metadata["music"] = MP3 文件路径）
        music_path = msg.metadata.get("music") if msg.metadata else None
        if music_path:
            await self._stream_music(music_path)

    async def _stream_music(self, mp3_path: str) -> None:
        """通过 WebSocket 发送音乐 PCM 流到客户端。

        发送流程：music start(JSON) → PCM chunks(二进制) → music end(JSON)
        """
        if self._ws.state != WsState.OPEN:
            logger.warning("[{}] WebSocket 已关闭，跳过音乐播放", self.session_id)
            return
        tts_sample_rate = self._channel._cfg("tts_sample_rate", 24000)
        player = MusicPlayer(sample_rate=tts_sample_rate)
        await self._send_json({"type": MessageType.MUSIC, "state": "start"})
        self._client_is_speaking = True
        try:
            sent_bytes = 0
            chunk_count = 0
            async for pcm_chunk in player.stream(mp3_path):
                if self._ws.state != WsState.OPEN:
                    break
                await self._ws.send(pcm_chunk)
                sent_bytes += len(pcm_chunk)
                chunk_count += 1
                # 复用 TTS 的节流策略，避免网络拥塞
                await asyncio.sleep(0.005)
            logger.info("[{}] 音乐播放完成: {} chunks, {} bytes", self.session_id, chunk_count, sent_bytes)
        except Exception as e:
            logger.exception("[{}] 音乐播放失败: {}", self.session_id, e)
        finally:
            self._client_is_speaking = False
            if self._ws.state == WsState.OPEN:
                await self._send_json({"type": MessageType.MUSIC, "state": "end"})

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
        self._client_is_speaking = False
        self._client_abort = False

        # 关闭本连接的 ASR 流式 WebSocket（Provider 本身保留供其他连接复用）
        asr_provider = self._asr_provider
        if asr_provider is not None:
            await asr_provider._close_stream_ws()

        # 释放 VAD 资源
        if self._vad_state is not None and self._channel._vad_provider is not None:
            self._channel._vad_provider.release_state(self._vad_state)
            self._vad_state = None

        # 取消 ASR 结果消费任务
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
        # 修复：初始化_running属性，防止AttributeError
        self._running = False

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
        # 修复：简化配置读取，移除冗余驼峰转换，兼容snake_case/驼峰
        if isinstance(self.config, dict):
            return self.config.get(key, self.config.get(key.replace("_", ""), default))
        return getattr(self.config, key, default)

    def is_allowed(self, sender_id: str) -> bool:
        return True
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
        for _device_id, handler in list(self._connections.items()):
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
            # 修复：删除冗余注销逻辑，统一由_cleanup处理
            pass

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
