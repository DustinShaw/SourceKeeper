# -*- coding: utf-8 -*-
"""「编辑站点」对话框：扩展参数 ext 编辑框高度动态伸缩（真实 Qt offscreen）
===================================================================
需求（2026-09-30 用户反馈）：
  ext 多行编辑框初始不要占太大高度，**有内容才按行数动态展开**。

断言口径（不依赖窗口 show，取 min/max 高度，setFixedHeight 会同步二者）：
  1) setFixedHeight → minimumHeight == maximumHeight（高度被真正锁定）
  2) 空 ext / 单行 ext   → 高度 = 2 行（紧凑）
  3) 多行 ext            → 高度随行数增长，且 ≈ 行数 × 行距 + 14
  4) 内容增长/清空       → textChanged 后高度随之增减
  5) 超长内容            → 高度封顶在 10 行（超出走内部滚动，不无限撑大）

用法：envs/default/Scripts/python.exe test_ext_editor.py
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import io
import json
import time
import inspect
import tempfile
import shutil

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


import injector as I
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit

QApplication.exec = lambda self=None: 0
QDialog.exec = lambda self: 1          # 手动覆盖为抓取式（见下）

app = QApplication.instance() or QApplication(sys.argv)

# ---- 夹具：两个站点（无 ext / 6 键多行 ext）----
EXT_OBJ = {
    "dataKey": "D2KREWR1BVNAUUJYEDL4FVHOY2Q0PQ==",
    "dataIv": "OC1A06E197EF10CF3F6058CA7A803B5E",
    "pkg": "com.dytiantang.one",
    "host": "",
    "site": "https://dyttandroid04-1372779881.cos.ap-shanghai.myqcloud.com/",
    "n": 0,
}
EXT_LINES = len(json.dumps(EXT_OBJ, ensure_ascii=False, indent=2).split("\n"))  # = 8

tmp = tempfile.mkdtemp(prefix="pyinj_extui_")
os.makedirs(os.path.join(tmp, "py"))
for n in ("plain.py", "withex.py"):
    with open(os.path.join(tmp, "py", n), "w", encoding="utf-8") as f:
        f.write("# stub\n")

RAW = json.dumps({
    "sites": [
        {"key": "py_plain", "name": "无扩展", "api": "py/plain.py", "type": 3},
        {"key": "py_ext", "name": "带扩展", "api": "py/withex.py", "type": 3,
         "ext": EXT_OBJ, "jar": ""},
    ]
}, ensure_ascii=False, indent=2)
cfg = os.path.join(tmp, "py.json")
with open(cfg, "w", encoding="utf-8") as f:
    f.write(RAW)
sites_active = I.parse_jsonc(RAW).get("sites", [])

# ---- 取出 ConfigDialog（真实 Qt）----
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return ConfigDialog\n", g)
ConfigDialog = g["run_gui"]()

dlg = ConfigDialog(None, tmp, RAW, sites_active, "py.json", tmp)
ok("ConfigDialog 构造成功", dlg is not None)

# 抓取式 exec：编辑框只在 edit_row 栈帧内存在，必须在 exec 时刻抓取
cap = {}


def _grab_exec(self):
    cap["editors"] = list(self.findChildren(QPlainTextEdit))
    return 1


QDialog.exec = _grab_exec


def open_editor(row):
    cap.clear()
    dlg.table.selectRow(row)
    dlg.edit_row()
    eds = cap.get("editors") or []
    return eds[-1] if eds else None


def lh_of(ed):
    return int(ed.fontMetrics().lineSpacing())


print("\n== 1) 空 ext → 紧凑（2 行）==")
ed0 = open_editor(0)
ok("抓到 ext 编辑框", ed0 is not None)
if ed0 is not None:
    lh = lh_of(ed0)
    h0 = ed0.minimumHeight()
    ok("高度被 setFixedHeight 锁定(min==max)",
       ed0.minimumHeight() == ed0.maximumHeight(),
       "min=%s max=%s" % (ed0.minimumHeight(), ed0.maximumHeight()))
    ok("空 ext 高度 = 2 行（紧凑）", h0 == 2 * lh + 14, "h=%s lh=%s" % (h0, lh))
    ok("空 ext 高度不再固定 120+（旧行为）", h0 < 120, "h=%s" % h0)
    ok("有 placeholder 提示",
       bool(ed0.placeholderText()) and "扩展参数" in ed0.placeholderText(),
       ed0.placeholderText())

print("\n== 2) 多行 ext → 按行数展开 ==")
row_ext = 1
ed1 = open_editor(row_ext)
ok("抓到 ext 编辑框（带内容）", ed1 is not None)
if ed1 is not None:
    lh = lh_of(ed1)
    ok("预填内容行数 = %d" % EXT_LINES, ed1.toPlainText().count("\n") + 1 == EXT_LINES,
       repr(ed1.toPlainText()[:40]))
    ok("高度 = %d 行 × 行距 + 14" % EXT_LINES,
       ed1.minimumHeight() == EXT_LINES * lh + 14,
       "h=%s expect=%s" % (ed1.minimumHeight(), EXT_LINES * lh + 14))
    ok("带内容高度 > 空 ext 高度", ed1.minimumHeight() > ed0.minimumHeight(),
       "%s vs %s" % (ed1.minimumHeight(), ed0.minimumHeight()))

    print("\n== 3) textChanged → 高度动态跟随 ==")
    ed1.setPlainText("{}")
    app.processEvents()
    ok("缩到 1 行 → 回落 2 行紧凑", ed1.minimumHeight() == 2 * lh + 14,
       "h=%s" % ed1.minimumHeight())

    ed1.setPlainText("{\n" + "\n".join('  "k%d": 1,' % i for i in range(4)) + "\n}")
    app.processEvents()
    ok("4 键（6 行）→ 高度 = 6 行", ed1.minimumHeight() == 6 * lh + 14,
       "h=%s expect=%s" % (ed1.minimumHeight(), 6 * lh + 14))

    ed1.setPlainText("")
    app.processEvents()
    ok("清空 → 回到 2 行紧凑", ed1.minimumHeight() == 2 * lh + 14,
       "h=%s" % ed1.minimumHeight())

    print("\n== 4) 超长内容 → 封顶 10 行 ==")
    ed1.setPlainText("{\n" + "\n".join('  "k%d": 1,' % i for i in range(30)) + "\n}")
    app.processEvents()
    ok("30 键（32 行）→ 高度封顶 10 行",
       ed1.minimumHeight() == 10 * lh + 14,
       "h=%s expect=%s" % (ed1.minimumHeight(), 10 * lh + 14))
    ok("封顶高度小于旧行为的大块占位",
       ed1.minimumHeight() <= 10 * lh + 14, "h=%s" % ed1.minimumHeight())

# 等后台检测线程收尾，避免退出告警
deadline = time.time() + 20
while time.time() < deadline:
    app.processEvents()
    if not (dlg._file_checking or getattr(dlg, "_scanning", False)
            or getattr(dlg, "_url_scanning", False)):
        break
    time.sleep(0.03)
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
