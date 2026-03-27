"""V1 配置扩展测试"""

from __future__ import annotations

import pytest

from nanobot.config.schema import (
    ASRConfig,
    HardwareChannelConfig,
    TTSConfig,
    VolcengineASRConfig,
    VolcengineTTSConfig,
)


class TestVolcengineASRConfig:
    """火山引擎 ASR 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = VolcengineASRConfig()
        assert config.app_id == ""
        assert config.token == ""
        assert config.cluster == "volcengine_streaming_common"
        assert config.language == "zh-CN"

    def test_camel_case_parsing(self):
        """测试 camelCase 解析"""
        # Pydantic 的 alias_generator 支持 camelCase
        config = VolcengineASRConfig(
            **{"appId": "app123", "token": "token456"}
        )
        assert config.app_id == "app123"
        assert config.token == "token456"

    def test_snake_case_parsing(self):
        """测试 snake_case 解析"""
        config = VolcengineASRConfig(
            app_id="app123",
            token="token456",
        )
        assert config.app_id == "app123"
        assert config.token == "token456"


class TestVolcengineTTSConfig:
    """火山引擎 TTS 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = VolcengineTTSConfig()
        assert config.app_id == ""
        assert config.token == ""
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


class TestHardwareChannelConfig:
    """Hardware Channel 配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = HardwareChannelConfig()
        assert config.enabled is False
        assert config.mqtt_host == "localhost"
        assert config.mqtt_port == 1883
        assert config.mqtt_username == ""
        assert config.mqtt_password == ""
        assert config.mqtt_tls is False
        assert config.audio_format == "opus"
        assert config.max_devices == 100
        assert config.allow_from == ["*"]

    def test_camel_case_parsing(self):
        """测试 camelCase 解析"""
        config = HardwareChannelConfig(**{
            "mqttHost": "broker.example.com",
            "mqttPort": 8883,
        })
        assert config.mqtt_host == "broker.example.com"
        assert config.mqtt_port == 8883

    def test_allow_from_all(self):
        """测试允许所有设备"""
        config = HardwareChannelConfig(allow_from=["*"])
        assert config.allow_from == ["*"]

    def test_allow_from_specific(self):
        """测试允许特定设备"""
        config = HardwareChannelConfig(allow_from=["device001", "device002"])
        assert len(config.allow_from) == 2
        assert "device001" in config.allow_from
