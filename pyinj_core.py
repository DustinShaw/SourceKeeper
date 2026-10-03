# -*- coding: utf-8 -*-
"""源管家 核心逻辑层（pyinj_core）
=====================================
纯逻辑、零 Qt 依赖：JSONC 解析、仓库扫描、检测（成人/短剧/直播/URL/文件存在）、
sites 手术式改写（插入/编辑/启停/删除/去重）、备份轮转。
由 injector.py（CLI/GUI 入口层）re-export；可直接 `import pyinj_core` 单测。
"""

import os
import re
import sys
import json
import shutil
import glob
import socket
import ssl
import urllib.request
import urllib.error
import subprocess
import tempfile
from datetime import datetime

CONFIG_NAME = "py.json"

LEVEL_TAG = {"info": "· ", "ok": "✓ ", "warn": "⚠ ", "err": "✗ "}


def get_app_dir():
    """绿色运行：优先用 exe 所在目录，否则当前文件目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def strip_jsonc_comments(text):
    """去除 // 与 /* */ 注释，便于用 json 模块解析做校验/读取。
    字符串内的 // 不会被误伤。"""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if c == '"':
            j = i + 1
            buf = '"'
            while j < n:
                if text[j] == "\\":
                    buf += text[j] + (text[j + 1] if j + 1 < n else "")
                    j += 2
                    continue
                if text[j] == '"':
                    buf += '"'
                    break
                buf += text[j]
                j += 1
            out.append(buf)
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_jsonc(text):
    return json.loads(strip_jsonc_comments(text))


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


# ----------------------------------------------------------------------------
# spider .py 静态解析（不执行代码）
# ----------------------------------------------------------------------------
def extract_getname(py_path):
    """静态提取 `def getName(self): return "xxx"` 的显示名。取不到返回 None。"""
    try:
        txt = read_text(py_path)
    except Exception:
        return None
    m = re.search(
        r"def\s+getName\s*\(\s*self\s*\)\s*:\s*return\s*[\"']([^\"']+)[\"']",
        txt,
    )
    return m.group(1).strip() if m else None


def has_spider_class(py_path):
    try:
        txt = read_text(py_path)
    except Exception:
        return False
    return bool(re.search(r"class\s+Spider\s*[\(\:]", txt))


# ----------------------------------------------------------------------------
# sites 数组手术式插入（保留注释）
# ----------------------------------------------------------------------------
def find_sites_close(text):
    """返回 sites 数组 '[' 之后位置 与 匹配 ']' 的位置。"""
    m = re.search(r'"sites"\s*:\s*\[', text)
    if not m:
        raise ValueError('py.json 中未找到 "sites" 数组')
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
        raise ValueError("未找到 sites 数组的结束 ]")
    return start, close


def _fmt_type_value(v):
    """type 输出为 JSON 字面量：字符串原样带引号，数字正常输出。
    影视仓变体可能用字符串 spider 类型（如 "py"），不能强转 int。"""
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return json.dumps(str(v), ensure_ascii=False)


# 7 个核心字段（fmt_entry 固定输出顺序；其余字段一律追加在 searchable 与 type 之间）
_CORE_ENTRY_KEYS = ("key", "name", "api", "filterable", "quickSearch", "searchable", "type")


def _fmt_generic(v):
    """把条目里的「非核心」字段值格式化为 JSON 字面量（ext/jar/adult/changeable/...）。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return json.dumps(str(v), ensure_ascii=False)


def fmt_entry(e):
    """把一条站点 dict 序列化为 JSON 对象文本。

    ⚠️ 字段保留规则（2026-09-30 修正，之前合并导入丢字段的根因之一）：
      固定输出 7 个核心字段（key/name/api/filterable/quickSearch/searchable/type），
      并**追加写出 dict 里多出的所有字段**（ext/jar/adult/changeable/categories/
      hide/playUrl/style/...），而非只写死的 7 字段——否则像 jar 型多站点那样
      带 ext 的源，导入后 ext 全丢、源直接废掉。
      7 字段 dict 的输出与旧版逐字一致（向后兼容）。"""
    core = (
        "        {\n"
        '            "key": ' + json.dumps(e["key"], ensure_ascii=False) + ",\n"
        '            "name": ' + json.dumps(e["name"], ensure_ascii=False) + ",\n"
        '            "api": ' + json.dumps(e["api"], ensure_ascii=False) + ",\n"
        '            "filterable": ' + ("1" if e["filterable"] else "0") + ",\n"
        '            "quickSearch": ' + ("1" if e["quickSearch"] else "0") + ",\n"
        '            "searchable": ' + ("1" if e["searchable"] else "0") + ",\n"
    )
    extra = ""
    for k, v in e.items():
        if k in _CORE_ENTRY_KEYS:
            continue
        extra += '            "%s": %s,\n' % (k, _fmt_generic(v))
    return core + extra + '            "type": ' + _fmt_type_value(e["type"]) + "\n        }"


def _insert_point(text, close):
    """在 sites 数组体内挑插入位置。返回 (插入点, 插入点之后是否紧跟禁用注释块)。
    禁用条目以 /* [disabled] */ 注释块形式存在，本身不是数组元素：
    新条目必须插到最后一个注释块「之前」，并自带尾逗号，否则会写出
    `*/\n,\n{...}` 这种非法片段（2026.09.25.f 修）。"""
    blocks = [b for b in _find_disabled_blocks(text) if b[1] <= close]
    if blocks:
        return blocks[-1][0], True
    return close, False


def insert_into_sites(text, entries):
    """把若干条目插进 sites 数组（手术式改写，保留其余内容与注解）。"""
    start, close = find_sites_close(text)
    body = text[start:close]
    if not body.strip():
        return text[:close] + "\n" + \
            ",\n".join(fmt_entry(e) for e in entries) + text[close:]
    # 多个条目之间用逗号分隔（数组内对象必须逗号隔开）
    block = ",\n".join(fmt_entry(e) for e in entries)
    ins, after_block = _insert_point(text, close)
    head = text[start:ins]                  # 插入点之前的数组体（覆盖后可能为空）
    # 左边已有内容且未以逗号收尾（「手改配置」常见尾逗号则已收尾）才补前导逗号；
    # 左边空空如也时补逗号会写成 `[ , {...}]` —— 那是非法 JSON（首条不能有前导逗号）
    lead = "," if (head.strip() and not head.rstrip().endswith(",")) else ""
    # 插入点后面若不是 ']'（即紧跟着禁用注释块），新条目必须自带尾逗号
    tail = "," if after_block else ""
    return text[:start] + head.rstrip() + lead + "\n" + block + tail + text[ins:]


# ----------------------------------------------------------------------------
# 仓库加载 / 条目收集 / 写入（GUI 与 CLI 共用）
# ----------------------------------------------------------------------------
def guess_config_file(repo_dir, hint=None):
    """在仓库目录猜测 spider 单仓配置文件（含 sites 数组的 JSON/JSONC）。
    hint: 用户指定的文件名或路径（优先采用）；为空则自动猜测。
    返回仓库内相对文件名（仓库外则返回绝对路径），找不到返回 None。
    猜测规则：
      1) 用户指定且存在 -> 直接用；
      2) 精确 py.json 存在 -> 用 py.json（兼容既有习惯）；
      3) 扫描根目录及一级子目录下 *.json（跳过 .bak），
         解析出「dict 且含非空 sites 数组、条目带 key/api 字段」者打分，
         分数 = 有效站点数 + 命名加分（py.json>+100 / 含 py>+10）+ 含 spider 字段 +5。
    """
    # 1) 用户指定优先
    if hint:
        cand = hint if os.path.isabs(hint) else os.path.join(repo_dir, hint)
        if os.path.isfile(cand):
            return hint if os.path.isabs(hint) else hint.replace("\\", "/")
        return None  # 用户明确指定但不存在：尊重意图，不再乱猜
    # 2) 精确 py.json
    if os.path.isfile(os.path.join(repo_dir, CONFIG_NAME)):
        return CONFIG_NAME
    # 3) 扫描 *.json 候选（根目录 + 一级子目录）
    cands = []
    for cur, subdirs, files in os.walk(repo_dir):
        rel = os.path.relpath(cur, repo_dir)
        depth = 0 if rel == "." else rel.count(os.sep)
        if depth > 1:
            subdirs[:] = []
            continue
        for f in files:
            if f.lower().endswith(".json"):
                cands.append(os.path.join(cur, f))
    best, best_score = None, -1
    for p in cands:
        try:
            data = parse_jsonc(read_text(p))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        sites = data.get("sites")
        if not isinstance(sites, list) or not sites:
            continue
        ok = sum(1 for s in sites[:50] if isinstance(s, dict) and ("key" in s or "api" in s))
        if ok == 0:
            continue
        score = ok
        name = os.path.basename(p).lower()
        if name == CONFIG_NAME:
            score += 100
        elif "py" in name:
            score += 10
        if data.get("spider"):
            score += 5
        if score > best_score:
            best, best_score = p, score
    if not best:
        return None
    ap, ar = os.path.abspath(best), os.path.abspath(repo_dir)
    if ap.startswith(ar + os.sep):
        return os.path.relpath(ap, ar).replace("\\", "/")
    return ap


def load_repo(repo_dir, cfg_name=CONFIG_NAME):
    """返回 (raw, sites, existing_keys, existing_apis)。失败抛异常。
    cfg_name 为配置文件名（相对 repo_dir）或绝对路径。"""
    cfg = cfg_name if os.path.isabs(cfg_name) else os.path.join(repo_dir, cfg_name)
    if not os.path.isfile(cfg):
        raise FileNotFoundError("未找到 %s：%s" % (cfg_name, cfg))
    raw = read_text(cfg)
    data = parse_jsonc(raw)
    sites = data.get("sites", []) or []
    existing_keys = {s.get("key") for s in sites if s.get("key")}
    existing_apis = {s.get("api") for s in sites if s.get("api")}
    return raw, sites, existing_keys, existing_apis


def make_entry(py_path, base_dir, copy_into_py):
    """根据 .py 文件生成一条 site 条目。base_dir 为基准目录（配置文件所在目录）。"""
    base = os.path.basename(py_path)
    name_py = os.path.splitext(base)[0]
    display = extract_getname(py_path) or name_py

    py_dir = os.path.join(base_dir, "py")
    inside_py = os.path.abspath(py_path).startswith(os.path.abspath(py_dir) + os.sep)

    if inside_py:
        rel = os.path.relpath(py_path, base_dir).replace("\\", "/")
        api = "./" + rel if not rel.startswith("./") else rel
        if not api.startswith("./"):
            api = "./" + api
    else:
        api = "./py/" + base
        if copy_into_py:
            os.makedirs(py_dir, exist_ok=True)
            shutil.copy2(py_path, os.path.join(py_dir, base))
    return {
        "file": py_path,
        "key": "py_" + name_py,
        "name": display + "┃PY",
        "api": api,
        "type": infer_type(api),
        "filterable": True,
        "quickSearch": True,
        "searchable": True,
    }


def _name_from_api(api):
    """从直连 CMS 的 api 地址推断一个可读站点名（无 .py 时用于展示）。"""
    try:
        from urllib.parse import urlparse
        p = urlparse(api)
        host = (p.netloc or api).split("@")[-1].split(":")[0]
        segs = [s for s in (p.path or "").split("/")
                if s and s.lower() not in
                ("api.php", "provide", "vod", "index.php", "index.html", "t.php", "")]
        if segs:
            return segs[-1]
        return host
    except Exception:
        return api


def _key_from_api(api):
    """为直连 CMS 源生成稳定且唯一的 key（按 api 哈希，避免与现有 key 撞名）。"""
    import hashlib
    h = hashlib.md5((api or "").encode("utf-8")).hexdigest()[:8]
    return "api_" + h


def make_entry_from_api(api, name=None, type_hint=1,
                        filterable=True, quickSearch=True, searchable=True, key=None):
    """根据直连 CMS 的 api 地址生成一条 site 条目（默认 type:1）。
    用于「添加直连源」：用户粘贴 API 地址 + 可选名称。name/key 缺省时分别由
    api 自动推断，保证可读且唯一。"""
    api = (api or "").strip()
    if not api:
        raise ValueError("api 地址为空")
    t = _norm_type(type_hint)
    if t is None:
        t = infer_type(api)
    if t is None:
        t = 1
    nm = (name or "").strip() or _name_from_api(api)
    k = (key or "").strip() or _key_from_api(api)
    return {
        "key": k,
        "name": nm,
        "api": api,
        "type": t,
        "filterable": filterable,
        "quickSearch": quickSearch,
        "searchable": searchable,
    }


def collect_from_files(files, base_dir, copy_into_py, existing_keys, existing_apis):
    """从文件列表收集可注入条目。返回 (entries, logs)。"""
    entries, logs = [], []
    for fp in files:
        if not has_spider_class(fp):
            logs.append(("warn", "跳过（未定义 class Spider）：%s" % os.path.basename(fp)))
            continue
        ent = make_entry(fp, base_dir, copy_into_py)
        if ent["key"] in existing_keys or any(p["key"] == ent["key"] for p in entries):
            logs.append(("warn", "跳过（key 重复）：%s → %s" % (ent["api"], ent["key"])))
            continue
        entries.append(ent)
        logs.append(("ok", "已加入：%s  (name=%s)" % (ent["api"], ent["name"])))
    return entries, logs


def collect_from_scan(base_dir, existing_keys, existing_apis):
    """扫描 py/ 目录收集未注册条目。返回 (entries, logs)。
    py/ 相对基准目录(base_dir)解析；若基准目录下没有，回退到仓库根目录。"""
    entries, logs = [], []
    py_dir = os.path.join(base_dir, "py")
    if not os.path.isdir(py_dir):
        logs.append(("err", "未找到 py/ 目录：%s" % py_dir))
        return entries, logs
    for fn in sorted(os.listdir(py_dir)):
        if not fn.lower().endswith(".py"):
            continue
        api = "./py/" + fn
        if api in existing_apis or any(p["api"] == api for p in entries):
            continue
        fp = os.path.join(py_dir, fn)
        if not has_spider_class(fp):
            continue
        ent = make_entry(fp, base_dir, False)
        if ent["key"] in existing_keys or any(p["key"] == ent["key"] for p in entries):
            logs.append(("warn", "跳过（key 重复）：%s" % api))
            continue
        entries.append(ent)
        logs.append(("ok", "扫描发现未注册：%s" % api))
    return entries, logs


def check_missing_py(base_dir, sites, alt_dir=None, name_map=None):
    """反向校验：已注册配置项对应的 .py 文件是否真实存在于磁盘。
    返回 (missing, relocated)：
      missing   = [(key, api)]             直接路径与 name_map 都找不到；
      relocated = [(key, api, found_path)] 直接路径失效但经 name_map 在别处找回。
    跳过远程 api（含 ://）与空 api。"""
    missing, relocated = [], []
    for e in sites:
        key = str(e.get("key", ""))
        api = str(e.get("api", ""))
        # 只校验「应有本地文件」的源（本地 Spider）；直连/XML/目录/远程一律跳过
        if not expects_local_file(e):
            continue
        p = resolve_spider_path(base_dir, api, alt_dir)
        if os.path.isfile(p):
            continue
        if name_map:
            bn = os.path.basename(api_to_path(base_dir, api)).lower()
            p2 = name_map.get(bn)
            if p2 and os.path.isfile(p2):
                relocated.append((key, api, p2))
                continue
        missing.append((key, api))
    return missing, relocated


def check_missing_py_resilient(base_dir, sites, repo_dir=None, cfg_name=CONFIG_NAME):
    """带遍历找回的缺失校验：先直接解析，对缺失项再遍历搜索根目录找回一次。
    返回 (missing, relocated)，含义同 check_missing_py。"""
    missing, relocated = check_missing_py(base_dir, sites, repo_dir)
    if not missing:
        return missing, relocated
    roots = default_search_roots(repo_dir, cfg_name)
    name_map = discover_py_files(roots) if roots else {}
    if not name_map:
        return missing, relocated
    still = []
    for key, api in missing:
        bn = os.path.basename(api_to_path(base_dir, api)).lower()
        p2 = name_map.get(bn)
        if p2 and os.path.isfile(p2):
            relocated.append((key, api, p2))
        else:
            still.append((key, api))
    return still, relocated


def commit_write(repo_dir, raw, entries, switches, cfg_name=CONFIG_NAME):
    """备份并写入。switches: dict(filterable, quickSearch, searchable, type)。
    返回备份文件名（backups/ 目录下，与 backup_and_write 同一套轮转策略）。
    CLI 与 GUI 的「写入配置」共用此函数，避免两处备份位置各写一套。"""
    for e in entries:
        e["filterable"] = switches["filterable"]
        e["quickSearch"] = switches["quickSearch"]
        e["searchable"] = switches["searchable"]
        # type：保留条目自身已有的（来自 .py 推断或来源配置）；
        # 仅当**真正缺失**时才回落 switches["type"]，绝不全局抹平每条记录的 type。
        # ⚠️ 0 是合法 type（XML），必须用 `is None / == ""` 判缺失，
        #    写成 `in (None, "", 0)` 会把显式 type=0 的 XML 站点改写成全局值。
        if e.get("type") is None or e.get("type") == "":
            e["type"] = switches["type"]
    new_text = insert_into_sites(raw, entries)
    return backup_and_write(repo_dir, new_text, cfg_name)


# ----------------------------------------------------------------------------
# 站点条目解析 / 修改 / 删除 / 查重（保留 JSONC 注释）
# ----------------------------------------------------------------------------
_STR_FIELDS = ("key", "name", "api", "jar")           # 字符串字段（jar 仅 jar 型 spider 源有值）
_INT_FIELDS = ("type", "filterable", "quickSearch", "searchable", "adult")
_JSON_FIELDS = ("ext",)                                # JSON 对象/数组字段（多线路 jar 源的 ext.site 等）
ALL_FIELDS = _STR_FIELDS + _INT_FIELDS + _JSON_FIELDS


def parse_site_spans(text):
    """解析 sites 数组内每个条目对象的文本 span。
    返回 [(start, end, obj), ...]：start 为 '{' 下标，end 为 '}' 之后一位，
    obj 为解析出的 dict。"""
    start, close = find_sites_close(text)
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
            obj = parse_jsonc(text[i:j + 1])
            spans.append((i, j + 1, obj))
            i = j + 1
            continue
        i += 1
    return spans


def _find_value_end(seg, i):
    """从 JSON 值的起始下标 i 扫描，返回该值结束下标（不含）。
    支持 string / object{} / array[] / number / true|false|null。"""
    if i >= len(seg):
        return i
    ch = seg[i]
    if ch == '"':
        j = i + 1
        while j < len(seg):
            if seg[j] == '\\':
                j += 2
                continue
            if seg[j] == '"':
                return j + 1
            j += 1
        return j
    if ch in '[{':
        close = '}' if ch == '{' else ']'
        depth = 0
        j = i
        while j < len(seg):
            c = seg[j]
            if c == '\\':
                j += 2
                continue
            if c == '"':
                j += 1
                while j < len(seg):
                    if seg[j] == '\\':
                        j += 2
                        continue
                    if seg[j] == '"':
                        break
                    j += 1
                j += 1
                continue
            if c == ch:
                depth += 1
            elif c == close:
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return j
    # number / true / false / null
    j = i
    while j < len(seg) and seg[j] not in ',}\n\r\t ]':
        j += 1
    return j


def _remove_field_in_span(seg, field):
    """在一个 JSON 对象 span 内删除某字段（含其值与相邻逗号，但只删一个逗号）。找不到则原样返回。"""
    m = re.search(r'"' + re.escape(field) + r'"\s*:\s*', seg)
    if not m:
        return seg
    val_start = m.end()
    val_end = _find_value_end(seg, val_start)
    # 优先删除「字段后的逗号」，保留字段前的逗号（字段在中间时最常见）
    k = val_end
    while k < len(seg) and seg[k] in ' \t\r\n':
        k += 1
    if k < len(seg) and seg[k] == ',':
        return seg[:m.start()] + seg[k + 1:]
    # 否则字段是对象里最后一项，删除「字段前的逗号」
    j = m.start() - 1
    while j >= 0 and seg[j] in ' \t\r\n':
        j -= 1
    if j >= 0 and seg[j] == ',':
        return seg[:j] + seg[val_end:]
    # 兜底（字段是对象里唯一项）
    return seg[:m.start()] + seg[val_end:]


def _set_json_field_in_span(seg, field, new_json_text):
    """在 span 内设置 JSON 字段（对象/数组/字符串）。不存在则插入。"""
    m = re.search(r'"' + re.escape(field) + r'"\s*:\s*', seg)
    if not m:
        return _insert_field_in_span(seg, field, new_json_text)
    val_start = m.end()
    val_end = _find_value_end(seg, val_start)
    return seg[:val_start] + new_json_text + seg[val_end:]


def set_field_in_span(text, start, end, field, value):
    """在 [start, end) 内把 field 的值替换为 value；若该字段不存在则插入。返回新文本。

    支持三类字段：字符串字段(_STR_FIELDS)、整数字段(_INT_FIELDS)、JSON 字段(_JSON_FIELDS)。
    空值约定（避免往原本没有该字段的源里塞空值）：
      · 字符串字段传 "" / None → 删除该字段；
      · JSON 字段传 None → 删除该字段。
    """
    seg = text[start:end]
    if field in _STR_FIELDS:
        if value is None or value == "":
            seg2 = _remove_field_in_span(seg, field)
        else:
            pat = re.compile(r'("' + re.escape(field) + r'"\s*:\s*)"[^"]*"')
            new_val = json.dumps(str(value), ensure_ascii=False)
            seg2, cnt = pat.subn(lambda m: m.group(1) + new_val, seg, count=1)
            if cnt == 0:
                seg2 = _insert_field_in_span(seg, field, new_val)
    elif field in _JSON_FIELDS:
        if value is None:
            seg2 = _remove_field_in_span(seg, field)
        else:
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    pass  # 极端兜底：保持原字符串
            seg2 = _set_json_field_in_span(seg, field, json.dumps(value, ensure_ascii=False))
    else:
        if value is None:
            value = 0
        pat = re.compile(r'("' + re.escape(field) + r'"\s*:\s*)-?\d+')
        new_val = str(int(value))
        seg2, cnt = pat.subn(lambda m: m.group(1) + new_val, seg, count=1)
        if cnt == 0:
            seg2 = _insert_field_in_span(seg, field, new_val)
    return text[:start] + seg2 + text[end:]


def _insert_field_in_span(seg, field, new_val):
    """在一个 JSON 对象 {} 的末尾 } 前插入一个新字段。"""
    idx = seg.rfind("}")
    if idx < 0:
        raise ValueError("对象缺少结束 }")
    inner = seg[:idx].rstrip()
    if inner.endswith("{"):
        insertion = '\n            "%s": %s' % (field, new_val)
    else:
        insertion = ',\n            "%s": %s' % (field, new_val)
    return seg[:idx] + insertion + seg[idx:]


def delete_site(text, key):
    """按 key 删除一个站点条目，返回 (新文本, 被删条目 dict)。保留注释。"""
    spans = parse_site_spans(text)
    for s, e, obj in spans:
        if obj.get("key") == key:
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
    raise ValueError("未找到 key=%s 的站点" % key)


def update_site(text, key, field, value):
    """按 key 修改某字段，返回 (新文本, 原条目 dict)。保留注释。"""
    if field not in ALL_FIELDS:
        raise ValueError("不支持的字段：%s（可选 %s）" % (field, "/".join(ALL_FIELDS)))
    spans = parse_site_spans(text)
    for s, e, obj in spans:
        if obj.get("key") == key:
            return set_field_in_span(text, s, e, field, value), obj
    raise ValueError("未找到 key=%s 的站点" % key)


def site_fingerprint(obj):
    """返回条目「功能身份」签名（用于判重）。**不含 key**。

    ⚠️ 判重要点（2026-09-29 二次修正）：
      · **不能用 api 单独判重**。TVBox/影视仓里有一类 jar 型 spider 源，
        `api` 是 jar 内部的**类名**（如 `csp_PanWebShare`），同一个 jar 里的同一个
        类会被**许多条不同的站点**复用——它们靠 `ext`（往往是 `ext.site`=上游站点
        地址）区分。在 `lubin.php` 这种「多仓聚合 jar」里尤其典型：一个
        `csp_PanWebShare` 就对应 8 个完全不同的上游站点。只按 api 判重会把
        7 组共 30 条合法站点全部误报/误删（2026-09-29 用户实测截图）。
      · **key 也不能放进指纹**。key 是「本地唯一标签」，两条 entry 即便 key 不同，
        只要 (api, jar, ext) 全同，仍是**同一站点的重复登记**——key 放进指纹会让
        这种真重复被漏报（false negative）。

    所以功能身份 = `(type, api, jar, ext)` 四元组（2026-09-30 升级，原三元组缺 type）：
      · api 相同但 ext/jar 不同 → 不同站点（合法的多线路复用），**不报**；
      · (type, api, jar, ext) 全同 → 功能上真的重复，**报**（不论 key 是否相同）；
      · 同 api 但 type 不同（如 type:1 直连 CMS 与 type:3 用裸 URL 当 api 的畸形
        写法）→ 现在因 type 不同而**正确判为两条不同源**（之前会误判重复跳过）。
    ext 用 JSON 规范化（sort_keys）后再比对，避免字典键序不同导致漏判。
    """
    import json as _json
    ext = obj.get("ext")
    try:
        ext_sig = _json.dumps(ext, ensure_ascii=False, sort_keys=True) if ext is not None else ""
    except Exception:
        ext_sig = repr(ext)
    return (str(obj.get("type", "") or ""), str(obj.get("api") or ""),
            str(obj.get("jar") or ""), ext_sig)



def check_duplicates(sites):
    """查重：返回重复项的报告列表（字符串）。

    判重口径（2026-09-29 二次修正，见 site_fingerprint 说明）：
      · **key 重复** → 结构性冲突（key 是配置主标识，必须唯一）；
      · **(type + api + jar + ext) 完全一样** → 功能上重复（真重复，不论 key 是否相同）；
      · **仅 api 相同、ext/jar 不同** → **不报**（多线路共享同一 spider 类名，
        如 csp_PanWebShare / csp_Bili，是合法配置，不是重复）。
    注意：**name 不参与判重**（名字只是显示标签，可改可重名，重名不代表重复）。
    """
    from collections import Counter
    reports = []

    # 1) key 重复（真冲突；key 是条目的主标识）
    key_c = Counter(str(s.get("key")) for s in sites if s.get("key") is not None)
    for k, v in key_c.items():
        if v > 1:
            reports.append("重复 key=%s（出现 %d 次）" % (k, v))

    # 2) 功能身份重复：type + api + jar + ext 全同（不含 key）
    fp_c = Counter(site_fingerprint(s) for s in sites)
    for fp, v in fp_c.items():
        if v <= 1:
            continue
        typ, api, jar, ext_sig = fp
        parts = ["type=%s" % (typ if typ != "" else "（空）"), "api=%s" % (api or "（空）")]
        if jar:
            parts.append("jar=%s" % (jar if len(jar) <= 48 else jar[:45] + "…"))
        if ext_sig:
            parts.append("ext=%s" % (ext_sig if len(ext_sig) <= 48 else ext_sig[:45] + "…"))
        # 附上命中的 key / name，方便用户在列表里定位（同组可能多个不同 key）
        hit = [s for s in sites if site_fingerprint(s) == fp]
        labels = []
        for s in hit[:6]:
            k = str(s.get("key") or "")
            n = str(s.get("name") or "")
            labels.append(k if not n else "%s(%s)" % (k, n))
        if len(hit) > 6:
            labels.append("…等 %d 条" % len(hit))
        reports.append("重复（%s）〔%s〕（出现 %d 次）"
                       % ("，".join(parts), "；".join(labels), v))
    return reports


def _remove_span(text, s, e):
    """删除 [s, e) 及其相邻的一个逗号，返回新文本（保持数组合法）。"""
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
        return text[:prev_comma] + text[e:]
    if next_comma is not None:
        return text[:s] + text[next_comma + 1:]
    return text[:s] + text[e:]


def deduplicate_sites(text):
    """按「功能身份」去重：保留每个身份首次出现的条目，删除后续重复。
    返回 (新文本, 删除项列表 [(key, name, reason), ...])。

    ⚠️ 判重口径与 check_duplicates 一致（2026-09-29 二次修正）：
      · 只有 **key 重复** 或 **四元组 (type,api,jar,ext) 全同（不含 key）** 才算重复、才删；
      · **仅 api 相同、ext/jar 不同**（多线路共享同一 spider 类名，如
        csp_PanWebShare / csp_Bili）**不删**——它们是不同的站点。
    """
    spans = parse_site_spans(text)
    seen_keys = set()
    seen_fps = set()
    removals = []  # (start, end, key, name, reason)
    for s, e, obj in spans:
        key = obj.get("key")
        reason = None
        fp = site_fingerprint(obj)
        if key is not None and str(key) in seen_keys:
            reason = "key=%s 重复" % key
        elif fp in seen_fps:
            reason = "重复（api=%s，jar/ext 相同）" % (obj.get("api") or "")
        else:
            if key is not None:
                seen_keys.add(str(key))
            seen_fps.add(fp)
        if reason:
            removals.append((s, e, key, obj.get("name", ""), reason))
    new_text = text
    removed = []
    for s, e, key, name, reason in reversed(removals):
        new_text = _remove_span(new_text, s, e)
        removed.append((key, name, reason))
    removed.reverse()
    return new_text, removed


# ----------------------------------------------------------------------------
# 成人内容自动检测（读取 .py 内容 / 站点名，判定是否涉及 NSFW，用于分级管理）
# ----------------------------------------------------------------------------
# 关键词经过实测调优：剔除在影视仓仓库里产生误报的泛义词
#   - 情色：豆瓣等影视站只是把「情色」当作电影分类标签（武侠/西部/灾难/情色）
#   - 福利：短剧站里是「免费/会员福利」之意，并非成人
#   - 骚：uaa有声「激情骚麦」是 ASMR 音频分类，非成人
#   - 性感：过于泛义，常出现在普通写真/穿搭语境
#   - jav（英文裸词）：哔哩影视的混淆加密串里恰好含 "jav" 子串，非真 JAV
# 保留全部明确指向成人内容的词（成人/色情/无码/三级/少妇/偷情/裸体/裸聊…），
# 宁可少量边界站点（如含 19+ / erotic / nude 分类的站点）被标出，也好过漏标。
_ADULT_ZH = (
    "成人", "色情", "裸体", "裸聊", "裸照", "性爱", "做爱", "性交", "性奴",
    "淫乱", "淫荡", "淫水", "三级片", "A片", "无码", "有码", "中出", "内射", "颜射",
    "麻豆", "18禁", "限制级", "援交", "约炮", "一夜情", "人妻", "少妇", "熟女",
    "制服诱惑", "SM", "凌辱", "迷奸", "肛交", "口交", "乳交", "足交", "群交", "轮奸",
    "波多野", "苍井空", "吉泽明步", "天海翼", "番号", "老司机", "色站",
    "AV女优", "女优", "援交妹", "偷情", "约啪", "欲女",
)
_ADULT_EN = (
    "porn", "pornhub", "xvideos", "xnxx", "xhamster", "youporn", "redtube",
    "hentai", "javhd", "nsfw", "adult", "nude", "naked", "milf",
    "gangbang", "bukkake", "creampie", "fetish", "erotic", "sexvideo", "sextube",
    "onlyfans", "camgirl", "sexuality",
)


def api_to_path(repo_dir, api):
    """把 api（如 ./py/xxx.py）解析为仓库下的绝对路径。"""
    a = (api or "").replace("\\", "/")
    if a.startswith("./"):
        a = a[2:]
    return os.path.normpath(os.path.join(repo_dir, a.replace("/", os.sep)))


def cfg_base_dir(repo_dir, cfg_name):
    """返回「基准目录」= 配置文件所在目录。
    api 路径（./py/xxx.py）与 py/ 目录都应相对它解析——
    配置文件可能在子目录（如 sub/xxx.json），此时并非所选仓库根目录。"""
    cfg_name = str(cfg_name or "")
    repo_dir = str(repo_dir or "")
    if os.path.isabs(cfg_name):
        d = os.path.dirname(cfg_name)
    else:
        d = os.path.dirname(os.path.join(repo_dir, cfg_name))
    return d or repo_dir


def resolve_spider_path(base_dir, api, alt_dir=None):
    """解析 spider .py 真实路径：优先配置文件所在目录(base_dir)，
    找不到再回退 alt_dir（通常是所选仓库根目录），仍找不到返回 base_dir 下的路径。
    解决「配置在子目录、按根目录拼接导致 .py 找不到」的问题。"""
    cands = []
    for b in (base_dir, alt_dir):
        if b and b not in cands:
            cands.append(b)
    for b in cands:
        p = api_to_path(b, api)
        if os.path.isfile(p):
            return p
    return api_to_path(base_dir or alt_dir or ".", api)


def detect_adult(py_path, site_name=""):
    """读取 .py 文件内容与站点名，判断是否涉及成人内容。
    返回 (是否成人, 命中的关键词或 None)。"""
    parts = [site_name or ""]
    try:
        parts.append(read_text(py_path))
    except Exception:
        pass
    hay = "\n".join(parts).lower()
    for w in _ADULT_ZH:
        if w in hay:
            return True, w
    for w in _ADULT_EN:
        if re.search(r"\b" + re.escape(w) + r"\b", hay):
            return True, w
    return False, None


# ----------------------------------------------------------------------------
# 短剧源检测（与成人检测同框架：读 .py 内容 + 站点名，关键词判定）
# 「短剧」一词在影视仓仓库里非常特异（短剧站点的名称、分类、接口注释里必有），
# 误报风险极低；「微短剧/短剧场」只是其叠加词，列出仅为日志可读性。
# ----------------------------------------------------------------------------
_DUANJU_ZH = ("短剧", "微短剧", "短剧场")
_DUANJU_EN = ("duanju", "short drama", "shortdrama")


def detect_duanju(py_path, site_name=""):
    """读取 .py 文件内容与站点名，判断是否为短剧类源。
    返回 (是否短剧, 命中的关键词或 None)。"""
    parts = [site_name or ""]
    try:
        parts.append(read_text(py_path))
    except Exception:
        pass
    hay = "\n".join(parts).lower()
    for w in _DUANJU_ZH:
        if w in hay:
            return True, w
    for w in _DUANJU_EN:
        if re.search(r"\b" + re.escape(w) + r"\b", hay):
            return True, w
    return False, None


# ----------------------------------------------------------------------------
# 直播源检测（与成人/短剧/直播检测同框架：读 .py 内容 + 站点名，关键词判定）
# 自 2026-09 新增：龙哥明确「讨厌直播」，要求把含直播的 py 源挑出来一键禁用。
# 关键词特意排除裸 "live"（英文里 live data / live preview / deliver / alive 等
# 大量出现会严重误报），改用 livetv / iptv / live stream / streaming 等特异词；
# 中文以「直播」为主，叠加「秀场 / 直播间 / 主播」提高召回（这些词在影视仓生态里
# 几乎专指直播）。如需要更激进（连裸 live 也算），可在 _LIVE_EN 里加回 "live"。
# ----------------------------------------------------------------------------
_LIVE_ZH = ("直播", "秀场", "直播间", "主播")
_LIVE_EN = ("livetv", "live tv", "iptv", "live stream", "live-stream", "streaming")


def detect_live(py_path, site_name=""):
    """读取 .py 文件内容与站点名，判断是否为直播类源。
    返回 (是否直播, 命中的关键词或 None)。"""
    parts = [site_name or ""]
    try:
        parts.append(read_text(py_path))
    except Exception:
        pass
    hay = "\n".join(parts).lower()
    for w in _LIVE_ZH:
        if w in hay:
            return True, w
    for w in _LIVE_EN:
        if re.search(r"\b" + re.escape(w) + r"\b", hay):
            return True, w
    return False, None


def default_search_roots(repo_dir, cfg_name):
    """返回「读取不到 .py 时」自动遍历搜索的根目录列表（去重、保序）：
       ① exe 主文件所在目录  ② 仓库根目录  ③ 配置文件所在目录。
    同名 .py 取首个匹配；用于 py 文件夹被改名/移动后找回 spider 文件。"""
    roots = []
    for r in (get_app_dir(), repo_dir, cfg_base_dir(repo_dir, cfg_name)):
        if r and os.path.isdir(r) and r not in roots:
            roots.append(r)
    return roots


def discover_py_files(roots, progress_cb=None, stop_check=None):
    """递归遍历 roots，建立 {小写文件名: 完整路径} 映射（同名取首个出现）。
    用于 .py 所在文件夹被改名/移动后，自动找回 spider 文件。
    progress_cb(done, total, dirname)：每扫描一个目录回调一次（total 恒为 0
       表示未知总量，进度条按忙碌指示显示）。
    stop_check()：返回 True 时立即中止（如对话框已关闭，避免无意义遍历）。
    限制递归深度并跳过无关目录，避免误入巨型目录树导致卡死。"""
    MAX_DEPTH = 8
    SKIP = (".git", ".idea", "node_modules", "__pycache__",
            ".venv", "venv", "dist", "build", ".workbuddy")
    name_map = {}
    done = 0
    roots = [r for r in roots if r and os.path.isdir(r)]
    if not roots:
        return name_map
    for root in roots:
        if stop_check and stop_check():
            break
        for cur, subdirs, files in os.walk(root):
            if stop_check and stop_check():
                break
            rel = os.path.relpath(cur, root)
            depth = 0 if rel == "." else rel.count(os.sep)
            if depth > MAX_DEPTH:
                subdirs[:] = []
                continue
            subdirs[:] = [d for d in subdirs if d not in SKIP]
            for f in files:
                if f.lower().endswith(".py"):
                    key = f.lower()
                    if key not in name_map:
                        name_map[key] = os.path.join(cur, f)
            done += 1
            if progress_cb:
                try:
                    progress_cb(done, 0, cur)
                except Exception:
                    pass
    return name_map


def resolve_spider_path_resilient(base_dir, api, alt_dir=None, name_map=None):
    """同 resolve_spider_path，但找不到时若给定 name_map（由 discover_py_files
    预建），按 api 文件名回退匹配。返回 (路径, 是否来自遍历搜索)。"""
    p = resolve_spider_path(base_dir, api, alt_dir)
    if os.path.isfile(p):
        return p, False
    if name_map:
        bn = os.path.basename(api_to_path(base_dir, api)).lower()
        p2 = name_map.get(bn)
        if p2 and os.path.isfile(p2):
            return p2, True
    return p, False


BACKUP_KEEP = 10  # 备份轮转：backups/ 目录只保留最近 N 份


def backup_and_write(repo_dir, new_text, cfg_name=CONFIG_NAME):
    """备份配置文件到 repo/backups/（按时间戳存档，只留最近 BACKUP_KEEP 份）后写入 new_text。
    返回备份文件完整路径。历史行为（配置同目录 <cfg>.bak.<ts>）已废弃，旧散落备份不受影响。"""
    cfg = cfg_name if os.path.isabs(cfg_name) else os.path.join(repo_dir, cfg_name)
    bdir = os.path.join(os.path.dirname(cfg), "backups")
    try:
        os.makedirs(bdir, exist_ok=True)
    except Exception:
        bdir = os.path.dirname(cfg)  # 建不了目录（只读盘等）退回同目录
    ts = datetime.now().strftime("%Y%m%d-%H%M%S%f")  # 含微秒：快速连续写入不互相覆盖
    bak = os.path.join(bdir, "%s.%s.bak" % (os.path.basename(cfg), ts))
    shutil.copy2(cfg, bak)
    # 轮转：按修改时间倒序，超出 BACKUP_KEEP 的旧备份删除
    try:
        olds = sorted(glob.glob(os.path.join(bdir, "*.bak")), key=os.path.getmtime, reverse=True)
        for p in olds[BACKUP_KEEP:]:
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        pass
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(new_text)
    return bak


def list_backups(repo_dir, cfg_name=CONFIG_NAME):
    """列出仓库 backups/ 目录下该配置的备份（新→旧）。供 GUI「恢复备份」与测试使用。"""
    cfg = cfg_name if os.path.isabs(cfg_name) else os.path.join(repo_dir, cfg_name)
    bdir = os.path.join(os.path.dirname(cfg), "backups")
    pat = os.path.join(bdir, "%s.*.bak" % os.path.basename(cfg))
    try:
        return sorted(glob.glob(pat), key=os.path.getmtime, reverse=True)
    except Exception:
        return []


def trash_spider(repo_dir, py_path):
    """删除 spider .py 前先备份到 repo/py_trash/，返回备份路径；无需删除返回 None。
    用于「删除配置项时一并删除对应 .py」，保留可恢复副本以防误删。"""
    if not py_path or not os.path.isfile(py_path):
        return None
    trash = os.path.join(repo_dir, "py_trash")
    os.makedirs(trash, exist_ok=True)
    base = os.path.basename(py_path)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(trash, "%s.%s.bak" % (base, ts))
    shutil.copy2(py_path, dst)
    os.remove(py_path)
    return dst


def collect_orphan_py(base_dir, removed_keys, key_api, remaining, alt_dir=None, search_roots=None):
    """计算删除这些 key 时应一并删除的 .py 路径。
    base_dir: 基准目录（配置文件所在目录）；alt_dir: 回退目录（所选仓库根目录）。
    search_roots: 读取不到 .py 时自动遍历搜索的根目录（见 default_search_roots），
        为 None 则仅按 base_dir/alt_dir 解析。
    返回 (to_delete[py_path...], skipped[(path, reason)...])。"""
    to_delete, skipped = [], []
    name_map = discover_py_files(search_roots) if search_roots else None
    for key in removed_keys:
        api = key_api.get(key, "")
        if not api:
            continue
        py_path, _ = resolve_spider_path_resilient(base_dir, api, alt_dir, name_map)
        if not os.path.isfile(py_path):
            continue
        still = any(str(o.get("key", "")) != key and o.get("api", "") == api for o in remaining)
        if still:
            skipped.append((py_path, "仍有其它站点引用同一 .py，跳过删除"))
            continue
        to_delete.append(py_path)
    return to_delete, skipped


# ----------------------------------------------------------------------------
# v14：URL 源地址可达性检测 + 禁用/启用（注释掉 JSON 条目）
# ----------------------------------------------------------------------------
# URL 提取：从 spider .py 文本里抓出所有 http(s) 源地址；
# 可达性：多种方法（TCP 连接 + HTTP GET），任一方法成功即判为有效；
# 禁用：把对应站点条目用 /* [disabled] ... */ 注释块包起来（TVBox 等解析器会忽略），
#       需要时在列表里增加「禁用」列供管理，并可一键启用还原。
_URL_RE = re.compile(r'https?://[^\s"\'<>]+', re.IGNORECASE)
_DISABLE_MARK = "[disabled]"


def extract_urls_from_py(py_path):
    """从 spider .py 文本中提取所有 http(s) URL（去重，保持出现顺序）。
    用于检测站点源地址是否仍然可达。返回 URL 列表。"""
    try:
        txt = read_text(py_path)
    except Exception:
        return []
    urls = []
    seen = set()
    for m in _URL_RE.finditer(txt):
        # 去掉结尾常见标点（中英文句号、括号、分号等），它们不是地址一部分
        u = m.group(0).rstrip(".,;)\u3002\uff09]}")
        # 必须含主机名（至少一点），过滤掉形如 http:// 的占位
        if re.match(r'https?://[^\s"\'<>]+\.[^\s"\'<>]+', u) is None:
            continue
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def _method_tcp_connect(url, timeout=2.5):
    """方法一：TCP 连接到 URL 主机:端口（默认 80/443）。
    主机在线即视为可达，最快。返回 (是否可达, 方法描述)。"""
    from urllib.parse import urlparse
    p = urlparse(url)
    host = p.hostname
    if not host:
        return False, ""
    port = p.port or (443 if p.scheme.lower() == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "tcp:%d" % port
    except Exception:
        return False, ""


def _method_http_get(url, timeout=4.0):
    """方法二：HTTP GET 请求（关闭证书校验，容忍自签/过期证书）。
    仅 2xx/3xx 视为可达；4xx/5xx（含代理返回的 502/504）视为不可达——
    避免代理拦截把死站误判为可达。TCP 连接（方法一）才是主机在线的权威信号。
    返回 (是否可达, 方法描述)。"""
    req = urllib.request.Request(
        url, method="GET",
        headers={"User-Agent": _HTTP_UA, "Accept": "*/*"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            code = resp.status or 200
            if 200 <= code < 400:
                return True, "http:%d" % code
            return False, "http:%d" % code
    except urllib.error.HTTPError as e:
        if 200 <= e.code < 400:
            return True, "http:%d" % e.code
        return False, "http:%d" % e.code
    except Exception:
        return False, ""


def check_url_reachable(url, tcp_timeout=2.5, http_timeout=4.0):
    """多种方法检测单个 URL 是否可达：TCP 连接 + HTTP GET，任一成功即有效。
    返回 (可达:bool, 方法:str, 错误:str)。"""
    methods = [_method_tcp_connect, _method_http_get]
    last_err = ""
    for fn in methods:
        to = tcp_timeout if fn is _method_tcp_connect else http_timeout
        try:
            ok, info = fn(url, to)
        except Exception as ex:
            ok, info = False, str(ex)[:80]
        if ok:
            return True, info, ""
        if info:
            last_err = info
    return False, "", last_err


def check_site_urls(py_path, max_urls=2):
    """检测某个站点对应 .py 中提取的所有 URL 的可达性。
    任一 URL 可达即判为有效。返回 dict：
        reachable: True / False / None（None=未从 .py 提取到 URL）
        method, url, note, urls。"""
    urls = extract_urls_from_py(py_path)
    if not urls:
        return {"reachable": None, "method": "", "url": "",
                "note": "未从 .py 中提取到 URL", "urls": []}
    tested = urls[:max_urls]
    for u in tested:
        ok, method, err = check_url_reachable(u)
        if ok:
            return {"reachable": True, "method": method, "url": u, "note": "", "urls": urls}
    return {"reachable": False, "method": "", "url": tested[0],
            "note": "前 %d 个 URL 的 TCP/HTTP 均不可达" % len(tested), "urls": urls}


def check_source_reachability(entry, base_dir=None, max_urls=2):
    """按 type 检测站点可达性（统一入口，替代直接调 check_site_urls 的 .py 写死）：
      - type:1（直连 CMS）：直接探 api（HTTP 可达即有效）
      - type:3 且本地有 .py：复用 check_site_urls 从 .py 文本抽取 URL 检测
      - type:0/4 或兜底：若 api 是 http 则 HTTP 探之
    返回 dict: {reachable, urls, note, method}；reachable 为 True/False/None。"""
    api = str(entry.get("api") or "")
    t = _norm_type(entry.get("type"))
    is_spider = (api.startswith("csp_")
                 or api.endswith((".py", ".js", ".jar", ".drpy"))
                 or t == 3)
    if t == 1 and api.startswith("http"):
        ok, method, _ = check_url_reachable(api)
        return {"reachable": ok, "urls": [api] if ok else [],
                "note": "直连 CMS 接口可达性", "method": method}
    if is_spider and base_dir:
        py_path = resolve_spider_path(base_dir, api)
        if py_path and os.path.isfile(py_path):
            return check_site_urls(py_path, max_urls=max_urls)
    if api.startswith("http"):
        ok, method, _ = check_url_reachable(api)
        return {"reachable": ok, "urls": [api] if ok else [],
                "note": "HTTP 接口可达性", "method": method}
    return {"reachable": None, "urls": [], "note": "无 URL 可检测", "method": ""}


def dead_source_keys(entries, url_map=None, file_map=None):
    """汇总「**已检测判定失效**」的站点 key（供「🩹 一键剔除失效源」使用）。

    只用两种**明确失效**信号，绝不把「未检测」算作失效（否则会误伤好源）：
      · url_map[key]  = (code, method, note)，code == 0 → URL 不可达
      · file_map[key] = "missing"                      → 本地脚本缺失

    返回 {"unreachable": [...], "missing_file": [...], "keys": [...]}
    （keys 已去重，顺序沿用 entries 顺序，便于用户逐条核对）。
    """
    unreach, missing = [], []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        k = str(e.get("key", ""))
        if not k:
            continue
        u = (url_map or {}).get(k)
        if u is not None:
            try:
                if str(u[0]) == "0":
                    unreach.append(k)
            except Exception:
                pass
        if (file_map or {}).get(k) == "missing":
            missing.append(k)
    keys = []
    for k in unreach + missing:
        if k not in keys:
            keys.append(k)
    return {"unreachable": unreach, "missing_file": missing, "keys": keys}


def _extract_first_object(inner):
    """从一段文本中提取首个 {...} 对象（正确处理字符串内花括号与转义）。
    用于从 /* [disabled] ... */ 注释块内取出被禁用的站点条目。返回 dict 或 None。"""
    i = inner.find("{")
    if i < 0:
        return None
    depth = 0
    j = i
    n = len(inner)
    while j < n:
        c = inner[j]
        if c == '"':
            k = j + 1
            while k < n:
                if inner[k] == "\\":
                    k += 2
                    continue
                if inner[k] == '"':
                    break
                k += 1
            j = k + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    if depth != 0:
        return None
    try:
        return parse_jsonc(inner[i:j + 1])
    except Exception:
        return None


def _extract_first_object_span(inner):
    """返回 inner 中首个 {...} 对象的原始文本（含内部换行/缩进，不含尾部逗号）。"""
    i = inner.find("{")
    if i < 0:
        return None
    depth = 0
    j = i
    n = len(inner)
    while j < n:
        c = inner[j]
        if c == '"':
            k = j + 1
            while k < n:
                if inner[k] == "\\":
                    k += 2
                    continue
                if inner[k] == '"':
                    break
                k += 1
            j = k + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    if depth != 0:
        return None
    return inner[i:j + 1]


def _find_disabled_blocks(text):
    """返回 [(start, end, obj, obj_text), ...]：被 /* [disabled] ... */ 包裹的站点条目。
    start/end 为整个注释块边界；obj_text 为块内 {对象} 原始文本。"""
    try:
        start, close = find_sites_close(text)
    except Exception:
        return []
    blocks = []
    i, n = start, close
    while i < n:
        if text[i] == "/" and i + 1 < n and text[i + 1] == "*" and _DISABLE_MARK in text[i:i + 60]:
            j = i + 2
            while j + 1 < n and not (text[j] == "*" and text[j + 1] == "/"):
                j += 1
            j += 2
            inner = text[i:j]
            obj = _extract_first_object(inner)
            obj_text = _extract_first_object_span(inner)
            if obj is not None and obj_text is not None and "key" in obj:
                blocks.append((i, j, obj, obj_text))
            i = j
            continue
        i += 1
    return blocks


def _parse_site_tokens(text):
    """按 sites 数组内出现顺序产出 token 列表，每个为 dict：
        {"kind": "active"/"disabled", "obj": {...}, "text": "{...} 原始对象文本"}
    active 文本来自 parse_site_spans；disabled 文本来自 /* [disabled] */ 块内对象。"""
    try:
        start, close = find_sites_close(text)
    except Exception:
        return []
    spans = parse_site_spans(text)
    items = [(s, "active", obj, text[s:e]) for s, e, obj in spans]
    for bstart, bend, obj, obj_text in _find_disabled_blocks(text):
        items.append((bstart, "disabled", obj, obj_text))
    items.sort(key=lambda t: t[0])
    return [{"kind": k, "obj": obj, "text": txt} for _pos, k, obj, txt in items]


def _rebuild_sites_body(tokens):
    """由 token 列表重新拼装 sites 数组体（介于 [ 与 ] 之间）。
    逗号仅在相邻 active 条目之间插入；disabled 条目以注释块形式插入、不产生逗号——
    因此任意「禁用 / 启用」组合均保持数组合法（彻底避免悬空逗号问题）。"""
    parts = []
    for t in tokens:
        if t["kind"] == "disabled":
            parts.append(("comment", "/* " + _DISABLE_MARK + "\n" + t["text"].rstrip("\n") + "\n*/"))
        else:
            parts.append(("active", t["text"]))
    out = []
    need_comma = False
    for kind, piece in parts:
        if kind == "active":
            if need_comma:
                out.append(",")
            out.append("\n    " + piece)
            need_comma = True
        else:
            out.append("\n    " + piece)
    return "".join(out) + "\n"


def _apply_site_kind(text, key, to_disabled):
    """将指定 key 的条目在 active/disabled 间切换（重建 sites 数组体）。
    to_disabled=True 表示禁用，False 表示启用。返回 (新文本, 是否找到)。"""
    tokens = _parse_site_tokens(text)
    found = False
    for t in tokens:
        if t["obj"].get("key") != key:
            continue
        if to_disabled and t["kind"] == "active":
            t["kind"] = "disabled"
            found = True
            break
        if (not to_disabled) and t["kind"] == "disabled":
            t["kind"] = "active"
            found = True
            break
    if not found:
        return text, False
    start, close = find_sites_close(text)
    new_body = _rebuild_sites_body(tokens)
    return text[:start] + new_body + text[close:], True


def parse_sites_with_disabled(text):
    """返回 [(obj, disabled), ...]：active 条目 disabled=False，注释禁用的 disabled=True。"""
    return [(t["obj"], t["kind"] == "disabled") for t in _parse_site_tokens(text)]


def parse_disabled_keys(text):
    """返回当前被禁用（注释掉）的站点 key 集合。"""
    return {str(t["obj"].get("key", "")) for t in _parse_site_tokens(text)
            if t["kind"] == "disabled"}


def disable_site(text, key):
    """禁用指定 key 的站点（注释掉对应配置，TVBox 等将忽略）。
    返回 (新文本, 是否找到)。保留其它条目与配置不变。"""
    return _apply_site_kind(text, key, True)


def enable_site(text, key):
    """启用指定 key 的站点（取消注释，恢复为可用）。返回 (新文本, 是否找到)。"""
    return _apply_site_kind(text, key, False)


# ----------------------------------------------------------------------------
# 多配置合并导入 / 干净配置导出
# ----------------------------------------------------------------------------
# 设计要点：
#   · 一切往来都以「站点条目列表」为准，不直接信任对方 JSON 的字段完整性 ——
#     先用 normalize_site() 归一到统一 7 字段，缺项补 TVBox 惯例默认值；
#   · 合并到当前配置时走「先删后插」的手术式改写，保留原配置的注解与其余条目；
#   · 导出时用 _rebuild_sites_body() 重建 sites 数组体，其余字段原样保留。
_SITE_BOOL_TRUE = ("1", "true", "yes", "on")
_SITE_BOOL_FALSE = ("0", "false", "no", "off", "")
# ⚠️ 必须是纯 ASCII：urllib 要求 HTTP 头值 latin-1 可编码，放中文会让
#    所有走 urllib 的请求直接崩（latin-1 codec can't encode）——2026-09-28 踩过。
_HTTP_UA = "SourceKeeper/1.0 (YuanGuanJia)"


def infer_type(api, default=3):
    """影视仓 / TVBox 的 sites[].type 是「接口类型」数字：
        0 = XML（极少用）
        1 = JSON 直连（CMS 类，如 api.php/provide/vod、普通 http(s) 接口）
        3 = Spider（jar / js / py / csp_* 全部归这一类；具体引擎由
            api 字段的后缀 .py/.js/.jar 或 csp_ 前缀区分，*不* 靠 type）
        4 = T4 / 目录型（Alist、WebDAV 等）
    本工具主要服务 spider，无法判断时回落 default（默认 3）。"""
    a = (api or "").strip().lower()
    if not a:
        return default
    if a.startswith("csp_") or a.endswith((".py", ".js", ".jar", ".drpy")):
        return 3
    if a.startswith("http://") or a.startswith("https://"):
        # 直连 CMS 接口（含 provide/vod）用 JSON(1)；其余无法判断回落 default
        return 1
    return default


def source_type_of(entry):
    """返回一条站点条目的「有效 type」（用于 GUI/CLI 分流，权威口径）：
    - 条目自带有效 type → 用它（兼容字符串 "py" 等影视仓变体仍返回原值）
    - 否则按 api 用 infer_type 推断
    返回 int（0/1/3/4）或字符串（变体 type）；无法判断时返回 3。"""
    t = _norm_type(entry.get("type"))
    if t is not None:
        return t
    return infer_type(str(entry.get("api") or ""))


def expects_local_file(entry):
    """判断一条站点是否「应有本地资源文件」（供缺失校验 / 遍历搜索 / 弹框分流）。

    关键区分（2026-09-29 修正）：
      - **jar 型 spider**：`csp_*` 前缀的 api 有**两种**情形——
          a) 本地 `.py` 文件名为 `csp_XXX.py`（有 .py 后缀）→ 有本地文件；
          b) 远程 jar 内的类名（条目带 `"jar": "http://..."` 字段，如 `csp_Config`）
             → **无本地文件**，绝不能被当成缺失 .py 而误报。
        判定：条目带 `jar` 字段、或 api 非 `.py/.js/.drpy` 后缀 → jar 型 → False。
      - type:1 直连 CMS / type:0 XML / type:4 目录型 → False
      - api 含 `://`（远程源）→ False
      - 其它：api 以 `.py/.js/.drpy` 结尾（本地 Spider 脚本）→ True
    本质：只有「本地 spider 脚本文件」才需要/能够做存在性校验与遍历找回。"""
    api = str(entry.get("api") or "").strip()
    if not api:
        return False
    t = source_type_of(entry)
    # 明确的非本地类型（直连 / XML / 目录）直接排除
    if t in (0, 1, 4):
        return False
    if "://" in api:                      # 远程源（含远程 spider）
        return False
    # jar 型 spider：带 jar 字段（远程 jar 里的类名，如 csp_Config）→ 无本地文件
    if entry.get("jar"):
        return False
    a = api.lower()
    if a.endswith((".py", ".js", ".drpy")):   # 本地 spider 脚本文件
        return True
    # 其余（含无后缀的 csp_XXX jar 类名、无后缀本地路径）：无本地脚本文件
    return False


def open_target_of(entry, base_dir=None, repo_dir=None, resolved_py=None):
    """按 type 判定一条站点「能打开什么」，供 GUI 的单击/双击/右键菜单分流。

    ⚠️ 不能一律当 .py 打开：不同 type 的条目要打开的东西完全不同（2026-09-29 修）：
      · type:3 本地 Spider（api 以 .py/.js/.drpy 结尾）→ 打开**本地脚本文件**；
      · type:3 jar 型 Spider（带 `jar` 字段，api 是类名如 csp_HuyaLiveAmns）
        → 本地无 .py，**打开远程 jar URL**（下载/浏览器）；
      · type:3 远程脚本（api 是 http 的 .py/.js）→ 打开该 URL；
      · type:1 直连 CMS / type:0·4 http 源 → 打开 **api 接口链接**；
      · type:4 目录型（本地路径）→ 打开该**目录**。

    返回 dict：
        kind: "file"（本地脚本）/ "jar"（远程 jar）/ "url"（api 链接）/
              "dir"（本地目录）/ "none"
        path: 本地路径（kind=file/dir 时有）
        url : 链接（kind=jar/url 时有）
        label: 菜单/提示用的中文说明
        note : 无法打开时的原因说明
    """
    api = str(entry.get("api") or "").strip()
    jar = str(entry.get("jar") or "").strip()
    t = source_type_of(entry)

    # 1) jar 型 spider：api 是类名、jar 指远程 jar → 打开 jar（不是本地 .py）
    if t == 3 and jar and not api.lower().endswith((".py", ".js", ".drpy")):
        return {"kind": "jar", "path": None, "url": jar,
                "label": "打开所依赖的 jar（远程）",
                "note": "该源为 jar 型 Spider（api=%s 是 jar 内类名，无本地 .py）" % (api or "（空）")}

    # 2) 远程脚本/接口：api 本身就是 http(s) URL → 打开链接
    if api.startswith("http://") or api.startswith("https://"):
        low = api.lower().split("?")[0]
        is_script = low.endswith((".py", ".js", ".jar", ".drpy"))
        return {"kind": "url", "path": None, "url": api,
                "label": "打开远程脚本" if is_script else "打开 API 链接",
                "note": ""}

    # 3) 本地 Spider 脚本：api 以 .py/.js/.drpy 结尾 → 打开本地文件
    if api.lower().endswith((".py", ".js", ".drpy")) or (resolved_py and os.path.isfile(resolved_py)):
        p = resolved_py or (resolve_spider_path(base_dir, api, repo_dir) if api else None)
        if p and os.path.isfile(p):
            return {"kind": "file", "path": p, "url": None,
                    "label": "打开脚本文件", "note": ""}
        return {"kind": "none", "path": p, "url": None, "label": "",
                "note": "未找到对应的脚本文件：\n%s" % (p or api)}

    # 4) type:4 目录型 + 本地路径 → 打开目录
    if t == 4 and api and "://" not in api:
        d = resolve_spider_path(base_dir, api, repo_dir) if base_dir else api
        return {"kind": "dir", "path": d, "url": None,
                "label": "打开目录", "note": ""}

    # 5) type:3 但 api 既非脚本后缀也无 jar：可能是本地无后缀指向目录的代理
    if t == 3 and api and "://" not in api:
        return {"kind": "dir", "path": resolve_spider_path(base_dir, api, repo_dir)
                if base_dir else api,
                "url": None, "label": "打开所在目录", "note": ""}

    return {"kind": "none", "path": None, "url": None, "label": "",
            "note": "该条目（api=%s）没有可打开的本地文件或链接。" % (api or "（空）")}



def _norm_type(v, default=3):
    """把任意 type 值归一成「合法 type」：
    - None / 空 / 布尔 → None（让调用方回落 infer_type）
    - 数字 / 数字字符串 → int
    - 其它字符串（影视仓变体可能用 "py" / "json" 这类 spider 类型）→ 原样保留"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return s


def normalize_site(obj):
    """把任意来源的站点 dict 归一为统一字段结构（缺项补默认）。
    返回 dict：key / name / api / type / filterable / quickSearch / searchable。
    非预期类型（None、字符串 "true" 等）按 TVBox 惯例折叠为 bool/int。"""

    def _b(v, default=True):
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        if isinstance(v, str):
            s = v.strip().lower()
            if s in _SITE_BOOL_TRUE:
                return True
            if s in _SITE_BOOL_FALSE:
                return False
        return default

    def _i(v, default=0):
        try:
            return int(v)
        except Exception:
            return default

    # ⚠️ 判重口径：区分「来源显式带 type」与「来源缺 type」。
    #   - 显式带 type（含 type=0！注意 0 是假值，不能用 `0 or infer` 误覆盖）→ 直接采用；
    #   - 缺 type → 回落 infer_type(api) 尽力推断（纯 URL 无法区分 XML/目录，只能给 best-effort）。
    _MISSING = object()
    raw_type = obj.get("type", _MISSING)
    if raw_type is _MISSING:
        typ = infer_type(obj.get("api"))
    else:
        typ = _norm_type(raw_type)
        if typ is None:
            # 来源写了 null/""/true/false 等无效 type → 回落推断
            typ = infer_type(obj.get("api"))
    return {
        "key": str(obj.get("key") or "").strip(),
        "name": str(obj.get("name") or "").strip(),
        "api": str(obj.get("api") or "").strip(),
        "type": typ,
        "filterable": _b(obj.get("filterable"), True),
        "quickSearch": _b(obj.get("quickSearch"), True),
        "searchable": _b(obj.get("searchable"), True),
    }


def normalize_site_full(obj):
    """归一化并**保留全部原始字段**（合并导入专用，修复「丢字段」根因）。

    仅对 7 个核心字段做类型归正（复用 normalize_site），其余字段
    （ext/jar/adult/changeable/categories/hide/playUrl/style/playerType/genre/indexs…）
    **原样保留**——TVBox/影视仓 配置里这些字段承载关键信息（如 jar 型多站点的
    ext.site 上游地址、adult 成人标记），丢了源就废了。

    注意：normalize_site 仍保留给只需核心字段的场景（其余测试/调用方白名单读取）。"""
    out = normalize_site(obj)
    for k, v in obj.items():
        if k in out:
            continue
        out[k] = v
    return out


def _strip_trailing_commas(text):
    """宽松容错：删除「,] / ,}」（尾逗号）。
    手改过的配置常在最后一个条目后落下尾逗号（严格 JSON 非法），
    此时不应整份拒绝导入 —— 先做这层清理再解析。
    仅应在 strip_jsonc_comments() 之后调用：注释里的 ']' / '}' 会干扰判断。
    逐字符扫描并跟踪字符串状态：字符串内的 ',}'/',]' 原样保留，
    只有真正落在数组/对象「收尾处」的逗号才被丢弃。"""
    out = []
    i, n, in_str = 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1          # 命中：丢掉这个逗号
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_config_text(text):
    """解析配置文本为 dict/list，容忍尾逗号等手改痕迹。失败抛 ValueError。"""
    try:
        return parse_jsonc(text)
    except Exception as ex:
        try:
            # 先去注释（注释里的 */ 会挡在尾逗号与 ] 之间），再清尾逗号
            return parse_jsonc(_strip_trailing_commas(strip_jsonc_comments(text)))
        except Exception:
            raise ValueError("不是合法的 JSON / JSONC：%s" % ex)


def load_sites_from_text(text):
    """解析一份配置文本 → [(obj, disabled), ...]（obj 为归一后的条目）。
    兼容三种形态：
      1) dict 且含 sites 数组（保留 /* [disabled] */ 注释掉的条目及其禁用状态）；
      2) dict 但无法按文本解析（退化为纯 JSON 取值，disabled 一律为 False）；
      3) 顶层就是站点数组的 JSON。
    无有效条目时返回空列表（由调用方决定提示文案）。"""
    try:
        data = parse_config_text(text)
    except Exception as ex:
        raise ValueError("不是合法的 JSON / JSONC：%s" % ex)
    items = []
    had_entry = False
    if isinstance(data, list):
        had_entry = bool(data)
        items = [(normalize_site_full(s), False) for s in data if isinstance(s, dict)]
    elif isinstance(data, dict):
        arr = data.get("sites")
        if not isinstance(arr, list):
            raise ValueError("配置中未找到 sites 数组")
        had_entry = bool(arr)
        try:
            pairs = parse_sites_with_disabled(text)
            items = [(normalize_site_full(obj), dis) for obj, dis in pairs]
        except Exception:
            items = [(normalize_site_full(s), False) for s in arr if isinstance(s, dict)]
    else:
        raise ValueError("配置内容不是 JSON 对象或数组")
    # 只保留至少能看出身份的条目（同时有 key 与 api 的视为脏数据）
    items = [it for it in items if it[0]["key"] or it[0]["api"]]
    if not items and had_entry:
        raise ValueError("配置里没有可识别的站点条目（每条需含 key 或 api）")
    return items


def load_sites_from_file(path):
    """读取配置文件路径 → [(obj, disabled), ...]。文件不存在/解析失败抛异常。"""
    if not os.path.isfile(path):
        raise ValueError("文件不存在：%s" % path)
    return load_sites_from_text(read_text(path))


# ---------------------------------------------------------------------------
# 远程抓取：直连失败时的镜像回退
# 生态里 GitHub raw 被墙/超时是最高频的失败原因（各同类工具的标配做法是挂镜像前缀）。
# 原则：**只在直连彻底失败后**才按顺序试镜像，并把用到的镜像如实上报；
#       直连能通就绝不走镜像 —— 避免拿到镜像缓存的旧内容还不自知。
# 仅对 github 系主机生效（本地/局域网/其它站点一律不走镜像），避免测试与内网行为漂移。
# ---------------------------------------------------------------------------
MIRROR_FALLBACK = True
_PREFIX_MIRRORS = (
    "https://ghfast.top/",
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
    "https://gh.llkk.cc/",
)
_MIRROR_HOSTS = ("raw.githubusercontent.com", "github.com", "www.github.com",
                 "gist.githubusercontent.com", "objects.githubusercontent.com",
                 "codeload.github.com", "raw.github.com")


def _mirror_urls(url):
    """给出该 URL 的镜像候选（前缀式 + jsDelivr 特例）；非 github 系主机返回 []。"""
    u = str(url or "")
    if not u.startswith(("http://", "https://")):
        return []
    try:
        from urllib.parse import urlsplit
        sp = urlsplit(u)
    except Exception:
        return []
    host = (sp.netloc or "").split("@")[-1].split(":")[0].lower()
    if host not in _MIRROR_HOSTS:
        return []
    out = [m + u for m in _PREFIX_MIRRORS]
    # jsDelivr 需要形式转换：
    #   https://raw.githubusercontent.com/<user>/<repo>/<branch>/<path>
    # → https://cdn.jsdelivr.net/gh/<user>/<repo>@<branch>/<path>
    if host in ("raw.githubusercontent.com", "raw.github.com"):
        parts = [p for p in sp.path.split("/") if p]
        if len(parts) >= 4:
            out.append("https://cdn.jsdelivr.net/gh/%s/%s@%s/%s"
                       % (parts[0], parts[1], parts[2], "/".join(parts[3:])))
    else:
        # github.com/<user>/<repo>/raw/<branch>/<path> 也可转 jsDelivr
        parts = [p for p in sp.path.split("/") if p]
        if len(parts) >= 5 and parts[2] in ("raw", "blob"):
            out.append("https://cdn.jsdelivr.net/gh/%s/%s@%s/%s"
                       % (parts[0], parts[1], parts[3], "/".join(parts[4:])))
    return out


def _http_read(url, timeout=10):
    """单次 HTTP GET，返回 bytes；失败抛 ValueError（含 HTTP 非 2xx / 空内容）。"""
    req = urllib.request.Request(url, headers={"User-Agent": _HTTP_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as ex:
        raise ValueError("HTTP %s" % ex.code)
    except Exception as ex:
        raise ValueError(str(ex))


def _fetch_url_bytes(url, timeout=10, info=None, allow_mirror=None):
    """直连优先、失败后镜像回退地取回 bytes。

    info：可选 dict，原地写入 {"mirror": 实际使用的镜像 URL 或 None, "error": 直连错误}
    allow_mirror：None=按主机自动判定；False=禁用镜像。
    """
    if info is not None:
        info.setdefault("mirror", None)
    direct_err = ""
    try:
        return _http_read(url, timeout)
    except Exception as ex:
        direct_err = str(ex)
    if info is not None:
        info["error"] = direct_err
    if allow_mirror is None:
        # 自动判定：只有 github 系主机才有镜像候选（内网/其它站点天然为空）
        allow_mirror = True
    if MIRROR_FALLBACK and allow_mirror:
        for mu in _mirror_urls(url):
            try:
                data = _http_read(mu, timeout)
                if data:
                    if info is not None:
                        info["mirror"] = mu
                    return data
            except Exception:
                continue
    raise ValueError(direct_err or ("下载失败：%s" % url))


def fetch_text_from_url(url, timeout=10, info=None, allow_mirror=None):
    """抓取远程配置文本（raw JSON / JSONC 均可）。失败抛 ValueError（含 HTTP 非 2xx）。
    直连失败时自动尝试镜像（ghproxy / jsDelivr 等），并在 info["mirror"] 里如实上报。"""
    try:
        raw = _fetch_url_bytes(url, timeout, info=info, allow_mirror=allow_mirror)
    except Exception as ex:
        raise ValueError("下载失败：%s（%s）" % (url, ex))
    body = raw.decode("utf-8", "ignore")
    if not body.strip():
        raise ValueError("远程内容为空：%s" % url)
    return body


def fetch_binary_from_url(url, timeout=15, info=None, allow_mirror=None):
    """抓取远程二进制资源（如 .jar），返回 bytes。失败抛 ValueError（含 HTTP 非 2xx）。
    直连失败时自动尝试镜像（ghproxy / jsDelivr 等），并在 info["mirror"] 里如实上报。"""
    try:
        return _fetch_url_bytes(url, timeout, info=info, allow_mirror=allow_mirror)
    except Exception as ex:
        raise ValueError("下载失败（%s）：%s" % (ex, url))


def _urljoin(base, rel):
    """把相对路径拼到远程基址上（统一用 / 分隔）。"""
    from urllib.parse import urljoin
    return urljoin(base, rel.replace("\\", "/"))


def _remote_companion_candidates(remote_base, target_repo_dir, entry):
    """返回该条目需从远程基址下载的 (remote_url, dst_abs, rel) 列表；无则 []。
    仅当 api/jar 是「相对本地路径」（非 http(s) URL）时才下载。"""
    out = []
    api = str(entry.get("api") or "").strip()
    rel = local_api_relpath(api)
    if rel:
        out.append((_urljoin(remote_base, rel),
                    os.path.join(target_repo_dir, rel.replace("/", os.sep)), rel))
    jar = str(entry.get("jar") or "").strip()
    if jar and not jar.startswith("http") and "://" not in jar:
        out.append((_urljoin(remote_base, jar),
                    os.path.join(target_repo_dir, jar.replace("/", os.sep)), jar))
    return [p for p in out if p[0] and p[1]]


def _remote_deep_refs(text, remote_base, target_repo_dir, base_rel):
    """扫描远程主脚本源码，递归找出需下载的同伴文件 (remote_url, dst_abs, rel)。

    与本地搬运共用 `iter_companion_refs`（同一套引用识别口径），
    覆盖 require/load/import 引号引用（含裸名、模板串、省略扩展名）+ Python 行首 import。
    """
    out = []
    for rel in sorted(iter_companion_refs(text, base_rel)):
        out.append((_urljoin(remote_base, rel),
                    os.path.join(target_repo_dir, rel.replace("/", os.sep)), rel))
    return out


def copy_companions_remote(remote_base, target_repo_dir, *entry_lists, plan=None, decisions=None):
    """从远程配置基址下载本地 spider 的 .py/.js/.drpy/.jar 到目标仓库。

    文本脚本用 fetch_text_from_url、二进制 .jar 用 fetch_binary_from_url；下载主脚本后
    递归扫描 import/require 取同伴文件（封顶 4 层）。目标**同名且内容相同** → 跳过；
    **同名但内容不同** → 按 decisions 处置（默认重命名，也可 overwrite/skip）；
    网络失败 / 404 → missing_src（不中断整次合并）。
    decisions: {rel: "rename"|"overwrite"|"skip"}；缺省一律 "rename"。"""
    if plan is None:
        plan = plan_companion_files_remote(remote_base, target_repo_dir, *entry_lists)
    return _copy_from_plan(plan, target_repo_dir, decisions,
                           src_ref_fn=lambda r: _urljoin(remote_base, r))


def entries_from_items(items):
    """[(obj, disabled)] → 可直接交给 fmt_entry 的条目列表（丢弃 disabled 标记）。"""
    return [obj for obj, _dis in items]


def plan_merge(base_items, incoming_items):
    """计算合并计划（不做任何写盘）。
    base_items     = [(obj, disabled), ...] 当前配置已存在的条目（全字段 dict）；
    incoming_items = [(obj, disabled), ...] 待导入条目（已归一，全字段）。
    判重口径（2026-09-30 修正，之前合并结果错得离谱的根因之一）：
      · 功能身份 = site_fingerprint(obj) = (type, api, jar, ext) 四元组（见 site_fingerprint）。
        jar 型 spider 的 api 是 jar 内类名（如 csp_PanWebShare），同一个类名被很多
        不同站点复用，靠 ext（上游站点地址）区分 —— **绝不能用 api 单独判重**，
        否则 csp_PanWebShare×8 这类会被误并成 1 条，丢掉 7 组合法站点。
      · key 仅作「结构性冲突」：指纹不同但 key 相同 = 真撞 key，需改名/覆盖。
    返回 dict：
      {"rows": [ {obj, disabled, verdict, action, matched_key, new_key, reason}, ... ],
       "summary": {"new":.., "dup":.., "conflict":.., "skip":..}}
    verdict / 默认 action：
      new      = 不撞指纹也不撞 key，且批次内不重复        → action=add
      dup      = 与现有撞指纹（功能重复）                  → action=skip（可改 overwrite）
      conflict = 与现有撞 key 但指纹不同（结构冲突）        → action=add（new_key 自动改名）
      skip     = 批次内自身重复（同指纹或同 key）            → action=skip（锁定）"""
    base_fps = {}
    base_keys = set()
    for obj, _dis in base_items:
        fp = site_fingerprint(obj)
        if fp not in base_fps:
            base_fps[fp] = obj.get("key") or ""
        k = obj.get("key")
        if k:
            base_keys.add(k)

    rows = []
    seen_fps, seen_keys = set(), set()
    summary = {"new": 0, "dup": 0, "conflict": 0, "skip": 0}

    for obj, dis in incoming_items:
        fp = site_fingerprint(obj)
        key = obj.get("key") or ""
        verdict = action = matched_key = None
        new_key = key
        reason = None
        if fp in base_fps:
            verdict, action, matched_key = "dup", "skip", base_fps[fp]
        elif key and key in base_keys:
            verdict, action = "conflict", "add"
            new_key = _unique_key(key, seen_keys | base_keys)
        elif fp in seen_fps:
            verdict, action, reason = "skip", "skip", "与本次导入中的条目重复（type+api+jar+ext 相同）"
        elif key and key in seen_keys:
            verdict, action, reason = "skip", "skip", "与本次导入中的 %s 重复" % key
        else:
            verdict, action = "new", "add"
        seen_fps.add(fp)
        if key:
            seen_keys.add(key)
        if new_key and new_key != key:
            seen_keys.add(new_key)
        summary[verdict] += 1
        rows.append({"obj": obj, "disabled": dis, "verdict": verdict,
                     "action": action, "matched_key": matched_key,
                     "new_key": new_key, "reason": reason})
    return {"rows": rows, "summary": summary}


def _unique_key(base, taken):
    """在 taken 集合里找一个不冲突的 key：base / base_2 / base_3 ...。"""
    base = base or "key"
    if base not in taken:
        return base
    i = 2
    while ("%s_%d" % (base, i)) in taken:
        i += 1
    return "%s_%d" % (base, i)


def local_api_relpath(api):
    """若 api 指向本地 spider 脚本文件（./py/x.py 或 py/x.py），返回相对仓库的路径串
    （去 ./ 前缀、规范为 / 分隔）；否则返回 None（远程源 / jar 类名 / 目录型等无需搬运）。"""
    a = (api or "").strip()
    if not a:
        return None
    if a.startswith("http://") or a.startswith("https://") or "://" in a:
        return None
    if not a.lower().endswith((".py", ".js", ".drpy")):
        return None
    return (a[2:] if a.startswith("./") else a).replace("\\", "/")


def _rel_under(base, p):
    """若绝对路径 p 落在 base 目录内，返回相对 base 的归一化相对路径；否则返回 None
    （跨盘 / 不在源仓内 → 无法 rebase）。"""
    if not base:
        return None
    try:
        rel = os.path.relpath(p, base)
    except ValueError:
        return None
    if rel.startswith("..") or os.path.isabs(rel):
        return None
    return rel


def _resolve_pair(src_repo_dir, target_repo_dir, p):
    """把条目里的 api/jar 路径 p（可能绝对/相对、可能含 ./ 前缀）解析成 (src_abs, dst_abs)。
    绝对路径会按「源仓根 → 目标仓根」重算相对位置（rebase），避免绝对路径在新仓库失效。"""
    if os.path.isabs(p):
        if src_repo_dir:
            rel = _rel_under(src_repo_dir, p)
            if rel is None:
                # 不在源仓内（如系统盘路径）→ 无 rebase 意义，保持原绝对（调用方会跳过/告警）
                return p, p
            return p, os.path.join(target_repo_dir, rel)
        return p, p
    # 相对路径：按 src/target 仓库根拼接
    return (os.path.join(src_repo_dir, p.replace("/", os.sep)),
            os.path.join(target_repo_dir, p.replace("/", os.sep)))


def _companion_candidates(src_repo_dir, target_repo_dir, entry):
    """返回该条目需在源→目标仓库间搬运的 (src_path, dst_path) 列表；无则返回 []。
    同时支持：① 相对路径本地 spider（./py/x.py）；② 绝对路径 rebase 到目标仓相对位置；
    ③ 本地 jar 字段（相对或绝对）。"""
    out = []
    api = str(entry.get("api") or "").strip()
    rel = local_api_relpath(api)
    if rel:
        # 绝对 api 用原值做 rebase 解析；相对 api 用 rel（已去 ./）
        p = api if os.path.isabs(api) else rel
        out.append(_resolve_pair(src_repo_dir, target_repo_dir, p))
    jar = str(entry.get("jar") or "").strip()
    if jar and not jar.startswith("http") and "://" not in jar:
        out.append(_resolve_pair(src_repo_dir, target_repo_dir, jar))
    return [pair for pair in out if pair[0] and pair[1]]


# ---------------------------------------------------------------------------
# 同伴文件（companion）引用识别 —— 本地搬运与远程下载**共用同一口径**，
# 保证「能识别到的引用 = 能搬运 + 改名后能改写」。
# ---------------------------------------------------------------------------
_COMPANION_EXTS = (".js", ".py", ".drpy")

# JS/TS 风格的「带引号引用」：
#   require('./x.js') / require(`./x.js`) / load('./x.js') / import('./x.js') / from './x.js' / import './x.js'
_JS_REF_RE = re.compile(
    r"(?P<kw>\b(?:require|load|import)\s*\(\s*|\b(?:from|import)\s+)"
    r"(?P<q>['\"`])(?P<path>[^'\"`\r\n]+)(?P=q)")

# Python 行首 import：`import a, b` / `from a.b import x`
# ⚠️ 必须①锚行首 ②要求 import 之后到达行尾/注释 —— 否则会把 JS 的
#    `import c from './c.js'` 误判成 Python import，把模块名 c 改成 c_2（破坏代码）。
_PY_IMPORT_RE = re.compile(
    r"^[ \t]*(?:"
    r"from[ \t]+([A-Za-z_][\w\.]*)[ \t]+import\b"
    r"|"
    r"import[ \t]+([A-Za-z_][\w\.]*(?:[ \t]*,[ \t]*[A-Za-z_][\w\.]*)*)"
    r"[ \t]*(?=$|\r?\n|#|;|\))"
    r")", re.M)

# 常见标准库/第三方顶层名：深挖时跳过，避免刷出一堆 404/missing_src 噪声
_PY_STDLIB = frozenset({
    "os", "sys", "re", "json", "math", "time", "datetime", "urllib", "http",
    "requests", "base64", "hashlib", "random", "string", "collections", "functools",
    "itertools", "threading", "socket", "struct", "subprocess", "io", "csv", "glob",
    "shutil", "traceback", "copy", "types", "typing", "uuid", "zlib", "gzip",
    "aiohttp", "lxml", "bs4", "pyquery", "cachetools", "cloudscraper", "html",
})


def _ref_candidates(own_rel, path):
    """引用串 → [(仓库相对路径, guessed)] 候选列表。

    guessed=True 表示「引用串省略了扩展名、由我们补全出来的」候选
    （这类候选只有真实存在才值得搬运/上报，否则就是噪声，例如 `import os`）。
    """
    p = str(path or "").strip()
    if (not p or "://" in p or p.startswith("/") or p.startswith("\\")
            or p.startswith("#")):
        return []
    ext = os.path.splitext(p)[1].lower()
    if not p.startswith(".") and "/" not in p:
        if ext not in _COMPANION_EXTS:
            return []
    elif ext and ext not in _COMPANION_EXTS:
        return []
    d = os.path.dirname(own_rel)
    rel = os.path.normpath(os.path.join(d, p) if d else p).replace("\\", "/")
    if rel.startswith("..") or rel in (".", ""):
        return []
    if ext:
        return [(rel, False)]
    return [(rel + e, True) for e in _COMPANION_EXTS]


def _ref_candidate_rels(own_rel, path):
    """引用串 → 「仓库相对路径」候选列表（无扩展名时依次补 .js/.py/.drpy）。

    过滤规则（避免把无关文件卷进来）：
      · http(s):// 绝对 URL、以 / 或 \\ 开头的绝对路径、# 锚点 → 不视为本地同伴；
      · 带扩展名：仅 _COMPANION_EXTS 才认（`./data.json` 这类不搬）；
      · 裸名（无 ./ 前缀、无目录）：仅当扩展名属于 _COMPANION_EXTS 才认，
        于是 `require('b.js')` 认（同目录文件），`require('fs')`/`require('axios')` 不认；
      · 已带扩展名时**不再无脑拼 ext**（旧实现会产出 `x.js.py`/`x.js.drpy` 等噪声候选）。
    """
    return [r for r, _g in _ref_candidates(own_rel, path)]


def iter_companion_refs(text, own_rel, exists_fn=None):
    """列出 text 引用到的同伴文件「仓库相对候选路径」集合（best-effort）。

    own_rel：当前文件相对仓库根的路径（如 py/lib/a.js）。
    exists_fn(rel) → bool：给出源侧存在性判断时，**补全型候选**只有真实存在才保留
      （显式写出扩展名的引用即使不存在也会保留，以便上报真实缺失）。
    """
    refs = set()

    def _keep(rel, guessed):
        if not guessed or exists_fn is None:
            return True
        try:
            return bool(exists_fn(rel))
        except Exception:
            return True

    if not text:
        return refs
    for m in _JS_REF_RE.finditer(text):
        for rel, guessed in _ref_candidates(own_rel, m.group("path")):
            if _keep(rel, guessed):
                refs.add(rel)
    d = os.path.dirname(own_rel)
    for m in _PY_IMPORT_RE.finditer(text):
        mods = m.group(1) or m.group(2) or ""
        for part in mods.split(","):
            mp = part.strip().replace(".", "/")
            if not mp or mp.startswith(".") or mp.startswith("/"):
                continue
            if mp.split("/")[0] in _PY_STDLIB:
                continue
            cand = os.path.normpath(os.path.join(d, mp) if d else mp)
            cand = cand.replace("\\", "/")
            for ext in _COMPANION_EXTS:
                rel = cand + ext
                if _keep(rel, True):
                    refs.add(rel)
    refs.discard(own_rel)
    return refs


def _local_deep_refs(text, base_rel, exists_fn=None):
    """扫描 spider 源码，找出同目录被 import / require 的同伴文件相对路径（最佳努力）。
    base_rel: 当前文件相对仓库根的路径。返回相对仓库根的候选路径集合。"""
    return iter_companion_refs(text, base_rel, exists_fn)


# ---------------------------------------------------------------------------
# 条目 ext 字段里的「本地脚本路径」引用识别
# ext 形态很杂：JSON 字符串（TVBox 常见）/"k=v" 串/"a.js|b.js" 串/dict/list/裸串。
# 取法：递归取所有字符串 → 按 | 换行 = 切 token → 用与「文件内引用」**同一套白名单
# 口径**判定（同 _COMPANION_EXTS、跳过 http(s):// 与绝对路径），于是
#   {"site": "./py/lib/x.js"} → 搬运；{"site": "https://a/x.js"} → 不动。
# 目的：消灭「ext 里藏本地脚本路径时静默漏搬」这一条链。
# ---------------------------------------------------------------------------
_EXT_EXTS = _COMPANION_EXTS + (".jar",)
_EXT_SPLIT_RE = re.compile(r"[|\r\n]")
_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_abs_path(p):
    """判断是否为绝对路径（含 Windows 盘符，跨平台判定一致）。"""
    return bool(_DRIVE_ABS_RE.match(str(p or ""))) or os.path.isabs(str(p or ""))


def _ext_token_rels(tok):
    """ext 里的一个字符串 token → [(rel, explicit)]。

    explicit=True：token 自带脚本扩展名（.js/.py/.drpy/.jar）→ 原样当路径用，
      即使源侧不存在也如实上报 missing_src（与「文件内显式引用缺失要上报」同口径）。
    explicit=False：无扩展名，只认 `./x` / `../x` 这类明确路径写法，且**必须源侧真实
      存在**才采纳（避免把 ext 里的普通配置串当文件；远程无法判定时一律不采纳）。
    """
    p = str(tok or "").strip().strip("'\"`").strip()
    if (not p or "://" in p or p.startswith("/") or p.startswith("\\")
            or p.startswith("#") or p.startswith("?")):
        return []
    # 绝对路径（含 Windows 盘符）不按「仓库相对路径」处理：本层只认相对引用，
    # 免得把 D:\x.js 之类的系统路径拼成仓库内的伪路径。
    if _looks_abs_path(p):
        return []
    ext = os.path.splitext(p)[1].lower()
    if ext in _EXT_EXTS:
        rel = os.path.normpath(p).replace("\\", "/")
        if rel.startswith("..") or rel in (".", "/", ""):
            return []
        return [(rel, True)]
    if not p.startswith("."):
        return []
    rel = os.path.normpath(p).replace("\\", "/")
    if rel.startswith("..") or rel in (".", "/", ""):
        return []
    return [(rel + e, False) for e in _COMPANION_EXTS]


def iter_ext_refs(entry, exists_fn=None):
    """条目 ext 字段引用的「本地脚本」→ 仓库相对路径集合（best-effort）。

    exists_fn(rel) → bool：本地来源传入，用于判定「无扩展名补全候选」是否真实存在。
    """
    if not isinstance(entry, dict):
        return set()
    ext = entry.get("ext")
    if ext is None or ext == "" or ext == {} or ext == []:
        return set()
    strs = []

    def _walk(v, depth=0):
        if depth > 6:
            return
        if isinstance(v, dict):
            for vv in v.values():
                _walk(vv, depth + 1)
        elif isinstance(v, (list, tuple)):
            for vv in v:
                _walk(vv, depth + 1)
        elif isinstance(v, str):
            s = v.strip()
            if s[:1] in ("{", "[") and len(s) < 500000:
                try:
                    _walk(json.loads(s), depth + 1)
                    return
                except Exception:
                    pass
            strs.append(v)

    _walk(ext)
    refs = set()
    for s in strs:
        for piece in _EXT_SPLIT_RE.split(s):
            for tok in piece.split("="):
                for rel, explicit in _ext_token_rels(tok):
                    if not explicit:
                        if exists_fn is None:
                            continue
                        try:
                            if not exists_fn(rel):
                                continue
                        except Exception:
                            continue
                    refs.add(rel)
    return refs


MAX_DEEP_DEPTH = 4
_LARGE_CMP_BYTES = 64 * 1024 * 1024    # 超过此大小只比大小，避免大文件整读/整比


def _read_bytes(path):
    """读文件原始字节；失败返回 None。"""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except Exception:
        return None


def _same_content(a, b):
    """字节级内容比对（同名文件冲突检测用）。超大文件退化为「只看大小」。"""
    if a is None or b is None:
        return False
    if len(a) != len(b):
        return False
    if len(a) > _LARGE_CMP_BYTES:
        return True
    return a == b


def _propose_rel(rel, taken, exists_fn=None):
    """给「同名但内容不同」的文件提一个不撞名的候选相对路径：py/x.py → py/x_2.py。"""
    d = os.path.dirname(rel)
    stem, ext = os.path.splitext(os.path.basename(rel))
    i = 2
    while True:
        name = "%s_%d%s" % (stem, i, ext)
        cand = ("%s/%s" % (d, name)) if d else name
        if cand not in taken and not (exists_fn and exists_fn(cand)):
            return cand
        i += 1


def _stem_rel(rel):
    return os.path.splitext(rel)[0]


def _rel_to_dot(rel, d):
    """相对路径 → Python 点号模块名（相对目录 d）；不在 d 之下则 None。"""
    try:
        r = os.path.relpath(_stem_rel(rel), d or ".")
    except Exception:
        return None
    if r.startswith("..") or os.path.isabs(r):
        return None
    return r.replace("\\", "/").replace("/", ".")


def _rel_to_dotpath(rel, d):
    """相对路径 → JS require 用的 './x' 形式（相对目录 d）；不在 d 之下则 None。"""
    try:
        r = os.path.relpath(_stem_rel(rel), d or ".")
    except Exception:
        return None
    if r.startswith("..") or os.path.isabs(r):
        return None
    r = r.replace("\\", "/")
    return r if r.startswith(".") else "./" + r


def _ref_style_rebuild(orig, new_rel, own_rel):
    """按原引用串的写法风格，把新目标 rel 还原成同风格引用串。
    保持：是否带 `./` 前缀、是否用裸名（同目录）、是否省略扩展名。"""
    d = os.path.dirname(own_rel)
    try:
        rel = os.path.relpath(new_rel, d or ".")
    except Exception:
        return None
    rel = rel.replace("\\", "/")
    if rel.startswith("..") or rel in (".", ""):
        return None
    if not os.path.splitext(orig)[1]:
        rel = os.path.splitext(rel)[0]          # 原串省略扩展名 → 新串也省略
    bare = (not orig.startswith(".")) and ("/" not in orig)
    if bare and "/" not in rel:
        return rel
    return rel if rel.startswith(".") else "./" + rel


def _rewrite_refs(text, own_rel, rename_map):
    """把 text 中对「已改名同伴文件」的引用改写为新名（best-effort）。

    覆盖两种风格，且**只在引用语句内**替换（避免误伤同名变量/字符串外的代码）：
      · JS：require/load/import(...) 与 from/import '...' 的引号引用
            （含裸名 `require('b.js')`、模板串、省略扩展名 `require('./lib/a')`）；
      · Python：**行首** import / from 的点号模块名。
    ⚠️ Python 分支必须锚行首，否则 JS 的 `import c from './c.js'` 会被当成
       Python import，把模块名 c 改写成 c_2 —— 这是旧实现的真实 bug（破坏代码）。
    """
    if not rename_map:
        return text
    d = os.path.dirname(own_rel)

    def _new_rel_of(path):
        for cand in _ref_candidate_rels(own_rel, path):
            if cand in rename_map:
                return rename_map[cand]
        return None

    def _rep_js(m):
        path = m.group("path")
        nr = _new_rel_of(path)
        if not nr:
            return m.group(0)
        new_txt = _ref_style_rebuild(path, nr, own_rel)
        if not new_txt or new_txt == path:
            return m.group(0)
        return m.group("kw") + m.group("q") + new_txt + m.group("q")

    text = _JS_REF_RE.sub(_rep_js, text)

    def _map_dot(mod):
        mp = mod.replace(".", "/")
        cand = os.path.normpath(os.path.join(d, mp) if d else mp).replace("\\", "/")
        for ext in _COMPANION_EXTS:
            if cand + ext in rename_map:
                return _rel_to_dot(rename_map[cand + ext], d)
        return None

    def _rep_py(m):
        whole = m.group(0)
        mods = m.group(1) or m.group(2) or ""
        if not mods:
            return whole
        if m.group(1):
            nm = _map_dot(mods)
            return whole.replace(mods, nm) if nm else whole
        parts = [x.strip() for x in mods.split(",")]
        newmods = ", ".join((_map_dot(x) or x) for x in parts)
        return whole.replace(mods, newmods) if newmods != mods else whole

    return _PY_IMPORT_RE.sub(_rep_py, text)


def _backup_companion(target_repo_dir, rel):
    """覆盖目标配套文件前先备份到 <target>/backups/companions/<rel>.<ts>.bak。"""
    import time as _time
    src = os.path.join(target_repo_dir, rel.replace("/", os.sep))
    if not os.path.isfile(src):
        return None
    ts = "%s-%06d" % (_time.strftime("%Y%m%d-%H%M%S"),
                      int((_time.time() % 1) * 1000000))
    bak = os.path.join(target_repo_dir, "backups", "companions",
                       rel.replace("/", os.sep) + "." + ts + ".bak")
    try:
        d = os.path.dirname(bak)
        if d:
            os.makedirs(d, exist_ok=True)
        shutil.copy2(src, bak)
        return bak
    except Exception:
        return None


def _entry_rel(v):
    """条目里的 api/jar 路径 → 仓库相对路径；URL / 空 → None。"""
    v = str(v or "").strip()
    if not v or v.startswith("http") or "://" in v:
        return None
    return (v[2:] if v.startswith("./") else v).replace("\\", "/")


def _rewrite_ext_str(s, rename_map):
    """把 ext 里字符串中「指向已改名文件」的路径改写为新名（best-effort）。

    只做**路径 token 级**替换，不重排/不重排 JSON 格式（ext 常是 JSON 串，
    文本替换可保住原有空白与转义，避免把配置写坏）。
    """
    out = str(s)
    pairs = [(str(o), str(n)) for o, n in (rename_map or {}).items()
             if o and n and str(o) != str(n)]
    if not pairs or not out:
        return out
    # ① 先改带 ./ 前缀的写法（更具体，避免被裸路径规则抢先）
    for o, n in pairs:
        out = out.replace("./" + o, "./" + n)
    # ② 再改裸路径：加边界断言，避免误伤更长路径（a/b.js 里的 b.js）与变量名
    for o, n in pairs:
        out = re.sub(r"(?<![\w./\\\-])" + re.escape(o) + r"(?![\w])",
                     lambda _m, _n=n: _n, out)
    return out


def _rewrite_ext_value(v, rename_map, depth=0):
    """递归改写 ext（dict / list / 字符串 / JSON 串）里的本地脚本路径。"""
    if depth > 6:
        return v
    if isinstance(v, dict):
        return {k: _rewrite_ext_value(vv, rename_map, depth + 1) for k, vv in v.items()}
    if isinstance(v, list):
        return [_rewrite_ext_value(vv, rename_map, depth + 1) for vv in v]
    if isinstance(v, str):
        return _rewrite_ext_str(v, rename_map)
    return v


def _apply_rename_to_entry(obj, rename_map):
    """若条目 api/jar（或 ext 里引用的本地脚本）指向的文件已改名，同步改写为新名。"""
    if not rename_map:
        return obj
    for f in ("api", "jar"):
        v = str(obj.get(f) or "").strip()
        rel = _entry_rel(v)
        if rel and rel in rename_map:
            new = rename_map[rel]
            obj[f] = ("./" + new) if v.startswith("./") else new
    ext = obj.get("ext")
    if ext is not None and ext != "" and ext != {} and ext != []:
        obj["ext"] = _rewrite_ext_value(ext, rename_map)
    return obj


def _plan_companions(target_repo_dir, candidates, fetch_fn, deep_fn, src_ref_fn):
    """统一的配套文件规划：枚举 → 取源内容 → 与目标同名文件比对 → 给冲突项提改名建议。

    candidates: [(rel, kind, src_ref)]；fetch_fn(rel, src_ref) → bytes|None（None=取不到）；
    deep_fn(text, rel) → set[rel]（同伴引用）；src_ref_fn(rel) → 上报用的源引用（本地绝对路径 / 远程 URL）。
    返回 {"items","map","cache","conflicts","same","missing","new"}；不写任何文件。"""
    items, seen, taken = [], set(), set()
    rename_map, cache = {}, {}
    queue = []
    for rel, kind, src_ref in candidates:
        rk = rel.replace("\\", "/")
        taken.add(rk)
        queue.append((rk, kind, src_ref, 0))
    exists_fn = (lambda r: os.path.isfile(os.path.join(target_repo_dir, r.replace("/", os.sep)))) \
        if target_repo_dir else None
    while queue:
        rel, kind, src_ref, depth = queue.pop(0)
        if rel in seen:
            continue
        seen.add(rel)
        data = fetch_fn(rel, src_ref)
        cache[rel] = data
        dst = os.path.join(target_repo_dir, rel.replace("/", os.sep)) if target_repo_dir else ""
        exists = bool(dst) and os.path.isfile(dst)
        if data is None:
            items.append({"rel": rel, "kind": kind, "deep": depth > 0, "exists": exists,
                          "same": False, "missing": True, "new_rel": None, "src_ref": src_ref})
            continue
        same, new_rel = False, None
        if exists:
            same = _same_content(data, _read_bytes(dst))
            if not same:
                new_rel = _propose_rel(rel, taken, exists_fn)
                rename_map[rel] = new_rel
                taken.add(new_rel)
        items.append({"rel": rel, "kind": kind, "deep": depth > 0, "exists": exists,
                      "same": same, "missing": False, "new_rel": new_rel, "src_ref": src_ref})
        if kind == "text" and depth < MAX_DEEP_DEPTH:
            try:
                txt = data.decode("utf-8", "ignore")
            except Exception:
                txt = ""
            try:
                refs = deep_fn(txt, rel)
            except Exception:
                refs = set()
            for r in refs or []:
                rr = str(r).replace("\\", "/")
                if rr and rr not in seen:
                    queue.append((rr, "text", src_ref_fn(rr), depth + 1))
    return {"items": items, "map": rename_map, "cache": cache,
            "conflicts": [it for it in items if it.get("new_rel")],
            "same": [it["rel"] for it in items if it["same"]],
            "missing": [it["rel"] for it in items if it["missing"]],
            "new": [it["rel"] for it in items if not it["exists"] and not it["missing"]]}


def _local_entry_rels(src_repo_dir, target_repo_dir, entry):
    """本地来源：条目 → [(rel, kind, src_abs)]。含 api/jar 与 ext 里引用的本地脚本。"""
    out = []
    for sp, dp in _companion_candidates(src_repo_dir, target_repo_dir, entry):
        try:
            rel = os.path.relpath(dp, target_repo_dir) if target_repo_dir else dp
        except Exception:
            continue
        rel = rel.replace(os.sep, "/")
        if rel.startswith(".."):
            continue
        out.append((rel, "bin" if rel.lower().endswith(".jar") else "text", sp))
    if target_repo_dir:
        ex = (lambda r: os.path.isfile(
            os.path.join(src_repo_dir, r.replace("/", os.sep)))) if src_repo_dir else None
        for rel in sorted(iter_ext_refs(entry, exists_fn=ex)):
            sp = os.path.join(src_repo_dir, rel.replace("/", os.sep)) if src_repo_dir else rel
            out.append((rel, "bin" if rel.lower().endswith(".jar") else "text", sp))
    return out


def _remote_entry_rels(remote_base, target_repo_dir, entry):
    """远程来源：条目 → [(rel, kind, url)]。含 api/jar 与 ext 里引用的本地脚本。"""
    out = []
    for url, _dp, rel in _remote_companion_candidates(remote_base, target_repo_dir, entry):
        rel = str(rel).replace("\\", "/")
        out.append((rel, "bin" if rel.lower().endswith(".jar") else "text", url))
    for rel in sorted(iter_ext_refs(entry)):          # 远程无法 stat → 只认显式扩展名
        rel = str(rel).replace("\\", "/")
        out.append((rel, "bin" if rel.lower().endswith(".jar") else "text",
                    _urljoin(remote_base, rel)))
    return out


def plan_companion_files_local(src_repo_dir, target_repo_dir, *entry_lists):
    """规划本地来源的配套文件搬运（含内容级冲突检测与改名建议），不写盘。"""
    cands = []
    for entries in entry_lists:
        for e in entries or []:
            if isinstance(e, dict):
                cands.extend(_local_entry_rels(src_repo_dir, target_repo_dir, e))
    return _plan_companions(
        target_repo_dir, cands,
        fetch_fn=lambda rel, ref: _read_bytes(os.path.join(src_repo_dir, rel.replace("/", os.sep))),
        # 本地可 stat：无扩展名补全出来的候选只有真存在才搬（避免 x.py/x.drpy 噪声 missing）
        deep_fn=lambda text, rel: _local_deep_refs(
            text, rel,
            exists_fn=lambda r: os.path.isfile(
                os.path.join(src_repo_dir, r.replace("/", os.sep)))),
        src_ref_fn=lambda rel: os.path.join(src_repo_dir, rel.replace("/", os.sep)))


def plan_companion_files_remote(remote_base, target_repo_dir, *entry_lists):
    """规划远程来源的配套文件下载（含内容级冲突检测与改名建议），不写盘。"""
    cands = []
    for entries in entry_lists:
        for e in entries or []:
            if isinstance(e, dict):
                cands.extend(_remote_entry_rels(remote_base, target_repo_dir, e))

    mirrors = {}

    def _fetch(rel, ref):
        url = ref or _urljoin(remote_base, rel)
        info = {}
        try:
            if rel.lower().endswith(".jar"):
                data = fetch_binary_from_url(url, info=info)
            else:
                data = fetch_text_from_url(url, info=info).encode("utf-8")
        except Exception:
            return None
        if info.get("mirror"):
            mirrors[rel] = info["mirror"]
        return data

    def _deep(text, rel):
        return {r for _u, _d, r in _remote_deep_refs(text, remote_base, target_repo_dir, rel)}

    plan = _plan_companions(target_repo_dir, cands, _fetch, _deep,
                            src_ref_fn=lambda rel: _urljoin(remote_base, rel))
    plan["mirrors"] = mirrors          # {rel: 实际使用的镜像 URL}，供 GUI 如实上报
    return plan


def _resolve_rename_map_from_plan(plan, decisions):
    """从规划 + 用户处置中解出「改名映射」{old_rel: new_rel}（仅 rename 决策）。"""
    m = {}
    if not plan:
        return m
    for it in plan.get("items", []):
        if not it.get("new_rel"):
            continue
        dec = (decisions or {}).get(it["rel"], "rename")
        if dec == "rename":
            m[it["rel"]] = it["new_rel"]
    return m


def _decode_utf8_or_none(data):
    """严格按 UTF-8 解码；失败返回 None。

    ⚠️ 改写引用前必须用严格解码：旧实现用 `decode("utf-8","ignore")`，
    遇到 GBK 编码的 .js 会丢字节再按 UTF-8 写回 → **原文件被写坏**。
    宁可放弃改写（记为 ref_skipped_encoding，交人工处理），也绝不损坏用户文件。
    """
    try:
        return data.decode("utf-8")
    except Exception:
        return None


def _copy_from_plan(plan, target_repo_dir, decisions, src_ref_fn):
    """按规划落盘：内容相同→跳过；冲突按 decisions（rename 默认 / overwrite / skip）；
    复制文本文件时按改名映射改写其内部 import/require 引用。返回统计 dict。"""
    stats = {"copied": [], "skipped": [], "missing_src": [],
             "renamed": [], "conflict_skipped": [], "backed_up": [],
             "ref_skipped_encoding": [], "via_mirror": []}
    if not plan or not target_repo_dir:
        return stats
    mirror_map = plan.get("mirrors") or {}
    rename_map = _resolve_rename_map_from_plan(plan, decisions)
    for it in plan.get("items", []):
        rel = it["rel"]
        kind = it.get("kind", "text")
        if it.get("missing"):
            stats["missing_src"].append(it.get("src_ref") or src_ref_fn(rel))
            continue
        if it.get("same"):
            stats["skipped"].append(rel)
            continue
        if it.get("new_rel"):
            dec = (decisions or {}).get(rel, "rename")
            if dec == "skip":
                stats["conflict_skipped"].append(rel)
                continue
            dst_rel = rel if dec == "overwrite" else it["new_rel"]
        else:
            dst_rel = rel
        data = plan.get("cache", {}).get(rel)
        if data is None:
            stats["missing_src"].append(it.get("src_ref") or src_ref_fn(rel))
            continue
        if kind != "bin" and rename_map:
            txt = _decode_utf8_or_none(data)
            if txt is None:
                # 非 UTF-8（如 GBK）：绝不改写，避免把原文件写坏；只记录待人工核对
                stats["ref_skipped_encoding"].append(rel)
            else:
                try:
                    new_txt = _rewrite_refs(txt, rel, rename_map)
                except Exception:
                    new_txt = txt
                if new_txt != txt:
                    data = new_txt.encode("utf-8")
        dst_abs = os.path.join(target_repo_dir, dst_rel.replace("/", os.sep))
        if os.path.isfile(dst_abs) and dst_rel == rel:
            bak = _backup_companion(target_repo_dir, rel)
            if bak:
                stats["backed_up"].append(bak)
        try:
            d = os.path.dirname(dst_abs)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(dst_abs, "wb") as fh:
                fh.write(data)
        except Exception:
            stats["skipped"].append(rel)
            continue
        if dst_rel != rel:
            stats["renamed"].append(dst_rel)
        else:
            stats["copied"].append(dst_rel)
        if mirror_map.get(rel):
            stats["via_mirror"].append(dst_rel)
    return stats


def copy_companions(src_repo_dir, target_repo_dir, *entry_lists, plan=None, decisions=None):
    """把本地 spider 的 .py/.js/.drpy 与本地 jar 从源仓库搬运到目标仓库。

    **内容级冲突处理**：目标存在**同名**文件时不再一律跳过 ——
      · 内容相同 → 跳过（真正无变化）；
      · 内容不同 → 按 decisions 处置，默认「重命名」（py/x.py → py/x_2.py，两侧都不破坏），
        也可选 "overwrite"（覆盖前先备份目标文件）或 "skip"（不搬，需人工处理）。
    源不存在 → missing_src。另支持绝对路径 rebase 与递归深挖同伴文件（封顶 4 层）。
    decisions: {rel: "rename"|"overwrite"|"skip"}；缺省一律 "rename"。"""
    if plan is None:
        plan = plan_companion_files_local(src_repo_dir, target_repo_dir, *entry_lists)
    return _copy_from_plan(
        plan, target_repo_dir, decisions,
        src_ref_fn=lambda r: os.path.join(src_repo_dir, r.replace("/", os.sep)))


def _rebase_entry(entry, src_repo_dir):
    """若条目的 api/jar 是源仓内的绝对路径，重写为目标仓相对路径（./...），
    使合并后的配置在新仓库里能正确解析。无法 rebase 的（跨盘/系统路径）原样保留。"""
    if not src_repo_dir:
        return entry
    e = dict(entry)
    for f in ("api", "jar"):
        v = str(e.get(f) or "").strip()
        if v and os.path.isabs(v) and not v.startswith("http") and "://" not in v:
            rel = _rel_under(src_repo_dir, v)
            if rel:
                e[f] = "./" + rel.replace(os.sep, "/")
    return e


def replace_site(text, key, entry):
    """用 entry（已归一条目）覆盖 key 对应的现有条目（先删后插，保留其余内容）。
    支持该条目原本处于 /* [disabled] */ 注释态。返回新文本。"""
    spans = [(s, e) for s, e, obj in parse_site_spans(text) if obj.get("key") == key]
    try:
        spans += [(s, e) for s, e, obj, _ot in _find_disabled_blocks(text)
                  if obj.get("key") == key]
    except Exception:
        pass
    new_text = text
    for s, e in sorted(spans, reverse=True):
        new_text = _remove_span(new_text, s, e)
    return insert_into_sites(new_text, [entry])


def _find_in_entries(pairs, key):
    for obj, _dis in pairs:
        if obj["key"] == key:
            return obj
    return None


def _as_pairs(items):
    """把混合输入统一成 [(obj, disabled), ...]：
    既接受 (obj, disabled) 二元组，也接受裸 obj 列表（disabled 记 False）。"""
    pairs = []
    for it in items or []:
        if isinstance(it, tuple) and len(it) == 2 and isinstance(it[0], dict):
            pairs.append(it)
        elif isinstance(it, dict):
            pairs.append((it, False))
    return pairs


def apply_merge(raw, rows, src_repo_dir=None, target_repo_dir=None, src_remote_base=None,
                file_plan=None, file_decisions=None):
    """按每行 action 把合并计划写进配置文本（手术式改写，保留其余内容与注释）。
    rows: plan_merge 返回的 rows；GUI 可把每行的 action 从默认改成 add / overwrite / skip。
    src_repo_dir / target_repo_dir: 都给出时才搬运本地配套文件（源仓库 → 目标仓库）；
        任一为 None（如来源是粘贴文本 / URL）则不搬运（用户需手动处理文件）。
        src_remote_base: 来源是远程 URL 时，其配置所在目录，用于下载本地 spider 与 jar。

    **配套文件内容级冲突处理（2026-09-30 新增）**：目标存在**同名**配套文件时不再一律跳过——
      · 内容相同 → 跳过；· 内容不同 → 默认「重命名」（py/x.py → py/x_2.py）。
    关键：**必须先定稿改名映射并把条目 api/jar 改写为新名，再拼配置文本**，
    否则会出现「文件改了名、配置仍指向旧名」的致命不一致。
    file_plan: plan_companion_files_local/remote 的产出（GUI 先规划、弹窗确认后传入；缺省则内部规划）；
    file_decisions: {rel: "rename"|"overwrite"|"skip"}（缺省一律 rename）。
    返回 (新文本, stats, file_stats)。
    action：
      "add"       → 插入（conflict 行的 obj 已用 new_key 改名，避免撞 key）；
      "overwrite" → 用 obj 覆盖 matched_key 对应的现有条目；
      "skip"      → 不写。
    所有字段（含 ext/jar/adult 等）原样保留 —— 不再丢字段。"""
    text = raw
    added_objs, added_keys, overwritten = [], [], 0
    missing_overwrite = []
    ov_pairs = []              # [(key, obj)]
    row_final_key = []         # 与 rows 对齐：每行最终写入的 key（None = 不写）
    for row in rows:
        action = row.get("action", "skip")
        if action == "add":
            obj = _rebase_entry(dict(row["obj"]), src_repo_dir)
            if row.get("verdict") == "conflict":
                obj["key"] = row.get("new_key") or obj.get("key")
            added_objs.append(obj)
            added_keys.append(obj.get("key"))
            row_final_key.append(obj.get("key"))
        elif action == "overwrite":
            key = row.get("matched_key") or row["obj"].get("key")
            obj = _find_in_entries([(row["obj"], row["disabled"])], key)
            if obj is None:
                missing_overwrite.append(key)
                row_final_key.append(None)
                continue
            ov_pairs.append((key, _rebase_entry(obj, src_repo_dir)))
            row_final_key.append(key)
        else:
            row_final_key.append(None)
    if missing_overwrite:
        raise ValueError("勾选了覆盖但找不到对应条目：%s" % "、".join(missing_overwrite))

    # ---- 配套文件：先定稿改名映射（务必在拼文本之前），再改写条目 api/jar ----
    copy_objs = list(added_objs) + [obj for _k, obj in ov_pairs]
    plan = file_plan
    if plan is None and target_repo_dir and copy_objs:
        try:
            if src_repo_dir:
                plan = plan_companion_files_local(src_repo_dir, target_repo_dir, copy_objs)
            elif src_remote_base:
                plan = plan_companion_files_remote(src_remote_base, target_repo_dir, copy_objs)
        except Exception:
            plan = None
    rename_map = _resolve_rename_map_from_plan(plan, file_decisions)
    if rename_map:
        for obj in copy_objs:
            _apply_rename_to_entry(obj, rename_map)

    # ---- 文本手术 ----
    for key, obj in ov_pairs:
        try:
            text = replace_site(text, key, obj)
            overwritten += 1
        except Exception:
            continue
    if added_objs:
        text = insert_into_sites(text, added_objs)
    # 沿用来源禁用态（新增/覆盖后仍是禁用）。必须用「最终 key」——改名过的条目按新名禁用。
    disabled_keys = [fk for row, fk in zip(rows, row_final_key)
                     if row.get("disabled") and fk]
    for key in disabled_keys:
        try:
            text, _f = disable_site(text, key)
        except Exception:
            continue
    # 配套文件搬运（含内容级冲突改名）
    file_stats = {"copied": [], "skipped": [], "missing_src": [],
                  "renamed": [], "conflict_skipped": [], "backed_up": []}
    if target_repo_dir and plan is not None:
        if src_repo_dir:
            file_stats = copy_companions(src_repo_dir, target_repo_dir, copy_objs,
                                         plan=plan, decisions=file_decisions)
        elif src_remote_base:
            file_stats = copy_companions_remote(src_remote_base, target_repo_dir, copy_objs,
                                                plan=plan, decisions=file_decisions)
    # 来源是粘贴文本（两者皆 None）→ 不搬运，由用户手动处理配套文件
    disabled_set = set(disabled_keys)
    # 结果自检：配置仍可读回，且本次写入的条目、原有启用的条目一条都不能丢。
    # 注意用 parse_config_text 而非 parse_jsonc —— 含 /* [disabled] */ 的配置
    # 在「去注释」后本就会少几条，那是正常形态，不该被判为写入失败。
    try:
        base_active = {str(o.get("key", "")) for o, dis
                       in parse_sites_with_disabled(raw) if not dis}
    except Exception:
        base_active = set()
    want = [k for k in (added_keys + [r.get("matched_key") for r in rows
                                      if r.get("action") == "overwrite"]) if k]
    # ⚠️ 被禁用的条目（新增/覆盖后沿用来源禁用态）会被移入 /* [disabled] */ 注释块，
    # 不再出现在「活动」sites 数组里 —— 自检时必须把它们从「必须启用」集合里剔除，
    # 改为校验它们确实以禁用形态存在，否则会误报「写入后读不回这些条目」。
    _validate_sites_result(text, want, base_active - disabled_set, disabled_set)
    stats = {"added": len(added_objs), "overwritten": overwritten,
             "disabled": len(disabled_keys)}
    return text, stats, file_stats


def _validate_sites_result(text, want_keys=(), base_keys=(), disabled_keys=()):
    """写入后的自检。失败抛 ValueError（调用方据此中止，绝不落盘）。

    want_keys   : 本次新增/覆盖写入的 key（无论启用/禁用都应存在）；
    base_keys   : 原有启用、且本次未被禁用的 key —— 必须仍是「启用」态（不能丢、也不能被误并成禁用）；
    disabled_keys: 本次被禁用（移入注释块）的 key —— 只需以「禁用」形态存在即可，
                   不再要求出现在活动 sites 数组里（那是正常形态，不该判为写入失败）。"""
    try:
        data = parse_config_text(text)
    except Exception as ex:
        raise ValueError("写入结果不合法，已中止：%s" % ex)
    arr = data.get("sites") if isinstance(data, dict) else data
    got_active = {str(s.get("key", "")) for s in (arr or []) if isinstance(s, dict)}
    try:
        got_disabled = parse_disabled_keys(text)
    except Exception:
        got_disabled = set()
    disabled_set = set(disabled_keys)
    # 禁用项：必须作为禁用条目存在（在 /* [disabled] */ 注释块里）。
    # 这一步同时兜底「disable_site 静默失败」——若没真禁掉会在此被抓出。
    lost_dis = [k for k in disabled_keys if k and k not in got_disabled]
    # 启用项：必须出现在活动 sites 数组里（既不能丢，也不能被误改成禁用态）。
    must_active = [k for k in (set(want_keys) | set(base_keys))
                   if k and k not in disabled_set]
    lost_active = [k for k in must_active if k not in got_active]
    lost = lost_dis + lost_active
    if lost:
        # 例如覆盖写入时被删掉、或注释块改写丢了条目 —— 必须中止而不是静默丢数据
        raise ValueError("写入后读不回这些条目，已中止：%s" % "、".join(sorted(lost)))


# ----------------------------------------------------------------------------
# 通用数组合并（lives / parses 等，非 sites 数组）
# ----------------------------------------------------------------------------
def load_array_items(text, name, accept_strings=False):
    """从配置文本里读取 name 数组（lives/parses 等）的条目列表（仅用于判重检测，不写回）。
    用 parse_jsonc 解析（会剥离注释，对检测足够）；失败返回空列表。
    accept_strings=True 时同时保留字符串条目（用于 ads 等字符串数组区块）。"""
    try:
        data = parse_jsonc(text)
    except Exception:
        return []
    arr = data.get(name)
    if isinstance(arr, list):
        if accept_strings:
            return [x for x in arr if isinstance(x, (dict, str))]
        return [x for x in arr if isinstance(x, dict)]
    return []


def ads_fingerprint(item):
    """ads 区块条目指纹：字符串按内容去重；对象按 name（无 name 则按归一化 JSON）去重。
    用于合并导入时 ads 的并集去重。"""
    if isinstance(item, str):
        return ("s", item.strip())
    if isinstance(item, dict):
        name = str(item.get("name") or "").strip().lower()
        return ("d", name, json.dumps(item, ensure_ascii=False, sort_keys=True))
    return ("x", str(item))


def live_fingerprint(live):
    """直播源功能身份 = (名称, URL 集合)。URL 可能是字符串或列表，统一归一。"""
    name = str(live.get("name") or "").strip().lower()
    url = live.get("url")
    if isinstance(url, list):
        urls = tuple(str(u).strip() for u in url)
    else:
        urls = (str(url or "").strip(),)
    return (name, urls)


def parse_fingerprint(p):
    """parses 功能身份 = (名称, api)。"""
    return (str(p.get("name") or "").strip().lower(), str(p.get("api") or "").strip())


def plan_section_merge(existing_items, incoming_items, fingerprint_fn):
    """通用数组合并计划（lives/parses）。existing/incoming: list[dict]。
    返回 {"rows":[{obj, verdict, action, reason}], "summary":{new,dup}}。
    verdict: new(可导入) / dup(重复，默认跳过)。"""
    exist_fps = {fingerprint_fn(o) for o in existing_items}
    seen = set()
    rows, summary = [], {"new": 0, "dup": 0}
    for obj in incoming_items:
        fp = fingerprint_fn(obj)
        if fp in exist_fps or fp in seen:
            verdict, action, reason = "dup", "skip", "与现有/本次重复"
        else:
            verdict, action, reason = "new", "add", None
            seen.add(fp)
        summary[verdict] += 1
        rows.append({"obj": obj, "verdict": verdict, "action": action, "reason": reason})
    return {"rows": rows, "summary": summary}


def _find_array_close(text, name):
    """定位 `"name": [...]` 的 [ 与匹配 ]（字符串感知）。找不到返回 None。"""
    import re
    m = re.search(r'"%s"\s*:\s*\[' % re.escape(name), text)
    if not m:
        return None
    start = m.end() - 1
    depth, in_str, i, n = 0, False, start, len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return (start, i)
        i += 1
    return None


def fmt_section_entry(e):
    """把通用条目（lives/parses）格式化为带 8 空格缩进的 JSON 对象文本。"""
    inner = json.dumps(e, ensure_ascii=False, indent=4)
    return "        " + inner.replace("\n", "\n        ")


def _insert_into_array(text, name, entries, fmt):
    """把若干条目插入 name 数组（手术式，保留其余内容与注释）。数组不存在则新建。"""
    pos = _find_array_close(text, name)
    if pos is None:
        # 新建数组：插到顶层对象的最后一个 } 之前
        idx = text.rstrip().rfind("}")
        if idx == -1:
            return text
        block = ",\n".join(fmt(e) for e in entries)
        ins = ',\n    "%s": [\n%s\n    ]' % (name, block)
        return text[:idx] + ins + text[idx:]
    start, close = pos
    body = text[start + 1:close]
    block = ",\n".join(fmt(e) for e in entries)
    if not body.strip():
        return text[:start + 1] + "\n" + block + text[close:]
    head = body.rstrip()
    lead = "," if not head.endswith(",") else ""
    return text[:start + 1] + head + lead + "\n" + block + text[close:]


def apply_merge_section(text, name, rows, fmt):
    """按 plan_section_merge 的 action 把条目写入 text 的 name 数组。
    返回 (新文本, 新增条数)。"""
    to_add = [row["obj"] for row in rows if row.get("action") == "add"]
    if not to_add:
        return text, 0
    return _insert_into_array(text, name, to_add, fmt), len(to_add)



def export_config_text(raw, keep_keys):
    """导出「干净配置」：只保留 keep_keys 中的条目，其余剔除。
    被剔除的条目即使原本处于禁用注释态也一并移除（导出的是干净可用的一版）。
    返回 (新文本, 剔除条目数)。新文本已通过 JSON 合法性校验（否则原样返回原文）。"""
    keep = {str(k) for k in keep_keys}
    try:
        tokens = _parse_site_tokens(raw)
    except Exception:
        raise ValueError("当前配置无法解析出 sites 数组，无法导出")
    kept, removed = [], 0
    for t in tokens:
        if str(t["obj"].get("key", "")) in keep:
            kept.append(t)
        else:
            removed += 1
    try:
        start, close = find_sites_close(raw)
    except Exception:
        raise ValueError("当前配置找不到 sites 数组，无法导出")
    new_text = raw[:start] + _rebuild_sites_body(kept) + raw[close:]
    try:
        parse_config_text(new_text)
    except Exception as ex:
        raise ValueError("导出结果不合法（已中止）：%s" % ex)
    return new_text, removed


def _entry_is_adult(entry, adult_keys=None):
    """判断一条站点是否成人：条目自带 `adult` 字段（=1 / True / "1" / "yes"）**或**
    调用方传入的 key 集合（GUI 检测结果）命中，二者取并集。"""
    v = entry.get("adult")
    if isinstance(v, bool):
        hit = v
    else:
        try:
            hit = int(v) == 1
        except Exception:
            hit = str(v).strip().lower() in ("1", "true", "yes")
    if hit:
        return True
    if adult_keys is not None:
        return str(entry.get("key", "")) in adult_keys
    return False


def split_by_adult(raw, sites, adult_keys=None, base_keys=None):
    """按成人标记把配置「智能分流」成两套文本：
      · 纯净版：剔除所有成人站点（其余原样保留，含禁用注释态）；
      · 完整版：保留全部站点（等价于原配置，便于两份文件成对使用）。

    判定依据（按用户拍板）：**只按现有 `adult` 字段**（或调用方传入的检测结果
    `adult_keys`），不做任何实时内容检测，保证「快、准」。

    sites      : 当前配置解析出的站点列表（含 _disabled 状态亦可），用于取 key。
    adult_keys : 可选，显式指定「视为成人」的 key 集合（GUI 用检测结果传入）。
    base_keys  : 可选，参与分流的 key 白名单；缺省= sites 里全部 key。

    返回 dict：
        {pure_text, full_text, pure_kept, pure_removed, total, adult_count, adult_names}
    纯净版/完整版都已通过 JSON 合法性校验；任何异常原样抛出（调用方处理）。"""
    sites = [e for e in (sites or []) if isinstance(e, dict)]
    if base_keys is None:
        base_keys = [str(e.get("key", "")) for e in sites]
    else:
        base_keys = [str(k) for k in base_keys]

    adult_names = []
    pure_keep = []
    for e in sites:
        key = str(e.get("key", ""))
        if key not in set(base_keys):
            continue
        if _entry_is_adult(e, adult_keys):
            adult_names.append(str(e.get("name") or key))
        else:
            pure_keep.append(key)

    pure_text, pure_removed = export_config_text(raw, pure_keep)
    full_text, _none = export_config_text(raw, base_keys)
    return {"pure_text": pure_text, "full_text": full_text,
            "pure_kept": len(pure_keep), "pure_removed": pure_removed,
            "total": len(base_keys), "adult_count": len(adult_names),
            "adult_names": adult_names}


# ----------------------------------------------------------------------------
# CLI 模式（无界面，不依赖 Qt）
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# 源测活：模拟影视仓加载 py 源（homeContent 分类栏 → 首页影片），判定死源
# ----------------------------------------------------------------------------

PROBE_WORKER_FLAG = "--pyinj-probe-worker"   # frozen exe 内部子进程入口
PROBE_TIMEOUT_DEFAULT = 30                   # 单个源的硬超时（秒）
PROBE_MARKER = "@@PYINJ_PROBE@@"             # 子进程输出中 JSON 的定位标记
# 兜底 UA：影视仓/TVBox 用的是移动端 UA；urllib 默认 Python-urllib/3.x、
# requests 默认 python-requests/2.x 常被站点直接拒绝，会被误判成死源。
# 源自己显式设置的 UA 优先级更高，兜底不会覆盖它。
PROBE_UA = ("Mozilla/5.0 (Linux; Android 11; SM-G975F Build/RP1A.200720.012; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/103.0.5060.129 "
            "Mobile Safari/537.36")

_PROBE_WORKER_CODE = r'''
# -*- coding: utf-8 -*-
"""源测活 worker：在独立子进程里，按影视仓的方式加载一个 py 源。
用法: python <file> <py_path> <timeout>       （frozen: exe --pyinj-probe-worker <py_path> <timeout>）
输出: 标记行 + 单行 JSON。任何异常都转成 JSON，绝不以非零退出崩掉父进程。"""
import io, json, os, sys, time, socket, threading, urllib.request

UA = os.environ.get("PYINJ_PROBE_UA", "")
EXT_RAW = os.environ.get("PYINJ_PROBE_EXT", "")
PROXY_RAW = os.environ.get("PYINJ_PROBE_PROXY", "0")
MARKER = "@@PYINJ_PROBE@@"
# 网络兜底超时：大量源发请求时不带 timeout，一旦对端不响应就会无限卡住，
# 把整个测活预算耗光（表现为「明明分类栏都出来了却被判异常」）。
NET_SOCK_TIMEOUT = 12


def _emit(text):
    """向父进程输出：必须写 UTF-8 **字节**。
    冻结 exe 里 sys.stdout 的编码可能随系统 locale（如 cp936），
    直接 write(str) 会让父进程按 UTF-8 解码时中文变乱码。"""
    data = text.encode("utf-8", "replace")
    try:
        buf = getattr(sys.stdout, "buffer", None)
        if buf is not None:
            buf.write(data)
            buf.flush()
            return
    except Exception:
        pass
    try:
        os.write(1, data)
    except Exception:
        pass


def _install_net_defaults(budget=30):
    """网络默认行为：
    1) 默认**不走系统代理** —— 影视仓/TVBox 运行在电视/手机上，不读 Windows 的
       代理环境变量，走代理会与之行为不一致（且代理隧道常卡在 TLS 握手）。
    2) 给所有 socket 兜底超时 —— 源不带 timeout 时不会无限等待。"""
    global NET_SOCK_TIMEOUT
    try:
        NET_SOCK_TIMEOUT = max(5, min(12, int(budget) - 2))
    except Exception:
        pass
    if PROXY_RAW.strip() not in ("1", "true", "yes", "on"):
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                  "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(k, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        try:
            urllib.request.install_opener(urllib.request.build_opener(
                urllib.request.ProxyHandler({})))
        except Exception:
            pass
    try:
        socket.setdefaulttimeout(NET_SOCK_TIMEOUT)
    except Exception:
        pass


def _with_budget(fn, secs):
    """在子线程里跑 fn，最多等 secs 秒。
    socket 已有兜底超时，这里再兜一层：卡死时**放弃这一步**而不是放弃整个源
    （分类栏拿到了就该判活，不能被首页影片探测拖累）。"""
    box = {}

    def _w():
        try:
            box["v"] = fn()
        except Exception as ex:
            box["e"] = ex

    t = threading.Thread(target=_w, daemon=True)
    t.start()
    t.join(max(1, secs))
    if t.is_alive():
        return None, "timedout"
    if "e" in box:
        return None, box["e"]
    return box.get("v"), None


def _install_ua_defaults():
    """给「源自己没带 UA」的请求兜底；源自己设的 UA 优先，不会被覆盖。"""
    if not UA:
        return
    try:
        op = urllib.request.build_opener()
        op.addheaders = [("User-Agent", UA)]
        urllib.request.install_opener(op)
    except Exception:
        pass
    try:
        import requests
        _old = requests.sessions.Session.__init__

        def _init(self, *a, **kw):
            _old(self, *a, **kw)
            try:
                if "User-Agent" not in self.headers:
                    self.headers["User-Agent"] = UA
            except Exception:
                pass
        requests.sessions.Session.__init__ = _init
    except Exception:
        pass


def _stub_base():
    """部分源码 `from base.spider import Spider`（影视仓/饭太硬 py 运行时提供），
    且大量源会调基类的 self.fetch(...) / self.post(...)。
    这里给一个**能跑的最小实现**（走 requests，UA 兜底已全局生效），
    与影视仓 PyLoader 的行为对齐——否则会因缺基类方法误判成死源。"""
    try:
        import types
        base = types.ModuleType("base")
        spider = types.ModuleType("base.spider")

        class Spider(object):
            def fetch(self, url, params=None, headers=None, cookies=None,
                      timeout=10, verify=True, allowRedirects=True, **kw):
                import requests
                return requests.get(url, params=params, headers=headers or {},
                                    cookies=cookies, timeout=timeout,
                                    verify=verify, allow_redirects=allowRedirects, **kw)

            def post(self, url, params=None, headers=None, cookies=None,
                     data=None, json=None, timeout=10, verify=True,
                     allowRedirects=True, **kw):
                import requests
                return requests.post(url, params=params, headers=headers or {},
                                     cookies=cookies, data=data, json=json,
                                     timeout=timeout, verify=verify,
                                     allow_redirects=allowRedirects, **kw)

        spider.Spider = Spider
        base.spider = spider
        sys.modules.setdefault("base", base)
        sys.modules.setdefault("base.spider", spider)
    except Exception:
        pass


class _Mod(object):
    """函数式源（模块级 homeContent / categoryContent）。"""

    def __init__(self, ns):
        self._ns = ns

    def __getattr__(self, k):
        try:
            return self._ns[k]
        except KeyError:
            raise AttributeError(k)


def _ext_obj():
    """站点 ext 配置（影视仓会把它传给 init(extend)），例如 csp_ 类源的配置项。"""
    if not EXT_RAW:
        return ""
    try:
        return json.loads(EXT_RAW)
    except Exception:
        return EXT_RAW


def _load(py_path):
    ns = {"__name__": "pyinj_probe", "__file__": py_path}
    d = os.path.dirname(os.path.abspath(py_path))
    for p in (d, os.path.join(d, "lib"), os.path.join(d, "..", "lib"),
              os.path.join(d, "..", "py")):
        ap = os.path.abspath(p)
        if os.path.isdir(ap) and ap not in sys.path:
            sys.path.insert(0, ap)
    _stub_base()
    src = io.open(py_path, "r", encoding="utf-8", errors="replace").read()
    exec(compile(src, py_path, "exec"), ns)
    cls = ns.get("Spider")
    if isinstance(cls, type) and getattr(cls, "__module__", "") == "pyinj_probe":
        sp = cls()
        ext = _ext_obj()
        try:
            sp.init(ext)
        except Exception:
            try:
                sp.init("")
            except Exception:
                pass
        return sp, "class"
    return _Mod(ns), "module"


def _call(obj, name, *args):
    fn = getattr(obj, name, None)
    if not callable(fn):
        raise AttributeError("源没有实现 %s" % name)
    return fn(*args)


def _try_call(obj, name, argsets):
    """按参数组合依次尝试，返回第一个成功的；全失败则抛最有信息量的那个异常
    （签名不匹配的 TypeError 优先让位给源内部的真实异常）。"""
    best = None
    for a in argsets:
        try:
            return _call(obj, name, *a)
        except Exception as ex:
            if best is None or (isinstance(best, TypeError) and not isinstance(ex, TypeError)):
                best = ex
    raise best if best is not None else RuntimeError("无可用调用")


def _as_dict(v):
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("{") or s.startswith("["):
            return json.loads(s)
    return v


def _classes_of(data):
    """分类栏：影视仓红框那一排标签就是它渲染出来的。"""
    arr = data.get("class") or data.get("classes") or []
    if not isinstance(arr, list):
        return []
    out = []
    for c in arr:
        if isinstance(c, dict):
            nm = c.get("type_name") or c.get("typeName") or ""
            if nm:
                out.append(str(nm))
        elif isinstance(c, str) and c.strip():
            out.append(c.strip())
    return out


def _videos(obj, classes):
    """首页影片：影视仓主页走 homeVideoContent；拿不到再退到第一个分类的第一页。"""
    try:
        r = _as_dict(_try_call(obj, "homeVideoContent", [()]))
        if isinstance(r, dict):
            lst = r.get("list") or r.get("videos") or []
            if isinstance(lst, list) and lst:
                return lst, "homeVideoContent"
    except Exception:
        pass
    for c in classes:
        tid = c.get("type_id") or c.get("typeId")
        if tid in (None, ""):
            continue
        for a in ((tid, 1, True, {}), (tid, 1, False, {}),
                  (tid, 1, True, ""), (tid, 1)):
            try:
                r = _as_dict(_call(obj, "categoryContent", *a))
            except Exception:
                continue
            if isinstance(r, dict):
                lst = r.get("list") or r.get("videos") or []
                if isinstance(lst, list) and lst:
                    return lst, "categoryContent"
    return [], ""


def main():
    out = {"ok": False, "alive": False, "classes": [], "videos": 0,
           "titles": [], "via": "", "style": "", "error": "", "note": ""}
    try:
        args = sys.argv[1:]
        if args and args[0] == "--pyinj-probe-worker":
            args = args[1:]
        py_path = args[0] if args else ""
        try:
            budget = int(args[1]) if len(args) > 1 else 30
        except Exception:
            budget = 30
        if not py_path or not os.path.isfile(py_path):
            raise ValueError("未找到 .py 文件：%s" % py_path)
        _install_net_defaults(budget)
        _install_ua_defaults()
        # 预算分配：「加载 + 分类栏」共用一个主预算（它们一起决定死活），
        # 首页影片只占小头（锦上添花）。
        # 加载阶段绝不单独切短预算 —— 不少源在 import / init 里就要发请求
        # （曾因给加载只留 7s 把活源「电影人生」误杀成异常）。
        main_budget = max(12, int(budget * 0.80))
        vid_budget = max(3, int(budget * 0.20))

        # ---- 阶段 0：加载源（模块级代码 / init 也可能发请求）----
        t_mark = time.time()
        loaded, err = _with_budget(lambda: _load(py_path), main_budget)
        if err is not None:
            raise (TimeoutError("加载源超时 %ss" % main_budget) if err == "timedout" else err)
        obj, style = loaded
        out["style"] = style

        # ---- 阶段 1：分类栏（影视仓红框那一排；它出来才算活源）----
        # 用主预算的**剩余**时间，加载慢的源仍有足够时间取分类
        home_budget = max(5, int(main_budget - (time.time() - t_mark)))
        data, err = _with_budget(
            lambda: _as_dict(_try_call(obj, "homeContent", [(True,), (False,), ()])),
            home_budget)
        if err is not None:
            if err == "timedout":
                raise TimeoutError("homeContent 超时 %ss（源卡住/网络不通）" % home_budget)
            raise err
        if not isinstance(data, dict):
            raise ValueError("homeContent 未返回对象（%s）" % type(data).__name__)
        raw = [c for c in (data.get("class") or data.get("classes") or [])
               if isinstance(c, dict)]
        out["classes"] = _classes_of(data)[:80]
        # 判别口径：分类栏出得来（影视仓红框区有内容）才算活源
        out["alive"] = bool(out["classes"])
        out["ok"] = True

        # ---- 阶段 2：首页影片（仅作参考；超时/失败不影响上面的死活判定）----
        box, err = _with_budget(lambda: _videos(obj, raw), vid_budget)
        if err is not None:
            why = "超时" if err == "timedout" else ("%s: %s" % (type(err).__name__, err))
            out["note"] = "首页影片未取到（%s）——分类栏正常，不影响活源判定" % why[:120]
        else:
            lst, via = box or ([], "")
            out["videos"] = len(lst)
            out["via"] = via
            for v in lst[:12]:
                if isinstance(v, dict):
                    t = v.get("vod_name") or v.get("title") or v.get("name") or ""
                    if t:
                        out["titles"].append(str(t))
    except Exception as ex:
        out["error"] = "%s: %s" % (type(ex).__name__, ex)
    # windowed 模式下 sys.stdout 可能为 None：直接写 fd 1，保证父进程收得到
    _emit("\n" + MARKER + "\n" + json.dumps(out, ensure_ascii=False) + "\n")


main()
'''


def _ssl_noverify():
    """返回一个「不校验证书」的 SSL 上下文。

    部分 CMS 站证书过期/自签，校验失败会被 urllib 直接抛错、误判成死源。
    本工具只做只读探测、不提交敏感数据，故对证书宽松对待。"""
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    except Exception:
        return None


def _extract_classes(obj):
    """从直连 CMS 的 JSON 响应里抽取分类栏（与 _classes_of 口径一致，
    但额外覆盖 videoClass / types / ac=class 形态）。

    影视仓红框区那一排分类标签 = homeContent 返回的 class 列表；
    分类非空即活源。返回分类名列表。"""
    if not isinstance(obj, dict):
        return []
    out = []
    # 1) class / classes：列表，元素为 dict（type_name）或字符串
    for key in ("class", "classes"):
        arr = obj.get(key)
        if isinstance(arr, list):
            for c in arr:
                if isinstance(c, dict):
                    nm = c.get("type_name") or c.get("typeName") or ""
                    if nm:
                        out.append(str(nm))
                elif isinstance(c, str) and c.strip():
                    out.append(c.strip())
    # 2) videoClass：苹果CMS 常见，可能是 "动作$武侠$" / 逗号/竖线分隔 / 列表
    vc = obj.get("videoClass")
    if vc:
        if isinstance(vc, list):
            for c in vc:
                s = str(c).strip()
                if s:
                    out.append(s)
        elif isinstance(vc, str):
            for part in vc.replace("$", ",").replace("|", ",").split(","):
                part = part.strip()
                if part:
                    out.append(part)
    # 3) types：dict {id: name} 或 list
    ty = obj.get("types")
    if isinstance(ty, dict):
        for v in ty.values():
            s = str(v).strip()
            if s:
                out.append(s)
    elif isinstance(ty, list):
        for c in ty:
            if isinstance(c, dict):
                nm = c.get("type_name") or c.get("typeName") or ""
                if nm:
                    out.append(str(nm))
            elif isinstance(c, str) and c.strip():
                out.append(c.strip())
    # 4) list/videos 中若元素是分类项（含 type_name）也纳入（苹果CMS ac=class 形态）
    for key in ("list", "videos"):
        arr = obj.get(key)
        if isinstance(arr, list):
            for c in arr:
                if isinstance(c, dict):
                    nm = c.get("type_name") or c.get("typeName")
                    if nm:
                        out.append(str(nm))
    # 去重保序
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def probe_cms_source(api, timeout=PROBE_TIMEOUT_DEFAULT, ua=None, use_proxy=False):
    """直连 CMS（type:1）测活：HTTP 取分类列表判活。

    影视仓顶部那一排分类标签 = 源 homeContent（苹果CMS 即 `ac=list` /
    `ac=class`）返回的 class 列表；**分类非空 = 活源**，空分类 = 死源，
    报错/超时 = 异常，找不到可访问接口 = 无资源。

    与 probe_py_source 返回同口径 dict：{ok, alive, classes, videos,
    titles, via, style, error, note}，便于统一判定。"""
    res = {"ok": False, "alive": False, "classes": [], "videos": 0,
           "titles": [], "via": "", "style": "cms", "error": "", "note": ""}
    api = (api or "").strip()
    if not api.startswith("http"):
        res["error"] = "非 http(s) 接口，无法 HTTP 探测：%s" % api
        return res

    import urllib.request
    import urllib.error
    import json as _json
    headers = {"User-Agent": ua or PROBE_UA,
               "Accept": "application/json, */*",
               "Connection": "close"}
    # 代理策略同 _install_net_defaults：默认不走系统代理（影视仓/TVBox 跑在
    # 电视/手机上不读 Windows 代理，走代理 tunnel 常卡 TLS 握手被误判死源）。
    handlers = []
    if use_proxy:
        ph = {}
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            v = os.environ.get(k, "")
            if v:
                ph["http"] = ph["https"] = v
        if ph:
            handlers.append(urllib.request.ProxyHandler(ph))
    else:
        handlers.append(urllib.request.ProxyHandler({}))
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
    ssl_ctx = _ssl_noverify()
    if ssl_ctx is not None:
        try:
            handlers.append(urllib.request.HTTPSHandler(context=ssl_ctx))
        except Exception:
            pass
    try:
        opener = urllib.request.build_opener(*handlers)
    except Exception as ex:
        res["error"] = "构建 opener 失败：%s" % ex
        return res

    def _get(url):
        req = urllib.request.Request(url, headers=headers, method="GET")
        return opener.open(req, timeout=timeout)

    if "?" in api:
        candidates = [api, api + "&ac=list", api + "&ac=class"]
    else:
        candidates = [api, api + "?ac=list", api + "?ac=class"]

    last_err = ""
    for url in candidates:
        try:
            with _get(url) as resp:
                raw = resp.read()
            text = ""
            for enc in ("utf-8", "gbk", "gb18030"):
                try:
                    text = raw.decode(enc)
                    break
                except Exception:
                    continue
            if not text:
                text = raw.decode("utf-8", "replace")
            data = _json.loads(text)
            if not isinstance(data, dict):
                last_err = "响应不是 JSON 对象（%s）" % type(data).__name__
                continue
            classes = _extract_classes(data)
            lst = data.get("list") or data.get("videos") or []
            titles = []
            if isinstance(lst, list):
                for v in lst[:12]:
                    if isinstance(v, dict):
                        t = (v.get("vod_name") or v.get("title")
                             or v.get("name") or "")
                        if t:
                            titles.append(str(t))
            res["ok"] = True
            res["classes"] = classes[:80]
            res["alive"] = bool(classes)
            res["videos"] = len(lst) if isinstance(lst, list) else 0
            res["titles"] = titles
            res["via"] = url
            if classes:
                res["note"] = "取分类栏成功（%d 个分类）" % len(classes)
            else:
                res["note"] = ("接口可达但无分类栏（该站可能非标准 CMS，"
                               "或需其它参数）")
            return res
        except Exception as ex:
            last_err = "%s: %s" % (type(ex).__name__, ex)
            continue
    res["error"] = "全部候选接口均失败：%s" % last_err[:200]
    return res


def _probe_http_only(api, timeout=PROBE_TIMEOUT_DEFAULT, ua=None,
                     use_proxy=False, style="", note=""):
    """仅做 HTTP 可达性的测活兜底：XML(type:0) / 目录(type:4) / 无本地 .py
    的 spider 兜底。返回与 probe_py_source 同口径 dict。"""
    res = {"ok": False, "alive": False, "classes": [], "videos": 0,
           "titles": [], "via": "", "style": style, "error": "", "note": note}
    try:
        ok, method, _ = check_url_reachable(
            api, tcp_timeout=min(2.5, timeout),
            http_timeout=min(4.0, timeout))
    except Exception as ex:
        res["error"] = "%s: %s" % (type(ex).__name__, ex)
        return res
    res["ok"] = True
    res["alive"] = bool(ok)
    res["via"] = method
    if not ok:
        res["error"] = "HTTP 不可达"
    return res


def probe_source(entry, base_dir=None, timeout=PROBE_TIMEOUT_DEFAULT,
                 ext=None, ua=None, use_proxy=False):
    """按 type 路由的**全源测活**入口（替代直连 probe_py_source 的 .py 写死）：
      - type:1 直连 CMS      → probe_cms_source（HTTP 取分类判活）
      - type:3 Spider + 本地有 .py → probe_py_source（子进程隔离执行源）
      - type:3 无本地 .py + http → _probe_http_only（仅可达性兜底）
      - type:0 XML / 4 目录 / 其它 → _probe_http_only（仅 HTTP 可达性）
    返回 (res, is_py)：
      res：{ok, alive, classes, ...} 同 probe_py_source 口径
      is_py：本次是否走了 .py 子进程（决定 GUI 是否允许「同时删除 .py」）"""
    api = str(entry.get("api") or "")
    t = _norm_type(entry.get("type"))
    if t is None:
        t = infer_type(api)
    if t is None:
        t = 3

    if t == 1 and api.startswith("http"):
        return probe_cms_source(api, timeout=timeout, ua=ua,
                                use_proxy=use_proxy), False

    if t == 3:
        is_spider = (api.startswith("csp_")
                     or api.endswith((".py", ".js", ".jar", ".drpy")))
        if is_spider and base_dir:
            py_path = resolve_spider_path(base_dir, api)
            if py_path and os.path.isfile(py_path):
                return probe_py_source(py_path, timeout=timeout, ext=ext,
                                       ua=ua, use_proxy=use_proxy), True
        if is_spider and api.startswith("http"):
            return _probe_http_only(api, timeout=timeout, ua=ua,
                                    use_proxy=use_proxy, style="spider",
                                    note="未找到本地 .py，仅做 HTTP 可达性"), False
        res = {"ok": False, "alive": False, "classes": [], "videos": 0,
               "titles": [], "via": "", "style": "spider",
               "error": "未找到本地 .py 文件", "note": ""}
        return res, False

    # type:0 / 4 / 其它：HTTP 可达性兜底
    if api.startswith("http"):
        return _probe_http_only(
            api, timeout=timeout, ua=ua, use_proxy=use_proxy,
            style=("xml" if t == 0 else ("dir" if t == 4 else "other")),
            note="type:%s 仅做 HTTP 可达性判定" % t), False
    res = {"ok": False, "alive": False, "classes": [], "videos": 0,
           "titles": [], "via": "", "style": "",
           "error": "非 http 接口且非 spider，无法探测", "note": ""}
    return res, False


def source_verdict(r, typ=None):
    """全源统一判定：(级别, 文字)。级别：ok=活源 / bad=死源 / err=异常 /
    none=无资源(或 .py)。与 probe_verdict 口径一致，供 probe_source 结果使用。"""
    if not r:
        return ("none", "无资源")
    if not r.get("ok"):
        if "未找到" in str(r.get("error", "")):
            return ("none", "无本地资源")
        return ("err", "异常")
    return ("ok", "活源") if r.get("alive") else ("bad", "死源")


def probe_py_source(py_path, timeout=PROBE_TIMEOUT_DEFAULT, ext=None, ua=None,
                    use_proxy=False):
    """模拟影视仓加载 py 源：homeContent 取分类栏 → 首页影片，据此判定死源/活源。

    在**子进程**中执行（隔离 + 硬超时）：卡死、死循环、阻塞网络请求的源
    会被超时杀掉，不会拖住本工具本身。
    ext：该站点在配置里的 ext 字段（影视仓会传给源的 init），例如 csp_ 源的配置。
    use_proxy：是否跟随系统代理。默认 False —— 影视仓/TVBox 跑在电视/手机上，
      不读 Windows 代理环境变量；走代理常卡在 TLS 握手，会被误判成死源。
    返回 dict: {ok, alive, classes, videos, titles, via, style, error, note}
    """
    res = {"ok": False, "alive": False, "classes": [], "videos": 0,
           "titles": [], "via": "", "style": "", "error": "", "note": ""}
    if not py_path or not os.path.isfile(py_path):
        res["error"] = "未找到 .py 文件：%s" % (py_path or "")
        return res
    env = os.environ.copy()
    env["PYINJ_PROBE_UA"] = ua or PROBE_UA
    env["PYINJ_PROBE_PROXY"] = "1" if use_proxy else "0"
    if ext:
        try:
            env["PYINJ_PROBE_EXT"] = json.dumps(ext, ensure_ascii=False)
        except Exception:
            pass
    tmp = None
    try:
        if getattr(sys, "frozen", False):
            # 冻结 exe 里没有独立 python：让 exe 自己带 worker 标志再跑一次
            cmd = [sys.executable, PROBE_WORKER_FLAG,
                   os.path.abspath(py_path), str(int(timeout))]
        else:
            fd, tmp = tempfile.mkstemp(prefix="pyinj_probe_", suffix=".py")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_PROBE_WORKER_CODE)
            cmd = [sys.executable, tmp, os.path.abspath(py_path), str(int(timeout))]
        kw = {}
        if os.name == "nt":
            # GUI 下不弹黑框控制台
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           stdin=subprocess.DEVNULL, env=env,
                           cwd=os.path.dirname(os.path.abspath(py_path)),
                           timeout=max(5, int(timeout) + 10), **kw)
        text = (p.stdout or b"").decode("utf-8", "replace")
        if PROBE_MARKER in text:
            payload = text.rsplit(PROBE_MARKER, 1)[1].strip().splitlines()
            if payload:
                data = json.loads(payload[0])
                if isinstance(data, dict):
                    res.update({k: v for k, v in data.items() if k in res})
                    return res
        err = (p.stderr or b"").decode("utf-8", "replace").strip()
        res["error"] = "源进程无有效输出（退出码 %s）%s" % (
            p.returncode, ("：" + err.splitlines()[-1]) if err else "")
    except subprocess.TimeoutExpired:
        res["error"] = "超时 %s 秒未返回（源卡住/网络不通），判为死源" % timeout
    except Exception as ex:
        res["error"] = "%s: %s" % (type(ex).__name__, ex)
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass
    return res


def probe_worker_main():
    """frozen exe 内部入口：PyInjector.exe --pyinj-probe-worker <py_path> <timeout>
    injector.main() 在解析 CLI 参数前先拦下这个标志。"""
    g = {"__name__": "__pyinj_probe_worker__"}
    exec(compile(_PROBE_WORKER_CODE, "<pyinj_probe_worker>", "exec"), g)


def probe_verdict(r):
    """统一判定：(级别, 文字)。级别：ok=活源 / bad=死源 / err=异常 / none=无 .py"""
    if not r:
        return ("none", "无 .py")
    if not r.get("ok"):
        if "未找到" in str(r.get("error", "")):
            return ("none", "无 .py")
        return ("err", "异常")
    return ("ok", "活源") if r.get("alive") else ("bad", "死源")
