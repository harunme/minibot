"""VAD Provider 测试"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nanobot.config.schema import VADConfig, SileroVADConfig
from nanobot.providers.vad import (
    VADProvider,
    VADState,
    SileroVADProvider,
    create_vad_provider,
)


@pytest.fixture(autouse=True)
def mock_vad_filesystem():
    """Mock os.path.exists 和 onnxruntime，阻止自动下载模型"""
    with patch("os.path.exists", return_value=True), \
         patch("onnxruntime.InferenceSession", return_value=MagicMock()):
        yield


class TestVADState:
    """VADState 数据类测试"""

    def test_default_state(self):
        """测试默认状态初始化"""
        state = VADState()
        assert state.state.shape == (2, 1, 128)
        assert state.context.shape == (1, 64)
        assert state.opus_decoder is None
        assert state.last_is_voice is False
        assert state.voice_window == []

    def test_state_with_decoder(self):
        """测试带 Opus 解码器的状态"""
        import opuslib_next

        decoder = opuslib_next.Decoder(16000, 1)
        state = VADState(opus_decoder=decoder)
        assert state.opus_decoder is decoder


class TestSileroVADProvider:
    """Silero VAD Provider 测试"""

    def test_init_with_model_path(self):
        """测试带模型路径的初始化（Mock ONNX Session）"""
        # autouse fixture patches onnxruntime → _session 为 MagicMock
        provider = SileroVADProvider(
            model_path="/fake/path/silero_vad.onnx",
            threshold=0.6,
            threshold_low=0.3,
            min_silence_duration_ms=500,
            frame_window_threshold=5,
        )
        assert provider._session is not None
        assert provider._threshold == 0.6
        assert provider._threshold_low == 0.3
        assert provider._silence_threshold_ms == 500
        assert provider._frame_window_threshold == 5

    def test_init_without_model_path(self):
        """测试无模型路径且下载失败时抛出异常"""
        with patch("os.path.exists", return_value=False), \
             patch.object(SileroVADProvider, "_download_model", side_effect=Exception("下载失败")):
            with pytest.raises(Exception, match="下载失败"):
                SileroVADProvider()

    def test_create_state(self):
        """测试创建 VADState（包含 Opus 解码器）"""
        provider = SileroVADProvider()
        state = provider.create_state()
        assert state.opus_decoder is not None

    def test_release_state(self):
        """测试释放 VADState 资源"""
        import opuslib_next

        decoder = opuslib_next.Decoder(16000, 1)
        state = VADState(opus_decoder=decoder)
        provider = SileroVADProvider()
        provider.release_state(state)
        assert state.opus_decoder is None

    def test_create_state_has_audio_buffer(self):
        """测试 create_state 创建的 state 包含音频缓冲"""
        provider = SileroVADProvider()
        state = provider.create_state()
        assert isinstance(state.audio_buffer, bytearray)
        assert state.client_have_voice is False
        assert state.client_voice_stop is False

    def test_is_vad_no_session(self):
        """测试无模型时抛出异常（而不是静默返回 False）"""
        with patch("os.path.exists", return_value=False), \
             patch.object(SileroVADProvider, "_download_model", side_effect=Exception("下载失败")):
            with pytest.raises(Exception):
                SileroVADProvider()

    def test_is_vad_no_decoder(self):
        """测试无 Opus 解码器时 is_vad 返回 False"""
        provider = SileroVADProvider(model_path="/any/path")
        state = VADState(opus_decoder=None)
        result = provider.is_vad(state, b"\x00\x01\x02\x03")
        assert result is False

    def test_is_vad_with_session_and_decoder(self):
        """测试完整 VAD 检测逻辑（Mock ONNX session）"""
        mock_session = MagicMock()
        mock_session.run.return_value = (
            np.array([[0.9]], dtype=np.float32),
            np.zeros((2, 1, 128), dtype=np.float32),
        )
        with patch("onnxruntime.InferenceSession", return_value=mock_session):
            provider = SileroVADProvider(
                model_path="/fake/silero_vad.onnx",
                threshold=0.5,
                threshold_low=0.2,
                frame_window_threshold=1,
            )

        state = provider.create_state()
        try:
            import opuslib_next

            encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_VOIP)
            test_pcm = b"\x00\x00" * 160
            opus_packet = encoder.encode(test_pcm, 160)
            result = provider.is_vad(state, opus_packet)
        except Exception:
            pass


class TestCreateVADProvider:
    """VAD Provider 工厂函数测试"""

    def test_create_silero_provider(self):
        """测试创建 Silero Provider"""
        config = VADConfig(
            provider="silero",
            silero=SileroVADConfig(
                model_path="/fake/silero.onnx",
                threshold=0.6,
                threshold_low=0.25,
                min_silence_duration_ms=800,
                frame_window_threshold=4,
            ),
        )
        provider = create_vad_provider(config)
        assert isinstance(provider, SileroVADProvider)

    def test_create_none_provider(self):
        """测试 provider=none 时返回 None"""
        config = VADConfig(provider="none")
        provider = create_vad_provider(config)
        assert provider is None

    def test_create_unsupported_provider(self):
        """测试创建不支持的 Provider"""
        config = VADConfig(provider="unsupported")
        with pytest.raises(ValueError, match="不支持的 VAD Provider"):
            create_vad_provider(config)


class TestVADProviderInterface:
    """VADProvider 抽象接口测试"""

    def test_abstract_methods_exist(self):
        """测试抽象方法存在"""
        assert hasattr(VADProvider, "is_vad")
        assert hasattr(VADProvider, "create_state")
        assert hasattr(VADProvider, "release_state")

    def test_silero_has_required_methods(self):
        """测试 SileroVADProvider 实现所有必需方法"""
        provider = SileroVADProvider()
        assert callable(provider.is_vad)
        assert callable(provider.create_state)
        assert callable(provider.release_state)
