# -*- coding: utf-8 -*-
"""窗体标题「版本标注」测试（真实 PySide6 offscreen）。

对应需求：所有窗体标题栏都必须明确标注版本。版本号本身随发布变化，本测试只校验「标题 = 文本 — 源管家 v<版本>」的结构，不写死具体版本串。

验证：
1. tagged_title() 的组合 / 幂等 / 空标题行为；
2. 静态扫描：injector.py 中每一处 setWindowTitle 都经 tagged_title（防止新增窗体漏标）；
3. 主窗口标题含版本标识且保留「路径 — 源管家」结构；
4. 全局兜底过滤器：未显式标注的窗体（如 QMessageBox）标题变化时被自动补上标识，且幂等、不改空标题；
5. 子对话框（🧰 工具箱）标题含标识。
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import io
import sys
import inspect

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                              line_buffering=True)

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


from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from PySide6.QtCore import QEvent

QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Yes)

import injector as I

app = QApplication.instance() or QApplication([])
SUF = I.APP_TITLE_SUFFIX

print("== 1) 版本号与 tagged_title 组合 ==")
print("  APP_VERSION = %s" % I.APP_VERSION)
print("  标题后缀   = %s" % SUF)
ok("APP_VERSION 非空（版本号存在）",
   bool(I.APP_VERSION and isinstance(I.APP_VERSION, str)), I.APP_VERSION)
ok("后缀 = 源管家 v<版本>", SUF == "源管家 v" + I.APP_VERSION, SUF)
ok("空标题 → 仅后缀", I.tagged_title("") == SUF, I.tagged_title(""))
ok("纯空白标题 → 仅后缀", I.tagged_title("   ") == SUF, I.tagged_title("   "))
ok("普通标题 → 「标题 — 后缀」",
   I.tagged_title("编辑条目") == "编辑条目 — " + SUF, I.tagged_title("编辑条目"))
ok("已含后缀 → 原样返回（幂等）", I.tagged_title(SUF) == SUF, I.tagged_title(SUF))
_t = I.tagged_title("合并导入")
ok("二次调用不叠加后缀", I.tagged_title(_t) == _t, I.tagged_title(_t))

print("\n== 2) 静态扫描：所有 setWindowTitle 都经 tagged_title ==")
src = open(os.path.join(HERE, "injector.py"), encoding="utf-8").read()
_bad = []
for _i, _line in enumerate(src.splitlines(), 1):
    # 只认可行的两种写法：直接 tagged_title(...)，或委托 _repo_title()（其内部也走 tagged_title）
    if ("setWindowTitle(" in _line and "tagged_title(" not in _line
            and "_repo_title()" not in _line and "def " not in _line):
        _bad.append("%d: %s" % (_i, _line.strip()))
ok("injector.py 每处 setWindowTitle 都标注版本", not _bad, " | ".join(_bad))
ok("_repo_title 内部走 tagged_title（委托链不断）",
   "return tagged_title(self.repo_dir or \"\")" in src, "")
ok("setWindowTitle 调用点数 ≥ 14（窗体未丢）",
   src.count("setWindowTitle(") >= 14, str(src.count("setWindowTitle(")))
ok("关于框标题也经 tagged_title 标注",
   'tagged_title("关于")' in src, "")
ok("run_gui 安装了全局标题兜底过滤器",
   "installEventFilter(w)" in src, "")

print("\n== 3) 主窗口标题 ==")
_s = inspect.getsource(I.run_gui)
_idx = _s.rfind("    app = QApplication")
_g = dict(I.__dict__)
exec(_s[:_idx] + "    return App\n", _g)
AppCls = _g["run_gui"]()
win = AppCls()
app.processEvents()
_title = win.windowTitle()
print("  标题: %s" % _title)
ok("主窗口标题含版本标识", SUF in _title, _title)
ok("主窗口标题保留「— 源管家」结构", ("— " + I.APP_NAME) in _title, _title)

print("\n== 4) 全局兜底过滤器（覆盖 QMessageBox 等未显式标注窗体）==")
_d1 = QDialog()
_d1.setWindowTitle("提示")          # 模拟 QMessageBox 直接 setWindowTitle
ok("前置：直接设标题时无标识", SUF not in _d1.windowTitle(), _d1.windowTitle())
win.eventFilter(_d1, QEvent(QEvent.WindowTitleChange))
_t1 = _d1.windowTitle()
print("  补标后: %s" % _t1)
ok("兜底过滤器补上版本标识", _t1 == "提示 — " + SUF, _t1)
win.eventFilter(_d1, QEvent(QEvent.WindowTitleChange))
ok("兜底过滤器幂等（不叠加）", _d1.windowTitle() == _t1, _d1.windowTitle())

_d2 = QDialog()                     # 空标题窗体不应被强行加标题
win.eventFilter(_d2, QEvent(QEvent.WindowTitleChange))
ok("空标题窗体保持空（不强行加标题）", _d2.windowTitle() == "", repr(_d2.windowTitle()))

_g2 = dict(I.__dict__)
exec(_s[:_idx] + "    return _ToolboxDialog\n", _g2)
Toolbox = _g2["run_gui"]()
tb = Toolbox(None, [], None, None)
print("  工具箱标题: %s" % tb.windowTitle())
ok("工具箱标题含版本标识", SUF in tb.windowTitle(), tb.windowTitle())

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
