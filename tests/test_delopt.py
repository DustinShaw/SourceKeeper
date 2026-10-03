# -*- coding: utf-8 -*-
"""v14.2 删除可选删 .py 测试（v2026.09.25.e 起默认勾选）：
GUI：del_row 复选框默认勾选=连 .py 删（备份 py_trash/）；取消勾选=只删配置项保留 .py。
CLI：--del 默认连 .py 删；--del --keep-py 只删配置项保留 .py。
真实 PySide6 offscreen 运行（envs/default/Scripts/python.exe）。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import io
import inspect
import tempfile
import shutil
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import injector as I

PASS, FAIL = 0, 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, extra))

from PySide6.QtWidgets import QApplication, QMessageBox, QDialog

# 全部弹框放行，不阻塞
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QDialog.accept = lambda self: None
QDialog.exec = lambda self: 1

# ---- 取出 ConfigDialog（真实 Qt）----
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
src2 = src[:idx] + "    return ConfigDialog\n"
g = dict(I.__dict__)
exec(src2, g)
ConfigDialog = g["run_gui"]()

app = QApplication.instance() or QApplication(sys.argv)

RAW = '''{
  "spider": "x",
  "sites": [
    {"key": "k1", "name": "One", "api": "./py/a.py", "type": 3},
    {"key": "k2", "name": "Two", "api": "./py/b.py", "type": 3}
  ]
}'''


def make_repo():
    tmp = tempfile.mkdtemp(prefix="pyinj_delopt_")
    pydir = os.path.join(tmp, "py")
    os.makedirs(pydir)
    for f in ("a.py", "b.py"):
        with open(os.path.join(pydir, f), "w", encoding="utf-8") as fh:
            fh.write("class Spider:\n    name='%s'\n" % f)
    with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as fh:
        fh.write(RAW)
    return tmp


print("== GUI：del_row 复选框 ==")
tmp = make_repo()
sites = I.parse_jsonc(RAW).get("sites", [])
dlg = ConfigDialog(None, tmp, RAW, list(sites), "py.json", tmp)
# 等后台线程收尾（不必要但保险）
for _ in range(10):
    app.processEvents()

# 1) 默认勾选 → 连 .py 删（备份 py_trash/）
dlg.table.selectRow(0)
orig_exec = QMessageBox.exec
QMessageBox.exec = lambda self: QMessageBox.Yes
dlg.del_row()
ok("k1 进入 removed_keys", "k1" in dlg.removed_keys)
ok("k1 默认勾选删 .py", "k1" in dlg.removed_del_py, str(dlg.removed_del_py))

# 2) 取消勾选 → 只删配置项、保留 .py
def _exec_uncheck(self):
    cb = self.checkBox()
    if cb is not None:
        cb.setChecked(False)
    return QMessageBox.Yes
QMessageBox.exec = _exec_uncheck
dlg.table.selectRow(0)  # 现在 entries 里第一行是 k2
dlg.del_row()
ok("k2 进入 removed_keys", "k2" in dlg.removed_keys)
ok("k2 取消勾选保留 .py", "k2" not in dlg.removed_del_py, str(dlg.removed_del_py))
QMessageBox.exec = orig_exec

# 3) 多选删除：Ctrl/Shift 多选两行 → 一次删两个（v2026.09.24.a）
QMessageBox.exec = lambda self: QMessageBox.Yes
dlg2 = ConfigDialog(None, tmp, RAW, list(sites), "py.json", tmp)
for _ in range(10):
    app.processEvents()
from PySide6.QtCore import QItemSelectionModel
dlg2.table.selectionModel().clearSelection()
for r in range(dlg2.table.rowCount()):
    dlg2.table.selectionModel().select(
        dlg2.table.model().index(r, 0),
        QItemSelectionModel.Select | QItemSelectionModel.Rows)
rows_sel = dlg2._selected_rows()
ok("多选选中 2 行", rows_sel == [0, 1], str(rows_sel))
dlg2.del_row()
ok("多选一次删两个", dlg2.removed_keys == {"k1", "k2"}, str(dlg2.removed_keys))
ok("多选后 entries 已清空", not dlg2.entries)
ok("多选默认勾选删 .py", dlg2.removed_del_py == {"k1", "k2"}, str(dlg2.removed_del_py))
dlg2.save()
raw3 = I.read_text(os.path.join(tmp, "py.json"))
sites3 = I.parse_jsonc(raw3).get("sites", [])
ok("多选删除保存后配置为空", not sites3, str(sites3))
ok("多选删除两个 .py 均移除", all(not os.path.isfile(os.path.join(tmp, "py", f))
                                for f in ("a.py", "b.py")))
QMessageBox.exec = orig_exec

# 4) save()：k1/k2 默认勾选 → .py 均删（备份 py_trash/）
dlg.save()
raw2 = I.read_text(os.path.join(tmp, "py.json"))
sites2 = I.parse_jsonc(raw2).get("sites", [])
ok("配置中 k1/k2 均已删除", not sites2, str(sites2))
ok("k1 的 .py 已移除（默认勾选）", not os.path.isfile(os.path.join(tmp, "py", "a.py")))
ok("k2 的 .py 已移除（勾选）", not os.path.isfile(os.path.join(tmp, "py", "b.py")))
def trash_has(repo, base):
    tr = os.path.join(repo, "py_trash")
    return os.path.isdir(tr) and any(f.startswith(base) for f in os.listdir(tr))


ok("k1 的 .py 已备份到 py_trash", trash_has(tmp, "a.py"))
ok("k2 的 .py 已备份到 py_trash", trash_has(tmp, "b.py"))
shutil.rmtree(tmp, ignore_errors=True)

print("== CLI：--del 与 --del --keep-py ==")
# CLI 默认：连 .py 删
tmp2 = make_repo()
rc = I.run_cli(["--repo", tmp2, "--del", "k1", "--write"])
ok("cli --del rc=0", rc == 0, str(rc))
s2 = I.parse_jsonc(I.read_text(os.path.join(tmp2, "py.json"))).get("sites", [])
ok("cli 删除后配置无 k1", [s.get("key") for s in s2] == ["k2"], str(s2))
ok("cli 默认连 .py 删除", not os.path.isfile(os.path.join(tmp2, "py", "a.py")))
ok("cli 默认删除有 py_trash 备份", trash_has(tmp2, "a.py"))
shutil.rmtree(tmp2, ignore_errors=True)

# CLI --keep-py：只删配置项
tmp3 = make_repo()
rc = I.run_cli(["--repo", tmp3, "--del", "k1", "--keep-py", "--write"])
ok("cli --del --keep-py rc=0", rc == 0, str(rc))
s3 = I.parse_jsonc(I.read_text(os.path.join(tmp3, "py.json"))).get("sites", [])
ok("keep-py 删除后配置无 k1", [s.get("key") for s in s3] == ["k2"], str(s3))
ok("keep-py 保留 .py 文件", os.path.isfile(os.path.join(tmp3, "py", "a.py")))
ok("keep-py 无 py_trash", not os.path.isdir(os.path.join(tmp3, "py_trash")))
shutil.rmtree(tmp3, ignore_errors=True)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
