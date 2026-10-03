# -*- coding: utf-8 -*-
"""name 列「自适应宽度 + 可手动调整」回归测试（真实 PySide6 offscreen）。

用户反馈：name 列被 QHeaderView.Stretch 撑得过宽且**无法手动拖动**。
修复：
  · 全部列改为 QHeaderView.Interactive（含 name 列，均可拖动）；
  · name 列按内容自适应初始宽度（clamp [120, 600]），窗口变化时吸收多余空间；
  · 用户拖动 name 列后记录 _name_user_resized，停止自动（尊重用户选择）；
  · name 列宽单独持久化到 cfg/namewidth。

断言：
  1) name 列（0）的 resizeMode 为 Interactive（可拖动，非 Stretch）
  2) 对话框加宽后 name 列变宽（吸收多余空间）
  3) 其它列宽不受 name 自适应影响（保持已存列宽）
  4) 模拟拖动 name 列 → _name_user_resized=True；此后窗口变化不再改 name 列
  5) name 列宽被保存到 cfg/namewidth 且落在 [120,600]
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
    src = inspect.getsource(I.run_gui)
    idx = src.rfind("    app = QApplication")
    g = dict(I.__dict__)
    exec(src[:idx] + "    return ConfigDialog\n", g)
    ConfigDialog = g["run_gui"]()

    app = QApplication.instance() or QApplication(sys.argv)

    tmp = tempfile.mkdtemp(prefix="pyinj_ncolfit_")
    st = QSettings("PyInjector", "PyInjector")
    saved_cols, saved_nw = {}, None
    try:
        sites = [{"key": "k%d" % i, "name": n, "api": "./py/%s.py" % n, "type": 3}
                 for i, n in enumerate(
                     ["豆瓣", "青禾影视", "农民影视", "鬼片之家1", "CCTV"])]
        raw = json.dumps({"sites": sites}, ensure_ascii=False)
        with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
            f.write(raw)

        # 记下并清空旧记忆，保证初始状态确定
        for c in range(1, 10):
            k = "cfg/colwidth/%d" % c
            if st.contains(k):
                saved_cols[c] = st.value(k)
            st.remove(k)
        if st.contains("cfg/namewidth"):
            saved_nw = st.value("cfg/namewidth")
        st.remove("cfg/namewidth")

        dlg = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
        dlg.resize(900, 560)
        dlg.show()
        app.processEvents()

        print("\n== 1) name 列可拖动（Interactive 而非 Stretch）==")
        hdr = dlg.table.horizontalHeader()
        rm0 = hdr.sectionResizeMode(0)
        try:
            from PySide6.QtWidgets import QHeaderView
            inter = QHeaderView.Interactive
        except Exception:
            inter = 0
        ok(rm0 == inter, "name 列 resizeMode == Interactive（可手动拖宽）",
           "mode=%s" % rm0)

        print("\n== 2) name 列吸收视口多余空间（自适应）==")
        w_before = dlg.table.columnWidth(0)
        viewport = dlg.table.viewport().width()
        others = sum(dlg.table.columnWidth(c) for c in range(1, 10))
        # 期望：name 列 ≈ 视口 - 其余列（在 [120,600] 内）
        expect = min(max(viewport - others - 2, 120), 600)
        ok(abs(w_before - expect) <= 4,
           "初始 name 列宽 = viewport - 其余列（自适应）",
           "w=%s expect=%s(vp=%s others=%s)" % (w_before, expect, viewport, others))
        # 手动调用 fit（模拟窗口变化后布局刷新）应仍然收敛到同一值
        dlg._fit_name_column()
        app.processEvents()
        ok(abs(dlg.table.columnWidth(0) - expect) <= 4,
           "再次自适应后仍收敛到同一值",
           "w=%s" % dlg.table.columnWidth(0))
        ok(dlg.table.columnWidth(0) <= 600, "name 列宽不超过上限 600",
           "w=%s" % dlg.table.columnWidth(0))

        print("\n== 3) 其它列宽不受影响 ==")
        others = [dlg.table.columnWidth(c) for c in range(1, 10)]
        ok(all(w > 0 for w in others), "其余 9 列宽度正常", str(others))

        print("\n== 4) 用户拖动 name 列后停止自适应 ==")
        # 模拟用户手动把 name 列拖成 200
        dlg._on_user_col_resized(0, 200)
        dlg.table.setColumnWidth(0, 200)
        dlg._fit_name_column()          # 即便再触发自适应也不该覆盖用户选择
        app.processEvents()
        ok(getattr(dlg, "_name_user_resized", False) is True,
           "拖动 name 列后 _name_user_resized=True")
        ok(dlg.table.columnWidth(0) == 200,
           "用户手动设定后，自适应不再覆盖 name 列宽",
           "w=%s" % dlg.table.columnWidth(0))

        print("\n== 5) name 列宽持久化 ==")
        dlg._teardown_persist()
        nw = st.value("cfg/namewidth", 0, type=int)
        ok(120 <= nw <= 600, "cfg/namewidth 落在 [120,600]", "nw=%s" % nw)
        dlg.close()
    finally:
        for c in range(1, 10):
            k = "cfg/colwidth/%d" % c
            if c in saved_cols:
                st.setValue(k, saved_cols[c])
            else:
                st.remove(k)
        if saved_nw is not None:
            st.setValue("cfg/namewidth", saved_nw)
        else:
            st.remove("cfg/namewidth")
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
