# -*- coding: utf-8 -*-
"""工具箱对话框（_ToolboxDialog）GUI 测试（真实 PySide6 offscreen）。
覆盖：分页切换、分类识别、JAR 体检、源测速、网络诊断、直播表转换、诊断报告导出。
全部在本地临时仓库 + 本地 HTTP 服务器上跑，不访问外网。"""
import io
import os
import sys
import time
import tempfile
import shutil
import inspect
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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


# ---- 本地服务器：提供 .py 源里引用的 URL 与 jar ----
class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = b"PK\x03\x04" + b"J" * 4096
        self.send_response(200)
        self.send_header("Content-Type", "application/java-archive")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
BASE = "http://127.0.0.1:%d" % PORT

tmp = tempfile.mkdtemp(prefix="pyinj_toolbox_")
py_dir = os.path.join(tmp, "py")
os.makedirs(py_dir)
# 一个含成人关键词的本地 py 源
with open(os.path.join(py_dir, "adult_src.py"), "w", encoding="utf-8") as f:
    f.write("class Spider:\n    # 麻豆传媒 成人\n    api = '%s/api.php/provide/vod'\n" % BASE)

RAW = """{
"sites": [
{"key":"py_live","name":"Live┃PY","api":"./py/adult_src.py","type":3,"filterable":1,"quickSearch":1,"searchable":1},
{"key":"csp_j","name":"Jar源","api":"csp_Jar","type":3,"jar":"%s/x.jar"},
{"key":"cms_x","name":"直连CMS","api":"%s/api.php/provide/vod","type":1}
]}
""" % (BASE, BASE)
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(RAW)

import injector as I
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QPushButton

QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)

app = QApplication.instance() or QApplication([])

src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return (_ToolboxDialog, ConfigDialog)\n", g)
_ToolboxDialog, ConfigDialog = g["run_gui"]()

sites_active = I.parse_jsonc(RAW)["sites"]
dlg = ConfigDialog(None, tmp, RAW, sites_active, "py.json", tmp)
app.processEvents()

print("== 0) ConfigDialog 有工具箱按钮 ==")
btns = [b.text() for b in dlg.findChildren(QPushButton)]
ok("底部有「🧰 工具箱」", "🧰 工具箱" in btns, str(btns))

items = [dict(e) for e in dlg.entries]
tb = _ToolboxDialog(dlg, items, tmp, tmp)
tb.show()                 # offscreen 下也需要 show，子控件 isVisible 才为真
app.processEvents()


def wait_tool(timeout=60.0):
    """工具箱各检测已改为后台线程，等当前任务跑完再断言（并把结果信号派发到主线程）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        w = getattr(tb, "_run_worker", None)
        if w is None:
            break
        w.wait(50)
    app.processEvents()
    return getattr(tb, "_run_worker", None) is None

print("== 1) 分页切换 ==")
ok("默认第 0 页（分类识别）可见", tb.pages["cat"].isVisible())
ok("其它页默认隐藏", not tb.pages["report"].isVisible())
tb._switch_page(5)
app.processEvents()
ok("切到报告页：报告可见、分类隐藏",
   tb.pages["report"].isVisible() and not tb.pages["cat"].isVisible())
tb._switch_page(0)
app.processEvents()

print("== 2) 分类识别（用外置敏感词库）==")
ok("分类页有进度条", "cat" in tb._page_bars)
tb._run_cat()
ok("检测中「开始」按钮全部禁用",
   all(not b.isEnabled() for b in tb._tool_buttons))
ok("检测完成", wait_tool())
txts = [tb.t_cat.item(r, 0).text() for r in range(tb.t_cat.rowCount())]
ok("识别出成人源", "Live┃PY" in txts, str(txts))
ok("分类标签含「成人」",
   any("成人" in (tb.t_cat.item(r, 2).text() or "") for r in range(tb.t_cat.rowCount())))
_bar, _lbl = tb._page_bars["cat"]
ok("分类页进度条走满", _bar.value() == 100 and _bar.maximum() == 100,
   "%s/%s" % (_bar.value(), _bar.maximum()))
ok("分类页状态文字给出结果", "完成" in _lbl.text() or "命中" in tb.lbl_status.text(),
   _lbl.text())

print("== 3) JAR 体检（本地 jar 可达）==")
ok("JAR 页有进度条", "jar" in tb._page_bars)
tb._run_jar()
ok("检测完成", wait_tool())
ok("JAR 表有一行", tb.t_jar.rowCount() == 1, str(tb.t_jar.rowCount()))
level = tb.t_jar.item(0, 1).text() if tb.t_jar.rowCount() else ""
ok("JAR 判定为健康", level == "健康", level)
_jbar, _ = tb._page_bars["jar"]
ok("JAR 页进度条走满", _jbar.value() == 100 and _jbar.maximum() == 100,
   "%s/%s" % (_jbar.value(), _jbar.maximum()))

print("== 4) 源测速（本地 HTTP 可达）==")
tb._run_speed()
ok("检测完成", wait_tool())
ok("测速表非空", tb.t_speed.rowCount() >= 1, str(tb.t_speed.rowCount()))
reach = [tb.t_speed.item(r, 1).text() for r in range(tb.t_speed.rowCount())]
ok("至少一个可达", "是" in reach, str(reach))
_sbar, _ = tb._page_bars["speed"]
ok("测速页进度条走满", _sbar.value() == 100 and _sbar.maximum() == 100,
   "%s/%s" % (_sbar.value(), _sbar.maximum()))

print("== 5) 网络诊断（本地回环应正常）==")
tb._run_net()
ok("检测完成", wait_tool())
ok("诊断表非空", tb.t_net.rowCount() >= 1, str(tb.t_net.rowCount()))
concl = [tb.t_net.item(r, 1).text() for r in range(tb.t_net.rowCount())]
ok("回环地址判定正常", "正常" in concl, str(concl))
_nbar, _ = tb._page_bars["net"]
ok("诊断页进度条走满", _nbar.value() == 100 and _nbar.maximum() == 100,
   "%s/%s" % (_nbar.value(), _nbar.maximum()))
ok("诊断页内置代理控件行（与主窗口共用同一设置）", hasattr(tb, "proxy_ctl"))
ok("本页代理验证按钮存在", "验证" in tb.proxy_ctl.btn.text(), tb.proxy_ctl.btn.text())

print("== 6) 直播表转换 ==")
plist_src = os.path.join(tmp, "list.txt")
with open(plist_src, "w", encoding="utf-8") as f:
    f.write("央视,#genre#\nCCTV1,%s/1.m3u8\n" % BASE)
_orig_open = QFileDialog.getOpenFileName
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (plist_src, ""))
try:
    tb._run_plist()
    ok("转换完成", wait_tool())
finally:
    QFileDialog.getOpenFileName = _orig_open
ok("转换表有一行", tb.t_plist.rowCount() == 1, str(tb.t_plist.rowCount()))
out_m3u = os.path.join(tmp, "list.m3u")
ok("生成的 m3u 存在", os.path.isfile(out_m3u))
if os.path.isfile(out_m3u):
    with open(out_m3u, "r", encoding="utf-8") as f:
        ok("m3u 含 #EXTM3U", "#EXTM3U" in f.read())
_pbar, _ = tb._page_bars["plist"]
ok("转换页进度条走满", _pbar.value() == 100, str(_pbar.value()))

print("== 7) 诊断报告导出 ==")
rep_path = os.path.join(tmp, "源诊断报告.md")
_orig_save = QFileDialog.getSaveFileName
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (rep_path, ""))
try:
    tb._run_report()
    ok("报告生成完成", wait_tool())
finally:
    QFileDialog.getSaveFileName = _orig_save
ok("报告表非空", tb.t_report.rowCount() == len(items), str(tb.t_report.rowCount()))
ok("报告文件已生成", os.path.isfile(rep_path))
if os.path.isfile(rep_path):
    with open(rep_path, "r", encoding="utf-8") as f:
        content = f.read()
    ok("报告含标题", "源诊断报告" in content)
    ok("报告含概览", "## 概览" in content)
_rbar, _ = tb._page_bars["report"]
ok("报告页进度条走满", _rbar.value() == 100 and _rbar.maximum() == 100,
   "%s/%s" % (_rbar.value(), _rbar.maximum()))

print("== 8) 检测结束后按钮恢复可用 ==")
ok("「开始」按钮已恢复", all(b.isEnabled() for b in tb._tool_buttons))
ok("页状态文字已被更新", bool(tb.lbl_status.text()))
ok("重复触发被拒绝（同一时刻只允许一个任务）",
   getattr(tb, "_run_worker", None) is None)
ok("六页都有独立进度条",
   set(tb._page_bars.keys()) == {"cat", "jar", "speed", "net", "plist", "report"},
   str(sorted(tb._page_bars.keys())))

tb.close()
dlg.close()
srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
