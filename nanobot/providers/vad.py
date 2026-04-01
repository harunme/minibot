"""VAD Provider - 语音活动检测提供者

VADProvider 抽象基类定义 VAD 的标准接口，
支持多提供商扩展（V1 实现 Silero VAD）。

使用方式：
    provider = SileroVADProvider()
    state = provider.create_state()
    while True:
        have_voice = provider.is_vad(state, opus_packet)
        if state.client_voice_stop:
            # 用户说完，触发 ASR
            pass
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import opuslib_next
from loguru import logger

if TYPE_CHECKING:
    import onnxruntime


@dataclass
class VADState:
    """VAD 运行时状态（duplex 模式下每连接独立）

    包含 ONNX 推理状态、Opus 解码器以及所有流控标志。
    ConnectionHandler 在 `listen(start)` 时创建，结束时销毁。
    """

    # ONNX Runtime 状态（hidden state）
    state: np.ndarray = field(default_factory=lambda: np.zeros((2, 1, 128), dtype=np.float32))
    # 上下文窗口（保留最后 64 帧）
    context: np.ndarray = field(default_factory=lambda: np.zeros((1, 64), dtype=np.float32))
    # Opus 解码器（16kHz 单声道）
    opus_decoder: opuslib_next.Decoder | None = None
    # 上一次是否为语音（双阈值滞后判断用）
    last_is_voice: bool = False
    # 滑动窗口（连续 N 帧有声才认为有声）
    voice_window: list[bool] = field(default_factory=list)
    # 最后活动时间（毫秒，time.time() * 1000）
    last_activity_time_ms: float = 0.0
    # 累积 PCM 音频缓冲（VAD 说完后送 ASR recognize()）
    audio_buffer: bytearray = field(default_factory=bytearray)
    # 是否已检测到语音（持续为 True 直到静默超时）
    client_have_voice: bool = False
    # VAD 检测到说完（静默超时后由 VAD 置 True，调用方处理后清零）
    client_voice_stop: bool = False


class VADProvider(ABC):
    """VAD 语音活动检测抽象基类 — 支持多提供商扩展"""

    @abstractmethod
    def is_vad(self, state: VADState, data: bytes, audio_format: str = "pcm") -> bool:
        """检测音频数据中的语音活动

        Args:
            state: VAD 运行时状态（由 create_state() 创建）
            data: 音频数据（opus packet 或 pcm 原始数据）
            audio_format: 音频格式（"opus" 或 "pcm"）

        Returns:
            当前帧是否有语音活动
        """
        ...

    def create_state(self) -> VADState:
        """创建 VAD 运行时状态（子类可覆盖）"""
        return VADState(opus_decoder=opuslib_next.Decoder(16000, 1))

    def release_state(self, state: VADState) -> None:
        """释放 VAD 运行时状态资源"""
        if state.opus_decoder is not None:
            try:
                del state.opus_decoder
                state.opus_decoder = None
            except Exception:
                pass


class SileroVADProvider(VADProvider):
    """Silero VAD 实现（V1 主选）

    基于 Silero VAD ONNX 模型实现，支持双阈值判断和滑动窗口。
    模型由 pip 包 `silero-vad` 绑定提供，无需手动下载。

    算法要点：
    - 双阈值判断：speech_prob >= high_threshold → 有声，
                  speech_prob <= low_threshold → 无声，
                  中间值保持前一状态
    - 滑动窗口：连续 N 帧有声才认为真正有声（防噪声抖动）
    - 静默超时：超过 silence_threshold_ms 无声音认为说完一句话
    """

    def __init__(
        self,
        threshold: float = 0.5,
        threshold_low: float = 0.2,
        min_silence_duration_ms: int = 1000,
        frame_window_threshold: int = 3,
    ):
        """
        初始化 Silero VAD Provider。

        Args:
            threshold: 高阈值（speech_prob >= threshold → 有声）
            threshold_low: 低阈值（speech_prob <= threshold_low → 无声）
            min_silence_duration_ms: 最小静默持续时间（毫秒），超过则认为说完一句话
            frame_window_threshold: 滑动窗口阈值（连续 N 帧有声才认为有声）
        """
        self._threshold = threshold
        self._threshold_low = threshold_low
        self._silence_threshold_ms = min_silence_duration_ms
        self._frame_window_threshold = frame_window_threshold

        # 从 silero-vad pip 包获取模型路径
        model_path = self._get_model_path()

        import onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._session: onnxruntime.InferenceSession = onnxruntime.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
            sess_options=opts,
        )
        logger.info(
            "[VAD] Silero VAD 已加载: path={}, threshold={}, threshold_low={}, silence_ms={}, window={}",
            model_path,
            threshold,
            threshold_low,
            min_silence_duration_ms,
            frame_window_threshold,
        )

    def _get_model_path(self) -> str:
        """从 silero-vad pip 包获取 ONNX 模型路径

        优先使用 importlib.resources（Python 3.9+），回退到手动构造路径。
        silero-vad 包在 site-packages/silero_vad/data/ 下绑定了 silero_vad.onnx。
        """
        try:
            from importlib.resources import files

            ref = files("silero_vad") / "data" / "silero_vad.onnx"
            # Python 3.9+：as_file 临时解压 zip/egg 中的文件
            return str(ref)
        except (ImportError, ModuleNotFoundError) as e:
            raise RuntimeError(
                "缺少依赖 silero-vad，请运行: pip install silero-vad onnxruntime"
            ) from e
        except Exception:
            # 回退：手动构造路径（兼容旧版 Python 或特殊安装方式）
            import os

            try:
                import silero_vad

                return os.path.join(
                    os.path.dirname(silero_vad.__file__), "data", "silero_vad.onnx"
                )
            except ImportError as e:
                raise RuntimeError(
                    "缺少依赖 silero-vad，请运行: pip install silero-vad onnxruntime"
                ) from e

    def create_state(self) -> VADState:
        """创建 VAD 运行时状态（包含 Opus 解码器）"""
        return VADState(opus_decoder=opuslib_next.Decoder(16000, 1))

    def is_vad(self, state: VADState, data: bytes, audio_format: str = "pcm") -> bool:
        """检测音频数据中的语音活动

        实现逻辑：
        1. 根据 audio_format 解码音频为 PCM int16
        2. 每次送入 512 样本给 ONNX 模型
        3. 双阈值 + 滑动窗口判断
        4. 更新 state.client_have_voice / state.client_voice_stop
        5. 将解码后的 PCM 追加到 state.audio_buffer（供 ASR recognize() 使用）
        """
        import time as time_module

        if self._session is None:
            return False

        try:
            # Step 1: 解码音频为 PCM
            if audio_format == "opus":
                decoder = state.opus_decoder
                if decoder is None:
                    return False
                pcm_frame = decoder.decode(data, 960)
            else:
                # PCM 格式：直接使用原始字节
                pcm_frame = data

            # 累积到音频缓冲
            state.audio_buffer.extend(pcm_frame)

            client_have_voice = False

            # 每次处理 512 样本
            while len(state.audio_buffer) >= 512 * 2:
                chunk = bytes(state.audio_buffer[: 512 * 2])
                state.audio_buffer = state.audio_buffer[512 * 2 :]

                audio_int16 = np.frombuffer(chunk, dtype=np.int16)
                audio_float32 = audio_int16.astype(np.float32) / 32768.0

                # 拼接上下文窗口：[context(1,64), audio(1,512)] → (1, 576)
                audio_input = np.concatenate(
                    [state.context, audio_float32.reshape(1, -1)],
                    axis=1,
                ).astype(np.float32)

                ort_inputs = {
                    "input": audio_input,
                    "state": state.state,
                    "sr": np.array(16000, dtype=np.int64),
                }
                out, state.state = self._session.run(None, ort_inputs)

                # 更新上下文（保留最后 64 帧）
                state.context = audio_input[:, -64:]
                speech_prob = out.item()

                # 双阈值判断
                if speech_prob >= self._threshold:
                    is_voice = True
                elif speech_prob <= self._threshold_low:
                    is_voice = False
                else:
                    is_voice = state.last_is_voice

                state.last_is_voice = is_voice

                # 滑动窗口
                state.voice_window.append(is_voice)
                if len(state.voice_window) > self._frame_window_threshold:
                    state.voice_window.pop(0)

                client_have_voice = (
                    state.voice_window.count(True) >= self._frame_window_threshold
                )

                # 静默超时判断
                if state.client_have_voice and not client_have_voice:
                    stop_duration = time_module.time() * 1000 - state.last_activity_time_ms
                    if stop_duration >= self._silence_threshold_ms:
                        state.client_voice_stop = True

                if client_have_voice:
                    state.client_have_voice = True
                    state.last_activity_time_ms = time_module.time() * 1000

            return client_have_voice

        except Exception as e:
            logger.warning("[VAD] 处理音频帧时出错 (format={}): {}", audio_format, e)
            return False


def create_vad_provider(config) -> VADProvider | None:
    """基于配置创建 VAD Provider

    Args:
        config: VADConfig 配置对象

    Returns:
        VADProvider 实例，provider 为 "none" 时返回 None
    """
    provider_name = config.provider.lower()

    if provider_name == "silero":
        cfg = config.silero
        return SileroVADProvider(
            threshold=cfg.threshold,
            threshold_low=cfg.threshold_low,
            min_silence_duration_ms=cfg.min_silence_duration_ms,
            frame_window_threshold=cfg.frame_window_threshold,
        )
    elif provider_name == "none":
        return None
    else:
        raise ValueError(f"不支持的 VAD Provider: {provider_name}")
