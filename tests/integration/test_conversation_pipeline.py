"""M4 全链路集成测试 — WebSocket → ASR → Agent → TTS → WebSocket

验证完整对话管道：
1. 客户端 WebSocket 连接 + hello 握手
2. listen(start) → 发送音频 → listen(stop)
3. ASR 返回识别文本
4. 文本通过 MessageBus → AgentLoop → LLM 处理
5. Agent 回复通过 MessageBus → ChannelManager → WebSocket Channel
6. 客户端收到 reply(文本) + TTS 音频帧 + TTS end

所有外部服务（ASR/TTS/LLM）均使用 Mock，测试聚焦管道集成。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket_hw import (
    ConnectionHandler,
    MessageType,
    WebSocketHardwareChannel,
)


# ==================== Mock Providers ====================


class MockASRProvider:
    """Mock ASR Provider — 直接返回预设文本，模拟流式识别"""

    def __init__(self, final_text: str = "你好", interim_texts: list[str] | None = None):
        self._final_text = final_text
        self._interim_texts = interim_texts or [final_text[:2], final_text]

    async def recognize_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        *,
        audio_format: str = "opus",
        sample_rate: int = 16000,
    ) -> AsyncIterator[str]:
        # 消费全部音频（必须 drain 否则队列 hang）
        async for _ in audio_stream:
            pass
        # 模拟流式返回中间结果
        for text in self._interim_texts:
            await asyncio.sleep(0.001)
            yield text

    async def is_available(self) -> bool:
        return True


class MockTTSProvider:
    """Mock TTS Provider — 返回预设音频块"""

    def __init__(self, audio_chunks: list[bytes] | None = None):
        self._chunks = audio_chunks or [b"\x00\x01" * 100, b"\x02\x03" * 100]

    async def synthesize(
        self,
        text: str,
        voice_id: str = "default",
        *,
        audio_format: str = "opus",
        sample_rate: int = 24000,
    ) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            await asyncio.sleep(0.001)
            yield chunk

    async def list_voices(self) -> list[dict]:
        return [{"id": "mock_voice", "name": "Mock", "language": "zh-CN", "gender": "female"}]

    async def is_available(self) -> bool:
        return True


# ==================== Mock WebSocket ====================


class MockWebSocket:
    """模拟 WebSocket 连接，记录所有发送的消息"""

    def __init__(self):
        self.open = True
        self.remote_address = ("127.0.0.1", 54321)
        self.sent_messages: list[str | bytes] = []
        self._incoming: asyncio.Queue[str | bytes] = asyncio.Queue()
        self._closed = asyncio.Event()

    async def send(self, data: str | bytes) -> None:
        if not self.open:
            raise Exception("WebSocket closed")
        self.sent_messages.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.open = False
        self._closed.set()

    def inject(self, message: str | bytes) -> None:
        """注入一条"客户端发送的"消息"""
        self._incoming.put_nowait(message)

    def inject_close(self) -> None:
        """模拟客户端关闭连接"""
        self._closed.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        # 非阻塞检查 close
        while True:
            try:
                msg = self._incoming.get_nowait()
                return msg
            except asyncio.QueueEmpty:
                if self._closed.is_set():
                    raise StopAsyncIteration
                await asyncio.sleep(0.01)

    @property
    def json_messages(self) -> list[dict]:
        """返回所有 JSON 格式的发送消息"""
        result = []
        for m in self.sent_messages:
            if isinstance(m, str):
                try:
                    result.append(json.loads(m))
                except json.JSONDecodeError:
                    pass
        return result

    @property
    def binary_messages(self) -> list[bytes]:
        """返回所有二进制发送消息"""
        return [m for m in self.sent_messages if isinstance(m, bytes)]


# ==================== Fixtures ====================


@pytest.fixture
def ws_config():
    """WebSocket Channel 配置"""
    return {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 0,  # 随机端口
        "authKey": "",
        "maxConnections": 10,
        "timeoutSeconds": 60,
        "audioFormat": "pcm",
        "allowFrom": ["*"],
    }


@pytest.fixture
def mock_asr():
    return MockASRProvider(final_text="你好世界", interim_texts=["你好", "你好世界"])


@pytest.fixture
def mock_tts():
    return MockTTSProvider(audio_chunks=[b"\xaa\xbb" * 50, b"\xcc\xdd" * 50])


@pytest.fixture
def channel_with_providers(ws_config, mock_asr, mock_tts):
    """创建带 Mock ASR/TTS 的 WebSocket Channel"""
    bus = MessageBus()
    with patch.object(WebSocketHardwareChannel, "_create_asr_provider", return_value=mock_asr), \
         patch.object(WebSocketHardwareChannel, "_create_tts_provider", return_value=mock_tts):
        ch = WebSocketHardwareChannel(ws_config, bus)
    return ch, bus


# ==================== Pipeline Stage Tests ====================


class TestPipelineStage1_ASR:
    """阶段 1：WebSocket → ASR — 音频入 → 文本出"""

    async def test_asr_produces_final_text(self, channel_with_providers):
        """验证 ASR 流式识别产出最终文本并发送到客户端"""
        channel, bus = channel_with_providers
        ws = MockWebSocket()
        handler = ConnectionHandler(ws, channel)
        handler.device_id = "dev001"
        handler.authenticated = True

        # 启动 ASR
        handler._listening = True
        handler._listen_start_time = time.monotonic()
        handler._asr_task = asyncio.create_task(handler._run_asr())

        # 模拟发送音频帧
        for _ in range(5):
            await handler._asr_audio_queue.put(b"\x00" * 320)
            await asyncio.sleep(0.001)

        # 发送结束信号
        await handler._asr_audio_queue.put(None)

        # 等待 ASR 任务完成
        await asyncio.wait_for(handler._asr_task, timeout=5.0)

        # 验证客户端收到了 STT 消息
        stt_msgs = [m for m in ws.json_messages if m.get("type") == "stt"]
        assert len(stt_msgs) >= 2  # 至少有中间结果和最终结果

        # 最后一条 STT 应该是 is_final=True
        final_stt = [m for m in stt_msgs if m.get("is_final")]
        assert len(final_stt) == 1
        assert final_stt[0]["text"] == "你好世界"

    async def test_asr_publishes_to_bus(self, channel_with_providers):
        """验证 ASR 最终结果发布到 MessageBus"""
        channel, bus = channel_with_providers
        ws = MockWebSocket()
        handler = ConnectionHandler(ws, channel)
        handler.device_id = "dev001"
        handler.authenticated = True
        channel._register_connection("dev001", handler)

        # 启动 ASR
        handler._listening = True
        handler._listen_start_time = time.monotonic()
        handler._asr_task = asyncio.create_task(handler._run_asr())

        # 发送音频 + 结束信号
        await handler._asr_audio_queue.put(b"\x00" * 320)
        await handler._asr_audio_queue.put(None)

        await asyncio.wait_for(handler._asr_task, timeout=5.0)

        # 验证 MessageBus 中有 InboundMessage
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2.0)
        assert isinstance(msg, InboundMessage)
        assert msg.channel == "websocket_hw"
        assert msg.chat_id == "dev001"
        assert msg.content == "你好世界"
        assert "_pipeline_t0" in msg.metadata


class TestPipelineStage2_BusRouting:
    """阶段 2：MessageBus → Channel.send() — Agent 回复路由到正确连接"""

    async def test_outbound_routes_to_device(self, channel_with_providers):
        """验证 OutboundMessage 路由到正确的 WebSocket 连接"""
        channel, bus = channel_with_providers
        ws = MockWebSocket()
        handler = ConnectionHandler(ws, channel)
        handler.device_id = "dev001"
        handler.authenticated = True
        channel._register_connection("dev001", handler)

        # 模拟 Agent 回复
        outbound = OutboundMessage(
            channel="websocket_hw",
            chat_id="dev001",
            content="你好！我是小助手。",
            metadata={"_pipeline_t0": time.monotonic() - 0.5},
        )
        await channel.send(outbound)

        # 验证客户端收到了 reply + TTS 消息
        json_msgs = ws.json_messages
        reply_msgs = [m for m in json_msgs if m.get("type") == "reply"]
        assert len(reply_msgs) == 1
        assert reply_msgs[0]["text"] == "你好！我是小助手。"

        # TTS 相关消息
        tts_msgs = [m for m in json_msgs if m.get("type") == "tts"]
        assert any(m.get("state") == "start" for m in tts_msgs)
        assert any(m.get("state") == "end" for m in tts_msgs)

        # 验证收到了二进制音频
        assert len(ws.binary_messages) == 2

    async def test_outbound_to_disconnected_device_silent(self, channel_with_providers):
        """向未连接设备发送不报错"""
        channel, bus = channel_with_providers
        outbound = OutboundMessage(
            channel="websocket_hw",
            chat_id="dev_unknown",
            content="no one listening",
        )
        # 不应抛出异常
        await channel.send(outbound)


class TestPipelineStage3_FullPipeline:
    """阶段 3：全链路集成 — WebSocket → ASR → Bus → [Agent省略] → Bus → Channel → TTS → WebSocket"""

    async def test_full_pipeline_without_agent(self, channel_with_providers):
        """全链路测试（不含 Agent/LLM）：
        1. 客户端 hello 握手
        2. listen(start) → 发送音频 → listen(stop)
        3. ASR 产出文本 → 发布到 inbound bus
        4. 手动从 bus 取出并创建 outbound
        5. Channel.send() → reply + TTS 音频 → 客户端
        """
        channel, bus = channel_with_providers
        ws = MockWebSocket()
        handler = ConnectionHandler(ws, channel)

        # ---- Step 1: hello 握手 ----
        await handler._handle_hello({"device_id": "dev_test", "token": ""})
        assert handler.authenticated is True
        hello_resp = [m for m in ws.json_messages if m.get("type") == "hello"]
        assert len(hello_resp) == 1

        # ---- Step 2: listen(start) ----
        await handler._handle_listen({"mode": "start"})
        assert handler._listening is True
        assert handler._asr_task is not None

        # ---- Step 3: 发送音频 ----
        for i in range(3):
            await handler._handle_binary(b"\x00\x01\x02" * 100)
            await asyncio.sleep(0.002)

        # ---- Step 4: listen(stop) ----
        await handler._handle_listen({"mode": "stop"})

        # 等待 ASR 完成
        await asyncio.wait_for(handler._asr_task, timeout=5.0)

        # ---- Step 5: 验证 ASR 结果到 bus ----
        inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=2.0)
        assert inbound.content == "你好世界"
        assert inbound.channel == "websocket_hw"
        assert inbound.chat_id == "dev_test"

        # ---- Step 6: 模拟 Agent 回复 ----
        outbound = OutboundMessage(
            channel="websocket_hw",
            chat_id="dev_test",
            content="你好！有什么可以帮你的吗？",
            metadata={"_pipeline_t0": inbound.metadata.get("_pipeline_t0")},
        )
        await channel.send(outbound)

        # ---- Step 7: 验证客户端收到完整回复 ----
        json_msgs = ws.json_messages
        # 应该有: hello 响应 + STT 中间结果 + STT 最终结果 + reply + TTS start + TTS end
        msg_types = [m.get("type") for m in json_msgs]
        assert "hello" in msg_types
        assert "stt" in msg_types
        assert "reply" in msg_types
        assert "tts" in msg_types

        # reply 文本正确
        reply = [m for m in json_msgs if m.get("type") == "reply"]
        assert reply[-1]["text"] == "你好！有什么可以帮你的吗？"

        # 有 TTS 音频二进制帧
        assert len(ws.binary_messages) >= 2

    async def test_pipeline_latency_metadata_propagated(self, channel_with_providers):
        """验证 _pipeline_t0 在整个管道中正确传递"""
        channel, bus = channel_with_providers
        ws = MockWebSocket()
        handler = ConnectionHandler(ws, channel)

        await handler._handle_hello({"device_id": "dev_lat", "token": ""})
        await handler._handle_listen({"mode": "start"})
        await handler._handle_binary(b"\x00" * 100)
        await handler._handle_listen({"mode": "stop"})
        await asyncio.wait_for(handler._asr_task, timeout=5.0)

        inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=2.0)

        # _pipeline_t0 应该是 listen(start) 的时刻
        assert "_pipeline_t0" in inbound.metadata
        t0 = inbound.metadata["_pipeline_t0"]
        assert isinstance(t0, float)
        assert t0 > 0

        # 模拟 Agent 传递 metadata
        outbound = OutboundMessage(
            channel="websocket_hw",
            chat_id="dev_lat",
            content="回复",
            metadata=dict(inbound.metadata),
        )
        await channel.send(outbound)
        # 如果没有异常就是通过


class TestPipelineStage4_ASRUnavailable:
    """阶段 4：ASR 不可用时的优雅降级"""

    async def test_no_asr_sends_error(self, ws_config):
        """ASR Provider 为 None 时发送错误消息"""
        bus = MessageBus()
        with patch.object(WebSocketHardwareChannel, "_create_asr_provider", return_value=None), \
             patch.object(WebSocketHardwareChannel, "_create_tts_provider", return_value=None):
            channel = WebSocketHardwareChannel(ws_config, bus)

        ws = MockWebSocket()
        handler = ConnectionHandler(ws, channel)
        handler.device_id = "dev001"
        handler.authenticated = True

        handler._listening = True
        handler._listen_start_time = time.monotonic()
        handler._asr_task = asyncio.create_task(handler._run_asr())
        await asyncio.wait_for(handler._asr_task, timeout=3.0)

        error_msgs = [m for m in ws.json_messages if m.get("type") == "error"]
        assert len(error_msgs) == 1
        assert error_msgs[0]["code"] == "asr_unavailable"

    async def test_no_tts_still_sends_text(self, ws_config):
        """TTS Provider 为 None 时仍然发送文本回复"""
        bus = MessageBus()
        with patch.object(WebSocketHardwareChannel, "_create_asr_provider", return_value=None), \
             patch.object(WebSocketHardwareChannel, "_create_tts_provider", return_value=None):
            channel = WebSocketHardwareChannel(ws_config, bus)

        ws = MockWebSocket()
        handler = ConnectionHandler(ws, channel)
        handler.device_id = "dev001"
        handler.authenticated = True
        channel._register_connection("dev001", handler)

        outbound = OutboundMessage(
            channel="websocket_hw",
            chat_id="dev001",
            content="文本回复，无音频",
        )
        await channel.send(outbound)

        # 应该有 reply 但没有 TTS
        reply_msgs = [m for m in ws.json_messages if m.get("type") == "reply"]
        assert len(reply_msgs) == 1
        assert reply_msgs[0]["text"] == "文本回复，无音频"

        tts_msgs = [m for m in ws.json_messages if m.get("type") == "tts"]
        assert len(tts_msgs) == 0  # 无 TTS provider 不应有 TTS 消息


class TestPipelineStage5_TTS_Abort:
    """阶段 5：TTS 中止功能"""

    async def test_abort_stops_tts_streaming(self, channel_with_providers):
        """abort 中止 TTS 流式发送"""
        channel, bus = channel_with_providers

        # 使用慢速 TTS mock
        slow_chunks = [b"\x00" * 100] * 20  # 20 个块

        class SlowTTSProvider:
            async def synthesize(self, text, voice_id="default", *, audio_format="opus", sample_rate=24000):
                for chunk in slow_chunks:
                    await asyncio.sleep(0.02)  # 每块 20ms
                    yield chunk

        channel._tts_provider = SlowTTSProvider()

        ws = MockWebSocket()
        handler = ConnectionHandler(ws, channel)
        handler.device_id = "dev001"
        handler.authenticated = True
        channel._register_connection("dev001", handler)

        outbound = OutboundMessage(
            channel="websocket_hw",
            chat_id="dev001",
            content="这是一段较长的回复",
        )

        # 在 50ms 后触发 abort
        async def trigger_abort():
            await asyncio.sleep(0.05)
            handler._tts_abort = True

        abort_task = asyncio.create_task(trigger_abort())
        await channel.send(outbound)
        await abort_task

        # 不应收到全部 20 个音频块
        assert len(ws.binary_messages) < 20


class TestPipelineStage6_MultipleConnections:
    """阶段 6：多连接路由"""

    async def test_multiple_devices_independent(self, channel_with_providers):
        """多个设备独立收发"""
        channel, bus = channel_with_providers

        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        h1 = ConnectionHandler(ws1, channel)
        h2 = ConnectionHandler(ws2, channel)

        await h1._handle_hello({"device_id": "dev_A", "token": ""})
        await h2._handle_hello({"device_id": "dev_B", "token": ""})

        # 向 dev_A 发消息
        await channel.send(OutboundMessage(
            channel="websocket_hw", chat_id="dev_A", content="Hello A",
        ))
        # 向 dev_B 发消息
        await channel.send(OutboundMessage(
            channel="websocket_hw", chat_id="dev_B", content="Hello B",
        ))

        # 各自收到自己的消息
        a_replies = [m for m in ws1.json_messages if m.get("type") == "reply"]
        b_replies = [m for m in ws2.json_messages if m.get("type") == "reply"]
        assert len(a_replies) == 1 and a_replies[0]["text"] == "Hello A"
        assert len(b_replies) == 1 and b_replies[0]["text"] == "Hello B"

        # dev_A 没收到 dev_B 的消息
        assert not any(m.get("text") == "Hello B" for m in ws1.json_messages)


class TestPipelineStage7_HandshakeToReply:
    """阶段 7：完整对话轮次（含握手）"""

    async def test_conversation_round_trip(self, channel_with_providers, mock_asr, mock_tts):
        """完整对话轮次：握手 → 监听 → ASR → [Bus] → 回复 → TTS"""
        channel, bus = channel_with_providers
        ws = MockWebSocket()

        # 使用连接处理器
        handler = ConnectionHandler(ws, channel)

        # 1. 握手
        await handler._handle_hello({"device_id": "round_trip_dev", "token": ""})
        assert handler.authenticated

        # 2. 开始监听
        await handler._handle_listen({"mode": "start"})

        # 3. 发送音频
        for _ in range(5):
            await handler._handle_binary(b"\xfe\xed" * 80)
            await asyncio.sleep(0.001)

        # 4. 停止监听
        await handler._handle_listen({"mode": "stop"})

        # 5. 等待 ASR
        await asyncio.wait_for(handler._asr_task, timeout=5.0)

        # 6. 从 bus 获取 inbound
        inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=2.0)
        assert inbound.content == "你好世界"

        # 7. 模拟 Agent 回复
        reply = OutboundMessage(
            channel="websocket_hw",
            chat_id="round_trip_dev",
            content="我收到了你说的：" + inbound.content,
            metadata=dict(inbound.metadata),
        )
        await channel.send(reply)

        # 8. 验证完整回复链
        msg_types = [m.get("type") for m in ws.json_messages]
        assert msg_types.count("hello") == 1  # 握手响应
        assert msg_types.count("reply") == 1  # 文本回复
        assert "stt" in msg_types  # ASR 结果
        assert "tts" in msg_types  # TTS 状态

        # 文本回复内容
        replies = [m for m in ws.json_messages if m.get("type") == "reply"]
        assert "你好世界" in replies[0]["text"]

        # 音频帧
        assert len(ws.binary_messages) >= 2
