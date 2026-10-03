# -*- coding: utf-8 -*-
"""「禁用短剧」按钮 offscreen GUI 测试（真实 Qt）：
- 检测完成后短剧列标橙「是(检)」
- 点「禁用短剧」批量注释禁用（确认框自动 Yes），禁用列变「是」
- 未检测时点击给出提示、不改文件
（列号：key 列已移除，短剧列=5，禁用列=8）
"""
import io
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def ok(cond, name, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


tmp = tempfile.mkdtemp()
py_dir = os.path.join(tmp, "py")
os.makedirs(py_dir)
with open(os.path.join(py_dir, "dj.py"), "w", encoding="utf-8") as f:
    f.write("# 短剧源\nclass Spider: pass\n")
with open(os.path.join(py_dir, "dj2.py"), "w", encoding="utf-8") as f:
    f.write("cates=['微短剧','电影']\n")
with open(os.path.join(py_dir, "mv.py"), "w", encoding="utf-8") as f:
    f.write("# 电影电视剧\nclass Spider: pass\n")

RAW = """{
"sites": [
{"key":"py_dj","name":"快看短剧","api":"./py/dj.py","type":3,"filterable":1,"quickSearch":1,"searchable":1},
{"key":"py_dj2","name":"星辰剧场","api":"./py/dj2.py","type":3,"filterable":1,"quickSearch":1,"searchable":1},
{"key":"py_mv","name":"好看电影","api":"./py/mv.py","type":3,"filterable":1,"quickSearch":1,"searchable":1}
]}
"""

import injector as I
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
import inspect
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
src2 = src[:idx] + "    return ConfigDialog\n"
g = dict(I.__dict__)
exec(src2, g)
ConfigDialog = g["run_gui"]()

import json as _json
sites_active = _json.loads(RAW)["sites"]
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(RAW)

print("== 构造 ConfigDialog（不自动内容检测）==")
dlg = ConfigDialog(None, tmp, RAW, sites_active, "py.json", tmp)
ok({dlg.table.item(r, 5).text() for r in range(dlg.table.rowCount())} == {"未检测"},
   "短剧列默认「未检测」")

# 未检测时点「禁用短剧」-> 只提示，不改文件
print("== 未检测时点击「禁用短剧」==")
raw_before = dlg.raw
answers = {"n": 0}
orig_info = QMessageBox.information
orig_q = QMessageBox.question


def fake_info(*a, **kw):
    answers["n"] += 1
    return QMessageBox.Ok


def fake_q(*a, **kw):
    return QMessageBox.Yes


QMessageBox.information = staticmethod(fake_info)
QMessageBox.question = staticmethod(fake_q)
try:
    dlg.disable_duanju()
    app.processEvents()
    ok(answers["n"] == 1, "弹出提示（引导先检测）", str(answers))
    ok(dlg.raw == raw_before, "未改动配置")
    ok({dlg.table.item(r, 8).text() for r in range(dlg.table.rowCount())} == {"否"},
       "禁用列仍全「否」")

    # 启动成人/短剧检测并等完成
    print("== 启动检测 ==")
    dlg._start_adult()
    deadline = time.time() + 60
    while time.time() < deadline:
        app.processEvents()
        if not dlg._scanning:
            break
        time.sleep(0.03)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    ok(dlg._scanning is False, "检测完成")
    ok("短剧" in dlg.prog_label.text(), "汇总含短剧统计", dlg.prog_label.text())
    ok(dlg.duanju_map.get("py_dj", (False,))[0] and dlg.duanju_map.get("py_dj2", (False,))[0],
       "duanju_map 命中 py_dj / py_dj2", str(dlg.duanju_map))
    ok(not dlg.duanju_map.get("py_mv", (False,))[0], "duanju_map 未命中 py_mv")
    col_dj = [dlg.table.item(r, 5).text() for r in range(dlg.table.rowCount())]
    ok(col_dj == ["是(检)", "是(检)", "否"], "短剧列文本 是/是/否", str(col_dj))
    c0 = dlg.table.item(0, 5).foreground().color().getRgb()[:3]
    ok(c0 == (200, 130, 20), "短剧命中标橙", str(c0))

    # 点「禁用短剧」-> 自动 Yes，批量禁用
    print("== 检测后点击「禁用短剧」==")
    dlg.disable_duanju()
    app.processEvents()
    col_dis = [dlg.table.item(r, 8).text() for r in range(dlg.table.rowCount())]
    ok(col_dis == ["是", "是", "否"], "两个短剧站已禁用", str(col_dis))
    ok(dlg.raw.count("[disabled]") == 2, "[disabled] 标记出现 2 处", str(dlg.raw.count("[disabled]")))
    ok(any(fn.startswith("py.json.") for fn in os.listdir(os.path.join(tmp, "backups"))) if os.path.isdir(os.path.join(tmp, "backups")) else False, "生成备份（backups/ 目录）")
    ok(len(I.parse_jsonc(dlg.raw).get("sites", [])) == 1,
       "配置仍 JSON 合法（启用项可解析）")

    # 再次点击 -> 已禁用，提示无可禁用
    n_before = answers["n"]
    dlg.disable_duanju()
    app.processEvents()
    ok(answers["n"] == n_before + 1, "重复禁用幂等（仅提示）")
finally:
    QMessageBox.information = orig_info
    QMessageBox.question = orig_q

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
