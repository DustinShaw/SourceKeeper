# -*- coding: utf-8 -*-
"""智能分流导出（split_by_adult）单元测试。

判定依据（用户拍板）：只按现有 adult 字段 / 已跑过的检测结果，不做实时内容检测。
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyinj_core as C   # noqa: E402

PASS = FAIL = 0


def ok(cond, name, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


RAW = """{
"spider": "",
"sites": [
{"key":"a","name":"普通A","api":"./py/a.py","type":3},
{"key":"b","name":"成人B","api":"./py/b.py","type":3,"adult":1},
{"key":"c","name":"成人C","api":"./py/c.py","type":3,"adult":0},
{"key":"d","name":"成人D","api":"./py/d.py","type":3,"adult":true}
]
}
"""


def _sites(raw=RAW):
    return C.parse_config_text(raw)["sites"]


def test_pure_excludes_adult():
    r = C.split_by_adult(RAW, _sites())
    pure = json.loads(r["pure_text"])
    keys = {s["key"] for s in pure["sites"]}
    ok(keys == {"a", "c"}, "纯净版剔除 adult=1/true，保留 adult=0", str(keys))
    ok(r["adult_count"] == 2, "成人计数=2", str(r["adult_count"]))
    ok(r["pure_removed"] == 2, "纯净版剔除数=2", str(r["pure_removed"]))


def test_full_keeps_all():
    r = C.split_by_adult(RAW, _sites())
    full = json.loads(r["full_text"])
    keys = {s["key"] for s in full["sites"]}
    ok(keys == {"a", "b", "c", "d"}, "完整版保留全部 4 条", str(keys))


def test_result_shape():
    r = C.split_by_adult(RAW, _sites())
    for k in ("pure_text", "full_text", "pure_kept", "pure_removed",
              "total", "adult_count", "adult_names"):
        ok(k in r, "返回含字段 %s" % k)
    ok(set(r["adult_names"]) == {"成人B", "成人D"}, "成人名列表正确", str(r["adult_names"]))


def test_adult_keys_union_with_field():
    """adult_keys 与字段取并集：普通 A 也被算成人 → 纯净版只剩 c（唯一的非成人）。"""
    r = C.split_by_adult(RAW, _sites(), adult_keys={"a"})
    pure = json.loads(r["pure_text"])
    keys = {s["key"] for s in pure["sites"]}
    ok(keys == {"c"}, "adult_keys={a} ∪ 字段成人{b,d} → 纯净版只留 c", str(keys))


def test_adult_keys_extra_beyond_field():
    """再给一个不重名的 key（c 本非成人）→ 并集仍是 {a? 否}，纯净版清空。"""
    r = C.split_by_adult(RAW, _sites(), adult_keys={"a", "c"})
    pure = json.loads(r["pure_text"])
    keys = {s["key"] for s in pure["sites"]}
    ok(keys == set(), "adult_keys={a,c} 且 b/d 字段成人 → 纯净版空", str(keys))


def test_base_keys_subset():
    """base_keys 限定参与分流的范围。"""
    r = C.split_by_adult(RAW, _sites(), base_keys=["a", "b"])
    pure = json.loads(r["pure_text"])
    keys = {s["key"] for s in pure["sites"]}
    ok(keys == {"a"}, "base_keys=[a,b] → 纯净版只留 a", str(keys))
    ok(r["total"] == 2, "total=2", str(r["total"]))


def test_no_adult_all_kept():
    raw = '{"sites":[{"key":"x","name":"X","api":"./py/x.py","type":3}]}'
    r = C.split_by_adult(raw, C.parse_config_text(raw)["sites"])
    pure = json.loads(r["pure_text"])
    ok(len(pure["sites"]) == 1 and r["adult_count"] == 0, "无成人时纯净版=全部", str(r))


def test_result_is_valid_jsonc():
    r = C.split_by_adult(RAW, _sites())
    for t in (r["pure_text"], r["full_text"]):
        try:
            C.parse_config_text(t)
            good = True
        except Exception:
            good = False
        ok(good, "导出文本可被 parse_config_text 解析")


def test_scalar_forms():
    """adult 的各种形态：1 / "1" / true / yes / 0 / false / None。"""
    cases = [
        ({"key": "k", "adult": 1}, True), ({"key": "k", "adult": "1"}, True),
        ({"key": "k", "adult": True}, True), ({"key": "k", "adult": "yes"}, True),
        ({"key": "k", "adult": 0}, False), ({"key": "k", "adult": "0"}, False),
        ({"key": "k", "adult": False}, False), ({"key": "k"}, False),
    ]
    for e, exp in cases:
        got = C._entry_is_adult(e, None)
        ok(got == exp, "adult=%r → %s" % (e.get("adult"), exp), str(got))


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)
