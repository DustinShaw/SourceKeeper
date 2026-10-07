# -*- coding: utf-8 -*-
"""源管家 · 网络诊断模块（pyinj_netdiag）
=========================================
识别「源是不是需要特殊上网（代理/科学上网）才能用」，而不是源本身坏了。

判定手段（任一命中即提示，按优先级）：
  1. **域名命中「需特殊上网域名库」** → 直接标记（用户可自行维护该库）；
  2. **DNS 解析失败**（gaierror）→ 域名无法解析，多半需要代理或已失效；
  3. **连接超时**（timeout，非 refuse）→ 直连被阻断的典型特征（被墙多为超时而非拒绝）。

代理口径：配置了自定义代理服务器（pyinj_proxy）后，诊断**经代理**进行
（本机 DNS 不再参与，域名的解析交给代理），错误分类重新映射；此时
「需特殊上网」判定仍以域名库为准。

对外主要接口：
  · diagnose_url(url)       → 单个 URL 的诊断结果 dict
  · diagnose_source(entry)  → 站点条目级诊断（取其 URL 逐个诊断）
零 Qt 依赖、纯逻辑，可单测。
"""

import socket
import time
import urllib.request
import urllib.error

from pyinj_core import (
    extract_urls_from_py, resolve_spider_path, source_type_of, _HTTP_UA,
)
from pyinj_kw import load_proxy_domains, domain_needs_proxy
import pyinj_proxy as _proxy_mod

DNS_TIMEOUT = 3.0
CONNECT_TIMEOUT = 3.0
PROXY_TIMEOUT = 6.0        # 经代理探测的超时（比直连宽松：代理本身有一段处理开销）

# 诊断结论等级
LEVEL_OK = "ok"            # 正常
LEVEL_PROXY = "proxy"      # 疑似需特殊上网
LEVEL_DNS = "dns"          # DNS 解析失败
LEVEL_TIMEOUT = "timeout"  # 连接超时（疑似被阻断）
LEVEL_REFUSED = "refused"  # 连接被拒绝（服务未开）
LEVEL_UNKNOWN = "unknown"  # 其它错误

LEVEL_LABELS = {
    LEVEL_OK: "正常",
    LEVEL_PROXY: "需特殊上网",
    LEVEL_DNS: "DNS 失败",
    LEVEL_TIMEOUT: "连接超时",
    LEVEL_REFUSED: "连接被拒",
    LEVEL_UNKNOWN: "异常",
}


def _host_of(url):
    from urllib.parse import urlparse
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _port_of(url, host=""):
    """取 URL 的实际端口（未写则按 scheme 取 80/443）。
    必须尊重显式端口，否则自建端口/非标端口的源会被误判「连接被拒」。"""
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
        return p.port or (443 if (p.scheme or "").lower() == "https" else 80)
    except Exception:
        return 443 if url.lower().startswith("https") else 80


def resolve_dns(host, timeout=DNS_TIMEOUT):
    """解析域名，返回 (是否成功, IP 或错误说明, 耗时ms)。"""
    if not host:
        return False, "空域名", 0
    old = socket.getdefaulttimeout()
    t0 = time.time()
    try:
        socket.setdefaulttimeout(timeout)
        infos = socket.getaddrinfo(host, None)
        ip = infos[0][4][0] if infos else ""
        return True, ip, int((time.time() - t0) * 1000)
    except socket.gaierror as e:
        return False, "DNS 解析失败：%s" % (e, ), int((time.time() - t0) * 1000)
    except Exception as e:
        return False, "解析异常：%s" % (str(e)[:60],), int((time.time() - t0) * 1000)
    finally:
        socket.setdefaulttimeout(old)


def _tcp_probe(host, port, timeout=CONNECT_TIMEOUT):
    """TCP 连接探测，返回 (结果等级, 说明, 耗时ms)。
    区分 timeout（被阻断）与 refused（服务没开）——这是判断「是否需要代理」的关键。"""
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return LEVEL_OK, "已连接", int((time.time() - t0) * 1000)
    except socket.timeout:
        return LEVEL_TIMEOUT, "连接超时（疑似被阻断 / 需代理）", int((time.time() - t0) * 1000)
    except ConnectionRefusedError:
        return LEVEL_REFUSED, "连接被拒绝（服务未开启）", int((time.time() - t0) * 1000)
    except OSError as e:
        msg = str(e).lower()
        if "timed out" in msg:
            return LEVEL_TIMEOUT, "连接超时（疑似被阻断 / 需代理）", int((time.time() - t0) * 1000)
        if "refused" in msg:
            return LEVEL_REFUSED, "连接被拒绝（服务未开启）", int((time.time() - t0) * 1000)
        return LEVEL_UNKNOWN, "网络错误：%s" % (str(e)[:60],), int((time.time() - t0) * 1000)
    except Exception as e:
        return LEVEL_UNKNOWN, "网络错误：%s" % (str(e)[:60],), int((time.time() - t0) * 1000)


def _classify_proxied(r, in_lib):
    """把「经代理的一次请求结果」映射成 (level, note)。"""
    status = r.get("status")
    err = str(r.get("err") or "")
    if r.get("ok"):
        return LEVEL_OK, "经代理访问成功（HTTP %s）" % status
    if status is not None and status >= 400:
        return LEVEL_UNKNOWN, "经代理返回 HTTP %s（连通但非 2xx/3xx）" % status
    low = err.lower()
    if "超时" in err or "timed out" in low:
        return LEVEL_TIMEOUT, "经代理连接超时（代理未启动 / 被阻断 / 目标不可达）"
    if "拒绝" in err or "refused" in low:
        return LEVEL_REFUSED, "经代理连接被拒绝（%s）" % err[:60]
    if "connect 被拒" in err or "CONNECT" in err:
        return LEVEL_UNKNOWN, "代理拒绝为 %s 建立隧道（%s）" % ("该目标", err[:60])
    if not err:
        return LEVEL_UNKNOWN, "经代理探测无响应"
    return LEVEL_UNKNOWN, "经代理异常：%s" % err[:80]


def diagnose_url(url, proxy_domains=None, proxy=None):
    """诊断单个 URL：域名库命中 / DNS / TCP 超时 vs 拒绝。
    配置了自定义代理时**经代理**探测（本机 DNS 不参与）。
    返回 dict：{url, host, level, label, note, dns_ok, ip, latency_ms,
               needs_proxy, via}。"""
    host = _host_of(url)
    res = {"url": url, "host": host, "level": LEVEL_UNKNOWN, "label": LEVEL_LABELS[LEVEL_UNKNOWN],
           "note": "", "dns_ok": None, "ip": "", "latency_ms": None,
           "needs_proxy": False, "via": "direct"}
    if not host:
        res["note"] = "无法解析出域名"
        return res

    in_lib = domain_needs_proxy(host, proxy_domains)
    res["needs_proxy"] = in_lib

    px = _proxy_mod.resolve(proxy)
    if px:
        # ---- 经代理探测：DNS 交给代理，故不判本机 DNS ----
        res["via"] = "proxy"
        r = _proxy_mod.request_via(px, url, "GET", timeout=PROXY_TIMEOUT, max_bytes=1024)
        res["latency_ms"] = r.get("latency_ms")
        level, note = _classify_proxied(r, in_lib)
        if in_lib and level != LEVEL_OK:
            # 域名库命中优先：无论代理这次结果如何，都提示「需特殊上网」
            res["level"] = LEVEL_PROXY
            res["label"] = LEVEL_LABELS[LEVEL_PROXY]
            res["note"] = "域名在「需特殊上网域名库」中（经代理：%s）" % note
            return res
        res["level"] = level
        res["label"] = LEVEL_LABELS.get(level, LEVEL_LABELS[LEVEL_UNKNOWN])
        res["note"] = note
        return res

    port = _port_of(url, host)
    dns_ok, ip_or_err, dns_ms = resolve_dns(host)
    res["dns_ok"] = dns_ok
    if dns_ok:
        res["ip"] = ip_or_err
    else:
        # DNS 都拿不到 → 若在代理库里，就是「需特殊上网」；否则算 DNS 失败
        if in_lib:
            res["level"] = LEVEL_PROXY
            res["label"] = LEVEL_LABELS[LEVEL_PROXY]
            res["note"] = "域名在「需特殊上网域名库」中，且 DNS 解析失败"
        else:
            res["level"] = LEVEL_DNS
            res["label"] = LEVEL_LABELS[LEVEL_DNS]
            res["note"] = ip_or_err
        res["latency_ms"] = dns_ms
        return res

    level, note, ms = _tcp_probe(host, port)
    res["latency_ms"] = ms
    if in_lib:
        # 在代理库里：无论通不通，都提示「需特殊上网」（直连时通时不通）
        res["level"] = LEVEL_PROXY
        res["label"] = LEVEL_LABELS[LEVEL_PROXY]
        res["note"] = "域名在「需特殊上网域名库」中（%s）" % note
        return res
    if level == LEVEL_TIMEOUT:
        res["level"] = LEVEL_PROXY                 # 超时=阻断特征 → 也归为需代理
        res["label"] = LEVEL_LABELS[LEVEL_PROXY]
        res["note"] = note + "（直连被阻断的特征，源本身可能正常）"
        return res
    res["level"] = level
    res["label"] = LEVEL_LABELS.get(level, LEVEL_LABELS[LEVEL_UNKNOWN])
    res["note"] = note
    return res


def diagnose_source(entry, base_dir=None, max_urls=2, proxy_domains=None, proxy=None):
    """站点条目级诊断：取其 URL 逐个诊断，汇总。
    返回 dict：{urls, results, level, label, note, needs_proxy, via_proxy}。"""
    api = str(entry.get("api") or "")
    t = source_type_of(entry)
    urls = []
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
        return {"urls": [], "results": [], "level": LEVEL_UNKNOWN,
                "label": "无 URL", "note": "未从源中提取到 URL",
                "needs_proxy": False, "via_proxy": False}
    results = [diagnose_url(u, proxy_domains, proxy=proxy) for u in urls]
    # 汇总优先级：proxy > dns > timeout > refused > unknown > ok
    prio = {LEVEL_PROXY: 0, LEVEL_DNS: 1, LEVEL_TIMEOUT: 2,
            LEVEL_REFUSED: 3, LEVEL_UNKNOWN: 4, LEVEL_OK: 5}
    worst = min(results, key=lambda r: prio.get(r["level"], 9))
    return {"urls": urls, "results": results,
            "level": worst["level"], "label": worst["label"],
            "note": worst["note"],
            "needs_proxy": any(r["needs_proxy"] for r in results),
            "via_proxy": bool(_proxy_mod.resolve(proxy))}
