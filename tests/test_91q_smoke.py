# -*- coding: utf-8 -*-
"""91qMV 本地冒烟：模拟影视仓 homeContent→categoryContent→detailContent→playerContent→searchContent"""
import sys, os, json, time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "Q91MV", os.path.join(HERE, "..", "py", "91qMV.py"))
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
check("分类数=1", len(cls) == 1, "got %d" % len(cls))
print("  class:", [c["type_name"] for c in cls])

print("== homeVideoContent ==")
hv = sp.homeVideoContent()
hvl = hv.get("list") or []
check("首页推荐有条目", len(hvl) > 0, "got %d" % len(hvl))
for v in hvl[:3]:
    print("   -", v["vod_id"], v["vod_name"], "|", v["vod_remarks"])

print("== categoryContent featured pg1 ==")
c = sp.categoryContent("featured", "1", True, {})
vods = c.get("list") or []
check("有MV条目", len(vods) > 0, "got %d" % len(vods))
check("page/pagecount/total", c.get("page") == 1 and c.get("total", 0) > 0 and c.get("pagecount", 0) > 0,
      "page=%s pagecount=%s total=%s" % (c.get("page"), c.get("pagecount"), c.get("total")))
for v in vods[:4]:
    print("   -", v["vod_id"], v["vod_name"], "|", v["vod_remarks"], "|", v["vod_pic"][:60])
check("vod_id非空", all(v.get("vod_id") for v in vods))
check("vod_pic为http", all(str(v.get("vod_pic", "")).startswith("http") for v in vods))

print("== categoryContent pg2 (翻页不重复) ==")
c2 = sp.categoryContent("featured", "2", True, {})
v2 = c2.get("list") or []
ids1 = set(v["vod_id"] for v in vods)
ids2 = set(v["vod_id"] for v in v2)
check("pg2有条目", len(v2) > 0, "got %d" % len(v2))
check("pg1/pg2不重复", len(ids1 & ids2) == 0, "overlap=%d" % len(ids1 & ids2))

if vods:
    mv_id = vods[0]["vod_id"]
    print("== detailContent %s ==" % mv_id)
    d = sp.detailContent([mv_id])
    dl = d.get("list") or []
    check("详情非空", len(dl) == 1)
    if dl:
        v = dl[0]
        print("   -", v["vod_name"], "|", v["vod_remarks"])
        print("   - content:", (v.get("vod_content") or "")[:120].replace("\n", " / "))
        check("vod_play_from", v.get("vod_play_from") == "九天MV")
        check("play_url同前缀", str(v.get("vod_play_url", "")).startswith("九天MV$"))
        print("== playerContent ==")
        t0 = time.time()
        p = sp.playerContent("九天MV", mv_id, [])
        pu = p.get("url") or ""
        print("   - %.2fs %s" % (time.time() - t0, pu[:120]))
        check("parse=0", p.get("parse") == 0)
        check("m3u8直链", ".m3u8" in pu, pu[:60])
        check("dmhmusic域名", "dmhmusic.com" in pu)
        # 真实拉一次 m3u8 验证可达 + 内容形态
        if pu:
            try:
                req = urllib.request.Request(pu, headers={"User-Agent": M.UA})
                with urllib.request.urlopen(req, timeout=15) as r:
                    body = r.read(400).decode("utf-8", "ignore")
                    code = r.getcode()
                check("m3u8可达200", code == 200, "code=%s" % code)
                check("m3u8内容合法", "#EXTM3U" in body, body[:40].replace("\n", " "))
            except Exception as e:
                check("m3u8可达200", False, repr(e))
            # https 变体是否也可达（信息项）
            if pu.startswith("http://"):
                https_pu = "https://" + pu[len("http://"):]
                try:
                    req = urllib.request.Request(https_pu, headers={"User-Agent": M.UA})
                    with urllib.request.urlopen(req, timeout=10) as r:
                        r.read(64)
                    print("   INFO https variant also 200")
                except Exception as e:
                    print("   INFO https variant FAIL:", repr(e)[:80])

print("== 第二个MV详情链路复用 (V10000010429) ==")
d2 = sp.detailContent(["V10000010429"])
dl2 = d2.get("list") or []
check("第二条详情非空", len(dl2) == 1)
if dl2:
    print("   -", dl2[0]["vod_name"], "|", dl2[0]["vod_remarks"], "|", dl2[0].get("vod_play_url"))
p2 = sp.playerContent("九天MV", "V10000010429", [])
check("第二条可播放", bool(p2.get("url")), (p2.get("url") or "")[:80])

print("== searchContent 大张伟 (首次触发全量索引) ==")
t0 = time.time()
s = sp.searchContent("大张伟", False, "1")
build_s = time.time() - t0
sl = s.get("list") or []
print("   首次搜索(含建索引)耗时 %.2fs, 结果 %d 条" % (build_s, len(sl)))
check("搜索有结果", len(sl) > 0, "got %d" % len(sl))
for v in sl[:5]:
    print("   -", v["vod_id"], v["vod_name"], "|", v["vod_remarks"])
check("搜索id非空", all(v.get("vod_id") for v in sl))
check("播放量降序", all(int(str(v["vod_remarks"]).rsplit(" ", 1)[-1] or 0) >=
                    int(str(sl[i + 1]["vod_remarks"]).rsplit(" ", 1)[-1] or 0)
                    for i, v in enumerate(sl[:-1])))
# 抽查前 3 条的 artist 确含关键词
hit = 0
for v in sl[:3]:
    info = sp._video_info(v["vod_id"])
    if info and "大张伟" in M._artists_of(info):
        hit += 1
check("前3条artist含大张伟", hit >= 2, "hit=%d/3" % hit)

print("== searchContent Sunrise (英文歌名, 大小写不敏感) ==")
t1 = time.time()
s2 = sp.searchContent("sunrise", True, "1")
print("   二次搜索耗时 %.2fs (索引已缓存)" % (time.time() - t1))
sl2 = s2.get("list") or []
check("Sunrise有结果", len(sl2) > 0, "got %d" % len(sl2))
for v in sl2[:3]:
    print("   -", v["vod_id"], v["vod_name"], "|", v["vod_remarks"])
check("大小写不敏感", any(v["vod_name"].lower() == "sunrise" for v in sl2))

print("== searchContent 星野 (歌手名带空格) ==")
s2b = sp.searchContent("星野", False, "1")
sl2b = s2b.get("list") or []
check("星野有结果", len(sl2b) > 0, "got %d" % len(sl2b))
for v in sl2b[:3]:
    print("   -", v["vod_id"], v["vod_name"], "|", v["vod_remarks"])

print("== searchContent 空关键词 ==")
s3 = sp.searchContent("", False, "1")
check("空关键词不炸", isinstance(s3, dict) and s3.get("list") == [])

print()
print("RESULT:", "ALL PASS" if ok else "HAS FAIL")
sys.exit(0 if ok else 1)
