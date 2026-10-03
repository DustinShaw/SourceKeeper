# -*- coding: utf-8 -*-
"""源管家 · 播放列表互转模块（pyinj_playlist）
================================================
处理 TVBox/影视仓配置里 `lives[].url` 指向的 **直播源列表**（通常是
`.txt` 或 `.m3u/.m3u8`）。这两格式在国内 IPTV 圈里被大量互相转换，本模块
以「新增模块」方式补上互转能力，便于用户把手上各种来源的频道表统一。

格式说明：
  · **TXT**（TVBox 通用「频道名,地址」）：
        频道名,#genre#
        频道名,http://xxx/playlist.m3u8
        频道名,http://xxx/live.m3u8
    其中 `xxx,#genre#` 是**分组标记**（TVBox 用它做分类）。
  · **M3U/M3U8**：
        #EXTM3U
        #EXTINF:-1 tvg-name="频道名" group-title="分组",频道名
        http://xxx/playlist.m3u8

对外接口：
  · parse_txt(text)        → [{"group","name","url"}, ...]
  · parse_m3u(text)        → 同上
  · to_txt(items)          → TXT 文本
  · to_m3u(items)          → M3U 文本
  · convert(text, to_fmt)  → 自动识别源格式并互转
  · is_m3u(text) / is_txt(text)
  · convert_file(src, dst=None, to_fmt=None) → 读文件转换并写盘（可选）

零 Qt 依赖、纯逻辑，可单测。
"""

import os
import re

GENRE_TAG = "#genre#"
DEFAULT_GROUP = "未分组"


# ----------------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------------
def is_m3u(text):
    """是否 M3U/M3U8（出现 #EXTM3U 或 #EXTINF）。"""
    t = (text or "").lstrip("\ufeff \t\r\n")
    return t.startswith("#EXTM3U") or "#EXTINF" in text


def is_txt(text):
    """是否 TVBox 风格 TXT（存在非注释的 `名称,地址` 行）。"""
    if is_m3u(text):
        return False
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if "," in line and re.search(r"https?://", line):
            return True
    return False


def _clean(name):
    return (name or "").strip().strip('"').strip()


def parse_txt(text):
    """解析 TVBox TXT 频道表 → [{"group","name","url"}, ...]。
    `名称,#genre#` 视为分组切换；`名称,url` 为频道。"""
    items = []
    cur_group = DEFAULT_GROUP
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        if line.startswith("#"):
            continue
        # `分组名,#genre#`
        if line.lower().endswith("," + GENRE_TAG.lower()) or line.endswith("," + GENRE_TAG):
            name = line.rsplit(",", 1)[0].strip()
            cur_group = _clean(name) or DEFAULT_GROUP
            continue
        if "," not in line:
            continue
        name, _, url = line.partition(",")
        name = _clean(name)
        url = url.strip()
        if not url:
            continue
        items.append({"group": cur_group, "name": name or url, "url": url})
    return items


_ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')


def parse_m3u(text):
    """解析 M3U/M3U8 → [{"group","name","url"}, ...]。
    取 #EXTINF 的 group-title / tvg-name，以及逗号后的显示名。"""
    items = []
    pending = None
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        if line.upper().startswith("#EXTINF"):
            attrs = dict(_ATTR_RE.findall(line))
            disp = line.rsplit(",", 1)[-1].strip() if "," in line else ""
            name = _clean(attrs.get("tvg-name") or disp)
            group = _clean(attrs.get("group-title") or "") or DEFAULT_GROUP
            pending = {"group": group, "name": name, "url": ""}
            continue
        if line.startswith("#"):
            continue
        # 真正的地址行
        url = line.strip()
        if pending is not None:
            pending["url"] = url
            if not pending["name"]:
                pending["name"] = url
            items.append(pending)
            pending = None
        else:
            items.append({"group": DEFAULT_GROUP, "name": url, "url": url})
    return items


# ----------------------------------------------------------------------------
# 生成
# ----------------------------------------------------------------------------
def to_txt(items):
    """[{"group","name","url"}] → TVBox TXT 文本（按 group 输出 #genre# 标记）。"""
    lines = []
    cur = None
    for it in items or []:
        g = _clean(it.get("group") or DEFAULT_GROUP) or DEFAULT_GROUP
        name = _clean(it.get("name") or "")
        url = (it.get("url") or "").strip()
        if not url:
            continue
        if g != cur:
            lines.append("%s,%s" % (g, GENRE_TAG))
            cur = g
        lines.append("%s,%s" % (name or url, url))
    return "\n".join(lines) + ("\n" if lines else "")


def to_m3u(items, extm3u=True):
    """[{"group","name","url"}] → M3U 文本。"""
    lines = []
    if extm3u:
        lines.append("#EXTM3U")
    for it in items or []:
        url = (it.get("url") or "").strip()
        if not url:
            continue
        name = _clean(it.get("name") or url)
        group = _clean(it.get("group") or DEFAULT_GROUP) or DEFAULT_GROUP
        lines.append('#EXTINF:-1 tvg-name="%s" group-title="%s",%s' % (name, group, name))
        lines.append(url)
    return "\n".join(lines) + ("\n" if lines else "")


# ----------------------------------------------------------------------------
# 互转
# ----------------------------------------------------------------------------
def parse_auto(text):
    """自动识别并解析为 items。"""
    if is_m3u(text):
        return parse_m3u(text), "m3u"
    return parse_txt(text), "txt"


def convert(text, to_fmt="m3u"):
    """自动识别源格式并转换到 to_fmt（'m3u' 或 'txt'）。
    返回 (新文本, 条目数, 源格式)。若源格式与目标相同也照样重新生成（可用于规范化）。"""
    items, src = parse_auto(text)
    if str(to_fmt).lower() in ("m3u", "m3u8"):
        return to_m3u(items), len(items), src
    return to_txt(items), len(items), src


def convert_file(src_path, dst_path=None, to_fmt=None):
    """读文件并转换写盘。to_fmt 为 None 时按 src 扩展名推断（.m3u→txt，.txt→m3u）。
    返回 {"src","dst","fmt","count","src_fmt"}。"""
    with open(src_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        text = f.read()
    src_fmt = "m3u" if is_m3u(text) else "txt"
    if to_fmt is None:
        to_fmt = "txt" if src_fmt == "m3u" else "m3u"
    new_text, count, _ = convert(text, to_fmt)
    if dst_path is None:
        root, _ext = os.path.splitext(src_path)
        dst_path = root + ("." + str(to_fmt).replace("m3u8", "m3u"))
    with open(dst_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
    return {"src": src_path, "dst": dst_path, "fmt": to_fmt,
            "count": count, "src_fmt": src_fmt}


if __name__ == "__main__":       # 手动试跑：python pyinj_playlist.py <file> [m3u|txt]
    import sys
    if len(sys.argv) > 1:
        fmt = sys.argv[2] if len(sys.argv) > 2 else None
        print(convert_file(sys.argv[1], to_fmt=fmt))
