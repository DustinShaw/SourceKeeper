# -*- coding: utf-8 -*-
"""「注入文件」伴生资源落地回归测试。

要求（用户 2026-10-20 明确）：对 py.json 配置条目做「注入文件」时，必须把 spider
用到的 py/js 等本地资源文件放到「仓库目录」里，并保持相对引用；否则 py.json 上传
电视机后影视仓找不到依赖、源直接失效。

本文件锁定 pyinj_core.land_injected_companions / collect_from_files 的行为：
  1) 主 .py 的 import/require 伴生文件会被搬进仓库 py/（保持相对结构）；
  2) 目标已有同名但内容不同 → 默认改名 _2，且**主文件里的引用同步改写**；
  3) 纯标准库依赖不产生噪声搬运；
  4) 条目的 api 与 file 均为相对路径（file == api）。
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


def _write(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


MAIN = """# -*- coding: utf-8 -*-
import helper
from base.spider import Spider

class Spider(object):
    def getName(self):
        return "注入伴生测试源"
    def getDependence(self):
        return require('./lib/a.js')
"""


# ============================================================ 1) 基础搬运
print("== 1) 注入时伴生 py/js 搬进仓库并保持相对引用 ==")
try:
    src = tempfile.mkdtemp(prefix="inject_src_")
    repo = tempfile.mkdtemp(prefix="inject_repo_")
    _write(os.path.join(src, "main.py"), MAIN)
    _write(os.path.join(src, "helper.py"), "# helper\nVALUE = 1\n")
    _write(os.path.join(src, "lib", "a.js"), "// a.js\nmodule.exports = {};\n")

    ents, logs = C.collect_from_files([os.path.join(src, "main.py")], repo, True, set(), set())
    ent = ents[0] if ents else {}
    ok("生成条目", bool(ent), logs)
    ok("api 为相对 ./py/main.py", ent.get("api") == "./py/main.py", ent.get("api"))
    ok("file == api（相对）", ent.get("file") == ent.get("api"), (ent.get("file"), ent.get("api")))
    ok("主文件已落地", os.path.isfile(os.path.join(repo, "py", "main.py")))
    ok("伴生 py 已搬运", os.path.isfile(os.path.join(repo, "py", "helper.py")))
    ok("伴生 js 已搬运", os.path.isfile(os.path.join(repo, "py", "lib", "a.js")))
    ok("引用保持相对未破坏", "import helper" in _read(os.path.join(repo, "py", "main.py")))
except Exception as ex:
    ok("基础搬运执行", False, ex)


# ==================================================== 2) 同名冲突：改名 + 引用改写
print("== 2) 目标同名但内容不同 → 改名 _2 且主文件引用同步改写 ==")
try:
    src = tempfile.mkdtemp(prefix="inject_src2_")
    repo = tempfile.mkdtemp(prefix="inject_repo2_")
    _write(os.path.join(src, "main2.py"),
           "class Spider(object):\n    def getName(self):\n        return 'x'\n"
           "    def getDependence(self):\n        return require('./lib/a.js')\n")
    _write(os.path.join(src, "lib", "a.js"), "// NEW CONTENT\n")
    # 目标仓库已存在同名、内容不同的 a.js（用户本地改过的版本，不能被覆盖）
    _write(os.path.join(repo, "py", "lib", "a.js"), "// OLD USER VERSION\n")

    ents, logs = C.collect_from_files([os.path.join(src, "main2.py")], repo, True, set(), set())
    ent = ents[0] if ents else {}
    old_kept = os.path.isfile(os.path.join(repo, "py", "lib", "a.js")) and \
        "OLD USER VERSION" in _read(os.path.join(repo, "py", "lib", "a.js"))
    new_made = os.path.isfile(os.path.join(repo, "py", "lib", "a_2.js")) and \
        "NEW CONTENT" in _read(os.path.join(repo, "py", "lib", "a_2.js"))
    main_txt = _read(os.path.join(repo, "py", "main2.py"))
    ok("目标旧文件未被覆盖（安全）", old_kept)
    ok("新内容以 _2 落地", new_made)
    ok("主文件引用已改写为 a_2", "a_2" in main_txt, main_txt)
    ok("改名后 api 仍相对", str(ent.get("api", "")).startswith("./"), ent.get("api"))
    ok("改名后 file == api", ent.get("file") == ent.get("api"), (ent.get("file"), ent.get("api")))
except Exception as ex:
    ok("冲突改名执行", False, ex)


# =================================================== 3) 纯标准库：不产生噪声搬运
print("== 3) 仅标准库依赖 → 不搬运多余文件 ==")
try:
    src = tempfile.mkdtemp(prefix="inject_src3_")
    repo = tempfile.mkdtemp(prefix="inject_repo3_")
    _write(os.path.join(src, "onlystd.py"),
           "import os, sys, json, re\nclass Spider(object):\n    def getName(self):\n        return 's'\n")
    ents, logs = C.collect_from_files([os.path.join(src, "onlystd.py")], repo, True, set(), set())
    ent = ents[0] if ents else {}
    py_dir = os.path.join(repo, "py")
    files = []
    for root, _dirs, fns in os.walk(py_dir):
        for fn in fns:
            files.append(os.path.relpath(os.path.join(root, fn), py_dir).replace(os.sep, "/"))
    ok("只落地主文件", files == ["onlystd.py"], files)
    ok("条目 api 相对", ent.get("api") == "./py/onlystd.py", ent.get("api"))
except Exception as ex:
    ok("纯标准库场景执行", False, ex)


print("\n\u7ed3\u679c\uff1a%d \u901a\u8fc7, %d \u5931\u8d25" % (passed, failed))
sys.exit(1 if failed else 0)
