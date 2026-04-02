"""MP3 音频流播放器 — 将 MP3 文件通过 ffmpeg 转换为 PCM 流。"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

from loguru import logger

if TYPE_CHECKING:
    pass

WORKSPACE_MUSIC_DIR = Path.home() / ".nanobot" / "workspace" / "mp3"


class MusicPlayer:
    """将 MP3 文件解码为 PCM 音频流的异步生成器。

    输出格式：pcm_s16le, 24000Hz, mono（与 TTS 输出格式一致）。
    """

    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate

    async def stream(self, mp3_path: str) -> AsyncGenerator[bytes]:
        """异步流式返回 PCM chunks（yield bytes）。"""
        path = Path(mp3_path)
        if not path.exists():
            logger.warning("[MusicPlayer] 文件不存在: {}", mp3_path)
            return

        logger.info("[MusicPlayer] 开始播放: {} (目标采样率 {}Hz)", path.name, self.sample_rate)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", str(path.absolute()),
            "-f", "s16le",  # PCM 16-bit little-endian
            "-ar", str(self.sample_rate),  # 24000 Hz
            "-ac", "1",  # mono
            "-",
        ]
        logger.debug("[MusicPlayer] ffmpeg cmd: {}", " ".join(shlex.quote(c) for c in cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            while True:
                chunk = await proc.stdout.read(8192)
                if not chunk:
                    break
                yield chunk
        finally:
            await proc.wait()
            if proc.returncode not in (0, None):
                stderr = await proc.stderr.read()
                logger.error("[MusicPlayer] ffmpeg 失败 (code={}): {}", proc.returncode, stderr.decode(errors="replace"))


async def search_songs(query: str) -> list[tuple[Path, float]]:
    """搜索匹配的 MP3 文件，按相关度排序。搜索 ~/.nanobot/workspace/mp3/ 目录。

    Returns:
        [(Path, score), ...] 按 score 降序
    """
    results: list[tuple[Path, float]] = []

    for base_dir in (WORKSPACE_MUSIC_DIR,):
        if not base_dir.exists():
            continue
        for mp3_path in list(base_dir.glob("**/*.mp3")) + list(base_dir.glob("**/*.MP3")):
            name_lower = mp3_path.stem.lower()
            query_lower = query.lower()
            score = 0.0
            if query_lower in name_lower:
                score = 1.0
                if name_lower == query_lower:
                    score = 2.0
            elif any(query_lower in word for word in name_lower.split()):
                score = 0.8
            else:
                common = set(query_lower) & set(name_lower)
                score = len(common) / max(len(query_lower), len(name_lower)) * 0.5

            if score > 0:
                results.append((mp3_path, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
