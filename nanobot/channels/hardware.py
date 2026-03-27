"""Hardware MQTT Channel - 硬件设备 MQTT 语音通道

通过 MQTT 连接 ESP32 等硬件设备，实现音频流的双向传输。
设备通过 MQTT 上传音频帧，后端通过 MQTT 下行 TTS 合成的音频。

Topic 结构：
- device/{device_id}/audio/up     - 上行音频帧 [QoS 0]
- device/{device_id}/audio/down    - 下行音频帧 [QoS 0]
- device/{device_id}/ctrl/up       - 上行控制消息 [QoS 1]
- device/{device_id}/ctrl/down     - 下行控制指令 [QoS 1]
- device/{device_id}/status       - 设备状态上报 [QoS 1]

帧格式（音频帧）：4 字节 Header + Audio Data
- byte[0]: 帧类型标识 (0x01=上行, 0x02=下行)
- byte[1-2]: 序列号 (uint16, big-endian)
- byte[3]: 标志位 (bit0=最后一帧)
"""

from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass
from typing import Any, AsyncIterator

import aiomqtt
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import HardwareChannelConfig


# MQTT 帧类型标识
FRAME_TYPE_UP = 0x01  # 上行音频帧
FRAME_TYPE_DOWN = 0x02  # 下行音频帧
# 标志位
FRAME_FLAG_LAST = 0x01  # 最后一帧


@dataclass
class AudioFrame:
    """MQTT 音频帧"""

    frame_type: int  # 0x01=上行, 0x02=下行
    seq: int  # 序列号
    is_last: bool  # 是否最后一帧
    data: bytes  # 音频数据（不含 Header）


@dataclass
class CtrlMessage:
    """控制消息"""

    device_id: str
    msg_type: str  # audio_start, audio_end, reply_start, reply_end, text, error, playback_control
    payload: dict[str, Any]


@dataclass
class DeviceStatus:
    """设备状态"""

    device_id: str
    status: str  # online, offline
    battery: int | None = None
    signal: int | None = None
    wifi_rssi: int | None = None
    firmware: str | None = None
    uptime: int | None = None
    ts: int | None = None


class HardwareChannel(BaseChannel):
    """硬件 MQTT Channel - 继承 nanobot BaseChannel

    通过 MQTT 连接硬件设备，实现语音双向通信。
    内部集成 ASR/TTS Provider 调用火山引擎进行语音识别和合成。
    """

    name = "hardware"
    display_name = "Hardware MQTT"

    def __init__(self, config: Any, bus: MessageBus, asr_provider: Any = None, tts_provider: Any = None):
        """
        初始化 Hardware Channel。

        Args:
            config: Hardware Channel 配置（dict 或 HardwareChannelConfig）
            bus: 消息总线
            asr_provider: ASR Provider 实例（用于语音识别）
            tts_provider: TTS Provider 实例（用于语音合成）
        """
        super().__init__(config, bus)
        self._mqtt_client: aiomqtt.Client | None = None
        self._running = False
        self._stop_event = asyncio.Event()

        # ASR/TTS Provider（可选，Channel 可独立运行）
        # 如果未提供，尝试从全局配置创建
        if asr_provider is None:
            asr_provider = self._create_asr_provider()
        if tts_provider is None:
            tts_provider = self._create_tts_provider()
        self._asr_provider = asr_provider
        self._tts_provider = tts_provider
        # 设备音频缓冲（device_id -> list of AudioFrame）
        self._audio_buffers: dict[str, list[AudioFrame]] = {}
        # 设备会话状态（device_id -> dict）
        self._sessions: dict[str, dict[str, Any]] = {}

    def _cfg(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持 dict 和对象两种格式

        Args:
            key: snake_case 格式的键名（如 mqtt_host）
            default: 默认值
        """
        if isinstance(self.config, dict):
            # snake_case -> camelCase 转换
            parts = key.split("_")
            camel_key = parts[0] + "".join(p.capitalize() for p in parts[1:])
            return self.config.get(key, self.config.get(camel_key, default))
        return getattr(self.config, key, default)

    def _create_asr_provider(self) -> Any | None:
        """从全局配置创建 ASR Provider"""
        try:
            from nanobot.config.loader import load_config
            from nanobot.providers.asr import create_asr_provider
            config = load_config()
            return create_asr_provider(config.asr)
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

    async def start(self) -> None:
        """启动 MQTT Channel，连接到 Broker 并订阅设备 Topic"""
        self._running = True
        self._stop_event.clear()
        logger.info("Hardware Channel 启动中...")

        try:
            # 生成唯一的 Client ID（服务器端使用固定前缀）
            import uuid
            client_id = f"minibot_server_{uuid.uuid4().hex[:8]}"

            async with aiomqtt.Client(
                identifier=client_id,
                hostname=self._cfg("mqtt_host", "localhost"),
                port=self._cfg("mqtt_port", 1883),
                username=self._cfg("mqtt_username") or None,
                password=self._cfg("mqtt_password") or None,
                # TLS 支持
                transport="tcp",  # aiomqtt 支持 TLS 时使用 tls_context
                # Keep Alive
                keepalive=60,
                # Clean Session: False 以支持持久会话（断线重连后恢复订阅）
                clean_session=False,
            ) as client:
                self._mqtt_client = client
                logger.info(
                    "MQTT 连接成功，Broker: {}:{}",
                    self._cfg("mqtt_host"),
                    self._cfg("mqtt_port"),
                )

                # 订阅设备 Topic（通配符订阅）
                await client.subscribe("device/+/audio/up", qos=0)
                await client.subscribe("device/+/audio/down", qos=0)
                await client.subscribe("device/+/ctrl/up", qos=1)
                await client.subscribe("device/+/status", qos=1)
                logger.info("已订阅设备 Topic: device/+/audio/up, device/+/ctrl/up, device/+/status")

                # 消息循环
                async for message in client.messages:
                    if not self._running:
                        break
                    try:
                        await self._dispatch_message(message)
                    except Exception as e:
                        logger.exception("处理 MQTT 消息失败: {}", e)

        except asyncio.CancelledError:
            logger.info("Hardware Channel 取消")
        except Exception as e:
            logger.exception("Hardware Channel 异常退出: {}", e)
            raise
        finally:
            self._running = False

    async def stop(self) -> None:
        """停止 MQTT Channel"""
        logger.info("Hardware Channel 停止中...")
        self._running = False
        self._stop_event.set()

    async def send(self, msg: OutboundMessage) -> None:
        """通过 MQTT 发送消息（Agent 回复 → TTS → MQTT 下行）

        Args:
            msg: OutboundMessage 包含回复内容和元数据
        """
        if not self._mqtt_client or not self._running:
            logger.warning("MQTT 未连接，无法发送消息")
            return

        device_id = msg.chat_id  # chat_id 即 device_id
        if not self.is_allowed(device_id):
            logger.warning("设备 {} 未授权，拒绝发送", device_id)
            return

        # 1. 发送 reply_start 控制消息
        await self._publish_ctrl(
            device_id,
            {"type": "reply_start", "format": self._cfg("audio_format", "opus"), "sample_rate": 24000, "channels": 1},
            qos=1,
        )

        # 2. TTS 流式合成 + MQTT 音频下行
        if self._tts_provider and msg.content:
            try:
                audio_stream = self._tts_provider.synthesize(msg.content)
                seq = 0
                async for audio_chunk in audio_stream:
                    is_last = len(audio_chunk) < 2048  # 简单判断：小于 2048 字节视为最后一块
                    await self._publish_audio(device_id, audio_chunk, seq, is_last, qos=0)
                    seq += 1
                    # 小延迟避免发送过快
                    await asyncio.sleep(0.001)
            except Exception as e:
                logger.exception("TTS 合成失败: {}", e)

        # 3. 发送 reply_end 控制消息
        await self._publish_ctrl(device_id, {"type": "reply_end"}, qos=1)

    async def send_text(self, device_id: str, text: str) -> None:
        """发送文本消息到设备

        Args:
            device_id: 设备 ID
            text: 文本内容
        """
        if not self._mqtt_client or not self._running:
            logger.warning("MQTT 未连接，无法发送文本")
            return

        if not self.is_allowed(device_id):
            logger.warning("设备 {} 未授权", device_id)
            return

        await self._publish_ctrl(
            device_id,
            {"type": "text", "content": text},
            qos=1,
        )

    # ==================== 内部方法 ====================

    async def _dispatch_message(self, message: aiomqtt.Message) -> None:
        """分发 MQTT 消息到对应处理器

        Args:
            message: MQTT 消息
        """
        topic_str = str(message.topic)
        topic_parts = topic_str.split("/")

        if len(topic_parts) < 3:
            logger.warning("无效 Topic 格式: {}", topic_str)
            return

        # device/{device_id}/{category}[/{subcategory}]
        device_id = topic_parts[1]
        category = topic_parts[2]

        # 使用 BaseChannel.is_allowed() 验证设备白名单
        if not self.is_allowed(device_id):
            logger.warning("未授权设备: {}", device_id)
            await self._publish_error(device_id, "auth_failed", "设备未授权")
            return

        if category == "audio":
            await self._handle_audio(device_id, bytes(message.payload))
        elif category == "ctrl":
            await self._handle_ctrl(device_id, topic_parts, message.payload)
        elif category == "status":
            await self._handle_status(device_id, bytes(message.payload))

    async def _handle_audio(self, device_id: str, payload: bytes) -> None:
        """处理音频帧

        Args:
            device_id: 设备 ID
            payload: MQTT 音频帧载荷（4 字节 Header + Audio Data）
        """
        if len(payload) < 4:
            logger.warning("音频帧太短: {} bytes", len(payload))
            return

        # 解析 Header
        frame_type = payload[0]
        seq = struct.unpack(">H", payload[1:3])[0]  # big-endian uint16
        flags = payload[3]
        is_last = bool(flags & FRAME_FLAG_LAST)
        audio_data = payload[4:]

        frame = AudioFrame(frame_type=frame_type, seq=seq, is_last=is_last, data=audio_data)

        # 缓冲音频帧
        if device_id not in self._audio_buffers:
            self._audio_buffers[device_id] = []
        self._audio_buffers[device_id].append(frame)

        # 如果是最后一帧，处理完整音频
        if is_last:
            await self._process_audio(device_id)

    async def _process_audio(self, device_id: str) -> None:
        """处理完整的音频数据（audio_end 时调用）

        Args:
            device_id: 设备 ID
        """
        frames = self._audio_buffers.get(device_id, [])
        if not frames:
            return

        # 按序列号排序
        frames.sort(key=lambda f: f.seq)
        # 合并音频数据
        audio_data = b"".join(f.data for f in frames)
        # 清理缓冲
        del self._audio_buffers[device_id][:]

        logger.debug("设备 {} 收到音频数据: {} bytes, {} 帧", device_id, len(audio_data), len(frames))

        # 如果配置了 ASR Provider，进行语音识别
        if self._asr_provider:
            try:
                text = await self._asr_provider.recognize(audio_data)
                if text:
                    logger.info("ASR 识别结果: {}", text)
                    # 发送到消息总线
                    await self._handle_message(
                        sender_id=device_id,
                        chat_id=device_id,
                        content=text,
                        metadata={"device_id": device_id, "audio_frames": len(frames)},
                    )
            except Exception as e:
                logger.exception("ASR 识别失败: {}", e)
                await self._publish_error(device_id, "asr_failed", f"语音识别失败: {e}")

    async def _handle_ctrl(self, device_id: str, topic_parts: list[str], payload: bytes) -> None:
        """处理控制消息

        Args:
            device_id: 设备 ID
            topic_parts: Topic 路径
            payload: MQTT 消息载荷
        """
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("控制消息 JSON 解析失败: {}", e)
            return

        msg_type = data.get("type", "")
        logger.debug("设备 {} 控制消息: {}", device_id, msg_type)

        if msg_type == "audio_start":
            # 设备开始录音，初始化会话
            self._sessions[device_id] = {
                "format": data.get("format", "opus"),
                "sample_rate": data.get("sample_rate", 16000),
                "channels": data.get("channels", 1),
                "start_ts": data.get("ts"),
            }
            logger.info("设备 {} 开始录音", device_id)

        elif msg_type == "audio_end":
            # 设备结束录音，处理完整音频
            session = self._sessions.get(device_id)
            if session and self._audio_buffers.get(device_id):
                await self._process_audio(device_id)
            if device_id in self._sessions:
                del self._sessions[device_id]
            logger.info("设备 {} 录音结束", device_id)

        elif msg_type == "playback_control":
            # 播放控制（暂停/继续等）
            action = data.get("action", "")
            logger.info("设备 {} 播放控制: {}", device_id, action)

        else:
            logger.warning("未知控制消息类型: {}", msg_type)

    async def _handle_status(self, device_id: str, payload: bytes) -> None:
        """处理设备状态上报

        Args:
            device_id: 设备 ID
            payload: 状态消息载荷（JSON）
        """
        try:
            data = json.loads(payload.decode("utf-8"))
            status = DeviceStatus(
                device_id=device_id,
                status=data.get("status", "unknown"),
                battery=data.get("battery"),
                signal=data.get("signal"),
                wifi_rssi=data.get("wifi_rssi"),
                firmware=data.get("firmware"),
                uptime=data.get("uptime"),
                ts=data.get("ts"),
            )
            logger.info("设备状态: {}", status)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("状态消息解析失败: {}", e)

    async def _publish_audio(
        self, device_id: str, audio_data: bytes, seq: int, is_last: bool, qos: int = 0
    ) -> None:
        """发布下行音频帧

        Args:
            device_id: 设备 ID
            audio_data: 音频数据
            seq: 序列号
            is_last: 是否最后一帧
            qos: QoS 级别
        """
        if not self._mqtt_client:
            return

        # 组装帧：4 字节 Header + Audio Data
        flags = FRAME_FLAG_LAST if is_last else 0
        header = bytes([FRAME_TYPE_DOWN, (seq >> 8) & 0xFF, seq & 0xFF, flags])
        payload = header + audio_data

        topic = f"device/{device_id}/audio/down"
        try:
            await self._mqtt_client.publish(topic, payload, qos=qos)
        except Exception as e:
            logger.warning("发布音频帧失败: {}", e)

    async def _publish_ctrl(self, device_id: str, data: dict[str, Any], qos: int = 1) -> None:
        """发布控制消息

        Args:
            device_id: 设备 ID
            data: 控制消息数据
            qos: QoS 级别
        """
        if not self._mqtt_client:
            return

        topic = f"device/{device_id}/ctrl/down"
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            await self._mqtt_client.publish(topic, payload, qos=qos)
        except Exception as e:
            logger.warning("发布控制消息失败: {}", e)

    async def _publish_error(self, device_id: str, code: str, message: str) -> None:
        """发布错误消息到设备

        Args:
            device_id: 设备 ID
            code: 错误码
            message: 错误信息
        """
        await self._publish_ctrl(
            device_id,
            {"type": "error", "code": code, "message": message},
            qos=1,
        )

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """返回默认配置（用于 onboard）"""
        return {
            "enabled": False,
            "mqtt_host": "localhost",
            "mqtt_port": 1883,
            "mqtt_username": "",
            "mqtt_password": "",
            "mqtt_tls": False,
            "audio_format": "opus",
            "max_devices": 100,
            "allow_from": ["*"],
        }
