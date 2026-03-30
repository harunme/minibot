#!/usr/bin/env python3
"""MiniBot WebSocket 测试客户端 — 模拟 Tauri/Web 客户端行为

通过 WebSocket 连接 MiniBot 后端，进行语音对话测试。

功能：
- WebSocket 连接 + hello 握手认证
- 麦克风录音（PCM 16kHz 16bit）→ 二进制上行
- 接收 TTS 下行音频 → 扬声器播放
- 接收 ASR 识别结果和 Agent 回复
- 交互模式命令行控制

使用方式：
    python tools/ws_test_client.py --device dev001 --url ws://localhost:9000
    python tools/ws_test_client.py --device dev001 --url ws://localhost:9000 --mic --play
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from typing import Any

import websockets
from websockets.protocol import State as WsState

# 可选依赖：sounddevice 用于音频录制/播放
try:
    import sounddevice as sd

    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False
    print("警告: sounddevice 未安装，麦克风和扬声器功能不可用")
    print("安装方式: pip install sounddevice")

# 可选依赖：numpy 用于音频播放
try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# 音频参数
SAMPLE_RATE = 16000  # 采样率
CHANNELS = 1  # 单声道
CHUNK_DURATION_MS = 100  # 每块音频时长（毫秒）
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 每次采集的样本数


class WebSocketTestClient:
    """WebSocket 测试客户端 — 模拟 Tauri 客户端

    连接 WebSocket 服务器，上传麦克风音频，接收并播放 TTS 音频。
    """

    def __init__(
        self,
        device_id: str,
        url: str = "ws://localhost:9000",
        token: str = "",
        use_mic: bool = False,
        use_speaker: bool = False,
    ):
        """初始化测试客户端

        Args:
            device_id: 设备 ID
            url: WebSocket 服务器地址
            token: 认证 Token
            use_mic: 是否启用麦克风录音
            use_speaker: 是否启用扬声器播放
        """
        self.device_id = device_id
        self.url = url
        self.token = token
        self.use_mic = use_mic
        self.use_speaker = use_speaker

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._running = False
        self._recording = False
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._mic_stream: Any = None

    async def start(self) -> None:
        """启动客户端"""
        print(f"[{self.device_id}] 启动 WebSocket 测试客户端...")
        print(f"  服务器: {self.url}")
        print(f"  麦克风: {'启用' if self.use_mic else '禁用'}")
        print(f"  扬声器: {'启用' if self.use_speaker else '禁用'}")

        try:
            async with websockets.connect(self.url) as ws:
                self._ws = ws
                self._running = True
                print(f"[{self.device_id}] WebSocket 连接成功")

                # 发送 hello 握手
                await self._send_hello()

                # 启动接收任务
                recv_task = asyncio.create_task(self._receive_messages())

                # 启动播放任务
                play_task = None
                if self.use_speaker and HAS_SOUNDDEVICE and HAS_NUMPY:
                    play_task = asyncio.create_task(self._play_audio())

                # 等待接收任务完成（连接关闭）
                await recv_task

                if play_task:
                    play_task.cancel()

        except websockets.ConnectionClosed as e:
            print(f"[{self.device_id}] 连接关闭: {e}")
        except Exception as e:
            print(f"[{self.device_id}] 错误: {e}")
        finally:
            self._running = False
            self._recording = False

    async def stop(self) -> None:
        """停止客户端"""
        print(f"[{self.device_id}] 停止中...")
        self._running = False
        self._recording = False

        if self._mic_stream:
            try:
                self._mic_stream.close()
            except Exception:
                pass

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _send_hello(self) -> None:
        """发送握手消息"""
        hello = {
            "type": "hello",
            "device_id": self.device_id,
            "token": self.token,
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
            },
        }
        await self._send_json(hello)
        print(f"[{self.device_id}] 已发送 hello")

    async def _receive_messages(self) -> None:
        """接收服务器消息"""
        if not self._ws:
            return

        try:
            async for message in self._ws:
                if not self._running:
                    break

                if isinstance(message, str):
                    await self._handle_text(message)
                elif isinstance(message, bytes):
                    await self._handle_binary(message)
        except websockets.ConnectionClosed:
            pass

    async def _handle_text(self, message: str) -> None:
        """处理服务器文本消息"""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            print(f"[{self.device_id}] 无效 JSON: {message[:100]}")
            return

        msg_type = data.get("type", "")

        if msg_type == "hello":
            session_id = data.get("session_id", "")
            print(f"[{self.device_id}] 握手成功，session={session_id}")

        elif msg_type == "stt":
            text = data.get("text", "")
            is_final = data.get("is_final", False)
            prefix = "【最终】" if is_final else "【中间】"
            print(f"[{self.device_id}] ASR {prefix}: {text}")

        elif msg_type == "reply":
            text = data.get("text", "")
            print(f"[{self.device_id}] Agent 回复: {text}")

        elif msg_type == "tts":
            state = data.get("state", "")
            if state == "start":
                print(f"[{self.device_id}] TTS 开始...")
            elif state == "end":
                print(f"[{self.device_id}] TTS 结束")

        elif msg_type == "pong":
            pass  # 心跳响应，静默处理

        elif msg_type == "error":
            code = data.get("code", "")
            msg = data.get("message", "")
            print(f"[{self.device_id}] 错误: {code} - {msg}")

        else:
            print(f"[{self.device_id}] 未知消息: {data}")

    async def _handle_binary(self, data: bytes) -> None:
        """处理服务器二进制消息（TTS 音频）"""
        if self.use_speaker:
            await self._audio_queue.put(data)
            print(f"[{self.device_id}] 收到音频: {len(data)} bytes")

    async def _send_json(self, data: dict[str, Any]) -> None:
        """发送 JSON 消息"""
        if self._ws:
            await self._ws.send(json.dumps(data, ensure_ascii=False))

    async def start_recording(self) -> None:
        """开始录音"""
        if not HAS_SOUNDDEVICE:
            print("sounddevice 未安装，无法录音")
            return

        if self._recording:
            print("已在录音中")
            return

        self._recording = True
        # 通知服务器开始监听
        await self._send_json({"type": "listen", "mode": "start"})
        print(f"[{self.device_id}] 开始录音...")

        # 在后台录制并发送
        asyncio.create_task(self._record_and_send())

    async def stop_recording(self) -> None:
        """停止录音"""
        if not self._recording:
            return

        self._recording = False
        # 通知服务器停止监听
        await self._send_json({"type": "listen", "mode": "stop"})
        print(f"[{self.device_id}] 停止录音")

    async def _record_and_send(self) -> None:
        """录音并通过 WebSocket 发送"""
        if not HAS_SOUNDDEVICE or not self._ws:
            return

        loop = asyncio.get_event_loop()
        audio_ready = asyncio.Queue()

        def audio_callback(indata: Any, _frames: int, _time: Any, status: Any) -> None:
            if status:
                print(f"[{self.device_id}] 录音状态: {status}")
            if self._recording:
                loop.call_soon_threadsafe(audio_ready.put_nowait, bytes(indata))

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=audio_callback,
            )
            self._mic_stream = stream
            stream.start()

            while self._recording and self._running:
                try:
                    audio_data = await asyncio.wait_for(audio_ready.get(), timeout=0.5)
                    if self._ws and self._ws.state == WsState.OPEN:
                        await self._ws.send(audio_data)
                except asyncio.TimeoutError:
                    continue

        except Exception as e:
            print(f"[{self.device_id}] 录音错误: {e}")
        finally:
            if self._mic_stream:
                self._mic_stream.stop()
                self._mic_stream.close()
                self._mic_stream = None

    async def _play_audio(self) -> None:
        """播放音频队列中的音频"""
        if not HAS_SOUNDDEVICE or not HAS_NUMPY:
            return

        while self._running:
            try:
                audio_data = await asyncio.wait_for(self._audio_queue.get(), timeout=1.0)
                try:
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    sd.play(audio_array, SAMPLE_RATE)
                except Exception as e:
                    print(f"[{self.device_id}] 播放失败: {e}")
            except asyncio.TimeoutError:
                continue

    async def send_abort(self) -> None:
        """发送中止命令"""
        await self._send_json({"type": "abort"})
        print(f"[{self.device_id}] 已发送中止")

    async def send_ping(self) -> None:
        """发送心跳"""
        await self._send_json({"type": "ping"})


async def interactive_mode(client: WebSocketTestClient) -> None:
    """交互模式"""
    # 启动客户端连接（后台运行）
    client_task = asyncio.create_task(client.start())

    # 等待连接建立
    await asyncio.sleep(1)

    print("\n=== MiniBot WebSocket 测试客户端 - 交互模式 ===")
    print("可用命令:")
    print("  mic    - 切换麦克风录音（开始/停止）")
    print("  abort  - 中止 TTS 播放")
    print("  ping   - 发送心跳")
    print("  help   - 显示帮助")
    print("  quit   - 退出")
    print()

    while client._running:
        try:
            cmd = await asyncio.get_event_loop().run_in_executor(None, input, ">>> ")
            cmd = cmd.strip().lower()

            if cmd == "mic":
                if client._recording:
                    await client.stop_recording()
                else:
                    await client.start_recording()
            elif cmd == "abort":
                await client.send_abort()
            elif cmd == "ping":
                await client.send_ping()
            elif cmd == "help":
                print("可用命令: mic, abort, ping, help, quit")
            elif cmd == "quit":
                break
            else:
                print(f"未知命令: {cmd}")

        except (EOFError, KeyboardInterrupt):
            break

    await client.stop()
    client_task.cancel()
    try:
        await client_task
    except asyncio.CancelledError:
        pass


def main() -> None:
    """主函数"""
    parser = argparse.ArgumentParser(description="MiniBot WebSocket 测试客户端")
    parser.add_argument("--device", "-d", default="dev001", help="设备 ID")
    parser.add_argument("--url", "-u", default="ws://localhost:9000", help="WebSocket 服务器地址")
    parser.add_argument("--token", "-t", default="", help="认证 Token")
    parser.add_argument("--mic", action="store_true", help="启用麦克风录音")
    parser.add_argument("--play", action="store_true", help="启用扬声器播放")

    args = parser.parse_args()

    client = WebSocketTestClient(
        device_id=args.device,
        url=args.url,
        token=args.token,
        use_mic=args.mic,
        use_speaker=args.play,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _signal_handler(*_: Any) -> None:
        try:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(client.stop()))
        except RuntimeError:
            pass

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        loop.run_until_complete(interactive_mode(client))
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        loop