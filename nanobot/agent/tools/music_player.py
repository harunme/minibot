"""音乐播放 Tool — 在客户端设备上播放本地 MP3 文件。"""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage
from nanobot.channels.music_player import search_songs


class MusicPlayerTool(Tool):
    """在客户端设备上播放指定的 MP3 歌曲文件。

    用户说"播放某某歌曲"时，LLM 调用此工具。
    Tool 搜索 mp3/ 目录下的匹配文件，并通过 MessageBus 发送
    带 music metadata 的 OutboundMessage，由 WebSocket 通道检测并流式播放。
    """

    def __init__(
        self,
        send_callback: Any = None,
        default_channel: str = "",
        default_chat_id: str = "",
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id

    def set_context(self, channel: str, chat_id: str) -> None:
        """设置当前消息上下文（由 AgentLoop._set_tool_context 调用）。"""
        self._default_channel = channel
        self._default_chat_id = chat_id

    @property
    def name(self) -> str:
        return "music_player_play"

    @property
    def description(self) -> str:
        return (
            "在客户端设备上播放 MP3 歌曲文件。当用户说「播放xxx歌曲」、"
            "「我想听xxx」、「放一首xxx」时调用此工具。只播放本地 mp3/ 目录中已有的歌曲。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "歌曲名称（可以是部分名称，会自动模糊匹配 mp3/ 目录下的文件）",
                },
            },
            "required": ["song_name"],
        }

    async def execute(self, song_name: str, **kwargs: Any) -> str:
        if not self._default_channel or not self._default_chat_id:
            return "错误：未设置播放目标 channel/chat_id"

        results = await search_songs_async(song_name)
        if not results:
            available = await list_songs_async()
            if available:
                names = ", ".join(p.stem for p in available[:10])
                return f"未找到歌曲「{song_name}」。当前可用的歌曲有：{names}（共 {len(available)} 首）"
            return f"未找到歌曲「{song_name}」，mp3/ 目录为空，请先添加 MP3 文件。"

        best = results[0][0]
        logger.info("[MusicPlayerTool] 播放歌曲: {} (路径: {})", best.stem, best)
        msg = OutboundMessage(
            channel=self._default_channel,
            chat_id=self._default_chat_id,
            content=f"🎵 正在播放：{best.stem}",
            metadata={"music": str(best.absolute())},
        )
        if self._send_callback:
            try:
                await self._send_callback(msg)
            except Exception as e:
                logger.error("[MusicPlayerTool] 发送音乐消息失败: {}", e)
                return f"播放失败：{e}"
        return f"🎵 正在播放：{best.stem}"


async def search_songs_async(query: str):
    """search_songs 的异步包装（search_songs 本身是 CPU 密集型同步操作）。"""
    import asyncio
    return await asyncio.to_thread(search_songs, query)


async def list_songs_async():
    """列出所有可用歌曲。"""
    from nanobot.channels.music_player import SKILLS_MUSIC_PLAYER_DIR

    if not SKILLS_MUSIC_PLAYER_DIR.exists():
        return []
    return list(SKILLS_MUSIC_PLAYER_DIR.glob("**/*.mp3")) + list(SKILLS_MUSIC_PLAYER_DIR.glob("**/*.MP3"))
