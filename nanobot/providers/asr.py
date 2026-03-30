"""ASR Provider - 语音识别提供者

ASRProvider 抽象基类定义语音识别的标准接口，
支持多提供商扩展（V1 实现火山引擎 ASR）。

使用方式：
    # 完整音频识别
    provider = VolcengineASRProvider(app_id="xxx", token="xxx")
    text = await provider.recognize(audio_data)

    # 流式识别
    async for result in provider.recognize_stream(audio_stream):
        print(result)
"""

from __future__ import annotations

import asyncio
import base64
import json
from abc import ABC, abstractmethod
from typing import AsyncIterator, Callable

import httpx
import websockets
from loguru import logger

from nanobot.config.schema import ASRConfig


# 火山引擎 ASR WebSocket API 配置
VOLCEENGINE_ASR_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"


class ASRProvider(ABC):
    """ASR 语音识别提供者抽象基类 — 支持多提供商扩展

    所有 ASR Provider 必须实现此接口，确保可切换不同厂商。
    """

    @abstractmethod
    async def recognize(
        self,
        audio_data: bytes,
        *,
        audio_format: str = "opus",
        sample_rate: int = 16000,
        language: str = "zh-CN",
    ) -> str | None:
        """将音频转为文本（完整音频识别）

        Args:
            audio_data: 音频数据（bytes）
            audio_format: 音频格式（opus/pcm）
            sample_rate: 采样率
            language: 语言代码

        Returns:
            识别出的文本，失败返回 None
        """
        ...

    @abstractmethod
    async def recognize_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        *,
        audio_format: str = "opus",
        sample_rate: int = 16000,
    ) -> AsyncIterator[str]:
        """流式识别：边发送音频边获取中间结果

        注意：子类实现时使用 async def + yield（async generator）。
        抽象基类中不能使用 yield，因此声明为普通方法返回 AsyncIterator[str]。

        Args:
            audio_stream: 音频流
            audio_format: 音频格式
            sample_rate: 采样率

        Yields:
            识别出的文本片段
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """检查服务可用性"""
        ...


class VolcengineASRProvider(ASRProvider):
    """火山引擎 ASR WebSocket 流式识别实现（V1 主选）

    文档参考：
    - 火山引擎 ASR API 文档
    - docs/design/v1/asr-tts.md §4.2
    """

    def __init__(
        self,
        app_id: str | None = None,
        token: str | None = None,
        cluster: str = "volcengine_streaming_common",
        language: str = "zh-CN",
    ):
        """
        初始化火山引擎 ASR Provider。

        Args:
            app_id: 火山引擎 App ID
            token: 火山引擎 Token
            cluster: ASR 集群，默认 volcengine_streaming_common
            language: 语言代码，默认 zh-CN
        """
        self._app_id = app_id or ""
        self._token = token or ""
        self._cluster = cluster
        self._language = language
        self._ws_url = VOLCEENGINE_ASR_WS_URL

    async def recognize(
        self,
        audio_data: bytes,
        *,
        audio_format: str = "opus",
        sample_rate: int = 16000,
        language: str = "zh-CN",
    ) -> str | None:
        """将音频转为文本（完整音频识别）

        通过 WebSocket 发送完整音频，获取识别结果。
        """
        try:
            # 对于完整音频，使用单次识别模式
            # 火山引擎 ASR 支持发送完整音频后获取结果
            results = await self._recognize_once(audio_data, audio_format, sample_rate, language)
            if results:
                # 返回最后一个完整句子
                return results[-1].get("text", "") if isinstance(results, list) else results
            return None
        except Exception as e:
            logger.warning("ASR 识别失败: {}", e)
            return None

    async def recognize_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        *,
        audio_format: str = "opus",
        sample_rate: int = 16000,
    ) -> AsyncIterator[str]:
        """流式识别：边发送音频边获取中间结果

        通过 WebSocket 并行发送音频和接收识别结果。
        使用单一 WebSocket 连接，sender 和 receiver 共享同一连接。
        """
        async for text in self._ws_stream(audio_stream, audio_format, sample_rate):
            yield text

    async def is_available(self) -> bool:
        """检查服务可用性"""
        try:
            async with httpx.AsyncClient() as client:
                # 简单的可用性检查：尝试获取 token
                response = await client.get(
                    "https://openspeech.bytedance.com/",
                    timeout=5.0,
                )
                return response.status_code == 200
        except Exception:
            return False

    async def _recognize_once(
        self,
        audio_data: bytes,
        audio_format: str,
        sample_rate: int,
        _language: str,
    ) -> list[dict]:
        """单次识别模式（发送完整音频）"""
        results: list[dict] = []
        result_event = asyncio.Event()

        async def on_message(message: str) -> None:
            try:
                data = json.loads(message)
                if data.get("code") == 1000 or data.get("event") == "finished":
                    results.append(data)
                    result_event.set()
                elif data.get("code") and data["code"] != 1000:
                    logger.warning("ASR 错误: {} - {}", data.get("code"), data.get("message"))
                    result_event.set()
            except json.JSONDecodeError:
                pass

        # 启动 WebSocket 连接
        ws_task = asyncio.create_task(
            self._ws_connect_and_send(audio_data, audio_format, sample_rate, on_message)
        )

        # 等待结果（超时 30 秒）
        try:
            await asyncio.wait_for(result_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("ASR 识别超时")

        ws_task.cancel()
        return results

    async def _ws_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        audio_format: str,
        sample_rate: int,
    ) -> AsyncIterator[str]:
        """WebSocket 流式识别

        使用单一 WebSocket 连接，通过 asyncio.Task 并行处理发送和接收，
        接收到的识别结果通过 asyncio.Queue 实时传递给调用方。
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        try:
            async with websockets.connect(
                self._ws_url,
                extra_headers=self._get_headers(),
                open_timeout=10,
                close_timeout=10,
            ) as ws:
                # 发送开始请求
                await ws.send(json.dumps(self._build_start_request(audio_format, sample_rate)))

                async def sender() -> None:
                    """发送音频到共享的 WebSocket 连接"""
                    try:
                        async for audio_chunk in audio_stream:
                            audio_base64 = base64.b64encode(audio_chunk).decode("utf-8")
                            await ws.send(json.dumps({
                                "event": "audio",
                                "data": {"audio": audio_base64},
                            }))
                            await asyncio.sleep(0.01)  # 控制发送速率

                        # 发送结束请求
                        await ws.send(json.dumps({"event": "done"}))
                    except Exception as e:
                        logger.warning("ASR 发送错误: {}", e)

                async def receiver() -> None:
                    """从共享的 WebSocket 连接接收识别结果"""
                    try:
                        async for message in ws:
                            data = json.loads(message)
                            if data.get("code") == 1000:
                                text = data.get("result", {}).get("text", "")
                                if text:
                                    await queue.put(text)
                            elif data.get("event") == "finished":
                                break
                            elif data.get("code") and data["code"] != 1000:
                                logger.warning("ASR 流式错误: {}", data)
                                break
                    except Exception as e:
                        logger.warning("ASR 接收错误: {}", e)
                    finally:
                        # 发送结束信号
                        await queue.put(None)

                # 并行启动 sender 和 receiver，receiver 完成即结束
                sender_task = asyncio.create_task(sender())
                receiver_task = asyncio.create_task(receiver())

                # 从队列实时 yield 结果（真正的流式输出）
                while True:
                    result = await queue.get()
                    if result is None:
                        break
                    yield result

                # 清理 tasks
                sender_task.cancel()
                try:
                    await sender_task
                except asyncio.CancelledError:
                    pass
                await receiver_task

        except Exception as e:
            logger.warning("ASR WebSocket 连接失败: {}", e)

    async def _ws_connect_and_send(
        self,
        audio_data: bytes,
        audio_format: str,
        sample_rate: int,
        on_message: Callable,
    ) -> None:
        """连接 WebSocket 并发送音频"""
        try:
            async with websockets.connect(
                self._ws_url,
                extra_headers=self._get_headers(),
                open_timeout=10,
                close_timeout=10,
            ) as ws:
                # 发送开始请求
                await ws.send(json.dumps(self._build_start_request(audio_format, sample_rate)))

                # 接收初始响应
                response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                await on_message(response)

                # 发送音频数据
                audio_base64 = base64.b64encode(audio_data).decode("utf-8")
                await ws.send(json.dumps({
                    "event": "audio",
                    "data": {"audio": audio_base64},
                }))

                # 接收结果
                while True:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        await on_message(message)
                    except asyncio.TimeoutError:
                        break
        except Exception as e:
            logger.warning("WebSocket 连接失败: {}", e)

    def _get_headers(self) -> dict[str, str]:
        """获取 WebSocket 请求头"""
        return {
            "Authorization": f"Bearer; {self._token}",
            "Content-Type": "application/json",
            "X-App-Id": self._app_id,
        }

    def _build_start_request(self, audio_format: str, sample_rate: int) -> dict:
        """构建开始请求"""
        return {
            "event": "start",
            "data": {
                "appid": self._app_id,
                "cluster": self._cluster,
                "language": self._language,
                "audio_format": "opus" if audio_format == "opus" else "pcm",
                "sample_rate": sample_rate,
                "enable_vad": True,  # 启用语音活动检测
                "enable_punctuation": True,  # 启用标点
            },
        }


# 工厂函数：基于配置创建 ASR Provider
def create_asr_provider(config: ASRConfig) -> ASRProvider:
    """基于配置创建 ASR Provider

    Args:
        config: ASRConfig 配置对象

    Returns:
        ASRProvider 实例
    """
    provider_name = config.provider.lower()

    if provider_name == "volcengine":
        return VolcengineASRProvider(
            app_id=config.volcengine.app_id,
            token=config.volcengine.token,
            cluster=config.volcengine.cluster,
            language=config.volcengine.language,
        )
    else:
        raise ValueError(f"不支持的 ASR Provider: {provider_name}")
