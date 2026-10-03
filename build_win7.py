# -*- coding: utf-8 -*-
"""build_win7.py —— Windows 7 版一键构建流水线（Qt5 / PySide2）
=================================================================
与 build.py 完全对称，但整条链路都跑在 **Python 3.9** 上（3.9 是最后支持 Win7 的
Python，3.10 起连安装器都不给 Win7 用），Qt 绑定走 PySide2 5.15.2.2（Qt5 官方支持 Win7）。

injector.py 里已内建 Qt 绑定兼容层：优先 PySide6/Qt6，ImportError 时回退
PySide2/Qt5，所以**同一份源码**既能打 Win10+ 版也能打 Win7 版。

流程（任一步失败立即中止）：
  1) 解释器体检：必须是 Python 3.9.x，且 PySide2 可导入
  2) 版本核对：APP_VERSION 须为 YYMMDDHHMM（日期+时间），日期部分必须等于今天
  3) 测试：纯逻辑 test_*.py（跳过硬依赖 PySide6 的 GUI 用例）+ test_win7_build.py（Qt5 GUI 冒烟）
  4) PyInstaller 打包：PyInjector-win7.spec -> dist/源管家Win7.exe
  5) 部署冒烟：deploy_win7.py（版本化命名 + 冻结 exe CLI 冒烟 + py.json md5 校验）

用法：
  python build_win7.py            # 完整流水线
  python build_win7.py --skip-tests
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


def main():
    # ---- 1) 解释器体检：必须 Python 3.9 + PySide2 ----
    print("== 1) 解释器体检 ==")
    venv_py = os.path.join(os.path.expanduser("~"),
                           ".workbuddy/binaries/python/envs/win39/python.exe")
    VPY = venv_py if os.path.isfile(venv_py) else sys.executable
    print("使用解释器：%s" % VPY)
    info = subprocess.run([VPY, "-c",
                           "import sys, platform; sys.stdout.write(platform.python_version())"],
                          capture_output=True, text=True)
    ver = info.stdout.strip()
    if not ver.startswith("3.9."):
        print("!! Win7 版必须用 Python 3.9，当前是 %s —— "
              "请改用 Python 3.9 环境（见 requirements-win7.txt）" % (ver or info.stderr[:120]))
        sys.exit(1)
    chk = subprocess.run([VPY, "-c", "import PySide2; print(PySide2.__version__)"],
                         capture_output=True, text=True)
    if chk.returncode != 0:
        print("!! PySide2 不可用：%s" % chk.stderr.strip()[:200])
        sys.exit(1)
    print("✓ Python %s + PySide2 %s" % (ver, chk.stdout.strip()))

    # ---- 2) 版本核对 ----
    print("\n== 2) 版本核对 ==")
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

    # ---- 3) 测试 ----
    if "--skip-tests" not in sys.argv:
        print("\n== 3) 测试（纯逻辑用例 + Qt5 GUI 冒烟）==")
        env = {"QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": HERE}
        tests = []
        for f in sorted(os.listdir(TESTS)):
            if not (f.startswith("test_") and f.endswith(".py")):
                continue
            src = open(os.path.join(TESTS, f), encoding="utf-8", errors="replace").read()
            if "PySide6" in src:
                print("--- %s  [跳过：硬依赖 PySide6，属 Win10+ 专属用例]" % f)
                continue
            tests.append(f)
        failed = []
        for t in tests:
            print("--- %s" % t)
            log = os.path.join(os.environ.get("TEMP", "/tmp"), t + ".win7.log")
            with open(log, "w", encoding="utf-8", errors="replace") as lf:
                rc = subprocess.call([VPY, os.path.join("tests", t)], cwd=HERE, stdout=lf,
                                     stderr=subprocess.STDOUT,
                                     env=dict(os.environ, **env))
            if rc != 0:
                failed.append(t)
        if os.path.isfile(os.path.join(TESTS, "test_win7_build.py")):
            print("--- test_win7_build.py  [Qt5 GUI 冒烟]")
            log = os.path.join(os.environ.get("TEMP", "/tmp"), "test_win7_build.log")
            with open(log, "w", encoding="utf-8", errors="replace") as lf:
                rc = subprocess.call([VPY, os.path.join("tests", "test_win7_build.py")], cwd=HERE, stdout=lf,
                                     stderr=subprocess.STDOUT,
                                     env=dict(os.environ, **env))
            if rc != 0:
                failed.append("test_win7_build.py")
        if failed:
            print("!! 失败：%s（日志见 %%TEMP%%/*.win7.log）" % " ".join(failed))
            sys.exit(1)
        print("✓ Win7 版测试全部通过")
    else:
        print("\n== 3) 跳过测试（--skip-tests）==")

    # ---- 4) 打包 ----
    print("\n== 4) PyInstaller 打包（Qt5）==")
    sh([VPY, "-m", "PyInstaller", "PyInjector-win7.spec", "--noconfirm"])

    # ---- 5) 部署 + 冒烟 ----
    print("\n== 5) 部署冒烟 ==")
    sh([VPY, "deploy_win7.py"])
    print("\n✅ build_win7.py 全流程完成：源管家 v%s-Win7" % ver)


if __name__ == "__main__":
    main()
