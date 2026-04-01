"""TTS Provider - 语音合成提供者

TTSProvider 抽象基类定义语音合成的标准接口，
支持多提供商扩展（V1 实现火山引擎 TTS）。

使用方式：
    # 流式合成（内部缓冲后逐块返回）
    provider = VolcengineTTSProvider(appid="xxx", token="xxx")
    async for audio_chunk in provider.synthesize("你好"):
        play_audio(audio_chunk)

    # 获取可用音色
    voices = await provider.list_voices()
"""

from __future__ import annotations

import base64
import json
import uuid
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx
from loguru import logger

from nanobot.config.schema import TTSConfig

# 火山引擎 TTS HTTP API URL（注意：不是 WebSocket，是 HTTPS POST）
VOLCENGINE_TTS_API_URL = "https://openspeech.bytedance.com/api/v1/tts"


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
    """火山引擎 TTS HTTP POST 流式合成实现（V1 主选）

    参考 xiaozhi `core/providers/tts/doubao.py` 实现。

    协议要点（对比错误的旧实现）：
    - ❌ 旧实现用 WebSocket（wss://.../ws_binary）→ 1006 立即关闭
    - ✅ 正确实现用 HTTPS POST（https://openspeech.bytedance.com/api/v1/tts）
    - ❌ 旧实现用 event/data 格式 → 服务端不认识
    - ✅ 正确实现用 app/audio/request 嵌套格式（与 ASR 一致）
    - ❌ 旧实现 Authorization: Bearer {token} + X-App-Id
    - ✅ 正确实现 Authorization: {authorization}{token}（两段拼接）
    - ❌ 旧实现直接收 binary 帧
    - ✅ 正确实现解析 JSON 响应，取 data 字段（base64 编码音频）

    预置音色：
    - zh_female_cancan_mars_bigtts - 灿灿
    - zh_male_shaoguoyang_mars_bigtts - 邵国防
    - zh_female_tianmei_mars_bigtts - 甜美
    """

    def __init__(
        self,
        appid: str | None = None,
        token: str | None = None,
        authorization: str = "Bearer ",
        cluster: str = "volcano_tts",
        default_voice: str = "zh_female_cancan_mars_bigtts",
    ):
        """
        初始化火山引擎 TTS Provider。

        Args:
            appid: 火山引擎 App ID
            token: 火山引擎 Token（authorization token 后半段）
            authorization: Authorization 前缀，默认 "Bearer "
            cluster: TTS 集群
            default_voice: 默认音色 ID
        """
        self._appid = appid or ""
        self._token = token or ""
        self._authorization = authorization
        self._cluster = cluster
        self._default_voice = default_voice
        self._api_url = VOLCENGINE_TTS_API_URL

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
        audio_format: str = "pcm",
        sample_rate: int = 24000,
        speed_ratio: float = 1.0,
        volume_ratio: float = 1.0,
        pitch_ratio: float = 1.0,
    ) -> AsyncIterator[bytes]:
        """将文本转为语音音频流

        通过 HTTPS POST 请求火山引擎 TTS API，收到完整音频后按固定大小分块 yield。

        Args:
            text: 待合成的文本
            voice_id: 音色 ID
            audio_format: 输出格式（pcm/wav）
            sample_rate: 采样率
            speed_ratio: 语速（0.1-3.0）
            volume_ratio: 音量（0.1-3.0）
            pitch_ratio: 音调（0.1-3.0）

        Yields:
            音频数据块（流式输出，每块 8192 bytes）
        """
        voice = voice_id if voice_id != "default" else self._default_voice

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = self._build_request(text, voice, audio_format, speed_ratio, volume_ratio, pitch_ratio)
                headers = self._get_headers()
                logger.debug("[TTS] 发送请求: {}", json.dumps(payload, ensure_ascii=False))
                response = await client.post(self._api_url, json=payload, headers=headers)

                if response.status_code != 200:
                    # 401 时打印 Authorization header 供调试（隐藏完整 token）
                    auth_hint = headers.get("Authorization", "")
                    if auth_hint and len(auth_hint) > 20:
                        auth_hint = auth_hint[:20] + "..."
                    logger.warning(
                        "[TTS] HTTP 错误: status={}, body={} | Authorization: {}",
                        response.status_code,
                        response.text[:200],
                        auth_hint,
                    )
                    return

                resp_data = response.json()
                code = resp_data.get("code")
                # logger.debug("[TTS] 响应: {}", resp_data)
                # code=1000 或 code=3000 均表示成功（不同集群格式）
                if code and code not in (1000, 3000):
                    logger.warning("[TTS] 服务端错误: code={}, message={}", code, resp_data.get("message"))
                    return

                # 音频数据可能在 data 或 data.audio 等不同字段，尝试多路径获取
                data_field = resp_data.get("data") or resp_data.get("data", {}).get("audio") or resp_data.get("data", {}).get("result")
                if isinstance(data_field, str) and data_field:
                    b64_audio = data_field
                elif isinstance(data_field, dict):
                    b64_audio = data_field.get("audio") or data_field.get("result") or ""
                else:
                    b64_audio = ""
                if not b64_audio:
                    logger.warning("[TTS] 响应中无 audio 数据")
                    return

                audio_bytes = base64.b64decode(b64_audio)
                logger.info("[TTS] 合成完成: {} bytes, 前4字节hex={}", len(audio_bytes), audio_bytes[:4].hex())

                # 按固定大小分块 yield，模拟流式输出
                chunk_size = 8192
                for i in range(0, len(audio_bytes), chunk_size):
                    yield audio_bytes[i : i + chunk_size]

        except httpx.TimeoutException:
            logger.warning("[TTS] 请求超时")
        except Exception as e:
            logger.warning("[TTS] 合成失败: {}", e)

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
        """获取 HTTP 请求头（按 xiaozhi doubao.py 格式）

        Authorization 格式：{authorization}{token}（两段拼接，如 "Bearer " + token）
        """
        return {
            "Authorization": f"{self._authorization}{self._token}",
            "Content-Type": "application/json",
        }

    def _build_request(
        self,
        text: str,
        voice: str,
        audio_format: str,
        speed_ratio: float,
        volume_ratio: float,
        pitch_ratio: float,
    ) -> dict:
        """构建请求体（按 xiaozhi doubao.py 格式）

        使用 app/audio/request 嵌套结构，与 ASR 协议格式一致。
        """
        return {
            "app": {
                "appid": self._appid,
                "token": self._token,
                "cluster": self._cluster,
            },
            "user": {"uid": "1"},
            "audio": {
                "voice_type": voice,
                "encoding": audio_format,
                "speed_ratio": speed_ratio,
                "volume_ratio": volume_ratio,
                "pitch_ratio": pitch_ratio,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "with_frontend": 1,
                "frontend_type": "unitTson",
            },
        }


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
            appid=config.volcengine.appid,
            token=config.volcengine.token,
            authorization=config.volcengine.authorization,
            cluster=config.volcengine.cluster,
            default_voice=config.volcengine.default_voice,
        )
    else:
        raise ValueError(f"不支持的 TTS Provider: {provider_name}")
