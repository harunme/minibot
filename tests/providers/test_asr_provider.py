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
            app_key="test_app_key",
            access_key="test_access_key",
            language="zh-CN",
        )
        assert provider._app_key == "test_app_key"
        assert provider._access_key == "test_access_key"
        assert provider._language == "zh-CN"

    def test_init_defaults(self):
        """测试默认值"""
        provider = VolcengineASRProvider()
        assert provider._app_key == ""
        assert provider._access_key == ""
        assert provider._language == "zh-CN"

    def test_get_headers(self):
        """测试请求头生成（SAUC API 规范）"""
        provider = VolcengineASRProvider(app_key="app123", access_key="key456")
        headers = provider._get_headers("test-connect-id")
        assert headers["X-Api-App-Key"] == "app123"
        assert headers["X-Api-Access-Key"] == "key456"
        assert headers["X-Api-Resource-Id"] == "volc.bigasr.sauc.duration"
        assert headers["X-Api-Connect-Id"] == "test-connect-id"

    def test_build_init_request(self):
        """测试初始化请求构建（message_type=0）"""
        provider = VolcengineASRProvider(app_key="app123")
        request = provider._build_init_request(16000, "zh-CN")
        assert request["header"]["message_type"] == 0
        assert request["header"]["serialization"] == 1
        assert request["header"]["compression"] == 0
        assert request["payload"]["audio"]["format"] == "pcm"
        assert request["payload"]["audio"]["sample_rate"] == 16000
        assert request["payload"]["audio"]["channels"] == 1
        assert request["payload"]["audio"]["bits"] == 16
        assert request["payload"]["request"]["model_name"] == "bigmodel"
        assert request["payload"]["request"]["enable_punctuation"] is True
        assert request["payload"]["request"]["language"] == "zh-CN"

    def test_build_init_request_pcm(self):
        """测试 PCM 格式初始化请求"""
        provider = VolcengineASRProvider(app_key="app123")
        request = provider._build_init_request(16000, "en-US")
        assert request["payload"]["audio"]["format"] == "pcm"
        assert request["payload"]["request"]["language"] == "en-US"

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
            # WebSocket 连接会失败，应该返回 None
            assert result is None


class TestCreateASRProvider:
    """ASR Provider 工厂函数测试"""

    def test_create_volcengine_provider(self):
        """测试创建火山引擎 Provider（新字段）"""
        config = ASRConfig(
            provider="volcengine",
            volcengine=VolcengineASRConfig(
                app_key="app_key_123",
                access_key="access_key_456",
                language="zh-CN",
            ),
        )

        provider = create_asr_provider(config)

        assert isinstance(provider, VolcengineASRProvider)
        assert provider._app_key == "app_key_123"
        assert provider._access_key == "access_key_456"

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
