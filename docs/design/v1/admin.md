# V1 §6 管理后台

> 摘自 `V1_DESIGN.md` §6，实现 `admin/` 时参考。

## 6.1 后端 API (FastAPI)

### 认证 API

```
POST /api/auth/register
  Body: { "phone": "138xxx", "password": "xxx", "familyName": "张家" }
  Response: { "token": "jwt...", "familyId": "uuid", "memberId": "uuid" }

POST /api/auth/login
  Body: { "phone": "138xxx", "password": "xxx" }
  Response: { "token": "jwt...", "familyId": "uuid" }

POST /api/auth/refresh
  Headers: Authorization: Bearer {token}
  Response: { "token": "new_jwt..." }
```

### 设备管理 API

```
GET /api/devices
  Headers: Authorization: Bearer {token}
  Response: { "devices": [...] }

POST /api/devices/bind
  Body: { "deviceId": "dev001", "name": "客厅设备" }
  Response: { "device": { "id": "dev001", "authToken": "xxx" } }

DELETE /api/devices/{deviceId}
  Response: { "ok": true }

GET /api/devices/{deviceId}/config
  Response: { "voiceId": "longxiaochun", "volume": 70, "wakeWord": "你好小伙伴" }

PUT /api/devices/{deviceId}/config
  Body: { "voiceId": "longhua", "volume": 80 }
  Response: { "ok": true }
```

### 家庭成员 API

```
GET /api/members
  Response: { "members": [...] }

POST /api/members
  Body: { "name": "小明", "role": "child" }
  Response: { "member": { "id": "uuid", ... } }
```

## 6.2 前端 (React)

V1 MVP 页面：

| 页面 | 路由 | 功能 |
|------|------|------|
| 登录 | `/login` | 手机号 + 密码登录 |
| 注册 | `/register` | 创建家庭账号 |
| 首页/设备列表 | `/` | 显示已绑定设备列表和在线状态 |
| 绑定设备 | `/devices/bind` | 输入设备 ID 绑定 |
| 设备配置 | `/devices/:id` | 修改音色、音量、唤醒词 |

## 6.3 管理后台部署

管理后台作为独立 FastAPI 服务运行，与 nanobot gateway 共享数据目录：

```bash
nanobot gateway                        # 启动 nanobot + 硬件 MQTT Channel（端口 18790）
cd admin/backend && uvicorn main:app   # 启动管理后台（端口 8080）
```
