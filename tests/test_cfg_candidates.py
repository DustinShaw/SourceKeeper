# -*- coding: utf-8 -*-
"""test_cfg_candidates.py —— 「配置文件」下拉候选（list_config_candidates）单测。

覆盖：
  1. py.json 命名加分排第一；有效站点数参与排序
  2. 一级子目录的 json 入选；二级不入选
  3. 解析失败/无 sites 的 json 不出现在候选里；*.bak 排除
  4. 无任何有效配置时退化为全部 *.json（字母序）
  5. 非法目录返回 []
  6. 与 guess_config_file 口径一致（py.json 存在时首个即其结果）
  7. offscreen GUI：App 的配置文件控件是可编辑 QComboBox，
     _refresh_cfg_candidates 按仓库目录填充、保留当前文本、_resolve_cfg 适配
"""
import os, sys, io, json, tempfile, shutil

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import pyinj_core as core

PASS = FAIL = 0
def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s" % name)
    else:
        FAIL += 1
        print("[FAIL] %s  %s" % (name, extra))


def _mkjson(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _sites(n):
    return [{"key": "k%d" % i, "name": "s%d" % i, "type": 3,
             "api": "./py/x%d.py" % i} for i in range(n)]


tmp = tempfile.mkdtemp(prefix="cfgcand_")
try:
    print("== 1. 打分排序 ==")
    _mkjson(os.path.join(tmp, "py.json"), {"sites": _sites(3), "spider": "./py/x.py"})
    _mkjson(os.path.join(tmp, "other.json"), {"sites": _sites(5)})
    _mkjson(os.path.join(tmp, "zz.json"), {"sites": _sites(5)})   # 与 other 同分
    _mkjson(os.path.join(tmp, "sub", "inner.json"), {"sites": _sites(2)})
    _mkjson(os.path.join(tmp, "sub", "sub2", "deep.json"), {"sites": _sites(9)})  # 二级：不扫
    with open(os.path.join(tmp, "junk.json"), "w", encoding="utf-8") as f:
        f.write("{not valid json")
    _mkjson(os.path.join(tmp, "nosites.json"), {"lives": []})
    _mkjson(os.path.join(tmp, "py.json.bak.20260101"), {"sites": _sites(99)})

    got = core.list_config_candidates(tmp)
    ok("py.json 排第一（命名加分）", got and got[0] == "py.json", str(got))
    ok("一级子目录 json 入选", "sub/inner.json" in got, str(got))
    ok("二级子目录 json 不入选", not any("deep" in g for g in got), str(got))
    ok("解析失败/无 sites 的 json 被排除",
       not any(g in ("junk.json", "nosites.json") for g in got), str(got))
    ok("*.bak 排除", not any(g.startswith("py.json.bak") for g in got), str(got))
    ok("同分按文件名稳定排序",
       got.index("other.json") < got.index("zz.json"), str(got))

    print("\n== 2. 与 guess_config_file 口径一致 ==")
    ok("py.json 存在时 guess 即 py.json", core.guess_config_file(tmp) == "py.json")
    ok("候选首位即 guess 结果", got[0] == core.guess_config_file(tmp))

    print("\n== 3. 退化与边界 ==")
    tmp2 = tempfile.mkdtemp(prefix="cfgcand2_")
    _mkjson(os.path.join(tmp2, "onlyjunk.json"), {"foo": 1})
    got2 = core.list_config_candidates(tmp2)
    ok("无有效配置退化为全部 json（字母序）", got2 == ["onlyjunk.json"], str(got2))
    ok("空目录返回 []", core.list_config_candidates(tempfile.mkdtemp()) == [])
    ok("非法目录返回 []", core.list_config_candidates(os.path.join(tmp, "不存在")) == [])
    ok("空串返回 []", core.list_config_candidates("") == [])
    ok("hint 优先不受影响", core.guess_config_file(tmp, "other.json") == "other.json")

finally:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)

# ---- offscreen GUI 冒烟：App 的配置文件控件 ----
print("\n== 4. GUI 下拉框（offscreen）==")
from PySide6.QtWidgets import QApplication, QComboBox
QApplication.exec = lambda self=None: 0
app = QApplication([])

import inspect
import injector
s = inspect.getsource(injector.run_gui)
idx = s.rfind("    app = QApplication")
g = dict(injector.__dict__)
exec(s[:idx] + "    return App\n", g)
AppCls = g["run_gui"]()
win = AppCls()

ok("配置文件控件是 QComboBox", isinstance(win.ent_cfg, QComboBox))
ok("可编辑", win.ent_cfg.isVisibleTo(win) or win.ent_cfg.isEditable())
ok("lineEdit 存在（editable combo）", win.ent_cfg.lineEdit() is not None)

tmp3 = tempfile.mkdtemp(prefix="cfgcand3_")
try:
    _mkjson(os.path.join(tmp3, "py.json"), {"sites": _sites(3)})
    _mkjson(os.path.join(tmp3, "my源.json"), {"sites": _sites(1)})
    win.ent_repo.setText(tmp3)
    win._refresh_cfg_candidates()
    items = [win.ent_cfg.itemText(i) for i in range(win.ent_cfg.count())]
    ok("下拉框填充候选", items[0] == "py.json" and "my源.json" in items, str(items))

    # 手动选择非默认配置 → _resolve_cfg 采用之
    win.ent_cfg.setCurrentText("my源.json")
    cfg, err = win._resolve_cfg()
    ok("选中非默认 json 后 _resolve_cfg 采用之", cfg == "my源.json" and err is None,
       str((cfg, err)))
    # 回显不覆盖用户手输
    ok("当前文本保持 my源.json", win.ent_cfg.currentText() == "my源.json",
       win.ent_cfg.currentText())

    # 切回 py.json 也能解析
    win.ent_cfg.setCurrentText("py.json")
    cfg2, err2 = win._resolve_cfg()
    ok("切回 py.json 解析正常", cfg2 == "py.json" and err2 is None, str((cfg2, err2)))
finally:
    shutil.rmtree(tmp3, ignore_errors=True)

print("\n== %d/%d passed ==" % (PASS, PASS + FAIL))
if FAIL:
    sys.exit(1)
