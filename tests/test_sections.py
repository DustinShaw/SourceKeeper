# -*- coding: utf-8 -*-
"""pyinj_sections 快速自检（纯逻辑，零 Qt，不碰真实文件）。
用临时文本验证 lives/parses 的增删改、拖拽排序落盘、注释保留。
"""
import sys
import pyinj_sections as S
from pyinj_core import parse_config_text

PASS = FAIL = 0


def _valid(text):
    """用容错解析器校验文本是不是合法 JSONC（去注释 + 清尾逗号）。"""
    try:
        parse_config_text(text)
        return True
    except Exception:
        return False


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


CFG = '''{
  "spider": "",
  //电视直播
  "lives": [
    {
      "name": "直播A",
      "type": 0,
      "url": "http://a/tv.m3u"
    },
    {
      "name": "直播B",
      "type": 0,
      "url": "http://b/tv.txt"
    }
  ],
  //解析
  "parses": [
    {"name": "解析A", "type": 0, "url": "https://jx.a/?url="}
  ],
  "sites": [
    {"key": "k1", "name": "站点A", "api": "./py/a.py", "type": 3},
    {"key": "k2", "name": "站点B", "api": "./py/b.py", "type": 3}
  ]
}
'''

print("== 1) 数组定位与条目解析 ==")
ok("has_array lives", S.has_array(CFG, "lives") is True)
ok("has_array parses", S.has_array(CFG, "parses") is True)
ok("has_array sites", S.has_array(CFG, "sites") is True)
ok("has_array 不存在的数组", S.has_array(CFG, "foo") is False)
lv = S.section_entries(CFG, "lives")
ok("lives 条目数 2", len(lv) == 2, lv)
ok("lives[0].name 直播A", lv[0].get("name") == "直播A", lv)

print("== 2) 增 ==")
t = S.add_section_entry(CFG, "lives", {"name": "直播C", "type": 0, "url": "http://c/tv.m3u"})
lv2 = S.section_entries(t, "lives")
ok("追加后 3 条", len(lv2) == 3, lv2)
ok("新条目在末尾", lv2[-1].get("name") == "直播C", lv2)
ok("追加后 JSON 合法", _valid(t), t[:200] if not _valid(t) else "")

print("== 3) 改（单字段 / 整体替换）==")
t2, found = S.set_section_field(CFG, "lives", lv[0], "url", "http://a/new.m3u")
ok("set 找到", found is True)
ok("url 已改", S.section_entries(t2, "lives")[0]["url"] == "http://a/new.m3u")
ok("name 未动", S.section_entries(t2, "lives")[0]["name"] == "直播A")
t3, f3 = S.update_section_entry(CFG, "parses", {"name": "解析A", "type": 0, "url": "https://jx.a/?url="},
                                {"name": "解析A改", "type": 1, "url": "https://jx.b/?url="})
ok("整体替换找到", f3 is True)
ok("替换后 name 生效", S.section_entries(t3, "parses")[0]["name"] == "解析A改")

print("== 4) 删 ==")
t4, removed = S.delete_section_entry(CFG, "lives", lv[0])
ok("删除返回被删条目", removed is not None and removed.get("name") == "直播A", removed)
ok("删除后剩 1 条", len(S.section_entries(t4, "lives")) == 1)
ok("删除后 JSON 合法", _valid(t4), t4[:200] if not _valid(t4) else "")
ok("parses 未受影响", len(S.section_entries(t4, "parses")) == 1)

print("== 5) 拖拽排序落盘 ==")
ents = S.section_entries(CFG, "sites")
ok("sites 原序 k1,k2", [e["key"] for e in ents] == ["k1", "k2"], ents)
t5 = S.move_section_entry(CFG, "sites", ents[0], +1)   # k1 下移
ok("k1 下移后 k2,k1", [e["key"] for e in S.section_entries(t5, "sites")] == ["k2", "k1"])
ok("排序后 JSON 合法", _valid(t5), t5[:200] if not _valid(t5) else "")
t6 = S.move_section_entry(CFG, "sites", ents[0], -1)   # k1 已是最上，越界不动
ok("上移越界保持不变", [e["key"] for e in S.section_entries(t6, "sites")] == ["k1", "k2"])

print("== 6) 注释保留 ==")
ok("排序后仍保留 //电视直播 注释", "//电视直播" in t5, "")
ok("lives/parses/sites 三者并存", all(S.has_array(t5, n) for n in ("lives", "parses", "sites")))

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
