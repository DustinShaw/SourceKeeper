# -*- coding: utf-8 -*-
"""「源管家」全源管理器（py + 直连 CMS 等）回归测试（真实 PySide6 offscreen，纯逻辑零网络）。

覆盖 v2026.09.28 起的新能力：
  A) 数据层（pyinj_core，零 Qt）：
     - make_entry_from_api：粘贴 API 地址生成 type:1 条目（name/key 自动推断）
     - probe_cms_source：直连 CMS 走 HTTP 取分类列表判活（mock 响应）
     - probe_source：按 type 路由（1→CMS / 3→.py / 0·4→HTTP 可达性兜底）
     - source_verdict / check_source_reachability 的 type 分流
  B) GUI（offscreen）：类型列友好标签、资源列类型感知、类型过滤下拉框
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import io
import json
import inspect
import tempfile
import shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


# =========================================================================
# A) 数据层
# =========================================================================
import pyinj_core as C

print("== A1) make_entry_from_api（直连 CMS，type:1）==")
e = C.make_entry_from_api("https://cms.example.com/api.php/provide/vod?ac=list",
                          name=None, type_hint=1)
ok("type 默认为 1", e["type"] == 1, e)
ok("name 按地址自动推断", e["name"] == "cms.example.com", e["name"])
ok("key 按地址稳定唯一", e["key"].startswith("api_"), e["key"])
ok("filterable/quickSearch/searchable 默认开",
   e["filterable"] and e["quickSearch"] and e["searchable"])

print("== A2) probe_cms_source（mock HTTP 取分类列表）==")
payload = json.dumps({
    "code": 1, "msg": "ok",
    "class": [{"type_id": "1", "type_name": "电影"}, {"type_id": "2", "type_name": "剧集"}],
    "list": [{"vod_name": "影片A"}, {"vod_name": "影片B"}],
})
class _R:
    def __init__(self, d):
        self._d = d.encode("utf-8")

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Op:
    def __init__(self, d):
        self._d = d

    def open(self, req, timeout=0):
        return _R(self._d)


C.urllib.request.build_opener = lambda *a, **k: _Op(payload)
r = C.probe_cms_source("https://cms.example.com/api.php/provide/vod?ac=list", timeout=5)
ok("cms ok", r["ok"] is True)
ok("cms 分类非空即活源", r["alive"] is True, r)
ok("cms 分类解析正确", r["classes"] == ["电影", "剧集"], r["classes"])
ok("cms 首页标题解析", r["titles"] == ["影片A", "影片B"], r["titles"])

print("== A3) probe_source 按 type 路由 ==")
# type:1 直连 → CMS
res1, is_py1 = C.probe_source({"key": "k", "name": "n", "api": "https://cms/api.php/provide/vod", "type": 1},
                               base_dir=None, timeout=5)
lvl1, _ = C.source_verdict(res1)
ok("type:1 路由到 CMS 且非 .py", lvl1 == "ok" and is_py1 is False, (lvl1, is_py1))
# type:3 本地无 .py → 无 .py
res3, is_py3 = C.probe_source({"key": "k", "name": "n", "api": "spider_x.py", "type": 3},
                              base_dir="/nonexistent", timeout=2)
lvl3, v3 = C.source_verdict(res3)
ok("type:3 无本地 .py → 无本地资源", lvl3 == "none" and v3 == "无本地资源", (lvl3, v3))
ok("type:3 标记非 .py 路径", is_py3 is False, is_py3)
# type:0/4 + http → HTTP 可达性兜底（用黑名单地址验证可达性为 False 不报错）
res0, _ = C.probe_source({"key": "k", "name": "n", "api": "https://10.255.255.1/x.m3u", "type": 0},
                         base_dir=None, timeout=2)
lvl0, _ = C.source_verdict(res0)
ok("type:0 http 走 HTTP 兜底且返回判定", lvl0 in ("ok", "bad", "err"), lvl0)

print("== A4) check_source_reachability 按 type 分流 ==")
cr1 = C.check_source_reachability({"api": "https://10.255.255.1/api.php/provide/vod?ac=list", "type": 1})
ok("type:1 走直连 CMS 可达性", cr1["method"] == "" or "可达" in cr1["note"] or "不可达" in cr1["note"], cr1)
cr3 = C.check_source_reachability({"api": "spider_x.py", "type": 3}, base_dir=None)
ok("type:3 无 .py 时可达性为 None（无 URL）", cr3["reachable"] is None, cr3)

# =========================================================================
# B) GUI（offscreen）
# =========================================================================
print("\n== B) ConfigDialog 类型列 / 资源列 / 类型过滤 ==")
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QDialog.exec = lambda self: 1

import injector as I
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return ConfigDialog\n", g)
ConfigDialog = g["run_gui"]()

app = QApplication.instance() or QApplication(sys.argv)
tmp = tempfile.mkdtemp(prefix="asm_test_")
os.makedirs(os.path.join(tmp, "py"))
with open(os.path.join(tmp, "py", "ok.py"), "w", encoding="utf-8") as f:
    f.write("class Spider:\n    pass\n")
sites = [
    {"key": "cms1", "name": "直连A", "api": "https://cms.example.com/api.php/provide/vod?ac=list", "type": 1},
    {"key": "sp1", "name": "蜘蛛B", "api": "./py/ok.py", "type": 3},
    {"key": "xml1", "name": "XML C", "api": "https://x.example.com/index.m3u", "type": 0},
]
raw = json.dumps({"sites": sites}, ensure_ascii=False)
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(raw)
dlg = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
for _ in range(20):
    app.processEvents()

print("-- 类型列友好标签 --")
type_vals = [dlg.table.item(r, 2).text() for r in range(dlg.table.rowCount())]
ok("类型列：1·直连 / 3·Spider / 0·XML",
   type_vals == ["1·直连", "3·Spider", "0·XML"], type_vals)

print("-- 资源列类型感知 --")
res_vals = [dlg.table.item(r, 9).text() for r in range(dlg.table.rowCount())]
ok("资源列：直连 / 正常 / 远程",
   res_vals == ["直连", "正常", "远程"], res_vals)
ok("资源列表头已改名为「资源」", dlg.table.horizontalHeaderItem(9).text() == "资源",
   dlg.table.horizontalHeaderItem(9).text())

print("-- 类型过滤下拉框 --")
dlg.type_filter.setCurrentIndex(1)  # 直连 CMS (1)
dlg._refresh_table()
shown = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())]
ok("过滤 type==1 仅剩直连源", shown == ["直连A"], shown)
dlg.type_filter.setCurrentIndex(2)  # Spider (3)
dlg._refresh_table()
shown = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())]
ok("过滤 type==3 仅剩 Spider 源", shown == ["蜘蛛B"], shown)
dlg.type_filter.setCurrentIndex(0)  # 全部
dlg._refresh_table()
shown = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())]
ok("过滤 全部 显示 3 个", len(shown) == 3, shown)

print("-- 添加直连源（type:1）经 make_entry_from_api 生成条目 --")
cms_entry = I.make_entry_from_api("https://newcms.example.com/api.php/provide/vod?ac=list",
                                  name=None, type_hint=1)
ok("添加直连生成 type:1 条目", cms_entry["type"] == 1 and "newcms" in cms_entry["name"],
   cms_entry)

import json as _json
import subprocess
import tempfile as _tf

cli_tmp = _tf.mkdtemp(prefix="asm_cli_")
with open(os.path.join(cli_tmp, "py.json"), "w", encoding="utf-8") as f:
    _json.dump({"sites": [{"key": "sp1", "name": "sp", "api": "./py/ok.py", "type": 3}]},
               f, ensure_ascii=False)

print("-- CLI --version 必须是 UTF-8 字节（应用名含中文）--")
rv = subprocess.run([sys.executable, os.path.join(HERE, "injector.py"), "--version"],
                    capture_output=True)
ok("--version rc=0", rv.returncode == 0, rv.stderr[-200:])
ok("--version 输出 UTF-8 字节的应用名",
   "源管家".encode("utf-8") in rv.stdout, repr(rv.stdout[:40]))
ok("--version 不带版本号以外的乱码（非 GBK 字节）",
   "源管家".encode("gbk") not in rv.stdout, repr(rv.stdout[:40]))

print("-- CLI --add-cms 添加直连 CMS 源 --")
_api = "https://cmsv.example.com/api.php/provide/vod?ac=list"
rc = subprocess.run([sys.executable, os.path.join(HERE, "injector.py"),
                     "--repo", cli_tmp, "--add-cms", _api, "--write"],
                    capture_output=True)
_out = rc.stdout.decode("utf-8", "replace")
ok("--add-cms rc=0", rc.returncode == 0, rc.stderr.decode("utf-8", "replace")[-300:])
try:
    _after = _json.load(open(os.path.join(cli_tmp, "py.json"), encoding="utf-8"))["sites"]
except Exception as _e:
    _after = []
    ok("--add-cms 写入后配置仍合法", False, str(_e))
ok("--add-cms 新增 1 条", len(_after) == 2, len(_after))
if len(_after) == 2:
    ok("--add-cms 新条目 type=1", _after[-1].get("type") == 1, _after[-1])
    ok("--add-cms 新条目 api 正确", _after[-1].get("api") == _api, _after[-1])
    ok("--add-cms 原 Spider 条目 type 未被覆盖", _after[0].get("type") == 3, _after[0])
ok("--add-cms 输出可读无崩溃", ("注入" in _out or "站点" in _out or "写入" in _out), _out[-200:])
shutil.rmtree(cli_tmp, ignore_errors=True)

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
