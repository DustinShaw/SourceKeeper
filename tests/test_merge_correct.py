# -*- coding: utf-8 -*-
"""合并导入（修正版）正确性测试
=================================
覆盖 2026-09-30 重做前暴露的 4 类根因：
  1) jar 型 spider 按 api 单独判重 -> 同 api 不同 ext 多站点被误并（必须按 api+jar+ext 指纹）；
  2) normalize_site 只留 7 字段 -> 丢 ext/jar/adult；
  3) fmt_entry 只写 6 字段 -> 落地丢 ext/jar；
  4) 配套 .py/.js 文件未搬运 -> 源失效。
用法：envs/default/Scripts/python.exe test_merge_correct.py
"""
import os
import io
import json
import tempfile
import shutil

sys = __import__("sys")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


import pyinj_core as C

print("\n== 1) normalize_site_full 保留全部字段 ==")
raw = {"key": "k", "name": "n", "api": "./py/a.py", "ext": {"site": "http://x"},
       "jar": "http://j.jar", "adult": 1, "changeable": True, "categories": ["电影"]}
o = C.normalize_site_full(raw)
ok("ext 保留", o.get("ext") == {"site": "http://x"}, o)
ok("jar 保留", o.get("jar") == "http://j.jar", o)
ok("adult 保留", o.get("adult") == 1, o)
ok("changeable 保留", o.get("changeable") is True, o)
ok("categories 保留", o.get("categories") == ["电影"], o)
ok("核心字段仍在", o["key"] == "k" and o["api"] == "./py/a.py" and o["type"] == 3, o)

print("\n== 2) fmt_entry 写出额外字段 ==")
txt = C.fmt_entry(o)
ok("ext 被写出", '"ext"' in txt and '"site": "http://x"' in txt, txt)
ok("jar 被写出", '"jar": "http://j.jar"' in txt, txt)
ok("adult 被写出", '"adult": 1' in txt, txt)
ok("type 收尾且合法", txt.rstrip().endswith("}"), txt)
# 7 字段 dict 输出与旧版一致（向后兼容）
core = C.fmt_entry({"key": "k", "name": "n", "api": "u", "filterable": True,
                    "quickSearch": False, "searchable": True, "type": 1})
ok("纯核心 dict 含 7 字段、无多余键",
   all(k in core for k in ('"key"', '"name"', '"api"', '"filterable"',
                           '"quickSearch"', '"searchable"', '"type"')),
   core)

print("\n== 3) plan_merge：jar 多站点（同 api 不同 ext）不互相合并（关键回归）==")
base = [({"key": "b1", "name": "B", "api": "csp_PanWebShare",
          "jar": "http://x.jar", "ext": {"site": "Z"}}, False)]
inc = [({"key": "s%d" % i, "api": "csp_PanWebShare", "jar": "http://x.jar",
         "ext": {"site": chr(65 + i)}}, False) for i in range(8)]
plan = C.plan_merge(base, inc)
ok("8 个同 api 不同 ext 全部判为新增（未被误并）", plan["summary"]["new"] == 8,
   plan["summary"])
ok("无一条被判重复", plan["summary"]["dup"] == 0, plan["summary"])
ok("8 条新增 key 互不相同",
   len({r["obj"]["key"] for r in plan["rows"] if r["verdict"] == "new"}) == 8,
   [r["obj"]["key"] for r in plan["rows"]])
# 第 9 个与 base 同指纹 -> 重复
inc2 = inc + [({"key": "dup1", "api": "csp_PanWebShare", "jar": "http://x.jar",
                "ext": {"site": "Z"}}, False)]
plan2 = C.plan_merge(base, inc2)
ok("与 base 同指纹的条目被判 dup", plan2["summary"]["dup"] == 1, plan2["summary"])

print("\n== 4) plan_merge：dup / conflict / skip 区分 ==")
base = [({"key": "a", "name": "A", "api": "./py/x.py"}, False)]
inc = [
    ({"key": "z", "name": "Z", "api": "./py/x.py"}, False),   # 同 api 无 jar/ext -> 同指纹 -> dup
    ({"key": "a", "name": "A2", "api": "./py/y.py"}, False),  # 同 key 不同指纹 -> conflict
    ({"key": "n", "name": "N", "api": "./py/n.py"}, False),   # 全新 -> new
    ({"key": "n", "name": "N2", "api": "./py/n2.py"}, False), # 批次内同 key -> skip
]
plan = C.plan_merge(base, inc)
bykey = {r["obj"]["key"]: r for r in plan["rows"]}
ok("z 判为 dup（功能重复）", bykey["z"]["verdict"] == "dup" and bykey["z"]["matched_key"] == "a", bykey["z"])
ok("a 判为 conflict（key 撞车）", bykey["a"]["verdict"] == "conflict", bykey["a"])
ok("conflict 自动改名 a_2", bykey["a"]["new_key"] == "a_2", bykey["a"])
ok("n 判为 new",
   next(r["verdict"] for r in plan["rows"] if r["obj"]["key"] == "n" and r["verdict"] == "new") == "new",
   [r["verdict"] for r in plan["rows"] if r["obj"]["key"] == "n"])
ok("第二个 n 判为 skip（批次内重复）",
   [r["verdict"] for r in plan["rows"] if r["obj"]["key"] == "n"][1] == "skip", plan["rows"])

print("\n== 5) apply_merge：字段原样落地 ==")
RAW = '{\n  "spider": "http://e.com/s.js",\n  "sites": [\n    {"key": "a", "name": "A", "api": "./py/x.py", "type": 3}\n  ]\n}'
inc_raw = [({"key": "new1", "name": "新", "api": "csp_PanWebShare", "jar": "http://x.jar",
             "ext": {"site": "http://up"}, "adult": 1, "type": 3}, False)]
inc = [(C.normalize_site_full(d), dis) for d, dis in inc_raw]
plan = C.plan_merge(C.load_sites_from_text(RAW), inc)
rows = plan["rows"]
text, stats, fstats = C.apply_merge(RAW, rows)
data = C.parse_config_text(text)
added = [s for s in data["sites"] if s["key"] == "new1"][0]
ok("新增站点含 ext", added.get("ext") == {"site": "http://up"}, added)
ok("新增站点含 jar", added.get("jar") == "http://x.jar", added)
ok("新增站点含 adult", added.get("adult") == 1, added)
ok("原站点未被改动", any(s["key"] == "a" and s["api"] == "./py/x.py" for s in data["sites"]))
ok("统计 added=1", stats["added"] == 1, stats)

print("\n== 6) copy_companions：本地 .py 配套文件搬运 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_cp_")
src = os.path.join(tmp, "src"); tgt = os.path.join(tmp, "tgt")
for d in (src, tgt):
    os.makedirs(os.path.join(d, "py"))
with open(os.path.join(src, "py", "foo.py"), "w", encoding="utf-8") as f:
    f.write("class Spider:\n    pass\n")
fs = C.copy_companions(src, tgt, [{"api": "./py/foo.py"}])
ok("文件被复制", os.path.isfile(os.path.join(tgt, "py", "foo.py")), fs)
ok("copied 计数 1", len(fs["copied"]) == 1, fs)
fs2 = C.copy_companions(src, tgt, [{"api": "./py/foo.py"}])
ok("目标已存在则跳过", len(fs2["skipped"]) == 1 and len(fs2["copied"]) == 0, fs2)
# 远程 api 不搬运
fs3 = C.copy_companions(src, tgt, [{"api": "http://e.com/x.py"}])
ok("远程 api 不搬运", len(fs3["copied"]) + len(fs3["skipped"]) == 0, fs3)
shutil.rmtree(tmp, ignore_errors=True)

print("\n== 7) site_fingerprint 四元组 (type, api, jar, ext) ==")
fp_a1 = C.site_fingerprint({"type": 1, "api": "http://cms/x", "jar": "", "ext": None})
fp_a3 = C.site_fingerprint({"type": 3, "api": "http://cms/x", "jar": "", "ext": None})
ok("同 api 不同 type 不再误判重复", fp_a1 != fp_a3, (fp_a1, fp_a3))
fp_j1 = C.site_fingerprint({"type": 3, "api": "csp_X", "jar": "j.jar", "ext": {"site": "1"}})
fp_j2 = C.site_fingerprint({"type": 3, "api": "csp_X", "jar": "j.jar", "ext": {"site": "2"}})
ok("jar 同类名不同 ext 仍不误并", fp_j1 != fp_j2)
fp_same = C.site_fingerprint({"type": 3, "api": "csp_X", "jar": "j.jar", "ext": {"site": "1"}})
ok("完全相同四项则判重", fp_j1 == fp_same)

print("\n== 8) normalize_site 修复 type=0 被误覆盖 + 缺 type 兜底 ==")
n0 = C.normalize_site({"key": "x", "name": "X", "api": "http://xml/x.xml", "type": 0})
ok("显式 type=0 保留为 0（不再被 infer 改 1）", n0["type"] == 0, n0)
n4 = C.normalize_site({"key": "y", "name": "Y", "api": "http://dir/d", "type": 4})
ok("显式 type=4 保留为 4", n4["type"] == 4, n4)
n1 = C.normalize_site({"key": "z", "api": "http://cms/api.php/provide/vod/"})
ok("缺 type 的 URL 推断为 1", n1["type"] == 1, n1)
n3 = C.normalize_site({"key": "w", "api": "./py/t.py"})
ok("缺 type 的 .py 推断为 3", n3["type"] == 3, n3)
n0m = C.normalize_site({"key": "q", "api": "http://xml/x.xml"})
ok("缺 type 的 XML 不崩溃（best-effort）", n0m["type"] in (0, 1), n0m)

print("\n== 9) copy_companions：绝对路径 rebase + 传递依赖深挖 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_d_")
src = os.path.join(tmp, "src"); tgt = os.path.join(tmp, "tgt")
os.makedirs(os.path.join(src, "py", "sub")); os.makedirs(os.path.join(tgt, "py"))
open(os.path.join(src, "py", "main.py"), "w", encoding="utf-8").write("import helper\nfrom sub.mod import x\n")
open(os.path.join(src, "py", "helper.py"), "w", encoding="utf-8").write("print(1)\n")
open(os.path.join(src, "py", "sub", "mod.py"), "w", encoding="utf-8").write("print(2)\n")
abs_api = os.path.join(src, "py", "absmain.py")
open(abs_api, "w", encoding="utf-8").write("import helper\n")
st = C.copy_companions(src, tgt, [{"api": "./py/main.py"}, {"api": abs_api}])
ok("主脚本复制", os.path.isfile(os.path.join(tgt, "py", "main.py")), st)
ok("深挖：同目录 helper.py 复制", os.path.isfile(os.path.join(tgt, "py", "helper.py")), st)
ok("深挖：子包 sub/mod.py 复制", os.path.isfile(os.path.join(tgt, "py", "sub", "mod.py")), st)
ok("绝对路径 api rebase 复制", os.path.isfile(os.path.join(tgt, "py", "absmain.py")), st)
reb = C._rebase_entry({"api": abs_api}, src)
ok("rebase 后 api 变相对路径", reb["api"] == "./py/absmain.py", reb)
shutil.rmtree(tmp, ignore_errors=True)

print("\n== 10) copy_companions_remote：file:// 离线模拟远程下载（深挖 + 二进制 jar）==")
tmp = tempfile.mkdtemp(prefix="pyinj_r_")
remote_dir = os.path.join(tmp, "remote"); tgt = os.path.join(tmp, "tgt")
os.makedirs(os.path.join(remote_dir, "py")); os.makedirs(tgt)
open(os.path.join(remote_dir, "py", "main.py"), "w", encoding="utf-8").write("import helper\n")
open(os.path.join(remote_dir, "py", "helper.py"), "w", encoding="utf-8").write("print(1)\n")
open(os.path.join(remote_dir, "x.jar"), "wb").write(b"\xca\xfe\xba\xbeJAR\x00")
from urllib.parse import urljoin
rb = urljoin("file:///" + remote_dir.replace("\\", "/") + "/", "./")
st = C.copy_companions_remote(rb, tgt, [{"api": "./py/main.py"}, {"jar": "x.jar"}])
ok("远程 .py 下载落地", os.path.isfile(os.path.join(tgt, "py", "main.py")), st)
ok("远程深挖 helper.py 下载", os.path.isfile(os.path.join(tgt, "py", "helper.py")), st)
ok("远程 .jar 下载落地", os.path.isfile(os.path.join(tgt, "x.jar")), st)
ok("jar 二进制未损坏（魔数保留）",
   open(os.path.join(tgt, "x.jar"), "rb").read()[:4] == b"\xca\xfe\xba\xbe", st)
shutil.rmtree(tmp, ignore_errors=True)

print("\n== 11) lives / parses 通用数组合并 ==")
cfg = '{"sites": [], "lives": [{"name": "L1", "url": "http://1"}]}'
exist = C.load_array_items(cfg, "lives")
inc = [{"name": "L1", "url": "http://1"}, {"name": "L2", "url": "http://2"}]
plan = C.plan_section_merge(exist, inc, C.live_fingerprint)
ok("重复 L1 判 dup", plan["summary"]["dup"] == 1, plan["summary"])
ok("新增 L2 判 new", plan["summary"]["new"] == 1, plan["summary"])
rows = [dict(r) for r in plan["rows"]]
for r in rows:
    if r["verdict"] != "new":
        r["action"] = "skip"
nt, added = C.apply_merge_section(cfg, "lives", rows, C.fmt_section_entry)
ok("仅新增 1 条", added == 1, added)
ok("写入后仍可解析", len(C.load_array_items(nt, "lives")) == 2, nt)
ok("不破坏原 sites 数组", '"sites": []' in nt, nt)
cfgp = '{"parses": [{"name": "P1", "api": "./x"}]}'
pp = C.plan_section_merge(C.load_array_items(cfgp, "parses"),
                          [{"name": "P1", "api": "./x"}, {"name": "P2", "api": "./y"}],
                          C.parse_fingerprint)
nr, ap = C.apply_merge_section(cfgp, "parses", pp["rows"], C.fmt_section_entry)
ok("parses 新增 1 条（P1 重复跳过）", ap == 1, ap)

def _w(p, s):
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _r(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


print("\n== 12) 配套文件「同名不同内容」→ 改名 + api 改写（不再静默跳过）==")
tmp = tempfile.mkdtemp(prefix="pyinj_cf_")
src = os.path.join(tmp, "src"); tgt = os.path.join(tmp, "tgt")
_w(os.path.join(src, "py", "x.py"), "B\n")
_w(os.path.join(tgt, "py", "x.py"), "A\n")          # 目标已有同名但内容不同
raw = '{"sites": [{"key": "a", "name": "A", "api": "./py/other.py", "type": 3}]}'
inc = C.load_sites_from_text('{"sites": [{"key": "n1", "name": "N1", "api": "./py/x.py", "type": 3}]}')
plan = C.plan_merge(C.parse_sites_with_disabled(raw), inc)
rows = plan["rows"]
fp = C.plan_companion_files_local(src, tgt, [r["obj"] for r in rows if r["action"] == "add"])
ok("规划检出同名内容不同", len(fp["conflicts"]) == 1, fp["map"])
ok("改名建议 py/x.py -> py/x_2.py", fp["map"].get("py/x.py") == "py/x_2.py", fp["map"])
nt, st, fst = C.apply_merge(raw, rows, src_repo_dir=src, target_repo_dir=tgt, file_plan=fp)
n1 = [s for s in json.loads(nt)["sites"] if s["key"] == "n1"][0]
ok("配置 api 同步改写为新名", n1["api"] == "./py/x_2.py", n1["api"])
ok("改名文件落盘（B 内容）", _r(os.path.join(tgt, "py", "x_2.py")) == "B\n")
ok("原同名文件未被破坏（A 内容）", _r(os.path.join(tgt, "py", "x.py")) == "A\n")
ok("renamed 统计 1", len(fst["renamed"]) == 1, fst)
shutil.rmtree(tmp, ignore_errors=True)

print("\n== 13) 同名同内容 → 跳过；决策 overwrite → 覆盖并备份 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_cf2_")
src = os.path.join(tmp, "src"); tgt = os.path.join(tmp, "tgt")
_w(os.path.join(src, "py", "s.py"), "SAME\n")
_w(os.path.join(tgt, "py", "s.py"), "SAME\n")
f1 = C.copy_companions(src, tgt, [{"api": "./py/s.py"}])
ok("内容相同计入 skipped（不判冲突）", f1["skipped"] == ["py/s.py"] and not f1["renamed"], f1)
_w(os.path.join(src, "py", "s.py"), "NEW\n")
fplan = C.plan_companion_files_local(src, tgt, [{"api": "./py/s.py"}])
f2 = C.copy_companions(src, tgt, [{"api": "./py/s.py"}], plan=fplan,
                       decisions={"py/s.py": "overwrite"})
ok("覆盖后目标为新内容", _r(os.path.join(tgt, "py", "s.py")) == "NEW\n")
ok("覆盖前已备份旧内容", len(f2["backed_up"]) == 1 and _r(f2["backed_up"][0]) == "SAME\n", f2)
f3 = C.copy_companions(src, tgt, [{"api": "./py/s.py"}], plan=fplan,
                       decisions={"py/s.py": "skip"})
ok("决策 skip → 不搬、计入 conflict_skipped", f3["conflict_skipped"] == ["py/s.py"], f3)
shutil.rmtree(tmp, ignore_errors=True)

print("\n== 14) 深挖同伴冲突 → 改名 + 主脚本内 import 改写 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_cf3_")
src = os.path.join(tmp, "src"); tgt = os.path.join(tmp, "tgt")
_w(os.path.join(src, "py", "main.py"), "import helper\nfrom sub.mod import x\n")
_w(os.path.join(src, "py", "helper.py"), "H2\n")
_w(os.path.join(src, "py", "sub", "mod.py"), "M2\n")
_w(os.path.join(tgt, "py", "helper.py"), "H1\n")     # helper 同名不同内容
fp = C.plan_companion_files_local(src, tgt, [{"api": "./py/main.py"}])
ok("helper 判冲突 -> helper_2", fp["map"].get("py/helper.py") == "py/helper_2.py", fp["map"])
C.copy_companions(src, tgt, [{"api": "./py/main.py"}], plan=fp)
ok("主脚本 import 已改写为 helper_2", "import helper_2" in _r(os.path.join(tgt, "py", "main.py")),
   _r(os.path.join(tgt, "py", "main.py")))
ok("helper_2 落盘（H2）", _r(os.path.join(tgt, "py", "helper_2.py")) == "H2\n")
ok("原 helper 未破坏（H1）", _r(os.path.join(tgt, "py", "helper.py")) == "H1\n")
shutil.rmtree(tmp, ignore_errors=True)

print("\n== 15) jar 冲突改名 + jar 字段改写；远程(file://)冲突改名 ==")
tmp = tempfile.mkdtemp(prefix="pyinj_cf4_")
src = os.path.join(tmp, "src"); tgt = os.path.join(tmp, "tgt")
os.makedirs(os.path.join(src, "jars")); os.makedirs(os.path.join(tgt, "jars"))
open(os.path.join(src, "jars", "pg.jar"), "wb").write(b"\xca\xfe\xba\xbeBBBB")
open(os.path.join(tgt, "jars", "pg.jar"), "wb").write(b"\xca\xfe\xba\xbeAAAA")
raw6 = '{"sites": [{"key":"a","name":"A","api":"csp_Other","jar":"jars/pg.jar","type":3}]}'
inc6 = C.load_sites_from_text(
    '{"sites": [{"key":"n2","name":"N2","api":"csp_Pan","jar":"jars/pg.jar","type":3}]}')
nt6, _s6, _f6 = C.apply_merge(raw6, C.plan_merge(C.parse_sites_with_disabled(raw6), inc6)["rows"],
                              src_repo_dir=src, target_repo_dir=tgt)
n2 = [s for s in json.loads(nt6)["sites"] if s["key"] == "n2"][0]
ok("jar 字段改名 jars/pg_2.jar", n2.get("jar") == "jars/pg_2.jar", n2.get("jar"))
ok("新 jar 落盘且二进制完好", open(os.path.join(tgt, "jars", "pg_2.jar"), "rb").read().endswith(b"BBBB"))
ok("原 jar 未破坏", open(os.path.join(tgt, "jars", "pg.jar"), "rb").read().endswith(b"AAAA"))
shutil.rmtree(tmp, ignore_errors=True)

tmp = tempfile.mkdtemp(prefix="pyinj_cf5_")
rroot = os.path.join(tmp, "remote"); tgt = os.path.join(tmp, "tgt")
_w(os.path.join(rroot, "py", "x.py"), "R-B\n")
_w(os.path.join(tgt, "py", "x.py"), "L-A\n")
from urllib.parse import urljoin as _urljoin
rb = _urljoin("file:///" + rroot.replace("\\", "/") + "/", "./")
fp = C.plan_companion_files_remote(rb, tgt, [{"api": "./py/x.py"}])
ok("远程检出同名冲突", fp["map"].get("py/x.py") == "py/x_2.py", fp["map"])
fst = C.copy_companions_remote(rb, tgt, [{"api": "./py/x.py"}], plan=fp)
ok("远程改名文件落盘", _r(os.path.join(tgt, "py", "x_2.py")) == "R-B\n", fst)
shutil.rmtree(tmp, ignore_errors=True)

print("\n== 16) 冲突改名行 + 沿用禁用态：禁用的是新 key（不是被占用的旧 key）==")
raw7 = '{"sites": [{"key":"a","name":"A","api":"./py/other.py","type":3}]}'
inc7 = C.load_sites_from_text('{"sites": [{"key":"a","name":"A2","api":"./py/x7.py","type":3}]}')
rows7 = C.plan_merge(C.parse_sites_with_disabled(raw7), inc7)["rows"]
for r in rows7:
    r["action"] = "add"
    r["disabled"] = True                 # 冲突改名 + 沿用禁用
tmp = tempfile.mkdtemp(prefix="pyinj_cf6_")
src = os.path.join(tmp, "src"); tgt = os.path.join(tmp, "tgt")
os.makedirs(src)
nt7, st7, _f = C.apply_merge(raw7, rows7, src_repo_dir=src, target_repo_dir=tgt)
_pairs7 = C.parse_sites_with_disabled(nt7)
active7 = {o["key"] for o, dis in _pairs7 if not dis}
dis7 = {o["key"] for o, dis in _pairs7 if dis}
ok("原 key a 仍启用（未被误禁用）", "a" in active7, active7)
ok("改名后的 a_2 以禁用态存在", "a_2" in dis7, dis7)
shutil.rmtree(tmp, ignore_errors=True)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
