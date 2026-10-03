# -*- coding: utf-8 -*-
"""v2026.09.24 UI 改版测试（真实 PySide6 offscreen）：
1. 表格去掉 key 列：共 10 列，表头 name 开头；
2. api 列链接化：本地源蓝色下划线 + tooltip；远程源灰色无下划线；
3. 双击除 api 列外的列弹出编辑（api 列单击=打开 .py，双击不弹编辑）；
4. 「禁用选中/启用选中」按钮按选中项状态联动（无选中双灰 / 启用项仅禁用亮 / 禁用项仅启用亮，
   禁用后按钮自动翻转）；
5. CLI --version 输出「PyInjector v<APP_VERSION>」。
"""
import io
import os
import sys
import time
import json as _json
import shutil
import subprocess
import tempfile
import inspect

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


tmp = tempfile.mkdtemp(prefix="pyinj_uifix_")
py_dir = os.path.join(tmp, "py")
os.makedirs(py_dir)
for n in ("live.py", "off.py"):
    with open(os.path.join(py_dir, n), "w", encoding="utf-8") as f:
        f.write("class Spider:\n    pass\n")

RAW = """{
"sites": [
{"key":"py_live","name":"Live┃PY","api":"./py/live.py","type":3,"filterable":1,"quickSearch":1,"searchable":1},
/* [disabled]
{"key":"py_off","name":"Off┃PY","api":"./py/off.py","type":3,"filterable":1,"quickSearch":1,"searchable":1},
*/
{"key":"py_remote","name":"Remote┃PY","api":"http://x.com/y.py","type":3,"filterable":1,"quickSearch":1,"searchable":1}
]}
"""
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(RAW)

import injector as I
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

app = QApplication.instance() or QApplication([])

src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
src2 = src[:idx] + "    return ConfigDialog\n"
g = dict(I.__dict__)
exec(src2, g)
ConfigDialog = g["run_gui"]()

sites_active = I.parse_jsonc(RAW)["sites"]   # parse_jsonc 容忍注释；_disabled 由 ConfigDialog 依 raw 标定
dlg = ConfigDialog(None, tmp, RAW, sites_active, "py.json", tmp)
app.processEvents()

print("== 1) key 列已移除 ==")
ok("表格 10 列", dlg.table.columnCount() == 10, str(dlg.table.columnCount()))
headers = [dlg.table.horizontalHeaderItem(c).text() for c in range(dlg.table.columnCount())]
ok("表头 name 开头、无 key", headers[0] == "name" and "key" not in headers, str(headers))
ok("表头顺序完整", headers == ["name", "api", "类型", "筛选/快搜/搜", "成人", "短剧", "直播", "可达", "禁用", "资源"],
   str(headers))
col0 = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())]
ok("第 0 列是 name 而非 key", col0 == ["Live┃PY", "Off┃PY", "Remote┃PY"], str(col0))

print("== 2) api 列链接化 ==")
a_local = dlg.table.item(0, 1)
a_off = dlg.table.item(1, 1)
a_remote = dlg.table.item(2, 1)
ok("本地源 api 蓝色", a_local.foreground().color().getRgb()[:3] == (0, 102, 204),
   str(a_local.foreground().color().getRgb()[:3]))
ok("本地源 api 下划线", a_local.font().underline() is True)
ok("本地源 api tooltip 含打开", "打开" in a_local.toolTip(), a_local.toolTip())
ok("远程源 api 灰色", a_remote.foreground().color().getRgb()[:3] == (110, 110, 110),
   str(a_remote.foreground().color().getRgb()[:3]))
ok("远程源 api 无下划线", a_remote.font().underline() is False)
ok("已禁用项 api 仍为链接样式（本地源）", a_off.foreground().color().getRgb()[:3] == (0, 102, 204))

print("== 3) 双击编辑（api 列除外）==")
edit_calls = []
orig_edit = dlg.edit_row
dlg.edit_row = lambda: edit_calls.append(1)
try:
    dlg._on_row_double_clicked(0, 0)   # name 列
    ok("双击 name 列触发编辑", edit_calls == [1], str(edit_calls))
    edit_calls.clear()
    dlg._on_row_double_clicked(0, 1)   # api 列
    ok("双击 api 列不触发编辑", edit_calls == [], str(edit_calls))
    edit_calls.clear()
    dlg._on_row_double_clicked(0, 8)   # 禁用列
    ok("双击禁用列触发编辑", edit_calls == [1], str(edit_calls))
finally:
    dlg.edit_row = orig_edit

print("== 4) 禁用/启用按钮状态联动 ==")
ok("初始无选中：双灰", not dlg._btn_disable.isEnabled() and not dlg._btn_enable.isEnabled())
dlg.table.selectRow(0)          # py_live（启用项）
app.processEvents()
ok("选中启用项：禁用亮/启用灰",
   dlg._btn_disable.isEnabled() and not dlg._btn_enable.isEnabled())
dlg.table.selectRow(1)          # py_off（禁用项）
app.processEvents()
ok("选中禁用项：启用亮/禁用灰",
   dlg._btn_enable.isEnabled() and not dlg._btn_disable.isEnabled())
# 选中 py_live 后点「禁用选中」→ 状态翻转，按钮自动反转（无需重新选择）
dlg.table.selectRow(0)
app.processEvents()
dlg.disable_selected()
app.processEvents()
ok("禁用动作生效", dlg._shown[0].get("_disabled") is True)
ok("禁用后按钮自动翻转：启用亮/禁用灰",
   dlg._btn_enable.isEnabled() and not dlg._btn_disable.isEnabled())
# 恢复
dlg.enable_selected()
app.processEvents()
ok("启用后按钮回到：禁用亮/启用灰",
   dlg._btn_disable.isEnabled() and not dlg._btn_enable.isEnabled())
ok("恢复后 py_live 已启用", not dlg._shown[0].get("_disabled"))

print("== 4b) 多选批量禁用/启用（v2026.09.24.b） ==")
from PySide6.QtCore import QItemSelectionModel
# 混合多选：第 0 行 py_live（启用）+ 第 1 行 py_off（预置禁用）
dlg.table.selectionModel().clearSelection()
for r in (0, 1):
    dlg.table.selectionModel().select(
        dlg.table.model().index(r, 0),
        QItemSelectionModel.Select | QItemSelectionModel.Rows)
app.processEvents()
ok("混合多选：两按钮同时亮",
   dlg._btn_disable.isEnabled() and dlg._btn_enable.isEnabled())
# 批量禁用 → py_live 被禁用，py_off 原样
dlg.disable_selected()
app.processEvents()
ok("批量禁用后两行均禁用",
   dlg._shown[0].get("_disabled") is True and dlg._shown[1].get("_disabled") is True)
ok("批量禁用后按钮：启用亮/禁用灰",
   dlg._btn_enable.isEnabled() and not dlg._btn_disable.isEnabled())
# 批量启用 → 两行均恢复
dlg.enable_selected()
app.processEvents()
ok("批量启用后两行均启用",
   not dlg._shown[0].get("_disabled") and not dlg._shown[1].get("_disabled"))
ok("批量启用后按钮：禁用亮/启用灰",
   dlg._btn_disable.isEnabled() and not dlg._btn_enable.isEnabled())
ok("raw 中 py_live/py_off 均不在禁用集合",
   all(k not in I.parse_disabled_keys(dlg.raw) for k in ("py_live", "py_off")))

print("== 5b) 体验增强（v2026.09.24.c） ==")
from PySide6.QtCore import Qt as _Qt
ok("搜索框内置清空 ×", dlg.search_edit.isClearButtonEnabled())
ok("表格右键菜单已接线",
   dlg.table.contextMenuPolicy() == _Qt.ContextMenuPolicy.CustomContextMenu)
dlg._toast("toast测试提示")
app.processEvents()
ok("toast 瞬时提示显示", "toast测试提示" in dlg.lbl_toast.text())
dlg.table.selectAll()
app.processEvents()
dlg.disable_selected()
app.processEvents()
ok("批量禁用走 toast 而非弹窗", "已禁用" in dlg.lbl_toast.text(),
   dlg.lbl_toast.text())
ok("计数行含已禁用数", "已禁用 3" in dlg.lbl_count.text(),
   dlg.lbl_count.text())
_orig_exec = QMessageBox.exec
dlg.enable_selected()
app.processEvents()
# 暂存一个删除（不写入）→ 计数行出现「未保存更改」圆点
QMessageBox.exec = lambda self: QMessageBox.Yes
dlg.table.selectRow(2)
dlg.del_row()
app.processEvents()
ok("暂存删除后计数行含未保存更改提示", "未保存更改" in dlg.lbl_count.text(),
   dlg.lbl_count.text())
QMessageBox.exec = _orig_exec

print("== 5) --version 与标题 ==")
p = subprocess.run([sys.executable, os.path.join(HERE, "injector.py"), "--version"],
                   capture_output=True, timeout=60)
out = p.stdout.decode("utf-8", "ignore")
ok("--version rc=0", p.returncode == 0, "rc=%s err=%s" % (p.returncode, p.stderr[:150]))
ok("--version 输出 v<APP_VERSION>", ("源管家 v%s" % I.APP_VERSION) in out, out[:100])
ok("APP_TITLE 不再含版本号（版本移入「关于」）", ("v%s" % I.APP_VERSION) not in I.APP_TITLE, I.APP_TITLE)
ok("版本号保留在 APP_VERSION（供关于框展示）", bool(I.APP_VERSION), I.APP_VERSION)

print("== 6) 选中/悬停样式（v2026.09.24.a） ==")
ss = dlg.table.styleSheet()
ok("选中色为淡蓝 #cfe4f7", "QTableWidget::item:selected { background: #cfe4f7" in ss)
ok("未选中悬停不显示高亮", "QTableWidget::item:!selected:hover { background: transparent; }" in ss)

print("== 7) 空状态提示（v2026.09.24.d） ==")
ok("空状态 label 存在", hasattr(dlg, "empty_label") and dlg.empty_label is not None)
ok("初始有数据：空状态隐藏", dlg.empty_label.isHidden() is True)
dlg.search_edit.setText("zzz_不存在关键字_zzz")
app.processEvents()
ok("搜索无结果：空状态显示", dlg.empty_label.isHidden() is False)
ok("空状态文字正确", "没有匹配的站点" in dlg.empty_label.text(), dlg.empty_label.text())
dlg._clear_search()
app.processEvents()
ok("清空搜索：空状态重新隐藏", dlg.empty_label.isHidden() is True)

print("== 8) 主窗口工具栏图标 + 拖拽注入（v2026.09.24.d） ==")
src_app = inspect.getsource(I.run_gui)
idx2 = src_app.rfind("    app = QApplication")
g2 = dict(I.__dict__)
exec(src_app[:idx2] + "    return App\n", g2)
AppCls = g2["run_gui"]()
win = AppCls()
btn_texts = [b.text() for b in win.findChildren(QPushButton)]
for t in ["📄 注入文件", "🔍 扫描目录", "💾 写入配置", "⚙ 管理站点"]:
    ok("工具栏图标按钮: " + t, t in btn_texts, str(btn_texts))
ok("主窗口接受拖放", win.acceptDrops() is True)
# 拖拽注入复用 _inject_files：拖入一个全新 .py
win.repo_dir = tmp
win.base_dir = tmp
win.cfg_file = "py.json"
win.raw, win.sites, win.existing_keys, win.existing_apis = I.load_repo(tmp, "py.json")
new_py = os.path.join(tmp, "dragme.py")
with open(new_py, "w", encoding="utf-8") as f:
    f.write("class Spider:\n    def getName(self):\n        return 'DragMe'\n")
win._inject_files([new_py])
ok("拖拽注入加入待注入条目", len(win.pending) == 1,
   str([e.get("api") for e in win.pending]))
if win.pending:
    ok("拖入条目 api 指向 dragme.py",
       os.path.basename(win.pending[0].get("api", "")).replace(".py", "") == "dragme",
       str(win.pending[0]))
win.close()

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
