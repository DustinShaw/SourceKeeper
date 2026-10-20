# -*- coding: utf-8 -*-
"""「复制为新条目」GUI 回归测试（真实 PySide6 offscreen）。

覆盖 ConfigDialog.clone_row 的真实交互链路：
  1) 构造带一条 B 站条目的临时仓库 → 打开「管理站点」对话框
  2) 选中该条目 → 调用 clone_row → 对话框弹出
  3) 模拟填写 key / name / ext → 点「确定」
  4) 断言：配置文本已更新、新条目存在且 ext 正确、源条目未被动
  5) 断言：菜单里存在「复制为新条目」入口

注：ext 里的 mid 会含真实 UP 号以外的自造值，不涉及任何个人数据。
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import json
import shutil
import tempfile
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPlainTextEdit
from PySide6.QtCore import QTimer

import injector as I
import pyinj_core as C

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print("[%s] %-56s %s" % ("OK " if cond else "FAIL", name, extra))


app = QApplication.instance() or QApplication([])

# ConfigDialog 定义在 run_gui() 内部（惰性导入），按既有测试手法取出内层类
# （同 tests/test_toolbox_gui.py：截断 run_gui 源码 → exec → 调用 g["run_gui"]()）
from PySide6.QtWidgets import QMessageBox
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)

_src = inspect.getsource(I.run_gui)
_idx = _src.rfind("    app = QApplication")
_g = dict(I.__dict__)
exec(_src[:_idx] + "    return ConfigDialog\n", _g)
ConfigDialog = _g["run_gui"]()
ok("成功取出内层 ConfigDialog", ConfigDialog is not None)

# ---- 造一个临时仓库（只有 1 个条目，够用且互不干扰）----
RAW = """{
  "spider": "",
  "sites": [
    {
      "key": "py_demo",
      "name": "演示源┃PY",
      "api": "./py/demo.py",
      "filterable": 1,
      "quickSearch": 1,
      "searchable": 1,
      "ext": {
        "mid": "111"
      },
      "file": "./py/demo.py",
      "type": 3
    }
  ]
}
"""

tmp = tempfile.mkdtemp(prefix="clone_gui_")
os.makedirs(os.path.join(tmp, "py"), exist_ok=True)
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(RAW)
with open(os.path.join(tmp, "py", "demo.py"), "w", encoding="utf-8") as f:
    f.write("# demo\nclass Spider:\n    def getName(self): return 'demo'\n")

sites = C.parse_config_text(RAW)["sites"]

print("== 1) 打开「管理站点」对话框 ==")
dlg = ConfigDialog(None, tmp, RAW, sites, "py.json", base_dir=tmp)
dlg._refresh_table()          # _shown 在刷新时才填充
ok("对话框构造成功", dlg is not None)
ok("表格有 1 行", len(dlg._shown) == 1, len(dlg._shown))
# ⚠️ 顺序要点：先 show + processEvents（让 showEvent 里的 singleShot 回调跑完，
#    否则它会在后面触发 _refresh_table 重置选中），再选行。
dlg.show()
app.processEvents()
app.processEvents()
dlg._refresh_table()

print()
print("== 2) 选中条目并调用 clone_row ==")
dlg.table.selectRow(0)
dlg.table.setCurrentCell(0, 0)
app.processEvents()
sel = dlg._sel_entry()
ok("选中的条目 key 正确", sel and sel.get("key") == "py_demo", sel and sel.get("key"))

# 让 clone_row 弹出对话框后自动填表并点确定
captured = {}


def _drive():
    """在 clone_row 弹出的 QDialog 上填表并点确定。"""
    d = app.activeModalWidget()
    if not isinstance(d, QDialog):
        captured["err"] = "未找到模态对话框"
        dlg_done()
        return
    # 找到各输入框（按创建顺序：key, name, api, ext）
    edits = d.findChildren(QLineEdit)
    plains = d.findChildren(QPlainTextEdit)
    captured["n_edit"] = len(edits)
    captured["n_plain"] = len(plains)
    if len(edits) >= 3 and plains:
        edits[0].setText("py_demo_copy")      # 新 key
        edits[1].setText("演示源2┃PY")       # 新 name
        edits[2].setText("./py/demo.py")     # 复用 api
        plains[0].setPlainText(json.dumps({"mid": "222"}, ensure_ascii=False))
        # 点「确定」
        from PySide6.QtWidgets import QDialogButtonBox
        boxes = d.findChildren(QDialogButtonBox)
        for b in boxes:
            b.accepted.emit()
        captured["accepted"] = True
    else:
        captured["err"] = "输入框数量异常 edit=%s plain=%s" % (len(edits), len(plains))
    dlg_done()


def dlg_done():
    d = app.activeModalWidget()
    if isinstance(d, QDialog):
        d.accept()


QTimer.singleShot(50, _drive)
dlg.clone_row()
app.processEvents()

print()
print("== 3) 断言克隆结果 ==")
ok("模态对话框被找到并填写", captured.get("accepted") is True, captured.get("err", ""))
ok("输入框数量符合预期", captured.get("n_edit", 0) >= 3 and captured.get("n_plain", 0) >= 1,
   "edit=%s plain=%s" % (captured.get("n_edit"), captured.get("n_plain")))

new_sites = C.parse_sites_with_disabled(dlg.raw)
objs = [o for o, _ in new_sites]
keys = [o.get("key") for o in objs]
ok("条目数 1 → 2", len(objs) == 2, len(objs))
ok("新 key 已写入", "py_demo_copy" in keys, keys)

new = next((o for o in objs if o.get("key") == "py_demo_copy"), None)
ok("新条目 ext 正确", new and new.get("ext") == {"mid": "222"}, new and new.get("ext"))
ok("新条目 api 复用", new and new.get("api") == "./py/demo.py", new and new.get("api"))

src = next((o for o in objs if o.get("key") == "py_demo"), None)
ok("源条目 ext 未被动", src and src.get("ext") == {"mid": "111"}, src and src.get("ext"))
ok("源条目 name 未被动", src and src.get("name") == "演示源┃PY", src and src.get("name"))
ok("配置仍是合法 JSONC", isinstance(C.parse_jsonc(dlg.raw), dict))
ok("changed 标记已置位", getattr(dlg, "changed", False) is True)

print()
print("== 4) 菜单入口 ==")
import inspect
src_code = inspect.getsource(I)
ok("clone_row 方法已定义", "def clone_row(self)" in src_code)
ok("右键菜单含「复制为新条目」", src_code.count("复制为新条目") >= 2,
   "出现 %d 次" % src_code.count("复制为新条目"))

try:
    dlg.close()
except Exception:
    pass
shutil.rmtree(tmp, ignore_errors=True)

print()
print("CLONE-GUI TEST %s (%d 通过, %d 失败)" % ("OK" if FAIL == 0 else "FAIL", PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
