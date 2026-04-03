"""文本规范化工具 — 将 Markdown 内容转换为 TTS 友好格式。

职责：
- 移除或转换 Markdown 语法（表格、代码块、列表等）
- 口语化数字、百分比、符号
- 输出纯文本，供 TTS 引擎直接合成

注意：本模块专注文本转换，不做发音时长、SSML 等高级处理。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class NormalizeOptions:
    """normalize_for_tts 的选项。"""

    # 是否跳过代码块内容（True = 只说"以下为代码"，不读代码内容）
    strip_code_blocks: bool = True
    # 表格转线性描述时的列分隔符
    table_separator: str = "；"


# ----------------------------------------------------------------------
# Markdown 元素转换规则
# ----------------------------------------------------------------------


def _strip_inline_markdown(text: str) -> str:
    """移除行内 Markdown 语法（加粗、斜体、行内代码、链接）。"""
    # 链接 [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # 行内代码 `code` → "代码"
    text = re.sub(r"`([^`]+)`", r"代码", text)
    # 加粗 **text** / __text__ → text
    text = re.sub(r"\*\*([^\*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    # 斜体 *text* / _text_ → text
    text = re.sub(r"\*(?!\*)([^\*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"\1", text)
    # 删除线 ~~text~~ → text
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    return text


def _normalize_tables(text: str, separator: str = "；") -> str:
    """将 Markdown 表格转换为线性描述。"""
    lines = text.split("\n")
    result_lines: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        # 检测 Markdown 表格分隔行（|---|---|）
        if re.match(r"^\|[\s\-:|]+\|$", line) or re.match(r"^\|[\s\-:|]+$", line):
            # 前一行是表头，尝试提取列名
            if result_lines and "|" in result_lines[-1]:
                header_line = result_lines[-1]
                # 解析表头列名
                cols = [c.strip() for c in header_line.split("|") if c.strip()]
                result_lines.pop()  # 移除原始表头行
                col_count = len(cols)

                # 消费表头后面的所有数据行
                i += 1  # 跳过分隔行
                data_rows: list[list[str]] = []
                while i < len(lines) and "|" in lines[i]:
                    cells = [c.strip() for c in lines[i].split("|") if c.strip()]
                    data_rows.append(cells)
                    i += 1
                # i 会由外层 while 再次递增，这里先减一补偿
                i -= 1

                if data_rows:
                    for row in data_rows:
                        parts = []
                        for j, col_name in enumerate(cols):
                            val = row[j] if j < len(row) else ""
                            parts.append(f"{col_name}为{val}")
                        result_lines.append(separator.join(parts) + "。")
            i += 1
            continue

        # 跳过纯分隔线行（不在表格上下文中的）
        if re.match(r"^\|[\s\-:|]+\|$", line) or re.match(r"^\|[\s\-:|]+$", line):
            i += 1
            continue

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines)


def _normalize_code_blocks(text: str) -> str:
    """将代码块替换为"以下为代码"的提示。"""
    # 匹配 ```language\n...``` 或 ```\n...```
    result = re.sub(
        r"```[\w]*\n([\s\S]*?)```",
        "以下为代码。",
        text,
    )
    return result


def _normalize_list_items(text: str) -> str:
    """将 Markdown 列表（- / 1. / *）转换为口语化描述。"""
    lines = text.split("\n")
    result_lines: list[str] = []
    in_list = False
    counter = 0

    for line in lines:
        stripped = line.strip()

        # 有序列表：1. 2. 3.
        ordered_match = re.match(r"^(\d+)?[.、]\s+(.*)", stripped)
        if ordered_match:
            if not in_list:
                in_list = True
                counter = 0
            counter += 1
            content = ordered_match.group(2).strip()
            ordinals = ["第一", "第二", "第三", "第四", "第五",
                        "第六", "第七", "第八", "第九", "第十"]
            prefix = ordinals[counter - 1] if counter <= 10 else f"第{counter}"
            result_lines.append(f"{prefix}，{content}")
            continue

        # 无序列表：- / * / +
        unordered_match = re.match(r"^[-\*+]\s+(.*)", stripped)
        if unordered_match:
            if not in_list:
                in_list = True
                counter = 0
            counter += 1
            content = unordered_match.group(1).strip()
            ordinals = ["第一", "第二", "第三", "第四", "第五",
                        "第六", "第七", "第八", "第九", "第十"]
            prefix = ordinals[counter - 1] if counter <= 10 else f"第{counter}"
            result_lines.append(f"{prefix}，{content}")
            continue

        # 非列表行，重置状态
        in_list = False
        counter = 0
        result_lines.append(line)

    return "\n".join(result_lines)


def _normalize_numbers_and_symbols(text: str) -> str:
    """数字、百分比、符号口语化。"""
    # 百分比
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", lambda m: _num_to_chinese(m.group(1)) + "百分之", text)
    # 分数 如 1/2
    text = re.sub(r"(\d+)\s*/\s*(\d+)", lambda m: f"{_num_to_chinese(m.group(1))}分之{_num_to_chinese(m.group(2))}", text)
    # 箭头 → ← ↑ ↓
    text = text.replace("→", "到")
    text = text.replace("←", "返回")
    text = text.replace("↑", "上升")
    text = text.replace("↓", "下降")
    # 省略号
    text = text.replace("…", "等等")
    text = text.replace("...", "等等")
    return text


def _num_to_chinese(num_str: str) -> str:
    """将纯数字字符串转为中文读法（支持整数和小数）。"""
    try:
        if "." in num_str:
            parts = num_str.split(".")
            integer = _int_to_chinese(parts[0])
            decimal = "".join(_DIGIT_NAMES[int(d)] for d in parts[1])
            return f"{integer}点{decimal}"
        else:
            return _int_to_chinese(num_str)
    except (ValueError, IndexError):
        return num_str


def _int_to_chinese(num_str: str) -> str:
    """将整数字符串转为中文读法。"""
    if num_str.startswith("-"):
        return "负" + _int_to_chinese(num_str[1:])
    num = int(num_str)
    if num == 0:
        return "零"

    units = ["", "万", "亿"]
    result = ""
    chunk_idx = 0

    while num > 0:
        chunk = num % 10000
        if chunk != 0 or result == "":
            chunk_str = _chunk_to_chinese(chunk)
            result = chunk_str + units[chunk_idx] + result
        num //= 10000
        chunk_idx += 1

    return result or "零"


def _chunk_to_chinese(chunk: int) -> str:
    """将 0~9999 的整数转为中文（不含万/亿单位）。"""
    if chunk == 0:
        return ""
    digits = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    result = ""
    pos_names = ["", "十", "百", "千"]

    idx = 0
    while chunk > 0:
        digit = chunk % 10
        if digit != 0:
            if idx == 1 and digit == 1 and result == "":
                # 十几 → 十而不是一十几
                result = pos_names[idx] + result
            else:
                result = digits[digit] + pos_names[idx] + result
        elif result and not result.startswith("零"):
            result = "零" + result
        chunk //= 10
        idx += 1

    return result


_DIGIT_NAMES = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


def _normalize_headers(text: str) -> str:
    """将 Markdown 标题前缀转换为口语化语调标记（当前为简化处理）。"""
    lines = text.split("\n")
    result_lines: list[str] = []
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            content = m.group(2).strip()
            result_lines.append(content)  # 降调处理：只保留内容，不读井号
        else:
            result_lines.append(line)
    return "\n".join(result_lines)


def _collapse_blank_lines(text: str) -> str:
    """将连续空行/只含空白字符的行压缩为单行。"""
    lines = text.split("\n")
    result: list[str] = []
    prev_blank = False
    for line in lines:
        if not line.strip():
            if not prev_blank:
                result.append("")
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False
    return "\n".join(result).strip()


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------


def normalize_for_tts(text: str, *, options: NormalizeOptions | None = None) -> str:
    """将 Markdown 内容转换为 TTS 友好纯文本。

    转换顺序：
    1. 代码块 → "以下为代码"
    2. 表格 → 线性描述
    3. 标题 → 去除井号
    4. 列表 → "第一，第二，..." 格式
    5. 行内格式（加粗/链接等）→ 纯文本
    6. 数字/符号 → 口语化
    7. 多余空行压缩

    Args:
        text: 原始 Markdown 文本
        options: 规范化选项

    Returns:
        TTS 友好的纯文本
    """
    if not text:
        return text

    opts = options or NormalizeOptions()
    t = text

    t = _normalize_code_blocks(t)
    t = _normalize_tables(t, separator=opts.table_separator)
    t = _normalize_headers(t)
    t = _normalize_list_items(t)
    t = _strip_inline_markdown(t)
    t = _normalize_numbers_and_symbols(t)
    t = _collapse_blank_lines(t)

    return t
