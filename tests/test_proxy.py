# -*- coding: utf-8 -*-
"""自定义代理服务器（pyinj_proxy）回归测试 —— **纯逻辑**部分（零 Qt 依赖）。

覆盖：
  A. 解析 / 规范化 / 纠错提示（http、https、socks5、账号密码、IPv6、无效输入）
  B. 全局单例 + 订阅通知 + 子进程环境变量（留空 = 直连，不被环境变量悄悄接管）
  C. 直连请求（本地 HTTP 服务）：状态码 / body / 耗时
  D. **内置 SOCKS5 隧道**（自造 SOCKS5 服务）—— 不依赖 PySocks
  E. **HTTP CONNECT 隧道**（自造 CONNECT 代理）+ 代理返回 502 的失败路径
  F. check_proxy：以「能否连到 Google 首页」为准（测试时把 test_url 指向本地服务）
  G. 全链路接入：pyinj_core.check_url_reachable / deep_fetch_text / _fetch_url_bytes、
     pyinj_netdiag.diagnose_url/diagnose_source、pyinj_speed、pyinj_jar 都要走代理
  H. 源测活子进程：probe_py_source 注入代理环境变量（桩掉 subprocess.run，不真的跑）

⚠ 本文件**必须保持零 Qt 依赖**：Win7 链的筛选规则是「文件里出现 Qt6 绑定模块名就整文件
   跳过」，一旦这里出现该字样，就会连上面 8 组纯逻辑用例一起被跳过。
   GUI 用例（_ProxyControls 控件行）请写到姊妹文件 test_proxy_gui.py。

全程**不访问真实外网**：所有断言都指向 127.0.0.1 上的临时服务或用桩替换。
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import io
import json
import select
import socket
import struct
import sys
import threading
import time
import types

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


# ============================================================
# 本地测试服务
# ============================================================
JAR_BYTES = b"PK\x03\x04" + b"jar-content-" * 200      # > 1024 字节，模拟 jar


class _Handler(object):
    """极简 HTTP 处理器（不引 http.server，避免依赖），供各测试复用。"""

    @staticmethod
    def serve(sock):
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                data += chunk
            line = data.split(b"\r\n")[0].decode("latin-1")
            path = line.split()[1] if len(line.split()) > 1 else "/"
            if path.startswith("/jar"):
                body = JAR_BYTES
                ctype = "application/java-archive"
            elif path.startswith("/notfound"):
                sock.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                return
            else:
                body = ("hello-from-local:%s" % path).encode()
                ctype = "text/html; charset=utf-8"
            head = ("HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                    "Connection: close\r\n\r\n" % (ctype, len(body)))
            sock.sendall(head.encode() + body)
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass


def start_http_server():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except Exception:
                return
            threading.Thread(target=_Handler.serve, args=(c,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1]


def _pump(a, b):
    socks = [a, b]
    while True:
        try:
            r, _w, _x = select.select(socks, [], [], 5)
        except Exception:
            break
        if not r:
            break
        for s in r:
            try:
                d = s.recv(65536)
            except Exception:
                d = b""
            if not d:
                for x in socks:
                    try:
                        x.close()
                    except Exception:
                        pass
                return
            try:
                (b if s is a else a).sendall(d)
            except Exception:
                return


def start_socks5_proxy(require_auth=None):
    """自造 SOCKS5 代理（支持无认证与用户名/密码认证）。require_auth=(user, pwd) 时强制认证。"""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def handle(c):
        try:
            v, n = c.recv(2), 0
            methods = c.recv(v[1]) if False else c.recv(v[1])
            if require_auth:
                if b"\x02" not in methods:
                    c.sendall(b"\x05\xff")
                    c.close()
                    return
                c.sendall(b"\x05\x02")
                ver = c.recv(1)
                ln = c.recv(1)[0]
                user = c.recv(ln).decode("utf-8", "replace")
                pl = c.recv(1)[0]
                pwd = c.recv(pl).decode("utf-8", "replace")
                if (user, pwd) != require_auth:
                    c.sendall(b"\x01\x01")
                    c.close()
                    return
                c.sendall(b"\x01\x00")
            else:
                c.sendall(b"\x05\x00")
            h = c.recv(4)
            atyp = h[3]
            if atyp == 3:
                host = c.recv(c.recv(1)[0]).decode()
            elif atyp == 1:
                host = socket.inet_ntoa(c.recv(4))
            else:
                c.close()
                return
            port = struct.unpack(">H", c.recv(2))[0]
            up = socket.create_connection((host, port), timeout=5)
            c.sendall(b"\x05\x00\x00\x01" + b"\x00" * 4 + b"\x00\x00")
            _pump(c, up)
        except Exception:
            try:
                c.close()
            except Exception:
                pass

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except Exception:
                return
            threading.Thread(target=handle, args=(c,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1]


def start_connect_proxy(force_code=None):
    """自造 HTTP CONNECT 代理。force_code='502 Bad Gateway' 时一律拒绝（测试失败路径）。"""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    seen = {"auth": None, "target": None}

    def handle(c):
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                d = c.recv(4096)
                if not d:
                    return
                data += d
            lines = data.split(b"\r\n")
            first = lines[0].decode("latin-1")
            for ln in lines:
                if ln.lower().startswith(b"proxy-authorization:"):
                    seen["auth"] = ln.decode("latin-1")
            if force_code:
                c.sendall(("HTTP/1.1 %s\r\n\r\n" % force_code).encode())
                c.close()
                return
            target = first.split()[1]
            seen["target"] = target
            host, port = target.rsplit(":", 1)
            up = socket.create_connection((host, int(port)), timeout=5)
            c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            _pump(c, up)
        except Exception:
            try:
                c.close()
            except Exception:
                pass

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except Exception:
                return
            threading.Thread(target=handle, args=(c,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1], seen


HTTP_PORT = start_http_server()
BASE = "http://127.0.0.1:%d" % HTTP_PORT


# ============================================================
print("\n== A) 解析 / 规范化 / 纠错 ==")
a = P.parse_proxy("127.0.0.1:7890")
ok("裸 host:port → http", a and a["scheme"] == "http" and a["port"] == 7890, a)
ok("规范化串", a["raw"] == "http://127.0.0.1:7890", a.get("raw"))
b = P.parse_proxy("socks5://user:p%40ss@10.0.0.5:1080")
ok("socks5 + 账号密码（url 解码）",
   b and b["user"] == "user" and b["password"] == "p@ss", b)
ok("显示时隐去密码", P.display_proxy(b) == "socks5://user:***@10.0.0.5:1080",
   P.display_proxy(b))
ok("socks5h 受支持", P.parse_proxy("socks5h://127.0.0.1:1080")["scheme"] == "socks5h")
ok("https 代理", P.parse_proxy("https://p.example.com:8443")["port"] == 8443)
ok("IPv6 字面量", P.parse_proxy("http://[::1]:7890")["host"] == "::1",
   P.parse_proxy("http://[::1]:7890"))
ok("显式协议无端口 → 协议默认端口",
   P.parse_proxy("https://p.example.com")["port"] == 443
   and P.parse_proxy("socks5://p.example.com")["port"] == 1080)
ok("只写 host 不臆测端口 → 无效", P.parse_proxy("127.0.0.1") is None
   and P.parse_proxy("garbage") is None)
ok("不支持的协议 → 无效", P.parse_proxy("ftp://x:21") is None)
ok("空值 → 无效", P.parse_proxy("") is None and P.parse_proxy(None) is None)
ok("「代理：」前缀噪音被剥离",
   P.parse_proxy("代理：http://127.0.0.1:7890")["port"] == 7890)
ok("纠错提示：缺端口", "端口" in P.parse_error_hint("garbage"), P.parse_error_hint("garbage"))
ok("纠错提示：协议不支持", "协议" in P.parse_error_hint("ftp://x:21"))

print("\n== B) 全局单例 / 订阅 / 子进程环境变量 ==")
seen = []
P.subscribe(lambda s: seen.append(s))
P.set_active("127.0.0.1:7890")
ok("set/get 生效", P.get_active() and P.get_active()["port"] == 7890)
ok("订阅收到变更", seen and seen[-1] == "http://127.0.0.1:7890", seen)
env = P.proxy_env()
ok("proxy_env 六大写小写键齐全",
   len(env) == 6 and env["HTTPS_PROXY"] == "http://127.0.0.1:7890"
   and env["all_proxy"] == env["ALL_PROXY"], env)
ok("ProxyHandler 映射", P.proxy_handler_map() == {"http": "http://127.0.0.1:7890",
                                                "https": "http://127.0.0.1:7890"})
ok("resolve('') 强制直连", P.resolve("") is None)
ok("resolve(dict) 原样返回", isinstance(P.resolve(P.parse_proxy("127.0.0.1:1")), dict))
P.set_active("")
ok("留空 = 直连（不被 HTTP_PROXY 环境变量悄悄接管）", P.get_active() is None,
   P.get_active())
ok("直连时 proxy_env 为空", P.proxy_env() == {})
ok("环境变量代理仅作提示", isinstance(P.env_proxy_raw(), str))
P.set_active("bad-input")
ok("无效输入 = 直连（但界面会提示，不静默采纳）", P.get_active() is None)
P.set_active("")

print("\n== C) 直连请求 ==")
r = P.request_via(None, BASE + "/x", timeout=5)
ok("直连 200", r["ok"] and r["status"] == 200, r)
ok("body 正确", r["body"].startswith(b"hello-from-local"), r["body"][:40])
ok("latency 为毫秒整数", isinstance(r["latency_ms"], int))
ok("404 → ok=False 且记状态码",
   P.request_via(None, BASE + "/notfound", timeout=5)["ok"] is False
   and P.request_via(None, BASE + "/notfound", timeout=5)["status"] == 404)
r2 = P.request_via(None, "http://127.0.0.1:1/", timeout=2)
ok("拒连 → 明确错误信息", (not r2["ok"]) and r2["err"], r2["err"])

print("\n== D) 内置 SOCKS5 隧道（零依赖，不需要 PySocks）==")
sp = start_socks5_proxy()
rs = P.request_via(P.parse_proxy("socks5://127.0.0.1:%d" % sp), BASE + "/s", timeout=5)
ok("经 SOCKS5 取到 200", rs["ok"] and rs["status"] == 200, rs)
ok("body 透传正确", rs["body"].startswith(b"hello-from-local"), rs["body"][:40])
spa = start_socks5_proxy(require_auth=("u", "p"))
rsp = P.request_via(P.parse_proxy("socks5://u:p@127.0.0.1:%d" % spa), BASE + "/a", timeout=5)
ok("SOCKS5 用户名/密码认证通过", rsp["ok"] and rsp["status"] == 200, rsp)
rsp2 = P.request_via(P.parse_proxy("socks5://u:wrong@127.0.0.1:%d" % spa), BASE + "/a", timeout=5)
ok("SOCKS5 密码错误 → 明确失败", (not rsp2["ok"]) and rsp2["err"], rsp2["err"])

print("\n== E) HTTP CONNECT 隧道 ==")
cp, seen_conn = start_connect_proxy()
rc = P.request_via(P.parse_proxy("http://127.0.0.1:%d" % cp), BASE + "/c", timeout=5)
ok("经 HTTP 代理取到 200", rc["ok"] and rc["status"] == 200, rc)
ok("代理收到 CONNECT 目标", seen_conn["target"] == "127.0.0.1:%d" % HTTP_PORT,
   seen_conn["target"])
cpa, seen_auth = start_connect_proxy()
P.request_via(P.parse_proxy("http://user:pass@127.0.0.1:%d" % cpa), BASE + "/c2", timeout=5)
ok("代理认证头已发出（Basic）",
   seen_auth["auth"] and "Basic" in seen_auth["auth"], seen_auth["auth"])
cpb, _ = start_connect_proxy(force_code="502 Bad Gateway")
rcb = P.request_via(P.parse_proxy("http://127.0.0.1:%d" % cpb), BASE + "/c3", timeout=5)
ok("代理 502 → ok=False 且提示 CONNECT 被拒",
   (not rcb["ok"]) and "CONNECT" in rcb["err"], rcb["err"])
ok("死代理 → 网络错误可读",
   (not P.request_via(P.parse_proxy("http://127.0.0.1:1"), BASE, timeout=2)["ok"]))

print("\n== F) check_proxy（口径：能否连到 Google 首页；测试指向本地）==")
c_ok = P.check_proxy("http://127.0.0.1:%d" % cp, test_url=BASE + "/g", timeout=5,
                     with_direct=False)
ok("可用代理 → 正常", c_ok["ok"] and c_ok["label"] == "正常" and c_ok["status"] == 200, c_ok)
ok("note 报告状态码与耗时", "HTTP 200" in c_ok["note"] and "ms" in c_ok["note"], c_ok["note"])
c_bad = P.check_proxy("http://127.0.0.1:1", test_url=BASE, timeout=2, with_direct=False)
ok("不可用代理 → 不可用 + 原因", (not c_bad["ok"]) and c_bad["label"] == "不可用"
   and "代理服务器不可用" in c_bad["note"], c_bad["note"])
c_fmt = P.check_proxy("garbage")
ok("格式错误单独标注", c_fmt["label"] == "格式错误" and not c_fmt["valid"], c_fmt)
c_none = P.check_proxy("")
ok("未配置单独标注", c_none["label"] == "未配置" and not c_none["valid"], c_none)
c_applied = P.check_proxy("http://127.0.0.1:%d" % cp, test_url=BASE + "/g", timeout=5,
                          with_direct=True)
ok("带直连对照时 applied 字段有意义（直连也通 → False）",
   c_applied["applied"] is False, c_applied.get("applied"))
ok("默认测试地址就是 Google 首页", P.CHECK_URL == "https://www.google.com/")

print("\n== G) 全链路接入（可达性 / 深度检测 / 远程抓取 / 网络诊断 / 测速 / JAR）==")
import pyinj_core as C
import pyinj_netdiag as ND
import pyinj_speed as SP
import pyinj_jar as JAR

# G1 check_url_reachable：配了代理后只走经代理的 HTTP
P.set_active("http://127.0.0.1:%d" % cp)
ok_chk, meth, _err = C.check_url_reachable(BASE + "/g")
ok("check_url_reachable 经代理成功且标注 proxy",
   ok_chk and meth.startswith("proxy:"), (ok_chk, meth))
P.set_active("")
ok_chk2, meth2, _e2 = C.check_url_reachable(BASE + "/g")
ok("未配代理时仍是原直连口径（tcp 或 http）",
   ok_chk2 and (meth2.startswith("tcp:") or meth2.startswith("http:")), (ok_chk2, meth2))

# G2 deep_fetch_text 走代理
P.set_active("http://127.0.0.1:%d" % cp)
txt = C.deep_fetch_text(BASE + "/deep", timeout=5)
ok("deep_fetch_text 经代理取到内容", "hello-from-local" in txt, txt[:60])
P.set_active("")

# G3 _fetch_url_bytes / fetch_text_from_url 走代理
P.set_active("http://127.0.0.1:%d" % cp)
ok("_fetch_url_bytes 经代理取回字节",
   C._fetch_url_bytes(BASE + "/cfg", timeout=5).startswith(b"hello-from-local"))
ok("fetch_text_from_url 经代理取回文本",
   "hello-from-local" in C.fetch_text_from_url(BASE + "/cfg", timeout=5))
P.set_active("")

# G4 网络诊断：经代理 → 正常；走代理时通过 note 表明
P.set_active("http://127.0.0.1:%d" % cp)
d = ND.diagnose_url(BASE + "/d")
ok("diagnose_url 经代理 → 正常", d["level"] == ND.LEVEL_OK and d["via"] == "proxy", d)
ok("经代理时 note 说明走了代理", "代理" in d["note"], d["note"])
d_src = ND.diagnose_source({"key": "k", "name": "n", "api": BASE + "/d", "type": 1}, None)
ok("diagnose_source 汇总 via_proxy=True", d_src["via_proxy"] is True, d_src.get("via_proxy"))
P.set_active("")
d2 = ND.diagnose_url(BASE + "/d")
ok("直连时 via=direct", d2["via"] == "direct", d2.get("via"))

# G5 测速：经代理只走 HTTP，且不再做 TCP 兜底
P.set_active("http://127.0.0.1:%d" % cp)
st = SP.speed_test_url(BASE + "/s", samples=1)
ok("测速经代理 → reachable 且 method=http",
   st["reachable"] and st["method"] == "http", st)
ok("测速经代理不回落 TCP（method 不会是 tcp）", st["method"] != "tcp")
ok("测速经代理取到延迟", isinstance(st["latency_ms"], int), st["latency_ms"])
dead = SP.speed_test_url("http://127.0.0.1:1/", samples=1)
ok("经代理时死地址不靠 TCP 误判为可达", not dead["reachable"], dead)
P.set_active("")
st_direct = SP.speed_test_url(BASE + "/s", samples=1)
ok("直连测速仍可用", st_direct["reachable"], st_direct)

# G6 JAR 体检：经代理
P.set_active("http://127.0.0.1:%d" % cp)
jr = JAR.check_jar_url(BASE + "/jar/app.jar")
ok("jar 体检经代理 → 健康", jr["ok"] and jr["level"] == JAR.JAR_OK, jr)
ok("jar 体检经代理读到内容长度", jr["content_length"] == len(JAR_BYTES), jr["content_length"])
md5_info = JAR.compute_md5(BASE + "/jar/app.jar")
ok("jar 整包 MD5 经代理可算", len(md5_info["md5"]) == 32, md5_info)
P.set_active("")

print("\n== H) 源测活子进程注入代理环境变量 ==")
import subprocess as _sub
captured = {}


class _FakeProc(object):
    stdout = (C.PROBE_MARKER + json.dumps(
        {"ok": True, "alive": True, "classes": ["电影"], "videos": 3,
         "titles": [], "via": "http", "style": "cms", "error": "", "note": ""},
        ensure_ascii=False) + "\n").encode("utf-8")
    stderr = b""
    returncode = 0


def _fake_run(cmd, **kw):
    captured["cmd"] = cmd
    captured["env"] = dict(kw.get("env") or {})
    return _FakeProc()


_real_run = _sub.run
try:
    _sub.run = _fake_run
    py_tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_dummy.py")
    with open(py_tmp, "w", encoding="utf-8") as f:
        f.write("# dummy\n")
    P.set_active("socks5://user:pw@127.0.0.1:1080")
    res = C.probe_py_source(py_tmp, timeout=5)
    env = captured.get("env") or {}
    ok("测活结果解析正常（桩）", res.get("alive") is True, res)
    ok("子进程注入 HTTPS_PROXY", env.get("HTTPS_PROXY") == "socks5://user:pw@127.0.0.1:1080",
       env.get("HTTPS_PROXY"))
    ok("子进程注入 ALL_PROXY/http_proxy（小写同样给到）",
       env.get("ALL_PROXY") == env.get("all_proxy") and env.get("all_proxy"),
       (env.get("ALL_PROXY"), env.get("all_proxy")))
    ok("PYINJ_PROBE_PROXY=1（worker 据此保留 env 不直连）", env.get("PYINJ_PROBE_PROXY") == "1",
       env.get("PYINJ_PROBE_PROXY"))
    ok("PYINJ_PROBE_PROXY_SPEC 传给 worker", env.get("PYINJ_PROBE_PROXY_SPEC")
       == "socks5://user:pw@127.0.0.1:1080", env.get("PYINJ_PROBE_PROXY_SPEC"))
    ok("NO_PROXY 被清掉（否则会强制直连）",
       "NO_PROXY" not in env and "no_proxy" not in env)
    ok("SOCKS5 且环境无 PySocks → 结果带醒目提示（不静默判死源）",
       "PySocks" in (res.get("note") or ""), res.get("note"))
    # http 代理不该出现该提示
    captured.clear()
    P.set_active("http://127.0.0.1:7890")
    res_http = C.probe_py_source(py_tmp, timeout=5)
    ok("HTTP 代理不出现 SOCKS5 提示", "PySocks" not in (res_http.get("note") or ""),
       res_http.get("note"))
    # 未配代理时不应注入
    P.set_active("")
    captured.clear()
    C.probe_py_source(py_tmp, timeout=5)
    env2 = captured.get("env") or {}
    ok("未配代理时 PROXY=0 且不注入 HTTP_PROXY",
       env2.get("PYINJ_PROBE_PROXY") == "0" and not env2.get("HTTP_PROXY"),
       (env2.get("PYINJ_PROBE_PROXY"), env2.get("HTTP_PROXY")))
finally:
    _sub.run = _real_run
    try:
        os.remove(py_tmp)
    except Exception:
        pass
P.set_active("")

print("\n（GUI 用例 _ProxyControls 已拆到 test_proxy_gui.py，以保持本文件零 Qt 依赖）")

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
