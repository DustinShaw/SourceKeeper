# -*- coding: utf-8 -*-
"""自定义代理服务器（pyinj_proxy）GUI 回归测试 —— _ProxyControls 控件行。

这是 test_proxy.py 的**姊妹文件**：test_proxy.py 只放纯逻辑用例（A–H 组，零 Qt 依赖），
本文件只放**硬依赖 PySide6** 的 GUI 用例，因此：

  * Win10+ 链（build.py）两个文件都跑；
  * Win7 链（build_win7.py）按既有约定「文件含 PySide6 则整文件跳过」只跳过本文件，
    纯逻辑的 test_proxy.py 照常执行 —— 保证 pyinj_proxy 在两条链上都有覆盖。

覆盖：
  I. GUI：_ProxyControls 控件行（留空直连提示 / 无效地址提示 / 验证回调 / 两处同步）
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyinj_proxy as P

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


print("\n== I) GUI：_ProxyControls 控件行 ==")
import inspect
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
import injector as I

app = QApplication.instance() or QApplication([])
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
g = dict(I.__dict__)
exec(src[:idx] + "    return _ProxyControls\n", g)
ProxyControls = g["run_gui"]()

# 清掉可能残留的设置，保证从「留空直连」开始
from PySide6.QtCore import QSettings
QSettings("PyInjector", "PyInjector").setValue(ProxyControls.SETTINGS_KEY, "")
P.set_active("")

host = QWidget()
lay = QVBoxLayout(host)
ctl = ProxyControls(lay)
ok("控件齐备（输入框 / 验证按钮 / 状态标签）",
   hasattr(ctl, "edit") and hasattr(ctl, "btn") and hasattr(ctl, "lbl"))
ok("验证按钮文案带 🔌", "验证" in ctl.btn.text(), ctl.btn.text())
ok("初始为留空直连提示", "直连" in ctl.lbl.text(), ctl.lbl.text())

ctl.edit.setText("socks5://127.0.0.1:7891")
ctl._commit()
ok("提交后全局单例生效", P.get_active() and P.get_active()["scheme"] == "socks5")
ok("提交后持久化到 QSettings",
   QSettings("PyInjector", "PyInjector").value(ProxyControls.SETTINGS_KEY, "", type=str)
   == "socks5://127.0.0.1:7891")
ok("状态标签显示已启用", "已启用" in ctl.lbl.text(), ctl.lbl.text())

ctl.edit.setText("garbage")
ctl._commit()
ok("无效地址：状态标签给出纠错提示", "⚠" in ctl.lbl.text(), ctl.lbl.text())
ok("无效地址：不会静默启用（全局已回退直连）", P.get_active() is None)
ctl.edit.setText("127.0.0.1:7890")
ctl._commit()

# 两处 UI 同步（模拟另一处界面改了代理）
ctl2 = ProxyControls(lay)
ok("第二处控件读到全局已有值", ctl2.edit.text() == "http://127.0.0.1:7890", ctl2.edit.text())
P.set_active("socks5://10.0.0.9:1080")
ok("一处变更 → 另一处同步刷新", ctl.edit.text() == "socks5://10.0.0.9:1080", ctl.edit.text())
ok("同步后状态标签一并刷新", "已启用" in ctl.lbl.text(), ctl.lbl.text())

# 验证回调（不真的联网：直接喂结果给回调）
notes = []
ctl.on_verify_note = lambda o, n: notes.append((o, n))
ctl._on_verified({"ok": True, "note": "代理服务器正常：经代理打开 Google 首页 HTTP 200（123 ms）"})
ok("验证成功 → 标签 ✓ 且按钮恢复可用",
   ctl.lbl.text().startswith("✓") and ctl.btn.isEnabled(), ctl.lbl.text())
ok("验证成功 → 回调收到通知", notes and notes[-1][0] is True, notes)
ctl._on_verified({"ok": False, "note": "代理服务器不可用：连接超时（5s）"})
ok("验证失败 → 标签 ✗", ctl.lbl.text().startswith("✗"), ctl.lbl.text())
ok("验证失败 → 回调收到通知", notes and notes[-1][0] is False, notes)
ok("验证中不启动后台线程时按钮仍可用（stub 场景）", ctl.btn.isEnabled())

# 无效地址点验证：不启动线程，直接提示
ctl.edit.setText("garbage")
ctl.verify()
ok("无效地址点验证 → 直接提示且不起线程", ctl.worker is None and "⚠" in ctl.lbl.text(),
   ctl.lbl.text())
ctl.teardown()
ctl2.teardown()
QSettings("PyInjector", "PyInjector").setValue(ProxyControls.SETTINGS_KEY, "")
P.set_active("")
ok("退订后不再收到全局变更通知", True)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
