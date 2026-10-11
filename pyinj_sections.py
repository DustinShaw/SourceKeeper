# -*- coding: utf-8 -*-
"""源管家 · 分区管理模块（pyinj_sections）
=========================================
以「新增模块」方式扩展：在**不改动** pyinj_core 既有 sites 逻辑的前提下，
把配置里的其它顶层数组（`lives` 电视直播 / `parses` 解析接口）
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
    _extract_first_object, _extract_first_object_span, _DISABLE_MARK,
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


def _canonical(e):
    """条目的规范 JSON 文本（键排序、无空格），用于身份回退比较。"""
    try:
        return json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return str(e)


def _entry_identity(e):
    """条目的稳定身份：优先 key，其次 name+url，再次 name，最后规范 JSON。
    用于定位/替换/删除。最后一档是给 rules / ijk / flags 这类
    **没有 key、name、url 的分区**用的——否则所有条目会塌缩成同一个身份，
    导致「删了第一条却删到别的条目」这类事故。"""
    if e.get("key"):
        return ("key", str(e["key"]))
    if e.get("url") is not None:
        return ("name+url", "%s|%s" % (e.get("name", ""), e.get("url", "")))
    if e.get("name") is not None:
        return ("name", str(e.get("name", "")))
    return ("json", _canonical(e))


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


def reorder_by_keys(text, name, ordered_keys, key_field="key"):
    """按 ordered_keys 给出的顺序重排数组内条目（以 key_field 识别）。
    返回 (新文本, 位置发生变化的条目数)；顺序没变则原样返回 (text, 0)。

    用途：GUI 里点了列头排序（或过滤后）想把「当前看到的顺序」落到配置文件。

    设计（复用「上移/下移」那套片段级机制，因此同样不破坏注释与禁用块）：
      · 只有「出现在 ordered_keys 里、且能在数组里定位到」的条目参与重排；
      · **槽位填充**：参与条目按新顺序回填它们原本占据的位置，
        未参与的条目（如被搜索/过滤隐藏的）与数组内注释**位置不动**；
      · 数组内注释「跟随其后紧跟的条目」一起移动，说明性注释不会与条目错位
        （末尾孤立的注释留在末尾）；
      · 条目原文（obj_text）原样复用 —— 注释式禁用块、缩进写法都不会被改写。
    """
    pieces = scan_array_pieces(text, name)
    if not pieces:
        return text, 0

    # 1) 切块：注释挂到它后面那个条目上（末尾孤立注释自成一块）
    blocks = []
    lead = []
    for p in pieces:
        if p["kind"] == "extra":
            lead.append(p)
            continue
        blocks.append({"lead": lead, "ent": p})
        lead = []
    if lead:
        blocks.append({"lead": lead, "ent": None})

    # 2) 目标顺序（去重保序）+ 参与条目的槽位
    want, seen = [], set()
    for k in ordered_keys:
        k = str(k)
        if k and k not in seen:
            seen.add(k)
            want.append(k)
    idx_of = {}
    for i, b in enumerate(blocks):
        if b["ent"] is None:
            continue
        k = str((b["ent"]["obj"] or {}).get(key_field, ""))
        if k and k not in idx_of:
            idx_of[k] = i
    hits = [k for k in want if k in idx_of]
    if len(hits) < 2:
        return text, 0
    slots = sorted(idx_of[k] for k in hits)
    picks = [blocks[idx_of[k]] for k in hits]

    # 3) 槽位回填：按新顺序把参与条目填回它们原来的位置
    out_blocks = list(blocks)
    for slot, blk in zip(slots, picks):
        out_blocks[slot] = blk
    pos_before = {id(b): i for i, b in enumerate(blocks)}
    moved = sum(1 for i, b in enumerate(out_blocks) if pos_before.get(id(b)) != i)
    if not moved:
        return text, 0

    flat = []
    for b in out_blocks:
        flat.extend(b["lead"])
        if b["ent"] is not None:
            flat.append(b["ent"])
    return replace_array_body(text, name, flat), moved


def move_section_entry(text, name, entry, offset):
    """把某条目在数组内上移/下移 offset 位（GUI 拖拽/上下移按钮）。返回新文本。
    offset<0 上移，>0 下移；越界则原样返回。

    实现走「片段级重建」：只在**启用中的条目**之间换位，
    被注释禁用的条目与数组内注释**原样留在原位**（不会像 reorder_section 那样被挪走）。"""
    pieces = scan_array_pieces(text, name)
    act = [i for i, p in enumerate(pieces) if p["kind"] == "active"]
    pos = None
    for n, i in enumerate(act):
        if _same_entry(pieces[i]["obj"], entry):
            pos = n
            break
    if pos is None:
        return text
    tgt = pos + offset
    if tgt < 0 or tgt >= len(act):
        return text
    i, j = act[pos], act[tgt]
    for k in ("obj", "obj_text"):
        pieces[i][k], pieces[j][k] = pieces[j][k], pieces[i][k]
    return replace_array_body(text, name, pieces)


# ============================================================================
# 片段级扫描 / 重建（支持注释式「禁用」，并保留数组内注释位置）
# ----------------------------------------------------------------------------
# 设计要点：一个数组体被切成有序「片段」列表 ——
#   active   : 正常条目        {…}
#   disabled : 注释禁用的条目   /* [disabled] {…} */
#   extra    : 其余注释（行注释 / 块注释），原样保留在各自位置
# 条目原文统一存在 obj_text（不含缩进前缀）；渲染时按 kind 决定是否包注释，
# 于是「禁用 ↔ 启用」只是改 kind，永远不会出现「启用了但还是一段注释」的脏数据。
# ============================================================================
def scan_array_pieces(text, name):
    """扫描顶层数组体，按**原始出现顺序**返回片段列表，每项为 dict：
        {"kind": "active"/"disabled"/"extra", "pos": int,
         "obj": dict|None, "obj_text": str|None, "raw": str|None}
    raw 仅 extra 片段使用。"""
    try:
        start, close = find_array_close(text, name)
    except Exception:
        return []
    pieces = []
    i, n = start, close
    while i < n:
        ch = text[i]
        if ch in " \t\r\n,":
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = i + 2
            while j + 1 < n and not (text[j] == "*" and text[j + 1] == "/"):
                j += 1
            j = min(j + 2, n)
            block = text[i:j]
            if _DISABLE_MARK in block[:60]:
                obj = _extract_first_object(block)
                obj_text = _extract_first_object_span(block)
                if obj is not None and obj_text is not None:
                    pieces.append({"kind": "disabled", "pos": i, "obj": obj,
                                   "obj_text": obj_text, "raw": None})
                    i = j
                    continue
            pieces.append({"kind": "extra", "pos": i, "obj": None,
                           "obj_text": None, "raw": block})
            i = j
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = i
            while j < n and text[j] != "\n":
                j += 1
            pieces.append({"kind": "extra", "pos": i, "obj": None,
                           "obj_text": None, "raw": text[i:j]})
            i = j + 1
            continue
        if ch == "{":
            k = i + 1
            depth = 1
            while k < n:
                c2 = text[k]
                if c2 == "/" and k + 1 < n and text[k + 1] == "/":
                    while k < n and text[k] != "\n":
                        k += 1
                    continue
                if c2 == '"':
                    m = k + 1
                    while m < n:
                        if text[m] == "\\":
                            m += 2
                            continue
                        if text[m] == '"':
                            break
                        m += 1
                    k = m + 1
                    continue
                if c2 == "{":
                    depth += 1
                elif c2 == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            seg = text[i:k + 1]
            try:
                obj = parse_jsonc(seg)
            except Exception:
                pieces.append({"kind": "extra", "pos": i, "obj": None,
                               "obj_text": None, "raw": seg})
                i = k + 1
                continue
            pieces.append({"kind": "active", "pos": i, "obj": obj,
                           "obj_text": seg, "raw": None})
            i = k + 1
            continue
        i += 1
    return pieces


def piece_text(p):
    """片段渲染成文本：active 直接给对象原文；disabled 包上 /* [disabled] */ 注释。"""
    if p["kind"] == "active":
        return (p.get("obj_text") or "").strip()
    if p["kind"] == "disabled":
        return "/* " + _DISABLE_MARK + "\n" + (p.get("obj_text") or "").rstrip("\n") + "\n*/"
    return (p.get("raw") or "").strip()


def _pieces_body(pieces, trailing_comma):
    """把片段列表渲染成数组体文本（不含外层 `[` `]`）。
    逗号只加在**相邻的启用条目之间**（加在前一个条目的行尾）——
    这样即使中间夹着 `//` 行注释，也不会出现「逗号被注释吃掉」或悬空逗号。"""
    act = [i for i, p in enumerate(pieces) if p["kind"] == "active"]
    need_comma = set(act[:-1])
    if trailing_comma and act:
        need_comma.add(act[-1])
    out = []
    for idx, p in enumerate(pieces):
        txt = piece_text(p)
        if not txt:
            continue
        line = "\n    " + txt
        if idx in need_comma:
            line += ","
        out.append(line)
    return "".join(out) + "\n  "


def replace_array_body(text, name, pieces):
    """用片段列表整体重写数组体（保留数组外的其它配置与注释）。返回新文本。"""
    start, close = find_array_close(text, name)
    trailing = text[start:close].rstrip().endswith(",")
    return text[:start] + _pieces_body(pieces, trailing) + text[close:]


def parse_section_tokens(text, name):
    """按顺序返回 [{"kind": "active"/"disabled", "obj": {...}, "text": 渲染文本}]。"""
    return [{"kind": p["kind"], "obj": p["obj"], "text": piece_text(p)}
            for p in scan_array_pieces(text, name) if p["kind"] in ("active", "disabled")]


def section_entries_with_disabled(text, name):
    """返回 [(obj, disabled)]：active 条目 disabled=False，注释禁用的 disabled=True。
    顺序即数组内原始顺序（与 GUI 列表一致）。"""
    return [(p["obj"], p["kind"] == "disabled") for p in scan_array_pieces(text, name)
            if p["kind"] in ("active", "disabled")]


def set_section_enabled(text, name, entry, enabled):
    """把某条目在 启用/禁用 之间切换（禁用 = 用 /* [disabled] … */ 注释掉，
    宿主程序会忽略它；数据仍在文件里，随时可恢复）。返回 (新文本, 是否发生变化)。"""
    pieces = scan_array_pieces(text, name)
    want = "active" if enabled else "disabled"
    changed = False
    for p in pieces:
        if p["kind"] not in ("active", "disabled"):
            continue
        if not _same_entry(p["obj"], entry):
            continue
        if p["kind"] != want:
            p["kind"] = want
            changed = True
        break
    if not changed:
        return text, False
    return replace_array_body(text, name, pieces), True


def remove_section_entry(text, name, entry):
    """删除一条条目（**含被注释禁用的**），返回 (新文本, 被删条目 或 None)。"""
    pieces = scan_array_pieces(text, name)
    hit = None
    for i, p in enumerate(pieces):
        if p["kind"] in ("active", "disabled") and _same_entry(p["obj"], entry):
            hit = pieces.pop(i)["obj"]
            break
    if hit is None:
        return text, None
    return replace_array_body(text, name, pieces), hit


def replace_section_entry(text, name, old_entry, new_entry):
    """按身份定位并整体替换一条条目（含禁用的），保留其它片段与注释。
    返回 (新文本, 是否找到)。"""
    pieces = scan_array_pieces(text, name)
    for p in pieces:
        if p["kind"] in ("active", "disabled") and _same_entry(p["obj"], old_entry):
            p["obj"] = dict(new_entry)
            p["obj_text"] = _fmt_generic_entry(new_entry)
            return replace_array_body(text, name, pieces), True
    return text, False


def section_summary(entry):
    """给分区管理表格用的 (标题, 摘要)。纯展示，不改变数据。"""
    title = ""
    for k in ("name", "key", "host", "group", "title", "label"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            title = v.strip()
            break
    if not title:
        for _k, v in entry.items():
            if isinstance(v, str) and v.strip():
                title = v.strip()
                break
    sub = ""
    for k in ("url", "api", "rule", "value", "options", "type", "ext"):
        if k in entry:
            v = entry[k]
            sub = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            break
    if not sub:
        sub = json.dumps(entry, ensure_ascii=False)
    if len(sub) > 160:
        sub = sub[:157] + "…"
    return (title or "(无名称)"), sub
