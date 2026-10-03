# -*- coding: utf-8 -*-
"""测速 / 网络诊断 / 词库模块自检（纯逻辑；网络部分用本地 http server，离线可跑）。"""
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyinj_kw as KW
import pyinj_speed as SP
import pyinj_netdiag as ND

PASS = FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


# ---------------- 本地测试服务器 ----------------
class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/empty"):
            body = b""
        else:
            body = (b"<html><body>" + b"x" * 4096 + b"</body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
_port = _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % _port

print("== A) 词库加载 ==")
kws = KW.load_keywords()
ok("6 个分类齐全", all(c in kws for c in ("adult", "duanju", "live", "music", "audio", "vod")), list(kws))
ok("adult 中文非空", len(kws["adult"]["zh"]) > 10)
ok("live 英文含 iptv", "iptv" in kws["live"]["en"])
hits = KW.detect_categories("这是短剧直播站点", "测试站")
ok("命中短剧", "duanju" in hits, hits)
ok("命中直播", "live" in hits, hits)
ok("不误报成人", "adult" not in hits, hits)
hits2 = KW.detect_categories("", "音乐台MV")
ok("按站点名命中音乐", "music" in hits2, hits2)
pdoms = KW.load_proxy_domains()
ok("代理域名库非空", len(pdoms) > 5, len(pdoms))
ok("google.com 命中", KW.domain_needs_proxy("google.com", pdoms) is True)
ok("子域 www.google.com 命中", KW.domain_needs_proxy("www.google.com", pdoms) is True)
ok("apis.google.com 命中", KW.domain_needs_proxy("apis.google.com", pdoms) is True)
ok("baidu.com 不命中", KW.domain_needs_proxy("baidu.com", pdoms) is False)
ok("evil-google.com 不命中（防后缀误伤）", KW.domain_needs_proxy("evil-google.com", pdoms) is False)

print("== B) 测速（本地服务器）==")
r = SP.speed_test_url(BASE + "/", samples=2)
ok("可达", r["reachable"] is True, r)
ok("拿到 2xx", r["status"] == 200, r)
ok("读到前 N 字节 > 0", r["bytes"] > 0, r)
ok("有延迟值", isinstance(r["latency_ms"], int), r)
ok("质量为优/良/中/差 之一", r["quality"] in ("优", "良", "中", "差"), r)
r_bad = SP.speed_test_url("http://127.0.0.1:1", samples=2)
ok("死端口不可达", r_bad["reachable"] is False, r_bad)
ok("死端口质量为不可达", r_bad["quality"] == "不可达", r_bad)
ok("加权均值：单次成功即可", SP._weighted_mean([100, None, None]) == 100)
ok("加权均值：全失败为 None", SP._weighted_mean([None, None]) is None)
ok("加权均值：截尾丢最慢", SP._weighted_mean([100, 120, 5000]) == 110, SP._weighted_mean([100, 120, 5000]))

print("== C) 网络诊断 ==")
d = ND.diagnose_url(BASE + "/")
ok("本地可达 → ok", d["level"] == "ok", d)
ok("DNS 成功", d["dns_ok"] is True, d)
d2 = ND.diagnose_url("http://google.com/")
ok("命中代理库 → proxy", d2["level"] == "proxy", d2)
ok("proxy 标记", d2["needs_proxy"] is True, d2)
d3 = ND.diagnose_url("http://127.0.0.1:1/")
ok("拒绝端口 → refused/ok 之一（本地快拒）", d3["level"] in ("refused", "ok"), d3)
ok("DNS 不存在的域名", ND.resolve_dns("nonexistent.invalid")[0] is False)

print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
try:
    _srv.shutdown()
except Exception:
    pass
sys.exit(1 if FAIL else 0)
