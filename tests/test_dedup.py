# -*- coding: utf-8 -*-
"""查重 / 去重判重口径回归测试（2026-09-29 二次修正）。

判重口径（最终）：
  · **key 重复** → 结构性冲突（key 必须唯一）；
  · **(api + jar + ext) 三者全同** → 功能重复（真重复，不论 key 是否相同）；
  · 仅 api 相同、ext/jar 不同 → 多线路复用，**不算重复**；
  · **name 不参与判重**（重名 ≠ 重复）。

本文件锁定：不得用 api 单列判重（会把合法多线路误报）；
也不得把 key 塞进功能指纹（会漏报 key 不同但实为重复的条目）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyinj_core as C  # noqa: E402

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  \u2713 " + name)
    else:
        FAIL += 1
        print("  \u2717 " + name + "   " + str(extra))


JAR = "http://x/lubin.jar"


def S(key, api, jar=None, ext=None, name=None):
    d = {"key": key, "api": api}
    if jar is not None:
        d["jar"] = jar
    if ext is not None:
        d["ext"] = ext
    if name is not None:
        d["name"] = name
    return d


# ---------------------------------------------------------------------------
print("== 1) site_fingerprint 不含 key（关键回归点）==")
fp1 = C.site_fingerprint(S("k1", "csp_X", JAR, {"site": "http://a.com"}))
fp2 = C.site_fingerprint(S("k2", "csp_X", JAR, {"site": "http://a.com"}))
ok("key 不同、其余全同 → 指纹相同（不含 key）", fp1 == fp2, "%r vs %r" % (fp1, fp2))
ok("指纹长度为 4（type/api/jar/ext）", len(fp1) == 4, fp1)

print("== 1b) type 判重维度（2026-09-30 三元组 → 四元组升级）==")
OK_T = C.check_duplicates([
    {"key": "t1", "api": "http://cms/vod/", "type": 1},
    {"key": "t2", "api": "http://cms/vod/", "type": 3},   # 同 URL 不同 type
])
ok("同 api 不同 type 不判重复", OK_T == [], OK_T)
OK_T2 = C.check_duplicates([
    {"key": "t3", "api": "http://cms/vod/", "type": 1},
    {"key": "t4", "api": "http://cms/vod/", "type": 1},   # 同 type 同 api
])
ok("同 type 同 api 仍判重复", len(OK_T2) == 1, OK_T2)

print("== 2) 真重复：type+api+jar+ext 全同、key 不同 → 应报 ==")
r = C.check_duplicates([
    S("a1", "csp_X", JAR, {"site": "http://a.com"}),
    S("a2", "csp_X", JAR, {"site": "http://a.com"}),
])
ok("报出 1 组重复", len(r) == 1, r)

print("== 3) 仅 api 相同、ext 不同 → 不应报（多线路复用）==")
r = C.check_duplicates([
    S("b1", "csp_PanWebShare", JAR, {"site": ["http://a.com"]}),
    S("b2", "csp_PanWebShare", JAR, {"site": ["http://b.com"]}),
])
ok("不报（api 相同 ext 不同）", r == [], r)

print("== 4) 仅 api 相同、jar 不同 → 不应报 ==")
r = C.check_duplicates([
    S("c1", "csp_X", "http://x/1.jar", {"site": "http://a.com"}),
    S("c2", "csp_X", "http://x/2.jar", {"site": "http://a.com"}),
])
ok("不报（jar 不同）", r == [], r)

print("== 5) key 重复 → 应报 ==")
r = C.check_duplicates([S("k1", "./py/a.py"), S("k1", "./py/b.py")])
ok("报 key 重复", len(r) == 1 and "key=k1" in r[0], r)

print("== 6) name 相同但 api 不同 → 不应报 ==")
r = C.check_duplicates([S("m1", "./py/a.py", name="同名"),
                        S("m2", "./py/b.py", name="同名")])
ok("name 重复不算重复", r == [], r)

print("== 7) ext 字典键序不同 → 仍判为相同（sort_keys 归一）==")
r = C.check_duplicates([
    S("e1", "csp_X", JAR, {"site": "http://a.com", "level": 1}),
    S("e2", "csp_X", JAR, {"level": 1, "site": "http://a.com"}),
])
ok("键序不同仍判重复", len(r) == 1, r)

print("== 8) 报告含 key/name 便于定位 ==")
r = C.check_duplicates([
    S("a1", "csp_X", JAR, {"site": "http://a.com"}, name="站A"),
    S("a2", "csp_X", JAR, {"site": "http://a.com"}, name="站B"),
])
ok("报告含命中 key", "a1" in r[0] and "a2" in r[0], r)

print("== 9) 真实配置：合法多线路不应被误报 ==")
REAL = [
    S("至臻", "csp_PanWebShare", JAR, {"site": ["http://103.231.12.104:22776"]}),
    S("木偶", "csp_PanWebShare", JAR, {"site": ["https://www.muoua.top"]}),
    S("蜡笔", "csp_PanWebShare", JAR, {"site": ["http://xiaocge.fun"]}),
    S("配置中心", "csp_Config", JAR, None),
    S("csp_Config", "csp_Config", "http://rihou.cc:88/jar/vox.jar", None),
]
ok("7 组 csp_* 同名 api 全不报", C.check_duplicates(REAL) == [],
   C.check_duplicates(REAL))

# ---------------------------------------------------------------------------
print("== 10) deduplicate_sites 删真重复、留多线路 ==")
raw = """{
"sites": [
{"key":"a1","name":"站A","api":"csp_X","jar":"%s","ext":{"site":"http://a.com"}},
{"key":"a2","name":"站A副本","api":"csp_X","jar":"%s","ext":{"site":"http://a.com"}},
{"key":"b1","name":"站B","api":"csp_X","jar":"%s","ext":{"site":"http://b.com"}}
]}
""" % (JAR, JAR, JAR)
new, removed = C.deduplicate_sites(raw)
data = C.parse_config_text(new)
left = [s["key"] for s in data["sites"]]
ok("删掉 1 条真重复", len(removed) == 1, removed)
ok("保留 a1 + 多线路 b1", left == ["a1", "b1"], left)
ok("结果仍是合法 JSON", isinstance(data, dict))

print("== 11) deduplicate_sites：key 重复也删 ==")
raw2 = ('{"sites":[\n'
        '{"key":"k1","name":"X","api":"./py/x.py"},\n'
        '{"key":"k1","name":"Y","api":"./py/y.py"}\n]}\n')
new2, removed2 = C.deduplicate_sites(raw2)
left2 = [s["key"] for s in C.parse_config_text(new2)["sites"]]
ok("删掉重复 key 的第 2 条", len(removed2) == 1 and left2 == ["k1"], (removed2, left2))

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
