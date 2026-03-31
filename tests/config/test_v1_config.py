"""V1 配置扩展测试"""

from __future__ import annotations

from nanobot.config.schema import (
    ASRConfig,
    TTSConfig,
    VolcengineASRConfig,
    VolcengineTTSConfig,
    WebSocketChannelConfig,
)


class TestVolcengineASRConfig:
    """火山引擎 ASR 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = VolcengineASRConfig()
        assert config.app_key == ""
        assert config.access_key == ""
        assert config.language == "zh-CN"

    def test_camel_case_parsing(self):
        """测试 camelCase 解析"""
        config = VolcengineASRConfig(
            **{"appKey": "key123", "accessKey": "secret456"}
        )
        assert config.app_key == "key123"
        assert config.access_key == "secret456"

    def test_snake_case_parsing(self):
        """测试 snake_case 解析"""
        config = VolcengineASRConfig(
            app_key="key123",
            access_key="secret456",
        )
        assert config.app_key == "key123"
        assert config.access_key == "secret456"


class TestVolcengineTTSConfig:
    """火山引擎 TTS 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = VolcengineTTSConfig()
        assert config.appid == ""
        assert config.token == ""
        assert config.authorization == "Bearer "
        assert config.cluster == "volcano_tts"
        assert config.default_voice == "zh_female_cancan_mars_bigtts"


class TestASRConfig:
    """ASR 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = ASRConfig()
        assert config.provider == "volcengine"
        assert isinstance(config.volcengine, VolcengineASRConfig)

    def test_provider_selection(self):
        """测试 Provider 选择"""
        config = ASRConfig(provider="volcengine")
        assert config.provider == "volcengine"


class TestTTSConfig:
    """TTS 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = TTSConfig()
        assert config.provider == "volcengine"
        assert isinstance(config.volcengine, VolcengineTTSConfig)

    def test_provider_selection(self):
        """测试 Provider 选择"""
        config = TTSConfig(provider="volcengine")
        assert config.provider == "volcengine"


class TestWebSocketChannelConfig:
    """WebSocket Channel 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = WebSocketChannelConfig()
        assert config.enabled is False
        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.auth_key == ""
        assert config.max_connections == 100
        assert config.timeout_seconds == 120
        assert config.audio_format == "opus"
        assert config.allow_from == ["*"]

    def test_camel_case_parsing(self):
        """测试 camelCase 解析"""
        config = WebSocketChannelConfig(**{
            "authKey": "my_secret",
            "maxConnections": 50,
        })
        assert config.auth_key == "my_secret"
        assert config.max_connections == 50

    def test_allow_from_all(self):
        """测试允许所有设备"""
        config = WebSocketChannelConfig(allow_from=["*"])
        assert config.allow_from == ["*"]

    def test_allow_from_specific(self):
        """测试允许特定设备"""
        config = WebSocketChannelConfig(allow_from=["device001", "device002"])
        assert len(config.allow_from) == 2
        assert "device001" in config.allow_from
