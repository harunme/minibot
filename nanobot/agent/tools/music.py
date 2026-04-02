"""Play Music Tool — 搜索并播放本地 MP3 歌曲."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool
from nanobot.utils.audio import search_songs

if TYPE_CHECKING:
    from nanobot.agent.tools.message import MessageTool


class PlayMusicTool(Tool):
    """
    搜索并播放本地 MP3 歌曲。

    歌曲存放目录：~/.nanobot/workspace/mp3/。
    找不到歌曲时返回提示信息（不发消息）。
    找到歌曲时直接调用 MessageTool.execute() 发送带 _music metadata 的消息，
    由 Channel 在 TTS 播放完毕后读取 metadata["_music"] 播放对应 MP3。
    """

    def __init__(self, message_tool: "MessageTool | None" = None):
        self._message_tool = message_tool

    def bind_message_tool(self, message_tool: "MessageTool") -> None:
        """绑定 MessageTool，用于发送消息."""
        self._message_tool = message_tool

    @property
    def name(self) -> str:
        return "play_music"

    @property
    def description(self) -> str:
        return (
            "搜索并播放本地 MP3 歌曲。当用户请求播放歌曲时调用。"
            "歌曲存放目录：~/.nanobot/workspace/mp3/。"
            "找不到歌曲时返回提示信息。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "要播放的歌曲名（支持模糊匹配）",
                },
            },
            "required": ["song_name"],
        }

    async def execute(self, song_name: str, **_: Any) -> str:
        results = await search_songs(song_name)
        if not results:
            return f"未找到歌曲「{song_name}」，请尝试其他歌曲名。"

        best_path = results[0][0]
        song_display = best_path.stem
        content = f"好的，正在为你播放「{song_display}」！🎵"

        # 直接调用 MessageTool.execute() 发送消息（带 _music metadata），
        # 避免依赖 LLM 主动调用 MessageTool 导致消息丢失。
        # MessageTool._sent_in_turn 会被设置，防止 LLM 重复发送。
        if self._message_tool is not None:
            # 通过 keyword args 触发 message tool 的 metadata 逻辑
            await self._message_tool.execute(content=content, _music=song_name)

        return content
