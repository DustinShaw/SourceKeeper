# -*- coding: utf-8 -*-
"""KuwoMV.py 本地全链路冒烟：home/category/detail/player/search"""
import json
import sys

sys.path.insert(0, "C:/Users/PC2/Documents/iDATA/同步/py-PP/py")
import KuwoMV as K

sp = K.Spider()
sp.init("")

# 1. homeContent
home = sp.homeContent(True)
print("== home classes:", [(c["type_id"], c["type_name"]) for c in home["class"]])

# 2. categoryContent 首播 pg1
cat = sp.categoryContent("236682871", "1", True, {})
print("== 首播 pg1: n=%d pagecount=%s total=%s" % (
    len(cat["list"]), cat["pagecount"], cat["total"]))
if cat["list"]:
    print("   sample:", json.dumps(cat["list"][0], ensure_ascii=False))
    MID = cat["list"][0]["vod_id"]
else:
    MID = "156755380"

# 3. categoryContent 华语 pg2（翻页 + 另一分类）
cat2 = sp.categoryContent("236682731", "2", True, {})
print("== 华语 pg2: n=%d" % len(cat2["list"]))

# 4. detailContent
det = sp.detailContent([MID])
d = det["list"][0]
print("== detail:", json.dumps({k: d.get(k) for k in
      ("vod_id", "vod_name", "vod_play_from", "vod_play_url", "vod_pic",
       "vod_remarks", "vod_content")}, ensure_ascii=False))
assert d.get("vod_play_from") == "酷我MV", "缺 vod_play_from"
assert d.get("vod_play_url", "").startswith("酷我MV$"), "play_url 前缀错"
assert d.get("vod_name"), "缺 vod_name"

# 5. playerContent
pc = sp.playerContent("酷我MV", MID, [])
print("== player: parse=%s url=%s" % (pc.get("parse"), (pc.get("url") or "")[:90]))
print("   header:", pc.get("header"))
assert pc.get("url", "").startswith("http"), "播放直链为空"

# 6. searchContent
s = sp.searchContent("周杰伦", False, "1")
print("== search 周杰伦: n=%d" % len(s["list"]))
if s["list"]:
    print("   sample:", json.dumps(s["list"][0], ensure_ascii=False))
    smid = s["list"][0]["vod_id"]
    pc2 = sp.playerContent("酷我MV", smid, [])
    print("   search->play:", (pc2.get("url") or "")[:80])
    assert pc2.get("url"), "搜索结果播放直链为空"

# 7. 搜索 id 直接播放（Kugou 式：搜索项 vod_id 即 mid）
print("\nALL PASS")
