# -*- coding: utf-8 -*-
"""v2026.09.25.c name 列可见性回归测试（真实 PySide6 offscreen）。
事故：QSettings 记忆的旧布局（key 列时代）列宽错位，把 stretch 的 name 列压成 0 宽，
管理列表只见 api 不见 name（电视机端识别站点靠 name）。
修复：列宽恢复/保存双向 clamp [36,180]。
断言：
  1) 预置超大旧记忆值后构造，api 列（1）宽度被 clamp 到 <=180
  2) name 列（0）宽度 >=60（可见，不再被挤没）
  3) _teardown_persist 保存的值也在 clamp 范围内
  4) name 列内容正确填充（站点中文名）
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import inspect
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import injector as I
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

PASS = 0
FAIL = 0


def ok(cond, msg, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % msg)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (msg, extra))


def main():
    # ---- 取出 ConfigDialog（与 test_gui_real_v14 同手法）----
    src = inspect.getsource(I.run_gui)
    idx = src.rfind("    app = QApplication")
    g = dict(I.__dict__)
    exec(src[:idx] + "    return ConfigDialog\n", g)
    ConfigDialog = g["run_gui"]()

    app = QApplication.instance() or QApplication(sys.argv)

    tmp = tempfile.mkdtemp(prefix="pyinj_namecol_")
    st = QSettings("PyInjector", "PyInjector")
    saved = {}   # 测试前记住已有 colwidth，测完恢复，避免污染真实注册表
    saved_nw = st.value("cfg/namewidth", None) if st.contains("cfg/namewidth") else None
    if st.contains("cfg/namewidth"):
        saved_nw = st.value("cfg/namewidth")
    try:
        sites = [{"key": "k%d" % i, "name": n, "api": "./py/%s.py" % n, "type": 3}
                 for i, n in enumerate(["豆瓣", "青禾影视", "农民影视"])]
        raw = json.dumps({"sites": sites}, ensure_ascii=False)
        with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
            f.write(raw)

        # 预置旧布局遗留的超大列宽（模拟事故现场）
        for c in range(1, 10):
            key = "cfg/colwidth/%d" % c
            if st.contains(key):
                saved[c] = st.value(key)
            st.setValue(key, 800 if c == 1 else 150)
        # 断言 4 依赖「未被手动拖过」= False；显式清掉上轮运行可能残留的分支标志，
        # 否则会被外部注册表状态污染（历史故障：残留 cols_user_resized=True → 误报）
        st.remove("cfg/cols_user_resized")
        st.sync()

        print("\n== name 列可见性（列宽 clamp）==")
        dlg = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
        w0, w1 = dlg.table.columnWidth(0), dlg.table.columnWidth(1)
        ok(w1 <= 240, "api 列宽在合理范围（<=240，按内容自适应）", "w1=%s" % w1)
        ok(w0 >= 60, "name 列宽 >=60（可见，不被挤没）", "w0=%s" % w0)
        ok(all(dlg.table.item(r, 0).text() == sites[r]["name"] for r in range(3)),
           "name 列填充站点中文名")
        # 新行为：未手动拖过列宽时，_teardown_persist 不写入 cfg/colwidth/*（保持按内容自适应）
        dlg._teardown_persist()
        w_saved = st.value("cfg/colwidth/1", 0, type=int)
        ok(w_saved == 0,
           "_teardown_persist 未污染列宽（无手动拖动则不写 cfg/colwidth）",
           "saved=%s" % w_saved)

        # 窄窗口复现（用户实测 737px 对话框）：stretch name 列曾被压到 ~17px。
        # 修复 = hdr.setMinimumSectionSize(76)：空间不足时出横向滚动条，name 列保底 76px。
        print("\n== 窄窗口（737px）name 列保底 ==")
        dlg.resize(737, 560)
        dlg.show()
        app.processEvents()
        app.processEvents()
        w0n = dlg.table.columnWidth(0)
        ok(w0n >= 76, "窄窗口下 name 列 >=76（minimumSectionSize 保底）", "w0=%s" % w0n)
        sb = dlg.table.horizontalScrollBar()
        ok(sb.maximum() > 0 or dlg.table.viewport().width() >=
           sum(dlg.table.columnWidth(c) for c in range(10)),
           "空间不足时出现横向滚动条（列不再互相挤压）",
           "sbmax=%s" % sb.maximum())
        dlg.close()
    finally:
        # 清理：恢复测试前的键值
        for c in range(1, 10):
            key = "cfg/colwidth/%d" % c
            if c in saved:
                st.setValue(key, saved[c])
            else:
                st.remove(key)
        if saved_nw is not None:
            st.setValue("cfg/namewidth", saved_nw)
        else:
            st.remove("cfg/namewidth")
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
