# -*- coding: utf-8 -*-
"""源管家 · 源测速模块（pyinj_speed）
=====================================
以「新增模块」方式给现有可达性检测**加装**：
  1. 延迟测量（多次采样取统计量，而非只判 bool）；
  2. 前 N 字节真实下载判活（HTTP 拿到 2xx 后读一点 body，确认真能出数据，
     而不是「端口通但内容是错误页 / 空响应」）；
  3. 加权均值防误杀（多次采样里个别超时不应直接判死；用截尾加权均值 +
     「至少一次成功」的宽松门槛）。

复用 pyinj_core 的底层原语（TCP/HTTP 探测、URL 提取），不重写它们。
零 Qt 依赖，纯逻辑（仅做网络 IO），可单独在 __main__ 里对着 URL 跑。
"""

import socket
import ssl
import time
import urllib.request
import urllib.error

from pyinj_core import (
    extract_urls_from_py, resolve_spider_path, source_type_of, _HTTP_UA,
)
import pyinj_proxy as _proxy_mod

# ---- 超时预算（秒）----
TCP_TIMEOUT = 2.5
HTTP_TIMEOUT = 4.0
READ_BYTES = 1024          # 前 N 字节：读到这么多就认为「真有数据」
SAMPLES_DEFAULT = 3        # 每个 URL 的采样次数


def _parse_host_port(url):
    from urllib.parse import urlparse
    p = urlparse(url)
    host = p.hostname
    if not host:
        return None, None
    port = p.port or (443 if p.scheme.lower() == "https" else 80)
    return host, port


def measure_tcp_latency(url, timeout=TCP_TIMEOUT, proxy=None):
    """TCP 连接一次并返回耗时（毫秒）。失败返回 None。

    ⚠️ 纯直连指标：配置了自定义代理时**直接返回 None**（TCP 绕不过 HTTP 代理，
    测出来的直连延迟与「经代理的真实体验」无关，留着会给出误导性数值）。"""
    if _proxy_mod.resolve(proxy):
        return None
    host, port = _parse_host_port(url)
    if not host:
        return None
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return int((time.time() - t0) * 1000)
    except Exception:
        return None


def measure_http_latency(url, timeout=HTTP_TIMEOUT, read_bytes=READ_BYTES, proxy=None):
    """HTTP GET 到「第一个响应字节」的耗时（毫秒）+ 状态码 + 实际读数。
    返回 (latency_ms 或 None, status 或 None, nbytes, err)。
    配置了自定义代理时经代理请求（http/https/socks5 均可）。"""
    px = _proxy_mod.resolve(proxy)
    if px:
        r = _proxy_mod.request_via(
            px, url, "GET", timeout=timeout, max_bytes=read_bytes,
            headers={"Range": "bytes=0-%d" % (read_bytes - 1)})
        ms = r.get("latency_ms")
        status = r.get("status")
        n = len(r.get("body") or b"")
        if r.get("ok"):
            return ms, status, n, ""
        return None, status, n, (r.get("err") or ("http:%s" % status))
    req = urllib.request.Request(
        url, method="GET",
        headers={"User-Agent": _HTTP_UA, "Accept": "*/*",
                 "Range": "bytes=0-%d" % (read_bytes - 1)})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            status = getattr(resp, "status", None) or 200
            try:
                head = resp.read(read_bytes)
            except Exception:
                head = b""
            ms = int((time.time() - t0) * 1000)
            if 200 <= status < 400:
                return ms, status, len(head or b""), ""
            return None, status, len(head or b""), "http:%d" % status
    except urllib.error.HTTPError as e:
        return None, e.code, 0, "http:%d" % e.code
    except Exception as ex:
        return None, None, 0, str(ex)[:80]


def _weighted_mean(samples):
    """截尾加权均值：丢掉最慢的一个（若有 ≥3 个），其余取平均；
    若全失败返回 None。这样单次抖动/超时不会把活源误杀成死源。"""
    good = [s for s in samples if s is not None]
    if not good:
        return None
    if len(good) >= 3:
        good = sorted(good)[:-1]        # 丢掉最慢一个
    return int(sum(good) / len(good))


def speed_test_url(url, samples=SAMPLES_DEFAULT, read_bytes=READ_BYTES,
                   tcp_timeout=TCP_TIMEOUT, http_timeout=HTTP_TIMEOUT, proxy=None):
    """对单个 URL 做「延迟采样 + 前 N 字节真实下载」测速。
    返回 dict：
        url, reachable(bool), latency_ms(int|None), status, bytes,
        ok_count, samples, method, err, quality(优/良/中/差/不可达)
    判定口径（防误杀）：
        · 任一次 HTTP 成功读到响应（2xx/3xx）→ reachable=True；
        · 否则任一 TCP 成功 → reachable=True（但 quality 记「中」，提示仅有端口）；
        · 全失败 → reachable=False。
    配置了自定义代理时只走 HTTP（经代理），不再做 TCP 直连兜底。"""
    res = {"url": url, "reachable": False, "latency_ms": None, "status": None,
           "bytes": 0, "ok_count": 0, "samples": samples, "method": "",
           "err": "", "quality": "不可达"}
    px = _proxy_mod.resolve(proxy)
    http_samples, tcp_samples = [], []
    last_status, last_bytes, last_err = None, 0, ""
    for _ in range(max(1, samples)):
        ms, status, nbytes, err = measure_http_latency(url, http_timeout, read_bytes,
                                                      proxy=proxy)
        last_status, last_bytes, last_err = status, nbytes, err
        if ms is not None:
            http_samples.append(ms)
            res["ok_count"] += 1
        elif not px:
            tcp_samples.append(measure_tcp_latency(url, tcp_timeout, proxy=proxy))

    res["status"] = last_status
    res["bytes"] = last_bytes
    if http_samples:
        res["reachable"] = True
        res["latency_ms"] = _weighted_mean(http_samples)
        res["method"] = "http"
        res["quality"] = _quality_from_latency(res["latency_ms"], last_bytes)
    elif any(t is not None for t in tcp_samples):
        res["reachable"] = True
        res["latency_ms"] = _weighted_mean(tcp_samples)
        res["method"] = "tcp"
        res["err"] = last_err or "仅端口可达（未取到 HTTP 响应）"
        res["quality"] = "中"
    else:
        res["err"] = last_err or "不可达"
    return res


def _quality_from_latency(ms, nbytes):
    if ms is None:
        return "差"
    if nbytes <= 0:
        return "中"                     # 通了但没读到 body，存疑
    if ms < 300:
        return "优"
    if ms < 800:
        return "良"
    if ms < 2000:
        return "中"
    return "差"


def speed_test_source(entry, base_dir=None, max_urls=2, samples=SAMPLES_DEFAULT,
                      proxy=None):
    """对一个站点条目测速：从其 .py（Spider）或 api（直连）取出 URL 逐个测。
    返回 dict：{urls:[url...], results:[{...}], best:{...}|None,
               reachable(bool|None), note}。"""
    api = str(entry.get("api") or "")
    t = source_type_of(entry)
    urls = []
    if t == 1 or api.startswith("http"):
        if api.startswith("http"):
            urls = [api]
    if not urls and base_dir:
        try:
            p = resolve_spider_path(base_dir, api)
            if p:
                urls = extract_urls_from_py(p)[:max_urls]
        except Exception:
            urls = []
    if not urls:
        return {"urls": [], "results": [], "best": None, "reachable": None,
                "note": "未从源中提取到可测 URL"}
    results = [speed_test_url(u, samples=samples, proxy=proxy) for u in urls]
    ok = [r for r in results if r["reachable"]]
    best = None
    if ok:
        best = min(ok, key=lambda r: (r["latency_ms"] if r["latency_ms"] is not None else 10 ** 9))
    return {"urls": urls, "results": results, "best": best,
            "reachable": bool(ok) if results else None,
            "note": "" if ok else "全部 URL 不可达"}


if __name__ == "__main__":       # 手动试跑：python pyinj_speed.py <url> [samples]
    import sys
    if len(sys.argv) > 1:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else SAMPLES_DEFAULT
        print(speed_test_url(sys.argv[1], samples=n))
