# -*- coding: utf-8 -*-
"""源管家 · 词库加载模块（pyinj_kw）
====================================
把原先**硬编码在 pyinj_core.py 里的关键词**抽取成「可编辑的本地文本文件」
（见 data/敏感词库.txt 与 data/需特殊上网域名库.txt），并对外提供统一的：

  · load_keywords()      → {分类: {zh/en/ja/ko/ru/th: [...]}}
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
# 成人词表 = 全项目单一来源（pyinj_core.detect_adult 也从这里取），
# 2026-10-04 合并了 pyinj_core 旧 _ADULT_ZH/_ADULT_EN 与本表的全部词条并补充：
#   黄色/黄片/黄站/黄网/巨乳/爆乳/乱伦/换妻/偷拍/自慰/嫩模/楼凤（中文）
#   sex/xxx（英文）
# 注意：旧 pyinj_core 词表里的裸 "SM" 被剔除——中文是子串匹配，"SM" 会命中
# 音频站的 "aSMr" 造成误报（与上方「骚」剔除同理）。
_FALLBACK = {
    "adult": {
        "zh": ("成人", "色情", "裸体", "裸聊", "裸照", "性爱", "做爱", "性交", "性奴",
               "淫乱", "淫荡", "淫水", "三级片", "A片", "无码", "有码", "中出", "内射",
               "颜射", "麻豆", "18禁", "限制级", "援交", "约炮", "一夜情", "人妻",
               "少妇", "熟女", "制服诱惑", "凌辱", "迷奸", "肛交", "口交", "乳交",
               "足交", "群交", "轮奸", "波多野", "苍井空", "吉泽明步", "天海翼",
               "番号", "老司机", "色站", "AV女优", "女优", "援交妹", "偷情", "约啪",
               "欲女", "黄色", "黄片", "黄站", "黄网", "巨乳", "爆乳", "乱伦",
               "换妻", "偷拍", "自慰", "嫩模", "楼凤"),
        "en": ("porn", "pornhub", "xvideos", "xnxx", "xhamster", "youporn", "redtube",
               "hentai", "javhd", "nsfw", "adult", "nude", "naked", "milf",
               "gangbang", "bukkake", "creampie", "fetish", "erotic", "sexvideo",
               "sextube", "onlyfans", "camgirl", "sexuality", "sex", "xxx"),
        # 日语：AV 生态最庞大的外语源；假名词（エロ/セックス…）是简中词永远
        # 匹配不到的盲区；汉字词（巨乳/熟女/中出…）已由 zh 桶覆盖（子串匹配）。
        "ja": ("無修正", "エロ", "えろ", "セックス", "オナニー", "レイプ", "盗撮",
               "近親相姦", "風俗", "ソープ", "デリヘル", "AV女優", "中出し",
               "おっぱい", "アダルト", "裏動画", "セフレ", "乱交"),
        # 韩语：야동(成人短视频)/야설(成人小说) 是韩国站最高频标记词；
        # 성인(成人) 用于年龄认证横幅；刻意不收 몰카(也指整蛊节目) 노출(泛义暴露)。
        "ko": ("야동", "야설", "포르노", "성인", "음란", "야한"),
        # 俄语：用子串匹配（俄语词形变化丰富，整词边界会漏 поиск 式变形；
        # порно 是绝对主干词，误报风险极低）。
        "ru": ("порно", "секс", "интим", "эротика", "порнография"),
        # 泰语：หนังโป๊=成人片、คลิปหลุด=流出台（泰国站两大主干词）；
        # 泰文不按空格分词，必须用子串匹配。
        "th": ("หนังโป๊", "คลิปหลุด", "หนังx"),
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

# 语言桶及命中优先级：zh → en → ja → ko → ru → th。
# zh/ja/ko/th 用子串匹配（这四种文字不以空格分词，整词边界无意义）；
# en 用 \b 整词边界（防 "class" 命中 "classification" 之类的子串误报）；
# ru 用子串（俄语词形变化丰富，边界匹配会漏变性变格式，且主干词误报率极低）。
_LANGS = ("zh", "en", "ja", "ko", "ru", "th")
_LANG_BOUNDARY = {"en"}
# 词库文件里的语言行前缀（`日文 = xxx, yyy`）；未列出的语言行忽略。
_LANG_LINE_PREFIX = {
    "中文": "zh", "英文": "en", "日文": "ja", "日语": "ja",
    "韩文": "ko", "韓文": "ko", "한국어": "ko",
    "俄文": "ru", "俄语": "ru",
    "泰文": "th", "泰语": "th",
}
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
    """读取敏感词库文件，返回 {分类: {zh: (...), en: (...), ja/ko/ru/th: (...)}}。
    文件不存在/某分类缺失 → 用内置兜底补全（保证 6 个分类、全部语言桶齐全）；
    文件里出现「日文 =/韩文 =/俄文 =/泰文 =」等行时叠加进对应语言桶。"""
    d = data_dir or get_data_dir()
    result = {k: {lang: tuple(v.get(lang, ())) for lang in _LANGS}
              for k, v in _FALLBACK.items()}
    path = os.path.join(d, KW_FILENAME)
    if not os.path.isfile(path):
        return result
    try:
        cur = None            # 当前分类（[xxx] 行）
        cur_lang = None       # 当前语言（`中文 =` / `英文 =` / `日文 =` …）
        for raw in _read_lines(path):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                cur = line[1:-1].strip().lower()
                if cur not in result:
                    result[cur] = {lang: () for lang in _LANGS}
                cur_lang = None
                continue
            if cur is None or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            cur_lang = None
            for prefix, lang in _LANG_LINE_PREFIX.items():
                if key.startswith(prefix):
                    cur_lang = lang
                    break
            if cur_lang is None:
                continue
            words = list(result[cur].get(cur_lang, ()))
            for w in _split_words(val):
                if w not in words:
                    words.append(w)
            result[cur][cur_lang] = tuple(words)
    except Exception:
        return {k: {lang: tuple(v.get(lang, ())) for lang in _LANGS}
                for k, v in _FALLBACK.items()}
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


def _hit_words(hay, words, boundary=False):
    """按语言特性匹配：boundary=True 用 \\b 整词边界（英文），否则子串。"""
    for w in words:
        if not w:
            continue
        if w in hay:
            if not boundary:
                return w
            # 边界语言还需确认前后都是词边界，防子串误报
            try:
                if re.search(r"\b" + re.escape(w) + r"\b", hay):
                    return w
            except Exception:
                return w
    return None


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
    """判断一段文本（.py 内容 + 站点名 + ext/API 补充文本）命中的分类。
    返回 {分类: 命中词} 的 dict（未命中则不在其中）。
    每个分类按 zh → en → ja → ko → ru → th 的语言优先级全桶匹配。"""
    kws = keywords if keywords is not None else load_keywords()
    hay = ("\n".join([site_name or "", text or ""])).lower()
    hits = {}
    for cat in _CAT_ORDER:
        words = kws.get(cat)
        if not words:
            continue
        w = None
        for lang in _LANGS:
            w = _hit_words(hay, words.get(lang, ()), boundary=lang in _LANG_BOUNDARY)
            if w is not None:
                break
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
