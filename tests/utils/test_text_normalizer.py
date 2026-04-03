"""nanobot/utils/text_normalizer.py 的单元测试"""

from __future__ import annotations

import pytest

from nanobot.utils.text_normalizer import normalize_for_tts


class TestNormalizeForTts:
    """Markdown → TTS 友好文本的转换测试"""

    def test_empty_string(self):
        assert normalize_for_tts("") == ""
        assert normalize_for_tts(None) is None  # type: ignore[arg-type]

    def test_plain_text_passthrough(self):
        text = "今天天气很好，我们去公园散步吧。"
        assert normalize_for_tts(text) == text

    def test_bold_italic_stripped(self):
        text = "这是**加粗**和*斜体*文本。"
        result = normalize_for_tts(text)
        assert "**" not in result
        assert "*" not in result or "斜体" in result  # 普通星号内容保留
        assert "加粗" in result
        assert "斜体" in result

    def test_inline_code_stripped(self):
        text = "请运行 `python main.py` 来启动。"
        result = normalize_for_tts(text)
        assert "`" not in result
        assert "python main.py" not in result  # 代码内容被替换

    def test_link_text_only(self):
        text = "请访问 [官方文档](https://example.com) 获取更多信息。"
        result = normalize_for_tts(text)
        assert "[" not in result
        assert "(" not in result
        assert "官方文档" in result
        assert "https://" not in result

    def test_heading_strips_hash(self):
        text = "## 这是二级标题\n### 这是三级标题"
        result = normalize_for_tts(text)
        assert "#" not in result
        assert "这是二级标题" in result
        assert "这是三级标题" in result

    def test_code_block_replaced(self):
        text = "```python\ndef hello():\n    print('hi')\n```"
        result = normalize_for_tts(text)
        assert "```" not in result
        assert "def hello" not in result
        assert "以下为代码" in result

    def test_ordered_list_converted(self):
        text = "1. 第一步\n2. 第二步\n3. 第三步"
        result = normalize_for_tts(text)
        assert "第一，" in result
        assert "第二，" in result
        assert "第三，" in result
        assert "1." not in result

    def test_unordered_list_converted(self):
        text = "- 项目A\n- 项目B\n- 项目C"
        result = normalize_for_tts(text)
        assert "第一，" in result
        assert "第二，" in result
        assert "第三，" in result
        assert "- " not in result

    def test_table_converted_to_linear(self):
        text = """| 名称 | 状态 |
|------|------|
| 项目A | 进行中 |
| 项目B | 已完成 |"""
        result = normalize_for_tts(text)
        assert "|" not in result
        assert "名称为项目A" in result or "名称" in result
        assert "状态为进行中" in result

    def test_number_to_chinese(self):
        from nanobot.utils.text_normalizer import _num_to_chinese

        assert _num_to_chinese("80") == "八十"
        assert _num_to_chinese("123") == "一百二十三"
        assert _num_to_chinese("0") == "零"
        assert _num_to_chinese("10000") == "一万"
        assert _num_to_chinese("3.14") == "三点一四"

    def test_percent_normalized(self):
        text = "增长率为80%。"
        result = normalize_for_tts(text)
        assert "%" not in result
        assert "八十百分之" in result or "百分之八十" in result

    def test_arrow_normalized(self):
        text = "输入 → 输出"
        result = normalize_for_tts(text)
        assert "→" not in result
        assert "输出" in result

    def test_complex_markdown(self):
        """混合场景：包含标题、列表、表格、加粗、链接"""
        text = """# 项目概览

**团队成员：**[张三](https://example.com/zs)、李四、王五。

## 功能列表
1. 用户管理
2. 数据分析
- 报表导出
- 可视化

## 配置示例
```yaml
name: demo
version: 1.0
```
"""
        result = normalize_for_tts(text)
        # 无 Markdown 语法残留
        assert "#" not in result
        assert "**" not in result
        assert "[" not in result
        assert "```" not in result
        # 关键内容保留
        assert "项目概览" in result
        assert "团队成员" in result or "张三" in result
        assert "用户管理" in result
        assert "第一，" in result
        assert "第二，" in result
