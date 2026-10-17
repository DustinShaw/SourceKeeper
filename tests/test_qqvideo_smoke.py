# -*- coding: utf-8 -*-
"""QqVideoMV 冒烟测试：搜索/分类/详情/播放(MP4 Range)"""
import sys
import time
import urllib.request

sys.path.insert(0, "py")
import QqVideoMV as q  # noqa: E402

UA = q.UA
REF = q.REFERER
PASS = []
FAIL = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))


def http(url, timeout=25, tries=4, rng=True):
    last = None
    for _ in range(tries):
        try:
            h = {"User-Agent": UA, "Referer": REF}
            if rng:
                h["Range"] = "bytes=0-4095"
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except Exception as e:
            last = e
            time.sleep(1.2)
    print("      err:", str(last)[:80])
    return None, None


print("=== 1. homeContent / homeVideoContent ===")
sp = q.Spider()          # 模块内的类名统一是 Spider（文件名只作模块名）
sp.init()
hc = sp.homeContent()
check("home.class", len(hc.get("class", [])) == len(q.CATS),
      "(%d)" % len(hc.get("class", [])))
hv = sp.homeVideoContent()
check("homeVideo.list", len(hv.get("list", [])) >= 10,
      "(%d)" % len(hv.get("list", [])))

print("=== 2. categoryContent 翻页 ===")
c1 = sp.categoryContent("MV", 1, 0, {})
c2 = sp.categoryContent("MV", 2, 0, {})
i1 = set(v["vod_id"] for v in c1.get("list", []))
i2 = set(v["vod_id"] for v in c2.get("list", []))
check("cat.pg1", len(i1) >= 15, "(%d)" % len(i1))
check("cat.pg2", bool(i2), "(%d)" % len(i2))
check("cat.no-overlap", not (i1 & i2), "overlap=%d" % len(i1 & i2))

print("=== 3. detailContent ===")
vid = c1["list"][0]["vod_id"]
vod = sp.detailContent([vid])["list"][0]
print("   ", vod.get("vod_name"), "|", vod.get("vod_remarks"),
      "|", vod.get("vod_pic")[:45])
check("detail.name", bool(vod.get("vod_name")))
check("detail.pic", str(vod.get("vod_pic")).startswith("http"))
check("detail.remarks", bool(vod.get("vod_remarks")))
lines = vod["vod_play_url"].split("$$$")
check("detail.play_lines", len(lines) == 2 and all("$" in l for l in lines),
      "(%d)" % len(lines))

print("=== 4. playerContent（两档）===")
res = []
for line in lines:
    tag, pid = line.split("$", 1)
    pc = sp.playerContent("腾讯", pid)
    res.append((tag, pc.get("url") or "", pc.get("header") or {}))
    print("   %-4s url=%s" % (tag, res[-1][1][:80]))
check("player.urls", all(r[1].startswith("http") for r in res))
check("player.header", all("Referer" in r[2] for r in res),
      "%d/2" % sum(1 for r in res if "Referer" in r[2]))

print("=== 5. 真实拉流（Range 206）===")
st, body = http(res[0][1])
ok = (st in (200, 206)) and body and b"ftyp" in body[:32]
check("http.mp4-range", bool(st in (200, 206)), "status=%s len=%s"
      % (st, len(body) if body else 0))
check("http.mp4-ftyp", ok, "head=%s" % (body[:12].hex() if body else "-"))

print("=== 6. 搜索 ===")
try:
    sr = sp.searchContent("周杰伦MV", False, "1")
    check("search.list", len(sr.get("list", [])) >= 5,
          "(%d)" % len(sr.get("list", [])))
except Exception as e:
    check("search.list", False, str(e)[:60])

print("\n== SUMMARY ==  PASS=%d FAIL=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", ", ".join(FAIL))
else:
    print("ALL PASS")
