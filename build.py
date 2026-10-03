# -*- coding: utf-8 -*-
"""build.py —— PyInjector 一键构建流水线
==========================================
流程（任一步失败立即中止）：
  1) 版本核对：APP_VERSION 须为 YYMMDDHHMM（日期+时间），日期部分必须等于今天
     防止跨天会话沿用旧日期（2026-09-25 教训）
  2) 全量源码测试：test_*.py（offscreen，venv python；test_v13_exe 依赖打包产物，移到部署后）
  3) PyInstaller 打包：PyInjector.spec -> dist/源管家.exe
  4) 部署冒烟：deploy.py（版本化 exe + 冻结 CLI 冒烟 + 真实 py.json md5 校验）
用法：
  python build.py            # 完整流水线
  python build.py --skip-tests   # 跳过测试（仅紧急调试用）
"""
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(HERE, "tests")
INJ = os.path.join(HERE, "injector.py")


def sh(cmd, env=None):
    print("\n$ %s" % " ".join(cmd))
    e = dict(os.environ)
    if env:
        e.update(env)
    rc = subprocess.call(cmd, cwd=HERE, env=e)
    if rc != 0:
        print("!! 命令失败 rc=%d：%s" % (rc, " ".join(cmd)))
        sys.exit(rc)
    return rc


def _other_binding_tests():
    """只属于 Qt5/PySide2 那条链路的用例（留给 build_win7.py 在 Python 3.9 环境跑）。"""
    out = []
    for f in sorted(os.listdir(TESTS)):
        if not (f.startswith("test_") and f.endswith(".py")):
            continue
        if f == "test_v13_exe.py":
            continue
        try:
            src = open(os.path.join(TESTS, f), encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        if "PySide2" in src or f == "test_win7_build.py":
            out.append(f)
    return out


def _needs_other_binding(f):
    return f in _other_binding_tests()


def main():
    # venv python：优先用 WorkBuddy 隔离 venv，否则当前解释器
    venv_py = os.path.join(os.path.expanduser("~"),
                           ".workbuddy/binaries/python/envs/default/Scripts/python.exe")
    VPY = venv_py if os.path.isfile(venv_py) else sys.executable
    print("使用解释器：%s" % VPY)

    # ---- 1) 版本核对 ----
    print("\n== 1) 版本核对 ==")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', open(INJ, encoding="utf-8").read())
    if not m:
        print("!! injector.py 中找不到 APP_VERSION")
        sys.exit(1)
    ver = m.group(1)
    today6 = datetime.now().strftime("%y%m%d")
    if ver.isdigit() and len(ver) == 10:
        if ver[:6] != today6:
            print("!! APP_VERSION=%s 须为 YYMMDDHHMM 格式且日期须为今天（%s）" % (ver, today6))
            sys.exit(1)
        print("✓ APP_VERSION=%s 与今天 %s 一致" % (ver, today6))
    else:
        # 非标准版本号（节日特别版标记串，如「2026 国庆特别版」）：无日期可核对 → 跳过
        print("⚠️ APP_VERSION=%s 为非标准版本号（节日特别版），跳过日期核对" % ver)

    # ---- 2) 全量源码测试 ----
    if "--skip-tests" not in sys.argv:
        print("\n== 2) 全量源码测试（offscreen）==")
        tests = sorted(f for f in os.listdir(TESTS)
                       if f.startswith("test_") and f.endswith(".py")
                       and f != "test_v13_exe.py"
                       and not _needs_other_binding(f))
        print("· 跳过另一条 Qt 绑定专属的用例：%s"
              % ", ".join(_other_binding_tests()) or "· 无跳过")
        env = {"QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": HERE}
        failed = []
        for t in tests:
            print("--- %s" % t)
            log = os.path.join(os.environ.get("TEMP", "/tmp"), t + ".log")
            # 带超时：某个用例若死等事件循环，不能把整个流水线拖死（2026-09-26 教训）
            try:
                with open(log, "w", encoding="utf-8", errors="replace") as lf:
                    rc = subprocess.run(
                        [VPY, os.path.join("tests", t)], cwd=HERE, stdout=lf, stderr=subprocess.STDOUT,
                        env=dict(os.environ, **env), timeout=300).returncode
            except subprocess.TimeoutExpired:
                rc = -9
                print("   !! 超时 300s，已终止（很可能卡在事件循环）")
            if rc != 0:
                failed.append(t)
            else:
                try:
                    os.remove(log)
                except Exception:
                    pass
        if failed:
            print("!! 失败：%s（日志见 %%TEMP%%/*.log）" % " ".join(failed))
            sys.exit(1)
        print("✓ %d 个测试全部通过" % len(tests))
    else:
        print("\n== 2) 跳过测试（--skip-tests）==")

    # ---- 3) 打包 ----
    print("\n== 3) PyInstaller 打包 ==")
    sh([VPY, "-m", "PyInstaller", "PyInjector.spec", "--noconfirm"])

    # ---- 4) 部署 + 冒烟（含冻结 exe 测试）----
    print("\n== 4) 部署冒烟 ==")
    sh([VPY, "deploy.py"])
    print("\n✅ build.py 全流程完成：源管家 v%s" % ver)


if __name__ == "__main__":
    main()
