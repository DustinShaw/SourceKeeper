# -*- coding: utf-8 -*-
"""农民影视(1).py 回归测试 —— 离线夹具 + 真实 pyquery（不联网）。

背景（2026-10-20）：站点 vip.wwgz.cn:5200 改版后，旧脚本全面失效：
  ① 列表详情链接由 /vod-play-id-N.html 改为 /vod-detail-id-N.html；
  ② 播放解析链（player/*.js + r'http.*?url=' 混淆正则）整体废弃，
     真实直链改在播放页的 mac_url 变量里；
  ③ 「动漫」分类指向的 www.wwgz.cn（无端口）实测连不通；
  ④ mac_url 直链含中文路径，必须 URL 编码；
  ⑤ 详情页已无 .sDes 节点（主演取不到）；
  ⑥ 片名靠 doc('h1 a') 命中「第二个 h1」的巧合；
  ⑦ 线路 tab 选择器 tab_box('ul li') 会把剧集名也抓进 vod_play_from。

本测试用**离线 HTML 夹具**覆盖以上全部修复点，**零网络**、零 Qt。
用真实 pyquery 解析夹具 —— 这样选择器本身也真正被验证到（不是只测纯逻辑函数）。
"""
import os
import sys
import re
import types
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print("[%s] %-56s %s" % ("OK " if cond else "FAIL", name, extra))


# ---------------------------------------------------------------- 载入被测脚本
def load_spider():
    """载入 py/农民影视(1).py（桩掉 requests 与 base.spider，不触网）。"""
    req = types.ModuleType("requests")
    req.get = lambda *a, **k: None
    req.post = lambda *a, **k: None
    sys.modules["requests"] = req

    pkg = types.ModuleType("base")
    pkg.__path__ = []
    mod = types.ModuleType("base.spider")

    class BaseSpider(object):
        def fetch(self, url, headers=None, cookies=None, **kw):
            return None

        def post(self, url, data=None, headers=None, **kw):
            return None

    mod.Spider = BaseSpider
    sys.modules["base"] = pkg
    sys.modules["base.spider"] = mod

    path = os.path.join(ROOT, "py", "农民影视(1).py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("nm_spider", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_spider()
ok("脚本可载入", M is not None)
if M is None:
    print("\nNM TEST FAIL (0 通过, 1 失败)")
    sys.exit(1)

from pyquery import PyQuery as pq

# ---------------------------------------------------------------- 离线夹具
HOME_HTML = """
<html><body>
<div class="globalPicList">
<ul class="resize_list"><li><a href="/vod-detail-id-96319.html" title="伟大的长征">
  <div class="pic"><img data-echo="https://laudio-cdn.tencentmusic.com/a.jpg"></div>
  <span class="sBottom"><span>更新至21集<em>0.0</em></span></span>
  <span class="sTit">伟大的长征</span><span class="sDes">主演：于和伟 王劲松</span></a></li></ul>
<ul class="resize_list"><li><a href="/vod-detail-id-96049.html" title="美人余">
  <div class="pic"><img data-echo="https://laudio-cdn.tencentmusic.com/b.jpg"></div>
  <span class="sBottom"><span>28集全<em>0.0</em></span></span>
  <span class="sTit">美人余</span><span class="sDes">主演：王佳佳 李一桐</span></a></li></ul>
</div></body></html>
"""

DETAIL_HTML = """
<html><body>
<h1 class="type-title">国产剧</h1>
<h1 class="title"><a href="/vod-detail-id-96319.html" title="伟大的长征">伟大的长征</a></h1>
<section class="mod"><article class="detail-con">
<span>年代：<em>2026</em></span><span>人气：<em>0</em></span>
<p>简&nbsp;&nbsp;&nbsp;介：以中央红军长征为主线，全面反映了……</p>
</article></section>
<div id="leftTabBox" class="numlistBox">
  <div class="hd"><ul><li><a href="javascript:;">线路①</a></li><li><a href="javascript:;">线路②</a></li></ul></div>
  <div class="bd">
    <div id="monday" class="numList"><ul>
      <li class=""><a href="/vod-play-id-96319-src-1-num-21.html" target="_self">第21集</a></li>
      <li class=""><a href="/vod-play-id-96319-src-1-num-20.html" target="_self">第20集</a></li>
      <li class=""><a href="/vod-play-id-96319-src-1-num-1.html" target="_self">第01集</a></li>
    </ul></div>
    <div id="lzm3u8" class="numList"><ul>
      <li class=""><a href="/vod-play-id-96319-src-2-num-1.html" target="_self">第01集</a></li>
    </ul></div>
  </div>
</div>
</body></html>
"""

PLAY_HTML = """
<html><body><script>
var mac_flag='play',mac_link='/vod-play-id-96319-src-{src}-num-{num}.html',
mac_name='伟大的长征',mac_from='monday$$$lzm3u8',mac_server='no$$$no',mac_note='$$$',
mac_url='第01集$https://cdn.example.com/202510/伟大的长征/EP01.m3u8#第02集$https://cdn.example.com/202510/伟大的长征/EP02.m3u8#第03集$https://cdn.example.com/202510/伟大的长征/EP03.m3u8'
</script></body></html>
"""


class _Resp(object):
    """模拟 fetch/post 的返回对象。"""
    def __init__(self, text):
        self.text = text


def _install_fake_fetch(s, mapping):
    """让 fetch/post 按 URL 返回夹具内容。"""
    def fetch(url, headers=None, cookies=None, **kw):
        for frag, html in mapping.items():
            if frag in url:
                return _Resp(html)
        return _Resp("")

    def post(url, data=None, headers=None, **kw):
        for frag, html in mapping.items():
            if frag in url:
                return _Resp(html)
        return _Resp("")

    s.fetch = fetch
    s.post = post


s = M.Spider()
s.init("")

# ================================================================ 纯逻辑
print()
print("== A) 工具函数 ==")
ok("_abs 相对转绝对", s._abs("/vod-detail-id-1.html") == "https://vip.wwgz.cn:5200/vod-detail-id-1.html",
   s._abs("/vod-detail-id-1.html"))
ok("_abs 绝对地址原样", s._abs("https://x.com/a") == "https://x.com/a")
ok("_abs 空值安全", s._abs("") == "" and s._abs(None) == "")
ok("isVideoFormat 认 m3u8/mp4", s.isVideoFormat("a.m3u8") and s.isVideoFormat("a.mp4")
   and not s.isVideoFormat("a.html"))

print()
print("== B) URL 编码（中文直链必修）==")
enc = s._encode_url("https://cdn.example.com/202510/伟大的长征/EP01.m3u8")
ok("中文路径已百分号编码", "%E4%BC%9F" in enc, enc[:70])
ok("协议与分隔符未被编码", enc.startswith("https://cdn.example.com/202510/"), enc[:56])
ok("已编码的不重复编码", s._encode_url(enc).count("%E4") == enc.count("%E4"))

print()
print("== C) mac_url 解析（播放核心）==")
entries = s._parse_mac_url(PLAY_HTML)
ok("解析出 3 集", len(entries) == 3, len(entries))
ok("集名正确", entries[0][0] == "第01集", entries[0][0])
ok("直链已 URL 编码", "%E4%BC%9F" in entries[0][1], entries[0][1][:66])
ok("第2集也对", entries[1][0] == "第02集" and "EP02" in entries[1][1])
ok("无 mac_url 时返回空", s._parse_mac_url("<html></html>") == [])
ok("双引号形式也认", len(s._parse_mac_url('mac_url="第01集$https://a/b.m3u8"')) == 1)

print()
print("== D) 分页信息解析 ==")
pc, tot = s._page_info(pq("<html><body>共 20721 条</body></html>"), 1, 30)
ok("总条数能解析", tot == 20721, tot)
pc2, tot2 = s._page_info(pq("<html><body>没有分页信息</body></html>"), 3, 30)
ok("无分页信息时 pagecount=1", pc2 == 1, pc2)

# ================================================================ 带选择器
print()
print("== E) 首页：列表与详情链接格式 ==")
_install_fake_fetch(s, {"/": HOME_HTML})
h = s.homeContent(False)
ok("首页列出 2 条", len(h["list"]) == 2, len(h["list"]))
ok("详情链接是 /vod-detail-id-（改版后新格式）",
   all("/vod-detail-id-" in v["vod_id"] for v in h["list"]),
   h["list"][0]["vod_id"] if h["list"] else "-")
ok("旧格式 /vod-play-id- 不再出现在列表",
   not any("/vod-play-id-" in v["vod_id"] for v in h["list"]))
ok("片名取到", h["list"][0]["vod_name"] == "伟大的长征", h["list"][0]["vod_name"])
ok("图片取到 data-echo", "laudio-cdn" in (h["list"][0]["vod_pic"] or ""),
   h["list"][0]["vod_pic"][:50])
ok("分类表 6 项", len(h["class"]) == 6, [c["type_name"] for c in h["class"]])

print()
print("== F) 详情：线路 / 剧集 / 片名 / 年代 ==")
_install_fake_fetch(s, {"vod-detail-id-96319": DETAIL_HTML})
d = s.detailContent(["https://vip.wwgz.cn:5200/vod-detail-id-96319.html"])["list"][0]
ok("片名正确（显式取 .title，不靠 h1 巧合）", d["vod_name"] == "伟大的长征", d["vod_name"])
ok("年代解析为 2026", d["vod_year"] == "2026", d["vod_year"])
ok("简介非空", len(d["vod_content"]) > 10, d["vod_content"][:40])
lines = d["vod_play_from"].split("$$$")
urls = d["vod_play_url"].split("$$$")
ok("线路只有 2 条（不含剧集名）", lines == ["线路①", "线路②"], d["vod_play_from"])
ok("线路数与剧集组数一致", len(lines) == len(urls), (len(lines), len(urls)))
eps = urls[0].split("#")
ok("线路① 有 3 集", len(eps) == 3, len(eps))
ok("剧集已正序（第01集在前）", eps[0].split("$")[0] == "第01集", eps[0].split("$")[0])
ok("剧集链接为绝对地址", eps[0].split("$")[1].startswith("https://vip.wwgz.cn:5200/"),
   eps[0].split("$")[1][:60])

print()
print("== G) 播放：按集数取对应直链 ==")
_install_fake_fetch(s, {"vod-play-id-96319": PLAY_HTML})
p1 = s.playerContent("线路①", "https://vip.wwgz.cn:5200/vod-play-id-96319-src-1-num-1.html", {})
ok("parse=0（直链免解析）", p1.get("parse") == 0, p1.get("parse"))
ok("取到 EP01 直链", "EP01" in p1.get("url", ""), p1.get("url", "")[:66])
p3 = s.playerContent("线路①", "https://vip.wwgz.cn:5200/vod-play-id-96319-src-1-num-3.html", {})
ok("第3集取到 EP03 直链", "EP03" in p3.get("url", ""), p3.get("url", "")[:66])
p2 = s.playerContent("线路①", "https://vip.wwgz.cn:5200/vod-play-id-96319-src-1-num-2.html", {})
ok("第2集取到 EP02 直链", "EP02" in p2.get("url", ""), p2.get("url", "")[:66])

print()
print("== H) 分类：统一走主站 + 真实分页 ==")
_cat = HOME_HTML.replace("</body>", "<div class='page'><a href='/vod-list-id-1-pg-12.html'>12</a></div>共 20721 条</body>")
_install_fake_fetch(s, {"vod-list-id-1": _cat})
c = s.categoryContent("1", 1, False, {})
ok("分类有列表", len(c["list"]) == 2, len(c["list"]))
ok("pagecount 取自分页链接", c["pagecount"] == 12, c["pagecount"])
ok("total 取自「共 N 条」", c["total"] == 20721, c["total"])
ok("分类 URL 用主站带端口（不再是 www.wwgz.cn 无端口）",
   "vip.wwgz.cn:5200" in s.host and "www.wwgz.cn" not in s.host, s.host)

print()
print("== I) 搜索 ==")
_search = """<html><body><ul id="data_list">
<li><a href="/vod-detail-id-96319.html"><span class="sTit">伟大的长征</span>
<span class="sDes">主演：于和伟</span><span class="sDes">评分：8.0</span>
<img class="lazyload" data-src="https://laudio-cdn.tencentmusic.com/a.jpg"/></a></li>
</ul></body></html>"""
_install_fake_fetch(s, {"m=vod-search": _search})
r = s.searchContent("长征", False)
ok("搜索有结果", len(r["list"]) == 1, len(r["list"]))
ok("搜索结果链接是 /vod-detail-id-", "/vod-detail-id-" in r["list"][0]["vod_id"],
   r["list"][0]["vod_id"][:60])
ok("备注取评分（最后一个 sDes）", "评分" in r["list"][0]["vod_remarks"], r["list"][0]["vod_remarks"])

print()
print("NM TEST %s (%d 通过, %d 失败)" % ("OK" if FAIL == 0 else "FAIL", PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
