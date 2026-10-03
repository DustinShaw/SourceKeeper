# -*- coding: utf-8 -*-
"""pyinj_jar / pyinj_playlist / pyinj_report 的单元测试。
用本地 ThreadingHTTPServer 提供 jar 与频道表，不依赖外网。"""
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pyinj_jar import (jar_url_of, is_jar_entry, iter_jar_entries,
                       check_jar_url, check_jar_source, check_jar_sites,
                       compute_md5, verify_md5,
                       JAR_OK, JAR_SMALL, JAR_HTTP_ERR, JAR_UNREACHABLE,
                       MD5_OK, MD5_MISMATCH, MD5_SKIP)
from pyinj_playlist import (parse_txt, parse_m3u, to_txt, to_m3u,
                            convert, is_m3u, is_txt, convert_file)
from pyinj_report import (analyze_one, build_report, render_markdown,
                          render_csv, export_report)

PASS = []
FAIL = []


def ok(name):
    PASS.append(name)
    print("  ok  - %s" % name)


def bad(name, msg):
    FAIL.append((name, msg))
    print("  FAIL- %s :: %s" % (name, msg))


def eq(name, a, b):
    if a == b:
        ok(name)
    else:
        bad(name, "%r != %r" % (a, b))


# ---------------------------------------------------------------------------
# 本地服务器：/ok.jar → 200 + 64KB 内容；/tiny.jar → 200 + 10 字节；
#            /404.jar → 404；/list.m3u → m3u 文本
# ---------------------------------------------------------------------------
class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/ok.jar":
            body = b"PK\x03\x04" + b"J" * (64 * 1024)
            self.send_response(200)
            self.send_header("Content-Type", "application/java-archive")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == "/tiny.jar":
            body = b"<html>404</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == "/404.jar":
            self.send_response(404)
            self.end_headers()
        elif p == "/list.m3u":
            body = ('#EXTM3U\n#EXTINF:-1 tvg-name="CCTV1" group-title="央视",CCTV1\n'
                    'http://a/1.m3u8\n#EXTINF:-1 tvg-name="湖南卫视" group-title="卫视",湖南卫视\n'
                    'http://a/2.m3u8\n').encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "audio/x-mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


# ---------------------------------------------------------------------------
def test_jar():
    print("[pyinj_jar]")
    # jar_url_of
    eq("jar_url_of jar field", jar_url_of({"jar": "http://x/a.jar"}), "http://x/a.jar")
    eq("jar_url_of api .jar", jar_url_of({"api": "http://x/a.jar"}), "http://x/a.jar")
    eq("jar_url_of none", jar_url_of({"api": "csp_Xxx"}), "")
    eq("jar_url_of dict key api http non-jar",
       jar_url_of({"api": "http://x/api.php/provide/vod"}), "")
    eq("is_jar_entry true", is_jar_entry({"jar": "http://x/a.jar"}), True)
    eq("is_jar_entry false", is_jar_entry({"api": "csp_Xxx"}), False)
    eq("iter_jar_entries", len(iter_jar_entries([
        {"jar": "http://x/a.jar"}, {"api": "csp_Y"}, {"jar": "http://y/b.jar"}])), 2)

    srv, port = start_server()
    base = "http://127.0.0.1:%d" % port
    try:
        r = check_jar_url(base + "/ok.jar")
        eq("check_jar_url ok level", r["level"], JAR_OK)
        eq("check_jar_url ok flag", r["ok"], True)

        r2 = check_jar_url(base + "/tiny.jar")
        eq("check_jar_url small level", r2["level"], JAR_SMALL)

        r3 = check_jar_url(base + "/404.jar")
        eq("check_jar_url http err", r3["level"], JAR_HTTP_ERR)

        r4 = check_jar_url("http://127.0.0.1:1/none.jar", timeout=1.0)
        eq("check_jar_url unreachable", r4["level"], JAR_UNREACHABLE)

        r5 = check_jar_url("")
        eq("check_jar_url no url", r5["level"], "no_url")

        r6 = check_jar_source({"name": "X", "key": "csp_X", "jar": base + "/ok.jar"})
        eq("check_jar_source name", r6["name"], "X")
        eq("check_jar_source ok", r6["level"], JAR_OK)

        summary = check_jar_sites([
            {"name": "A", "jar": base + "/ok.jar"},
            {"name": "B", "jar": base + "/404.jar"},
            {"name": "C", "api": "csp_C"},          # 非 jar 源，应被忽略
        ])
        eq("check_jar_sites total", summary["total"], 2)
        eq("check_jar_sites ok", summary["ok"], 1)
        eq("check_jar_sites bad", summary["bad"], 1)

        # ---- MD5 校验（新增）----
        import hashlib as _hl
        ok_body = b"PK\x03\x04" + b"J" * (64 * 1024)
        real_md5 = _hl.md5(ok_body).hexdigest()

        c = compute_md5(base + "/ok.jar")
        eq("compute_md5 md5", c["md5"], real_md5)
        eq("compute_md5 bytes", c["bytes"], len(ok_body))

        v1 = verify_md5(base + "/ok.jar", real_md5)
        eq("verify_md5 一致", v1["level"], MD5_OK)
        v2 = verify_md5(base + "/ok.jar", "deadbeef" * 4)
        eq("verify_md5 不一致", v2["level"], MD5_MISMATCH)
        v3 = verify_md5(base + "/ok.jar", "")
        eq("verify_md5 空期望→skip", v3["level"], MD5_SKIP)
        v4 = verify_md5("http://127.0.0.1:1/x.jar", real_md5, timeout=1.0)
        eq("verify_md5 不可达→skip", v4["level"], MD5_SKIP)

        # check_jar_url 带 expect_md5：一致 → ok；不一致 → ok=False 且 note 提示
        r7 = check_jar_url(base + "/ok.jar", expect_md5=real_md5)
        eq("check_jar_url w/ md5 ok", r7["ok"], True)
        eq("check_jar_url w/ md5 md5_info", r7["md5_info"]["level"], MD5_OK)
        r8 = check_jar_url(base + "/ok.jar", expect_md5="deadbeef" * 4)
        eq("check_jar_url w/ bad md5 ok=False", r8["ok"], False)
        eq("check_jar_url w/ bad md5 md5_info", r8["md5_info"]["level"], MD5_MISMATCH)
        r9 = check_jar_url(base + "/ok.jar")   # 不带期望值：不做 MD5
        eq("check_jar_url no md5 param", r9["md5_info"], None)
    finally:
        srv.shutdown()


def test_playlist():
    print("[pyinj_playlist]")
    txt = ("央视,#genre#\n"
           "CCTV1,http://a/1.m3u8\n"
           "CCTV2,http://a/2.m3u8\n"
           "卫视,#genre#\n"
           "湖南卫视,http://a/3.m3u8\n")
    items = parse_txt(txt)
    eq("parse_txt count", len(items), 3)
    eq("parse_txt group1", items[0]["group"], "央视")
    eq("parse_txt group2", items[2]["group"], "卫视")
    eq("parse_txt name", items[0]["name"], "CCTV1")
    eq("parse_txt url", items[0]["url"], "http://a/1.m3u8")

    m3u = to_m3u(items)
    eq("to_m3u header", m3u.splitlines()[0], "#EXTM3U")
    eq("is_m3u", is_m3u(m3u), True)
    eq("is_txt on m3u", is_txt(m3u), False)

    items2 = parse_m3u(m3u)
    eq("parse_m3u count", len(items2), 3)
    eq("parse_m3u group", items2[0]["group"], "央视")
    eq("parse_m3u name", items2[1]["name"], "CCTV2")

    # 往返：TXT→items→M3U→items→TXT 应稳定
    back = to_txt(items2)
    eq("roundtrip group marker", "#genre#" in back, True)
    items3 = parse_txt(back)
    eq("roundtrip count", len(items3), 3)
    eq("roundtrip name", items3[2]["name"], "湖南卫视")

    # convert 自动识别
    out, n, src = convert(txt, "m3u")
    eq("convert txt->m3u src", src, "txt")
    eq("convert txt->m3u n", n, 3)
    eq("convert txt->m3u is_m3u", is_m3u(out), True)

    # 无分组 TXT
    plain = "CCTV1,http://a/1.m3u8\n"
    items4 = parse_txt(plain)
    eq("parse_txt no group", items4[0]["group"], "未分组")


def test_playlist_file():
    print("[pyinj_playlist file]")
    d = os.path.join(HERE, "_tmp_pl")
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, "a.m3u")
    try:
        with open(src, "w", encoding="utf-8") as f:
            f.write('#EXTM3U\n#EXTINF:-1 tvg-name="CCTV1" group-title="央",CCTV1\n'
                    'http://a/1.m3u8\n')
        r = convert_file(src, to_fmt="txt")
        eq("convert_file src_fmt", r["src_fmt"], "m3u")
        eq("convert_file fmt", r["fmt"], "txt")
        eq("convert_file exists", os.path.isfile(r["dst"]), True)
        with open(r["dst"], "r", encoding="utf-8") as f:
            content = f.read()
        eq("convert_file content group", "央,#genre#" in content, True)
        os.remove(r["dst"])
    finally:
        try:
            os.remove(src)
        except Exception:
            pass


def test_report():
    print("[pyinj_report]")
    sites = [
        {"key": "csp_A", "name": "Jar源A", "api": "csp_A", "type": 3,
         "jar": "http://127.0.0.1:1/a.jar"},
        {"key": "k_b", "name": "直连B", "api": "http://127.0.0.1:1/api.php/provide/vod",
         "type": 1},
    ]
    rep = build_report(sites, base_dir=None, repo_name="test",
                       do_speed=False, do_diag=False, do_jar=False)
    eq("report total", rep["total"], 2)
    eq("report has title", bool(rep["title"]), True)
    md = render_markdown(rep)
    eq("markdown has overview", "## 概览" in md, True)
    eq("markdown has detail", "## 明细" in md, True)
    eq("markdown has name", "直连B" in md, True)
    csv_text = render_csv(rep)
    eq("csv has header", "站点" in csv_text, True)
    eq("csv has name", "直连B" in csv_text, True)

    # 带 JAR 体检（不可达）
    rep2 = build_report(sites, base_dir=None, do_speed=False, do_diag=False, do_jar=True)
    jrec = [r for r in rep2["records"] if r["jar"]][0]
    eq("report jar recorded", jrec["jar"]["level"] in ("unreachable", "http"), True)
    eq("report summary jar_total", rep2["summary"]["jar_total"], 1)

    # 导出
    d = os.path.join(HERE, "_tmp_rep")
    os.makedirs(d, exist_ok=True)
    try:
        p_md = os.path.join(d, "r.md")
        p_csv = os.path.join(d, "r.csv")
        export_report(p_md, rep)
        export_report(p_csv, rep)
        eq("export md exists", os.path.isfile(p_md), True)
        eq("export csv exists", os.path.isfile(p_csv), True)
        with open(p_csv, "rb") as f:
            head = f.read(3)
        eq("csv bom", head, b"\xef\xbb\xbf")
        os.remove(p_md)
        os.remove(p_csv)
    finally:
        try:
            os.rmdir(d)
        except Exception:
            pass


def main():
    test_jar()
    test_playlist()
    test_playlist_file()
    test_report()
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
