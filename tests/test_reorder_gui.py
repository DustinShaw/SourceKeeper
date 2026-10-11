# -*- coding: utf-8 -*-
"""「⇅ 排序写回配置」按钮 offscreen GUI 测试（真实 Qt）。

覆盖：
  1) 底部按钮存在且已接线（真实 click 触发，不是直接调内部方法）；
  2) 点列头排序后点按钮 → 配置文件 sites 顺序 == 列表当前显示顺序；备份已生成；
  3) 顺序与文件一致时 → 只提示、不写盘（文件内容不变）；
  4) 搜索过滤只剩部分可见时 → 只重排可见条目（槽位填充），隐藏条目原位不动；
  5) 检测进行中（_scanning）→ 只提示、不写盘；
  6) 写回后内存条目顺序与文件一致（表格刷新后仍对得上）。

注意：写入前会弹确认框，测试里把 _confirm_sort_write 替换为直接返回 True（同
「禁用直播」等用例对确认框的处理方式）。
"""
import io
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = FAIL = 0


def ok(cond, name, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


import injector as I
import pyinj_sections as S
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

app = QApplication.instance() or QApplication([])
import inspect
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return ConfigDialog\n", g)
ConfigDialog = g["run_gui"]()

# ---- 收集弹窗调用（不真的弹） ----
INFO = []
CRIT = []
QMessageBox.information = staticmethod(lambda *a, **k: INFO.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: INFO.append("WARN"))
QMessageBox.critical = staticmethod(lambda *a, **k: CRIT.append(a[2] if len(a) > 2 else ""))

RAW = """{
  "sites": [
    // 丙在最前
    {"key":"kC","name":"CCC站","api":"./py/c.py","type":3},
    {"key":"kA","name":"AAA站","api":"./py/a.py","type":3},
    {"key":"kB","name":"BBB台","api":"./py/b.py","type":3},
    {"key":"kD","name":"DDD台","api":"./py/d.py","type":3}
  ],
  "lives": []
}
"""

tmp = tempfile.mkdtemp(prefix="pyinj_sort_")
cfg = os.path.join(tmp, "py.json")
with open(cfg, "w", encoding="utf-8") as f:
    f.write(RAW)
os.makedirs(os.path.join(tmp, "py"), exist_ok=True)

dlg = ConfigDialog(None, tmp, RAW, I.parse_jsonc(RAW)["sites"], "py.json", tmp)
dlg._sort_col = -1                      # 不受上一次会话的排序偏好影响
dlg._confirm_sort_write = lambda moved, hidden: True   # 跳过确认框
dlg.show()
app.processEvents()


def wait_files(timeout=20.0):
    t0 = time.time()
    while getattr(dlg, "_file_checking", False) and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.02)


def file_keys():
    with open(cfg, "r", encoding="utf-8") as f:
        return [o.get("key") for o, _d in S.section_entries_with_disabled(f.read(), "sites")]


def shown_keys():
    return [str(e.get("key", "")) for e in dlg._shown]


try:
    wait_files()

    print("\n== 1) 按钮存在且已接线 ==")
    btns = [b for b in dlg.findChildren(QPushButton) if "排序写回" in b.text()]
    ok(len(btns) == 1, "底部存在唯一「⇅ 排序写回配置」按钮",
       str([b.text() for b in dlg.findChildren(QPushButton)]))
    btn = btns[0]
    ok(callable(getattr(dlg, "write_sorted_order", None)), "处理器 write_sorted_order 存在")

    print("\n== 2) 排序后写回：文件顺序 == 列表顺序 ==")
    ok(file_keys() == ["kC", "kA", "kB", "kD"], "初始文件顺序为原始顺序")
    dlg._on_header_clicked(0)            # 按「名称」列升序
    dlg._refresh_table()
    app.processEvents()
    ok(shown_keys() == ["kA", "kB", "kC", "kD"], "点表头后列表按名称升序", str(shown_keys()))
    INFO.clear()
    btn.click()                          # 真实点击，验证接线
    app.processEvents()
    got = file_keys()
    ok(got == ["kA", "kB", "kC", "kD"], "配置里的 sites 顺序已按列表顺序重写", str(got))
    baks = os.listdir(os.path.join(tmp, "backups"))
    ok(len(baks) == 1, "写入前已自动备份", str(baks))
    ok(getattr(dlg, "changed", False) is True, "标记为已改动（changed=True）")
    ok(not CRIT, "无错误弹窗", str(CRIT))
    ok("// 丙在最前" in open(cfg, encoding="utf-8").read(), "数组内注释未丢失")
    ok([str(e.get("key", "")) for e in dlg.entries] == ["kA", "kB", "kC", "kD"],
       "内存条目顺序已同步", str([e.get("key") for e in dlg.entries]))

    print("\n== 3) 顺序已一致 → 只提示、不写盘 ==")
    before = open(cfg, "r", encoding="utf-8").read()
    n_bak = len(os.listdir(os.path.join(tmp, "backups")))
    INFO.clear()
    btn.click()
    app.processEvents()
    ok(open(cfg, "r", encoding="utf-8").read() == before, "文件内容未变")
    ok(len(os.listdir(os.path.join(tmp, "backups"))) == n_bak, "未产生新备份")
    ok(any("顺序" in str(x) for x in INFO), "给出「顺序未变」提示", str(INFO))

    print("\n== 4) 过滤后只重排可见条目（槽位填充） ==")
    with open(cfg, "w", encoding="utf-8") as f:      # 复位成原始顺序
        f.write(RAW)
    dlg.raw = RAW
    dlg.entries = []
    for obj, dis in I.parse_sites_with_disabled(RAW):
        e2 = dict(obj)
        e2["_disabled"] = dis
        dlg.entries.append(e2)
    dlg._sort_col = -1
    dlg._refresh_table()
    dlg.search_edit.setText("站")                  # 只剩 甲本站 / 丙本站
    dlg._refresh_table()
    app.processEvents()
    ok(sorted(shown_keys()) == ["kA", "kC"], "过滤后可见 2 条", str(shown_keys()))
    dlg._on_header_clicked(0)
    dlg._refresh_table()
    app.processEvents()
    ok(shown_keys() == ["kA", "kC"], "可见两条按名称升序", str(shown_keys()))
    btn.click()
    app.processEvents()
    got = file_keys()
    ok(got[0] == "kA" and got[1] == "kC", "可见两条换到最前两个槽位", str(got))
    ok(got[2] == "kB" and got[3] == "kD", "被过滤隐藏的两条原位不动", str(got))
    dlg.search_edit.setText("")
    dlg._refresh_table()
    app.processEvents()

    print("\n== 5) 检测进行中 → 不写盘 ==")
    before = open(cfg, "r", encoding="utf-8").read()
    dlg._scanning = True
    INFO.clear()
    btn.click()
    app.processEvents()
    ok(open(cfg, "r", encoding="utf-8").read() == before, "检测中不写盘")
    ok(any("检测" in str(x) for x in INFO), "提示「检测进行中」", str(INFO))
    dlg._scanning = False

    print("\n== 6) 可见不足 2 条 → 提示不写盘 ==")
    before = open(cfg, "r", encoding="utf-8").read()
    dlg.search_edit.setText("AAA")
    dlg._refresh_table()
    app.processEvents()
    INFO.clear()
    btn.click()
    app.processEvents()
    ok(open(cfg, "r", encoding="utf-8").read() == before, "只有 1 条可见时不写盘")
    ok(any("不足" in str(x) for x in INFO), "提示可见不足 2 条", str(INFO))
    dlg.search_edit.setText("")
    dlg._refresh_table()

    print("\n== 7) 排序写回后再排序再写回（幂等/可重复） ==")
    dlg._on_header_clicked(1)            # 按 api 列排序
    dlg._refresh_table()
    app.processEvents()
    btn.click()
    app.processEvents()
    ok(file_keys() == shown_keys(), "第二次写回后文件顺序仍与列表一致",
       "%s vs %s" % (file_keys(), shown_keys()))

    dlg.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
