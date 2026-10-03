# -*- coding: utf-8 -*-
"""验证：查看/修改配置表格的行号列（垂直表头）底色与数据行斑马纹逐行一致。
真实 PySide6 offscreen 渲染 ConfigDialog 的表格到 QImage 后采样像素比对。
需在带 PySide6 的 venv 下运行：envs/default/Scripts/python.exe"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import inspect
import tempfile

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
from PySide6.QtGui import QImage, QColor

# 避免任何弹框阻塞
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Yes)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QWidget.show = lambda self: None
QDialog.exec = lambda self: 1

import injector as I

tmp = tempfile.mkdtemp(prefix="pyinj_zebra_")
RAW = '''{
  "spider": "x",
  "sites": [
    {"key": "py_a", "name": "A┃PY", "api": "./py/a.py", "type": 3},
    {"key": "py_b", "name": "B┃PY", "api": "./py/b.py", "type": 3},
    {"key": "py_c", "name": "C┃PY", "api": "./py/c.py", "type": 3},
    {"key": "py_d", "name": "D┃PY", "api": "./py/d.py", "type": 3}
  ]
}'''
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(RAW)
sites = I.parse_jsonc(RAW).get("sites", [])

# 取出 ConfigDialog（真实 Qt，不启动 run_gui 主循环）
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
src2 = src[:idx] + "    return ConfigDialog\n"
g = dict(I.__dict__)
exec(src2, g)
ConfigDialog = g["run_gui"]()

app = QApplication.instance() or QApplication(sys.argv)
dlg = ConfigDialog(None, tmp, RAW, sites, "py.json", tmp)
# 行存在即可渲染验证（后台检测只影响文字，不影响底色）
for _ in range(10):
    app.processEvents()

t = dlg.table
t.resize(700, 400)
img = QImage(max(700, t.width()), max(400, t.height()), QImage.Format_ARGB32)
img.fill(0xFFFFFFFF)
t.render(img)

vhw = t.verticalHeader().width()
hh = t.horizontalHeader().height()
rowh = t.rowHeight(0) if t.rowCount() else 24
ok("表格有 4 行", t.rowCount() == 4, "rows=%s" % t.rowCount())
ok("行号列宽度>0", vhw > 0, "vhw=%s" % vhw)


def px(x, y):
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


# 采样点避开文字：行号列取左侧 x=3；数据单元格取行顶部 3px 处（避开垂直居中的文字）
mismatch = []
for r in range(min(4, t.rowCount())):
    y = hh + r * rowh + 3
    c_num = px(3, y)
    c_dat = px(vhw + 30, y)
    match = c_num == c_dat
    print("  行%d: 行号列=%s 数据行=%s %s" % (r + 1, c_num, c_dat, "一致" if match else "不一致"))
    if not match:
        mismatch.append((r, c_num, c_dat))

ok("行号列与数据行底色逐行一致", not mismatch, str(mismatch))
# 斑马纹存在性：4 行应出现两种底色
colors = {px(3, hh + r * rowh + rowh // 2) for r in range(min(4, t.rowCount()))}
ok("行号列出现两种底色（斑马纹）", len(colors) == 2, str(colors))

dlg._closed = True
import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
