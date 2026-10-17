# -*- coding: utf-8 -*-
"""工具箱「上传到电视 / 盒子」页 GUI 测试（真实 offscreen 渲染 + 假 adb 端到端）。

用「假 adb」替代真实 adb.exe：把 pyinj_upload.Adb 换成内存实现，走完整链路
（连接 → 清单 → 建目录 → push → md5 校验 → 结果表），不接触任何真实设备。

覆盖：
  1) 第 7 页存在且可切换，切页不会误触发分区重载；
  2) 「＋ 加入仓库目录」按默认排除规则生成清单（不含 backups / exe）；
  3) 连接成功后显示设备串号；「测试写权限」走通；
  4) 上传写进假设备、结果表逐行显示成功；远端目录随输入框实时变化；
  5) 再次上传 MD5 相同 → 全部「跳过」且不再 push；
  6) 自定义文件（仓库之外）可加入并上传；
  7) 未勾选任何文件时点上传只提示、不启动任务；
  8) 移除选中行生效。
"""
import io
import os
import sys
import time
import hashlib
import inspect
import tempfile

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


# ---- 临时「仓库」----
tmp = tempfile.mkdtemp(prefix="pyinj_upgui_")
FILES = {
    "py.json": b'{"sites":[]}',
    "py/a.py": b"class Spider:\n    pass\n",
    "py/sub/b.py": b"# b\n",
    "backups/py.json.1.bak": b"old",
    "py_trash/x.py.1.bak": b"old",
    "tool.exe": b"MZ",
}
for rel, data in FILES.items():
    p = os.path.join(tmp, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
# 仓库之外的「其它配置文件」
other = os.path.join(tempfile.mkdtemp(prefix="pyinj_other_"), "别的配置.json")
with open(other, "w", encoding="utf-8") as f:
    f.write('{"lives":[]}')
# 假 adb.exe（只需是个文件，FakeAdb 不会真的执行它）
adb_stub = os.path.join(tmp, "adb.exe")
with open(adb_stub, "wb") as f:
    f.write(b"stub")

import injector as I
import pyinj_upload as U
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QSettings

# 测试隔离：本页会持久化 adb 路径 / 地址 / 远端目录（QSettings），
# 若用真实注册表会污染用户设置、也会让本测试第二次运行结果漂移 —— 改写到临时 INI。
_cfg_dir = tempfile.mkdtemp(prefix="pyinj_qsettings_")
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _cfg_dir)
_st = QSettings("PyInjector", "PyInjector")
_st.clear()
_st.sync()

QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)


class FakeAdb(object):
    """内存版 adb：记录 push 内容，md5 由内容算出。"""
    store = {}
    pushes = []
    serials = []
    write_checks = []

    def __init__(self, adb_path, serial="", timeout=60):
        self.adb_path = adb_path
        self.serial = serial
        FakeAdb.serials.append(serial)

    @classmethod
    def reset(cls):
        cls.store = {}
        cls.pushes = []
        cls.write_checks = []

    def connect(self, addr):
        FakeAdb.last_addr = addr
        return {"ok": True, "text": "connected to %s" % addr, "msg": "已连接 %s" % addr}

    def devices(self):
        return {"ok": True, "devices": [
            {"serial": "192.168.1.9:5555", "state": "device", "extra": "model:TV_Box_4"},
            {"serial": "abc", "state": "unauthorized", "extra": ""}]}

    def mkdir_p(self, d):
        return {"ok": True, "out": "", "err": ""}

    def md5(self, r):
        return FakeAdb.store.get(r, "")

    def rm(self, r):
        FakeAdb.store.pop(r, None)
        return {"ok": True}

    def push(self, local, remote):
        FakeAdb.pushes.append(remote)
        data = open(local, "rb").read()
        FakeAdb.store[remote] = hashlib.md5(data).hexdigest()
        return {"ok": True, "out": "", "err": ""}

    def test_writable(self, remote):
        FakeAdb.write_checks.append(remote)
        return {"ok": True, "msg": "目录可写：%s" % remote}


app = QApplication.instance() or QApplication([])

src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return (_ToolboxDialog, ConfigDialog)\n", g)
_ToolboxDialog, ConfigDialog = g["run_gui"]()

RAW = '{"sites":[]}'
dlg = ConfigDialog(None, tmp, RAW, [], "py.json", tmp)
app.processEvents()
tb = _ToolboxDialog(dlg, [], tmp, tmp)
tb.show()
app.processEvents()


def wait_push(timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if tb._push_worker is None:
            break
        tb._push_worker.wait(30)
    app.processEvents()
    return tb._push_worker is None


print("== 1) 页面存在 / 切换 ==")
ok("功能下拉共 8 项", tb.page.count() == 8, str(tb.page.count()))
ok("第 7 项是上传页", "上传" in tb.page.itemText(6), tb.page.itemText(6))
tb.page.setCurrentIndex(6)
app.processEvents()
ok("上传页可见", tb.pages["push"].isVisible())
ok("分区页隐藏", not tb.pages["sect"].isVisible())
ok("默认远端目录 /sdcard/", tb.ed_remote.text() == "/sdcard/", tb.ed_remote.text())
ok("默认勾选「跳过 MD5 相同」", tb.chk_skip.isChecked())

print("\n== 2) 加入仓库目录（默认排除生效）==")
tb._push_add_repo()
app.processEvents()
rels = [tb.tree_push.topLevelItem(i).text(0)
        for i in range(tb.tree_push.topLevelItemCount())]
ok("清单只含 py.json 与 py/*.py（3 个）", sorted(rels) == ["py.json", "py/a.py", "py/sub/b.py"],
   str(rels))
ok("不含 backups / py_trash / exe",
   not any(("backups" in r or "py_trash" in r or r.endswith(".exe")) for r in rels), str(rels))
ok("远端路径已拼好", tb.tree_push.topLevelItem(0).text(2).startswith("/sdcard/"),
   tb.tree_push.topLevelItem(0).text(2))

print("\n== 3) 连接与写权限 ==")
tb.ed_adb.setText(adb_stub)
tb.ed_ip.setText("192.168.1.9")
U.Adb = FakeAdb                     # 打桩：后续所有 adb 调用走内存实现
ok("连接返回成功", tb._push_connect() is True)
ok("界面显示已连接串号", "192.168.1.9:5555" in tb.lbl_push_dev.text(), tb.lbl_push_dev.text())
tb._push_test_write()
ok("测试写权限走通", "目录可写" in tb.lbl_status.text(), tb.lbl_status.text())
ok("写权限检查用的是当前远端目录", FakeAdb.write_checks[-1] == "/sdcard/",
   str(FakeAdb.write_checks))

print("\n== 4) 上传（端到端）==")
FakeAdb.reset()
tb._push_start()
ok("上传任务已结束", wait_push())
ok("结果表 3 行", tb.t_push.rowCount() == 3, str(tb.t_push.rowCount()))
statuses = [tb.t_push.item(i, 1).text() for i in range(tb.t_push.rowCount())]
ok("全部显示成功", all("成功" in s for s in statuses), str(statuses))
ok("假设备收到 3 个文件", len(FakeAdb.store) == 3, str(sorted(FakeAdb.store)))
ok("文本内容按 md5 校验一致",
   FakeAdb.store.get("/sdcard/py/a.py") == hashlib.md5(FILES["py/a.py"]).hexdigest(),
   str(FakeAdb.store.get("/sdcard/py/a.py")))
ok("状态栏汇总正确", "成功 3" in tb.lbl_status.text(), tb.lbl_status.text())

print("\n== 5) 再传一次：MD5 相同全部跳过 ==")
FakeAdb.pushes = []
tb._push_start()
ok("第二次上传结束", wait_push())
st2 = [tb.t_push.item(i, 1).text() for i in range(tb.t_push.rowCount())]
ok("全部显示跳过", all("跳过" in s for s in st2), str(st2))
ok("跳过时没有再 push", FakeAdb.pushes == [], str(FakeAdb.pushes))

print("\n== 6) 改远端目录 / 自定义文件 ==")
tb.ed_remote.setText("/sdcard/TVBox/")
app.processEvents()
ok("清单远端列实时跟随", tb.tree_push.topLevelItem(0).text(2).startswith("/sdcard/TVBox/"),
   tb.tree_push.topLevelItem(0).text(2))
tb._push_add_entries([U.custom_file(other)])
app.processEvents()
ok("自定义文件加入清单", tb.tree_push.topLevelItemCount() == 4,
   str(tb.tree_push.topLevelItemCount()))
ok("自定义文件远端落点正确",
   any(tb.tree_push.topLevelItem(i).text(2) == "/sdcard/TVBox/别的配置.json"
       for i in range(tb.tree_push.topLevelItemCount())),
   str([tb.tree_push.topLevelItem(i).text(2)
        for i in range(tb.tree_push.topLevelItemCount())]))
FakeAdb.pushes = []
tb._push_start()
ok("第三轮上传结束", wait_push())
ok("新目录下收到 4 个文件", len([k for k in FakeAdb.store if k.startswith("/sdcard/TVBox/")]) == 4,
   str([k for k in FakeAdb.store if k.startswith("/sdcard/TVBox/")]))
ok("自定义配置已上传", "/sdcard/TVBox/别的配置.json" in FakeAdb.store)

print("\n== 7) 未勾选 → 不启动 ==")
tb._push_check_all(False)
app.processEvents()
before = tb.t_push.rowCount()
tb._push_start()
app.processEvents()
ok("没有启动上传任务", tb._push_worker is None)
ok("结果表未被清空/改动", tb.t_push.rowCount() == before, str(tb.t_push.rowCount()))

print("\n== 8) 移除选中 ==")
n0 = tb.tree_push.topLevelItemCount()
tb.tree_push.topLevelItem(0).setSelected(True)
tb._push_remove()
app.processEvents()
ok("移除一行", tb.tree_push.topLevelItemCount() == n0 - 1,
   "%d -> %d" % (n0, tb.tree_push.topLevelItemCount()))

print("\n结果：%d 通过 / %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
