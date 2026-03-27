# V1 §5 多租户模块

> 摘自 `V1_DESIGN.md` §5，实现 `nanobot/tenant/` 时参考。

## 5.1 数据模型

### 主库 (master.db)

全局共享，存储租户索引和设备映射。

```sql
-- 家庭（租户）表
CREATE TABLE families (
    id          TEXT PRIMARY KEY,      -- UUID
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,         -- ISO 8601
    updated_at  TEXT NOT NULL,
    status      TEXT DEFAULT 'active'  -- active | suspended
);

-- 设备表
CREATE TABLE devices (
    id          TEXT PRIMARY KEY,      -- 设备唯一ID（硬件烧录）
    family_id   TEXT NOT NULL,
    name        TEXT,
    auth_token  TEXT NOT NULL,
    status      TEXT DEFAULT 'active', -- active | disabled
    last_seen   TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (family_id) REFERENCES families(id)
);

CREATE INDEX idx_devices_family ON devices(family_id);
```

### 租户库 ({family_id}.db)

每个家庭独立数据库文件。

```sql
-- 家庭成员表
CREATE TABLE members (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL,         -- parent | child
    phone       TEXT,
    password    TEXT,                  -- 密码哈希
    avatar      TEXT,
    created_at  TEXT NOT NULL
);

-- 内容元数据表
CREATE TABLE contents (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,         -- story | music | document
    title       TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    file_size   INTEGER,
    mime_type   TEXT,
    duration    INTEGER,
    metadata    TEXT,                  -- JSON 扩展字段
    uploaded_by TEXT,
    created_at  TEXT NOT NULL
);

-- 设备配置表
CREATE TABLE device_configs (
    device_id   TEXT PRIMARY KEY,
    voice_id    TEXT DEFAULT 'longxiaochun',
    volume      INTEGER DEFAULT 70,
    wake_word   TEXT DEFAULT '你好小伙伴',
    config      TEXT,                  -- JSON 扩展配置
    updated_at  TEXT NOT NULL
);
```

## 5.2 租户路由

```python
class TenantManager:
    """多租户管理器"""
    
    def get_family_by_device(self, device_id: str) -> Family | None:
        """设备 ID → 家庭（核心路由方法）"""
    
    def get_tenant_db(self, family_id: str) -> sqlite3.Connection:
        """获取租户数据库连接（带缓存）"""
    
    def create_family(self, name: str) -> Family:
        """创建新家庭（自动初始化租户库 + 文件目录 + workspace）"""
    
    def bind_device(self, device_id: str, family_id: str) -> Device:
        """绑定设备到家庭"""
    
    def unbind_device(self, device_id: str) -> None:
        """解绑设备"""
```

## 5.3 文件存储结构

```
{data_dir}/
├── master.db
├── families/
│   ├── {family_id}/
│   │   ├── tenant.db
│   │   ├── workspace/           # nanobot workspace
│   │   │   ├── sessions/
│   │   │   ├── memory/
│   │   │   └── skills/
│   │   ├── content/             # 上传内容
│   │   │   ├── stories/
│   │   │   ├── music/
│   │   │   └── documents/
│   │   └── voices/              # 音色数据（V3）
```
