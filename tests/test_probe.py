# -*- coding: utf-8 -*-
"""源测活：模拟影视仓加载 py 源（homeContent 分类栏 → 首页影片），判定死源。

A) pyinj_core 纯逻辑（零 Qt，子进程真跑假 spider）
B) 真实 Qt（offscreen）的 _ProbeDialog：表格判定 + 模拟分类标签栏
"""
import os
import sys
import time
import threading
import tempfile
import http.server

sys.path.insert(0, ".")
import pyinj_core as C          # noqa: E402

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s   %s" % (name, extra))


D = tempfile.mkdtemp(prefix="pyinj_probe_")


def spider(fname, body):
    p = os.path.join(D, fname)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


# =========================================================================
# A) 纯逻辑
# =========================================================================
print("== A1) 函数式源（模块级 homeContent / homeVideoContent）==")
p_fn = spider("fn.py", '''
def homeContent(filter):
    return {"class": [{"type_id": "1", "type_name": "鬼片大全"},
                      {"type_id": "2", "type_name": "大陆鬼片"},
                      {"type_id": "3", "type_name": "港台鬼片"}]}

def homeVideoContent():
    return {"list": [{"vod_name": "片A"}, {"vod_name": "片B"}, {"vod_name": "片C"}]}

def categoryContent(tid, pg, f, ext):
    return {"list": [{"vod_name": "分类-%s" % tid}]}
''')
r = C.probe_py_source(p_fn, timeout=10)
ok("函数式源跑通", r["ok"], r.get("error"))
ok("分类栏 = 影视仓顶部标签", r["classes"] == ["鬼片大全", "大陆鬼片", "港台鬼片"], r["classes"])
ok("首页取到影片", r["videos"] == 3, r["videos"])
ok("首页走 homeVideoContent", r["via"] == "homeVideoContent", r["via"])
ok("标题样例读得出", r["titles"][:2] == ["片A", "片B"], r["titles"])
ok("判定为活源", C.probe_verdict(r) == ("ok", "活源"), C.probe_verdict(r))
ok("入口形态识别为 module", r["style"] == "module", r["style"])

print("\n== A2) 类式源 + ext 配置（影视仓把站点 ext 传给 init）==")
p_cls = spider("cls.py", '''
class Spider:
    def init(self, extend):
        self.ext = extend or {}

    def homeContent(self, filter):
        names = str((self.ext or {}).get("分类", "默认")).split("&")
        return {"class": [{"type_id": str(i + 1), "type_name": n} for i, n in enumerate(names)]}

    def categoryContent(self, tid, pg, f, ext):
        return {"list": [{"vod_name": "X-%s" % tid}]}
''')
r2 = C.probe_py_source(p_cls, timeout=10, ext={"分类": "电影&剧集&动漫"})
ok("类式源跑通", r2["ok"], r2.get("error"))
ok("ext 生效（分类来自 ext 配置）", r2["classes"] == ["电影", "剧集", "动漫"], r2["classes"])
ok("无 homeVideoContent 时退到 categoryContent",
   r2["via"] == "categoryContent" and r2["videos"] == 1, (r2["via"], r2["videos"]))
ok("入口形态识别为 class", r2["style"] == "class", r2["style"])

print("\n== A3) 空分类 = 死源 ==")
p_dead = spider("dead.py", 'def homeContent(filter):\n    return {"class": []}\n')
r3 = C.probe_py_source(p_dead, timeout=10)
ok("有返回但分类为空", r3["ok"] and r3["classes"] == [])
ok("判定为死源", C.probe_verdict(r3) == ("bad", "死源"), C.probe_verdict(r3))

print("\n== A4) 源内部抛真实异常（应报真实异常，不是签名 TypeError）==")
p_boom = spider("boom.py",
                'def homeContent(filter):\n    raise RuntimeError("站点改版了")\n')
r4 = C.probe_py_source(p_boom, timeout=10)
ok("抛异常时不判活源", not r4["alive"] and not r4["ok"])
ok("错误信息是真实异常", "RuntimeError" in r4["error"] and "站点改版" in r4["error"], r4["error"])
ok("判定为异常", C.probe_verdict(r4)[0] == "err", C.probe_verdict(r4))

print("\n== A5) 没实现 homeContent ==")
p_none = spider("none.py", 'def getName():\n    return "x"\n')
r5 = C.probe_py_source(p_none, timeout=10)
ok("缺失入口判为异常", C.probe_verdict(r5)[0] == "err", C.probe_verdict(r5))
ok("提示没有实现 homeContent", "homeContent" in r5["error"], r5["error"])

print("\n== A6) homeContent 返回 JSON 字符串也能解析 ==")
p_str = spider("str.py",
               'def homeContent(filter):\n'
               '    return \'{"class": [{"type_id": "1", "type_name": "综艺"}]}\'\n')
r6 = C.probe_py_source(p_str, timeout=10)
ok("字符串返回可解析", r6["ok"] and r6["classes"] == ["综艺"], r6.get("error"))
ok("判定为活源", C.probe_verdict(r6)[0] == "ok")

print("\n== A7) .py 不存在 ==")
r7 = C.probe_py_source(os.path.join(D, "nope.py"), timeout=10)
ok("缺文件不判活源", not r7["ok"])
ok("判定为无 .py", C.probe_verdict(r7) == ("none", "无 .py"), C.probe_verdict(r7))

print("\n== A8) 卡死的源（子进程硬超时，不拖住本工具）==")
p_slow = spider("slow.py",
                'import time\n'
                'def homeContent(filter):\n    time.sleep(120)\n    return {"class": []}\n')
t0 = time.time()
r8 = C.probe_py_source(p_slow, timeout=2)
cost = time.time() - t0
ok("超时被杀掉", not r8["ok"] and "超时" in r8["error"], r8.get("error"))
ok("超时判为异常而非活源", C.probe_verdict(r8)[0] == "err", C.probe_verdict(r8))
ok("耗时受控（< 20s）", cost < 20, "%.1fs" % cost)

print("\n== A9) UA 兜底：源自己没设 UA 时按影视仓的移动端 UA 兜底 ==")
seen = []


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        seen.append(self.headers.get("User-Agent", ""))
        body = '{"class": [{"type_id": "1", "type_name": "电影"}]}'.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/" % port

p_noua = spider("noua.py", '''
import urllib.request
def homeContent(filter):
    with urllib.request.urlopen("%s", timeout=5) as r:
        return r.read().decode("utf-8")
''' % URL)
p_ownua = spider("ownua.py", '''
import urllib.request
def homeContent(filter):
    req = urllib.request.Request("%s", headers={"User-Agent": "MyOwnUA/9.9"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode("utf-8")
''' % URL)
try:
    rn = C.probe_py_source(p_noua, timeout=15)
    ok("无 UA 的源能拿到分类", rn["ok"] and rn["classes"] == ["电影"], rn.get("error"))
    ok("兜底 UA 已生效", seen and seen[-1] == C.PROBE_UA, seen)
    ro = C.probe_py_source(p_ownua, timeout=15)
    ok("源自带 UA 的源也能跑", ro["ok"], ro.get("error"))
    ok("源自带 UA 不被兜底覆盖", len(seen) >= 2 and seen[-1] == "MyOwnUA/9.9", seen)
finally:
    srv.shutdown()
    srv.server_close()

print("\n== A10) 子进程输出强制 UTF-8（frozen exe 下 locale 可能是 GBK）==")
_old_io = os.environ.get("PYTHONIOENCODING")
os.environ["PYTHONIOENCODING"] = "gbk"   # 让子进程 stdout 编码变成 GBK
try:
    r10 = C.probe_py_source(p_fn, timeout=10)
finally:
    if _old_io is None:
        os.environ.pop("PYTHONIOENCODING", None)
    else:
        os.environ["PYTHONIOENCODING"] = _old_io
ok("非 UTF-8 locale 下中文分类名仍不乱码",
   r10["classes"] == ["鬼片大全", "大陆鬼片", "港台鬼片"], r10["classes"])

print("\n== A11) 源依赖 requests 与 base.spider 基类 fetch（影视仓运行时自带的能力）==")
srv2 = http.server.HTTPServer(("127.0.0.1", 0), _H)
port2 = srv2.server_address[1]
threading.Thread(target=srv2.serve_forever, daemon=True).start()
URL2 = "http://127.0.0.1:%d/" % port2
p_req = spider("req.py", '''
import requests
def homeContent(filter):
    r = requests.get("%s", timeout=5)
    return r.json()
''' % URL2)
p_base = spider("basesp.py", '''
from base.spider import Spider as _B

class Spider(_B):
    def init(self, extend=""):
        pass

    def homeContent(self, filter):
        return self.fetch("%s", timeout=5).json()
''' % URL2)
try:
    rq = C.probe_py_source(p_req, timeout=15)
    ok("import requests 的源能测活", rq["ok"] and rq["classes"] == ["电影"], rq.get("error"))
    rb = C.probe_py_source(p_base, timeout=15)
    ok("base.spider.fetch 基类方法可用（对齐 PyLoader）",
       rb["ok"] and rb["classes"] == ["电影"], rb.get("error"))
finally:
    srv2.shutdown()
    srv2.server_close()

print("\n== A12) 分类栏优先：首页影片卡死不能连累死活判定 ==")
# 真实教训：可可 / LIBVIO 的 homeContent（分类栏）正常，却卡在首页影片探测，
# 旧版整体超时后连分类栏结果一起丢掉 → 被误判成「异常/死源」。
p_slowvid = spider("slowvid.py", '''
import time
def homeContent(filter):
    return {"class": [{"type_id": "1", "type_name": "电影"},
                      {"type_id": "2", "type_name": "剧集"}]}

def homeVideoContent():
    time.sleep(60)
    return {"list": []}
''')
t0 = time.time()
r12 = C.probe_py_source(p_slowvid, timeout=6)
cost12 = time.time() - t0
ok("首页卡死仍判活源", r12["ok"] and r12["alive"], r12.get("error"))
ok("分类栏照常返回", r12["classes"] == ["电影", "剧集"], r12["classes"])
ok("首页未取到时给出说明", "首页影片未取到" in (r12.get("note") or ""), r12.get("note"))
ok("判定为活源而非异常", C.probe_verdict(r12) == ("ok", "活源"), C.probe_verdict(r12))
ok("耗时受控（< 25s）", cost12 < 25, "%.1fs" % cost12)

print("\n== A12b) 加载慢的活源不能被「加载阶段预算」误杀 ==")
# 真实回归：给加载阶段单独切 7s 预算后，在 init 里发请求的「电影人生」被误判异常。
# 加载 + 分类栏必须共用主预算，加载慢不该挤掉取分类的时间。
p_slowinit = spider("slowinit.py", '''
import time

class Spider:
    def init(self, extend=""):
        time.sleep(9)          # 模拟 init 阶段发请求
        self.host = "x"

    def homeContent(self, filter):
        return {"class": [{"type_id": "1", "type_name": "电影"}]}

    def homeVideoContent(self):
        return {"list": [{"vod_name": "片A"}]}
''')
t0 = time.time()
r12b = C.probe_py_source(p_slowinit, timeout=30)
cost12b = time.time() - t0
ok("init 慢（9s）的源仍判活源", r12b["ok"] and r12b["alive"], r12b.get("error"))
ok("分类栏正常返回", r12b["classes"] == ["电影"], r12b["classes"])
ok("首页影片也取到了", r12b["videos"] == 1, r12b["videos"])
ok("总耗时仍在预算内", cost12b < 40, "%.1fs" % cost12b)

print("\n== A13) 网络兜底：socket 默认超时 + 默认不走系统代理 ==")
# 源里看不到父进程环境，让它把自己看到的运行时状态「报」回来（借分类名传回）
p_env = spider("envspy.py", '''
import os, socket
def homeContent(filter):
    return {"class": [
        {"type_id": "p", "type_name": "proxy=" + str(os.environ.get("http_proxy", ""))},
        {"type_id": "t", "type_name": "timeout=" + str(socket.getdefaulttimeout())},
    ]}
''')
_old_proxy = os.environ.get("http_proxy")
os.environ["http_proxy"] = "http://127.0.0.1:1"     # 故意指向不可用地址
os.environ["HTTP_PROXY"] = "http://127.0.0.1:1"
try:
    r13 = C.probe_py_source(p_env, timeout=15)
finally:
    for k in ("http_proxy", "HTTP_PROXY"):
        if _old_proxy is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = _old_proxy
names13 = r13.get("classes") or []
ok("子进程里系统代理已被清掉（与影视仓一致）",
   any(n.startswith("proxy=") and n[len("proxy="):] in ("", "None") for n in names13), names13)
ok("socket 有兜底超时（源不带 timeout 也不会无限卡）",
   any(n.startswith("timeout=") and n[len("timeout="):] not in ("None", "0", "0.0")
       and 0 < float(n[len("timeout="):]) <= 15 for n in names13), names13)

# =========================================================================
# B) 真实 Qt 对话框
# =========================================================================
print("\n== B) 真实 Qt（offscreen）源测活对话框 ==")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog   # noqa: E402

QDialog.exec = lambda self: 1

import inspect                                          # noqa: E402
import injector as I                                    # noqa: E402

app = QApplication.instance() or QApplication([])


def _cls_from_run_gui(name):
    """injector 的对话框类都定义在 run_gui 内部，按既有测试的同样方式取出。"""
    lines = inspect.getsource(I.run_gui).split("\n")
    cut = next((k for k, l in enumerate(lines)
                if l.strip().startswith("app = QApplication")), None)
    if cut is None:
        raise RuntimeError("run_gui 中找不到 app = QApplication 收尾标记")
    head = lines[:cut]
    while head and not head[-1].strip():
        head.pop()
    g = dict(I.__dict__)
    exec("\n".join(head) + "\n    return %s\n" % name, g)
    return g["run_gui"]()


_ProbeDialog = _cls_from_run_gui("_ProbeDialog")


def _cell(t, r, col):
    it = t.item(r, col)
    return it.text() if it is not None else ""


items = [("k_alive", "活的下片源", {"key": "k_alive", "api": p_fn, "type": 3}, p_fn, None),
         ("k_dead", "空分类源", {"key": "k_dead", "api": p_dead, "type": 3}, p_dead, None),
         ("k_boom", "报错源", {"key": "k_boom", "api": p_boom, "type": 3}, p_boom, None)]
dlg = _ProbeDialog(None, items)
dlg.base_dir = D  # 让 probe_source 能按 api 绝对路径定位到本地 .py
ok("对话框构造成功", dlg is not None)
ok("表格行数 = 待测数", dlg.table.rowCount() == 3, dlg.table.rowCount())
ok("初始为「待测…」", _cell(dlg.table, 0, 1) == "待测…", _cell(dlg.table, 0, 1))

# 打开不再默认测活：显式点「测活全部」触发（与用户手动点按钮等价）
dlg._start(None)
t0 = time.time()
while len(dlg.results) < 3 and time.time() - t0 < 90:
    app.processEvents()
    time.sleep(0.05)
ok("三个源都测完了", len(dlg.results) == 3, len(dlg.results))

P = _ProbeDialog
ok("活源判定入表", _cell(dlg.table, 0, P.P_VERDICT) == "活源", _cell(dlg.table, 0, P.P_VERDICT))
ok("活源分类数", _cell(dlg.table, 0, P.P_CLASSES) == "3", _cell(dlg.table, 0, P.P_CLASSES))
ok("分类标签预览 = 红框区内容",
   "鬼片大全" in _cell(dlg.table, 0, P.P_TABS) and "大陆鬼片" in _cell(dlg.table, 0, P.P_TABS),
   _cell(dlg.table, 0, P.P_TABS))
ok("首页影片数入表", _cell(dlg.table, 0, P.P_VIDEOS) == "3", _cell(dlg.table, 0, P.P_VIDEOS))
ok("死源判定入表", _cell(dlg.table, 1, P.P_VERDICT) == "死源", _cell(dlg.table, 1, P.P_VERDICT))
ok("死源说明写明分类为空", "分类为空" in _cell(dlg.table, 1, P.P_NOTE), _cell(dlg.table, 1, P.P_NOTE))
ok("异常源判定入表", _cell(dlg.table, 2, P.P_VERDICT) == "异常", _cell(dlg.table, 2, P.P_VERDICT))
ok("异常源说明带真实错误", "站点改版" in _cell(dlg.table, 2, P.P_NOTE), _cell(dlg.table, 2, P.P_NOTE))
ok("汇总计数正确", dlg.lbl_sum.text() == "活源 1 · 死源 0+1?" or
   ("活源 1" in dlg.lbl_sum.text() and "死源 1" in dlg.lbl_sum.text()), dlg.lbl_sum.text())

dlg.table.selectRow(0)
ok("预览区渲染出分类标签栏", "鬼片大全" in dlg.preview.text(), dlg.preview.text()[:80])
ok("预览区带「主页」标签", "主页" in dlg.preview.text())
ok("预览区带首页样例", "片A" in dlg.preview.text())

dlg.cb_bad.setChecked(True)
ok("只看死源时隐藏活源", dlg.table.isRowHidden(0), "row0 应隐藏")
ok("只看死源时保留死源", not dlg.table.isRowHidden(1) and not dlg.table.isRowHidden(2))
dlg.cb_bad.setChecked(False)
ok("取消过滤后活源恢复显示", not dlg.table.isRowHidden(0))

print("\n== B2) 进度条收尾：跑完必须停在 100%（不能停在 total-1）==")
# 真实 bug：worker 在「开始测第 i 个之前」报进度，最后一个测完不再报一次，
# 于是进度条永远差一格，而停止按钮已置灰 —— 看着像没跑完。
ok("进度条已拉满", dlg.prog.value() == dlg.prog.maximum(),
   "%d/%d" % (dlg.prog.value(), dlg.prog.maximum()))
ok("测完后停止按钮置灰", not dlg.btn_stop.isEnabled())
ok("测完后开始按钮可用", dlg.btn_start.isEnabled())
ok("worker 引用已释放（可重新测活）", dlg._worker is None, dlg._worker)

print("\n== B3) 双击打开 .py / 右键菜单的入口 ==")
_opened = []
_orig_open = _ProbeDialog._open_path
_ProbeDialog._open_path = staticmethod(lambda p: (_opened.append(p), True)[1])
try:
    dlg.table.cellDoubleClicked.emit(0, 0)
    ok("双击行 = 打开该源的 .py", bool(_opened)
       and os.path.abspath(_opened[-1]) == os.path.abspath(p_fn), _opened)
finally:
    _ProbeDialog._open_path = _orig_open
ok("不存在的路径不会误打开", _ProbeDialog._open_path(os.path.join(D, "nope.py")) is False)
ok("越界行不响应双击", dlg._item_at(99) is None and dlg._item_at(-1) is None)
ok("右键菜单已挂上（策略=CustomContextMenu）",
   hasattr(dlg, "_ctx_menu") and callable(dlg._ctx_menu))

print("\n== B4) 部分测活：只测选中的行，未选行保持待测 ==")
# 新开一个对话框（上一个已经跑过全部，results 里有数据，先确认语义隔离）
d2 = _ProbeDialog(None, items)
d2.base_dir = D  # 让 probe_source 能按 api 绝对路径定位到本地 .py
ok("新对话框初始全部待测", all(_cell(d2.table, r, 1) == "待测…" for r in range(3)),
   [_cell(d2.table, r, 1) for r in range(3)])
# 只选中第 0、2 行（活源 + 报错源），点「测活选中」
# 默认 QTableWidget 是 ExtendedSelection：先选第 0 行，再叠加选第 2 行
d2.table.selectRow(0)
from PySide6.QtCore import QItemSelectionModel
d2.table.selectionModel().select(
    d2.table.model().index(2, 0),
    QItemSelectionModel.Select | QItemSelectionModel.Rows)
d2._update_sel_btn()
ok("「测活选中」按钮在选中 2 行时显示数量并可用",
   d2.btn_start_sel.isEnabled() and "2" in d2.btn_start_sel.text(),
   d2.btn_start_sel.text())
d2._start("selected")
t0 = time.time()
while len(d2.results) < 2 and time.time() - t0 < 90:
    app.processEvents()
    time.sleep(0.05)
ok("只测完了选中的 2 个源", len(d2.results) == 2, d2.results.keys())
ok("未选中的第 1 行仍显示待测", _cell(d2.table, 1, 1) == "待测…", _cell(d2.table, 1, 1))
ok("选中的活源已出判定", _cell(d2.table, 0, d2.P_VERDICT) == "活源", _cell(d2.table, 0, d2.P_VERDICT))
ok("选中的报错源已出判定", _cell(d2.table, 2, d2.P_VERDICT) == "异常", _cell(d2.table, 2, d2.P_VERDICT))
# 进度条按子集大小收尾
ok("部分测活进度条按子集拉满", d2.prog.maximum() == 2 and d2.prog.value() == 2,
   "%d/%d" % (d2.prog.value(), d2.prog.maximum()))
# 之后可再对第 1 行补测，不覆盖已测结果
d2.table.selectRow(1)
d2._start("selected")
t1 = time.time()
while len(d2.results) < 3 and time.time() - t1 < 90:
    app.processEvents()
    time.sleep(0.05)
ok("补测后 3 个源全部完成", len(d2.results) == 3, d2.results.keys())
ok("补测后活源结果仍保留", _cell(d2.table, 0, d2.P_VERDICT) == "活源", _cell(d2.table, 0, d2.P_VERDICT))

print("\n结果：%d 通过 / %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
