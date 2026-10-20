# -*- coding: utf-8 -*-
"""「复制为新条目」(clone_site_entry) 回归测试 —— 纯逻辑，零 Qt 依赖。

背景：同一个 spider 脚本被多条 site 条目共用、各条用 ext 区分参数的场景
（如「一个脚本爬多个 UP 主」——每条 ext.mid 不同）。此前这类条目只能手改 JSON
或找 AI 代劳，GUI 完全做不到（源管家的注入规则里 key = "py_" + 文件名，
同一个脚本只能生成一个 key，重复注入会被「跳过（key 重复）」拦下）。

覆盖：
  A. 基本克隆：条目数 +1、key 唯一、源条目原样保留
  B. ext 覆盖：新条目的 ext 生效，源条目 ext 不受影响
  C. key 冲突 / 源不存在 → 抛 ValueError（不静默覆盖）
  D. unique_site_key：base / base_2 / base_3 不冲突
  E. 注释与排版保留（JSONC 不被破坏，仍可解析）
  F. 克隆后不产生「功能重复」（同 api 不同 ext → 指纹不同，不报重）
  G. 禁用条目克隆后不带 _disabled 标记
  H. 真实场景：一条 B 站脚本克隆出第二个 UP
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyinj_core as C

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print("[%s] %-56s %s" % ("OK " if cond else "FAIL", name, extra))


def _sites(text):
    return C.parse_jsonc(text)["sites"]


# ---- 构造一个含注释的迷你配置（贴近真实 py.json 的形态）----
RAW = """// 顶部注释
{
  "spider": "",
  // 站点数组
  "sites": [
    {
      "key": "py_demo",
      "name": "演示源┃PY",
      "api": "./py/demo.py",
      "ext": {
        "mid": "111"
      },
      "file": "./py/demo.py",
      "type": 3
    },
    {
      "key": "other",
      "name": "别的源",
      "api": "./py/other.py",
      "type": 3
    }
  ],
  // 尾注释
  "parses": []
}
"""

print("== A) 基本克隆 ==")
out, ent = C.clone_site_entry(RAW, "py_demo", "py_demo2",
                              new_name="演示源2┃PY", new_ext={"mid": "222"})
s = _sites(out)
ok("站点数 2 → 3", len(s) == 3, "got=%d" % len(s))
ok("新 key 存在", any(x.get("key") == "py_demo2" for x in s))
ks = [x.get("key") for x in s]
ok("key 仍唯一", len(ks) == len(set(ks)), ks)
new = next(x for x in s if x.get("key") == "py_demo2")
ok("新条目 name 已设", new.get("name") == "演示源2┃PY", new.get("name"))
ok("新条目 api 沿用源", new.get("api") == "./py/demo.py", new.get("api"))
ok("新条目 file 沿用源", new.get("file") == "./py/demo.py", new.get("file"))
ok("新条目 type 沿用源", new.get("type") == 3, new.get("type"))

print()
print("== B) ext 覆盖 ==")
ok("新条目 ext = 新值", new.get("ext") == {"mid": "222"}, new.get("ext"))
src = next(x for x in s if x.get("key") == "py_demo")
ok("源条目 ext 未被动", src.get("ext") == {"mid": "111"}, src.get("ext"))
ok("源条目 name 未被动", src.get("name") == "演示源┃PY", src.get("name"))

print()
print("== C) 冲突与异常 ==")
try:
    C.clone_site_entry(RAW, "py_demo", "other")
    ok("key 冲突应报错", False, "未抛异常")
except ValueError as ex:
    ok("key 冲突抛 ValueError", "已存在" in str(ex), str(ex)[:40])
try:
    C.clone_site_entry(RAW, "no_such", "x1")
    ok("源 key 不存在应报错", False, "未抛异常")
except ValueError as ex:
    ok("源 key 不存在抛 ValueError", "未找到" in str(ex), str(ex)[:40])
try:
    C.clone_site_entry(RAW, "py_demo", "   ")
    ok("空 key 应报错", False, "未抛异常")
except ValueError:
    ok("空 key 抛 ValueError", True)

print()
print("== D) unique_site_key ==")
k1 = C.unique_site_key(RAW, "py_demo")
k2 = C.unique_site_key(RAW, "py_demo", taken={"py_demo_2"})
k3 = C.unique_site_key(RAW, "brand_new")
ok("已存在 → 加 _2 后缀", k1 == "py_demo_2", k1)
ok("taken 冲突 → 跳到 _3", k2 == "py_demo_3", k2)
ok("全新 base 原样返回", k3 == "brand_new", k3)

print()
print("== E) 注释与排版保留 ==")
ok("仍是合法 JSONC", isinstance(C.parse_jsonc(out), dict))
ok("注释数量未变", out.count("//") == RAW.count("//"),
   "%d → %d" % (RAW.count("//"), out.count("//")))
ok("顶层键未丢", set(C.parse_jsonc(out).keys()) == set(C.parse_jsonc(RAW).keys()))
ok("其它段落未动", C.parse_jsonc(out).get("parses") == C.parse_jsonc(RAW).get("parses"))

print()
print("== F) 克隆后不产生功能重复 ==")
reps = C.check_duplicates(_sites(out))
ok("同 api 不同 ext → 不判重", len(reps) == 0, reps)
# 同样的 ext 则应判重（提醒用户 ext 必须改）
out_same, _ = C.clone_site_entry(RAW, "py_demo", "py_demo3", new_ext={"mid": "111"})
reps2 = C.check_duplicates(_sites(out_same))
ok("同 api 同 ext → 判为重复（提示改 ext）", len(reps2) == 1, reps2)

print()
print("== G) 禁用条目克隆 ==")
RAW_DIS = RAW.replace('"key": "py_demo",', '"key": "py_demo", "_disabled": 1,')
_, ent_dis = C.clone_site_entry(RAW_DIS, "py_demo", "py_demo4")
ok("新条目不带 _disabled", "_disabled" not in ent_dis)

print()
print("== H) 真实场景：一个脚本爬两个 UP ==")
out2, _ = C.clone_site_entry(RAW, "py_demo", "py_bili_up2",
                              new_name="UP2┃PY", new_ext={"mid": "222"})
s2 = _sites(out2)
a = next(x for x in s2 if x.get("key") == "py_demo")
b = next(x for x in s2 if x.get("key") == "py_bili_up2")
ok("两条共用同一 api", a.get("api") == b.get("api") == "./py/demo.py")
ok("两条 mid 不同", a.get("ext")["mid"] == "111" and b.get("ext")["mid"] == "222")
ok("两条 key 不同", a.get("key") != b.get("key"))
ok("不判为重复", len(C.check_duplicates(s2)) == 0)

print()
print("CLONE TEST %s (%d 通过, %d 失败)" % ("OK" if FAIL == 0 else "FAIL", PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
