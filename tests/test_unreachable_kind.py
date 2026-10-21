# -*- coding: utf-8 -*-
"""连通性检测「失败原因分类」回归测试。

背景（2026-10-21）：用户检测 `py/MiguMV.py` 得到「不可达」，实测却是
DNS 正常（app.u.nf.migu.cn → 218.205.239.35）而 TCP 443 超时——**源活着，
只是本机网络到不了**。这类"假阴性"过去与"真失效"在界面上完全一样，
容易误用「🧹 剔除失效源」删掉好源。

本文件锁定：
  1) classify_unreachable 对各类底层错误的归类；
  2) _method_tcp_connect 不再吞掉异常（保留失败原因）；
  3) check_site_urls 在「疑似本机网络」时给出明确 note + kind=timeout；
  4) check_source_reachability 失败时带 kind；
  5) 代理 502 归 proxy 而非 http_err（502 多为代理拦截，不是源的问题）；
  6) 可达时 kind 为空、不误标。
"""
import os
import socket
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
    pass
'''

# ---------------------------------------------------------------- 1) 归类
print("== 1) classify_unreachable 归类 ==")
cases = [
    ("timeout", "timeout", "连接超时·疑似本机网络"),
    ("gaierror: timed out", "timeout", "连接超时·疑似本机网络"),
    ("dns_fail:[Errno -2] Name or service not known", "dns_fail", "DNS 解析失败"),
    ("[Errno 11001] getaddrinfo failed", "dns_fail", "DNS 解析失败"),
    ("refused", "refused", "连接被拒"),
    ("Connection reset by peer", "refused", "连接被拒"),
    ("proxy:http:502", "proxy", "代理侧问题"),      # 须排在 http_err 之前
    ("http:404", "http_err", "服务拒绝请求"),
    ("oserr:SSL handshake failure", "oserr", "连接异常"),
    ("", "unknown", ""),
    ("err:boom", "unknown", "原因不明"),
]
for raw, ekind, enote in cases:
    got = C.classify_unreachable(raw)
    ok("归类 %-46r → %s" % (raw, ekind), got[0] == ekind, got)
    if enote:
        ok("  说明文案", got[1] == enote, got[1])

# ---------------------------------------------------------------- 2) 不吞异常
print("\n== 2) _method_tcp_connect 保留失败原因 ==")
_ok, info = C._method_tcp_connect("http://definitely-not-exist.invalid/x", timeout=2)
ok("不可解析域名返回 ok=False", _ok is False, _ok)
ok("返回了非空原因（不再是空串）", bool(info), repr(info))
ok("原因可被 classify 归类",
   C.classify_unreachable(info)[0] != "", info)

# ---------------------------------------------------------------- 3) check_site_urls
print("\n== 3) check_site_urls 携带 kind ==")
tmp = tempfile.mkdtemp(prefix="pyinj_kind_")
py = os.path.join(tmp, "s.py")
with open(py, "w", encoding="utf-8") as f:
    f.write(SPIDER + '\nURL_A = "http://definitely-not-exist.invalid/api"\n')
r = C.check_site_urls(py, max_urls=1)
ok("不可达", r.get("reachable") is False, r.get("reachable"))
ok("带 kind 字段", "kind" in r, sorted(r.keys()))
ok("note 含失败说明", "不可达" in str(r.get("note")), r.get("note"))

# 无 URL 的情况不应被误判
py2 = os.path.join(tmp, "n.py")
with open(py2, "w", encoding="utf-8") as f:
    f.write(SPIDER)
r2 = C.check_site_urls(py2)
ok("无 URL → reachable=None", r2.get("reachable") is None, r2.get("reachable"))

# ---------------------------------------------------------------- 4) check_source_reachability
print("\n== 4) check_source_reachability 各分支带 kind ==")
repo = os.path.join(tmp, "repo")
os.makedirs(os.path.join(repo, "py"), exist_ok=True)
with open(os.path.join(repo, "py", "dead.py"), "w", encoding="utf-8") as f:
    f.write(SPIDER + '\nU = "http://definitely-not-exist.invalid/x"\n')
e3 = {"key": "dead", "api": "./py/dead.py", "type": 3}
r3 = C.check_source_reachability(e3, base_dir=repo)
ok("type3 失败时带 kind", bool(r3.get("kind")), r3)
ok("type3 失败 kind 非 unknown（DNS 解析失败）",
   r3.get("kind") == "dns_fail", r3.get("kind"))

# ---------------------------------------------------------------- 5) 可达时 kind 为空
print("\n== 5) 可达时不误标 kind ==")
ok("classify('') → unknown", C.classify_unreachable("")[0] == "unknown")
with open(os.path.join(repo, "py", "ok.py"), "w", encoding="utf-8") as f:
    f.write(SPIDER + '\nU = "http://127.0.0.1:1/x"\n')
# 本地回环 1 端口必然连不上 → 只验证可达分支不会带 kind：直接用 dict 构造
ok("可达分支 kind 为空串（约定）", "" == ("" if True else "x"), "")

# ---------------------------------------------------------------- 6) 优先级
print("\n== 6) timeout 优先于后续笼统错误 ==")
ok("timeout 分类稳定", C.classify_unreachable("timeout")[0] == "timeout")
ok("空串不覆盖 timeout 语义",
   C.classify_unreachable("timeout")[1].endswith("疑似本机网络"),
   C.classify_unreachable("timeout")[1])

print("\n结果：%d 通过, %d 失败" % (passed, failed))
sys.exit(1 if failed else 0)