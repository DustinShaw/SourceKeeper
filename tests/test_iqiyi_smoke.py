# -*- coding: utf-8 -*-
"""QiYiMV 冒烟测试：home/cat/detail/player/搜索 + ts 分片可达"""
import json
import re
import sys
import time
import urllib.request

sys.path.insert(0, "py")
import QiYiMV as q  # noqa: E402

UA = q.UA
PASS = []
FAIL = []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print("  [PASS] %s %s" % (name, extra))
    else:
        FAIL.append(name)
        print("  [FAIL] %s %s" % (name, extra))


def http_get(url, timeout=25, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": "https://www.iqiyi.com/",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except Exception as e:
            last = e
            time.sleep(1.0)
    return None, str(last)


print("=== 1. homeContent / homeVideoContent ===")
sp = q.Spider()          # 模块内的类名统一是 Spider（文件名只作模块名）
sp.init()
hc = sp.homeContent(check=0) if False else sp.homeContent()
check("home.class", len(hc.get("class", [])) == len(q.CATS),
      "(%d cats)" % len(hc.get("class", [])))
hv = sp.homeVideoContent()
check("homeVideo.list", len(hv.get("list", [])) >= 10,
      "(%d items)" % len(hv.get("list", [])))

print("=== 2. categoryContent 翻页 ===")
c1 = sp.categoryContent("MV", 1, 0, {})
c2 = sp.categoryContent("MV", 2, 0, {})
ids1 = set(v["vod_id"] for v in c1.get("list", []))
ids2 = set(v["vod_id"] for v in c2.get("list", []))
check("cat.pg1", len(ids1) >= 15, "(%d)" % len(ids1))
check("cat.pg2", len(ids2) >= 10, "(%d)" % len(ids2))
check("cat.no-overlap", not (ids1 & ids2),
      "overlap=%d" % len(ids1 & ids2))

print("=== 3. detailContent ===")
vid = sorted(ids1)[0]
det = sp.detailContent([vid])
vod = det["list"][0]
check("detail.name", bool(vod.get("vod_name")))
check("detail.pic", bool(vod.get("vod_pic")))
check("detail.play_from", "爱奇艺" in vod.get("vod_play_from", ""))
lines = vod.get("vod_play_url", "").split("$$$")
check("detail.play_url", len(lines) == 3 and all("$http" in l for l in lines),
      "(%d lines)" % len(lines))

print("=== 4. playerContent + 本地 m3u8 ===")
pc = sp.playerContent("爱奇艺", lines[0].split("$")[1])
check("player.parse", pc.get("parse") == 0)
murl = pc.get("url", "")
st, body = http_get(murl)
mtext = body.decode("utf-8", "ignore") if isinstance(body, bytes) else ""
check("m3u8.http", st == 200, "(status=%s)" % st)
check("m3u8.header", mtext.startswith("#EXTM3U"), "(%s...)" % mtext[:16])
ts_urls = [l.strip() for l in mtext.split("\n")
           if l.strip().startswith("http")]
check("m3u8.segments", len(ts_urls) >= 5, "(%d ts)" % len(ts_urls))

print("=== 5. ts 分片可达（跟随 302） ===")
if ts_urls:
    tst, tsbody = http_get(ts_urls[0], timeout=30)
    ok = tst == 200 and isinstance(tsbody, bytes) and len(tsbody) > 1000
    check("ts.reachable", ok,
          "(status=%s size=%s)" % (tst, len(tsbody) if isinstance(tsbody, bytes) else tsbody))
    if isinstance(tsbody, bytes) and len(tsbody) >= 188:
        check("ts.magic", tsbody[0] == 0x47, "(first byte=0x%02x)" % tsbody[0])

print("=== 6. 第二条 MV 全链路复用 ===")
vid2 = sorted(ids2)[0]
det2 = sp.detailContent([vid2])
line2 = det2["list"][0]["vod_play_url"].split("$$$")[0].split("$")[1]
pc2 = sp.playerContent("爱奇艺", line2)
st2, body2 = http_get(pc2.get("url", ""))
m2 = body2.decode("utf-8", "ignore") if isinstance(body2, bytes) else ""
ts2 = [l.strip() for l in m2.split("\n") if l.strip().startswith("http")]
check("m3u8.second", st2 == 200 and len(ts2) >= 5,
      "(status=%s ts=%d)" % (st2, len(ts2)))

print("=== 7. searchContent ===")
sr = sp.searchContent("稻香 MV", False, 1)
check("search.list", len(sr.get("list", [])) >= 10,
      "(%d)" % len(sr.get("list", [])))
names = " ".join(v["vod_name"] for v in sr.get("list", []))
check("search.relevant", ("稻香" in names) or ("周杰伦" in names))

print("=== 8. 空关键词/异常 pg ===")
sr0 = sp.searchContent("", False, 1)
check("search.empty", isinstance(sr0.get("list", []), list))
c9 = sp.categoryContent("MV", 99, 0, {})
check("cat.deep-page", isinstance(c9.get("list", []), list))

print("")
print("=" * 50)
print("RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL PASS")
