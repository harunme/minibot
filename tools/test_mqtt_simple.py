#!/usr/bin/env python3
"""简单的 MQTT 连接测试脚本"""

import asyncio
import sys

async def test_mqtt():
    try:
        import aiomqtt
    except ImportError:
        print("需要安装 aiomqtt: pip install aiomqtt")
        return

    print("测试 MQTT 连接...\n")

    broker = input("Broker 地址 [localhost]: ").strip() or "localhost"
    port = int(input("端口 [1883]: ").strip() or "1883")
    device_id = input("设备 ID [test001]: ").strip() or "test001"
    username = input("用户名 [空]: ").strip()
    password = input("密码 [空]: ").strip()

    print(f"\n连接 {broker}:{port} ...")

    try:
        async with aiomqtt.Client(
            identifier=f"device_{device_id}",
            hostname=broker,
            port=port,
            username=username or None,
            password=password or None,
        ) as client:
            print("✓ 连接成功!\n")

            # 菜单
            while True:
                print("1. 上报在线状态")
                print("2. 订阅下行消息")
                print("3. 发送测试消息")
                print("4. 退出")
                choice = input("\n选择: ").strip()

                if choice == "1":
                    import json
                    import time
                    payload = json.dumps({
                        "status": "online",
                        "battery": 85,
                        "signal": -50,
                        "firmware": "1.0.0-test",
                        "uptime": int(time.time()),
                        "ts": int(time.time() * 1000),
                    })
                    await client.publish(f"device/{device_id}/status", payload.encode(), qos=1)
                    print(f"✓ 已上报状态到 device/{device_id}/status")

                elif choice == "2":
                    print(f"订阅 device/{device_id}/# (Ctrl+C 退出订阅)")
                    await client.subscribe(f"device/{device_id}/#", qos=0)
                    async for message in client.messages:
                        print(f"收到: {message.topic} -> {message.payload[:100]}")

                elif choice == "3":
                    import json
                    topic = input("Topic: ").strip() or f"device/{device_id}/ctrl/down"
                    msg = input("消息 JSON: ").strip() or '{"type":"test","content":"hello"}'
                    await client.publish(topic, msg.encode())
                    print(f"✓ 已发送")

                elif choice == "4":
                    break

    except Exception as e:
        print(f"✗ 连接失败: {e}")

if __name__ == "__main__":
    asyncio.run(test_mqtt())
