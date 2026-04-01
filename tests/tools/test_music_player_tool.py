"""MusicPlayerTool 单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.agent.tools.music_player import MusicPlayerTool


@pytest.mark.asyncio
async def test_returns_error_when_no_target_context() -> None:
    """未设置 channel/chat_id 时应返回错误。"""
    tool = MusicPlayerTool()
    result = await tool.execute(song_name="晴天")
    assert "错误" in result
    assert "未设置播放目标" in result


@pytest.mark.asyncio
async def test_returns_error_when_callback_not_set() -> None:
    """未设置 send_callback 时应返回错误。"""
    tool = MusicPlayerTool(default_channel="websocket", default_chat_id="dev001")
    with patch("nanobot.agent.tools.music_player.search_songs_async", return_value=[]):
        with patch("nanobot.agent.tools.music_player.list_songs_async", return_value=[]):
            result = await tool.execute(song_name="晴天")
    # 无 send_callback 时走 search 路径（因为有 channel/chat_id），但发不出消息
    assert "未找到" in result


@pytest.mark.asyncio
async def test_song_not_found_returns_message() -> None:
    """找不到歌曲时返回提示信息。"""
    send_mock = AsyncMock()
    tool = MusicPlayerTool(
        send_callback=send_mock,
        default_channel="websocket",
        default_chat_id="dev001",
    )
    with patch("nanobot.agent.tools.music_player.search_songs_async", return_value=[]):
        with patch("nanobot.agent.tools.music_player.list_songs_async", return_value=[]):
            result = await tool.execute(song_name="不存在的歌曲")

    assert "未找到" in result
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_song_not_found_lists_available() -> None:
    """找不到歌曲时列出可用歌曲。"""
    send_mock = AsyncMock()
    tool = MusicPlayerTool(
        send_callback=send_mock,
        default_channel="websocket",
        default_chat_id="dev001",
    )
    fake_paths = [Path("/tmp/mp3/晴天.mp3"), Path("/tmp/mp3/七里香.mp3")]
    with patch("nanobot.agent.tools.music_player.search_songs_async", return_value=[]):
        with patch("nanobot.agent.tools.music_player.list_songs_async", return_value=fake_paths):
            result = await tool.execute(song_name="稻香")

    assert "未找到" in result
    assert "晴天" in result
    assert "七里香" in result
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_song_found_sends_music_message() -> None:
    """找到歌曲时发送带 music metadata 的 OutboundMessage。"""
    send_mock = AsyncMock()
    tool = MusicPlayerTool(
        send_callback=send_mock,
        default_channel="websocket",
        default_chat_id="dev001",
    )
    best_path = Path("/tmp/mp3/晴天.mp3")
    with patch("nanobot.agent.tools.music_player.search_songs_async", return_value=[(best_path, 1.0)]):
        result = await tool.execute(song_name="晴天")

    assert "🎵 正在播放" in result
    assert "晴天" in result
    send_mock.assert_awaited_once()
    msg = send_mock.call_args[0][0]
    assert msg.metadata.get("music") == str(best_path.absolute())
    assert msg.channel == "websocket"
    assert msg.chat_id == "dev001"


@pytest.mark.asyncio
async def test_song_found_picks_best_match() -> None:
    """多个匹配时选择得分最高的（分数降序排列）。"""
    send_mock = AsyncMock()
    tool = MusicPlayerTool(
        send_callback=send_mock,
        default_channel="ws",
        default_chat_id="d1",
    )
    best = Path("/mp3/七里香.mp3")
    worse = Path("/mp3/七里香demo.mp3")
    # search_songs_async 返回已按 score 降序排列的结果
    with patch(
        "nanobot.agent.tools.music_player.search_songs_async",
        return_value=[(best, 1.0), (worse, 0.8)],
    ):
        result = await tool.execute(song_name="七里香")

    send_mock.assert_awaited_once()
    msg = send_mock.call_args[0][0]
    assert msg.metadata.get("music") == str(best.absolute())


@pytest.mark.asyncio
async def test_send_callback_exception_returns_error() -> None:
    """send_callback 抛出异常时返回错误信息。"""
    send_mock = AsyncMock(side_effect=RuntimeError("连接断开"))
    tool = MusicPlayerTool(
        send_callback=send_mock,
        default_channel="ws",
        default_chat_id="d1",
    )
    best = Path("/mp3/test.mp3")
    with patch("nanobot.agent.tools.music_player.search_songs_async", return_value=[(best, 1.0)]):
        result = await tool.execute(song_name="test")

    assert "播放失败" in result
    assert "连接断开" in result


def test_set_context_updates_channel_and_chat_id() -> None:
    """set_context 正确更新内部状态。"""
    tool = MusicPlayerTool()
    tool.set_context(channel="my_channel", chat_id="my_chat")
    assert tool._default_channel == "my_channel"
    assert tool._default_chat_id == "my_chat"
