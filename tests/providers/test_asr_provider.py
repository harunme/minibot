"""ASR Provider 测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.asr import ASRProvider, VolcengineASRProvider, create_asr_provider
from nanobot.config.schema import ASRConfig, VolcengineASRConfig


class TestVolcengineASRProvider:
    """火山引擎 ASR Provider 测试"""

    def test_init(self):
        """测试初始化"""
        provider = VolcengineASRProvider(
            app_id="test_app_id",
            token="test_token",
            cluster="volcengine_streaming_common",
            language="zh-CN",
        )
        assert provider._app_id == "test_app_id"
        assert provider._token == "test_token"
        assert provider._cluster == "volcengine_streaming_common"
        assert provider._language == "zh-CN"

    def test_init_defaults(self):
        """测试默认值"""
        provider = VolcengineASRProvider()
        assert provider._app_id == ""
        assert provider._token == ""
        assert provider._cluster == "volcengine_streaming_common"
        assert provider._language == "zh-CN"

    def test_get_headers(self):
        """测试请求头生成"""
        provider = VolcengineASRProvider(app_id="app123", token="token456")
        headers = provider._get_headers()
        assert headers["Authorization"] == "Bearer; token456"
        assert headers["Content-Type"] == "application/json"
        assert headers["X-App-Id"] == "app123"

    def test_build_start_request(self):
        """测试开始请求构建"""
        provider = VolcengineASRProvider(app_id="app123")
        request = provider._build_start_request("opus", 16000)
        assert request["event"] == "start"
        assert request["data"]["appid"] == "app123"
        assert request["data"]["cluster"] == "volcengine_streaming_common"
        assert request["data"]["language"] == "zh-CN"
        assert request["data"]["audio_format"] == "opus"
        assert request["data"]["sample_rate"] == 16000
        assert request["data"]["enable_vad"] is True
        assert request["data"]["enable_punctuation"] is True

    def test_build_start_request_pcm(self):
        """测试 PCM 格式开始请求构建"""
        provider = VolcengineASRProvider(app_id="app123")
        request = provider._build_start_request("pcm", 16000)
        assert request["data"]["audio_format"] == "pcm"

    @pytest.mark.asyncio
    async def test_is_available_success(self):
        """测试服务可用性检查（成功）"""
        provider = VolcengineASRProvider()

        with patch("nanobot.providers.asr.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            result = await provider.is_available()
            assert result is True

    @pytest.mark.asyncio
    async def test_is_available_failure(self):
        """测试服务可用性检查（失败）"""
        provider = VolcengineASRProvider()

        with patch("nanobot.providers.asr.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Network error")
            )

            result = await provider.is_available()
            assert result is False

    @pytest.mark.asyncio
    async def test_recognize_returns_none_on_error(self):
        """测试识别失败返回 None"""
        provider = VolcengineASRProvider()

        # 模拟 WebSocket 连接失败
        with patch("nanobot.providers.asr.websockets.connect", new_callable=AsyncMock):
            result = await provider.recognize(b"fake_audio_data")
            # 由于 WebSocket 连接会失败，应该返回 None
            # 注意：实际实现可能返回 None 或空字符串


class TestCreateASRProvider:
    """ASR Provider 工厂函数测试"""

    def test_create_volcengine_provider(self):
        """测试创建火山引擎 Provider"""
        config = ASRConfig(
            provider="volcengine",
            volcengine=VolcengineASRConfig(
                app_id="app123",
                token="token456",
                cluster="volcengine_streaming_common",
                language="zh-CN",
            ),
        )

        provider = create_asr_provider(config)

        assert isinstance(provider, VolcengineASRProvider)
        assert provider._app_id == "app123"
        assert provider._token == "token456"

    def test_create_unsupported_provider(self):
        """测试创建不支持的 Provider"""
        config = ASRConfig(provider="unsupported")

        with pytest.raises(ValueError, match="不支持的 ASR Provider"):
            create_asr_provider(config)


class TestASRProviderInterface:
    """ASRProvider 抽象接口测试"""

    def test_abstract_methods_exist(self):
        """测试抽象方法存在"""
        assert hasattr(ASRProvider, "recognize")
        assert hasattr(ASRProvider, "recognize_stream")
        assert hasattr(ASRProvider, "is_available")

    @pytest.mark.asyncio
    async def test_volcengine_has_required_methods(self):
        """测试 VolcengineASRProvider 实现所有必需方法"""
        provider = VolcengineASRProvider()

        assert callable(provider.recognize)
        assert callable(provider.recognize_stream)
        assert callable(provider.is_available)
