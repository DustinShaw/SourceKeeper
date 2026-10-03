# -*- coding: utf-8 -*-
"""按 type 真正管理各种源 —— 回归测试（真实 PySide6 offscreen，纯逻辑零网络）。

背景：GUI 的检测逻辑曾事实上「只针对 type:3」——(1) URL 可达性检测对 type:1
直连源也去找 .py，找不到就报「未找到 .py」；(2) 成人/短剧/直播检测对非 Spider
源也去解析 .py；(3) 缺失校验把 type:0/4 也当 .py 校验，产生误报。

本测试覆盖修复后的「type 感知」口径：
  A) 数据层 pyinj_core：
     - source_type_of：有效 type 口径（自带 type 优先，否则 infer_type）
     - expects_local_file：只有「本地 Spider」才应有本地文件
  B) GUI（offscreen）：
     - _MissingPyWorker：type:1/0/4 不参与缺失统计（不再误报「缺失」）
     - _UrlCheckWorker：type:1 直连走 HTTP（不再「未找到 .py」）
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import json
import inspect
import tempfile

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

print("== A1) source_type_of（有效 type 口径）==")
ok("自带 type:1 优先", C.source_type_of({"type": 1, "api": "./py/a.py"}) == 1)
ok("自带 type:0 优先", C.source_type_of({"type": 0, "api": "https://x/y.xml"}) == 0)
ok("自带 type:4 优先", C.source_type_of({"type": 4, "api": "https://x/alist"}) == 4)
ok("无 type + 直连 → 推断 1",
   C.source_type_of({"api": "https://x.com/api.php/provide/vod"}) == 1)
ok("无 type + .py → 推断 3", C.source_type_of({"api": "./py/a.py"}) == 3)
ok("字符串变体 'py' 原样保留", C.source_type_of({"type": "py", "api": "./py/a.py"}) == "py")

print("== A2) expects_local_file（只有本地 Spider 才应有本地文件）==")
_false_cases = [
    ({"type": 1, "api": "https://x.com/api.php/provide/vod"}, "type:1 直连"),
    ({"type": 0, "api": "https://x.com/index.xml"}, "type:0 XML"),
    ({"type": 4, "api": "https://x.com/alist"}, "type:4 目录"),
    ({"type": 3, "api": "http://x.com/a.py"}, "type:3 远程 .py"),
    ({"api": "https://x.com/api.php/provide/vod"}, "无 type 直连（推断 1）"),
    ({"api": ""}, "空 api"),
    # jar 型 spider：api 是远程 jar 内的类名（带 jar 字段）→ 无本地文件
    ({"type": 3, "api": "csp_Config", "jar": "http://h/jar/lubin.php"}, "type:3 jar 内类名（带 jar 字段）"),
    ({"type": 3, "api": "csp_PanWebShare", "jar": "http://h/jar/lubin.php"}, "type:3 csp_ + jar 字段"),
    ({"type": 3, "api": "csp_LocalFile", "jar": "http://h/jar/lubin.php"}, "type:3 csp_ 本地类名 + jar"),
    ({"type": 3, "api": "csp_Wogg"}, "type:3 无后缀 csp_（无 .py 后缀）"),
]
for e, desc in _false_cases:
    ok("%s → 无本地文件" % desc, C.expects_local_file(e) is False, e)

_true_cases = [
    ({"type": 3, "api": "./py/a.py"}, "type:3 本地 .py"),
    ({"type": 3, "api": "csp_DouBan.py"}, "type:3 csp_ 前缀 + .py 后缀（本地脚本）"),
    ({"type": 3, "api": "./py/csp_XBPQ.py"}, "type:3 本地 csp_XBPQ.py"),
    ({"type": 3, "api": "spider.js"}, "type:3 本地 .js"),
    ({"type": 3, "api": "spider.drpy"}, "type:3 本地 .drpy"),
    ({"api": "./py/b.py"}, "无 type + .py（推断 3）"),
    ({"type": "py", "api": "./py/c.py"}, "字符串变体 'py'"),
]
for e, desc in _true_cases:
    ok("%s → 有本地文件" % desc, C.expects_local_file(e) is True, e)

# =========================================================================
# B) GUI（offscreen）
# =========================================================================
print("== B) GUI：各 type 的缺失 / 可达检测不再一律当 .py ==")
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QFileDialog
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QDialog.exec = lambda self: 1

import injector as I
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return ConfigDialog\n", g)
ConfigDialog = g["run_gui"]()

app = QApplication.instance() or QApplication(sys.argv)

tmp = tempfile.mkdtemp(prefix="typeroute_")
os.makedirs(os.path.join(tmp, "py"))
with open(os.path.join(tmp, "py", "ok.py"), "w", encoding="utf-8") as f:
    f.write("class Spider:\n    pass\n")
# gone.py 故意不建：Spider 源 .py 缺失，应被检出；其余 type 不应参与
sites = [
    {"key": "cms1", "name": "直连A", "api": "https://cms.example.com/api.php/provide/vod", "type": 1},
    {"key": "sp_ok", "name": "蜘蛛OK", "api": "./py/ok.py", "type": 3},
    {"key": "sp_bad", "name": "蜘蛛缺失", "api": "./py/gone.py", "type": 3},
    {"key": "xml1", "name": "XML C", "api": "https://x.example.com/index.m3u", "type": 0},
    {"key": "dir1", "name": "目录D", "api": "https://x.example.com/alist", "type": 4},
    # jar 型 spider：远程 jar 里的类名，绝不能被当缺失 .py 误报
    {"key": "jar1", "name": "配置中心", "api": "csp_Config", "type": 3,
     "jar": "http://47.120.41.246:8025/vip/jar/lubin.php"},
    {"key": "jar2", "name": "至臻", "api": "csp_PanWebShare", "type": 3,
     "jar": "http://47.120.41.246:8025/vip/jar/lubin.php"},
]
raw = json.dumps({"sites": sites}, ensure_ascii=False)
with open(os.path.join(tmp, "py.json"), "w", encoding="utf-8") as f:
    f.write(raw)

dlg = ConfigDialog(None, tmp, raw, sites, "py.json", tmp)
# 等 _MissingPyWorker 跑完：先阻塞等后台线程结束（确保 finished_check 已 emit），
# 再驱动事件循环把跨线程 queued 信号投递到主线程——offscreen 下只有 processEvents
# 会处理该事件；用「file_checking 变 False」作为完成哨兵，避免固定次数盲等导致信号丢失。
if getattr(dlg, "_file_worker", None) is not None:
    dlg._file_worker.wait(15000)
for _ in range(200):
    app.processEvents()
    if not getattr(dlg, "_file_checking", False):
        break

print("-- 缺失校验只针对本地 Spider --")
miss_keys = {k for k, _a in getattr(dlg, "_file_missing", [])} if hasattr(dlg, "_file_missing") else set()
# 兼容：从 file_map 读最终状态
fm = getattr(dlg, "file_map", {})
ok("Spider 缺失源被标记 missing", fm.get("sp_bad") == "missing", fm)
ok("Spider 正常源 marked normal", fm.get("sp_ok") == "normal", fm)
ok("type:1 直连源不参与缺失（直连）", fm.get("cms1") not in ("missing",) and fm.get("cms1") == "remote", fm)
ok("type:0 XML 源不参与缺失", fm.get("xml1") != "missing", fm)
ok("type:4 目录源不参与缺失", fm.get("dir1") != "missing", fm)
ok("jar 型 spider（csp_Config）不参与缺失", fm.get("jar1") != "missing", fm)
ok("jar 型 spider（csp_PanWebShare）不参与缺失", fm.get("jar2") != "missing", fm)

print("-- 资源列类型感知渲染 --")
rows = {dlg.table.item(r, 0).text(): dlg.table.item(r, 9).text()
        for r in range(dlg.table.rowCount())}
ok("资源列：直连源显示「直连」", rows.get("直连A") == "直连", rows)
ok("资源列：缺失 Spider 显示「缺失」", rows.get("蜘蛛缺失") == "缺失", rows)
ok("资源列：正常 Spider 显示「正常」", rows.get("蜘蛛OK") == "正常", rows)
ok("资源列：jar 型源显示「远程」（非误报缺失）", rows.get("配置中心") == "远程", rows)
ok("资源列：csp_ jar 源显示「远程」", rows.get("至臻") == "远程", rows)

print("-- URL 检测路由（type:1 走 HTTP，不报「未找到 .py」）--")
# 直接调 check_source_reachability 验type 分流（不联网：type:1 会 HTTP，用不可达域名可接受）
r_cms = I.check_source_reachability(sites[0], base_dir=tmp)
ok("type:1 直连 → note 为直连接口可达性（不涉及 .py）",
   "直连" in r_cms.get("note", ""), r_cms)
ok("type:1 直连 → 不返回「未找到 .py」",
   "未找到" not in r_cms.get("note", ""), r_cms)

r_sp_missing = I.check_source_reachability(sites[2], base_dir=tmp)
ok("type:3 缺 .py → note 说明无本地文件/无 URL（非崩溃）",
   r_sp_missing.get("reachable") in (None, False), r_sp_missing)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
