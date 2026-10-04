# -*- coding: utf-8 -*-
"""test_adult_detect.py —— 成人检测增强（A 词表统一 / C ext 素材 / B 深度拉取）单测。

覆盖：
  1. 新增关键词命中（黄色/巨乳/爆乳/换妻…）——「4黄色仓库站」回归
  2. 旧词不回归（成人/色情/无码 仍命中）
  3. 误报剔除：裸 "SM" 不再命中 asmr 音频站
  3b. 多语言：日语/韩语/俄语/泰语 命中 + 各语言阴性样本不误报 + 词库一致性
  4. 词库单一来源：pyinj_core._ADULT_* 与 pyinj_kw._FALLBACK adult 完全一致
  5. entry_extra_text：ext dict/list/str/None 归一
  6. detect_adult/detect_duanju/detect_live 的 extra_text 叠加
  7. entry_deep_url：http(s) api 返回 URL，本地路径返回 ''
  8. deep_fetch_text：非 URL 返回 ''；本地 HTTP 服务器内容可拉取并驱动全链路命中
  9. load_keywords 解析「日文 =/韩文 =/俄文 =/泰文 =」新语言行并叠加
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import pyinj_core as core  # noqa: E402
import pyinj_kw  # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print("  ok  %s" % msg)
    else:
        FAILS.append(msg)
        print("  FAIL %s" % msg)


print("== 1. 新增关键词命中（截图回归：4黄色仓库站）==")
is_ad, kw = core.detect_adult("", "4黄色仓库站合集")
check(is_ad and kw == "黄色", "站名含『黄色』→ 命中（kw=%r）" % kw)
for name, word in [("xxx黄片网", "黄片"), ("巨乳合集站", "巨乳"), ("爆乳天堂", "爆乳"),
                   ("换妻俱乐部", "换妻"), ("乱伦小说站", "乱伦"), ("偷拍偷窥网", "偷拍")]:
    is_ad, kw = core.detect_adult("", name)
    check(is_ad and kw == word, "站名含『%s』→ 命中" % word)

print("== 2. 旧词不回归 ==")
for name, word in [("成人频道", "成人"), ("色情站", "色情"), ("无码专区", "无码"),
                   ("麻豆传媒", "麻豆"), ("人妻系列", "人妻")]:
    is_ad, kw = core.detect_adult("", name)
    check(is_ad and kw == word, "站名含『%s』→ 仍命中" % word)

print("== 3. 误报剔除：裸 SM 不再命中 asmr ==")
is_ad, kw = core.detect_adult("", "uaa有声站", extra_text="asmr 激情骚麦 电台")
check(not is_ad, "asmr 音频站不误报为成人（kw=%r）" % kw)

print("== 3b. 多语言：日/韩/俄/泰 ==")
# --- 命中 ---
for label, name, word in [
    ("ja-假名", "エロ動画まとめ", "エロ"),
    ("ja-片假名小写", "えろげー攻略", "えろ"),
    ("ja-片假名长词", "無修正動画サイト", "無修正"),
    ("ja-成人服务", "風俗情報ステーション", "風俗"),
    ("ko-主干词", "야동 모음 사이트", "야동"),
    ("ko-年龄认证", "성인 인증 커뮤니티", "성인"),
    ("ru-主干词", "порно архив онлайн", "порно"),
    ("ru-词干", "секс видео", "секс"),
    ("th-主干词", "หนังโป๊ ออนไลน์", "หนังโป๊"),
    ("th-流出台", "คลิปหลุด ทางบ้าน", "คลิปหลุด"),
]:
    is_ad, kw = core.detect_adult("", name)
    check(is_ad and kw == word, "%s『%s』→ 命中 %r" % (label, name, kw))

# --- 阴性样本（各语言正常内容不得误报）---
for label, name in [
    ("ja-正常剧", "日本のドラマを探す"),
    ("ko-正常剧", "한국드라마 추천"),
    ("ru-正常词", "сериалы и фильмы онлайн"),  # сериал/фильм 均非词库词
    ("ru-интервью 不含 интим", "интервью со звездой"),
    ("th-正常剧", "หนังไทย ฟรี"),
    ("en-边界不误报", "my classics collection"),  # 子串含 ass？不；验证 en 边界逻辑仍在
]:
    is_ad, _kw = core.detect_adult("", name)
    check(not is_ad, "%s『%s』→ 不误报" % (label, name))

# en 整词边界回归：classification 不应命中 class？词库无 class，改用 sextube 类似逻辑：
# "sexuality" 含 "sex" 子串，但 en 是整词边界 → 只应命中 sexuality（若文本同时含独立 sex 则先 zh 后 en 顺序不受影响）
is_ad, kw = core.detect_adult("", "sexuality studies")
check(is_ad and kw == "sexuality", "en 边界：sexuality 命中为整词而非 sex 子串（kw=%r）" % kw)

# detect_categories 走同一词库 → 多语言同样命中
cats = pyinj_kw.detect_categories("", site_name="エロ動画まとめ")
check(cats.get("adult") == "エロ", "detect_categories 日语站名 → adult 命中")
cats2 = pyinj_kw.detect_categories("порно видео подборка", site_name="Ресурс")
check(cats2.get("adult") == "порно", "detect_categories 俄语文本 → adult 命中")

print("== 3c. 词库文件解析新语言行 ==")
import tempfile
tmpd = tempfile.mkdtemp(prefix="kwtest_")
with open(os.path.join(tmpd, pyinj_kw.KW_FILENAME), "w", encoding="utf-8") as f:
    f.write("[adult]\n中文 = 自定义中文词\n日文 = テスト用語\n韩文 = 커스텀단어\n"
            "俄文 = тестовоеслово\n泰文 = คำทดสอบ\n")
kws_f = pyinj_kw.load_keywords(data_dir=tmpd)
check("自定义中文词" in kws_f["adult"]["zh"], "文件「中文 =」行照常叠加")
check("テスト用語" in kws_f["adult"]["ja"], "文件「日文 =」行解析并入 ja 桶")
check("커스텀단어" in kws_f["adult"]["ko"], "文件「韩文 =」行解析并入 ko 桶")
check("тестовоеслово" in kws_f["adult"]["ru"], "文件「俄文 =」行解析并入 ru 桶")
check("คำทดสอบ" in kws_f["adult"]["th"], "文件「泰文 =」行解析并入 th 桶")
check("エロ" in kws_f["adult"]["ja"], "文件词与内置兜底 ja 词共存（叠加不覆盖）")
is_ad, kw = core.detect_adult("", "エロ動画まとめ")
check(is_ad, "detect_adult 走内置兜底 ja 词表（不依赖文件，架构如此）")
cats3 = pyinj_kw.detect_categories("番組紹介：含テスト用語的内容", site_name="資源站",
                                   keywords=kws_f)
check(cats3.get("adult") == "テスト用語",
      "文件追加的日语词驱动 detect_categories 命中（文件词影响智能分类）")

print("== 4. 词库单一来源 ==")
check(core._ADULT_ZH == pyinj_kw._FALLBACK["adult"]["zh"],
      "pyinj_core._ADULT_ZH 即 pyinj_kw 兜底 adult.zh")
check(core._ADULT_EN == pyinj_kw._FALLBACK["adult"]["en"],
      "pyinj_core._ADULT_EN 即 pyinj_kw 兜底 adult.en")
for _lang in ("ja", "ko", "ru", "th"):
    check(getattr(core, "_ADULT_" + _lang.upper()) == pyinj_kw._FALLBACK["adult"][_lang],
          "pyinj_core._ADULT_%s 即 pyinj_kw 兜底 adult.%s" % (_lang.upper(), _lang))
check([l for l, _w, _b in core._ADULT_ALL] == list(pyinj_kw._LANGS),
      "pyinj_core._ADULT_ALL 语言顺序与 pyinj_kw._LANGS 一致")
check(pyinj_kw._LANG_BOUNDARY == {"en"}, "仅英文使用整词边界（zh/ja/ko/ru/th 子串）")
check("SM" not in core._ADULT_ZH and "SM" not in pyinj_kw._FALLBACK["adult"]["zh"],
      "裸 SM 已从两处词库剔除")
kws = pyinj_kw.load_keywords()  # data/敏感词库.txt 在，兜底词条也必须保留
check("黄色" in kws["adult"]["zh"] and "巨乳" in kws["adult"]["zh"],
      "load_keywords() 合并结果含新词（文件词叠加兜底词）")

print("== 5. entry_extra_text 归一 ==")
check(core.entry_extra_text({"ext": {"a": "巨乳"}}) == '{"a": "巨乳"}'
      or "巨乳" in core.entry_extra_text({"ext": {"a": "巨乳"}}),
      "dict ext → JSON 文本")
check(core.entry_extra_text({"ext": ["熟女", "人妻"]}).count("熟女") == 1,
      "list ext → JSON 文本")
check(core.entry_extra_text({"ext": "raw text"}) == "raw text", "str ext 原样")
check(core.entry_extra_text({"ext": None}) == "", "None ext → 空串")
check(core.entry_extra_text({}) == "" and core.entry_extra_text(None) == "",
      "缺 ext / 空 entry → 空串")

print("== 6. detect_* 叠加 extra_text ==")
ext_text = core.entry_extra_text({"ext": {"分类": ["巨乳", "爆乳", "乱伦"]}})
is_ad, kw = core.detect_adult("", "干净站名", extra_text=ext_text)
check(is_ad, "干净站名 + ext 含成人分类 → 命中")
is_dj, dkw = core.detect_duanju("", "干净站名", extra_text="某某短剧APP")
check(is_dj and dkw == "短剧", "detect_duanju extra_text 生效")
is_lv, lkw = core.detect_live("", "干净站名", extra_text="体育直播列表")
check(is_lv and lkw == "直播", "detect_live extra_text 生效")
is_ad2, _ = core.detect_adult("", "干净站名")
check(not is_ad2, "不给 extra_text 时同样站名不命中（对照）")

print("== 7. entry_deep_url ==")
check(core.entry_deep_url({"api": "https://api.xxx.com/api.php/provide/vod/"})
      == "https://api.xxx.com/api.php/provide/vod/", "https api → 原样返回")
check(core.entry_deep_url({"api": "http://a.b/c"}) == "http://a.b/c", "http api → 返回")
check(core.entry_deep_url({"api": "./py/x.py"}) == "", "本地路径 → 空串")
check(core.entry_deep_url({"api": ""}) == "" and core.entry_deep_url({}) == "",
      "空 api → 空串")

print("== 8. deep_fetch_text ==")
check(core.deep_fetch_text("not-a-url") == "", "非 http URL → 空串")
check(core.deep_fetch_text("") == "", "空 URL → 空串")
check(core.deep_fetch_text("./py/x.py") == "", "相对路径 → 空串")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/adult":
            # 刻意用默认 ensure_ascii=True 模拟返回 \uXXXX 转义 JSON 的真实采集站
            body = json.dumps({
                "class": [
                    {"type_id": 1, "type_name": "巨乳熟女"},
                    {"type_id": 2, "type_name": "乱伦伦理"},
                ]}).encode("utf-8")
        elif self.path == "/clean":
            body = json.dumps({
                "class": [
                    {"type_id": 1, "type_name": "电影"},
                    {"type_id": 2, "type_name": "电视剧"},
                ]}, ensure_ascii=False).encode("utf-8")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 静音
        pass


_srv = HTTPServer(("127.0.0.1", 0), _Handler)
_port = _srv.server_address[1]
_t = threading.Thread(target=_srv.serve_forever, daemon=True)
_t.start()
try:
    txt = core.deep_fetch_text("http://127.0.0.1:%d/adult" % _port)
    check("巨乳熟女" in txt and "乱伦伦理" in txt, "本地服务器内容可拉取")

    site = {"key": "s1", "name": "资源站",
            "api": "http://127.0.0.1:%d/adult" % _port, "type": 1}
    extra = core.entry_extra_text(site)
    fetched = core.deep_fetch_text(core.entry_deep_url(site))
    is_ad, kw = core.detect_adult("", site["name"], extra_text=(extra + "\n" + fetched))
    check(is_ad and kw in ("巨乳", "熟女", "乱伦"),
          "全链路：站名干净 + API 分类含成人 → 深度检测命中（kw=%r）" % kw)

    site2 = {"key": "s2", "name": "资源站", "type": 1,
             "api": "http://127.0.0.1:%d/clean" % _port}
    fetched2 = core.deep_fetch_text(core.entry_deep_url(site2))
    is_ad2, _ = core.detect_adult("", site2["name"], extra_text=fetched2)
    check(not is_ad2, "全链路：正常分类 API → 不误报")

    check(core.deep_fetch_text("http://127.0.0.1:%d/404path" % _port) == "",
          "HTTP 404 → 空串（异常吞掉）")
    # 不可达端口（连不上的端口）→ 空串
    check(core.deep_fetch_text("http://127.0.0.1:1/nope", timeout=2) == "",
          "连接失败 → 空串")
finally:
    _srv.shutdown()

print()
if FAILS:
    print("FAILED: %d 项\n  - %s" % (len(FAILS), "\n  - ".join(FAILS)))
    sys.exit(1)
print("ALL PASS (%s)" % sys.argv[0])
