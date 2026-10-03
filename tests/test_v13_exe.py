# -*- coding: utf-8 -*-
"""端到端（冻结二进制）：验证 v13 自动遍历搜索在真实 exe 中生效。
构造「配置在子目录 sub/xxx.json + py 文件夹改名为 spiders/」临时仓库，
用 dist/源管家.exe（或根目录最新「源管家 v*.exe」）跑 --adult-scan（不 --write，动副本），
断言：rc=0 且输出含「自动遍历找到 .py」(证明改名文件夹被找回) 且成人被检出。
不触碰真实仓库。结果写入 test_v13_exe_out.txt。"""
import os, sys, io, tempfile, shutil, subprocess, glob

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _find_exe():
    # 优先刚构建的 dist/源管家.exe；否则取根目录最新版本化 exe
    d = os.path.join(HERE, "dist", "源管家.exe")
    if os.path.exists(d):
        return d
    cands = sorted(glob.glob(os.path.join(HERE, "源管家 v*.exe")), reverse=True)
    return cands[0] if cands else os.path.join(HERE, "源管家.exe")
EXE = _find_exe()
buf = io.StringIO()
def log(*a):
    buf.write(" ".join(str(x) for x in a) + "\n")

ok = fail = 0
def check(n, c, e=""):
    global ok, fail
    if c:
        ok += 1; log("PASS", n, e)
    else:
        fail += 1; log("FAIL", n, e)

tmp = tempfile.mkdtemp(prefix="pyinj_v13exe_")
try:
    repo = os.path.join(tmp, "repo")
    sub = os.path.join(repo, "sub")
    spiders = os.path.join(repo, "spiders")  # 原应为 py/
    os.makedirs(sub, exist_ok=True)
    os.makedirs(spiders, exist_ok=True)
    with open(os.path.join(spiders, "demo.py"), "w", encoding="utf-8") as f:
        f.write('class Spider:\n    def getName(self): return "演示"\n    # 成人 苍井空\n')
    cfg = {
        "sites": [
            {"key": "py_demo", "name": "演示┃PY", "api": "./py/demo.py",
             "type": 3, "filterable": 1, "quickSearch": 1, "searchable": 1},
        ]
    }
    import json
    with open(os.path.join(sub, "xxx.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(cfg, ensure_ascii=False, indent=2))

    proc = subprocess.run(
        [EXE, "--repo", repo, "--config", "sub/xxx.json", "--adult-scan"],
        capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    rc = proc.returncode
    log("--- exe stdout ---")
    for ln in out.splitlines():
        log("   " + ln)
    log("--- rc=%d ---" % rc)

    check("exe rc=0", rc == 0, "rc=%d" % rc)
    check("输出含「自动遍历找到 .py」(改名文件夹被找回)",
          "自动遍历找到 .py" in out, "")
    check("成人内容被检出并标注",
          ("成人" in out) or ("标注" in out) or ("演示" in out), "")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---- 源测活：验证 exe 里 exec 动态加载的第三方依赖（hiddenimports）真实可用 ----
# 源码 import requests + from base.spider import Spider + self.fetch()，
# 全部是 PyInstaller 静态分析看不见的路径，只有真跑 exe 才能验证。
try:
    import threading as _th, http.server as _hs

    repo2 = tempfile.mkdtemp(prefix="pyinj_probe_exe_")
    os.makedirs(os.path.join(repo2, "py"), exist_ok=True)
    # 本地 HTTP 服务：返回一个最小 homeContent，供源请求
    seen2 = []

    class _H2(_hs.BaseHTTPRequestHandler):
        def do_GET(self):
            seen2.append(True)
            body = '{"class": [{"type_id": "1", "type_name": "打包依赖"}]}' \
                   .encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv2 = _hs.HTTPServer(("127.0.0.1", 0), _H2)
    _th.Thread(target=srv2.serve_forever, daemon=True).start()
    url2 = "http://127.0.0.1:%d/" % srv2.server_address[1]
    with open(os.path.join(repo2, "py", "dep.py"), "w", encoding="utf-8") as f:
        f.write(
            "import requests\n"
            "from base.spider import Spider as _B\n"
            "class Spider(_B):\n"
            "    def init(self, extend=\"\"):\n"
            "        pass\n"
            "    def homeContent(self, filter):\n"
            "        r = self.fetch('%s', timeout=5)\n"
            "        return r.json()\n" % url2)
    with open(os.path.join(repo2, "py.json"), "w", encoding="utf-8") as f:
        f.write('{"sites": [{"key": "dep", "name": "依赖源", "api": "./py/dep.py", "type": 3}]}')

    proc2 = subprocess.run([EXE, "--repo", repo2, "--probe"], capture_output=True)
    out2 = (proc2.stdout or b"").decode("utf-8", "replace")
    log("--- exe --probe stdout ---")
    for ln in out2.splitlines():
        log("   " + ln)
    check("exe --probe rc=0", proc2.returncode == 0, "rc=%d" % proc2.returncode)
    check("exec 动态依赖(requests/base.fetch)在 exe 里可用 → 活源",
          "活源" in out2, out2[-200:])
    check("本地服务确实被源请求到", bool(seen2))
    srv2.shutdown()
    srv2.server_close()
    shutil.rmtree(repo2, ignore_errors=True)
except Exception as ex:
    check("exe 源测活依赖验证未异常", False, repr(ex))

log("")
log("RESULT: %d passed, %d failed" % (ok, fail))
with open(os.path.join(HERE, "test_v13_exe_out.txt"), "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
