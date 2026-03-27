"""Hardware MQTT Channel 测试"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.channels.hardware import (
    AudioFrame,
    FRAME_FLAG_LAST,
    FRAME_TYPE_DOWN,
    FRAME_TYPE_UP,
    HardwareChannel,
)
from nanobot.config.schema import HardwareChannelConfig


def _make_audio_header(frame_type: int, seq: int, flags: int) -> bytes:
    """构建 4 字节音频帧头

    与 _handle_audio 的解析逻辑一致：
    - byte[0]: 帧类型
    - byte[1-2]: 序列号 (big-endian uint16)
    - byte[3]: 标志位
    """
    return bytes([frame_type, (seq >> 8) & 0xFF, seq & 0xFF, flags])


class TestAudioFrame:
    """AudioFrame 数据类测试"""

    def test_frame_creation(self):
        """测试音频帧创建"""
        frame = AudioFrame(
            frame_type=FRAME_TYPE_UP,
            seq=100,
            is_last=True,
            data=b"\x00\x01\x02\x03",
        )
        assert frame.frame_type == FRAME_TYPE_UP
        assert frame.seq == 100
        assert frame.is_last is True
        assert frame.data == b"\x00\x01\x02\x03"


class TestHardwareChannel:
    """Hardware MQTT Channel 测试"""

    @pytest.fixture
    def config(self):
        """测试配置"""
        return HardwareChannelConfig(
            enabled=True,
            mqtt_host="localhost",
            mqtt_port=1883,
            mqtt_username="testuser",
            mqtt_password="testpass",
            audio_format="opus",
            max_devices=100,
            allow_from=["*"],
        )

    @pytest.fixture
    def mock_bus(self):
        """Mock 消息总线"""
        bus = MagicMock()
        bus.publish_inbound = AsyncMock()
        return bus

    @pytest.fixture
    def channel(self, config, mock_bus):
        """创建 Channel 实例"""
        return HardwareChannel(config, mock_bus)

    def test_init(self, channel, config, mock_bus):
        """测试初始化"""
        assert channel.config == config
        assert channel.bus == mock_bus
        assert channel.name == "hardware"
        assert channel.display_name == "Hardware MQTT"
        assert channel._mqtt_client is None
        assert channel._running is False

    def test_config_property(self, channel, config):
        """测试 config 属性"""
        assert channel.config == config

    def test_is_allowed_star(self, channel):
        """测试通配符白名单"""
        assert channel.is_allowed("any_device_id") is True

    def test_is_allowed_specific(self, channel):
        """测试特定设备白名单"""
        channel.config.allow_from = ["device001", "device002"]
        assert channel.is_allowed("device001") is True
        assert channel.is_allowed("device002") is True
        assert channel.is_allowed("device003") is False

    def test_default_config(self):
        """测试默认配置"""
        config = HardwareChannel.default_config()
        assert config["enabled"] is False
        assert config["mqtt_host"] == "localhost"
        assert config["mqtt_port"] == 1883
        assert config["allow_from"] == ["*"]

    @pytest.mark.asyncio
    async def test_session_management(self):
        """测试会话管理"""
        config = HardwareChannelConfig(enabled=True, allow_from=["*"])
        channel = HardwareChannel(config, MagicMock())

        device_id = "test_device"
        await channel._handle_ctrl(
            device_id,
            ["device", device_id, "ctrl", "up"],
            json.dumps({
                "type": "audio_start",
                "format": "opus",
                "sample_rate": 16000,
            }).encode(),
        )
        assert device_id in channel._sessions
        assert channel._sessions[device_id]["format"] == "opus"

    @pytest.mark.asyncio
    async def test_audio_buffer_not_last(self):
        """测试音频缓冲（非最后一帧，不应立即处理）"""
        config = HardwareChannelConfig(enabled=True, allow_from=["*"])
        channel = HardwareChannel(config, MagicMock())

        device_id = "test_device"
        # 模拟 audio_start
        await channel._handle_ctrl(
            device_id,
            ["device", device_id, "ctrl", "up"],
            json.dumps({"type": "audio_start"}).encode(),
        )

        # 模拟音频帧（is_last=False）
        audio_data = b"\x00\x01\x02\x03\x04\x05"
        header = _make_audio_header(FRAME_TYPE_UP, seq=1, flags=0)  # is_last=False
        frame_payload = header + audio_data

        await channel._handle_audio(device_id, frame_payload)

        # 非最后一帧应该缓冲，不调用 _process_audio
        assert device_id in channel._audio_buffers
        assert len(channel._audio_buffers[device_id]) == 1

    @pytest.mark.asyncio
    async def test_audio_buffer_is_last(self):
        """测试音频缓冲（最后一帧，应触发处理）"""
        config = HardwareChannelConfig(enabled=True, allow_from=["*"])
        channel = HardwareChannel(config, MagicMock())

        device_id = "test_device"
        # 模拟 audio_start
        await channel._handle_ctrl(
            device_id,
            ["device", device_id, "ctrl", "up"],
            json.dumps({"type": "audio_start"}).encode(),
        )

        # 模拟音频帧（is_last=True）
        audio_data = b"\x00\x01\x02\x03\x04\x05"
        header = _make_audio_header(FRAME_TYPE_UP, seq=1, flags=FRAME_FLAG_LAST)
        frame_payload = header + audio_data

        # Mock ASR provider to avoid actual API call
        channel._asr_provider = MagicMock()
        channel._asr_provider.recognize = AsyncMock(return_value=None)

        await channel._handle_audio(device_id, frame_payload)

        # 最后一帧，处理后缓冲被清空
        assert device_id not in channel._audio_buffers or len(channel._audio_buffers[device_id]) == 0

    @pytest.mark.asyncio
    async def test_stop(self, channel):
        """测试停止"""
        channel._running = True
        await channel.stop()
        assert channel._running is False
        assert channel._stop_event.is_set()


class TestHardwareChannelPublish:
    """Hardware Channel 发布功能测试"""

    @pytest.fixture
    def channel(self):
        """创建带 Mock MQTT Client 的 Channel"""
        config = HardwareChannelConfig(
            enabled=True,
            mqtt_host="localhost",
            mqtt_port=1883,
        )
        mock_bus = MagicMock()
        ch = HardwareChannel(config, mock_bus)

        # Mock MQTT Client
        ch._mqtt_client = MagicMock()
        ch._mqtt_client.publish = AsyncMock()
        ch._running = True

        return ch

    @pytest.mark.asyncio
    async def test_publish_audio(self, channel):
        """测试发布音频帧"""
        await channel._publish_audio(
            device_id="test_device",
            audio_data=b"\x00\x01\x02\x03",
            seq=1,
            is_last=False,
            qos=0,
        )
        channel._mqtt_client.publish.assert_called_once()
        call_args = channel._mqtt_client.publish.call_args
        assert call_args[0][0] == "device/test_device/audio/down"
        assert call_args[1]["qos"] == 0

    @pytest.mark.asyncio
    async def test_publish_audio_last_frame(self, channel):
        """测试发布最后一帧"""
        await channel._publish_audio(
            device_id="test_device",
            audio_data=b"\x00\x01\x02\x03",
            seq=10,
            is_last=True,
            qos=0,
        )
        call_args = channel._mqtt_client.publish.call_args
        payload = call_args[0][1]
        # 最后一帧的标志位应该设置
        assert payload[3] & FRAME_FLAG_LAST

    @pytest.mark.asyncio
    async def test_publish_ctrl(self, channel):
        """测试发布控制消息"""
        await channel._publish_ctrl(
            device_id="test_device",
            data={"type": "text", "content": "Hello"},
            qos=1,
        )
        channel._mqtt_client.publish.assert_called_once()
        call_args = channel._mqtt_client.publish.call_args
        assert call_args[0][0] == "device/test_device/ctrl/down"
        assert call_args[1]["qos"] == 1
        # 验证 JSON 格式
        payload = json.loads(call_args[0][1].decode())
        assert payload["type"] == "text"
        assert payload["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_publish_error(self, channel):
        """测试发布错误消息"""
        await channel._publish_error("test_device", "auth_failed", "设备未授权")
        call_args = channel._mqtt_client.publish.call_args
        payload = json.loads(call_args[0][1].decode())
        assert payload["type"] == "error"
        assert payload["code"] == "auth_failed"
        assert payload["message"] == "设备未授权"

    @pytest.mark.asyncio
    async def test_publish_without_client(self, channel):
        """测试未连接时不发布"""
        channel._mqtt_client = None
        # 不应抛出异常
        await channel._publish_audio("test_device", b"data", 1, False)
        await channel._publish_ctrl("test_device", {"type": "test"})


class TestHardwareChannelDispatch:
    """Hardware Channel 消息分发测试"""

    @pytest.fixture
    def channel(self):
        """创建 Channel"""
        config = HardwareChannelConfig(
            enabled=True,
            allow_from=["*"],
        )
        mock_bus = MagicMock()
        return HardwareChannel(config, mock_bus)

    @pytest.mark.asyncio
    async def test_dispatch_invalid_topic(self, channel):
        """测试无效 Topic 格式"""
        mock_message = MagicMock()
        mock_message.topic = "invalid"
        mock_message.payload = b"{}"

        # 不应抛出异常
        await channel._dispatch_message(mock_message)

    @pytest.mark.asyncio
    async def test_dispatch_unauthorized_device(self, channel):
        """测试未授权设备"""
        channel.config.allow_from = ["allowed_device"]

        mock_message = MagicMock()
        mock_message.topic = "device/unauthorized/ctrl/up"
        mock_message.payload = json.dumps({"type": "test"}).encode()

        # Mock _publish_error
        channel._publish_error = AsyncMock()

        await channel._dispatch_message(mock_message)
        channel._publish_error.assert_called_once_with(
            "unauthorized", "auth_failed", "设备未授权"
        )
