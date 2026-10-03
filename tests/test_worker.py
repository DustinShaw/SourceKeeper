# -*- coding: utf-8 -*-
"""无界面验证 QThread+Signal 机制（与 ConfigDialog 内 _AdultScanWorker 同构）。
不创建任何窗口控件，仅验证：后台线程能逐条发出 progress/item_done，
并把最终 detect_map 投递回主线程。"""
import os, sys
import importlib.util
from PySide6.QtCore import QCoreApplication, QThread, Signal

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("inj", os.path.join(HERE, "injector.py"))
inj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)


class W(QThread):
    progress = Signal(int, int, str)
    item_done = Signal(str, bool, object)
    finished_map = Signal(dict)

    def __init__(self, repo, entries):
        super().__init__()
        self.repo = repo
        self.entries = entries

    def run(self):
        m = {}
        for i, e in enumerate(self.entries):
            k = str(e.get("key", ""))
            p = inj.api_to_path(self.repo, e.get("api", ""))
            a, kw = inj.detect_adult(p, e.get("name", ""))
            m[k] = (a, kw)
            self.item_done.emit(k, a, kw)
            self.progress.emit(i + 1, len(self.entries), e.get("name", ""))
        self.finished_map.emit(m)


app = QCoreApplication([])
raw, sites, _, _ = inj.load_repo(HERE)
print("站点总数: %d" % len(sites))

prog = []
items = {}
final = {}


def on_progress(d, t, n):
    prog.append((d, t, n))


def on_item(k, a, kw):
    items[k] = (a, kw)


def on_done(m):
    final.update(m)
    print("最终 detect_map 条目: %d" % len(m))
    print("progress 发射次数: %d（应等于站点数 %d）" % (len(prog), len(sites)))
    print("首条进度: %s" % (prog[0],))
    print("末条进度: %s" % (prog[-1],))
    ad = [k for k, v in final.items() if v[0]]
    print("成人命中: %d 个 -> %s" % (len(ad), ad))
    app.quit()


w = W(HERE, sites)
w.progress.connect(on_progress)
w.item_done.connect(on_item)
w.finished_map.connect(on_done)
w.start()
rc = app.exec()
print("QCoreApplication rc=%d  线程是否仍在运行: %s" % (rc, w.isRunning()))
print("HEADLESS WORKER TEST OK" if (len(prog) == len(sites) and len(final) == len(sites)) else "HEADLESS WORKER TEST FAIL")
