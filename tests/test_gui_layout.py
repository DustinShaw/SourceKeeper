# -*- coding: utf-8 -*-
"""主界面工具栏化冒烟测试（offscreen，无显示器）。

v2026.09.24.e：四步编号 GroupBox 改为顶部工具栏（图标 + 动词优先文字）；
检测区合并为一张卡片（勾选类型 + 共用控制）。"""
import os, sys, io

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import injector

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s" % name)
    else:
        FAIL += 1
        print("[FAIL] %s  %s" % (name, extra))

from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton, QHBoxLayout, QLabel

# 沙箱内禁止真实 GUI：仅构造，不 exec / 不 show
QApplication.exec = lambda self=None: 0

app = QApplication([])

import inspect
# 取出 run_gui 中定义的 App 类：截断函数体到 app = QApplication 之前，改为 return App
s = inspect.getsource(injector.run_gui)
idx = s.rfind("    app = QApplication")
src2 = s[:idx] + "    return App\n"
g = dict(injector.__dict__)
exec(src2, g)
AppCls = g["run_gui"]()
win = AppCls()

ok("App 构造成功", win is not None)

# 工具栏按钮（图标 + 动词优先，去编号）
btn_texts = [b.text() for b in win.findChildren(QPushButton)]
for t in ["📄 注入文件", "🔍 扫描目录", "移除选中", "🗑 清空列表",
          "💾 写入配置", "⚙ 管理站点", "✓ 查重", "♻ 去重", "🔄 刷新", "ℹ 关于"]:
    ok("工具栏按钮存在: " + t, t in btn_texts, str(btn_texts))

# 不再有步骤编号 GroupBox（① ② ③ ④ ⑤ ⑥ 已移除）
gbs = win.findChildren(QGroupBox)
titles = [g.title() for g in gbs]
ok("不再有步骤编号分组框",
   not any(t.startswith(("第一", "第二", "第三", "配置维护")) for t in titles),
   str(titles))
ok("保留全局开关/待注入列表分组",
   any(t.startswith("全局开关") for t in titles)
   and any(t.startswith("待注入列表") for t in titles),
   str(titles))

# 行布局：工具栏是一个 QHBoxLayout
hboxes = [l for l in win.findChildren(QHBoxLayout)]
ok("存在水平布局（工具栏）", len(hboxes) >= 4, str(len(hboxes)))

# 2026-09-30：工具栏按钮从「一行挤 12 个」改为「按维度分两行」——
#   行 1「待注入」= 注入文件/添加直连/扫描目录/移除选中/清空列表 + 写入配置
#   行 2「仓库」  = 管理站点/合并导入/查重/去重/刷新 + 关于
# 用结构判断（不依赖几何，测试不 show 窗口）：12 个按钮应恰好落在两个 QHBoxLayout 里。
print("\n== 工具栏按维度分两行（待注入 / 仓库）==")
TB = ["📄 注入文件", "➕ 添加直连", "🔍 扫描目录", "移除选中", "🗑 清空列表",
      "💾 写入配置", "⚙ 管理站点", "🔀 合并导入", "✓ 查重", "♻ 去重",
      "🔄 刷新", "ℹ 关于"]
row_layouts = []
for lay in win.findChildren(QHBoxLayout):
    txts = []
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if isinstance(w, QPushButton) and w.text() in TB:
            txts.append(w.text())
    if txts:
        row_layouts.append(txts)
ok("工具栏按钮分布在恰好两行", len(row_layouts) == 2,
   "rows=%s" % [len(r) for r in row_layouts])
ok("两行各 6 个按钮（6 + 6）", sorted(len(r) for r in row_layouts) == [6, 6],
   "rows=%s" % [len(r) for r in row_layouts])
ok("两行合计覆盖全部 12 个工具栏按钮（不丢不重）",
   sorted(sum(row_layouts, [])) == sorted(TB), "got=%s" % sorted(sum(row_layouts, [])))
lbls = [l.text() for l in win.findChildren(QLabel)]
ok("两个分组标签存在（待注入 / 仓库）", "待注入" in lbls and "仓库" in lbls, str(lbls))

# 2026-09-30：全局开关里的 type 默认锁定——.py 注入固定 3，「添加直连」自带 1，
# 该开关 normal 下从不参与写入，置灰避免"能全局改 type"的误解。
print("\n== 全局开关 type 默认锁定 ==")
ok("初始无待注入条目 → type 开关置灰锁定", not win.var_type.isEnabled(),
   "enabled=%s" % win.var_type.isEnabled())
ok("锁定时 tooltip 说明原因", "已锁定" in win.var_type.toolTip(), win.var_type.toolTip())
win.pending = [{"key": "py_t", "name": "T", "api": "./py/t.py"}]
win._sync_type_switch()
ok("出现「缺 type」条目 → 自动解锁", win.var_type.isEnabled(),
   "enabled=%s tip=%s" % (win.var_type.isEnabled(), win.var_type.toolTip()))
ok("解锁后 tooltip 提示条数", "1 条" in win.var_type.toolTip(), win.var_type.toolTip())
win.pending = [{"key": "py_t", "name": "T", "api": "./py/t.py", "type": 3}]
win._sync_type_switch()
ok("条目自带 type 后重新锁定", not win.var_type.isEnabled(),
   "enabled=%s" % win.var_type.isEnabled())

win.close()
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
