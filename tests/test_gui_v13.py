# -*- coding: utf-8 -*-
"""v13 GUI 集成测试（offscreen，无需显示器）：
驱动真实 run_gui -> App.view_config -> ConfigDialog + _AdultScanWorker 全链路。
场景：配置在 sub/12.json、py 文件夹改名 spiders/（无 py/ 目录）。
断言：worker 正常完成（不再卡死「检测中…」）、遍历搜索找回改名 .py、成人检测正确。
若 worker 因任何异常死亡/卡住 -> 20 秒超时判 FAIL（复现用户截图的呆滞现象）。
结果写入 test_gui_v13_out.txt。"""
import os, sys, io, json, tempfile, shutil

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import injector as inj
import PySide6.QtWidgets as QW
from PySide6.QtCore import QEventLoop, QTimer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
buf = io.StringIO()
def log(*a):
    buf.write(" ".join(str(x) for x in a) + "\n")

ok = fail = 0
def check(n, c, e=""):
    global ok, fail
    if c:
        ok += 1; log("PASS", n, e)
    else:
        fail += 1; log("FAIL", n, e)

# ---- 造临时仓库：sub/12.json + 改名的 spiders/（无 py/）----
tmp = tempfile.mkdtemp(prefix="pyinj_gui13_")
repo = os.path.join(tmp, "repo")
sub = os.path.join(repo, "sub")
spiders = os.path.join(repo, "spiders")
os.makedirs(sub); os.makedirs(spiders)
with open(os.path.join(spiders, "v13demoA.py"), "w", encoding="utf-8") as f:
    f.write('class Spider:\n    def getName(self): return "demo"\n    # 成人 苍井空\n')
with open(os.path.join(spiders, "v13cleanB.py"), "w", encoding="utf-8") as f:
    f.write('class Spider:\n    def getName(self): return "clean"\n')
cfg_text = json.dumps({"sites": [
    {"key": "py_demo", "name": "演示检测┃PY", "api": "./py/v13demoA.py",
     "type": 3, "filterable": 1, "quickSearch": 1, "searchable": 1},
    {"key": "py_clean", "name": "普通影视┃PY", "api": "./py/v13cleanB.py",
     "type": 3, "filterable": 1, "quickSearch": 1, "searchable": 1},
]}, ensure_ascii=False, indent=2)
with open(os.path.join(sub, "12.json"), "w", encoding="utf-8") as f:
    f.write(cfg_text)

state = {"app_done": False, "error": None,
         "scanning_finished": False, "detect_map": None}

def trigger():
    """在主事件循环里模拟：已加载仓库后点「查看/修改配置」。"""
    try:
        app = QW.QApplication.instance()
        win = None
        for w in app.topLevelWidgets():
            if type(w).__name__ == "App":
                win = w
                break
        if win is None:
            raise RuntimeError("找不到 App 主窗口")
        win.repo_dir = repo
        win.cfg_file = "sub/12.json"
        win.base_dir = inj.cfg_base_dir(repo, "sub/12.json")
        win.raw = cfg_text
        win.sites = json.loads(cfg_text)["sites"]
        win.view_config()  # 内部 dlg.exec() 会二次进入 fake_exec
    except Exception as ex:
        state["error"] = "trigger: %r" % ex
    finally:
        state["app_done"] = True

def fake_exec(self, *a, **k):
    if isinstance(self, QW.QApplication):
        # 主窗口事件循环：定时触发 view_config，等它结束
        QTimer.singleShot(150, trigger)
        loop = QEventLoop()
        t = QTimer(); t.timeout.connect(
            lambda: (state["app_done"] or state["error"]) and loop.quit())
        t.start(100)
        QTimer.singleShot(30000, loop.quit)  # 全局兜底
        loop.exec()
        t.stop()
        return 0
    # ConfigDialog.exec：等后台 worker 完成（或 20s 超时=卡死）
    dlg = self
    # 检测在 2026.09.24.e 之后改为「默认不自动开始」（避免打开界面即焦虑），
    # 因此这里显式点一次「开始」——否则 detect_map 恒空、用例变成假通过/假失败
    try:
        QTimer.singleShot(50, dlg._start_detect)
    except Exception:
        pass
    loop = QEventLoop()
    def check2():
        if not getattr(dlg, "_scanning", True) or state.get("error"):
            state["scanning_finished"] = True
            state["detect_map"] = dict(getattr(dlg, "detect_map", {}) or {})
            loop.quit()
    t2 = QTimer(); t2.timeout.connect(check2); t2.start(100)
    QTimer.singleShot(20000, loop.quit)  # 超时=复现「呆在检测中」
    loop.exec()
    t2.stop()
    try:
        dlg.close()
    except Exception:
        pass
    return 0

QW.QApplication.exec = fake_exec  # 拦截主事件循环以驱动测试
QW.QDialog.exec = fake_exec       # 拦截 ConfigDialog.exec（否则 offscreen 下永久阻塞）
QW.QWidget.show = lambda self: None  # 沙箱禁止显示真实窗口（会 SIGTERM）
# 让 run_gui 的隐藏控制台调用(user32)直接走它的 except 分支，避免沙箱杀 GUI 子系统调用
import ctypes as _ct
class _FakeWindll:
    def __getattr__(self, name):
        raise AttributeError(name)
_ct.windll = _FakeWindll()

try:
    try:
        inj.run_gui()
    except SystemExit:
        pass

    if state["error"]:
        check("GUI 流程无异常", False, state["error"])
    else:
        check("GUI 流程无异常", True)

    check("worker 完成（未卡死「检测中…」）", state["scanning_finished"], "")
    dm = state["detect_map"] or {}
    check("detect_map 覆盖全部站点", set(dm) == {"py_demo", "py_clean"}, dm)
    is_ad, kw = dm.get("py_demo", (None, None))
    check("改名 spiders/ 里的成人 .py 被找回并检出", is_ad is True and kw in ("成人", "苍井空"),
          (is_ad, kw))
    is_ad2, kw2 = dm.get("py_clean", (None, None))
    check("普通站点判为否", is_ad2 is False, (is_ad2, kw2))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

log("")
log("RESULT: %d passed, %d failed" % (ok, fail))
with open(os.path.join(HERE, "test_gui_v13_out.txt"), "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
