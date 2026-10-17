# -*- coding: utf-8 -*-
"""本地冒烟 v2026.10.13.b：detailContent 补全 + playerContent 全链路"""
import json
import sys

sys.path.insert(0, "C:/Users/PC2/Documents/iDATA/同步/py-PP/py")
import NeteaseMV as N

sp = N.Spider()
sp.init("")

# 1) 列表
cat = sp.categoryContent("rank", "1", True, {})
items = cat["list"]
print("== category pg1 items:", len(items))
print("   sample:", json.dumps(items[0], ensure_ascii=False)[:160])
MID = items[0]["vod_id"]

# 2) 详情（本次修复重点）
det = sp.detailContent([MID])
d = det["list"][0]
print("== detail vod_name:", d.get("vod_name"))
print("   vod_play_from:", d.get("vod_play_from"))
print("   vod_play_url:", d.get("vod_play_url"))
print("   vod_pic:", d.get("vod_pic", "")[:70])
print("   vod_remarks:", d.get("vod_remarks"))
print("   vod_content:", (d.get("vod_content") or "")[:70])
assert d.get("vod_play_from") == "网易云MV", "缺 vod_play_from"
assert d.get("vod_play_url", "").startswith("网易云MV$"), "play_url 前缀不匹配"
assert d.get("vod_name"), "缺 vod_name"

# 3) 播放
pc = sp.playerContent("网易云MV", MID, [])
print("== player parse=%s url=%s" % (pc.get("parse"), (pc.get("url") or "")[:80]))
print("   header:", pc.get("header"))
assert pc.get("url", "").startswith("http"), "播放直链为空"

# 4) 搜索链路
s = sp.searchContent("周杰伦", False, "1")
print("== search items:", len(s["list"]))
if s["list"]:
    smid = s["list"][0]["vod_id"]
    det2 = sp.detailContent([smid])
    pc2 = sp.playerContent("网易云MV", smid, [])
    print("   search detail from=%s url=%s play=%s" % (
        det2["list"][0].get("vod_play_from"),
        det2["list"][0].get("vod_play_url", "")[:30],
        (pc2.get("url") or "")[:60]))

print("\nALL PASS")
