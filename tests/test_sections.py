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

# ---------------------------------------------------------------------------
# 7-11：分区管理页（工具箱）依赖的新能力 —— 注释式禁用 / 通用身份 / 片段重建
# ---------------------------------------------------------------------------
CFG2 = '''{
  "lives": [
    {
      "name": "直播A",
      "type": 0,
      "url": "http://a/tv.m3u"
    },
    // 中间注释
    {
      "name": "直播B",
      "type": 0,
      "url": "http://b/tv.txt"
    }
  ],
  "rules": [
    {"host": "www.x.com", "rule": ["m3u8.php"]},
    {"host": "www.y.com", "rule": [".m3u8"]}
  ],
  "sites": [
    {"key": "k1", "name": "站点A", "api": "./py/a.py", "type": 3},
    {"key": "k2", "name": "站点B", "api": "./py/b.py", "type": 3}
  ]
}
'''

print("== 7) 片段扫描（active / disabled / extra）==")
pcs = S.scan_array_pieces(CFG2, "lives")
ok("lives 切成 3 个片段（2 条目 + 1 注释）", len(pcs) == 3, [p["kind"] for p in pcs])
ok("中间那条被识别为注释片段", pcs[1]["kind"] == "extra", pcs[1])

print("== 8) 注释式禁用 / 启用（数据不丢，可还原）==")
lv = S.section_entries(CFG2, "lives")
td, changed = S.set_section_enabled(CFG2, "lives", lv[0], False)
ok("禁用返回已变更", changed is True)
ok("禁用后写入 [disabled] 标记", "[disabled]" in td)
ok("禁用后仍是合法 JSONC", _valid(td), td[:200] if not _valid(td) else "")
ok("禁用后条目总数不变（注释式保留）",
   len(S.section_entries_with_disabled(td, "lives")) == 2)
ok("禁用后首条标记为 disabled",
   S.section_entries_with_disabled(td, "lives")[0][1] is True)
ok("数组内的 // 注释未被吞掉", "// 中间注释" in td)
ok("同一状态再次禁用 → 不产生变化", S.set_section_enabled(td, "lives", lv[0], False)[1] is False)

te, changed2 = S.set_section_enabled(td, "lives", lv[0], True)
ok("启用返回已变更", changed2 is True)
ok("启用后 [disabled] 消失（不会留成注释）", "[disabled]" not in te, te)
ok("启用后 active 恢复 2 条", len(S.section_entries(te, "lives")) == 2)
ok("启用后 JSONC 合法", _valid(te))

print("== 9) 通用身份：无 key/name/url 的分区（rules / ijk）==")
rules = S.section_entries(CFG2, "rules")
ok("rules 两条身份不同", S._entry_identity(rules[0]) != S._entry_identity(rules[1]),
   [S._entry_identity(r) for r in rules])
tr, rm = S.remove_section_entry(CFG2, "rules", rules[0])
ok("删除 rules[0] 命中正确（未误伤第二条）",
   rm is not None and rm.get("host") == "www.x.com", rm)
ok("rules 只剩 y", [r["host"] for r in S.section_entries(tr, "rules")] == ["www.y.com"])
ok("删除后 JSONC 合法", _valid(tr))

print("== 10) 删除被禁用的条目 / 整体替换 ==")
t1, _c = S.set_section_enabled(CFG2, "lives", lv[1], False)
t2, rm2 = S.remove_section_entry(t1, "lives", lv[1])
ok("能删掉「已禁用」的条目", rm2 is not None and rm2.get("name") == "直播B", rm2)
ok("删后剩 1 条", len(S.section_entries_with_disabled(t2, "lives")) == 1)
t3, f3 = S.replace_section_entry(CFG2, "lives", lv[0],
                                 {"name": "直播A改", "type": 0, "url": "http://a/new.m3u"})
ok("整体替换命中", f3 is True)
ok("替换后新名生效", S.section_entries(t3, "lives")[0]["name"] == "直播A改")
ok("替换后仍是合法 JSONC", _valid(t3))
ok("替换不影响 rules", len(S.section_entries(t3, "rules")) == 2)

print("== 11) 移动只换启用条目，禁用条目与注释留在原位 ==")
tm = S.move_section_entry(CFG2, "lives", lv[0], +1)
ok("下移后顺序 B,A", [e["name"] for e in S.section_entries(tm, "lives")] == ["直播B", "直播A"])
ok("移动后注释仍在", "// 中间注释" in tm)
ok("offset 越界原样返回", S.move_section_entry(CFG2, "lives", lv[0], -1) == CFG2)
td2, _c2 = S.set_section_enabled(CFG2, "lives", lv[1], False)
ok("禁用条目参与列表且保持原顺序",
   [o["name"] for o, _d in S.section_entries_with_disabled(td2, "lives")] == ["直播A", "直播B"])

print("== 12) 摘要（表格展示用）==")
ok("有 name 取 name", S.section_summary({"name": "X", "url": "u"})[0] == "X")
ok("无 name 取 host", S.section_summary({"host": "h", "rule": ["a"]})[0] == "h")
ok("摘要超长会截断", len(S.section_summary({"name": "n", "url": "u" * 500})[1]) <= 161)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
