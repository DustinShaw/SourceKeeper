# -*- coding: utf-8 -*-
"""「🧹 剔除失效源」测试（真实 PySide6 offscreen）
=====================================================
需求（竞品调研后补的收官能力）：各同类工具的第一卖点是「移除失效线路」，
我们此前只有「可达」列 + 检测结果，没有批量动作。

设计口径（本测试逐条钉死）：
  1) **判定只用明确失效信号**：URL 不可达（url_map code==0）+ 本地脚本缺失（file_map=="missing"）；
     **未检测过的条目一律不算失效**（否则会误伤好源）——这是最关键的一条；
  2) 过滤下拉新增「⛔ 仅失效源」，与剔除动作同一口径；
  3) 默认「禁用」（注释保留、可恢复、立即写盘 + 自动备份），可选「删除」（保存后生效，不删 .py）；
  4) 取消 → 一个字都不改；没有失效源 → 只提示，不动配置。

⚠️ 两个测试要点（踩过坑）：
  · ConfigDialog 打开时**自动后台跑「.py 存在性检测」**并会覆盖 file_map ——
    注入检测结果前必须等它跑完，否则注入值被冲掉（本测试用 _wait_filecheck）；
  · 关闭对话框会走 closeEvent → 未保存更改时弹模态框 ——
    测试必须 patch 掉 QMessageBox 的 4 个静态方法，否则 offscreen 下直接挂死。

用法：python test_purge.py
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
import io
import json
import time
import inspect
import tempfile
import shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                              line_buffering=True)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import injector as I  # noqa: E402
import pyinj_core as C  # noqa: E402

PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


# ------------------------------------------------------- A) 纯逻辑：失效判定口径
print("== A) dead_source_keys：只认「已检测出的失效」 ==")
E = [{"key": "k%d" % i} for i in range(1, 7)]
r = C.dead_source_keys(E, url_map={"k1": (0, "tcp", ""), "k2": (1, "tcp", ""),
                                   "k3": (2, "", "无URL")},
                       file_map={"k4": "missing", "k5": "ok", "k6": "relocated"})
ok("URL 不可达（code=0）→ 计入 unreachable", r["unreachable"] == ["k1"], r)
ok("可达（1）/无URL（2）→ 不算失效", "k2" not in r["keys"] and "k3" not in r["keys"], r)
ok("本地脚本缺失 → 计入 missing_file", r["missing_file"] == ["k4"], r)
ok("ok/relocated/remote 都算正常", all(k not in r["keys"] for k in ("k5", "k6")), r)
ok("keys 合并去重且保序", r["keys"] == ["k1", "k4"], r)
ok("★ 未检测（无 url_map/file_map）→ 零失效（不误伤）",
   C.dead_source_keys(E)["keys"] == [], C.dead_source_keys(E))
ok("★ 空映射 → 零失效",
   C.dead_source_keys(E, url_map={}, file_map={})["keys"] == [])
r4 = C.dead_source_keys(E, url_map={"k1": (0, "", "")}, file_map={"k1": "missing"})
ok("同时命中两种失效 → 只出现一次", r4["keys"] == ["k1"], r4)
ok("空 entries / 非 dict 不炸", C.dead_source_keys([])["keys"] == []
   and C.dead_source_keys([None, "x", {}])["keys"] == [])

# --------------------------------------------------------------- B) 真实 Qt GUI
print("\n== B) 真实 Qt：过滤「⛔ 仅失效源」+ 一键剔除 ==")
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

app = QApplication.instance() or QApplication([])
# 4 个静态弹窗全部 patch（question 不 patch 会在 closeEvent 里挂死）
for _m in ("information", "warning", "question", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: QMessageBox.Yes))
# ⚠️ closeEvent 的「有未保存的更改」是**实例式** QMessageBox(...)+exec()，
#    只 patch 静态方法挡不住 → offscreen 下会挂死；这里统一返回「放弃更改」。
QMessageBox.exec = lambda self, *a, **k: QMessageBox.Discard

src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return ConfigDialog\n", g)
ConfigDialog = g["run_gui"]()


def wait_filecheck(dlg, limit=300):
    """等「.py 存在性检测」后台线程结束——它会覆盖 file_map，必须等它跑完再注入。"""
    for _ in range(limit):
        app.processEvents()
        if not getattr(dlg, "_file_checking", False):
            return True
        time.sleep(0.02)
    return False


tmp = tempfile.mkdtemp(prefix="pyinj_purge_")
try:
    # 4 个 .py 都真实存在 → 自动文件检测应为「normal」，只有 URL 检测决定失效
    os.makedirs(os.path.join(tmp, "py"), exist_ok=True)
    for i in range(1, 5):
        with open(os.path.join(tmp, "py", "s%d.py" % i), "w", encoding="utf-8") as f:
            f.write("# spider %d\n" % i)
    sites = [{"key": "k1", "name": "正常源", "api": "./py/s1.py", "type": 3},
             {"key": "k2", "name": "不可达源", "api": "./py/s2.py", "type": 3},
             {"key": "k3", "name": "可达源", "api": "./py/s3.py", "type": 3},
             {"key": "k4", "name": "不可达源2", "api": "./py/s4.py", "type": 3}]
    raw = json.dumps({"sites": sites}, ensure_ascii=False)
    with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
        f.write(raw)

    dlg = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
    dlg.show()
    ok("自动文件检测跑完（不残留后台线程）", wait_filecheck(dlg))
    ok("★ 自动检测未把存在的 .py 误判为缺失",
       all(dlg.file_map.get("k%d" % i) == "normal" for i in range(1, 5)), dlg.file_map)

    # 注入 URL 检测结果（模拟用户跑完「URL 可达性检测」）
    dlg.url_map = {"k1": (1, "tcp", ""), "k2": (0, "tcp", ""),
                   "k3": (1, "tcp", ""), "k4": (0, "tcp", "")}
    dlg._url_started = True

    print("\n-- B1) 过滤下拉 --")
    texts = [dlg.type_filter.itemText(i) for i in range(dlg.type_filter.count())]
    ok("下拉新增「⛔ 仅失效源」", "⛔ 仅失效源" in texts, texts)
    ok("旧选项一个不少",
       all(t in texts for t in ["全部类型", "直连 CMS (1)", "Spider (3)", "XML (0)",
                                "目录型 (4)", "🔞 仅成人", "⚠️ 仅需特殊上网"]), texts)
    dlg.type_filter.setCurrentIndex(texts.index("⛔ 仅失效源"))
    app.processEvents()
    shown = [str(e.get("key", "")) for e in dlg._shown]
    ok("过滤后只剩 URL 不可达的 k2/k4", shown == ["k2", "k4"], shown)
    ok("正常源 k1 被滤掉", "k1" not in shown, shown)
    dlg.type_filter.setCurrentIndex(0)
    app.processEvents()
    ok("切回「全部类型」恢复 4 条", len(dlg._shown) == 4, [e.get("key") for e in dlg._shown])

    print("\n-- B2) 取消 → 一个字都不改 --")
    before = dlg.raw
    dlg._ask_purge_mode = lambda *a: None
    dlg.purge_dead_sources()
    app.processEvents()
    ok("取消后 raw 未变", dlg.raw == before)
    ok("取消后无条目被禁用", not any(e.get("_disabled") for e in dlg.entries))

    print("\n-- B3) 默认「禁用」：只动失效源 + 注释保留 + 写盘 + 备份 --")
    dlg._ask_purge_mode = lambda *a: "disable"
    dlg.purge_dead_sources()
    app.processEvents()
    pairs = C.parse_sites_with_disabled(dlg.raw) if hasattr(C, "parse_sites_with_disabled") \
        else [(o, d) for o, d in C.load_sites_from_text(dlg.raw)]
    dis = [str(o.get("key")) for o, d in pairs if d]
    ok("只禁用失效源 k2/k4（不碰健康的 k1/k3）", sorted(dis) == ["k2", "k4"], dis)
    ok("健康源 k1/k3 仍在启用态",
       sorted(str(o.get("key")) for o, d in pairs if not d) == ["k1", "k3"],
       [str(o.get("key")) for o, d in pairs if not d])
    ok("条目 _disabled 标记同步",
       sorted(str(e["key"]) for e in dlg.entries if e.get("_disabled")) == ["k2", "k4"])
    disk = open(os.path.join(tmp, "py.json"), encoding="utf-8").read()
    ok("已立即写盘（磁盘内容与内存一致）", disk == dlg.raw, disk[:60])
    bakdir = os.path.join(tmp, "backups")
    ok("写盘前已自动备份", os.path.isdir(bakdir) and len(os.listdir(bakdir)) >= 1,
       os.listdir(bakdir) if os.path.isdir(bakdir) else "无 backups 目录")
    ok("可恢复：启用后依然能解析出该站点", C.enable_site(dlg.raw, "k2")[1] is True)

    print("\n-- B4) 已禁用后再剔除 → 不重复处理、不炸 --")
    n_before = len([e for e in dlg.entries if e.get("_disabled")])
    dlg.purge_dead_sources()
    app.processEvents()
    ok("已全部禁用时状态不变",
       len([e for e in dlg.entries if e.get("_disabled")]) == n_before, n_before)

    print("\n-- B5) 本地脚本缺失也算失效（与 URL 口径合并） --")
    dlg2 = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
    dlg2.show()
    wait_filecheck(dlg2)
    dlg2.url_map = {"k2": (0, "tcp", "")}
    dlg2.file_map["k3"] = "missing"          # 模拟文件校验发现 s3.py 丢失
    dlg2._ask_purge_mode = lambda *a: "disable"
    dlg2.purge_dead_sources()
    app.processEvents()
    ok("URL 不可达 + 文件缺失 两类一并处理",
       sorted(str(e["key"]) for e in dlg2.entries if e.get("_disabled")) == ["k2", "k3"],
       [str(e["key"]) for e in dlg2.entries if e.get("_disabled")])

    print("\n-- B6) 模式「删除」：摘除配置项（保存后生效，不删 .py） --")
    dlg3 = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
    dlg3.show()
    wait_filecheck(dlg3)
    dlg3.url_map = {"k2": (0, "tcp", "")}
    dlg3.file_map["k3"] = "missing"
    dlg3._ask_purge_mode = lambda *a: "remove"
    dlg3.purge_dead_sources()
    app.processEvents()
    left = [str(e["key"]) for e in dlg3.entries]
    ok("失效源 k2/k3 已从列表摘除", left == ["k1", "k4"], left)
    ok("removed_keys 已记录（保存后生效）", dlg3.removed_keys == {"k2", "k3"},
       dlg3.removed_keys)
    ok("未误删 .py（removed_del_py 为空）", not dlg3.removed_del_py, dlg3.removed_del_py)
    ok("删除模式不改 raw（等 Ctrl+S）", dlg3.raw == raw)

    print("\n-- B7) 什么都没检测 → 只提示，不动配置 --")
    dlg4 = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
    dlg4.show()
    wait_filecheck(dlg4)
    dlg4._ask_purge_mode = lambda *a: "disable"
    dlg4.purge_dead_sources()
    app.processEvents()
    ok("未检测 → 不误删任何条目",
       len(dlg4.entries) == 4 and not any(e.get("_disabled") for e in dlg4.entries))

    print("\n-- B8) 按钮与右键入口 --")
    btns = [b.text() for b in dlg.findChildren(QPushButton)]
    ok("批量操作行有「🧹 剔除失效源」", "🧹 剔除失效源" in btns, btns)
    ok("该按钮受 busy 管理（检测期间禁用）",
       any(b.text() == "🧹 剔除失效源" and b in dlg._busy_buttons
           for b in dlg.findChildren(QPushButton)))

    for d in (dlg, dlg2, dlg3, dlg4):
        d.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
