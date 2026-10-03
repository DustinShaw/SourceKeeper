# -*- coding: utf-8 -*-
"""v13 Qt 冒烟测试（offscreen，无需显示器）：
复刻 _AdultScanWorker._ask_user_dir 的跨线程 QMetaObject.invokeMethod 调用。

⚠️ 2026-09-26：参数不再走 Q_ARG/Q_RETURN_ARG（Qt5/PySide2 没有这两个别名，
硬传会段错误），改为「无参槽 + 属性传递」——与 injector.py 保持同一写法，
这样 Qt5/Qt6 两条绑定都能用同一份验证。结果写入 qt_smoke_out.txt。"""
import os, sys, io

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QThread, Signal, QMetaObject, Qt, Slot

buf = io.StringIO()
def log(*a):
    buf.write(" ".join(str(x) for x in a) + "\n")

ok = fail = 0
def check(n, c, e=""):
    global ok, fail
    if c:
        ok += 1; log("PASS", n, e)
    else:
        fail += 1; log("FAIL", n, e)

app = QApplication(sys.argv)

class Dialog(QDialog):
    def __init__(self):
        super().__init__()
        self._closed = False
        self._pending_missing = ""
        self._pending_result = ""
    @Slot()
    def prompt_py_dir(self):
        # 忠实复刻 injector.py 的守卫与行为
        if self._closed:
            self._pending_result = ""
            return
        # 模拟用户选择了一个目录（真实场景是 QFileDialog）
        self._pending_result = "CHOSEN_DIR"

class Worker(QThread):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.result = None
    def run(self):
        # 复刻 worker 的调用方式（跨线程，payload 经属性传递）
        import json
        try:
            self.dialog._pending_missing = json.dumps(["py_a", "py_b"])
            self.dialog._pending_result = ""
            QMetaObject.invokeMethod(
                self.dialog, "prompt_py_dir", Qt.BlockingQueuedConnection)
            self.result = getattr(self.dialog, "_pending_result", "") or ""
        except Exception as ex:
            self.result = "EXC:%s" % ex

dlg = Dialog()
w = Worker(dlg)
w.start()
# 主线程事件循环运转；用 processEvents 等待 worker 结束（offscreen 无需真实窗口）
import time
for _ in range(200):
    app.processEvents()
    if not w.isRunning():
        break
    time.sleep(0.01)
w.wait(2000)

check("worker 跨线程调用取到返回值", w.result == "CHOSEN_DIR", repr(w.result))
check("dialog._closed 仍为 False", dlg._closed is False)

# 关闭后调用应返回 ''（不崩溃）
dlg._closed = True
# 生产路径：worker 线程在 _closed 时已提前返回 ''，不会发起 invokeMethod；
# 这里直接验证 slot 闭合守卫返回 ''（避免跨线程同线程误用的无意义调用）。
try:
    r = dlg.prompt_py_dir()
    check("关闭后 slot 守卫返回空串", r is None and dlg._pending_result == "",
          "r=%r result=%r" % (r, dlg._pending_result))
except Exception as ex:
    check("关闭后 slot 守卫返回空串", False, "EXC:%s" % ex)

log("")
log("RESULT: %d passed, %d failed" % (ok, fail))
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "qt_smoke_out.txt"),
          "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
