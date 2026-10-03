# -*- coding: utf-8 -*-
"""源管家 · 词库加载模块（pyinj_kw）
====================================
把原先**硬编码在 pyinj_core.py 里的关键词**抽取成「可编辑的本地文本文件」
（见 data/敏感词库.txt 与 data/需特殊上网域名库.txt），并对外提供统一的：

  · load_keywords()      → {分类: {zh:[...], en:[...]}}
  · detect_categories()  → 一条源命中的分类集合（成人/短剧/直播/音乐/音频/点播）
  · load_proxy_domains() → 需特殊上网域名列表
  · domain_needs_proxy() → 某域名是否命中该库

设计原则：
  - 零 Qt 依赖、纯逻辑、可单测；
  - 文件缺失 / 损坏时**回落到内置默认值**，绝不因词库问题让主程序崩；
  - 文件路径基于「exe 同目录」（绿色运行），另在内置 data/ 兜底。
"""

import os
import re
import sys

# --- 内置兜底词库（词库文件缺失时使用；内容与 data/敏感词库.txt 初次生成时一致）---
_FALLBACK = {
    "adult": {
        "zh": ("成人", "色情", "裸体", "裸聊", "裸照", "性爱", "做爱", "性交", "性奴",
               "淫乱", "淫荡", "三级片", "A片", "无码", "有码", "中出", "内射", "颜射",
               "麻豆", "18禁", "限制级", "援交", "约炮", "一夜情", "人妻", "少妇", "熟女",
               "波多野", "苍井空", "番号", "老司机", "色站", "女优", "偷情", "欲女"),
        "en": ("porn", "pornhub", "xvideos", "xnxx", "xhamster", "youporn", "redtube",
               "hentai", "javhd", "nsfw", "adult", "nude", "naked", "milf",
               "gangbang", "bukkake", "creampie", "fetish", "erotic", "sexvideo", "sextube"),
    },
    "duanju": {
        "zh": ("短剧", "微短剧", "短剧场"),
        "en": ("duanju", "short drama", "shortdrama"),
    },
    "live": {
        "zh": ("直播", "秀场", "直播间", "主播"),
        "en": ("livetv", "live tv", "iptv", "live stream", "live-stream", "streaming"),
    },
    "music": {
        "zh": ("音乐", "歌曲", "歌单", "专辑", "歌手", "音乐台", "无损音乐", "mv", "ktv",
               "音乐盒", "听歌", "唱歌", "点歌", "歌曲库", "音乐库", "音悦", "汽水音乐",
               "网易云", "QQ音乐", "酷狗", "酷我", "咪咕音乐", "音乐视频", "演唱",
               "音乐会", "歌单广场", "榜单"),
        "en": ("music", "song", "songs", "playlist", "album", "singer", "ktv", "mv",
               "mp3", "flac", "musicvideo", "music-video", "songlist", "vocaloid"),
    },
    "audio": {
        "zh": ("音频", "有声", "有声书", "听书", "广播剧", "播客", "电台", "相声",
               "评书", "戏曲", "睡眠", "助眠", "有声小说", "有声读物", "播讲", "朗读",
               "讲故事", "儿童故事", "曲艺", "广播", "音频播客", "语音", "网络电台",
               "录音", "音频节目"),
        "en": ("audio", "audiobook", "podcast", "radio", "asmr", "fm", "sound", "mp3",
               "audioplay", "spoken", "voice", "audio-book", "radio-station",
               "streaming-audio"),
    },
    "vod": {
        "zh": ("影视", "电影", "电视剧", "综艺", "动漫", "剧集", "点播"),
        "en": ("movie", "movies", "video", "vod", "tv", "anime", "drama"),
    },
}

_CAT_ORDER = ("adult", "duanju", "live", "music", "audio", "vod")
KW_FILENAME = "敏感词库.txt"
PROXY_FILENAME = "需特殊上网域名库.txt"


def get_data_dir():
    """词库目录：优先 exe/脚本同目录下的 data/，其次本文件同目录下的 data/。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(base, "data")
    return cand


def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()


def _split_words(s):
    return tuple(w.strip() for w in re.split(r"[,，、]", s) if w.strip())


def load_keywords(data_dir=None):
    """读取敏感词库文件，返回 {分类: {"zh": (...), "en": (...)}}。
    文件不存在/某分类缺失 → 用内置兜底补全（保证 6 个分类齐全）。"""
    d = data_dir or get_data_dir()
    result = {k: {"zh": tuple(v["zh"]), "en": tuple(v["en"])} for k, v in _FALLBACK.items()}
    path = os.path.join(d, KW_FILENAME)
    if not os.path.isfile(path):
        return result
    try:
        cur = None            # 当前分类（[xxx] 行）
        cur_lang = None       # 当前语言（`中文 =` / `英文 =`）
        for raw in _read_lines(path):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                cur = line[1:-1].strip().lower()
                if cur not in result:
                    result[cur] = {"zh": (), "en": ()}
                cur_lang = None
                continue
            if cur is None or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key.startswith("中文"):
                cur_lang = "zh"
            elif key.startswith("英文"):
                cur_lang = "en"
            else:
                continue
            words = list(result[cur].get(cur_lang, ()))
            for w in _split_words(val):
                if w not in words:
                    words.append(w)
            result[cur][cur_lang] = tuple(words)
    except Exception:
        return {k: {"zh": tuple(v["zh"]), "en": tuple(v["en"])} for k, v in _FALLBACK.items()}
    return result


def load_proxy_domains(data_dir=None):
    """读取「需特殊上网域名库」文件，返回小写域名元组（去重保序）。"""
    d = data_dir or get_data_dir()
    path = os.path.join(d, PROXY_FILENAME)
    if not os.path.isfile(path):
        return ()
    out = []
    try:
        for raw in _read_lines(path):
            line = raw.strip().lower()
            if not line or line.startswith("#"):
                continue
            if line.startswith("*."):
                line = line[2:]
            if line and line not in out:
                out.append(line)
    except Exception:
        return ()
    return tuple(out)


def _hit_zh(hay, words):
    for w in words:
        if w and w in hay:
            return w
    return None


def _hit_en(hay, words):
    for w in words:
        if not w:
            continue
        try:
            if re.search(r"\b" + re.escape(w) + r"\b", hay):
                return w
        except Exception:
            if w in hay:
                return w
    return None


def detect_categories(text, site_name="", keywords=None):
    """判断一段文本（.py 内容 + 站点名）命中的分类。
    返回 {分类: 命中词} 的 dict（未命中则不在其中）。"""
    kws = keywords if keywords is not None else load_keywords()
    hay = ("\n".join([site_name or "", text or ""])).lower()
    hits = {}
    for cat in _CAT_ORDER:
        words = kws.get(cat)
        if not words:
            continue
        w = _hit_zh(hay, words.get("zh", ()))
        if w is None:
            w = _hit_en(hay, words.get("en", ()))
        if w is not None:
            hits[cat] = w
    return hits


# 分类 → 界面友好标签
CAT_LABELS = {
    "adult": "成人",
    "duanju": "短剧",
    "live": "直播",
    "music": "音乐",
    "audio": "音频",
    "vod": "点播",
}


def domain_needs_proxy(domain, proxy_domains=None):
    """domain 是否命中「需特殊上网域名库」（子域名/后缀匹配）。"""
    doms = proxy_domains if proxy_domains is not None else load_proxy_domains()
    d = (domain or "").lower().strip().rstrip(".")
    if not d:
        return False
    for p in doms:
        if d == p or d.endswith("." + p):
            return True
    return False
