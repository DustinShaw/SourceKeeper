# -*- coding: utf-8 -*-
"""v2026.09.24.e 主窗口标题与状态标签 测试（真实 PySide6 offscreen）。
验证：
1. 标题栏 = 仓库路径 — PyInjector（版本号移入「关于」）；
2. 仓库状态（已加载/站点数）显示在状态标签 lbl_status，而非标题；
3. 指定不存在的配置文件时，状态标签显示「未找到配置文件」，标题不变；
4. 刷新配置后状态标签同步更新。
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import inspect

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


from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog

QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Yes)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QApplication.exec = lambda self=None: 0

import injector as I

app = QApplication.instance() or QApplication([])

# 取出 run_gui 中定义的 App 类
s = inspect.getsource(I.run_gui)
idx = s.rfind("    app = QApplication")
src2 = s[:idx] + "    return App\n"
g = dict(I.__dict__)
exec(src2, g)
AppCls = g["run_gui"]()

win = AppCls()   # 默认 repo=项目目录，内含真实 py.json
app.processEvents()

title = win.windowTitle()
print("  标题: %s" % title)
ok("标题含应用名（— PyInjector）", ("— " + I.APP_NAME) in title or title == I.APP_NAME, title)
ok("标题不再含已加载状态（已移到状态标签）", "已加载" not in title, title)
ok("存在状态标签 lbl_status", hasattr(win, "lbl_status"))
ok("状态标签显示已加载/站点数/配置文件名",
   "已加载" in win.lbl_status.text() and "站点" in win.lbl_status.text()
   and "py.json" in win.lbl_status.text(), win.lbl_status.text())

# 指定不存在的配置文件 → 状态标签显示未找到，标题不变
# （2026-10-04：配置文件框由 QLineEdit 升级为可编辑 QComboBox，API 同步更新）
win.ent_cfg.setCurrentText("no_such_cfg.json")
win.load_repo()
app.processEvents()
t2 = win.windowTitle()
print("  错误标题: %s" % t2)
ok("错误时标题仍为仓库路径—PyInjector", ("— " + I.APP_NAME) in t2 or t2 == I.APP_NAME, t2)
ok("错误时状态标签显示未找到配置文件", "未找到配置文件" in win.lbl_status.text(), win.lbl_status.text())

# 恢复有效配置 → 状态标签恢复
win.ent_cfg.setCurrentText("py.json")
win.load_repo()
app.processEvents()
t3 = win.windowTitle()
ok("恢复后标题仍为仓库路径—PyInjector", ("— " + I.APP_NAME) in t3 or t3 == I.APP_NAME, t3)
ok("恢复后状态标签恢复已加载", "已加载" in win.lbl_status.text() and "站点" in win.lbl_status.text(), win.lbl_status.text())

# 待注入列表空状态引导 overlay（需要窗口可见，isVisible 才有意义）
win.show()
app.processEvents()
ok("存在待注入列表空状态 overlay（lb_empty）", hasattr(win, "lb_empty"))
ok("空列表时 overlay 可见且含操作引导",
   win.lb_empty.isVisible() and "注入文件" in win.lb_empty.text()
   and "拖进本窗口" in win.lb_empty.text() and "扫描目录" in win.lb_empty.text(),
   win.lb_empty.text())
win.pending.append({"key": "py_t", "name": "T", "api": "./py/t.py", "type": 3})
win.refresh_list()
app.processEvents()
ok("加入条目后 overlay 隐藏", not win.lb_empty.isVisible())
win.pending.clear()
win.refresh_list()
app.processEvents()
ok("清空后 overlay 恢复显示", win.lb_empty.isVisible())
win.resize(win.width() + 80, win.height())
app.processEvents()
ok("resize 后 overlay 尺寸跟随 viewport",
   win.lb_empty.geometry().width() == win.lb.viewport().rect().width())

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
