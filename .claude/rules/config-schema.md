---
paths:
  - "nanobot/config/schema.py"
---

# 配置 Schema 修改规则

- **仅允许追加字段/新类，不允许修改已有字段**
- 新增配置类继承项目中的 `Base` 类（支持 camelCase/snake_case 双向兼容）
- 所有字段必须有类型标注和默认值
- 参考 `docs/design/V1_DESIGN.md` §8 章节
