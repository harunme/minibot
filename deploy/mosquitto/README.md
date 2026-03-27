# MiniBot MQTT Broker 部署指南

本文档说明如何启动 Mosquitto MQTT Broker（开发环境）。

## 快速启动

### 方式 1: Docker（推荐）

```bash
# 创建密码文件（首次）
docker run -it --rm \
  -v $(pwd)/mosquitto.conf:/mosquitto/config/mosquitto.conf \
  -v $(pwd)/data:/mosquitto/data \
  -v $(pwd)/log:/mosquitto/log \
  eclipse-mosquitto:2 mosquitto -c /mosquitto/config/mosquitto.conf

# 启动（后台运行）
docker run -d \
  --name minibot-mosquitto \
  -p 1883:1883 \
  -p 9001:9001 \
  -v $(pwd)/mosquitto.conf:/mosquitto/config/mosquitto.conf \
  -v $(pwd)/data:/mosquitto/data \
  -v $(pwd)/log:/mosquitto/log \
  eclipse-mosquitto:2
```

### 方式 2: Homebrew（macOS 开发环境）

```bash
# 安装
brew install mosquitto

# 配置（使用本目录的配置文件）
# 编辑 /opt/homebrew/etc/mosquitto/mosquitto.conf 或创建自定义配置

# 启动
mosquitto -c deploy/mosquitto/mosquitto.conf
```

## 密码文件管理

### 创建密码文件

```bash
# 创建用户（首次需要创建新文件）
mosquitto_passwd -c pwfile minibot
# 输入密码后按回车

# 添加更多用户
mosquitto_passwd -b pwfile device001 mypassword
mosquitto_passwd -b pwfile device002 mypassword
```

### 验证连接

```bash
# 测试订阅
mosquitto_sub -h localhost -p 1883 -u minibot -P yourpassword -t "device/+/audio/up" -v

# 测试发布
mosquitto_pub -h localhost -p 1883 -u minibot -P yourpassword -t "device/test001/ctrl/down" -m '{"type":"text","content":"Hello"}'
```

## 配置说明

### 连接参数（参考 docs/design/v1/mqtt-channel.md）

| 参数 | 值 |
|------|-----|
| Broker | mqtt://localhost:1883 |
| Protocol | MQTT |
| Clean Session | false |
| Keep Alive | 60s |
| Auth | username/password |

### Topic 结构

| Topic | QoS | 说明 |
|-------|-----|------|
| device/{id}/audio/up | 0 | 上行音频帧 |
| device/{id}/audio/down | 0 | 下行音频帧 |
| device/{id}/ctrl/up | 1 | 上行控制消息 |
| device/{id}/ctrl/down | 1 | 下行控制指令 |
| device/{id}/status | 1 | 设备状态上报 |

## 生产环境

生产环境建议使用 EMQX，支持：
- JWT Token 认证
- 百万级设备连接
- 规则引擎
- Web Dashboard

详见 EMQX 部署文档。
