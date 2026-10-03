# -*- coding: utf-8 -*-
"""源管家 · 分区管理模块（pyinj_sections）
=========================================
以「新增模块」方式扩展：在**不改动** pyinj_core 既有 sites 逻辑的前提下，
把 TVBox/影视仓配置里的其它顶层数组（`lives` 电视直播 / `parses` 解析接口）
纳入管理，并为 sites 数组提供「拖拽排序」所需的 move 能力。

设计要点（与 pyinj_core 保持一致）：
  - 零 Qt 依赖，纯逻辑，可直接 import 单测；
  - 一律「手术式改写」：保留 JSONC 注释、尾逗号、原始缩进风格；
  - 通用实现：find_array_close 按数组名定位任意顶层数组，复用于 sites/lives/parses。
"""

import json
import re

# 复用 pyinj_core 的底层原语（不改动它们，只调用）
from pyinj_core import (
    parse_jsonc, parse_site_spans, _STR_FIELDS, fmt_entry,
)


# ----------------------------------------------------------------------------
# 通用数组定位 / 条目 span（比 pyinj_core.find_sites_close 更通用：按数组名）
# ----------------------------------------------------------------------------
def find_array_close(text, name):
    """返回指定顶层数组 `"name": [` 的 (内容起点, 匹配 ']' 的位置)。
    跳过注释与字符串，正确处理嵌套 [] 与 {}（lives 的 url 里可能含 [ ]）。"""
    m = re.search(r'"' + re.escape(name) + r'"\s*:\s*\[', text)
    if not m:
        raise ValueError('配置中未找到 "%s" 数组' % name)
    start = m.end()
    depth = 1
    i, n = start, len(text)
    close = None
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            i = j + 1
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                close = i
                break
        i += 1
    if close is None:
        raise ValueError('未找到 "%s" 数组的结束 ]' % name)
    return start, close


def has_array(text, name):
    """该顶层数组是否存在（不存在时 GUI 应提示「无可管理的条目」）。"""
    try:
        find_array_close(text, name)
        return True
    except Exception:
        return False


def parse_object_spans(text, name):
    """解析指定数组内每个 `{...}` 条目的 span。
    返回 [(start, end, obj), ...]；obj 为解析出的 dict。
    与 pyinj_core.parse_site_spans 逻辑一致，但数组名可指定（sites/lives/parses）。"""
    start, close = find_array_close(text, name)
    spans = []
    i, n = start, close
    while i < n:
        ch = text[i]
        if ch in " \t\r\n,":
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == "{":
            j = i + 1
            depth = 1
            while j < n:
                c2 = text[j]
                if c2 == "/" and j + 1 < n and text[j + 1] == "/":
                    while j < n and text[j] != "\n":
                        j += 1
                    continue
                if c2 == '"':
                    k = j + 1
                    while k < n:
                        if text[k] == "\\":
                            k += 2
                            continue
                        if text[k] == '"':
                            break
                        k += 1
                    j = k + 1
                    continue
                if c2 == "{":
                    depth += 1
                elif c2 == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            try:
                obj = parse_jsonc(text[i:j + 1])
            except Exception:
                i = j + 1
                continue
            spans.append((i, j + 1, obj))
            i = j + 1
            continue
        i += 1
    return spans


# ----------------------------------------------------------------------------
# 条目读写（通用字段：字符串 / 数字 / 布尔 / 嵌套对象均按原样 JSON 序列化）
# ----------------------------------------------------------------------------
def _fmt_scalar(v):
    """把字段值格式化成 JSON 字面量（字符串带引号、数字/布尔原样、对象/数组 JSON）。"""
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return "null"
    return json.dumps(v, ensure_ascii=False)


def _fmt_generic_entry(e, indent="    "):
    """把一条通用条目 dict 序列化为对象文本（保留键顺序；缩进与现网配置一致）。
    lives/parses 的字段与 sites 不同（name/type/url/epg/logo/ext…），故不能复用
    fmt_entry，这里按键顺序逐个输出。"""
    items = list(e.items())
    out = [indent + "{",]
    pad = indent + "  "
    for idx, (k, v) in enumerate(items):
        val = _fmt_scalar(v)
        comma = "," if idx < len(items) - 1 else ""
        out.append(pad + json.dumps(str(k), ensure_ascii=False) + ": " + val + comma)
    out.append(indent + "}")
    return "\n".join(out)


def _entry_identity(e):
    """条目的稳定身份：优先 key，其次 name+url，其次 name。用于定位/替换。"""
    if e.get("key"):
        return ("key", str(e["key"]))
    if e.get("url") is not None:
        return ("name+url", "%s|%s" % (e.get("name", ""), e.get("url", "")))
    return ("name", str(e.get("name", "")))


def _same_entry(a, b):
    return _entry_identity(a) == _entry_identity(b)


def section_entries(text, name):
    """返回指定数组的条目 dict 列表（顺序即数组顺序）。"""
    return [obj for _s, _e, obj in parse_object_spans(text, name)]


# ----------------------------------------------------------------------------
# CRUD（手术式改写，保留注释）
# ----------------------------------------------------------------------------
def _array_body_insert(text, name, entry_text):
    """把 entry_text 插到指定数组体末尾（在最后一个 ] 之前）。"""
    start, close = find_array_close(text, name)
    body = text[start:close]
    stripped = body.rstrip()
    if not stripped.strip():
        return text[:start] + "\n" + entry_text + "\n" + text[close:]
    lead = "" if stripped.endswith(",") else ","
    return text[:start] + stripped + lead + "\n" + entry_text + "\n" + text[close:]


def add_section_entry(text, name, entry):
    """向数组追加一条条目，返回新文本。"""
    return _array_body_insert(text, name, _fmt_generic_entry(entry))


def update_section_entry(text, name, old_entry, new_entry):
    """按身份定位并整体替换一条条目（保留注释），返回 (新文本, 是否找到)。"""
    for s, e, obj in parse_object_spans(text, name):
        if _same_entry(obj, old_entry):
            return text[:s] + _fmt_generic_entry(new_entry) + text[e:], True
    return text, False


def set_section_field(text, name, entry, field, value):
    """只改某条目的单个字段（保留其余字段与注释），返回 (新文本, 是否找到)。"""
    for s, e, obj in parse_object_spans(text, name):
        if not _same_entry(obj, entry):
            continue
        seg = text[s:e]
        lit = _fmt_scalar(value)
        pat = re.compile(r'("' + re.escape(field) + r'"\s*:\s*)'
                         r'("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null|\{.*?\}|\[.*?\])',
                         re.DOTALL)
        seg2, cnt = pat.subn(lambda m: m.group(1) + lit, seg, count=1)
        if cnt == 0:
            idx = seg.rfind("}")
            inner = seg[:idx].rstrip()
            sep = "" if inner.endswith("{") else ","
            ins = '%s"%s": %s' % (sep, field, lit)
            seg2 = seg[:idx].rstrip() + ins + "\n    " + seg[idx:]
        return text[:s] + seg2 + text[e:], True
    return text, False


def delete_section_entry(text, name, entry):
    """删除一条条目（正确处理前后逗号），返回 (新文本, 被删条目 或 None)。"""
    for s, e, obj in parse_object_spans(text, name):
        if not _same_entry(obj, entry):
            continue
        i = s
        prev_comma = None
        while i > 0 and text[i - 1] in " \t\r\n":
            i -= 1
        if i > 0 and text[i - 1] == ",":
            prev_comma = i - 1
        j = e
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        next_comma = j if (j < len(text) and text[j] == ",") else None
        if prev_comma is not None:
            new_text = text[:prev_comma] + text[e:]
        elif next_comma is not None:
            new_text = text[:s] + text[next_comma + 1:]
        else:
            new_text = text[:s] + text[e:]
        return new_text, obj
    return text, None


# ----------------------------------------------------------------------------
# 拖拽排序：整段数组体按新顺序重建（对 sites 与 lives/parses 通用）
# ----------------------------------------------------------------------------
def reorder_section(text, name, ordered_entries):
    """按 ordered_entries 给定的条目顺序重建数组体（其余注释尽量保留在末尾）。
    用于 GUI 拖拽排序后落盘。返回新文本。

    实现：把现存条目文本按新顺序重排，逗号只在条目之间插入；
    数组体内的非条目内容（如注释行）统一收拢到数组体末尾。"""
    start, close = find_array_close(text, name)
    spans = parse_object_spans(text, name)
    by_id = {}
    for s, e, obj in spans:
        by_id.setdefault(_entry_identity(obj), (s, e, obj))

    # 收集数组体内不属于任何条目的「雜项」（注释等），按原顺序保留
    covered = [(s, e) for s, e, _o in spans]
    extras = []
    i = start
    while i < close:
        hit = None
        for s, e in covered:
            if s <= i < e:
                hit = (s, e)
                break
        if hit:
            i = hit[1]
            continue
        # 跳过纯空白/逗号
        if text[i] in " \t\r\n,":
            i += 1
            continue
        # 注释行：整行收拢
        if text[i] == "/" and i + 1 < close and text[i + 1] == "/":
            j = i
            while j < close and text[j] != "\n":
                j += 1
            extras.append(text[i:j])
            i = j + 1
            continue
        i += 1

    parts = []
    for ent in ordered_entries:
        key = _entry_identity(ent)
        s, e, _obj = by_id.get(key, (None, None, None))
        if s is None:
            parts.append(_fmt_generic_entry(ent))     # 新增条目
        else:
            parts.append(text[s:e])
    body = ",\n".join("    " + p.lstrip() for p in parts)
    if extras:
        body += "\n" + "\n".join(extras)
    if body.strip():
        body = "\n" + body + "\n  "
    return text[:start] + body + text[close:]


def move_section_entry(text, name, entry, offset):
    """把某条目在数组内上移/下移 offset 位（GUI 拖拽/上下移按钮）。返回新文本。
    offset<0 上移，>0 下移；越界则原样返回。"""
    ents = section_entries(text, name)
    idx = None
    for i, e in enumerate(ents):
        if _same_entry(e, entry):
            idx = i
            break
    if idx is None:
        return text
    new_idx = idx + offset
    if new_idx < 0 or new_idx >= len(ents):
        return text
    ents[idx], ents[new_idx] = ents[new_idx], ents[idx]
    return reorder_section(text, name, ents)
