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
import gzip
import json
import ssl
import uuid
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx
import opuslib_next
import websockets
from loguru import logger

from nanobot.config.schema import ASRConfig


# 火山引擎 ASR WebSocket API 配置
# 多语种模式使用 bigmodel_nostream，单语种使用 bigmodel
VOLCEENGINE_ASR_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
VOLCEENGINE_ASR_WS_URL_MULTILINGUAL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
# 资源 ID（固定值）
VOLCEENGINE_ASR_RESOURCE_ID = "volc.bigasr.sauc.duration"


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


def _http1_context() -> ssl.SSLContext:
    """创建强制 HTTP/1.1 的 SSL 上下文（解决火山引擎 ASR 不支持 HTTP/2 的问题）"""
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["http/1.1"])
    return ctx


class VolcengineASRProvider(ASRProvider):
    """火山引擎 ASR WebSocket 流式识别实现（V1 主选）

    文档参考：火山引擎 SAUC 双向流式大模型语音识别 WebSocket API

    认证方式（HTTP Header）：
        X-Api-App-Key: AppKey（控制台获取）
        X-Api-Access-Key: AccessKey（控制台获取）
        X-Api-Resource-Id: volc.bigasr.sauc.duration（固定）
        X-Api-Connect-Id: UUID（每次连接随机生成）

    协议格式：
        - 使用 gzip 压缩请求体
        - 二进制帧头：version(4bit) + header_size(4bit) | message_type(4bit) + flags(4bit) |
                     serialization(4bit) + compression(4bit) | reserved(8bit) | extension
        - 消息类型：0x01=初始化，0x02=音频，0x0F=服务端错误
    """

    def __init__(
        self,
        app_key: str | None = None,
        access_key: str | None = None,
        language: str = "zh-CN",
        enable_multilingual: bool = False,
    ):
        """
        初始化火山引擎 ASR Provider。

        Args:
            app_key: 火山引擎 AppKey（控制台获取）
            access_key: 火山引擎 AccessKey（控制台获取）
            language: 语言代码，默认 zh-CN
            enable_multilingual: 启用多语种模式
        """
        self._app_key = app_key or ""
        self._access_key = access_key or ""
        self._language = language
        self._enable_multilingual = enable_multilingual
        self._ws_url = VOLCEENGINE_ASR_WS_URL_MULTILINGUAL if enable_multilingual else VOLCEENGINE_ASR_WS_URL
        self._resource_id = VOLCEENGINE_ASR_RESOURCE_ID
        # Opus 解码器（用于 opus 格式音频输入）
        self._decoder = opuslib_next.Decoder(16000, 1)

    async def recognize(
        self,
        audio_data: bytes,
        *,
        audio_format: str = "opus",
        _sample_rate: int = 16000,
        _language: str = "zh-CN",
    ) -> str | None:
        """将音频转为文本（完整音频识别）

        通过 WebSocket 发送完整音频，获取识别结果。
        """
        try:
            result = await self._recognize_once(audio_data, audio_format)
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
        async for text in self._ws_stream(audio_stream, audio_format):
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

    # ─── 二进制协议 ───────────────────────────────────────────────────────────

    def _generate_header(
        self,
        version: int = 0x01,
        message_type: int = 0x01,
        message_type_specific_flags: int = 0x00,
        serial_method: int = 0x01,
        compression_type: int = 0x01,
        reserved_data: int = 0x00,
        extension_header: bytes = b"",
    ) -> bytearray:
        """生成二进制帧头

        格式：version(4bit) | header_size(4bit) || message_type(4bit) | flags(4bit) ||
              serialization(4bit) | compression(4bit) || reserved(8bit) || extension
        """
        header = bytearray()
        header_size = int(len(extension_header) / 4) + 1
        header.append((version << 4) | header_size)
        header.append((message_type << 4) | message_type_specific_flags)
        header.append((serial_method << 4) | compression_type)
        header.append(reserved_data)
        header.extend(extension_header)
        return header

    def _generate_audio_header(self, last: bool = False) -> bytearray:
        """生成音频帧头

        Args:
            last: 是否为最后一帧（last_audio_frame 标志）
        """
        return self._generate_header(
            version=0x01,
            message_type=0x02,
            message_type_specific_flags=0x02 if last else 0x00,
            serial_method=0x01,
            compression_type=0x01,
        )

    def _parse_response(self, res: bytes) -> dict:
        """解析二进制响应帧

        Args:
            res: 原始响应字节

        Returns:
            解析后的字典，支持两种格式：
            - {"code": int, "msg_length": int, "payload_msg": dict} 错误响应（message_type=0x0F）
            - {"payload_msg": dict} 正常 JSON 响应
        """
        if len(res) < 4:
            logger.error("[ASR] 响应数据长度不足: {}", len(res))
            return {"error": "响应数据长度不足"}

        header = res[:4]
        message_type = header[1] >> 4

        # 服务端错误响应（message_type=0x0F）
        if message_type == 0x0F:
            code = int.from_bytes(res[4:8], "big", signed=False)
            msg_length = int.from_bytes(res[8:12], "big", signed=False)
            error_msg = json.loads(res[12:].decode("utf-8"))
            return {
                "code": code,
                "msg_length": msg_length,
                "payload_msg": error_msg,
            }

        # 正常 JSON 响应（跳过 12 字节协议头）
        try:
            json_data = res[12:].decode("utf-8")
            result = json.loads(json_data)
            logger.debug("[ASR] 解析响应: {}", result)
            return {"payload_msg": result}
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.error("[ASR] JSON 解析失败: {}", e)
            logger.error("[ASR] 原始数据: {}", res)
            raise

    def _build_request(self, reqid: str) -> dict:
        """构建初始化请求参数（按火山引擎 SAUC API 规范）

        Args:
            reqid: 请求唯一 ID
        """
        req = {
            "app": {
                "appid": self._app_key,
                "cluster": "volcengine_streaming_common",
                "token": self._access_key,
            },
            "user": {"uid": "streaming_asr_service"},
            "request": {
                "reqid": reqid,
                "workflow": "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate",
                "show_utterances": True,
                "result_type": "single",
                "sequence": 1,
                "boosting_table_name": "",
                "correct_table_name": "",
                "end_window_size": 200,
            },
            "audio": {
                "format": "pcm",
                "codec": "pcm",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
                "sample_rate": 16000,
            },
        }
        # language 参数仅在多语种模式下有效
        if self._enable_multilingual and self._language:
            req["audio"]["language"] = self._language
        return req

    def _get_headers(self, connect_id: str) -> dict[str, str]:
        """获取 WebSocket 请求头（按火山引擎 SAUC API 规范）"""
        return {
            "X-Api-App-Key": self._app_key,
            "X-Api-Access-Key": self._access_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Connect-Id": connect_id,
        }

    # ─── 识别实现 ─────────────────────────────────────────────────────────────

    async def _recognize_once(
        self,
        audio_data: bytes,
        audio_format: str,
    ) -> str | None:
        """单次识别模式（发送完整音频，等待识别结果）"""
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        connect_id = str(uuid.uuid4())
        reqid = str(uuid.uuid4())

        try:
            async with websockets.connect(
                self._ws_url,
                additional_headers=self._get_headers(connect_id),
                ssl=_http1_context(),
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
            ) as ws:
                # 发送初始化请求（gzip 压缩 + 二进制帧）
                request_params = self._build_request(reqid)
                payload_bytes = str.encode(json.dumps(request_params))
                payload_bytes = gzip.compress(payload_bytes)
                full_request = bytearray(self._generate_header(message_type=0x01))
                full_request.extend(len(payload_bytes).to_bytes(4, "big"))
                full_request.extend(payload_bytes)
                await ws.send(bytes(full_request))

                # 接收初始化响应
                init_res = await asyncio.wait_for(ws.recv(), timeout=10.0)
                result = self._parse_response(init_res)
                logger.info("[ASR] 初始化响应: {}", result)

                # 检查初始化是否成功
                payload_msg = result.get("payload_msg", {})
                if "code" in payload_msg and payload_msg["code"] != 1000:
                    error_msg = payload_msg.get("payload_msg", {}).get("error", "未知错误")
                    logger.warning("[ASR] 初始化失败: {}", error_msg)
                    return None

                # Opus 解码为 PCM
                if audio_format == "opus":
                    pcm_data = self._decoder.decode(audio_data, 960)
                else:
                    pcm_data = audio_data

                # 发送音频数据（gzip 压缩 + 二进制帧）
                payload = gzip.compress(pcm_data)
                audio_request = bytearray(self._generate_audio_header())
                audio_request.extend(len(payload).to_bytes(4, "big"))
                audio_request.extend(payload)
                await ws.send(bytes(audio_request))

                # 发送结束帧
                empty_payload = gzip.compress(b"")
                last_request = bytearray(self._generate_audio_header(last=True))
                last_request.extend(len(empty_payload).to_bytes(4, "big"))
                last_request.extend(empty_payload)
                await ws.send(bytes(last_request))

                # 接收识别结果
                async for message in ws:
                    if isinstance(message, str):
                        data = json.loads(message)
                    else:
                        data = self._parse_response(message)
                    payload_msg = data.get("payload_msg", {})
                    status_code = payload_msg.get("code")

                    # 静默处理无有效语音错误码 1013
                    if status_code == 1013:
                        continue

                    if "result" in payload_msg:
                        utterances = payload_msg["result"].get("utterances", [])
                        text = payload_msg["result"].get("text", "")
                        if utterances:
                            for utterance in utterances:
                                if utterance.get("definite", False):
                                    await queue.put(utterance["text"])
                                    break
                        elif text:
                            await queue.put(text)

                    if "error" in payload_msg:
                        logger.warning("[ASR] 识别错误: {}", payload_msg["error"])
                        break

                    # 多语种模式：持续到收到最终结果
                    if self._enable_multilingual and payload_msg.get("result", {}).get("text"):
                        break

                await queue.put(None)

                # 收集所有文本
                texts = []
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    texts.append(item)
                return "".join(texts) if texts else None

        except asyncio.TimeoutError:
            logger.warning("[ASR] 识别超时")
            return None
        except websockets.exceptions.ConnectionClosed:
            logger.warning("[ASR] WebSocket 连接被关闭")
            return None
        except Exception as e:
            logger.warning("[ASR] WebSocket 连接失败: {}", e)
            return None

    async def _ws_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        audio_format: str,
    ) -> AsyncIterator[str]:
        """WebSocket 流式识别

        使用单一 WebSocket 连接，通过 asyncio.Task 并行处理发送和接收，
        接收到的识别结果通过 asyncio.Queue 实时传递给调用方。
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        done_event = asyncio.Event()
        init_ok_event = asyncio.Event()
        connect_id = str(uuid.uuid4())
        reqid = str(uuid.uuid4())

        logger.info("[ASR] 正在连接火山引擎 ASR WebSocket...")
        try:
            async with websockets.connect(
                self._ws_url,
                additional_headers=self._get_headers(connect_id),
                ssl=_http1_context(),
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
            ) as ws:
                logger.info("[ASR] WebSocket 连接成功，发送初始化请求")

                # 发送初始化请求（gzip 压缩 + 二进制帧）
                request_params = self._build_request(reqid)
                payload_bytes = str.encode(json.dumps(request_params))
                payload_bytes = gzip.compress(payload_bytes)
                full_request = bytearray(self._generate_header(message_type=0x01))
                full_request.extend(len(payload_bytes).to_bytes(4, "big"))
                full_request.extend(payload_bytes)
                await ws.send(bytes(full_request))

                async def sender() -> None:
                    """发送音频到共享的 WebSocket 连接

                    Opus 格式音频先解码为 PCM，再分帧发送。
                    发送完所有音频后发送结束帧标识流结束。
                    """
                    sent_chunks = 0
                    total_bytes = 0
                    try:
                        # 等待初始化响应成功
                        try:
                            await asyncio.wait_for(init_ok_event.wait(), timeout=10.0)
                        except asyncio.TimeoutError:
                            logger.warning("[ASR] 等待初始化响应超时，放弃发送")
                            return
                        logger.info("[ASR] 初始化成功，开始发送音频")

                        async for audio_chunk in audio_stream:
                            if audio_chunk is None:
                                logger.info("[ASR] 收到流结束信号，已发送 {} 块, {} bytes", sent_chunks, total_bytes)
                                break

                            # Opus 解码为 PCM
                            if audio_format == "opus":
                                pcm_frame = self._decoder.decode(audio_chunk, 960)
                            else:
                                pcm_frame = audio_chunk

                            # gzip 压缩并发送
                            payload = gzip.compress(pcm_frame)
                            audio_request = bytearray(self._generate_audio_header())
                            audio_request.extend(len(payload).to_bytes(4, "big"))
                            audio_request.extend(payload)
                            await ws.send(bytes(audio_request))

                            sent_chunks += 1
                            total_bytes += len(pcm_frame)
                            if sent_chunks == 1:
                                logger.info("[ASR] 首块音频: {} bytes, 前4字节hex={}", len(audio_chunk), audio_chunk[:4].hex())

                            await asyncio.sleep(0.02)  # 控制发送速率

                        # 发送结束帧
                        empty_payload = gzip.compress(b"")
                        last_request = bytearray(self._generate_audio_header(last=True))
                        last_request.extend(len(empty_payload).to_bytes(4, "big"))
                        last_request.extend(empty_payload)
                        await ws.send(bytes(last_request))
                        logger.info("[ASR] 音频发送完成: {} 块, {} bytes", sent_chunks, total_bytes)

                    except websockets.exceptions.ConnectionClosed:
                        pass
                    except Exception as e:
                        logger.warning("[ASR] 发送错误: {}", e)
                    finally:
                        done_event.set()

                async def receiver() -> None:
                    """从共享的 WebSocket 连接接收识别结果

                    首条响应为初始化确认，通过 init_ok_event 通知 sender 开始发音频。
                    """
                    first = True
                    try:
                        async for message in ws:
                            if isinstance(message, str):
                                data = json.loads(message)
                            else:
                                data = self._parse_response(message)

                            payload_msg = data.get("payload_msg", {})
                            status_code = payload_msg.get("code")

                            if first:
                                logger.info("[ASR] 收到首条响应: {}", payload_msg)
                                first = False
                                # 参考文件逻辑："code" in result and result["code"] != 1000 → 失败
                                # 没有 code 字段说明初始化成功
                                if "code" in payload_msg and payload_msg["code"] != 1000:
                                    error = payload_msg.get("payload_msg", {}).get("error", payload_msg.get("error", "未知错误"))
                                    logger.warning("[ASR] 初始化失败: code={}, error={}", payload_msg.get("code"), error)
                                    init_ok_event.set()
                                    break
                                else:
                                    init_ok_event.set()
                                continue

                            # 静默处理无有效语音错误码
                            if status_code == 1013:
                                continue

                            if "result" in payload_msg:
                                utterances = payload_msg["result"].get("utterances", [])
                                for utterance in utterances:
                                    if utterance.get("definite", False):
                                        await queue.put(utterance["text"])
                                        break

                            if "error" in payload_msg:
                                logger.warning("[ASR] 识别错误: {}", payload_msg["error"])
                                break

                            # 多语种模式持续到有结果
                            if self._enable_multilingual and payload_msg.get("result", {}).get("text"):
                                break

                    except websockets.exceptions.ConnectionClosed as e:
                        logger.info("[ASR] WebSocket 关闭: {}", e)
                    except Exception as e:
                        logger.warning("[ASR] 接收错误: {}", e)
                    finally:
                        init_ok_event.set()
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

    async def close(self) -> None:
        """释放资源（Opus 解码器等）"""
        if hasattr(self, "_decoder") and self._decoder is not None:
            try:
                del self._decoder
                self._decoder = None
                logger.debug("[ASR] Opus decoder 资源已释放")
            except Exception as e:
                logger.debug("[ASR] 释放 Opus decoder 时出错: {}", e)
            try:
                del self._decoder
                self._decoder = None
                logger.debug("[ASR] Opus decoder 资源已释放")
            except Exception as e:
                logger.debug("[ASR] 释放 Opus decoder 时出错: {}", e)


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
            enable_multilingual=cfg.enable_multilingual,
        )
    else:
        raise ValueError(f"不支持的 ASR Provider: {provider_name}")
