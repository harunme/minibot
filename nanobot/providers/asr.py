"""ASR Provider - 语音识别提供者

ASRProvider 抽象基类定义语音识别的标准接口，
支持多提供商扩展（V1 实现火山引擎 ASR）。

使用方式：
    # 完整音频识别
    provider = VolcengineASRProvider(app_key="xxx", access_key="xxx")
    text = await provider.recognize(audio_data)

    # 流式识别
    async for result in provider.recognize_stream(audio_stream):
        print(result)
"""

from __future__ import annotations

import asyncio
import certifi
import json
import ssl
import uuid
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx
import websockets
from loguru import logger

from nanobot.config.schema import ASRConfig


def _http1_context() -> ssl.SSLContext:
    """创建强制 HTTP/1.1 的 SSL 上下文（解决火山引擎 ASR 不支持 HTTP/2 的问题）"""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(certifi.where())  # 加载 certifi 根证书（macOS pyenv 兼容）
    ctx.set_alpn_protocols(["http/1.1"])
    return ctx


# 火山引擎 ASR WebSocket API 配置
VOLCEENGINE_ASR_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
# 资源 ID（固定值）
VOLCEENGINE_ASR_RESOURCE_ID = "volc.bigasr.sauc.duration"
# 每次发送音频的字节数（160ms @ 16kHz 16bit mono = 5120 bytes）
ASR_CHUNK_SIZE = 5120


class ASRProvider(ABC):
    """ASR 语音识别提供者抽象基类 — 支持多提供商扩展"""

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
    - 火山引擎 SAUC 双向流式大模型语音识别 WebSocket API

    认证方式（HTTP Header）：
        X-Api-App-Key: AppKey（控制台获取）
        X-Api-Access-Key: AccessKey（控制台获取）
        X-Api-Resource-Id: volc.bigasr.sauc.duration（固定）
        X-Api-Connect-Id: UUID（每次连接随机生成）
    """

    def __init__(
        self,
        app_key: str | None = None,
        access_key: str | None = None,
        language: str = "zh-CN",
    ):
        """
        初始化火山引擎 ASR Provider。

        Args:
            app_key: 火山引擎 AppKey（控制台获取）
            access_key: 火山引擎 AccessKey（控制台获取）
            language: 语言代码，默认 zh-CN
        """
        self._app_key = app_key or ""
        self._access_key = access_key or ""
        self._language = language
        self._ws_url = VOLCEENGINE_ASR_WS_URL
        self._resource_id = VOLCEENGINE_ASR_RESOURCE_ID

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
            result = await self._recognize_once(audio_data, sample_rate, language)
            return result
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
        async for text in self._ws_stream(audio_stream, sample_rate):
            yield text

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

    async def _recognize_once(
        self,
        audio_data: bytes,
        sample_rate: int,
        language: str,
    ) -> str | None:
        """单次识别模式（发送完整音频）"""
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        connect_id = str(uuid.uuid4())

        try:
            async with websockets.connect(
                self._ws_url,
                additional_headers=self._get_headers(connect_id),
                open_timeout=10,
                close_timeout=10,
                ssl=_http1_context(),
            ) as ws:
                # 发送初始化请求
                await ws.send(json.dumps(
                    self._build_init_request(sample_rate, language)
                ))

                # 接收初始化响应
                resp = await asyncio.wait_for(ws.recv(), timeout=10.0)
                if isinstance(resp, bytes):
                    # 二进制响应（可能是 protobuf 格式的错误信息）
                    try:
                        text_resp = resp.decode("utf-8", errors="replace")
                        logger.warning("[ASR] 初始化收到二进制响应，尝试解码: {}", text_resp[:200])
                    except Exception:
                        logger.warning("[ASR] 初始化收到二进制响应 ({} bytes): {}", len(resp), resp[:32].hex())
                    return None
                init_data = json.loads(resp)
                if init_data.get("payload", {}).get("status", {}).get("code") != 0:
                    logger.warning("ASR 初始化失败: {}", init_data)
                    return None

                # 将音频切分为 160ms 包并发送
                for i in range(0, len(audio_data), ASR_CHUNK_SIZE):
                    chunk = audio_data[i: i + ASR_CHUNK_SIZE]
                    await ws.send(chunk)
                    await asyncio.sleep(0.16)  # 控制发送速率与音频时长匹配

                # 发送负包（seq < 0）标识结束
                await ws.send(b"")

                # 接收识别结果
                async for message in ws:
                    if isinstance(message, bytes):
                        continue
                    data = json.loads(message)
                    status_code = data.get("payload", {}).get("status", {}).get("code")
                    if status_code is None:
                        continue
                    if status_code != 0:
                        logger.warning("ASR 错误码: {}", status_code)
                        break
                    result = data.get("payload", {}).get("result", {})
                    text = result.get("transcript", "")
                    is_final = result.get("is_final", False)
                    if text:
                        queue.put_nowait(text)
                    if is_final:
                        queue.put_nowait(None)
                        break

                # 收集所有文本结果
                texts = []
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    texts.append(item)

                return "".join(texts) if texts else None

        except asyncio.TimeoutError:
            logger.warning("ASR 识别超时")
            return None
        except websockets.exceptions.ConnectionClosed:
            logger.warning("ASR WebSocket 连接被关闭")
            return None
        except Exception as e:
            logger.warning("ASR WebSocket 连接失败: {}", e)
            return None

    async def _ws_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        sample_rate: int,
    ) -> AsyncIterator[str]:
        """WebSocket 流式识别

        使用单一 WebSocket 连接，通过 asyncio.Task 并行处理发送和接收，
        接收到的识别结果通过 asyncio.Queue 实时传递给调用方。
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        done_event = asyncio.Event()
        connect_id = str(uuid.uuid4())

        logger.info("[ASR] 正在连接火山引擎 ASR WebSocket...")
        try:
            async with websockets.connect(
                self._ws_url,
                additional_headers=self._get_headers(connect_id),
                open_timeout=10,
                close_timeout=10,
                ssl=_http1_context(),
            ) as ws:
                logger.info("[ASR] WebSocket 连接成功，发送初始化请求")
                # 发送初始化请求
                await ws.send(json.dumps(self._build_init_request(sample_rate, self._language)))

                async def sender() -> None:
                    """发送音频到共享的 WebSocket 连接

                    直接从 audio_stream 读取，None 表示流结束。
                    发送完所有音频后发送 b'' 标识结束。
                    """
                    sent_chunks = 0
                    total_bytes = 0
                    try:
                        # 等麦克风稳定（1秒），让队列中积累真实音频再开始发送
                        # 否则首块静音帧会导致火山引擎拒绝连接
                        await asyncio.sleep(1.0)
                        async for audio_chunk in audio_stream:
                            if audio_chunk is None:
                                # 流结束信号：等待一秒内队列中的残留音频被消费，
                                # 然后退出（sender 退出后，主循环会发送 b''）
                                logger.info("[ASR] 收到流结束信号，已发送 {} 块, {} bytes", sent_chunks, total_bytes)
                                break
                            sent_chunks += 1
                            total_bytes += len(audio_chunk)
                            if sent_chunks == 1:
                                logger.info("[ASR] 首块音频: {} bytes, 前4字节hex={}", len(audio_chunk), audio_chunk[:4].hex())
                            for i in range(0, len(audio_chunk), ASR_CHUNK_SIZE):
                                chunk = audio_chunk[i: i + ASR_CHUNK_SIZE]
                                try:
                                    await ws.send(chunk)
                                except websockets.exceptions.ConnectionClosed:
                                    break
                                await asyncio.sleep(0.16)
                        # 发送负包标识结束
                        try:
                            await ws.send(b"")
                        except websockets.exceptions.ConnectionClosed:
                            pass
                        logger.info("[ASR] 音频发送完成: {} 块, {} bytes", sent_chunks, total_bytes)
                    except Exception as e:
                        logger.warning("[ASR] 发送错误: {}", e)
                    finally:
                        done_event.set()

                async def receiver() -> None:
                    """从共享的 WebSocket 连接接收识别结果"""
                    first = True
                    try:
                        try:
                            async for message in ws:
                                if isinstance(message, bytes):
                                    # 跳过二进制帧（如协议层面的 ack 或二进制响应）
                                    # 如果长度较大，可能是服务端流式返回的音频参考数据
                                    if len(message) > 100:
                                        logger.debug("[ASR] 跳过大型二进制帧: {} bytes", len(message))
                                    continue
                                data = json.loads(message)
                                status_code = data.get("payload", {}).get("status", {}).get("code")
                                if first:
                                    logger.info("[ASR] 收到首条响应: code={}", status_code)
                                    first = False
                                if status_code is None:
                                    continue
                                if status_code != 0:
                                    logger.warning("ASR 流式错误码: {}", status_code)
                                    break
                                result = data.get("payload", {}).get("result", {})
                                text = result.get("transcript", "")
                                is_final = result.get("is_final", False)
                                if text:
                                    await queue.put(text)
                                if is_final:
                                    logger.info("[ASR] 收到最终结果: {}", text)
                                    break
                        except websockets.exceptions.ConnectionClosed as e:
                            logger.info("[ASR] WebSocket 关闭: {}", e)
                            pass
                    except Exception as e:
                        logger.warning("ASR 接收错误: {}", e)
                    finally:
                        await queue.put(None)

                sender_task = asyncio.create_task(sender())
                receiver_task = asyncio.create_task(receiver())

                while True:
                    result = await queue.get()
                    if result is None:
                        break
                    yield result

                await done_event.wait()
                sender_task.cancel()
                try:
                    await sender_task
                except asyncio.CancelledError:
                    pass
                await receiver_task

        except Exception as e:
            logger.warning("[ASR] WebSocket 连接失败: {}", e)

    def _get_headers(self, connect_id: str) -> dict[str, str]:
        """获取 WebSocket 请求头（按火山引擎 SAUC API 规范）

        Args:
            connect_id: 每次连接随机生成的 UUID
        """
        return {
            "X-Api-App-Key": self._app_key,
            "X-Api-Access-Key": self._access_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Connect-Id": connect_id,
        }

    def _build_init_request(self, sample_rate: int, language: str) -> dict:
        """构建初始化请求（message_type=0）

        Args:
            sample_rate: 采样率（仅支持 16000）
            language: 语言代码
        """
        return {
            "header": {
                "message_id": str(uuid.uuid4()),
                "message_type": 0,  # 0=初始化请求
                "serialization": 1,  # 1=JSON
                "compression": 0,
                "timestamp": 0,  # 服务端忽略，可填 0
            },
            "payload": {
                "audio": {
                    "format": "pcm",
                    "sample_rate": sample_rate,
                    "channels": 1,  # 仅支持单声道
                    "bits": 16,  # 仅支持 16bit
                },
                "request": {
                    "model_name": "bigmodel",
                    "vad_segment_duration": 1000,  # VAD 断句时长（毫秒）
                    "end_window_size": 500,  # 尾点检测窗口（毫秒）
                    "enable_punctuation": True,
                    "language": language,
                },
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
        cfg = config.volcengine
        return VolcengineASRProvider(
            app_key=cfg.app_key,
            access_key=cfg.access_key,
            language=cfg.language,
        )
    else:
        raise ValueError(f"不支持的 ASR Provider: {provider_name}")
