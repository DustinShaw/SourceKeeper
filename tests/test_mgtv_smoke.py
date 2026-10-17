# -*- coding: utf-8 -*-
"""MgtvMV 冒烟测试：home/分类/详情/播放(m3u8+ts)/搜索"""
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, "py")
import MgtvMV as m  # noqa: E402

UA = m.UA
REF = m.REFERER
PASS = []
FAIL = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))


def http(url, timeout=25, tries=4):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": REF})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except Exception as e:
            last = e
            time.sleep(1.0)
    print("      http err:", str(last)[:80])
    return None, None


print("=== 1. homeContent ===")
sp = m.Spider()          # 模块内的类名统一是 Spider（文件名只作模块名）
sp.init()
hc = sp.homeContent()
cats = hc.get("class", [])
check("home.class", len(cats) >= 6, "(%d cats)" % len(cats))
check("home.class-mv", sum(1 for c in cats if "MV" in c["type_name"]) >= 4,
      "MV 类=%d" % sum(1 for c in cats if "MV" in c["type_name"]))
hv = sp.homeVideoContent()
check("homeVideo.list", len(hv.get("list", [])) >= 3,
      "(%d items)" % len(hv.get("list", [])))

print("=== 2. categoryContent（各分类 + 翻页）===")
filled = []
for c in cats[:6]:
    try:
        lst = sp.categoryContent(c["type_id"], 1, 0, {}).get("list", [])
    except Exception as e:
        lst = []
        print("      cat %s err %s" % (c["type_id"], str(e)[:40]))
    print("   %-10s %-14s n=%d" % (c["type_id"], c["type_name"], len(lst)))
    if lst:
        filled.append((c["type_id"], lst))
check("cat.multi-nonempty", len(filled) >= 3, "(%d/%d)" % (len(filled), 6))

big_tid = None
big_n = 0
for tid, lst in filled:
    if tid.startswith("c") and len(lst) > big_n:
        big_tid, big_n = tid, len(lst)
p2 = sp.categoryContent(big_tid, 2, 0, {}).get("list", []) if big_tid else []
ids1 = set(v["vod_id"] for v in (dict(filled).get(big_tid) or []))
ids2 = set(v["vod_id"] for v in p2)
print("   paging on %s: pg1=%d pg2=%d overlap=%d"
      % (big_tid, len(ids1), len(ids2), len(ids1 & ids2)))
check("cat.pg1", bool(ids1))
check("cat.no-overlap", not (ids1 & ids2))

print("=== 3. detailContent ===")
target, lst0 = filled[0]
tok = lst0[0]["vod_id"]
det = sp.detailContent([tok])
vod = det["list"][0]
print("   detail:", vod.get("vod_name"), "|", vod.get("vod_remarks"),
      "|", vod.get("vod_pic")[:50])
check("detail.name", bool(vod.get("vod_name")))
check("detail.pic", str(vod.get("vod_pic")).startswith("http"))
check("detail.remarks", bool(vod.get("vod_remarks")))
check("detail.content", bool(vod.get("vod_content")))
lines = vod["vod_play_url"].split("$$$")
check("detail.play_lines", len(lines) == 3 and all("$" in l for l in lines),
      "(%d lines)" % len(lines))

print("=== 4. playerContent（三档清晰度）===")
res = []
for line in lines:
    tag, pid = line.split("$", 1)
    pc = sp.playerContent("芒果", pid)
    url = pc.get("url") or ""
    hdr = pc.get("header") or {}
    ok = url.startswith("http") and "Referer" in hdr
    res.append((tag, url, ok))
    print("   %-6s parse=%s url=%s" % (tag, pc.get("parse"), url[:80]))
check("player.all3", all(r[2] for r in res), "%d/3" % sum(1 for r in res if r[2]))

print("=== 5. m3u8 / ts 真实可达（带 Referer）===")
st, body = http(res[0][1])
ok_m3u8 = st == 200 and body and body[:7] == b"#EXTM3U"
check("http.m3u8-200", ok_m3u8, "status=%s len=%s"
      % (st, len(body) if body else 0))
ts_url = ""
if ok_m3u8:
    text = body.decode("utf-8", "ignore")
    seq = [l.strip() for l in text.split("\n")
           if l.strip() and not l.startswith("#")]
    if seq:
        ts_url = urllib.parse.urljoin(res[0][1], seq[0])
    print("   first ts:", ts_url[:100])
st2, body2 = http(ts_url) if ts_url else (None, None)
ok_ts = st2 == 200 and body2 and body2[0] == 0x47
check("http.ts-200", bool(st2 == 200), "status=%s" % st2)
check("http.ts-magic", ok_ts, "first byte=%s"
      % (hex(body2[0]) if body2 else "-"))

print("=== 6. searchContent ===")
try:
    sr = sp.searchContent("周杰伦", False, "1")
    n = len(sr.get("list", []))
    check("search.dict", isinstance(sr, dict) and "list" in sr, "n=%d" % n)
except Exception as e:
    check("search.dict", False, str(e)[:60])

print("\n== SUMMARY ==  PASS=%d FAIL=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", ", ".join(FAIL))
else:
    print("ALL PASS")
