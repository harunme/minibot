"""WebSocket 语音通道单元测试

覆盖场景：握手认证、消息路由、音频处理、超时断开、错误处理。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.channels.websocket_voice import (
    ConnectionHandler,
    MessageType,
    WebSocketVoiceChannel,
)


# ==================== Fixtures ====================


@pytest.fixture
def mock_bus():
    """创建 Mock 消息总线"""
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    return bus


@pytest.fixture
def channel_config():
    """默认 Channel 配置（dict 格式）"""
    return {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 9999,
        "authKey": "",
        "maxConnections": 10,
        "timeoutSeconds": 5,
        "audioFormat": "opus",
        "allowFrom": ["*"],
    }


@pytest.fixture
def auth_config():
    """带认证的 Channel 配置"""
    return {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 9999,
        "authKey": "test-secret-key",
        "maxConnections": 10,
        "timeoutSeconds": 5,
        "audioFormat": "opus",
        "allowFrom": ["*"],
    }


@pytest.fixture
def restricted_config():
    """带设备白名单限制的配置"""
    return {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 9999,
        "authKey": "",
        "maxConnections": 10,
        "timeoutSeconds": 5,
        "audioFormat": "opus",
        "allowFrom": ["dev001", "dev002"],
    }


@pytest.fixture
def channel(channel_config, mock_bus):
    """创建 Channel 实例（Mock ASR/TTS）"""
    with patch.object(WebSocketVoiceChannel, "_create_asr_provider", return_value=None), \
         patch.object(WebSocketVoiceChannel, "_create_tts_provider", return_value=None):
        ch = WebSocketVoiceChannel(channel_config, mock_bus)
    return ch


@pytest.fixture
def auth_channel(auth_config, mock_bus):
    """创建带认证的 Channel 实例"""
    with patch.object(WebSocketVoiceChannel, "_create_asr_provider", return_value=None), \
         patch.object(WebSocketVoiceChannel, "_create_tts_provider", return_value=None):
        ch = WebSocketVoiceChannel(auth_config, mock_bus)
    return ch


@pytest.fixture
def restricted_channel(restricted_config, mock_bus):
    """创建带白名单限制的 Channel 实例"""
    with patch.object(WebSocketVoiceChannel, "_create_asr_provider", return_value=None), \
         patch.object(WebSocketVoiceChannel, "_create_tts_provider", return_value=None):
        ch = WebSocketVoiceChannel(restricted_config, mock_bus)
    return ch


def make_mock_ws(messages=None):
    """创建 Mock WebSocket 连接

    Args:
        messages: 模拟客户端发送的消息列表
    """
    ws = AsyncMock()
    ws.open = True
    ws.remote_address = ("127.0.0.1", 12345)
    ws.send = AsyncMock()
    ws.close = AsyncMock()

    if messages:
        ws.__aiter__ = MagicMock(return_value=iter(messages))
    else:
        ws.__aiter__ = MagicMock(return_value=iter([]))

    return ws


# ==================== Channel 基础测试 ====================


class TestWebSocketVoiceChannel:
    """Channel 基础功能测试"""

    def test_channel_name(self, channel):
        """验证 Channel 名称"""
        assert channel.name == "websocket_voice"
        assert channel.display_name == "WebSocket Hardware"

    def test_default_config(self):
        """验证默认配置"""
        config = WebSocketVoiceChannel.default_config()
        assert config["enabled"] is False
        assert config["port"] == 9000
        assert config["allowFrom"] == ["*"]

    def test_cfg_dict_format(self, channel):
        """验证 dict 格式配置读取"""
        assert channel._cfg("host", "") == "127.0.0.1"
        assert channel._cfg("port", 0) == 9999
        assert channel._cfg("timeout_seconds", 0) == 5
        # camelCase 也应该能读到
        assert channel._cfg("max_connections", 0) == 10

    def test_register_unregister(self, channel):
        """验证连接注册/注销"""
        handler = MagicMock()
        channel._register_connection("dev001", handler)
        assert "dev001" in channel._connections

        channel._unregister_connection("dev001")
        assert "dev001" not in channel._connections

    async def test_register_replaces_old(self, channel):
        """验证重复设备连接会踢掉旧连接"""
        old_handler = MagicMock()
        old_handler._close = AsyncMock()
        new_handler = MagicMock()

        channel._register_connection("dev001", old_handler)
        channel._register_connection("dev001", new_handler)

        # 等待异步 close 任务执行
        await asyncio.sleep(0.01)

        assert channel._connections["dev001"] is new_handler
        old_handler._close.assert_called_once()


# ==================== 握手认证测试 ====================


class TestHelloHandshake:
    """hello 握手认证测试"""

    async def test_hello_success_no_auth(self, channel):
        """无 auth_key 时，hello 成功"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)

        await handler._handle_hello({"device_id": "dev001", "token": ""})

        assert handler.authenticated is True
        assert handler.device_id == "dev001"
        # 验证发送了 hello 响应
        ws.send.assert_called_once()
        response = json.loads(ws.send.call_args[0][0])
        assert response["type"] == "hello"
        assert "session_id" in response

    async def test_hello_missing_device_id(self, channel):
        """缺少 device_id 时拒绝"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)

        await handler._handle_hello({"device_id": "", "token": ""})

        assert handler.authenticated is False
        # 验证发送了错误消息并关闭连接
        assert ws.send.call_count >= 1
        error_msg = json.loads(ws.send.call_args_list[0][0][0])
        assert error_msg["type"] == "error"
        assert error_msg["code"] == "invalid_hello"

    async def test_hello_auth_success(self, auth_channel):
        """auth_key 匹配时认证成功"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, auth_channel)

        await handler._handle_hello({"device_id": "dev001", "token": "test-secret-key"})

        assert handler.authenticated is True

    async def test_hello_auth_failed(self, auth_channel):
        """auth_key 不匹配时认证失败"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, auth_channel)

        await handler._handle_hello({"device_id": "dev001", "token": "wrong-key"})

        assert handler.authenticated is False
        error_msg = json.loads(ws.send.call_args_list[0][0][0])
        assert error_msg["code"] == "auth_failed"

    async def test_hello_device_not_allowed(self, restricted_channel):
        """设备不在白名单中时拒绝"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, restricted_channel)

        await handler._handle_hello({"device_id": "dev999", "token": ""})

        assert handler.authenticated is False
        error_msg = json.loads(ws.send.call_args_list[0][0][0])
        assert error_msg["code"] == "auth_failed"

    async def test_hello_device_allowed(self, restricted_channel):
        """设备在白名单中时允许"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, restricted_channel)

        await handler._handle_hello({"device_id": "dev001", "token": ""})

        assert handler.authenticated is True


# ==================== 消息路由测试 ====================


class TestMessageRouting:
    """消息路由测试"""

    async def test_unauthenticated_message_rejected(self, channel):
        """未认证状态下非 hello 消息被拒绝"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)

        await handler._handle_text(json.dumps({"type": "listen", "mode": "start"}))

        # 应该发送 not_authenticated 错误
        error_msg = json.loads(ws.send.call_args[0][0])
        assert error_msg["code"] == "not_authenticated"

    async def test_ping_pong(self, channel):
        """ping 消息返回 pong"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)
        handler.authenticated = True
        handler.device_id = "dev001"

        await handler._handle_text(json.dumps({"type": "ping"}))

        response = json.loads(ws.send.call_args[0][0])
        assert response["type"] == "pong"

    async def test_invalid_json_ignored(self, channel):
        """无效 JSON 被忽略"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)

        # 不应抛出异常
        await handler._handle_text("not valid json {{{")

    async def test_unknown_type_logged(self, channel):
        """未知消息类型被记录"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)
        handler.authenticated = True
        handler.device_id = "dev001"

        # 不应抛出异常
        await handler._handle_text(json.dumps({"type": "unknown_type"}))

    async def test_binary_before_auth_ignored(self, channel):
        """未认证时二进制消息被忽略"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)

        await handler._handle_binary(b"\x00\x01\x02\x03")

        # 不应有任何队列数据
        assert handler._asr_audio_queue.empty()

    async def test_binary_not_listening_ignored(self, channel):
        """非监听状态时二进制消息被忽略"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)
        handler.authenticated = True
        handler.device_id = "dev001"
        handler._listening = False

        await handler._handle_binary(b"\x00\x01\x02\x03")

        assert handler._asr_audio_queue.empty()

    async def test_binary_listening_queued(self, channel):
        """监听状态时二进制消息入队"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)
        handler.authenticated = True
        handler.device_id = "dev001"
        handler._listening = True

        await handler._handle_binary(b"\x00\x01\x02\x03")

        assert not handler._asr_audio_queue.empty()
        data = await handler._asr_audio_queue.get()
        assert data == b"\x00\x01\x02\x03"


# ==================== Listen 控制测试 ====================


class TestListenControl:
    """语音监听控制测试"""

    async def test_listen_start(self, channel):
        """listen start 启动监听"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)
        handler.authenticated = True
        handler.device_id = "dev001"

        await handler._handle_listen({"mode": "start"})

        assert handler._listening is True
        assert handler._asr_task is not None

        # 清理
        handler._listening = False
        await handler._asr_audio_queue.put(None)
        if handler._asr_task:
            handler._asr_task.cancel()
            try:
                await handler._asr_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_listen_stop(self, channel):
        """listen stop 停止监听"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)
        handler.authenticated = True
        handler.device_id = "dev001"
        handler._listening = True

        await handler._handle_listen({"mode": "stop"})

        assert handler._listening is False
        # 队列应该收到 None（结束信号）
        data = await handler._asr_audio_queue.get()
        assert data is None

    async def test_listen_invalid_mode(self, channel):
        """无效 mode 不会崩溃"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)
        handler.authenticated = True
        handler.device_id = "dev001"

        await handler._handle_listen({"mode": "invalid"})

        assert handler._listening is False


# ==================== TTS 中止测试 ====================


class TestAbort:
    """TTS 中止测试"""

    async def test_abort_sets_flag(self, channel):
        """abort 设置中止标志"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)
        handler.authenticated = True
        handler.device_id = "dev001"

        await handler._handle_abort()

        assert handler._tts_abort is True


# ==================== 消息类型枚举测试 ====================


class TestMessageType:
    """消息类型枚举测试"""

    def test_message_types(self):
        """验证所有消息类型"""
        assert MessageType.HELLO == "hello"
        assert MessageType.LISTEN == "listen"
        assert MessageType.ABORT == "abort"
        assert MessageType.PING == "ping"
        assert MessageType.PONG == "pong"
        assert MessageType.STT == "stt"
        assert MessageType.TTS == "tts"
        assert MessageType.REPLY == "reply"
        assert MessageType.ERROR == "error"


# ==================== 发送回复测试 ====================


class TestSendReply:
    """Agent 回复发送测试"""

    async def test_send_reply_text(self, channel):
        """发送文本回复"""
        ws = make_mock_ws()
        handler = ConnectionHandler(ws, channel)
        handler.authenticated = True
        handler.device_id = "dev001"

        msg = MagicMock(spec=["content", "metadata", "channel", "chat_id"])
        msg.content = "你好"
        msg.metadata = {}

        await handler.send_reply(msg)

        # 应该发送了 reply 消息（无 TTS Provider 则不发音频）
        assert ws.send.call_count >= 1
        reply = json.loads(ws.send.call_args_list[0][0][0])
        assert reply["type"] == "reply"
        assert reply["text"] == "你好"

    async def test_send_reply_closed_ws(self, channel):
        """连接已关闭时不发送"""
        ws = make_mock_ws()
        ws.open = False
        handler = ConnectionHandler(ws, channel)
        handler.device_id = "dev001"

        msg = MagicMock(spec=["content", "metadata"])
        msg.content = "test"

        # 不应抛出异常
        await handler.send_reply(msg)


# ==================== Channel send() 测试 ====================


class TestChannelSend:
    """Channel.send() 测试"""

    async def test_send_to_connected_device(self, channel):
        """向已连接设备发送消息"""
        handler = MagicMock()
        handler.send_reply = AsyncMock()
        channel._connections["dev001"] = handler

        msg = MagicMock(spec=["chat_id", "content", "channel", "metadata"])
        msg.chat_id = "dev001"
        msg.content = "hello"

        await channel.send(msg)

        handler.send_reply.assert_called_once_with(msg)

    async def test_send_to_disconnected_device(self, channel):
        """向未连接设备发送消息（静默忽略）"""
        msg = MagicMock(spec=["chat_id", "content", "channel", "metadata"])
        msg.chat_id = "dev999"

        # 不应抛出异常
        await channel.send(msg)
