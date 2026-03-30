"""全局测试 fixtures — 共享 Mock 和配置，减少测试间重复。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


@pytest.fixture
def bus():
    """创建真实 MessageBus 实例（集成测试用）"""
    return MessageBus()


@pytest.fixture
def mock_bus():
    """创建 Mock 消息总线（单元测试用）"""
    b = MagicMock(spec=MessageBus)
    b.publish_inbound = AsyncMock()
    b.publish_outbound = AsyncMock()
    b.consume_inbound = AsyncMock()
    b.consume_outbound = AsyncMock()
    return b
