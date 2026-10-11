# -*- coding: utf-8 -*-
"""「按当前排序写回配置」纯逻辑测试（pyinj_sections.reorder_by_keys）。

要点（GUI 只负责把「当前显示顺序」传进来，全部重排在纯逻辑层完成）：
  1) 目标顺序生效，条目数 / 其它顶层键 / 尾逗号都不受影响；
  2) **槽位填充**：只有本次传入的条目参与重排，其余条目（被过滤隐藏的）原位不动；
  3) 数组内 `//` 注释跟随其后紧邻的条目一起移动，内容不被改写；
  4) `/* [disabled] */` 注释式禁用块原样保留（仍禁用、随时可启用），且不会产生悬空逗号；
  5) 顺序没变 / 空清单 / 未知 key / 数组不存在 → 原样返回 (text, 0)；
  6) 重排结果始终是合法 JSONC，且能被 disable/enable 等既有能力继续处理（往返一致）。

本文件为纯逻辑测试（不含任何 Qt 绑定字样），两条构建链都会跑。
"""
import os
import sys
import io
import json
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import injector as I
import pyinj_sections as S

PASS = FAIL = 0


def ok(cond, name, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


def keys_of(text):
    """解析出的 active 站点 key 顺序（注释掉的条目不在其中）。"""
    return [str(s.get("key", "")) for s in I.parse_jsonc(text)["sites"]]


def all_keys(text):
    """数组内全部条目（含 /* [disabled] */ 注释禁用的）的 key 顺序。"""
    return [str(o.get("key", "")) for o, _dis in I.parse_sites_with_disabled(text)]


RAW = """{
  // 顶层注释
  "spider": "",
  "sites": [
    // 甲组：影视
    {"key":"a","name":"AAA","api":"./py/a.py","type":3},
    {"key":"b","name":"BBB","api":"./py/b.py","type":3},
    /* [disabled]
    {"key":"c","name":"CCC","api":"./py/c.py","type":3}
    */
    {"key":"d","name":"DDD","api":"http://x/d","type":1},
    // 末尾随手记
    {"key":"e","name":"EEE","api":"./py/e.py","type":3}
  ],
  "lives": [
    {"name":"CCTV","url":"http://l/1"}
  ],
  "ads": []
}
"""

print("== 1) 基本重排（全量） ==")
out, moved = S.reorder_by_keys(RAW, "sites", ["e", "d", "c", "b", "a"])
ok(all_keys(out) == ["e", "d", "c", "b", "a"], "目标顺序生效（含禁用条目）",
   str(all_keys(out)))
ok(keys_of(out) == ["e", "d", "b", "a"], "active 顺序同步正确", str(keys_of(out)))
ok(moved == 4, "上报位置变化条数（反转 5 条时正中间那条槽位不变，故 4 条）",
   "moved=%s" % moved)
d0, d1 = I.parse_jsonc(RAW), I.parse_jsonc(out)
ok(len(d0["sites"]) == len(d1["sites"]), "条目数不变",
   "%s -> %s" % (len(d0["sites"]), len(d1["sites"])))
ok(sorted(d0.keys()) == sorted(d1.keys()), "其它顶层键保持不变")
ok(d1["lives"] == d0["lives"] and d1["ads"] == d0["ads"], "lives/ads 等数组内容不变")
ok(d1["spider"] == d0["spider"], "非数组字段不变")
ok("// 顶层注释" in out, "数组外的顶层注释保留")

print("\n== 2) 注释跟随条目 + 禁用块原样保留 ==")
ok(out.index("// 甲组：影视") < out.index('"key":"a"') and
   out.index("// 甲组：影视") > out.index('"key":"b"'),
   "`// 甲组` 随条目 a 一起移动（仍紧邻 a 之前）")
ok("// 末尾随手记" in out, "注释文本未被改写")
ok("[disabled]" in out, "禁用块保留")
ok([o.get("key") for o, dis in I.parse_sites_with_disabled(out) if dis] == ["c"],
   "c 仍是「已禁用」状态", str(all_keys(out)))
ok(I.parse_disabled_keys(out) == {"c"}, "禁用 key 集合不变")

print("\n== 3) 槽位填充：未参与条目原位不动 ==")
sub = ["a", "c", "e"]
out2, mv2 = S.reorder_by_keys(RAW, "sites", list(reversed(sub)))
ks2 = all_keys(out2)
ok([ks2[0], ks2[2], ks2[4]] == ["e", "c", "a"], "参与条目按新顺序回填原槽位", str(ks2))
ok(ks2[1] == "b" and ks2[3] == "d", "未参与条目 b/d 原位不动", str(ks2))
ok(mv2 == 2, "moved 只统计真正换了位置的条目", "moved=%s" % mv2)

print("\n== 4) 无变化 / 非法输入 → 原样返回 ==")
cur = all_keys(RAW)
o3, m3 = S.reorder_by_keys(RAW, "sites", cur)
ok(m3 == 0 and o3 is RAW, "顺序没变：返回原文且 moved=0", "moved=%s" % m3)
for name, args in (("空清单", []), ("未知 key", ["zz", "yy"]),
                   ("单条", ["a"])):
    o, m = S.reorder_by_keys(RAW, "sites", args)
    ok(m == 0 and o is RAW, "%s：不动作" % name, "moved=%s" % m)
o, m = S.reorder_by_keys(RAW, "nope", ["a", "b"])
ok(m == 0 and o is RAW, "数组不存在：不动作")
o, m = S.reorder_by_keys("{}", "sites", ["a", "b"])
ok(m == 0 and o == "{}", "配置无 sites：不动作")

print("\n== 5) 重复 key / 大小写 ==")
o, m = S.reorder_by_keys(RAW, "sites", ["a", "a", "b"])
ok(m == 0 and o is RAW, "重复 key 去重后顺序未变 → 不动作", "moved=%s" % m)
o, m = S.reorder_by_keys(RAW, "sites", ["A", "e", "b", "a"])
ok(all_keys(o) == ["e", "b", "c", "d", "a"],
   "key 区分大小写（A 不匹配 a，故 a 落到最后一个槽位）", str(all_keys(o)))

print("\n== 6) 重排后仍可继续做禁用 / 启用（往返一致） ==")
o = S.reorder_by_keys(RAW, "sites", ["e", "d", "c", "b", "a"])[0]
o2, found = I.enable_site(o, "c")
ok(found and I.parse_disabled_keys(o2) == set(), "启用 c 成功",
   str(I.parse_disabled_keys(o2)))
ok(all_keys(o2) == ["e", "d", "c", "b", "a"], "启用后顺序不变", str(all_keys(o2)))
o3, found = I.disable_site(o2, "e")
ok(found, "禁用 e 成功")
ok([x.get("key") for x, dis in I.parse_sites_with_disabled(o3) if dis] == ["e"],
   "e 变成已禁用", str(all_keys(o3)))
ok(all_keys(o3) == ["e", "d", "c", "b", "a"], "禁用不改变顺序", str(all_keys(o3)))

print("\n== 7) 缩进风格与文件体积（现网 4 空格缩进） ==")
o = S.reorder_by_keys(RAW, "sites", ["e", "d", "c", "b", "a"])[0]
ok('\n    {"key":"e"' in o and '\n    {"key":"d"' in o,
   "条目行保持 4 空格缩进（与现网配置一致）")
ok(len(o.splitlines()) <= len(RAW.splitlines()) + 4, "重排不会撑大文件",
   "%d -> %d 行" % (len(RAW.splitlines()), len(o.splitlines())))

print("\n== 8) 真实配置快照（存在才测，不修改原文件） ==")
_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cfg = os.path.join(_repo, "py.json")
if os.path.isfile(_cfg):
    with open(_cfg, "r", encoding="utf-8") as f:
        real = f.read()
    ks = keys_of(real)
    t0 = time.time()
    o, m = S.reorder_by_keys(real, "sites", list(reversed(ks)) + ks)
    dt = time.time() - t0
    got = keys_of(o)
    ok(len(got) == len(ks), "真实配置：条目数一致", "%s -> %s" % (len(ks), len(got)))
    ok(sorted(got) == sorted(ks), "真实配置：条目集合一致（无丢失/重复）")
    ok(got == list(reversed(ks)), "真实配置：顺序完全按目标重排")
    ok(sorted(I.parse_jsonc(o).keys()) == sorted(I.parse_jsonc(real).keys()),
       "真实配置：其它顶层键不变")
    ok(dt < 5.0, "真实配置：重排耗时 < 5s", "%.3fs" % dt)
    # 校验不写盘（原文件 hash 不变）
    with open(_cfg, "r", encoding="utf-8") as f:
        ok(f.read() == real, "真实配置原文件未被改动（只读验证）")
else:
    print("  [SKIP] 未找到 py.json（仓库配置不入库），跳过")

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
