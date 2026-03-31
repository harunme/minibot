"""TTS Provider 测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.tts import TTSProvider, VolcengineTTSProvider, create_tts_provider
from nanobot.config.schema import TTSConfig, VolcengineTTSConfig


class TestVolcengineTTSProvider:
    """火山引擎 TTS Provider 测试"""

    def test_init(self):
        """测试初始化"""
        provider = VolcengineTTSProvider(
            app_id="test_app_id",
            token="test_token",
            cluster="volcano_tts",
            default_voice="zh_female_cancan_mars_bigtts",
        )
        assert provider._app_id == "test_app_id"
        assert provider._token == "test_token"
        assert provider._cluster == "volcano_tts"
        assert provider._default_voice == "zh_female_cancan_mars_bigtts"

    def test_init_defaults(self):
        """测试默认值"""
        provider = VolcengineTTSProvider()
        assert provider._app_id == ""
        assert provider._token == ""
        assert provider._cluster == "volcano_tts"
        assert provider._default_voice == "zh_female_cancan_mars_bigtts"

    def test_get_headers(self):
        """测试请求头生成"""
        provider = VolcengineTTSProvider(app_id="app123", token="token456")
        headers = provider._get_headers()
        assert headers["Authorization"] == "Bearer token456"
        assert headers["Content-Type"] == "application/json"
        assert headers["X-App-Id"] == "app123"

    def test_build_start_request(self):
        """测试开始请求构建"""
        provider = VolcengineTTSProvider(app_id="app123")
        request = provider._build_start_request(
            text="你好",
            voice="zh_female_cancan_mars_bigtts",
            audio_format="opus",
            sample_rate=24000,
        )
        assert request["event"] == "start"
        assert request["data"]["appid"] == "app123"
        assert request["data"]["cluster"] == "volcano_tts"
        assert request["data"]["voice"] == "zh_female_cancan_mars_bigtts"
        assert request["data"]["text"] == "你好"
        assert request["data"]["encoding"] == "opus"
        assert request["data"]["sample_rate"] == 24000
        assert request["data"]["speed_ratio"] == 1.0
        assert request["data"]["volume_ratio"] == 1.0
        assert request["data"]["pitch_ratio"] == 1.0

    def test_build_start_request_pcm(self):
        """测试 PCM 格式开始请求构建"""
        provider = VolcengineTTSProvider(app_id="app123")
        request = provider._build_start_request(
            text="你好",
            voice="zh_female_cancan_mars_bigtts",
            audio_format="pcm",
            sample_rate=16000,
        )
        assert request["data"]["encoding"] == "pcm"

    def test_preset_voices(self):
        """测试预置音色"""
        provider = VolcengineTTSProvider()
        voices = provider._preset_voices
        assert len(voices) == 3
        assert any(v["id"] == "zh_female_cancan_mars_bigtts" for v in voices)
        assert any(v["name"] == "灿灿" for v in voices)

    @pytest.mark.asyncio
    async def test_list_voices(self):
        """测试列出可用音色"""
        provider = VolcengineTTSProvider()
        voices = await provider.list_voices()
        assert len(voices) == 3
        assert all("id" in v for v in voices)
        assert all("name" in v for v in voices)
        assert all("language" in v for v in voices)

    @pytest.mark.asyncio
    async def test_is_available_success(self):
        """测试服务可用性检查（成功）"""
        provider = VolcengineTTSProvider()

        with patch("nanobot.providers.tts.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            result = await provider.is_available()
            assert result is True

    @pytest.mark.asyncio
    async def test_is_available_failure(self):
        """测试服务可用性检查（失败）"""
        provider = VolcengineTTSProvider()

        with patch("nanobot.providers.tts.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Network error")
            )

            result = await provider.is_available()
            assert result is False

    def test_parse_audio_message_binary(self):
        """测试解析二进制音频消息"""
        provider = VolcengineTTSProvider()
        audio_data = b"\x00\x01\x02\x03\x04\x05"
        result = provider._parse_audio_message(audio_data)
        assert result == audio_data

    def test_parse_audio_message_json(self):
        """测试解析 JSON 音频消息"""
        provider = VolcengineTTSProvider()
        import base64

        audio_bytes = b"\x00\x01\x02\x03"
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        message = '{"code": 1000, "data": {"audio": "%s"}}' % audio_b64

        result = provider._parse_audio_message(message)
        assert result == audio_bytes

    def test_parse_audio_message_finished(self):
        """测试解析结束消息"""
        provider = VolcengineTTSProvider()
        message = '{"event": "finished"}'
        result = provider._parse_audio_message(message)
        assert result is None

    def test_parse_audio_message_invalid(self):
        """测试解析无效消息"""
        provider = VolcengineTTSProvider()
        result = provider._parse_audio_message("invalid json")
        assert result is None


class TestCreateTTSProvider:
    """TTS Provider 工厂函数测试"""

    def test_create_volcengine_provider(self):
        """测试创建火山引擎 Provider"""
        config = TTSConfig(
            provider="volcengine",
            volcengine=VolcengineTTSConfig(
                app_id="app123",
                token="token456",
                cluster="volcano_tts",
                default_voice="zh_female_cancan_mars_bigtts",
            ),
        )

        provider = create_tts_provider(config)

        assert isinstance(provider, VolcengineTTSProvider)
        assert provider._app_id == "app123"
        assert provider._token == "token456"

    def test_create_unsupported_provider(self):
        """测试创建不支持的 Provider"""
        config = TTSConfig(provider="unsupported")

        with pytest.raises(ValueError, match="不支持的 TTS Provider"):
            create_tts_provider(config)


class TestTTSProviderInterface:
    """TTSProvider 抽象接口测试"""

    def test_abstract_methods_exist(self):
        """测试抽象方法存在"""
        assert hasattr(TTSProvider, "synthesize")
        assert hasattr(TTSProvider, "list_voices")
        assert hasattr(TTSProvider, "is_available")

    @pytest.mark.asyncio
    async def test_volcengine_has_required_methods(self):
        """测试 VolcengineTTSProvider 实现所有必需方法"""
        provider = VolcengineTTSProvider()

        assert callable(provider.synthesize)
        assert callable(provider.list_voices)
        assert callable(provider.is_available)
