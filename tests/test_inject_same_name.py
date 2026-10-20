# -*- coding: utf-8 -*-
"""「注入文件」同名主 .py 覆盖保护回归测试。

背景（2026-10-20 用户决策）：`make_entry` 原来对主 .py 直接 `shutil.copy2` 无条件覆盖，
仓库 py/ 里已有同名脚本会被**静默毁掉**。伴生文件已有「同名不同内容→改名 _2」保护，
主 .py 缺这层 → 属不对称风险，必须补齐。

本文件锁定 pyinj_core.make_entry / _pick_free_py_name 的行为：
  1) 目标不存在        → 正常拷贝，api 指向 ./py/x.py；
  2) 目标存在且内容相同 → 复用不重复拷贝，api 仍为 ./py/x.py（不产生 _2）；
  3) 目标存在且内容不同 → 改名 x_2.py，**旧文件内容一字不动**，api 指向新名；
  4) 连续注入 3 个不同内容的同名脚本 → 依次得 x.py / x_2.py / x_3.py，互不覆盖；
  5) key 始终基于**原始文件名**，改名不影响 key 稳定性；
  6) file 恒等于 api 且为相对路径。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyinj_core as C  # noqa: E402

passed = 0
failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("  \u2713 " + name)
    else:
        failed += 1
        print("  \u2717 " + name + "   " + str(extra))


SPIDER = '''# -*- coding: utf-8 -*-
class Spider:
    def init(self, ext=""):
        pass
    def homeContent(self, filter):
        return {"class": []}
'''


def _write(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _tmpdir():
    return tempfile.mkdtemp(prefix="pyinj_same_")


# ---------------------------------------------------------------- 1) 全新落地
tmp = _tmpdir()
try:
    src = os.path.join(tmp, "src", "x.py")
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "py"), exist_ok=True)
    _write(src, SPIDER)
    ent = C.make_entry(src, repo, True)
    ok("全新落地：文件已拷贝", os.path.isfile(os.path.join(repo, "py", "x.py")))
    ok("全新落地：api == ./py/x.py", ent.get("api") == "./py/x.py", ent.get("api"))
    ok("全新落地：file == api", ent.get("file") == ent.get("api"))
except Exception as ex:
    ok("全新落地", False, ex)

# ------------------------------------------------- 2) 同名且内容相同 → 复用不重拷
tmp = _tmpdir()
try:
    src = os.path.join(tmp, "src", "x.py")
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "py"), exist_ok=True)
    _write(src, SPIDER)
    _write(os.path.join(repo, "py", "x.py"), SPIDER)
    mtime_before = os.path.getmtime(os.path.join(repo, "py", "x.py"))
    ent = C.make_entry(src, repo, True)
    ok("同名同内容：未产生 _2 文件",
       not os.path.exists(os.path.join(repo, "py", "x_2.py")))
    ok("同名同内容：目标文件未被重写",
       os.path.getmtime(os.path.join(repo, "py", "x.py")) == mtime_before)
    ok("同名同内容：api 仍是 ./py/x.py", ent.get("api") == "./py/x.py", ent.get("api"))
except Exception as ex:
    ok("同名同内容", False, ex)

# ------------------------------------------------- 3) 同名但内容不同 → 改名 _2
tmp = _tmpdir()
try:
    src = os.path.join(tmp, "src", "x.py")
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "py"), exist_ok=True)
    _write(src, SPIDER + "# 新版本内容\n")
    _write(os.path.join(repo, "py", "x.py"), SPIDER + "# 旧版本内容\n")
    old_content = _read(os.path.join(repo, "py", "x.py"))
    ent = C.make_entry(src, repo, True)
    ok("同名不同内容：新文件落为 x_2.py",
       os.path.isfile(os.path.join(repo, "py", "x_2.py")))
    ok("同名不同内容：旧文件内容一字未动",
       _read(os.path.join(repo, "py", "x.py")) == old_content)
    ok("同名不同内容：api 指向新名 ./py/x_2.py",
       ent.get("api") == "./py/x_2.py", ent.get("api"))
    ok("同名不同内容：file == api", ent.get("file") == ent.get("api"))
    ok("同名不同内容：key 仍基于原始名（不含 _2）",
       ent.get("key") == "py_x", ent.get("key"))
except Exception as ex:
    ok("同名不同内容", False, ex)

# --------------------------------------- 4) 连续注入 3 个不同内容的同名脚本
tmp = _tmpdir()
try:
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "py"), exist_ok=True)
    apis = []
    for i in range(3):
        src = os.path.join(tmp, "src", "x.py")
        _write(src, SPIDER + "# 版本 %d\n" % i)
        apis.append(C.make_entry(src, repo, True).get("api"))
    ok("连续注入：依次得到 x / x_2 / x_3",
       apis == ["./py/x.py", "./py/x_2.py", "./py/x_3.py"], apis)
    ok("连续注入：三个文件都存在",
       all(os.path.isfile(os.path.join(repo, "py", n))
           for n in ("x.py", "x_2.py", "x_3.py")))
    ok("连续注入：x_3 内容是最后一版",
       _read(os.path.join(repo, "py", "x_3.py")).endswith("# 版本 2\n"))
except Exception as ex:
    ok("连续注入", False, ex)

# -------------------------------------------- 5) 不拷贝时（copy_into_py=False）
tmp = _tmpdir()
try:
    src = os.path.join(tmp, "src", "x.py")
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo, exist_ok=True)
    _write(src, SPIDER)
    ent = C.make_entry(src, repo, False)
    ok("copy_into_py=False：未创建 py/ 目录",
       not os.path.exists(os.path.join(repo, "py")))
    ok("copy_into_py=False：api 仍为 ./py/x.py",
       ent.get("api") == "./py/x.py", ent.get("api"))
except Exception as ex:
    ok("copy_into_py=False", False, ex)

# ---------------------------------- 6) py/ 内脚本（inside_py 分支）不受影响
tmp = _tmpdir()
try:
    repo = os.path.join(tmp, "repo")
    _write(os.path.join(repo, "py", "y.py"), SPIDER)
    ent = C.make_entry(os.path.join(repo, "py", "y.py"), repo, True)
    ok("仓库内脚本：api == ./py/y.py", ent.get("api") == "./py/y.py", ent.get("api"))
    ok("仓库内脚本：未产生多余副本",
       not os.path.exists(os.path.join(repo, "py", "y_2.py")))
except Exception as ex:
    ok("仓库内脚本", False, ex)

print("\n结果：%d 通过, %d 失败" % (passed, failed))
sys.exit(1 if failed else 0)
