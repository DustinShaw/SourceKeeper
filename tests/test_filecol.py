# -*- coding: utf-8 -*-
"""v14.11 「文件」列测试（真实 PySide6 offscreen）：
打开 ConfigDialog 即自动后台检测 .py 存在性，异常在「文件」列标示：
  缺失（红）/ 已找回（橙，py 文件夹被改名移动后遍历定位）/ 远程（灰）/ 正常（绿），
并在检测分组标题给出汇总；点击「文件」列表头可按异常程度排序。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import time
import inspect
import tempfile
import shutil

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

QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Yes)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QWidget.show = lambda self: None
QDialog.exec = lambda self: 1

import injector as I

# ---- 测试仓库：正常 / 缺失 / 被移动（可遍历找回）/ 远程 ----
tmp = tempfile.mkdtemp(prefix="pyinj_filecol_")
os.makedirs(os.path.join(tmp, "py"))
os.makedirs(os.path.join(tmp, "moved"))
with open(os.path.join(tmp, "py", "ok.py"), "w", encoding="utf-8") as f:
    f.write("class Spider:\n    pass\n")
with open(os.path.join(tmp, "moved", "reloc.py"), "w", encoding="utf-8") as f:
    f.write("class Spider:\n    pass\n")

RAW = '''{
  "spider": "x",
  "sites": [
    {"key": "py_ok", "name": "OK┃PY", "api": "./py/ok.py", "type": 3},
    {"key": "py_gone", "name": "Gone┃PY", "api": "./py/gone.py", "type": 3},
    {"key": "py_reloc", "name": "Reloc┃PY", "api": "./py/reloc.py", "type": 3},
    {"key": "dr_remote", "name": "Remote┃PY", "api": "http://example.com/x.py", "type": 3}
  ]
}'''
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(RAW)
sites_active = I.parse_jsonc(RAW).get("sites", [])

src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
src2 = src[:idx] + "    return ConfigDialog\n"
g = dict(I.__dict__)
exec(src2, g)
ConfigDialog = g["run_gui"]()

app = QApplication.instance() or QApplication(sys.argv)

print("== 构造 ConfigDialog（自动启动 .py 存在性检测）==")
dlg = ConfigDialog(None, tmp, RAW, sites_active, "py.json", tmp)
ok("构造后即启动文件检测", dlg._file_checking is True or len(dlg.file_map) > 0)

deadline = time.time() + 30
while time.time() < deadline:
    app.processEvents()
    if not dlg._file_checking:
        break
    time.sleep(0.03)
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)

ok("文件检测已完成", dlg._file_checking is False)
ok("py_ok 正常", dlg.file_map.get("py_ok") == "normal", str(dlg.file_map))
ok("py_gone 缺失", dlg.file_map.get("py_gone") == "missing", str(dlg.file_map))
ok("py_reloc 已找回", dlg.file_map.get("py_reloc") == "relocated", str(dlg.file_map))
ok("py_reloc 找回路径指向 moved/", dlg.file_reloc.get("py_reloc", "").endswith(
    os.path.join("moved", "reloc.py")), str(dlg.file_reloc))
ok("dr_remote 标记远程", dlg.file_map.get("dr_remote") == "remote", str(dlg.file_map))

# 文件列显示（按 entries 顺序：ok/gone/reloc/remote）（v15 起为第 9 列）
col8 = [dlg.table.item(r, 9).text() for r in range(dlg.table.rowCount())]
ok("文件列文本正确", col8 == ["正常", "缺失", "已找回", "远程"], str(col8))

# 异常颜色：缺失=红、已找回=橙
c_gone = dlg.table.item(1, 9).foreground().color().getRgb()[:3]
c_reloc = dlg.table.item(2, 9).foreground().color().getRgb()[:3]
ok("缺失标红", c_gone == (200, 30, 30), str(c_gone))
ok("已找回标橙", c_reloc == (200, 130, 20), str(c_reloc))

# 分组标题汇总
ok("分组标题含缺失汇总", "缺失 1 个" in dlg.detect_grp.title(), dlg.detect_grp.title())
ok("分组标题含找回汇总", "已找回 1 个" in dlg.detect_grp.title(), dlg.detect_grp.title())

# 点击「文件」列表头排序：缺失排最前
print("== 点击文件列表头排序 ==")
dlg._on_header_clicked(9)
app.processEvents()
first_key = str(dlg._shown[0].get("key", ""))   # key 列已从表格移除，从数据侧取
first_file = dlg.table.item(0, 9).text()
ok("排序后缺失行排最前", first_key == "py_gone" and first_file == "缺失",
   "%s / %s" % (first_key, first_file))

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
