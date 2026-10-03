# -*- coding: utf-8 -*-
"""智能分流导出对话框 + 筛选增强 + 网络体检 worker 的 GUI 测试（真实 PySide6 offscreen）。

覆盖本轮 P0/P1：
  · _SplitExportDialog：判定表、纯净版/完整版落盘、adult 叠加检测
  · 过滤下拉：仅成人 / 仅需特殊上网 / 原 type 过滤保持可用
  · _ProxyCheckWorker：复用 pyinj_netdiag，结果写入 proxy_map
只读本地临时仓库 + 本地 HTTP 服务器，不访问外网。
"""
import io
import os
import sys
import tempfile
import shutil
import inspect
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = b"PK\x03\x04" + b"J" * 4096
        self.send_response(200)
        self.send_header("Content-Type", "application/java-archive")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]

tmp = tempfile.mkdtemp(prefix="pyinj_split_")
py_dir = os.path.join(tmp, "py")
os.makedirs(py_dir)
with open(os.path.join(py_dir, "a.py"), "w", encoding="utf-8") as f:
    f.write("# 普通站点\n")

RAW = """{
"sites": [
{"key":"s1","name":"普通1","api":"./py/a.py","type":3,"adult":0},
{"key":"s2","name":"成人2","api":"./py/a.py","type":3,"adult":1},
{"key":"s3","name":"直连3","api":"%s/api.php/provide/vod","type":1},
{"key":"s4","name":"成人4","api":"%s/api.php/provide/vod","type":1,"adult":1}
]}
""" % (BASE, BASE)
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(RAW)

import injector as I                      # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

app = QApplication.instance() or QApplication([])

src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return (_SplitExportDialog, ConfigDialog, _ProxyCheckWorker)\n", g)
_SplitExportDialog, ConfigDialog, _ProxyCheckWorker = g["run_gui"]()

sites = I.parse_jsonc(RAW)["sites"]
dlg = ConfigDialog(None, tmp, RAW, sites, "py.json", tmp)
app.processEvents()

print("== 1) 过滤下拉包含新维度、保留旧项 ==")
opts = [dlg.type_filter.itemText(i) for i in range(dlg.type_filter.count())]
ok("保留「全部类型」", "全部类型" in opts, str(opts))
ok("保留「Spider (3)」", "Spider (3)" in opts)
ok("新增「🔞 仅成人」", any("仅成人" in o for o in opts), str(opts))
ok("新增「⚠️ 仅需特殊上网」", any("仅需特殊上网" in o for o in opts), str(opts))

print("== 2) 仅成人 过滤（复用 _adult_of + adult 字段）==")
adult_idx = next(i for i, o in enumerate(opts) if "仅成人" in o)
dlg.type_filter.setCurrentIndex(adult_idx)
app.processEvents()
shown = [str(e.get("key", "")) for e in dlg._shown]
ok("只剩 adult 站点 s2/s4", set(shown) == {"s2", "s4"}, str(shown))

print("== 3) 原 type 过滤仍可用 ==")
dlg.type_filter.setCurrentIndex(1)      # 直连 CMS (1)
app.processEvents()
shown = {str(e.get("key", "")) for e in dlg._shown}
ok("type=1 → s3/s4", shown == {"s3", "s4"}, str(shown))
dlg.type_filter.setCurrentIndex(0)      # 全部
app.processEvents()
ok("全部 → 4 条", len(dlg._shown) == 4, str(len(dlg._shown)))

print("== 4) 仅需特殊上网 过滤（空 proxy_map 时为空）==")
proxy_idx = next(i for i, o in enumerate(opts) if "仅需特殊上网" in o)
dlg.type_filter.setCurrentIndex(proxy_idx)
app.processEvents()
ok("未体检时无命中", len(dlg._shown) == 0, str(len(dlg._shown)))
dlg.type_filter.setCurrentIndex(0)
app.processEvents()

print("== 5) 智能分流导出对话框：判定与落盘 ==")
entries = [dict(e) for e in dlg.entries]
sd = _SplitExportDialog(dlg, tmp, "py.json", RAW, entries, adult_keys=set())
ok("判定表 4 行", sd.table.rowCount() == 4, str(sd.table.rowCount()))
# 第 4 列是「判定」：s2/s4 应为「仅完整版」
verdicts = [sd.table.item(r, 4).text() for r in range(sd.table.rowCount())]
ok("含 2 个「仅完整版」", sum(1 for v in verdicts if "仅完整版" in v) == 2, str(verdicts))

sd.ent_dir.setText(tmp)
sd.ent_pure.setText("pure.json")
sd.ent_full.setText("full.json")
sd._do_export()
app.processEvents()
ok("纯净版已生成", os.path.isfile(os.path.join(tmp, "pure.json")))
ok("完整版已生成", os.path.isfile(os.path.join(tmp, "full.json")))
if os.path.isfile(os.path.join(tmp, "pure.json")):
    pure = json.loads(open(os.path.join(tmp, "pure.json"), encoding="utf-8").read())
    pk = {s["key"] for s in pure["sites"]}
    ok("纯净版剔除成人 s2/s4", pk == {"s1", "s3"}, str(pk))
if os.path.isfile(os.path.join(tmp, "full.json")):
    full = json.loads(open(os.path.join(tmp, "full.json"), encoding="utf-8").read())
    fk = {s["key"] for s in full["sites"]}
    ok("完整版保留全部", fk == {"s1", "s2", "s3", "s4"}, str(fk))

print("== 6) 分流叠加「自动检测结果」==")
sd2 = _SplitExportDialog(dlg, tmp, "py.json", RAW, entries, adult_keys={"s1"})
ok("叠加检测后 s1 也判为成人（共 3）",
   sum(1 for r in range(sd2.table.rowCount())
       if "仅完整版" in sd2.table.item(r, 4).text()) == 3)

print("== 7) 网络体检 worker（本地回环应正常→不需代理）==")
w = _ProxyCheckWorker(dlg, entries, tmp)
res = {}
w.finished_map.connect(lambda m: res.update(m))
w.run()                                   # 同步跑（测试环境）
app.processEvents()
ok("proxy_map 覆盖全部 4 条", len(res) == 4, str(res))
ok("本地回环判定不需代理", all(v is False for v in res.values()), str(res))

shutil.rmtree(tmp, ignore_errors=True)
srv.shutdown()
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
