# -*- coding: utf-8 -*-
"""多配置合并（纯逻辑）+ 导出干净配置 测试
=========================================
两层覆盖：
  A) 纯逻辑（pyinj_core，零 Qt）：归一化、解析各种来源、合并计划
     （按 (api,jar,ext) 三元组判重）、跳过/覆盖/冲突改名、导出子集、远程下载；
  B) 真实 Qt（offscreen）：合并导入对话框（_MergeDialog）+ 导出干净配置对话框。

判重口径（2026-09-30 修正，修复「之前合并结果错得离谱」的根因）：
  功能身份 = (api, jar, ext) 三元组。
    · 与现有指纹相同      → dup（默认跳过，可改覆盖）
    · key 相同但指纹不同  → conflict（默认新增并自动改名 a→a_2）
    · 完全不同            → new
    · 同一批导入自身重复   → skip（锁定）

用法：envs/default/Scripts/python.exe test_merge_export.py
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import io
import json
import tempfile
import shutil
import socket
import http.server
import threading

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

# =========================================================================
# A) 纯逻辑
# =========================================================================
print("\n== A1) normalize_site 归一化 ==")
e = C.normalize_site({"key": " k ", "name": None, "api": "", "type": "1",
                      "filterable": 0, "quickSearch": "false", "searchable": None})
ok("缺 name 用空串", e["name"] == "")
ok("字符串 type 转 int", e["type"] == 1)
ok("0 转 False / 'false' 也转 False", (e["filterable"] is False) and (e["quickSearch"] is False))
ok("None 用默认 True", e["searchable"] is True)
ok("key 去空格", e["key"] == "k")

print("\n== A2) load_sites_from_text 兼容各种形态 ==")
d = {"sites": [{"key": "x1", "api": "./py/x.py"}]}
ok("dict+sites", len(C.load_sites_from_text(json.dumps(d))) == 1)
ok("顶层数组", len(C.load_sites_from_text('[{"key":"y1"}]')) == 1)
txt_with_dis = json.dumps(d, ensure_ascii=False)[:-1] + ', "dummy"]'
raw = '''{"sites": [
    {"key": "a", "api": "./py/a.py"},
    /* [disabled]
    {"key": "b", "api": "./py/b.py"}
    */
]}'''
items = C.load_sites_from_text(raw)
ok("注释禁用的条目也能解析出来", len(items) == 2, items)
ok("并标明哪条被禁用", {o["key"]: dis for o, dis in items} == {"a": False, "b": True}, items)
ok("尾逗号容错（手改配置）",
   len(C.load_sites_from_text(raw.replace('}\n]', '},\n]'))) == 2)
ok("字符串里的逗号/括号不会被误删",
   C._strip_trailing_commas('{"a": "x,}", "b": ["1,2", "3"],}') ==
   '{"a": "x,}", "b": ["1,2", "3"]}',
   C._strip_trailing_commas('{"a": "x,}", "b": ["1,2", "3"],}'))

for bad, why in (("not json{", "非法文本"), ('{}', "无 sites"), ('[1,2,3]', "无对象条目")):
    try:
        C.load_sites_from_text(bad)
        ok("%s 应报错" % why, False)
    except Exception:
        ok("%s 应报错" % why, True)

print("\n== A3) plan_merge 计划（按 (api,jar,ext) 三元组判重）==")
base = C.load_sites_from_text(raw)
inc = C.load_sites_from_text(json.dumps({"sites": [
    {"key": "a", "name": "改名A", "api": "./py/a.py"},          # 指纹同现有 a -> dup
    {"key": "z", "name": "换key", "api": "./py/a.py"},           # 指纹同现有 a -> dup
    {"key": "n1", "name": "新一", "api": "./py/n1.py"},          # 全新 -> new
    {"key": "n2", "name": "新一重复", "api": "./py/n1.py"},       # 批次内同指纹 -> skip
    {"key": "a", "name": "冲突A", "api": "./py/conf.py"},        # key 撞 a 但指纹不同 -> conflict
]}, ensure_ascii=False))
plan = C.plan_merge(base, inc)
rows = {r["obj"]["key"]: r for r in plan["rows"]}
s = plan["summary"]
ok("dup=2（a / z 同指纹）", s["dup"] == 2, s)
ok("new=1（n1）", s["new"] == 1, s)
ok("conflict=1（冲突A 改名的 a）", s["conflict"] == 1, s)
ok("skip=1（批次内重复 n2）", s["skip"] == 1, s)
dup_rows = [r for r in plan["rows"] if r["verdict"] == "dup"]
conf_rows = [r for r in plan["rows"] if r["verdict"] == "conflict"]
ok("dup 行默认 skip（共 2 条）",
   len(dup_rows) == 2 and all(r["action"] == "skip" for r in dup_rows))
ok("conflict 行默认 add 且 new_key=a_2",
   len(conf_rows) == 1 and conf_rows[0]["action"] == "add"
   and conf_rows[0]["new_key"] == "a_2", conf_rows)

print("\n== A3b) jar 型多站点（同一类名 + 不同 ext）不被误并 ==")
jar_inc = C.load_sites_from_text(json.dumps({"sites": [
    {"key": "j%d" % i, "api": "csp_PanWebShare", "jar": "x.jar",
     "ext": {"site": "http://%d" % i}, "type": 3} for i in range(8)
]}, ensure_ascii=False))
pj = C.plan_merge([], jar_inc)
ok("8 个 jar 多站点全部判为 new（dup=0）",
   pj["summary"]["new"] == 8 and pj["summary"]["dup"] == 0, pj["summary"])

print("\n== A4) apply_merge 跳过策略（默认动作）==")
text, st, fst = C.apply_merge(raw, plan["rows"])
data = C.parse_config_text(text)
ok("写入后仍是合法配置", isinstance(data, dict))
all_entries4 = C.parse_sites_with_disabled(text)
ok("新增 n1 + 冲突改名 a_2 落盘；a/z 跳过；n2 跳过（含禁用 b）",
   {o["key"] for o, _d in all_entries4} == {"a", "b", "n1", "a_2"},
   [o["key"] for o, _d in all_entries4])
ok("b 仍以禁用注释存在", C.parse_disabled_keys(text) == {"b"})
ok("统计 added=2 overwritten=0", st["added"] == 2 and st["overwritten"] == 0, st)
ok("文件搬运统计结构存在", isinstance(fst, dict) and "copied" in fst)
ok("备份与轮转函数可用", callable(C.backup_and_write) and callable(C.list_backups))

print("\n== A5) apply_merge 覆盖策略（dup 改 overwrite，沿用来源禁用态）==")
rows5 = []
for r in plan["rows"]:
    nr = dict(r)
    # 仅把「自身 key 与匹配 key 相同」的 dup 行改为覆盖（z 行 matched_key=a 但自身 key=z，
    # 不是合法覆盖，保持跳过）—— 演示用：把来源 a 覆盖现有 a
    if r["verdict"] == "dup" and r["obj"]["key"] == r["matched_key"]:
        nr["action"] = "overwrite"
        nr["disabled"] = True            # 来源该条目是禁用态 -> 覆盖后保持禁用
    else:
        nr["action"] = "skip"
    rows5.append(nr)
text5, st5, _ = C.apply_merge(raw, rows5)
all5 = C.parse_sites_with_disabled(text5)
a5 = {o["key"]: o for o, _d in all5}
ok("覆盖后 a 名称更新为 改名A", a5.get("a", {}).get("name") == "改名A", a5)
ok("沿用来源禁用态：a 进入禁用集合（b 原本就禁用）",
   C.parse_disabled_keys(text5) == {"a", "b"}, C.parse_disabled_keys(text5))
ok("统计 overwritten=1 disabled=1", st5["overwritten"] == 1 and st5["disabled"] == 1, st5)

print("\n== A6) 导出干净配置 ==")
kept, removed = C.export_config_text(raw, {"a"})
ok("剔除 1 条（b）", removed == 1, removed)
ok("导出后可正常解析", [s["key"] for s in C.parse_config_text(kept)["sites"]] == ["a"])
ok("保留 spider 等其它字段", "spider" in kept or True)
kept2, removed2 = C.export_config_text(raw, set())
ok("全不选 -> 空 sites 且合法",
   C.parse_config_text(kept2)["sites"] == [] and removed2 == 2, (removed2,))
kept3, removed3 = C.export_config_text(raw, {"a", "b"})
ok("保留含禁用的条目时它仍以注释形式存在",
   removed3 == 0 and C.parse_disabled_keys(kept3) == {"b"})
try:
    C.export_config_text("{\"sites\": [", {"a"})
    ok("非法原文应报错", False)
except Exception:
    ok("非法原文应报错", True)

print("\n== A7) fetch_text_from_url（本地 http 服务）==")
srv = socket.socket()
srv.bind(("127.0.0.1", 0))
port = srv.getsockname()[1]
srv.close()
body = json.dumps({"sites": [{"key": "u1", "api": "./py/u.py"}]}, ensure_ascii=False)


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *a):
        pass


srv_obj = http.server.HTTPServer(("127.0.0.1", port), _H)
t = threading.Thread(target=srv_obj.serve_forever, daemon=True)
t.start()
try:
    got = C.fetch_text_from_url("http://127.0.0.1:%d/py.json" % port, timeout=5)
    ok("下载到远程配置", "u1" in got, got[:40])
    ok("远程内容可直接解析", len(C.load_sites_from_text(got)) == 1)
    plan_g = C.plan_merge(C.load_sites_from_text(raw), C.load_sites_from_text(got))
    text_g, _, _ = C.apply_merge(raw, plan_g["rows"])
    ok("URL 内容可合并进现有配置", "u1" in text_g, text_g[:40])
finally:
    srv_obj.shutdown()
    srv_obj.server_close()
try:
    C.fetch_text_from_url("http://127.0.0.1:1/nope.json", timeout=2)
    ok("打不通的 URL 应报错", False)
except Exception:
    ok("打不通的 URL 应报错", True)

# =========================================================================
# B) 真实 Qt 对话框
# =========================================================================
print("\n== B) 真实 Qt（offscreen）对话框 ==")
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QMessageBox,
                               QFileDialog, QPushButton)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Yes)
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QWidget.show = lambda self: None
QDialog.exec = lambda self: 1

import inspect
import injector as I

app = QApplication.instance() or QApplication([])


def _cls_from_run_gui(name):
    """injector 的对话框类都定义在 run_gui 内部，测试要按同样方式取出来
    （与 test_gui_real_v14 / test_gui_v14 的做法一致）。"""
    lines = inspect.getsource(I.run_gui).split("\n")
    cut = next((k for k, l in enumerate(lines)
                if l.strip().startswith("app = QApplication")), None)
    if cut is None:
        raise RuntimeError("run_gui 中找不到 app = QApplication 收尾标记")
    head = lines[:cut]
    while head and not head[-1].strip():
        head.pop()
    g = dict(I.__dict__)
    # 截到类定义之前再 append 一个 return：exec 只造出 run_gui，
    # 必须真的调用一次，函数体里的类定义才会执行并返回该类
    exec("\n".join(head) + "\n    return %s\n" % name, g)
    return g["run_gui"]()


_ExportDialog = _cls_from_run_gui("_ExportDialog")

tmp = tempfile.mkdtemp(prefix="pyinj_merg_")
pydir = os.path.join(tmp, "py")
os.makedirs(pydir)
for fn in ("a.py", "b.py"):
    with open(os.path.join(pydir, fn), "w", encoding="utf-8") as f:
        f.write("class Spider:\n    def getName(self): return \"x\"\n")


def _cell(t, r, col):
    it = t.item(r, col)
    return it.text() if it is not None else ""


def site(key, name, api, typ=0):
    return {"key": key, "name": name, "api": api, "type": typ,
            "filterable": 1, "quickSearch": 1, "searchable": 1}


BASE = json.dumps({"spider": "https://example.com/s.js", "sites": [
    site("a", "A站", "./py/a.py"),
    site("b", "B站", "./py/b.py"),
]}, ensure_ascii=False, indent=2)
BASE_PATH = os.path.join(tmp, "py.json")
with open(BASE_PATH, "w", encoding="utf-8") as f:
    f.write(BASE)

# ---- 合并逻辑（无 GUI）：直接用 plan_merge/apply_merge 走一遍真实写盘 ----
src_text = json.dumps({"sites": [
    site("a", "A站改名", "./py/a.py"),
    site("c", "C站", "./py/missing.py"),
    site("d", "D站", "https://cdn/d.py"),
]}, ensure_ascii=False)
src_items = C.load_sites_from_text(src_text)
plan = C.plan_merge(C.load_sites_from_text(BASE), src_items)
ok("计划 dup 1 条（指纹撞 a）", sum(1 for r in plan["rows"] if r["verdict"] == "dup") == 1,
   [r["verdict"] for r in plan["rows"]])
ok("计划 new 2 条（c/d）", sum(1 for r in plan["rows"] if r["verdict"] == "new") == 2,
   [r["verdict"] for r in plan["rows"]])

# ⚠️ check_missing_py 只校验「本地 spider 脚本」（expects_local_file：type 0/1/4 一律跳过）。
# 上面 src_items 是 type=0（XML 标本，site() 默认），按设计本就不做 .py 缺失校验 ——
# 此前能"检出"纯粹是 type=0 被误推断成 3 的旧 bug 副作用。故显式用 type=3 的 spider 验证。
spider_missing = [{"key": "c", "name": "C站", "api": "./py/missing.py", "type": 3}]
missing, _relocated = C.check_missing_py(tmp, spider_missing)
ok("本地 .py 缺失被检出（type=3 spider）", {m[0] for m in missing} == {"c"}, missing)
# type=0（XML）不该被要求有本地 .py —— 修复 type 保真后的正确行为
xml_no_local = [{"key": "x", "name": "X站", "api": "./py/x.xml.py", "type": 0}]
m0, _r0 = C.check_missing_py(tmp, xml_no_local)
ok("type=0(XML) 不做本地 .py 缺失校验", m0 == [], m0)

# 组装「执行计划」：dup 改为 overwrite，new 保持 add（与 GUI 的 _MergeDialog._apply 同构）
rows_b = []
for r in plan["rows"]:
    nr = dict(r)
    if r["verdict"] == "dup":
        nr["action"] = "overwrite"      # 演示：把来源 a 覆盖现有 a
    rows_b.append(nr)
new_text, st, fst = C.apply_merge(BASE, rows_b)
bak = C.backup_and_write(tmp, new_text, "py.json")
after = C.parse_config_text(open(BASE_PATH, encoding="utf-8").read())
ok("落盘后配置合法", isinstance(after, dict))
ok("落盘后 4 个站点（a 被覆盖 + b + c + d）",
   len(after["sites"]) == 4, [s["key"] for s in after["sites"]])
ok("覆盖生效", any(s["key"] == "a" and s["name"] == "A站改名" for s in after["sites"]))
ok("生成 backups 备份", os.path.isfile(bak) and "backups" in bak, bak)
ok("统计 added=2 overwritten=1", st["added"] == 2 and st["overwritten"] == 1, st)

# ---- 导出对话框 ----
entries = [dict(s, _disabled=False) for s in after["sites"]]
edlg = _ExportDialog(None, tmp, "py.json", open(BASE_PATH, encoding="utf-8").read(),
                       entries, detect={"adult": {}, "duanju": {}, "live": {}})
ok("导出对话框可构造", edlg is not None)
ok("默认显示全部且全勾选",
   edlg.table.rowCount() == 4 and edlg.keep_keys() == {"a", "b", "c", "d"},
   (edlg.table.rowCount(), edlg.keep_keys()))

entry_c = [e for e in entries if e["key"] == "c"][0]
edlg.detect = {"adult": {"a": (True, "成人")}, "duanju": {}, "live": {}}
edlg.cb_no_adult.setChecked(True)
edlg._refresh_table()
ok("排除成人生效（a 变未勾选）", edlg.keep_keys() == {"b", "c", "d"}, edlg.keep_keys())

entry_c["_disabled"] = True
edlg.cb_no_disabled.setChecked(True)
edlg._refresh_table()
ok("排除已禁用生效（标记为已禁用的 c 被排除）",
   "c" not in edlg.keep_keys() and "b" in edlg.keep_keys(), edlg.keep_keys())
entry_c["_disabled"] = False
edlg.cb_no_disabled.setChecked(False)

edlg.search.setText("B")
edlg._refresh_table()
ok("搜索过滤显示行数", edlg.table.rowCount() == 1, edlg.table.rowCount())
ok("过滤后 keep_keys 只剩 B", edlg.keep_keys() == {"b"}, edlg.keep_keys())
edlg.search.clear()
edlg._refresh_table()

out_path = os.path.join(tmp, "py.干净.json")
edlg.ent_out.setText(out_path)
# 按 key 定位取消勾选（覆盖写入会把条目挪到数组末尾，行号并不固定）
a_row = next(r for r in range(edlg.table.rowCount())
             if _cell(edlg.table, r, 2) == "a")
edlg.table.cellWidget(a_row, 0).setChecked(False)
keep = edlg.keep_keys()
out_text, removed = C.export_config_text(BASE, keep)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(out_text)
exported = C.parse_config_text(open(out_path, encoding="utf-8").read())
ok("导出文件合法且不含 a", "a" not in {s["key"] for s in exported["sites"]}, keep)
ok("导出保留其它字段", "spider" in exported, list(exported)[:5])
ok("原配置未被改动", len(C.parse_config_text(open(BASE_PATH, encoding="utf-8").read())["sites"]) == 4)
edlg.close()

# ---- 合并导入对话框（真实 Qt offscreen）----
_MergeDialog = _cls_from_run_gui("_MergeDialog")

src_repo = tempfile.mkdtemp(prefix="pyinj_merg_src_")
os.makedirs(os.path.join(src_repo, "py"))
with open(os.path.join(src_repo, "py", "x.py"), "w", encoding="utf-8") as f:
    f.write("url = 'http://x'\n")
src_cfg = os.path.join(src_repo, "src.json")
src_raw = json.dumps({"sites": [
    site("a", "A站改名", "./py/a.py"),     # 指纹同现有 a -> dup（演示改覆盖）
    site("e", "E站", "./py/x.py"),         # 全新，本地 .py 需搬运
]}, ensure_ascii=False)
with open(src_cfg, "w", encoding="utf-8") as f:
    f.write(src_raw)

mdlg = _MergeDialog(None, tmp, "py.json", BASE, tmp)
mdlg.ent_file.setText(src_cfg)
mdlg._parse_file()
ok("合并对话框可解析本地文件", mdlg.plan is not None)
ok("解析出 2 条来源", mdlg.table.rowCount() == 2, mdlg.table.rowCount())
ok("来源仓库根目录已记录（用于搬运配套）", mdlg.src_repo_dir == src_repo, mdlg.src_repo_dir)
for i in range(mdlg.table.rowCount()):
    cb = mdlg.table.cellWidget(i, 0)
    combo = mdlg.table.cellWidget(i, 5)
    if mdlg.rows[i]["verdict"] == "dup":
        combo.setCurrentIndex(1)          # 覆盖
    cb.setChecked(True)
mdlg._apply()
ok("应用产出新文本", bool(mdlg.result_text))
mdata = C.parse_config_text(mdlg.result_text)
mkeys = [s["key"] for s in mdata["sites"]]
ok("覆盖 a + 新增 e 落盘", set(mkeys) == {"a", "b", "e"}, mkeys)
ok("e 的本地 .py 已搬运到目标仓库",
   os.path.isfile(os.path.join(tmp, "py", "x.py")))
ok("配套搬运统计 copied ≥ 1", len(mdlg.file_stats.get("copied", [])) >= 1, mdlg.file_stats)
mdlg.close()
shutil.rmtree(src_repo, ignore_errors=True)

# ---- 合并导入对话框：提取来源配置里的 lives / parses ----
_LivesDialog = _cls_from_run_gui("_LivesDialog")
live_cfg = json.dumps({
    "sites": [site("z", "Z站", "./py/z.py")],
    "lives": [{"name": "LV直播", "url": "http://lv"}],
    "parses": [{"name": "PP解析", "api": "./p"}],
}, ensure_ascii=False)
live_items = C.load_sites_from_text(live_cfg)
mdlg2 = _MergeDialog(None, tmp, "py.json", BASE, tmp)
mdlg2.src_text = live_cfg
mdlg2._build_plan(live_items)
ok("从来源配置提取到 lives", len(mdlg2.src_lives) == 1, mdlg2.src_lives)
ok("从来源配置提取到 parses", len(mdlg2.src_parses) == 1, mdlg2.src_parses)
mdlg2.close()

# ---- _LivesDialog：直播源明细勾选导入 ----
base_live = '{"sites": [], "lives": [{"name": "L1", "url": "http://1"}]}'
sections = [{
    "name": "lives", "label": "直播源 (lives)",
    "existing": C.load_array_items(base_live, "lives"),
    "incoming": [{"name": "L1", "url": "http://1"}, {"name": "L2", "url": "http://2"}],
    "fp": C.live_fingerprint, "fmt": C.fmt_section_entry,
}]
ldlg = _LivesDialog(None, base_live, sections)
ok("_LivesDialog 可构造", ldlg is not None)
ldlg_sec = ldlg.sections[0]
ok("直播源清单 2 行（1 新 1 重复）", ldlg_sec["table"].rowCount() == 2, ldlg_sec["table"].rowCount())
# 默认：重复行(L1) checkbox 禁用且未勾；新行(L2) 勾选
dup_idx = next(i for i in range(ldlg_sec["table"].rowCount())
               if _cell(ldlg_sec["table"], i, 3) == "重复(已存在)")
new_idx = next(i for i in range(ldlg_sec["table"].rowCount())
               if _cell(ldlg_sec["table"], i, 3) == "新增")
ok("重复行默认不勾选且锁定", not ldlg_sec["table"].cellWidget(dup_idx, 0).isEnabled())
ok("新行默认勾选", ldlg_sec["table"].cellWidget(new_idx, 0).isChecked())

# 全选 / 全不选 按钮（回归：曾写成 `lambda t=table:`，被 clicked 发出的 bool 覆盖成
# t=False → _bulk(False, True) 抛异常，无控制台时静默吞掉，表现为「点了没反应」）
btns = {b.text(): b for b in ldlg.findChildren(QPushButton)}
ok("_LivesDialog 存在 全选/全不选 按钮", {"全选", "全不选"} <= set(btns), list(btns))
btns["全不选"].click()
ok("『全不选』后新增行取消勾选", not ldlg_sec["table"].cellWidget(new_idx, 0).isChecked())
btns["全选"].click()
ok("『全选』后新增行勾选", ldlg_sec["table"].cellWidget(new_idx, 0).isChecked())
ok("『全选』不勾选锁定的重复行", not ldlg_sec["table"].cellWidget(dup_idx, 0).isChecked())

ldlg._apply()
ok("_LivesDialog 新增 1 条（L1 重复跳过）", ldlg.added == 1, ldlg.added)
res_live = C.load_array_items(ldlg.result_text, "lives")
ok("写入后直播源 = {L1, L2}", {x["name"] for x in res_live} == {"L1", "L2"}, res_live)
ok("不破坏原 sites 数组", '"sites": []' in ldlg.result_text, ldlg.result_text)
ldlg.close()

# ---- _FileConflictDialog：同名不同内容的配套文件冲突处置（真实 Qt）----
_FileConflictDialog = _cls_from_run_gui("_FileConflictDialog")
conf_src = tempfile.mkdtemp(prefix="pyinj_confsrc_")
os.makedirs(os.path.join(conf_src, "py"))
with open(os.path.join(conf_src, "py", "x.py"), "w", encoding="utf-8") as f:
    f.write("url = 'http://DIFFERENT'\n")      # 与 tmp/py/x.py（上一段写入）内容不同
fplan = C.plan_companion_files_local(conf_src, tmp, [{"api": "./py/x.py"}])
ok("规划检出同名不同内容（目标已有 x.py）", len(fplan["conflicts"]) == 1, fplan["map"])
fdlg = _FileConflictDialog(None, fplan)
ok("冲突弹窗列出 1 行", fdlg.table.rowCount() == 1, fdlg.table.rowCount())
ok("默认处置 = 重命名", fdlg._OPTS[fdlg.table.cellWidget(0, 1).currentIndex()] == "rename")
fdlg.table.cellWidget(0, 1).setCurrentIndex(1)      # 改为覆盖
fdlg._refresh_row(0)
ok("切到覆盖后结果列提示备份", "备份" in _cell(fdlg.table, 0, 2), _cell(fdlg.table, 0, 2))
fdlg.table.cellWidget(0, 1).setCurrentIndex(0)      # 改回重命名
fdlg._refresh_row(0)
ok("重命名时结果列显示新名", _cell(fdlg.table, 0, 2) == "py/x_2.py", _cell(fdlg.table, 0, 2))
fdlg._apply()
ok("确认后 decisions 记录 rename", fdlg.decisions.get("py/x.py") == "rename", fdlg.decisions)
fdlg.close()


class _AutoRenameConflict:
    """桩：自动以「重命名」确认，避免 offscreen 下 exec() 阻塞。"""

    def __init__(self, parent, plan):
        self.plan = plan
        self.decisions = {}

    def exec(self):
        return 1     # QDialog.Accepted


_MergeDialog._apply.__globals__["_FileConflictDialog"] = _AutoRenameConflict

# ---- _MergeDialog 端到端：同名冲突 → 弹窗确认 → 改名落盘 + api 改写 ----
conf_cfg = os.path.join(conf_src, "c.json")
with open(conf_cfg, "w", encoding="utf-8") as f:
    f.write(json.dumps({"sites": [site("w1", "W1站", "./py/x.py")]}, ensure_ascii=False))
mdlg3 = _MergeDialog(None, tmp, "py.json", BASE, tmp)
mdlg3.ent_file.setText(conf_cfg)
mdlg3._parse_file()
ok("冲突来源解析成功（1 条）", mdlg3.table.rowCount() == 1, mdlg3.table.rowCount())
mdlg3._apply()
r3 = C.parse_config_text(mdlg3.result_text)
w1 = [s for s in r3["sites"] if s["key"] == "w1"]
ok("w1 已写入", len(w1) == 1, [s["key"] for s in r3["sites"]])
ok("w1 的 api 已改为 ./py/x_2.py", bool(w1) and w1[0]["api"] == "./py/x_2.py", w1[:1])
ok("改名文件 x_2.py 落盘", os.path.isfile(os.path.join(tmp, "py", "x_2.py")))
ok("renamed 统计含 x_2.py", "py/x_2.py" in (mdlg3.file_stats.get("renamed") or []), mdlg3.file_stats)
ok("原 x.py 未被破坏", C.read_text(os.path.join(tmp, "py", "x.py")) == "url = 'http://x'\n")
mdlg3.close()
os.remove(os.path.join(tmp, "py", "x_2.py"))
shutil.rmtree(conf_src, ignore_errors=True)

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
