# -*- coding: utf-8 -*-
"""点击 api 列打开目标测试（offscreen，按 type 分流）：
- 点击 api 列 -> 按 type 打开正确目标（本地 .py / 远程 url / jar / 目录）
- 非 api 列 -> 不触发
- 缺失 .py / 无 api -> 仅提示，不打开
"""
import io
import os
import shutil
import sys
import tempfile

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
with open(os.path.join(py_dir, "a.py"), "w", encoding="utf-8") as f:
    f.write("# a\nclass Spider: pass\n")

RAW = """{
"sites": [
{"key":"py_a","name":"A站","api":"./py/a.py","type":3,"filterable":1,"quickSearch":1,"searchable":1},
{"key":"py_remote","name":"远程","api":"http://x.com/y.py","type":3,"filterable":1,"quickSearch":1,"searchable":1},
{"key":"py_miss","name":"缺文件","api":"./py/miss.py","type":3,"filterable":1,"quickSearch":1,"searchable":1},
{"key":"py_noapi","name":"无api","api":"","type":3,"filterable":1,"quickSearch":1,"searchable":1}
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
sites = _json.loads(RAW)["sites"]
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(RAW)
dlg = ConfigDialog(None, tmp, RAW, sites, "py.json", tmp)

calls = []
orig_startfile = getattr(I.os, "startfile", None)
I.os.startfile = lambda p: calls.append(p)

# 拦截 QDesktopServices.openUrl（远程脚本 / API 链接 / jar 走这条路）
from PySide6.QtGui import QDesktopServices as _QDS
url_open = []
orig_openurl = _QDS.openUrl
_QDS.openUrl = staticmethod(lambda u: (url_open.append(u.toString()), True)[1])

msgs = []
orig_info = QMessageBox.information
orig_warn = QMessageBox.warning


def fake_info(*a, **k):
    msgs.append(("info", a[2] if len(a) > 2 else ""))
    return QMessageBox.Ok


def fake_warn(*a, **k):
    msgs.append(("warn", a[2] if len(a) > 2 else ""))
    return QMessageBox.Ok


QMessageBox.information = staticmethod(fake_info)
QMessageBox.warning = staticmethod(fake_warn)
try:
    dlg._on_api_cell_clicked(0, 1)
    ok(calls == [os.path.join(tmp, "py", "a.py")],
       "点击 api 打开正确 .py 路径", str(calls))

    calls.clear()
    dlg._on_api_cell_clicked(0, 0)
    ok(calls == [], "非 api 列不触发打开", str(calls))

    # type:3 远程 .py -> 按 type 分流，打开该 URL（不再只是提示）
    url_open.clear()
    msgs.clear()
    dlg._on_api_cell_clicked(1, 1)
    ok(calls == [] and url_open == ["http://x.com/y.py"],
       "远程源按 type 打开 URL", str(url_open) + str(msgs))

    msgs.clear()
    dlg._on_api_cell_clicked(2, 1)
    ok(calls == [] and any("未找到" in m[1] for m in msgs), "缺失 .py 仅提示不打开", str(msgs))

    msgs.clear()
    dlg._on_api_cell_clicked(3, 1)
    ok(calls == [] and any("没有可打开" in m[1] for m in msgs), "无 api 仅提示", str(msgs))
finally:
    QMessageBox.information = orig_info
    QMessageBox.warning = orig_warn
    _QDS.openUrl = orig_openurl
    if orig_startfile is not None:
        I.os.startfile = orig_startfile
    else:
        del I.os.startfile

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
