"""TTS Provider 测试"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import TTSConfig, VolcengineTTSConfig
from nanobot.providers.tts import TTSProvider, VolcengineTTSProvider, create_tts_provider


class TestVolcengineTTSProvider:
    """火山引擎 TTS Provider 测试（参考 xiaozhi doubao.py 实现）"""

    def test_init(self):
        """测试初始化"""
        provider = VolcengineTTSProvider(
            appid="test_appid",
            token="test_token",
            authorization="Bearer ",
            cluster="volcano_tts",
            default_voice="zh_female_cancan_mars_bigtts",
        )
        assert provider._appid == "test_appid"
        assert provider._token == "test_token"
        assert provider._authorization == "Bearer "
        assert provider._cluster == "volcano_tts"
        assert provider._default_voice == "zh_female_cancan_mars_bigtts"

    def test_init_defaults(self):
        """测试默认值"""
        provider = VolcengineTTSProvider()
        assert provider._appid == ""
        assert provider._token == ""
        assert provider._authorization == "Bearer "
        assert provider._cluster == "volcano_tts"
        assert provider._default_voice == "zh_female_cancan_mars_bigtts"

    def test_get_headers(self):
        """测试请求头生成（Authorization: {authorization}{token}）"""
        provider = VolcengineTTSProvider(appid="app123", token="token456", authorization="Bearer ")
        headers = provider._get_headers()
        assert headers["Authorization"] == "Bearer token456"
        assert headers["Content-Type"] == "application/json"
        # X-App-Id 已废弃（对比旧实现）

    def test_get_headers_no_bearer_prefix(self):
        """测试无 Bearer 前缀时的 header"""
        provider = VolcengineTTSProvider(appid="app123", token="token456", authorization="")
        headers = provider._get_headers()
        assert headers["Authorization"] == "token456"

    def test_build_request(self):
        """测试请求体构建（app/audio/request 嵌套格式）"""
        provider = VolcengineTTSProvider(appid="app123", token="tok", cluster="volcano_tts")
        request = provider._build_request(
            text="你好",
            voice="zh_female_cancan_mars_bigtts",
            audio_format="pcm",
            speed_ratio=1.0,
            volume_ratio=1.0,
            pitch_ratio=1.0,
        )
        assert request["app"]["appid"] == "app123"
        assert request["app"]["token"] == "tok"
        assert request["app"]["cluster"] == "volcano_tts"
        assert request["audio"]["voice_type"] == "zh_female_cancan_mars_bigtts"
        assert request["audio"]["encoding"] == "pcm"
        assert request["audio"]["speed_ratio"] == 1.0
        assert request["audio"]["volume_ratio"] == 1.0
        assert request["audio"]["pitch_ratio"] == 1.0
        assert request["request"]["text"] == "你好"
        assert request["request"]["text_type"] == "plain"
        assert request["request"]["operation"] == "query"
        assert "reqid" in request["request"]

    def test_build_request_wav_format(self):
        """测试 WAV 格式请求构建"""
        provider = VolcengineTTSProvider(appid="app123")
        request = provider._build_request(
            text="hello",
            voice="zh_female_cancan_mars_bigtts",
            audio_format="wav",
            speed_ratio=0.8,
            volume_ratio=1.5,
            pitch_ratio=1.2,
        )
        assert request["audio"]["encoding"] == "wav"
        assert request["audio"]["speed_ratio"] == 0.8
        assert request["audio"]["volume_ratio"] == 1.5
        assert request["audio"]["pitch_ratio"] == 1.2

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

    @pytest.mark.asyncio
    async def test_synthesize_success(self):
        """测试成功合成（返回 base64 编码的音频）"""
        provider = VolcengineTTSProvider(appid="app123", token="tok")
        audio_bytes = b"\x00\x01\x02\x03\x04\x05"
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"code": 1000, "data": b64_audio})

        with patch("nanobot.providers.tts.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            chunks = []
            async for chunk in provider.synthesize("你好"):
                chunks.append(chunk)

            assert len(chunks) > 0
            assert b"".join(chunks) == audio_bytes

    @pytest.mark.asyncio
    async def test_synthesize_http_error(self):
        """测试 HTTP 错误时正确处理"""
        provider = VolcengineTTSProvider(appid="app123", token="tok")
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch("nanobot.providers.tts.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            chunks = []
            async for chunk in provider.synthesize("你好"):
                chunks.append(chunk)

            assert chunks == []

    @pytest.mark.asyncio
    async def test_synthesize_server_error(self):
        """测试服务端返回错误码时正确处理"""
        provider = VolcengineTTSProvider(appid="app123", token="tok")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"code": 1001, "message": "invalid request"})

        with patch("nanobot.providers.tts.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            chunks = []
            async for chunk in provider.synthesize("你好"):
                chunks.append(chunk)

            assert chunks == []

    @pytest.mark.asyncio
    async def test_synthesize_no_data(self):
        """测试响应无 audio 数据时正确处理"""
        provider = VolcengineTTSProvider(appid="app123", token="tok")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"code": 1000})

        with patch("nanobot.providers.tts.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            chunks = []
            async for chunk in provider.synthesize("你好"):
                chunks.append(chunk)

            assert chunks == []

    @pytest.mark.asyncio
    async def test_synthesize_chunks_large_audio(self):
        """测试大音频分块输出"""
        provider = VolcengineTTSProvider(appid="app123", token="tok")
        # 模拟大于 8192 bytes 的音频
        large_audio = b"\x00" * 20000
        b64_audio = base64.b64encode(large_audio).decode("utf-8")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"code": 1000, "data": b64_audio})

        with patch("nanobot.providers.tts.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            chunks = []
            async for chunk in provider.synthesize("长文本"):
                chunks.append(chunk)

            # 20000 / 8192 = 3 chunks（最后一包 2016 bytes）
            assert len(chunks) == 3
            assert sum(len(c) for c in chunks) == 20000
            assert b"".join(chunks) == large_audio


class TestCreateTTSProvider:
    """TTS Provider 工厂函数测试"""

    def test_create_volcengine_provider(self):
        """测试创建火山引擎 Provider"""
        config = TTSConfig(
            provider="volcengine",
            volcengine=VolcengineTTSConfig(
                appid="app123",
                token="token456",
                authorization="Bearer ",
                cluster="volcano_tts",
                default_voice="zh_female_cancan_mars_bigtts",
            ),
        )

        provider = create_tts_provider(config)

        assert isinstance(provider, VolcengineTTSProvider)
        assert provider._appid == "app123"
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
