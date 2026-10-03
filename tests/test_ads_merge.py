# -*- coding: utf-8 -*-
"""ads 区块并集合并测试（合并导入功能扩展）
=========================================
覆盖 2026-10-01 为「合并导入」增加的 ads 并集去重：
  1) load_array_items(accept_strings) 能保留字符串条目（lives/parses 默认仍只认对象，向后兼容）；
  2) ads_fingerprint 对字符串按内容去重、且不与同名对象混淆；
  3) 并集去重主场景：目标 [a,b] + 源 [b,c,c] => [a,b,c]（唯一新增 c）；
  4) 目标无 ads 时，apply_merge_section 应能新建 ads 数组；
  5) 写回后文本仍合法、可被重新解析。
用法：envs/default/Scripts/python.exe test_ads_merge.py
"""
import io
import json
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, HERE)

PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  \u2713 %s" % name)
    else:
        FAIL += 1
        print("  \u2717 %s  %s" % (name, extra))


def valid(t):
    try:
        __import__("pyinj_core").parse_jsonc(t)
        return True
    except Exception:
        return False


import pyinj_core as C

print("\n== 1) load_array_items(accept_strings) 保留字符串条目 ==")
text = json.dumps({"sites": [], "ads": ["a.com", "b.com", {"name": "obj1"}]})
items = C.load_array_items(text, "ads", accept_strings=True)
ok("字符串与对象都保留", items == ["a.com", "b.com", {"name": "obj1"}], items)
items2 = C.load_array_items(text, "ads")
ok("默认仍只保留对象（向后兼容 lives/parses）", items2 == [{"name": "obj1"}], items2)

print("\n== 2) ads_fingerprint 去重语义 ==")
ok("相同字符串指纹一致", C.ads_fingerprint("a.com") == C.ads_fingerprint("a.com"))
ok("字符串与同名对象不混淆",
   C.ads_fingerprint("a.com") != C.ads_fingerprint({"name": "a.com"}))
ok("首尾空白不影响去重", C.ads_fingerprint(" a.com ") == C.ads_fingerprint("a.com"))

print("\n== 3) 并集去重：目标 [a,b] + 源 [b,c,c] => [a,b,c] ==")
target = json.dumps({"sites": [], "ads": ["a.com", "b.com"]})
source = json.dumps({"sites": [], "ads": ["b.com", "c.com", "c.com"]})
existing = C.load_array_items(target, "ads", accept_strings=True)
incoming = C.load_array_items(source, "ads", accept_strings=True)
plan = C.plan_section_merge(existing, incoming, C.ads_fingerprint)
rows = [dict(p, action=("add" if p["verdict"] == "new" else "skip")) for p in plan["rows"]]
new_text, added = C.apply_merge_section(target, "ads", rows, C.fmt_section_entry)
ok("唯一新增条数 = 1（c.com）", added == 1, added)
res_ads = C.load_array_items(new_text, "ads", accept_strings=True)
ok("结果含 a/b/c 且唯一（3 条）",
   set(res_ads) == {"a.com", "b.com", "c.com"} and len(res_ads) == 3, res_ads)
ok("写回后文本仍合法", valid(new_text))

print("\n== 4) 目标无 ads 时新建数组 ==")
target2 = json.dumps({"sites": []})
source2 = json.dumps({"sites": [], "ads": ["x.com"]})
existing2 = C.load_array_items(target2, "ads", accept_strings=True)
incoming2 = C.load_array_items(source2, "ads", accept_strings=True)
plan2 = C.plan_section_merge(existing2, incoming2, C.ads_fingerprint)
rows2 = [dict(p, action=("add" if p["verdict"] == "new" else "skip")) for p in plan2["rows"]]
new_text2, added2 = C.apply_merge_section(target2, "ads", rows2, C.fmt_section_entry)
ok("新增条数 = 1", added2 == 1, added2)
res2 = C.parse_jsonc(new_text2)
ok("新建 ads 数组含 x.com", res2.get("ads") == ["x.com"], res2.get("ads"))
ok("写回后文本仍合法", valid(new_text2))

print("\n== 5) 目标已有 ads 且源为空：不新增、不破坏 ==")
plan3 = C.plan_section_merge(
    C.load_array_items(target, "ads", accept_strings=True),
    C.load_array_items(json.dumps({"ads": []}), "ads", accept_strings=True),
    C.ads_fingerprint)
rows3 = [dict(p, action=("add" if p["verdict"] == "new" else "skip")) for p in plan3["rows"]]
new_text3, added3 = C.apply_merge_section(target, "ads", rows3, C.fmt_section_entry)
ok("源为空时新增 0 条", added3 == 0, added3)
ok("目标 ads 保持 [a,b]", C.load_array_items(new_text3, "ads", accept_strings=True) == ["a.com", "b.com"])

print("\n\u901a\u8fc7 %d / \u5931\u8d25 %d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
