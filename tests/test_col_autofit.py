# -*- coding: utf-8 -*-
"""非 name 列「按内容自适应」回归测试（真实 PySide6 offscreen）。

用户反馈：除 api 外的其它列（类型/筛选/成人/短剧/直播/可达/禁用/资源）
实际宽度远超自身内容需求，明显过宽。

根因：
  · `hdr.setMinimumSectionSize(76)` 把**每一列**最小宽度锁到 76px；
  · 且 `resizeColumnsToContents()` 在**表格还空着**时（构造期）执行，
    之后才 `_refresh_table()` 灌数据 → 宽度没跟上真实内容；
  · QSettings 回放的旧偏宽值又叠加。

修复：新增 `_auto_fit_other_columns()`，在 `_refresh_table()` **填完数据后**，
逐列按「表头 + 全部单元格」需求宽取值，再用各列专属 [min,max] 夹紧；
全局 `minimumSectionSize` 降到 46（不再把短列顶宽）。

断言：
  1) 短内容列宽接近其内容需求（不出现远超内容的宽列）
  2) 各列宽不超过其 COL_MAX 上限
  3) 总和贴合视口（name 列吸收了剩余空间，无大片浪费）
  4) 用户拖动任一非 name 列后 _cols_user_resized=True，不再自动收缩
  5) 内容变长后（重新灌数据）列宽随之增大
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


from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

app = QApplication.instance() or QApplication([])

src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return ConfigDialog\n", g)
ConfigDialog = g["run_gui"]()

tmp = tempfile.mkdtemp(prefix="pyinj_autofit_")
st = QSettings("PyInjector", "PyInjector")
saved = {}


def _mk_dlg(names, apis=None):
    sites = []
    for i, n in enumerate(names):
        api = (apis[i] if apis else "./py/s%d.py" % i)
        sites.append({"key": "k%d" % i, "name": n, "api": api, "type": 3,
                      "filterable": 1, "quickSearch": 1, "searchable": 1})
    raw = json.dumps({"sites": sites}, ensure_ascii=False)
    with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
        f.write(raw)
    d = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
    d.resize(1000, 560)
    d.show()
    for _ in range(6):
        app.processEvents()
    return d, sites


try:
    # 清掉旧列宽记忆，保证测的是纯「按内容自适应」
    for c in range(1, 10):
        k = "cfg/colwidth/%d" % c
        if st.contains(k):
            saved[k] = st.value(k)
        st.remove(k)
    for k in ("cfg/namewidth", "cfg/cols_user_resized"):
        if st.contains(k):
            saved[k] = st.value(k)
        st.remove(k)

    print("\n== 1) 短内容列不过宽 ==")
    d, _ = _mk_dlg(["豆瓣", "青禾影视", "农民影视"])
    # 这些列内容都是 1~2 字符，宽度应贴近其 COL_MAX 下限附近，而非 130+
    for c, label in ((4, "成人"), (5, "短剧"), (6, "直播"), (8, "禁用")):
        w = d.table.columnWidth(c)
        ok("%s 列不过宽（<=70）" % label, w <= 70, "w=%s" % w)
    ok("类型 列不过宽（<=95）", d.table.columnWidth(2) <= 95,
       "w=%s" % d.table.columnWidth(2))
    ok("资源 列不过宽（<=85）", d.table.columnWidth(9) <= 85,
       "w=%s" % d.table.columnWidth(9))

    print("\n== 2) 各列不超 COL_MAX 上限 ==")
    bad = [(c, d.table.columnWidth(c), d._COL_MAX.get(c))
           for c in range(1, 10)
           if d.table.columnWidth(c) > d._COL_MAX.get(c, 999)]
    ok("无列超过各自 COL_MAX", not bad, str(bad))

    print("\n== 3) 总宽贴合视口（name 吸收剩余）==")
    total = sum(d.table.columnWidth(c) for c in range(10))
    vp = d.table.viewport().width()
    ok("总列宽 ≈ 视口宽（±8px）", abs(total - vp) <= 8,
       "total=%s vp=%s" % (total, vp))

    print("\n== 4) 程序自身自适应不污染「用户拖过」标记 ==")
    ok("构造后 _cols_user_resized 仍为 False（自适应不自我污染）",
       getattr(d, "_cols_user_resized", False) is False,
       "flag=%s" % getattr(d, "_cols_user_resized", None))
    ok("构造后 _name_user_resized 仍为 False（name 自适应不算拖动）",
       getattr(d, "_name_user_resized", False) is False,
       "flag=%s" % getattr(d, "_name_user_resized", None))

    print("\n== 5) 用户拖动非 name 列后停止自动收缩 ==")
    d.table.setColumnWidth(4, 120)
    d._on_user_col_resized(4, 120)       # 模拟用户真实拖动分隔条后的回调
    ok("拖动非 name 列后 _cols_user_resized=True",
       getattr(d, "_cols_user_resized", False) is True)
    d._auto_fit_other_columns()          # 再调也不该覆盖
    ok("用户设定后不再被自动收缩覆盖",
       d.table.columnWidth(4) == 120, "w=%s" % d.table.columnWidth(4))
    d.close()

    print("\n== 6) 内容变长 → 列宽随之增大 ==")
    st.remove("cfg/cols_user_resized")   # 清掉上一段写入的「用户拖过」标记
    for c in range(1, 10):
        st.remove("cfg/colwidth/%d" % c)
    d2, _ = _mk_dlg(["站" * 3, "站" * 3], apis=["./py/a.py", "./py/a.py"])
    w_short = d2.table.columnWidth(1)   # api 列：内容短
    d2.close()
    st.remove("cfg/cols_user_resized")
    for c in range(1, 10):
        st.remove("cfg/colwidth/%d" % c)
    d3, _ = _mk_dlg(["站" * 3, "站" * 3],
                    apis=["./py/" + "x" * 60 + ".py", "./py/" + "x" * 60 + ".py"])
    w_long = d3.table.columnWidth(1)    # api 列：内容长
    ok("api 列随内容变长而变宽", w_long > w_short,
       "short=%s long=%s" % (w_short, w_long))
    ok("api 列不超上限 240", w_long <= 240, "w=%s" % w_long)
    d3.close()
finally:
    for k, v in saved.items():
        st.setValue(k, v)
    for k in ("cfg/namewidth", "cfg/cols_user_resized"):
        if k not in saved:
            st.remove(k)
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
