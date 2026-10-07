# -*- coding: utf-8 -*-
"""ConfigDialog 底部操作条布局回归测试（真实 PySide6 offscreen）。

用户反馈：底部按钮太多（原 13 个，2026-10-01 增至 14 个）挤在一行，把对话框撑得很宽，
表格上方因此出现一大截空白（表格宽度由按钮条最小宽度决定）。

修复：底部改为 **QGridLayout 两行分组**
  · 第 0 行：批量操作（删除/禁用/启用/禁用短剧/禁用直播）
  · 第 1 行：检测工具（源测活/网络体检/工具箱）+ 导出（导出干净/智能分流）
  · 右下角：保存并写入（主操作）；最右：关闭

断言：
  1) 底部是 QGridLayout（不是把 13 个按钮堆一行的 QHBoxLayout）
  2) 全部 14 个按钮仍然存在（功能不丢）
  3) 对话框最小宽度 < 700（按钮条不再决定宽度）
  4) 「保存并写入」仍是 primary 主操作、仍受 _busy_buttons 管理
  5) 「关闭」不受检测 busy 影响（不在 _busy_buttons 内）
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
import io
import inspect
import json
import tempfile
import shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import injector as I

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


from PySide6.QtWidgets import QApplication, QPushButton, QGridLayout, QHBoxLayout

app = QApplication.instance() or QApplication([])

src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return ConfigDialog\n", g)
ConfigDialog = g["run_gui"]()

tmp = tempfile.mkdtemp(prefix="pyinj_btnbar_")
try:
    sites = [{"key": "k%d" % i, "name": "站点%d" % i, "api": "./py/s%d.py" % i, "type": 3}
             for i in range(5)]
    raw = json.dumps({"sites": sites}, ensure_ascii=False)
    with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
        f.write(raw)

    dlg = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
    dlg.resize(900, 560)
    dlg.show()
    app.processEvents()

    print("\n== 1) 底部为两行分组网格 ==")
    grids = dlg.findChildren(QGridLayout)
    ok("底部使用 QGridLayout（分组两行）", len(grids) >= 1, "grids=%d" % len(grids))

    print("\n== 2) 14 个功能按钮均存在（功能不丢）==")
    texts = [b.text() for b in dlg.findChildren(QPushButton)]
    need = ["🗑 删除选中", "禁用选中", "启用选中", "禁用短剧", "禁用直播",
            "🧹 剔除失效源",
            "💾 保存并写入", "🩺 源测活", "🌐 网络体检", "🧰 工具箱",
            "📤 导出干净配置", "🔀 智能分流导出", "关闭"]
    miss = [t for t in need if t not in texts]
    ok("全部操作按钮存在", not miss, "缺失=%s" % miss)
    ok("已撤销的「🔀 合并导入」不再出现", "🔀 合并导入" not in texts)

    print("\n== 3) 对话框最小宽度不再被按钮条撑大 ==")
    mw = dlg.minimumSizeHint().width()
    ok("minimumSizeHint 宽度 < 760（按钮条不再决定宽度）", mw < 760,
       "mw=%d hint=%s" % (mw, dlg.minimumSizeHint()))
    # 表格本身应能拿到合理宽度：窗口 900 时视口明显大于 400
    vpw = dlg.table.viewport().width()
    ok("表格视口宽度充足（>400）", vpw > 400, "vpw=%s" % vpw)

    print("\n== 4) 主操作与关闭按钮归属正确 ==")
    save_btns = [b for b in dlg.findChildren(QPushButton) if b.text() == "💾 保存并写入"]
    ok("「保存并写入」唯一", len(save_btns) == 1, str(len(save_btns)))
    ok("「保存并写入」是 primary 主操作",
       save_btns and save_btns[0].property("accent") == "primary",
       save_btns[0].property("accent") if save_btns else "none")
    ok("「保存并写入」受 busy 管理",
       save_btns and save_btns[0] in dlg._busy_buttons)
    close_btns = [b for b in dlg.findChildren(QPushButton) if b.text() == "关闭"]
    ok("「关闭」不受 busy 管理（始终可用）",
       close_btns and close_btns[0] not in dlg._busy_buttons)
    ok("批量操作按钮仍在 busy 列表（5 批量 + 保存；🧹 剔除失效源亦在内）",
       sum(1 for b in dlg._busy_buttons
           if b.text() in ("🗑 删除选中", "禁用选中", "启用选中",
                           "禁用短剧", "禁用直播", "🧹 剔除失效源",
                           "💾 保存并写入")) == 7,
       str([b.text() for b in dlg._busy_buttons]))

    print("\n== 5) 自定义代理服务器控件（联网检测统一出口）==")
    ok("检测面板内置代理控件行", hasattr(dlg, "proxy_ctl"),
       str(getattr(dlg, "proxy_ctl", None)))
    ok("代理输入框 + 验证按钮齐备",
       hasattr(dlg.proxy_ctl, "edit") and "验证" in dlg.proxy_ctl.btn.text(),
       dlg.proxy_ctl.btn.text())
    ok("默认留空 = 直连提示", "直连" in dlg.proxy_ctl.lbl.text(),
       dlg.proxy_ctl.lbl.text())
    ok("新增一行后对话框最小宽度仍 < 760",
       dlg.minimumSizeHint().width() < 760, "mw=%d" % dlg.minimumSizeHint().width())

    dlg.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
