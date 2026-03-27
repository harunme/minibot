#!/usr/bin/env python3
"""MiniBot 硬件测试客户端 - 模拟 ESP32 设备行为

通过 MQTT 连接 MiniBot 后端，模拟硬件设备进行语音对话测试。

功能：
- 麦克风录音（PCM 16kHz 16bit）
- Opus 编码（可选）
- MQTT 上行音频帧
- MQTT 下行音频帧接收
- 扬声器播放

使用方式：
    python tools/hardware_test_client.py --device test001 --token your_token --broker localhost
    python tools/hardware_test_client.py --device test001 --token your_token --broker localhost --mic  # 启用麦克风
    python tools/hardware_test_client.py --device test001 --token your_token --broker localhost --play  # 启用扬声器播放
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
import time
from dataclasses import dataclass
from typing import Any

import aiomqtt

# 可选依赖：sounddevice 用于音频录制/播放
try:
    import sounddevice as sd

    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False
    print("警告: sounddevice 未安装，麦克风和扬声器功能不可用")
    print("安装方式: pip install sounddevice")


# MQTT Topic 常量
TOPIC_AUDIO_UP = "device/{device_id}/audio/up"
TOPIC_AUDIO_DOWN = "device/{device_id}/audio/down"
TOPIC_CTRL_UP = "device/{device_id}/ctrl/up"
TOPIC_CTRL_DOWN = "device/{device_id}/ctrl/down"
TOPIC_STATUS = "device/{device_id}/status"

# MQTT 帧类型
FRAME_TYPE_UP = 0x01
FRAME_TYPE_DOWN = 0x02
FRAME_FLAG_LAST = 0x01

# 音频参数
SAMPLE_RATE = 16000  # 采样率
CHANNELS = 1  # 单声道
SAMPLE_WIDTH = 2  # 16-bit
CHUNK_DURATION_MS = 100  # 每块音频时长（毫秒）
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 每次采集的样本数


@dataclass
class AudioConfig:
    """音频配置"""

    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    sample_width: int = SAMPLE_WIDTH
    format: str = "opus"  # 或 "pcm"


class HardwareTestClient:
    """硬件测试客户端 - 模拟 ESP32 设备

    连接到 MQTT Broker，上传麦克风音频，接收并播放 TTS 音频。
    """

    def __init__(
        self,
        device_id: str,
        token: str,
        broker: str = "localhost",
        port: int = 1883,
        use_mic: bool = False,
        use_speaker: bool = False,
    ):
        """
        初始化测试客户端。

        Args:
            device_id: 设备 ID
            token: 认证 Token
            broker: MQTT Broker 地址
            port: MQTT Broker 端口
            use_mic: 是否启用麦克风录音
            use_speaker: 是否启用扬声器播放
        """
        self.device_id = device_id
        self.token = token
        self.broker = broker
        self.port = port
        self.use_mic = use_mic
        self.use_speaker = use_speaker

        self._mqtt_client: aiomqtt.Client | None = None
        self._running = False
        self._recording = False
        self._audio_stream: asyncio.StreamReader | None = None
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._seq = 0
        # 音频缓冲（用于接收下行音频）
        self._audio_buffer: bytearray = bytearray()

        # 音频流相关
        self._mic_stream: Any = None
        self._play_stream: Any = None

    async def start(self) -> None:
        """启动客户端"""
        print(f"[{self.device_id}] 启动硬件测试客户端...")
        print(f"  Broker: {self.broker}:{self.port}")
        print(f"  麦克风: {'启用' if self.use_mic else '禁用'}")
        print(f"  扬声器: {'启用' if self.use_speaker else '禁用'}")

        # 初始化音频设备
        if self.use_mic and HAS_SOUNDDEVICE:
            await self._init_mic()
        if self.use_speaker and HAS_SOUNDDEVICE:
            await self._init_speaker()

        # 连接 MQTT
        try:
            self._mqtt_client = aiomqtt.Client(
                identifier=f"device_{self.device_id}",
                hostname=self.broker,
                port=self.port,
                username=self.device_id,
                password=self.token,
                clean_session=False,  # 保持持久会话
                keepalive=60,
            )
            await self._mqtt_client.__aenter__()
            print(f"[{self.device_id}] MQTT 连接成功")

            # 上报设备状态
            await self._report_status("online")

            # 订阅下行 Topic
            await self._mqtt_client.subscribe(f"device/{self.device_id}/audio/down", qos=0)
            await self._mqtt_client.subscribe(f"device/{self.device_id}/ctrl/down", qos=1)
            print(f"[{self.device_id}] 已订阅下行 Topic")

            # 启动录音（如果启用）
            if self.use_mic:
                asyncio.create_task(self._record_audio())

            # 启动播放任务
            if self.use_speaker:
                asyncio.create_task(self._play_audio())

            # 消息循环
            self._running = True
            async for message in self._mqtt_client.messages:
                if not self._running:
                    break
                await self._handle_message(message)

        except Exception as e:
            print(f"[{self.device_id}] 错误: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        """停止客户端"""
        print(f"[{self.device_id}] 停止中...")
        self._running = False
        self._recording = False

        # 停止音频流
        if self._mic_stream:
            try:
                self._mic_stream.close()
            except Exception:
                pass

        # 上报离线状态
        if self._mqtt_client:
            try:
                await self._report_status("offline")
            except Exception:
                pass

        # 关闭 MQTT 连接
        if self._mqtt_client:
            try:
                await self._mqtt_client.__aexit__(None, None, None)
            except Exception:
                pass

        print(f"[{self.device_id}] 已停止")

    async def _handle_message(self, message: aiomqtt.Message) -> None:
        """处理收到的 MQTT 消息"""
        topic_str = str(message.topic)

        if "audio/down" in topic_str:
            await self._handle_audio_down(message.payload)
        elif "ctrl/down" in topic_str:
            await self._handle_ctrl_down(message.payload)

    async def _handle_audio_down(self, payload: bytes) -> None:
        """处理下行音频帧"""
        if len(payload) < 4:
            return

        # 解析 Header
        frame_type = payload[0]
        flags = payload[3]
        is_last = bool(flags & FRAME_FLAG_LAST)
        audio_data = payload[4:]

        if frame_type == FRAME_TYPE_DOWN:
            self._audio_buffer.extend(audio_data)
            if is_last:
                # 完整音频帧，添加到播放队列
                audio = bytes(self._audio_buffer)
                self._audio_buffer.clear()
                if audio:
                    await self._audio_queue.put(audio)
                    print(f"[{self.device_id}] 收到音频: {len(audio)} bytes")

    async def _handle_ctrl_down(self, payload: bytes) -> None:
        """处理下行控制消息"""
        try:
            data = json.loads(payload.decode("utf-8"))
            msg_type = data.get("type", "")
            print(f"[{self.device_id}] 控制消息: {msg_type} - {data}")

            if msg_type == "reply_start":
                print(f"[{self.device_id}] 开始接收回复...")
            elif msg_type == "reply_end":
                print(f"[{self.device_id}] 回复结束")
            elif msg_type == "text":
                print(f"[{self.device_id}] 文本回复: {data.get('content', '')}")
            elif msg_type == "error":
                print(f"[{self.device_id}] 错误: {data.get('code')} - {data.get('message')}")

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[{self.device_id}] 控制消息解析失败: {e}")

    async def _report_status(self, status: str) -> None:
        """上报设备状态"""
        payload = json.dumps({
            "status": status,
            "battery": 100,
            "signal": -50,
            "firmware": "1.0.0-test",
            "uptime": int(time.time()),
            "ts": int(time.time() * 1000),
        }).encode("utf-8")
        await self._mqtt_client.publish(TOPIC_STATUS.format(device_id=self.device_id), payload, qos=1)

    async def _record_audio(self) -> None:
        """录音并发送音频帧"""
        if not HAS_SOUNDDEVICE:
            return

        print(f"[{self.device_id}] 开始录音...")

        def audio_callback(indata, _frames, _time, status):
            if status:
                print(f"[{self.device_id}] 录音状态: {status}")
            if self._recording:
                # 将音频数据转换为 bytes 并加入队列
                audio_bytes = indata.tobytes()
                asyncio.create_task(self._send_audio_frame(audio_bytes))

        try:
            self._mic_stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=audio_callback,
            )
            self._mic_stream.start()

            while self._running:
                await asyncio.sleep(0.1)

        except Exception as e:
            print(f"[{self.device_id}] 录音错误: {e}")
        finally:
            if self._mic_stream:
                self._mic_stream.stop()
                self._mic_stream.close()

    async def _send_audio_frame(self, audio_data: bytes) -> None:
        """发送音频帧"""
        if not self._mqtt_client or not self._running:
            return

        self._seq = (self._seq + 1) % 65536
        is_last = len(audio_data) < CHUNK_SIZE * 2  # 简单判断最后帧

        # 组装帧
        header = bytes([FRAME_TYPE_UP, (self._seq >> 8) & 0xFF, self._seq & 0xFF, FRAME_FLAG_LAST if is_last else 0])
        payload = header + audio_data

        try:
            await self._mqtt_client.publish(
                TOPIC_AUDIO_UP.format(device_id=self.device_id),
                payload,
                qos=0,
            )
        except Exception as e:
            print(f"[{self.device_id}] 发送音频帧失败: {e}")

    async def _init_mic(self) -> None:
        """初始化麦克风"""
        if not HAS_SOUNDDEVICE:
            return
        try:
            devices = sd.query_devices()
            print(f"[{self.device_id}] 可用音频设备: {devices}")
        except Exception as e:
            print(f"[{self.device_id}] 音频设备查询失败: {e}")

    async def _init_speaker(self) -> None:
        """初始化扬声器"""
        pass  # 播放时动态初始化

    async def _play_audio(self) -> None:
        """播放音频队列中的音频"""
        if not HAS_SOUNDDEVICE:
            return

        while self._running:
            try:
                audio_data = await asyncio.wait_for(self._audio_queue.get(), timeout=1.0)
                print(f"[{self.device_id}] 播放音频: {len(audio_data)} bytes")
                # PCM 播放（假设是原始 PCM 数据）
                # 如果是 Opus 编码，需要先解码
                try:
                    # 尝试直接播放（作为 PCM）
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    sd.play(audio_array, SAMPLE_RATE)
                except Exception as e:
                    print(f"[{self.device_id}] 播放失败: {e}")
            except asyncio.TimeoutError:
                continue

    async def _send_ctrl(self, ctrl_type: str, extra: dict | None = None) -> None:
        """发送控制消息"""
        if not self._mqtt_client:
            return

        data = {"type": ctrl_type, "ts": int(time.time() * 1000)}
        if extra:
            data.update(extra)

        payload = json.dumps(data).encode("utf-8")
        await self._mqtt_client.publish(
            TOPIC_CTRL_UP.format(device_id=self.device_id),
            payload,
            qos=1,
        )

    async def start_recording(self) -> None:
        """开始录音（发送 audio_start 并开始录制）"""
        self._recording = True
        self._seq = 0
        await self._send_ctrl("audio_start", {
            "format": "pcm",
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
        })
        print(f"[{self.device_id}] 开始录音")

    async def stop_recording(self) -> None:
        """停止录音"""
        self._recording = False
        await self._send_ctrl("audio_end")
        print(f"[{self.device_id}] 停止录音")


async def interactive_mode(client: HardwareTestClient) -> None:
    """交互模式"""
    print("\n=== MiniBot 硬件测试客户端 - 交互模式 ===")
    print("可用命令:")
    print("  mic     - 切换麦克风录音")
    print("  status  - 上报设备状态")
    print("  help    - 显示帮助")
    print("  quit    - 退出")
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
            elif cmd == "status":
                await client._report_status("online")
            elif cmd == "help":
                print("可用命令: mic, status, help, quit")
            elif cmd == "quit":
                break
            else:
                print(f"未知命令: {cmd}")

        except (EOFError, KeyboardInterrupt):
            break

    await client.stop()


def main() -> None:
    """主函数"""
    parser = argparse.ArgumentParser(description="MiniBot 硬件测试客户端")
    parser.add_argument("--device", "-d", required=True, help="设备 ID")
    parser.add_argument("--token", "-t", required=True, help="认证 Token")
    parser.add_argument("--broker", "-b", default="localhost", help="MQTT Broker 地址")
    parser.add_argument("--port", "-p", type=int, default=1883, help="MQTT Broker 端口")
    parser.add_argument("--mic", action="store_true", help="启用麦克风录音")
    parser.add_argument("--play", action="store_true", help="启用扬声器播放")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互模式")

    args = parser.parse_args()

    # 创建客户端
    client = HardwareTestClient(
        device_id=args.device,
        token=args.token,
        broker=args.broker,
        port=args.port,
        use_mic=args.mic,
        use_speaker=args.play,
    )

    # 信号处理
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    signal.signal(signal.SIGINT, lambda *_: asyncio.create_task(client.stop()))
    signal.signal(signal.SIGTERM, lambda *_: asyncio.create_task(client.stop()))

    try:
        if args.interactive or (not args.mic and not args.play):
            loop.run_until_complete(interactive_mode(client))
        else:
            loop.run_until_complete(client.start())
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        loop.close()


if __name__ == "__main__":
    # 添加 numpy 导入用于播放
    try:
        import numpy as np
    except ImportError:
        pass

    main()
