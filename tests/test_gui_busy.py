# -*- coding: utf-8 -*-
"""v14.9 两路检测分离（独立开始/暂停/停止）测试（真实 PySide6 offscreen）。

验证：
1. 打开界面默认平静态：两行各自 开始可用/暂停禁用/停止禁用，编辑按钮全可用，列显示「未检测」；
2. 只启动成人检测：忙碌生效，但 URL 行按钮完全不受影响（两路分离）；
3. 成人完成后不自动接力 URL；
4. URL 独立启动，中途可「停止」；
5. 暂停/继续：暂停后进度冻结、按钮变「继续」，继续后跑完；
6. 两路可同时运行。
"""
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


from PySide6.QtWidgets import QApplication, QWidget, QDialog, QMessageBox, QFileDialog, QPushButton, QProgressBar
from PySide6.QtCore import QTimer

QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Yes)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QWidget.show = lambda self: None
QDialog.exec = lambda self: 1

import injector as I
import pyinj_core as C

# 放慢 URL 可达性检测（每项 +0.3s），保证「暂停/停止」测试有稳定的中途窗口，
# 避免 12 项在点击暂停前就跑完造成竞态失败。
# ⚠️ 必须 patch **pyinj_core** 而非 injector：URL 检测走 pyinj_core.check_site_urls，
# 其内部调用的是 pyinj_core 自己的 check_url_reachable（模块全局），
# 改 injector 命名空间里那份对实际调用完全无效——此前一直是个假 patch，
# 导致本用例时好时坏（2026-09-26 根因修）。
_orig_check_url = C.check_url_reachable


def _slow_check_url(url, *a, **k):
    time.sleep(0.3)
    return _orig_check_url(url, *a, **k)


C.check_url_reachable = _slow_check_url

# ---- 测试仓库（多个站点让 URL 检测持续一小段时间，便于观察暂停/停止）----
tmp = tempfile.mkdtemp(prefix="pyinj_sep_")
pydir = os.path.join(tmp, "py")
os.makedirs(pydir)

s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(0.05)  # 拖慢一点，保证能观察暂停/停止中间态
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", port), _H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.2)

N = 12
site_lines = []
for i in range(N):
    with open(os.path.join(pydir, "s%d.py" % i), "w", encoding="utf-8") as f:
        f.write('url = "http://127.0.0.1:%d/feed%d"\n' % (port, i))
    site_lines.append('{"key": "k%02d", "name": "S%02d┃PY", "api": "./py/s%d.py", "type": 3}' % (i, i, i))
RAW = '{\n  "spider": "x",\n  "sites": [\n    ' + ",\n    ".join(site_lines) + "\n  ]\n}"
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


def wait_until(pred, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    return False


def spin(seconds):
    """原地跑事件循环 seconds 秒。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


print("== 构造 ConfigDialog（两路均默认平静态）==")
dlg = ConfigDialog(None, tmp, RAW, sites_active, "py.json", tmp)
app.processEvents()

busy_buttons = dlg._busy_buttons
# 2026-10-01：底部新增「🧹 剔除失效源」（也受 busy 管理）→ 6 → 7
ok("忙碌按钮共 7 个（查重/去重已移出底部）", len(busy_buttons) == 7, str(len(busy_buttons)))
# 「禁用选中/启用选中」按选中状态联动，不计入"平静态全可用"断言
state_btns = {dlg._btn_disable, dlg._btn_enable}
core_buttons = [b for b in busy_buttons if b not in state_btns]
ok("禁用/启用按钮互为不同实例", dlg._btn_disable is not dlg._btn_enable)
ok("无选中时禁用/启用按钮均灰",
   not dlg._btn_disable.isEnabled() and not dlg._btn_enable.isEnabled())
# 检测区合并为一张卡片：共用 开始/暂停/停止 + 类型勾选
ok("共用按钮态(开始可用/暂停禁用/停止禁用)",
   dlg.b_detect_start.isEnabled() and not dlg.b_detect_pause.isEnabled()
   and not dlg.b_detect_stop.isEnabled())
ok("存在类型勾选框且默认勾选",
   hasattr(dlg, "cb_adult") and hasattr(dlg, "cb_url")
   and dlg.cb_adult.isChecked() and dlg.cb_url.isChecked())
ok("编辑按钮全可用（平静态，状态按钮除外）", all(b.isEnabled() for b in core_buttons))
ok("搜索框可用", dlg.search_edit.isEnabled())
ok("未在检测", (not dlg._scanning) and (not dlg._url_scanning))
ok("状态行均显示未开始", "未开始" in dlg.prog_label.text() and "未开始" in dlg.url_label.text())
col4 = {dlg.table.item(r, 4).text() for r in range(dlg.table.rowCount())}
col5 = {dlg.table.item(r, 5).text() for r in range(dlg.table.rowCount())}
col7 = {dlg.table.item(r, 7).text() for r in range(dlg.table.rowCount())}
ok("成人列默认「未检测」", col4 == {"未检测"}, str(col4))
ok("短剧列默认「未检测」", col5 == {"未检测"}, str(col5))
ok("可达列默认「未检测」", col7 == {"未检测"}, str(col7))

print("== 只启动成人检测（取消勾选 URL）→ URL 行不受影响 ==")
dlg.cb_url.setChecked(False)        # 仅成人勾选
dlg.b_detect_start.click()          # 共用「开始」只启动勾选的类型
app.processEvents()
ok("共用：开始禁用/暂停可用/停止可用",
   not dlg.b_detect_start.isEnabled() and dlg.b_detect_pause.isEnabled()
   and dlg.b_detect_stop.isEnabled())
ok("暂停按钮显示「暂停」", dlg.b_detect_pause.text() == "暂停", dlg.b_detect_pause.text())
ok("URL 行不受影响：仍按未开始显示",
   "未开始" in dlg.url_label.text(), dlg.url_label.text())
ok("编辑按钮禁用（忙碌）", all(not b.isEnabled() for b in busy_buttons))
close_btn = [b for b in dlg.findChildren(QPushButton) if b.text() == "关闭"]
ok("关闭按钮仍可用", bool(close_btn) and close_btn[0].isEnabled())

done_a = wait_until(lambda: not dlg._scanning)
spin(0.3)
ok("成人检测完成", done_a)
ok("成人完成不自动接力 URL", not dlg._url_scanning and not dlg._url_started)
ok("成人状态行保留「完成」汇总", "完成" in dlg.prog_label.text(), dlg.prog_label.text())
ok("完成后编辑按钮恢复", all(b.isEnabled() for b in core_buttons))
# v2026.09.24 选中态联动：选中启用项 → 仅「禁用选中」可用；选中禁用项 → 仅「启用选中」可用
dlg.table.selectRow(0)
app.processEvents()
_e0 = dlg._shown[dlg.table.currentRow()]
if _e0.get("_disabled"):
    ok("选中禁用项：启用亮/禁用灰", dlg._btn_enable.isEnabled() and not dlg._btn_disable.isEnabled())
else:
    ok("选中启用项：禁用亮/启用灰", dlg._btn_disable.isEnabled() and not dlg._btn_enable.isEnabled())
ok("完成后共用按钮复位(开始可用/暂停禁用/停止禁用)",
   dlg.b_detect_start.isEnabled() and not dlg.b_detect_pause.isEnabled()
   and not dlg.b_detect_stop.isEnabled())
ok("URL 状态行仍未开始", "未开始" in dlg.url_label.text(), dlg.url_label.text())

print("== URL 独立启动 → 中途停止 ==")
dlg.cb_url.setChecked(True)          # 重新勾选 URL（成人已结束）
dlg.b_detect_start.click()          # 仅 URL 在跑，开始只启动它
app.processEvents()
ok("共用：开始禁用/暂停可用/停止可用",
   not dlg.b_detect_start.isEnabled() and dlg.b_detect_pause.isEnabled()
   and dlg.b_detect_stop.isEnabled())
ok("编辑按钮再次禁用", all(not b.isEnabled() for b in busy_buttons))
# 必须等「已开始但尚未跑满」的中途窗口：若扫描已结束再点停止，
# _stop_detect 会因「未在扫描」直接空转，两条断言都假失败
mid = wait_until(lambda: dlg._url_scanning and 0 < len(dlg.url_map) < N, timeout=30)
ok("捕获 URL 检测中途窗口（已开始未跑满）", mid,
   "url_map=%d/%d scanning=%s" % (len(dlg.url_map), N, dlg._url_scanning))
dlg.b_detect_stop.click()           # 共用「停止」停止在跑的 URL
ok("URL 停止标志置位", dlg._url_stop is True)
wait_until(lambda: not dlg._url_scanning)
spin(0.3)
ok("URL 状态行显示「已停止」", "已停止" in dlg.url_label.text(), dlg.url_label.text())
ok("停止后共用按钮复位", dlg.b_detect_start.isEnabled() and not dlg.b_detect_stop.isEnabled())
ok("停止后编辑按钮恢复", all(b.isEnabled() for b in core_buttons))

print("== URL 暂停 / 继续 ==")
dlg.cb_url.setChecked(True)
dlg.b_detect_start.click()          # 再次启动 URL
app.processEvents()
wait_until(lambda: dlg._url_scanning and 2 <= len(dlg.url_map) < N, timeout=30)
dlg.b_detect_pause.click()          # 共用「暂停」暂停在跑的 URL
app.processEvents()
ok("暂停后标志置位", dlg._url_paused is True)
ok("暂停按钮变「继续」", dlg.b_detect_pause.text() == "继续", dlg.b_detect_pause.text())
spin(0.3)
ok("状态行显示已暂停", "已暂停" in dlg.url_label.text(), dlg.url_label.text())
# 暂停的语义是「不再开始新的检测」，已在途的那一个请求仍会跑完
# （本用例每项 +0.3s，故它会在暂停后多落地 1 项）。先等在途结果落地再取快照，
# 之后的进度必须完全冻结——否则就是把产品语义误判成缺陷。
spin(0.6)
frozen = len(dlg.url_map)
spin(0.8)
ok("暂停期间进度冻结（在途那一项落地后不再增长）",
   len(dlg.url_map) == frozen, "%d -> %d" % (frozen, len(dlg.url_map)))
ok("暂停期间仍在 running 态（编辑按钮仍禁用）",
   dlg._url_scanning and all(not b.isEnabled() for b in busy_buttons))
dlg.b_detect_pause.click()          # 继续
app.processEvents()
ok("继续后标志复位", dlg._url_paused is False)
ok("继续按钮变回「暂停」", dlg.b_detect_pause.text() == "暂停")
done_u = wait_until(lambda: not dlg._url_scanning)
spin(0.3)
ok("继续后跑完", done_u)
ok("URL 汇总为「完成」", "完成" in dlg.url_label.text(), dlg.url_label.text())
ok("跑完后按钮复位", dlg.b_detect_start.isEnabled() and not dlg.b_detect_stop.isEnabled())
ok("全部结果 12 个", len(dlg.url_map) == 12, str(len(dlg.url_map)))

print("== 两路同时运行 ==")
dlg.cb_adult.setChecked(True)
dlg.cb_url.setChecked(True)
dlg.b_detect_start.click()           # 两类型均勾选 → 同时启动
app.processEvents()
ok("两路可同时运行", dlg._scanning and dlg._url_scanning)
ok("同时运行时编辑按钮禁用", all(not b.isEnabled() for b in busy_buttons))
wait_until(lambda: (not dlg._scanning) and (not dlg._url_scanning))
spin(0.3)
ok("两路均完成", "完成" in dlg.prog_label.text() and "完成" in dlg.url_label.text())
ok("结束后全部恢复", all(b.isEnabled() for b in core_buttons)
   and dlg.b_detect_start.isEnabled())

srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
