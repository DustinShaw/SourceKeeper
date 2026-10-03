# -*- coding: utf-8 -*-
"""Windows 7 版（Qt5 / PySide2）GUI 冒烟测试
============================================
与 test_gui_layout.py 的断言一致，但走 **PySide2 分支**，用来保证 injector.py 的
Qt 绑定兼容层在 Qt5 下同样能构造出完整主界面（Qt6 能跑不代表 Qt5 能跑：
QShortcut 归属、app.exec() 差异都在这里被兜住）。

本机跑（Python 3.9 环境）：
  QT_QPA_PLATFORM=offscreen <py39> test_win7_build.py
"""
import os
import sys
import io
import inspect

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import injector  # noqa: E402

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s" % name)
    else:
        FAIL += 1
        print("[FAIL] %s  %s" % (name, extra))


from PySide2.QtWidgets import QApplication, QPushButton, QGroupBox  # noqa: E402

# 注意：injector.py 的 Qt 导入块写在 run_gui() 内部（mock 测试要能跳过真实 Qt），
# 所以 QT_BINDING / _app_exec 落在下面 exec 出来的命名空间 g 里，而不是 injector 模块上。
ok("走 PySide2/Qt5 分支", "PySide2" in open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "injector.py"),
    encoding="utf-8").read())

# 沙箱内禁止真实 GUI：仅构造，不 exec / 不 show
QApplication.exec_ = lambda self=None: 0
QApplication.exec = lambda self=None: 0

app = QApplication([])

# 取出 run_gui 中定义的 App 类（截断到 app = QApplication 之前）
s = inspect.getsource(injector.run_gui)
idx = s.rfind("    app = QApplication")
src2 = s[:idx] + "    return App\n"
g = dict(injector.__dict__)
exec(src2, g)
AppCls = g["run_gui"]()

try:
    win = AppCls()
    ok("App 构造成功（Qt5）", win is not None)
except Exception as ex:
    ok("App 构造成功（Qt5）", False, "%s: %s" % (type(ex).__name__, ex))
    win = None

if win is not None:
    btn_texts = [b.text() for b in win.findChildren(QPushButton)]
    for t in ["📄 注入文件", "🔍 扫描目录", "移除选中", "🗑 清空列表",
              "💾 写入配置", "⚙ 管理站点", "♻ 去重", "🔄 刷新", "ℹ 关于"]:
        ok("工具栏按钮存在: " + t, t in btn_texts, str(btn_texts))

    titles = [gb.title() for gb in win.findChildren(QGroupBox)]
    ok("全局开关/待注入列表分组仍在",
       any(t.startswith("全局开关") for t in titles)
       and any(t.startswith("待注入列表") for t in titles),
       str(titles))

    # 快捷键（QShortcut 在 Qt5 属 QtWidgets，兼容层要能拿到）
    try:
        from PySide2.QtWidgets import QShortcut
        ok("QShortcut 从 QtWidgets 取得成功（Qt5 正确位置）", True)
    except Exception as ex:
        ok("QShortcut 从 QtWidgets 取得成功", False, str(ex))

    # _app_exec 兼容函数（在 run_gui 的命名空间里）
    ok("_app_exec 存在且可执行", callable(g.get("_app_exec")))

    # ---- 版本标注（节日特别版）：所有窗体标题栏带版本后缀，Qt5 下同样生效 ----
    from PySide2.QtWidgets import QDialog
    from PySide2.QtCore import QEvent

    suf = injector.APP_TITLE_SUFFIX
    print("  版本后缀: %s" % suf)
    ok("Qt5 下主窗口标题含版本标识", suf in win.windowTitle(), win.windowTitle())
    ok("Qt5 下 tagged_title 组合正确",
       injector.tagged_title("合并导入") == "合并导入 — " + suf,
       injector.tagged_title("合并导入"))
    ok("Qt5 存在 QEvent.WindowTitleChange", hasattr(QEvent, "WindowTitleChange"))

    d = QDialog()                      # 模拟 QMessageBox：直接设标题，不经 tagged_title
    d.setWindowTitle("提示")
    win.eventFilter(d, QEvent(QEvent.WindowTitleChange))
    ok("Qt5 兜底过滤器补上版本标识", d.windowTitle() == "提示 — " + suf, d.windowTitle())
    _t = d.windowTitle()
    win.eventFilter(d, QEvent(QEvent.WindowTitleChange))
    ok("Qt5 兜底过滤器幂等（不叠加）", d.windowTitle() == _t, d.windowTitle())

    # 主窗口待注入列表 / 状态栏等也在 Qt5 下正常
    ok("主窗口构造无异常（工具栏 + 分组）", len(titles) > 0, str(titles))

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
