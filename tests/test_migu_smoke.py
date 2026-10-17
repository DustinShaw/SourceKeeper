# -*- coding: utf-8 -*-
"""MiguMV 本地冒烟：模拟影视仓 homeContent→categoryContent→detailContent→playerContent→searchContent"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "MiguMV", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py", "MiguMV.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

sp = M.Spider()
sp.init("")

ok = True

def check(name, cond, extra=""):
    global ok
    print(("  PASS " if cond else "  FAIL ") + name + (" | " + extra if extra else ""))
    if not cond:
        ok = False

print("== homeContent ==")
h = sp.homeContent(True)
cls = h.get("class") or []
check("分类数=9", len(cls) == 9, "got %d" % len(cls))
check("分类字段完整", all(c.get("type_id") and c.get("type_name") for c in cls))
print("  class:", [c["type_name"] for c in cls])

print("== homeVideoContent ==")
check("不闪退(有list键)", isinstance(sp.homeVideoContent(), dict))

print("== categoryContent huayu-nan pg1 ==")
c = sp.categoryContent("huayu-nan", "1", True, {})
vods = c.get("list") or []
check("有MV条目", len(vods) > 0, "got %d" % len(vods))
check("page/pagecount/total", c.get("page") == 1 and c.get("total", 0) > 0 and c.get("pagecount", 0) > 0,
      "page=%s pagecount=%s total=%s" % (c.get("page"), c.get("pagecount"), c.get("total")))
for v in vods[:4]:
    print("   -", v["vod_id"], v["vod_name"], "|", v["vod_remarks"], "|", v["vod_pic"][:60])
check("vod_id非空", all(v.get("vod_id") for v in vods))
check("vod_pic为http", all(str(v.get("vod_pic", "")).startswith("http") for v in vods))

if vods:
    mv_id = vods[0]["vod_id"]
    print("== detailContent %s ==" % mv_id)
    d = sp.detailContent([mv_id])
    dl = d.get("list") or []
    check("详情非空", len(dl) == 1)
    if dl:
        v = dl[0]
        print("   -", v["vod_name"], "|", v["vod_remarks"], "|", v["vod_content"], "|", v["vod_pic"][:60])
        check("vod_play_from", v.get("vod_play_from") == "咪咕MV")
        check("play_url同前缀", str(v.get("vod_play_url", "")).startswith("咪咕MV$"))
        play = v.get("vod_play_url", "")[len("咪咕MV$"):]
        print("== playerContent ==")
        p = sp.playerContent("咪咕MV", play, [])
        pu = p.get("url") or ""
        print("   -", pu[:110])
        check("parse=0", p.get("parse") == 0)
        check("m3u8直链", ".m3u8" in pu, pu[:60])
        check("freevod域名", "freevod.nf.migu.cn" in pu)

print("== categoryContent pg2 (翻页不重复) ==")
c2 = sp.categoryContent("huayu-nan", "2", True, {})
v2 = c2.get("list") or []
ids1 = set(v["vod_id"] for v in vods)
ids2 = set(v["vod_id"] for v in v2)
check("pg2有条目", len(v2) > 0, "got %d" % len(v2))
check("pg1/pg2不重复", len(ids1 & ids2) == 0, "overlap=%d" % len(ids1 & ids2))

print("== searchContent 周杰伦 ==")
s = sp.searchContent("周杰伦", False, "1")
sl = s.get("list") or []
check("搜索有结果", len(sl) > 0, "got %d" % len(sl))
for v in sl[:4]:
    print("   -", v["vod_id"], v["vod_name"], "|", v["vod_remarks"])
check("搜索id非空", all(v.get("vod_id") for v in sl))

print()
print("RESULT:", "ALL PASS" if ok else "HAS FAIL")
sys.exit(0 if ok else 1)
