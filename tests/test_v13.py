# -*- coding: utf-8 -*-
"""v13 安全测试：.py 文件夹被改名/移动后，自动遍历搜索找回（不经 Qt）。
仅测试纯函数 + 复刻 _AdultScanWorker.run 的解析算法；不触碰真实仓库。
结果写入 test_v13_out.txt 供 Read（沙箱 shell 无 cat/ls）。"""
import os, sys, io, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import injector as I

buf = io.StringIO()
def log(*a):
    buf.write(" ".join(str(x) for x in a) + "\n")

ok = 0
fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        log("PASS", name, extra)
    else:
        fail += 1
        log("FAIL", name, extra)

# ---- 构造临时仓库：配置在子目录 sub/xxx.json；py 文件夹改名为 spiders 放在仓库根 ----
tmp = tempfile.mkdtemp(prefix="pyinj_v13_")
try:
    repo = os.path.join(tmp, "repo")
    sub = os.path.join(repo, "sub")
    py_renamed = os.path.join(repo, "spiders")  # 原应为 py/
    os.makedirs(sub, exist_ok=True)
    os.makedirs(py_renamed, exist_ok=True)

    # 写一个 spider
    with open(os.path.join(py_renamed, "demo.py"), "w", encoding="utf-8") as f:
        f.write('class Spider:\n    def getName(self): return "演示"\n    # 测试成人 苍井空\n')
    with open(os.path.join(py_renamed, "clean.py"), "w", encoding="utf-8") as f:
        f.write('class Spider:\n    def getName(self): return "干净"\n')

    # 配置文件：sub/xxx.json，站点 api 指向 ./py/demo.py 与 ./py/clean.py
    cfg_text = (
        '{\n'
        '  "sites": [\n'
        '    {"key":"py_demo","name":"演示┃PY","api":"./py/demo.py","type":3,"filterable":1,"quickSearch":1,"searchable":1},\n'
        '    {"key":"py_clean","name":"干净┃PY","api":"./py/clean.py","type":3,"filterable":1,"quickSearch":1,"searchable":1}\n'
        '  ]\n'
        '}\n'
    )
    cfg = os.path.join(sub, "xxx.json")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(cfg_text)

    repo_dir = repo
    cfg_name = "sub/xxx.json"
    base_dir = I.cfg_base_dir(repo_dir, cfg_name)   # = .../repo/sub
    check("base_dir 为配置子目录", os.path.normpath(base_dir) == os.path.normpath(sub),
          base_dir)

    # 1) 旧式解析（v12 行为）找不到 ==>.py
    p1 = I.resolve_spider_path(base_dir, "./py/demo.py", repo_dir)
    check("v12 直接解析找不到被改名文件夹里的 .py", not os.path.isfile(p1), p1)

    # 2) 遍历搜索根：exe / repo / base_dir
    roots = I.default_search_roots(repo_dir, cfg_name)
    check("搜索根含 exe/repo/base_dir 去重", len(roots) == 3, roots)

    # 3) discover_py_files 建立 basename 映射
    progress_hits = []
    nm = I.discover_py_files(roots, lambda d, t, dn: progress_hits.append(d))
    check("discover 找到 demo.py", nm.get("demo.py") and os.path.isfile(nm["demo.py"]),
          nm.get("demo.py"))
    check("discover 找到 clean.py", nm.get("clean.py") and os.path.isfile(nm["clean.py"]),
          nm.get("clean.py"))
    check("搜索进度回调被触发", len(progress_hits) >= 1, "hits=%d" % len(progress_hits))

    # 4) 复刻 worker 阶段 A 解析：resolve_spider_path_resilient
    p2, by_search = I.resolve_spider_path_resilient(base_dir, "./py/demo.py", repo_dir, nm)
    check("resilient 经遍历搜索找到 .py", os.path.isfile(p2) and by_search is True, p2)
    check("找到的是改名后的 spiders/demo.py", "spiders" in os.path.normpath(p2), p2)

    # 5) detect_adult 用找回的 .py 命中成人（演示含 苍井空）
    is_ad, kw = I.detect_adult(p2, "演示")
    check("找回的 .py 可正常做成人检测(命中)", is_ad and kw in ("成人", "苍井空"), (is_ad, kw))

    # 6) 不存在的 .py：resilient 仍返回原路径（文件不存在），退化为仅按名
    p3, by3 = I.resolve_spider_path_resilient(base_dir, "./py/nope.py", repo_dir, nm)
    check("不存在的 .py 找不到", not os.path.isfile(p3), p3)
    is_ad3, kw3 = I.detect_adult(p3, "正规影视")  # 文件不存在->仅按名
    check("找不到 .py 时退化为按站点名(否)", is_ad3 is False, (is_ad3, kw3))

    # 7) collect_orphan_py 带 search_roots：删除 demo 应能定位改名文件夹里的 .py
    remaining = [{"key": "py_clean", "api": "./py/clean.py"}]
    key_api = {"py_demo": "./py/demo.py"}
    to_del, skipped = I.collect_orphan_py(base_dir, {"py_demo"}, key_api, remaining,
                                           repo_dir, search_roots=roots)
    check("orphan 经搜索定位到改名文件夹 .py", len(to_del) == 1 and "spiders" in os.path.normpath(to_del[0]), to_del)

    # 8) 同名优先级：basename 取首个（同名文件应取遍历中第一个匹配的，不报错）
    dup = os.path.join(repo, "dup.py")
    with open(dup, "w", encoding="utf-8") as f:
        f.write("class Spider: pass\n")
    nm2 = I.discover_py_files(roots)
    check("存在多个同名 .py 不崩溃", "dup.py" in nm2, nm2.get("dup.py"))

    # 9) stop_check：关闭后遍历立即中止
    counter = {"n": 0}
    def sc():
        counter["n"] += 1
        return counter["n"] > 2
    nm3 = I.discover_py_files(roots, None, sc)
    check("stop_check 触发后中止遍历", counter["n"] > 2, "calls=%d" % counter["n"])

finally:
    shutil.rmtree(tmp, ignore_errors=True)

log("")
log("RESULT: %d passed, %d failed" % (ok, fail))
with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_v13_out.txt"),
          "w", encoding="utf-8") as fo:
    fo.write(buf.getvalue())
print(buf.getvalue())
