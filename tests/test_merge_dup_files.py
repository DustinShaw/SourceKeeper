# -*- coding: utf-8 -*-
"""合并导入：判重「重复(dup)」条目的配套文件处理回归测试（纯逻辑，零 Qt）。

背景（实测复现的真实缺陷）：
    来源站点与本地已有站点「功能身份」相同（type+api+jar+ext）时判 dup、action=skip，
    旧实现只对 action in (add, overwrite) 的条目搬运配套文件 —— 于是
    **配置里指向 ./py/x.py，但目标仓库根本没有这个文件**，该源直接失效。
    用户观感就是「合并了，但 py 文件没复制过来」。

修正后的口径（apply_merge 的 fill_missing_for_dup）：
    · 目标不存在      → 搬运（补全）          记入 file_stats["filled_missing"]
    · 目标存在且相同  → 跳过（无变化）
    · 目标存在但不同  → **不覆盖**（可能是用户本地改过）→ 记入 file_stats["dup_outdated"]
    · 补文件 ≠ 导入条目：配置文本的 sites 条目数必须保持不变
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyinj_core as C

PASS = FAIL = 0


def ok(cond, label, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("FAIL  %s  %s" % (label, extra))


SPIDER = "class Spider:\n    pass\n"


def cfg_text(sites):
    body = ",\n".join("    " + json.dumps(s, ensure_ascii=False) for s in sites)
    return '{\n  "sites": [\n%s\n  ]\n}\n' % body


def entry(api="./py/a.py", key="py_a", name="A站"):
    return {"key": key, "name": name, "api": api, "type": 3,
            "filterable": 1, "quickSearch": 1, "searchable": 1}


def make_pair(src_files, tgt_files):
    """建 (src_repo, tgt_repo)；files = {"py/a.py": "内容"}"""
    tmp = tempfile.mkdtemp(prefix="pyinj_dupf_")
    src, tgt = os.path.join(tmp, "src"), os.path.join(tmp, "tgt")
    for base, files in ((src, src_files), (tgt, tgt_files)):
        for rel, txt in (files or {}).items():
            p = os.path.join(base, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(txt)
        os.makedirs(os.path.join(base, "py"), exist_ok=True)
    return tmp, src, tgt


def dup_rows(raw, inc_text):
    """算合并计划；断言来源条目被判为 dup/skip。"""
    return C.plan_merge(C.parse_sites_with_disabled(raw),
                        C.load_sites_from_text(inc_text))["rows"]


print("== 1) dup + 目标缺 .py → 必须补上（核心修复）==")
raw = cfg_text([entry()])
inc = cfg_text([entry()])
rows = dup_rows(raw, inc)
ok(len(rows) == 1 and rows[0]["verdict"] == "dup" and rows[0]["action"] == "skip",
   "来源条目判为 dup / action=skip", rows)
tmp, src, tgt = make_pair({"py/a.py": SPIDER}, {})
nt, st, fs = C.apply_merge(raw, rows, src_repo_dir=src, target_repo_dir=tgt)
ok(os.path.isfile(os.path.join(tgt, "py", "a.py")),
   "目标仓库已补上 py/a.py（旧实现此处为空）", sorted(os.listdir(tgt)))
ok(fs.get("filled_missing") == ["py/a.py"], "file_stats.filled_missing 如实上报", fs)
ok(C.parse_jsonc(nt)["sites"].__len__() == 1, "补文件 ≠ 导入条目：sites 条目数不变")
ok(st.get("added") == 0, "未新增站点（added=0）", st)
shutil.rmtree(tmp, ignore_errors=True)

print("== 2) dup + 目标已有同名且内容相同 → 跳过，不重复搬 ==")
tmp, src, tgt = make_pair({"py/a.py": SPIDER}, {"py/a.py": SPIDER})
rows = dup_rows(raw, inc)
nt, st, fs = C.apply_merge(raw, rows, src_repo_dir=src, target_repo_dir=tgt)
ok(fs.get("filled_missing") == [], "内容相同 → 不计入 filled_missing（无需搬运）", fs)
ok(fs.get("copied") == [] and fs.get("renamed") == [] and fs.get("skipped") == [],
   "同内容文件不进计划：零 IO、零改动", fs)
with open(os.path.join(tgt, "py", "a.py"), encoding="utf-8") as f:
    ok(f.read() == SPIDER, "目标文件保持原样")
shutil.rmtree(tmp, ignore_errors=True)

print("== 3) dup + 目标已有同名但内容不同 → 不覆盖，只上报 ==")
LOCAL = "# 本地改过的版本\nclass Spider:\n    pass\n"
tmp, src, tgt = make_pair({"py/a.py": SPIDER}, {"py/a.py": LOCAL})
rows = dup_rows(raw, inc)
nt, st, fs = C.apply_merge(raw, rows, src_repo_dir=src, target_repo_dir=tgt)
ok(fs.get("dup_outdated") == ["py/a.py"], "上报 dup_outdated", fs)
with open(os.path.join(tgt, "py", "a.py"), encoding="utf-8") as f:
    still = f.read()
ok(still == LOCAL, "本地版本未被覆盖（绝不擅自盖掉用户改动）", still)
ok(fs.get("renamed") == [] and fs.get("copied") == [], "不改名、不搬运", fs)
ok(os.path.isfile(os.path.join(tgt, "py", "a.py"))
   and not os.path.isfile(os.path.join(tgt, "py", "a_2.py")), "未产生 a_2.py")
shutil.rmtree(tmp, ignore_errors=True)

print("== 4) dup 脚本内部的同伴引用也一并补齐（深挖）==")
tmp, src, tgt = make_pair(
    {"py/a.py": "import b\n" + SPIDER, "py/b.py": "# helper\n"}, {})
rows = dup_rows(raw, inc)
nt, st, fs = C.apply_merge(raw, rows, src_repo_dir=src, target_repo_dir=tgt)
ok(sorted(fs.get("filled_missing") or []) == ["py/a.py", "py/b.py"],
   "a.py 与其 import 的 b.py 都已补齐", fs)
ok(os.path.isfile(os.path.join(tgt, "py", "b.py")), "b.py 确实落盘")
shutil.rmtree(tmp, ignore_errors=True)

print("== 5) 可关闭：fill_missing_for_dup=False → 回到旧行为 ==")
tmp, src, tgt = make_pair({"py/a.py": SPIDER}, {})
rows = dup_rows(raw, inc)
nt, st, fs = C.apply_merge(raw, rows, src_repo_dir=src, target_repo_dir=tgt,
                           fill_missing_for_dup=False)
ok(not os.path.isfile(os.path.join(tgt, "py", "a.py")), "关闭后不补文件")
ok(fs.get("filled_missing") == [], "关闭后 filled_missing 为空", fs)
shutil.rmtree(tmp, ignore_errors=True)

print("== 6) 非 dup 场景不受影响（new 仍正常搬 + 冲突仍改名）==")
tmp, src, tgt = make_pair({"py/a.py": SPIDER}, {})
rows_new = C.plan_merge([], C.load_sites_from_text(inc))["rows"]
ok(rows_new[0]["verdict"] == "new" and rows_new[0]["action"] == "add",
   "空仓库来源判 new/add", rows_new)
nt, st, fs = C.apply_merge('{"sites":[]}', rows_new, src_repo_dir=src, target_repo_dir=tgt)
ok(fs.get("copied") == ["py/a.py"], "new 场景照常搬运", fs)
ok(fs.get("filled_missing") == [], "new 场景不产生 filled_missing（无重复行）", fs)

tmp, src, tgt = make_pair({"py/a.py": SPIDER}, {"py/a.py": "# 旧版\n"})
rows_new = C.plan_merge([], C.load_sites_from_text(inc))["rows"]
nt, st, fs = C.apply_merge('{"sites":[]}', rows_new, src_repo_dir=src, target_repo_dir=tgt)
ok(fs.get("renamed") == ["py/a_2.py"] or fs.get("copied") == ["py/a_2.py"],
   "目标同名不同内容 → 改名搬运（原有行为不变）", fs)
ok(os.path.isfile(os.path.join(tgt, "py", "a_2.py")), "a_2.py 落盘")
shutil.rmtree(tmp, ignore_errors=True)

print("== 7) 目标仓库被禁用行（verdict=skip）不参与补全 ==")
raw2 = cfg_text([entry(api="./py/a.py", key="py_a"),
                 entry(api="./py/b.py", key="py_b")])
inc2 = cfg_text([entry(api="./py/a.py", key="py_a"),
                 entry(api="./py/b.py", key="py_b")])
rows2 = C.plan_merge(C.parse_sites_with_disabled(raw2),
                     C.load_sites_from_text(inc2))["rows"]
ok(all(r["verdict"] == "dup" for r in rows2), "两条均为 dup", [r["verdict"] for r in rows2])
tmp, src, tgt = make_pair({"py/a.py": SPIDER, "py/b.py": SPIDER}, {})
nt, st, fs = C.apply_merge(raw2, rows2, src_repo_dir=src, target_repo_dir=tgt)
ok(sorted(fs.get("filled_missing") or []) == ["py/a.py", "py/b.py"],
   "两条 dup 的缺失文件都补齐", fs)
shutil.rmtree(tmp, ignore_errors=True)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
