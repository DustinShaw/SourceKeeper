# -*- coding: utf-8 -*-
"""远程抓取「镜像回退」测试（纯逻辑，无需 Qt）
=================================================
背景：GitHub raw 在国内直连失败是最高频的失败原因（同类工具普遍挂镜像前缀）。
原则（本测试逐条钉死）：
  1) **直连优先**：直连成功绝不碰镜像（避免拿到镜像缓存的旧内容还不自知）；
  2) 只有 **github 系主机**才生成镜像候选（localhost/内网/其它站点一律不走，避免行为漂移）；
  3) 镜像成功的 URL 如实回填 info["mirror"]，供 GUI 上报；全失败则原样抛错并带直连原因；
  4) MIRROR_FALLBACK=False 时完全禁用；
  5) 远程配套文件搬运把用到的镜像记入 plan["mirrors"] → stats["via_mirror"]。

用法：python test_mirror.py
"""
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import pyinj_core as C  # noqa: E402

PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


RAW = "https://raw.githubusercontent.com/user/repo/main/py/lib/a.js"
GH_PAGE = "https://github.com/user/repo/raw/main/py/lib/a.js"
LOCAL = "http://127.0.0.1:8080/py.json"

# ------------------------------------------------------------ A) 镜像 URL 生成
print("== A) 镜像候选生成：只对 github 系主机 ==")
ms = C._mirror_urls(RAW)
ok("raw.githubusercontent.com 生成多个前缀镜像", len(ms) >= 3, ms)
ok("前缀镜像形式正确（<mirror><原URL>）",
   all(m.endswith(RAW) for m in ms if not m.startswith("https://cdn.jsdelivr.net")), ms)
ok("含 jsDelivr 形式转换（/gh/user/repo@branch/path）",
   "https://cdn.jsdelivr.net/gh/user/repo@main/py/lib/a.js" in ms, ms)
ms2 = C._mirror_urls(GH_PAGE)
ok("github.com/raw/… 也转出 jsDelivr",
   "https://cdn.jsdelivr.net/gh/user/repo@main/py/lib/a.js" in ms2, ms2)
ok("非 github 主机 → 无镜像候选（localhost 不走镜像）", C._mirror_urls(LOCAL) == [], C._mirror_urls(LOCAL))
ok("file:// → 无镜像候选", C._mirror_urls("file:///tmp/x/py.json") == [])
ok("空/非法值不炸", C._mirror_urls("") == [] and C._mirror_urls(None) == [])

# ------------------------------------------------- B) 直连优先 / 镜像回退行为
print("\n== B) 直连优先、失败后镜像回退 ==")
calls = []


def _fake_read_ok(url, timeout=10, proxy=None):
    calls.append(url)
    return b'{"sites": []}'


orig_read = C._http_read
C._http_read = _fake_read_ok
try:
    info = {}
    txt = C.fetch_text_from_url(RAW, info=info)
    ok("直连成功即返回内容", "sites" in txt, txt)
    ok("直连成功时只调用一次（绝不碰镜像）", len(calls) == 1 and calls[0] == RAW, calls)
    ok("info['mirror'] 保持 None（如实：没走镜像）", info.get("mirror") is None, info)
finally:
    C._http_read = orig_read

calls.clear()


def _fake_read_direct_fail(url, timeout=10, proxy=None):
    calls.append(url)
    if url == RAW:
        raise ValueError("HTTP 502")
    return b'{"ok": 1}'


C._http_read = _fake_read_direct_fail
try:
    info = {}
    txt = C.fetch_text_from_url(RAW, info=info)
    ok("直连失败 → 镜像成功取回内容", txt.strip() == '{"ok": 1}', txt)
    ok("第一次仍是直连（顺序正确）", calls[0] == RAW, calls)
    ok("如实上报所用镜像", info.get("mirror") and info["mirror"] != RAW, info)
    ok("记录了直连失败原因", bool(info.get("error")), info)
finally:
    C._http_read = orig_read


def _always_fail(url, timeout=10, proxy=None):
    calls.append(url)
    raise ValueError("boom")


calls.clear()
C._http_read = _always_fail
try:
    try:
        C.fetch_text_from_url(RAW, timeout=1)
        ok("直连+镜像全失败应抛错", False)
    except Exception as ex:
        ok("直连+镜像全失败应抛错（且带直连原因）", "boom" in str(ex), str(ex))
    ok("逐个镜像都试过（次数 > 1）", len(calls) > 1, len(calls))
finally:
    C._http_read = orig_read

calls.clear()
C._http_read = _always_fail
try:
    try:
        C.fetch_text_from_url(LOCAL, timeout=1)
        ok("非 github 主机失败应抛错", False)
    except Exception:
        ok("非 github 主机失败应抛错", True)
    ok("非 github 主机不尝试任何镜像（仅 1 次直连）",
       len(calls) == 1 and calls[0] == LOCAL, calls)
finally:
    C._http_read = orig_read

# 二进制（.jar）同样支持
calls.clear()
_MIRROR_PREFIXES = ("https://ghfast.top/", "https://ghproxy.net/", "https://gh-proxy.com/",
                    "https://gh.llkk.cc/", "https://cdn.jsdelivr.net/")


def _direct_fail_mirror_ok(url, timeout=10, proxy=None):
    calls.append(url)
    if any(url.startswith(p) for p in _MIRROR_PREFIXES):
        return b'{"ok": 1}'
    raise ValueError("HTTP 502")


C._http_read = _direct_fail_mirror_ok
try:
    info = {}
    jar_url = "https://raw.githubusercontent.com/user/repo/main/jars/pg.jar"
    data = C.fetch_binary_from_url(jar_url, info=info)
    ok("二进制抓取也走镜像回退", data == b'{"ok": 1}', data)
    ok("二进制同样上报镜像", bool(info.get("mirror")), info)
finally:
    C._http_read = orig_read

# 总开关
calls.clear()
C._http_read = _always_fail
_saved = C.MIRROR_FALLBACK
try:
    C.MIRROR_FALLBACK = False
    try:
        C.fetch_text_from_url(RAW, timeout=1)
        ok("MIRROR_FALLBACK=False 时禁用镜像", False)
    except Exception:
        ok("MIRROR_FALLBACK=False 时禁用镜像", len(calls) == 1, calls)
finally:
    C.MIRROR_FALLBACK = _saved
    C._http_read = orig_read

print("\n== C) 远程配套搬运：镜像使用如实进 stats ==")
import tempfile  # noqa: E402
import shutil  # noqa: E402

tmp = tempfile.mkdtemp(prefix="pyinj_mirror_")
tgt = os.path.join(tmp, "tgt")
C._http_read = _direct_fail_mirror_ok
try:
    rb = "https://raw.githubusercontent.com/user/repo/main/"
    ent = {"key": "m1", "api": "./py/x.py", "type": 3}
    plan = C.plan_companion_files_remote(rb, tgt, [ent])
    ok("plan['mirrors'] 记录镜像来源",
       (plan.get("mirrors") or {}).get("py/x.py"), plan.get("mirrors"))
    st = C.copy_companions_remote(rb, tgt, [ent], plan=plan)
    ok("stats['via_mirror'] 记录经镜像搬运的文件", "py/x.py" in st.get("via_mirror", []), st)
    ok("文件确实落盘", os.path.isfile(os.path.join(tgt, "py", "x.py")))
finally:
    C._http_read = orig_read
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
