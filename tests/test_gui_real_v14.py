# -*- coding: utf-8 -*-
"""v14 真实 Qt（offscreen）集成测试：用真实 PySide6 驱动 ConfigDialog 与两个后台线程。
需要在带 PySide6 的 venv 下运行：envs/default/Scripts/python.exe。
不显示真实窗口（QT_QPA_PLATFORM=offscreen），避免沙箱杀进程。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import time
import inspect
import tempfile
import shutil
import socket
import http.server
import threading

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


from PySide6.QtWidgets import QApplication, QWidget, QDialog, QMessageBox, QFileDialog
from PySide6.QtCore import QTimer

# 避免任何弹框阻塞
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Yes)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QWidget.show = lambda self: None
QDialog.exec = lambda self: 1

import injector as I

# ---- 测试仓库 ----
tmp = tempfile.mkdtemp(prefix="pyinj_real_")
pydir = os.path.join(tmp, "py")
os.makedirs(pydir)

s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", port), _H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.2)

with open(os.path.join(pydir, "live.py"), "w", encoding="utf-8") as f:
    f.write('url = "http://127.0.0.1:%d/feed"\n' % port)
with open(os.path.join(pydir, "nope.py"), "w", encoding="utf-8") as f:
    f.write("x = 1\n")

RAW = '''{
  "spider": "x",
  "sites": [
    {"key": "py_live", "name": "Live┃PY", "api": "./py/live.py", "type": 3},
    /* [disabled]
    {"key": "py_off", "name": "Off┃PY", "api": "./py/nope.py", "type": 3}
    */
    {"key": "py_nope", "name": "Nope┃PY", "api": "./py/nope.py", "type": 3}
  ]
}'''
cfg = os.path.join(tmp, "py.json")
with open(cfg, "w", encoding="utf-8") as f:
    f.write(RAW)
sites_active = I.parse_jsonc(RAW).get("sites", [])

# ---- 取出 ConfigDialog（真实 Qt）----
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
src2 = src[:idx] + "    return ConfigDialog\n"
g = dict(I.__dict__)
exec(src2, g)
ConfigDialog = g["run_gui"]()

app = QApplication.instance() or QApplication(sys.argv)

print("== 真实 Qt offscreen：构造 ConfigDialog ==")
dlg = ConfigDialog(None, tmp, RAW, sites_active, "py.json", tmp)
ok("表格 10 列", dlg.table.columnCount() == 10, "cols=%s" % dlg.table.columnCount())
ok("已加载 3 条（含 1 禁用）", len(dlg.entries) == 3, str(len(dlg.entries)))
# v2026.09.24.e：检测区合并为一张卡片，勾选类型 + 共用 开始/暂停/停止
ok("构造后默认未开始检测", (not dlg._scanning) and (not dlg._url_scanning))
ok("构造后共用按钮态(开始可用/暂停禁用/停止禁用)",
   dlg.b_detect_start.isEnabled() and (not dlg.b_detect_pause.isEnabled())
   and (not dlg.b_detect_stop.isEnabled()))
ok("存在类型勾选框且默认勾选",
   hasattr(dlg, "cb_adult") and hasattr(dlg, "cb_url")
   and dlg.cb_adult.isChecked() and dlg.cb_url.isChecked())
ok("构造后成人列显示未检测",
   [dlg.table.item(r, 4).text() for r in range(dlg.table.rowCount())] == ["未检测"] * 3,
   str([dlg.table.item(r, 4).text() for r in range(dlg.table.rowCount())]))
ok("构造后短剧列显示未检测",
   [dlg.table.item(r, 5).text() for r in range(dlg.table.rowCount())] == ["未检测"] * 3,
   str([dlg.table.item(r, 5).text() for r in range(dlg.table.rowCount())]))
# 手动点「开始」（两路各自独立启动）
dlg._start_adult()
dlg._start_url()
app.processEvents()

# 驱动事件循环，等两个后台线程完成
deadline = time.time() + 60
while time.time() < deadline:
    app.processEvents()
    if (not dlg._scanning) and (not dlg._url_scanning):
        break
    time.sleep(0.03)
# 再跑一会收尾信号
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)

ok("成人检测完成", dlg._scanning is False)
ok("URL 检测完成", dlg._url_scanning is False)
ok("URL 结果含 py_live", "py_live" in dlg.url_map, str(dlg.url_map))
ok("py_live 可达(code=1)", dlg.url_map.get("py_live", (0,))[0] == 1, str(dlg.url_map.get("py_live")))
ok("py_nope 无URL(code=2)", dlg.url_map.get("py_nope", (0,))[0] == 2, str(dlg.url_map.get("py_nope")))
ok("禁用标记 F,T,F",
   [e.get("_disabled") for e in dlg.entries] == [False, True, False],
   str([e.get("_disabled") for e in dlg.entries]))
# 表格「禁用」列内容（v15 起为第 8 列）
col7 = []
for r in range(dlg.table.rowCount()):
    it = dlg.table.item(r, 8)
    col7.append(it.text() if it else "")
ok("禁用列含 是/否", col7 == ["否", "是", "否"], str(col7))
# v15：短剧列（key 列移除后为第 5 列）——夹具站点均非短剧源
col_dj = [dlg.table.item(r, 5).text() for r in range(dlg.table.rowCount())]
ok("短剧列全部「否」（夹具无短剧源）", col_dj == ["否"] * 3, str(col_dj))

# v14.11：打开界面即自动后台检测 .py 存在性（只读），结果填入「文件」列
deadline_f = time.time() + 30
while time.time() < deadline_f:
    app.processEvents()
    if not dlg._file_checking:
        break
    time.sleep(0.03)
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)
ok("文件存在性检测已完成", dlg._file_checking is False)
col8 = []
for r in range(dlg.table.rowCount()):
    it = dlg.table.item(r, 9)
    col8.append(it.text() if it else "")
ok("文件列全部「正常」（3 个 .py 均存在）", col8 == ["正常"] * 3, str(col8))
ok("file_map 覆盖全部条目", len(dlg.file_map) == 3, str(dlg.file_map))
ok("分组标题提示 Spider 资源齐全", "Spider 资源齐全" in dlg.detect_grp.title(), dlg.detect_grp.title())

print("== 真实 Qt：禁用 / 启用 ==")
dlg.table.selectRow(0)
before = dlg.raw
dlg.disable_selected()
ok("禁用后 raw 改变", dlg.raw != before)
ok("py_live 已被禁用", "py_live" in I.parse_disabled_keys(dlg.raw))
dlg.table.selectRow(0)
dlg.enable_selected()
ok("启用后 py_live 恢复", "py_live" not in I.parse_disabled_keys(dlg.raw))

srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
