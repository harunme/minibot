"""TTS Provider - 语音合成提供者

TTSProvider 抽象基类定义语音合成的标准接口，
支持多提供商扩展（V1 实现火山引擎 TTS）。

使用方式：
    # 流式合成
    provider = VolcengineTTSProvider(app_id="xxx", token="xxx")
    async for audio_chunk in provider.synthesize("你好"):
        play_audio(audio_chunk)

    # 获取可用音色
    voices = await provider.list_voices()
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx
import websockets
from loguru import logger

from nanobot.config.schema import TTSConfig, VolcengineTTSConfig


# 火山引擎 TTS WebSocket API URL
VOLCEENGINE_TTS_WS_URL = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"


class TTSProvider(ABC):
    """TTS 语音合成提供者抽象基类 — 支持多提供商扩展

    所有 TTS Provider 必须实现此接口，确保可切换不同厂商。
    """

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str = "default",
        *,
        audio_format: str = "opus",
        sample_rate: int = 24000,
    ) -> AsyncIterator[bytes]:
        """将文本转为语音音频流（流式输出）

        注意：子类实现时使用 async def + yield（async generator）。
        抽象基类中不能使用 yield，因此声明为普通方法返回 AsyncIterator[bytes]。

        Args:
            text: 待合成的文本
            voice_id: 音色 ID
            audio_format: 输出格式（opus/pcm）
            sample_rate: 采样率

        Yields:
            音频数据块（流式输出）
        """
        ...

    @abstractmethod
    async def list_voices(self) -> list[dict]:
        """列出可用音色

        Returns:
            音色列表，每项包含 id, name, language, gender 等
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """检查服务可用性"""
        ...


class VolcengineTTSProvider(TTSProvider):
    """火山引擎 TTS WebSocket 流式合成实现（V1 主选）

    文档参考：
    - 火山引擎 TTS API 文档
    - docs/design/v1/asr-tts.md §4.3

    预置音色：
    - zh_female_cancan_mars_bigtts - 灿灿
    - zh_male_shaoguoyang_mars_bigtts - 邵国防
    - zh_female_tianmei_mars_bigtts -甜美
    """

    def __init__(
        self,
        app_id: str | None = None,
        token: str | None = None,
        cluster: str = "volcano_tts",
        default_voice: str = "zh_female_cancan_mars_bigtts",
    ):
        """
        初始化火山引擎 TTS Provider。

        Args:
            app_id: 火山引擎 App ID
            token: 火山引擎 Token
            cluster: TTS 集群
            default_voice: 默认音色 ID
        """
        self._app_id = app_id or ""
        self._token = token or ""
        self._cluster = cluster
        self._default_voice = default_voice
        self._ws_url = VOLCEENGINE_TTS_WS_URL

        # 预置音色表
        self._preset_voices = [
            {"id": "zh_female_cancan_mars_bigtts", "name": "灿灿", "language": "zh-CN", "gender": "female"},
            {"id": "zh_male_shaoguoyang_mars_bigtts", "name": "邵国防", "language": "zh-CN", "gender": "male"},
            {"id": "zh_female_tianmei_mars_bigtts", "name": "甜美", "language": "zh-CN", "gender": "female"},
        ]

    async def synthesize(
        self,
        text: str,
        voice_id: str = "default",
        *,
        audio_format: str = "opus",
        sample_rate: int = 24000,
    ) -> AsyncIterator[bytes]:
        """将文本转为语音音频流（流式输出）

        通过 WebSocket 连接火山引擎 TTS API，流式获取合成的音频。
        """
        voice = voice_id if voice_id != "default" else self._default_voice

        try:
            async with websockets.connect(
                self._ws_url,
                additional_headers=self._get_headers(),
                open_timeout=10,
                close_timeout=10,
            ) as ws:
                logger.info("[TTS] WebSocket 连接成功，开始合成")
                # 发送开始请求
                start_req = self._build_start_request(text, voice, audio_format, sample_rate)
                logger.debug("[TTS] 发送请求: {}", start_req)
                await ws.send(json.dumps(start_req))

                # 接收响应头
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    logger.info("[TTS] 收到响应头: {}", response[:200] if isinstance(response, str) else f"<binary {len(response)} bytes>")
                    data = json.loads(response)
                    if data.get("code") and data["code"] != 1000:
                        logger.warning("TTS 错误: {} - {}", data.get("code"), data.get("message"))
                        return
                except asyncio.TimeoutError:
                    logger.warning("TTS 响应超时")
                    return

                # 流式接收音频数据
                chunk_count = 0
                total_bytes = 0
                while True:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=60.0)
                        audio_data = self._parse_audio_message(message)
                        if audio_data:
                            chunk_count += 1
                            total_bytes += len(audio_data)
                            if chunk_count == 1:
                                logger.info("[TTS] 首帧: {} bytes, type={}, 前4字节hex={}",
                                    len(audio_data), type(audio_data).__name__, audio_data[:4].hex())
                            yield audio_data
                        elif message == "" or message is None:
                            break
                    except asyncio.TimeoutError:
                        logger.warning("TTS 接收超时")
                        break

                logger.info("[TTS] 合成完成: 共 {} 帧, {} bytes", chunk_count, total_bytes)

        except Exception as e:
            logger.warning("TTS 合成失败: {}", e)

    async def list_voices(self) -> list[dict]:
        """列出可用音色"""
        return self._preset_voices.copy()

    async def is_available(self) -> bool:
        """检查服务可用性"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://openspeech.bytedance.com/",
                    timeout=5.0,
                )
                return response.status_code == 200
        except Exception:
            return False

    def _get_headers(self) -> dict[str, str]:
        """获取 WebSocket 请求头"""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "X-App-Id": self._app_id,
        }

    def _build_start_request(
        self,
        text: str,
        voice: str,
        audio_format: str,
        sample_rate: int,
    ) -> dict:
        """构建开始请求"""
        return {
            "event": "start",
            "data": {
                "appid": self._app_id,
                "cluster": self._cluster,
                "voice": voice,
                "text": text,
                "encoding": "opus" if audio_format == "opus" else "pcm",
                "sample_rate": sample_rate,
                "speed_ratio": 1.0,  # 语速
                "volume_ratio": 1.0,  # 音量
                "pitch_ratio": 1.0,  # 音调
            },
        }

    def _parse_audio_message(self, message: str | bytes) -> bytes | None:
        """解析音频消息

        Args:
            message: WebSocket 消息

        Returns:
            音频数据，失败返回 None
        """
        try:
            # 消息可能是二进制或 JSON
            if isinstance(message, bytes):
                # 二进制音频数据
                logger.debug("[TTS] 收到二进制音频: {} bytes, 前4字节hex={}", len(message), message[:4].hex())
                return message
            else:
                # JSON 格式
                data = json.loads(message)
                if data.get("code") == 1000:
                    # Base64 编码的音频数据
                    audio_b64 = data.get("data", {}).get("audio")
                    if audio_b64:
                        decoded = base64.b64decode(audio_b64)
                        logger.debug("[TTS] Base64音频解码: {} bytes, 前4字节hex={}", len(decoded), decoded[:4].hex())
                        return decoded
                elif data.get("event") == "finished":
                    logger.info("[TTS] 收到 finished 事件")
                    return None
                else:
                    logger.debug("[TTS] 收到非音频JSON: {}", data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("TTS 消息解析失败: {}", e)

        return None


# 工厂函数：基于配置创建 TTS Provider
def create_tts_provider(config: TTSConfig) -> TTSProvider:
    """基于配置创建 TTS Provider

    Args:
        config: TTSConfig 配置对象

    Returns:
        TTSProvider 实例
    """
    provider_name = config.provider.lower()

    if provider_name == "volcengine":
        return VolcengineTTSProvider(
            app_id=config.volcengine.app_id,
            token=config.volcengine.token,
            cluster=config.volcengine.cluster,
            default_voice=config.volcengine.default_voice,
        )
    else:
        raise ValueError(f"不支持的 TTS Provider: {provider_name}")
