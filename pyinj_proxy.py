# -*- coding: utf-8 -*-
"""源管家 · 自定义代理服务器模块（pyinj_proxy）
=====================================================================
给「联网检测」加装一个**可配置的自定义代理服务器**，并让工具内**全部网络请求**
统一走它：URL 可达性 / 网络体检 / 网络诊断 / 源测速 / JAR 体检 / 深度检测 /
远程配置抓取 / 源测活（连子进程里 py 源自己的 requests/urllib 一起）。

核心能力
--------
1. **解析** —— `parse_proxy()` 兼容以下写法，均可带 `user:pass@`：
       host:port · http://host:port · https://host:port
       socks5://host:port · socks5h://host:port
2. **验证** —— `check_proxy()` 判定口径按用户要求：**以能否连到 Google 首页为准**
   （`https://www.google.com/` 返回 2xx/3xx 即算连通，失败自动试 generate_204）。
   同时给一次「不经代理的直连」对照，用来区分两种"看起来正常"：
       · 直连不通 + 代理通 → 代理确实在起作用（`applied=True`）
       · 直连也通         → 代理可用，但它是否被真正使用需自行判断
3. **零依赖支持四种代理** —— http/https 走 CONNECT 隧道；socks5/socks5h 走**内置**
   握手实现（无认证 + 用户名密码认证），不需要 PySocks（两个构建环境都没装它）。
4. **全局单例 + 两处 UI 同步** —— `set_active()` / `get_active()`；网络原语未显式
   传 proxy 时自动取当前代理，传 `proxy=""` 可强制直连。`subscribe(cb)` 让
   「主窗口检测面板」与「工具箱→网络诊断页」共用同一份设置并互相同步。
   语义刻意可预测：**输入框留空 = 直连**；系统里的 `HTTP_PROXY/HTTPS_PROXY`
   环境变量不会自动生效，只由 `env_proxy_raw()` 读取后作为界面提示
   （CLI 可用 `--proxy` 显式启用）。

零 Qt 依赖、纯逻辑（只做网络 IO），可单测。
"""

import base64
import os
import socket
import ssl
import struct
import threading
import time
import urllib.parse

# 探测 UA：纯 ASCII，避免被站点按语言/编码误判
_UA = "SourceKeeper/1.0 (YuanGuanJia)"

SCHEMES = ("http", "https", "socks5", "socks5h")
# 显式写了协议但没写端口时，按**协议标准端口**兜底（与浏览器/curl 一致）；
# 只写 host（无协议无端口）不臆测，直接判无效让用户补全。
_DEFAULT_PORT = {"http": 80, "https": 443, "socks5": 1080, "socks5h": 1080}

# 「服务器是否正常」的判定基准（用户指定：以能否连到 Google 首页为准）
CHECK_URL = "https://www.google.com/"
CHECK_FALLBACK_URL = "https://www.google.com/generate_204"
CHECK_TIMEOUT = 10.0

MAX_BYTES = 200 * 1024          # 检测用默认只读前 200KB（够判定，且不拖慢）
HARD_MAX_BYTES = 16 * 1024 * 1024   # read_all 模式的硬上限，防被超大响应拖死

_LOCK = threading.RLock()
_active = {"raw": "", "parsed": None}
_subs = []


# ============================================================
# 一、解析 / 规范化
# ============================================================
def parse_proxy(raw):
    """解析代理地址 → dict 或 None（无法识别时）。

    返回：{scheme, host, port, user, password, raw(规范化), has_auth}"""
    s = str(raw or "").strip()
    if not s:
        return None
    # 去掉常见前缀噪音（用户可能从别处复制「代理：」之类）
    for pre in ("代理:", "代理：", "proxy:", "proxy："):
        if s.lower().startswith(pre.lower()):
            s = s[len(pre):].strip()
    explicit_scheme = ("://" in s)
    if not explicit_scheme:
        s = "http://" + s
    try:
        p = urllib.parse.urlsplit(s)
    except Exception:
        return None
    scheme = (p.scheme or "").lower()
    if scheme not in SCHEMES:
        return None
    try:
        host = p.hostname or ""
    except Exception:
        return None
    if not host:
        return None
    port = p.port
    if port is None:
        # 不臆测端口：只写了 host（无协议、无端口）时无法判断，判为无效让用户补全；
        # 显式写了协议（http://x）才按协议默认端口兜底。
        if not explicit_scheme:
            return None
        port = _DEFAULT_PORT.get(scheme, 80)
    try:
        port = int(port)
    except Exception:
        return None
    if not (0 < port < 65536):
        return None
    user = urllib.parse.unquote(p.username or "")
    pwd = urllib.parse.unquote(p.password or "")
    d = {"scheme": scheme, "host": host, "port": port,
         "user": user, "password": pwd, "has_auth": bool(user)}
    d["raw"] = format_proxy(d)
    return d


def format_proxy(p):
    """dict → 规范化字符串（含账号密码，供存储与子进程环境变量使用）。"""
    if not p:
        return ""
    auth = ""
    if p.get("user"):
        auth = "%s:%s@" % (urllib.parse.quote(p["user"], safe=""),
                           urllib.parse.quote(p.get("password") or "", safe=""))
    host = p["host"]
    if ":" in host and not host.startswith("["):   # IPv6 字面量
        host = "[%s]" % host
    return "%s://%s%s:%d" % (p["scheme"], auth, host, int(p["port"]))


def display_proxy(p):
    """给界面显示的字符串（**隐去密码**）。"""
    if not p:
        return ""
    auth = ""
    if p.get("user"):
        auth = "%s:***@" % urllib.parse.quote(p["user"], safe="")
    host = p["host"]
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    return "%s://%s%s:%d" % (p["scheme"], auth, host, int(p["port"]))


def parse_error_hint(raw):
    """给用户的输入纠错提示（无效时用）。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    if "://" in s and s.split("://", 1)[0].lower() not in SCHEMES:
        return "暂不支持该协议，请用 http / https / socks5（socks5h 亦可）"
    if ":" not in s:
        return "缺少端口，请写成 host:port（如 127.0.0.1:7890）"
    return "地址格式无法识别，示例：http://127.0.0.1:7890 或 socks5://127.0.0.1:7891"


# ============================================================
# 二、全局单例（两处 UI 共用；未设置时回落环境变量）
# ============================================================
def _env_proxy():
    """环境变量里的代理（仅作提示 / CLI 显式启用用）。NO_PROXY=* 时一律视为无。"""
    for k in ("NO_PROXY", "no_proxy"):
        if str(os.environ.get(k) or "").strip() == "*":
            return ""
    for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy",
              "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(k)
        if v and parse_proxy(v):
            return v
    return ""


def set_active(raw):
    """设置当前代理（"" 或无效值 = 直连）。返回规范化后的字符串（无效则为 ""）。"""
    p = parse_proxy(raw)
    canonical = (p["raw"] if p else "")
    with _LOCK:
        _active["raw"] = canonical
        _active["parsed"] = p
    _notify(canonical)
    return canonical


def get_active():
    """当前生效的代理 dict（None = 直连）。

    ⚠️ 语义刻意保持**可预测**：只看界面/程序里显式设置的代理，**不偷偷回落环境变量**
    —— 否则用户把输入框留空（本意直连）时，会被系统里的 HTTP_PROXY 悄悄接管，
    检测结果就会与预期不符。环境变量代理另由 `env_proxy_raw()` 只作提示。"""
    with _LOCK:
        return _active["parsed"]


def active_raw():
    """当前**显式设置的**规范化代理串（供 UI 回填输入框）。"""
    with _LOCK:
        return _active["raw"]


def env_proxy_raw():
    """系统环境变量里的代理串（无则 ""）。仅供界面提示 / CLI 显式启用，不自动生效。"""
    return _env_proxy()


def resolve(proxy=None):
    """统一解析调用方传入的 proxy 参数：
      · None → 当前生效代理（全局设置）
      · ""   → 强制直连（显式空串）
      · dict → 原样返回（已解析）
      · 其它 → parse_proxy(str)
    返回 dict 或 None（None = 直接连）。"""
    if proxy is None:
        return get_active()
    if isinstance(proxy, dict):
        return proxy or None
    s = str(proxy)
    if not s.strip():
        return None
    return parse_proxy(s)


def subscribe(cb):
    """订阅代理变更（两处 UI 互相同步）。返回 cb 便于链式取消。"""
    if callable(cb) and cb not in _subs:
        _subs.append(cb)
    return cb


def unsubscribe(cb):
    try:
        _subs.remove(cb)
    except ValueError:
        pass


def _notify(canonical):
    for cb in list(_subs):
        try:
            cb(canonical)
        except Exception:
            pass


def proxy_env(proxy=None):
    """给子进程用的代理环境变量 dict（无代理时返回 {}）。
    大小写键都给一份 —— requests/urllib 两种都认，但个别库只读其一。"""
    p = resolve(proxy)
    if not p:
        return {}
    u = format_proxy(p)
    return {"HTTP_PROXY": u, "HTTPS_PROXY": u, "ALL_PROXY": u,
            "http_proxy": u, "https_proxy": u, "all_proxy": u}


def proxy_handler_map(proxy=None):
    """urllib.request.ProxyHandler 用的映射（无代理时 {}）。"""
    p = resolve(proxy)
    if not p:
        return {}
    u = format_proxy(p)
    return {"http": u, "https": u}


# ============================================================
# 三、底层隧道（HTTP CONNECT / SOCKS5，均零依赖）
# ============================================================
def _ssl_ctx():
    """不校验证书的 TLS 上下文：本机代理 / 被劫持 / 自签环境常见，检测不因证书失败。"""
    try:
        ctx = ssl.create_default_context()
    except Exception:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("连接被对端提前关闭")
        buf += chunk
    return buf


def _read_line(sock, limit=16384):
    buf = b""
    while len(buf) < limit:
        ch = sock.recv(1)
        if not ch:
            break
        buf += ch
        if buf.endswith(b"\n"):
            break
    return buf.decode("latin-1", "replace").rstrip("\r\n")


def _host_bytes(host):
    try:
        return host.encode("idna")
    except Exception:
        return host.encode("utf-8", "replace")


def _socks5_connect(p, dst_host, dst_port, timeout):
    """内置 SOCKS5 握手 + CONNECT（支持无认证与用户名/密码认证）。返回已连通的 socket。
    域名用 ATYP=3（远端解析）——与 socks5h 一致的稳妥做法，本地 DNS 被污染也不影响。"""
    s = socket.create_connection((p["host"], p["port"]), timeout=timeout)
    try:
        s.settimeout(timeout)
        want_auth = bool(p.get("user"))
        methods = b"\x00\x02" if want_auth else b"\x00"
        s.sendall(b"\x05" + bytes([len(methods)]) + methods)
        head = _recv_exact(s, 2)
        if head[0] != 5:
            raise OSError("SOCKS5 握手失败（版本 %d，可能不是 SOCKS5 代理）" % head[0])
        method = head[1]
        if method == 0xFF:
            raise OSError("SOCKS5 代理拒绝了可用的认证方式")
        if method == 2:
            u = (p.get("user") or "").encode("utf-8")
            pw = (p.get("password") or "").encode("utf-8")
            s.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(pw)]) + pw)
            r = _recv_exact(s, 2)
            if r[1] != 0:
                raise OSError("SOCKS5 用户名/密码认证失败")
        elif method != 0:
            raise OSError("SOCKS5 不支持的认证方式：%d" % method)

        hb = _host_bytes(dst_host)
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb
                  + struct.pack(">H", int(dst_port)))
        rep = _recv_exact(s, 4)
        if rep[1] != 0:
            reasons = {1: "通用失败", 2: "规则不允许", 3: "网络不可达", 4: "主机不可达",
                       5: "连接被拒", 6: "TTL 超时", 7: "命令不支持", 8: "地址类型不支持"}
            raise OSError("SOCKS5 连接失败：%s（代码 %d）"
                          % (reasons.get(rep[1], "未知"), rep[1]))
        atyp = rep[3]
        if atyp == 1:
            _recv_exact(s, 4)
        elif atyp == 3:
            _recv_exact(s, _recv_exact(s, 1)[0])
        elif atyp == 4:
            _recv_exact(s, 16)
        _recv_exact(s, 2)          # 绑定端口
        return s
    except BaseException:
        try:
            s.close()
        except Exception:
            pass
        raise


def _http_connect_tunnel(p, dst_host, dst_port, timeout):
    """HTTP/HTTPS 代理的 CONNECT 隧道。https 代理先与代理本身建 TLS。"""
    s = socket.create_connection((p["host"], p["port"]), timeout=timeout)
    try:
        s.settimeout(timeout)
        if p.get("scheme") == "https":
            s = _ssl_ctx().wrap_socket(s, server_hostname=p["host"])
        auth = ""
        if p.get("user"):
            tok = base64.b64encode(
                ("%s:%s" % (p["user"], p.get("password") or "")).encode("utf-8")).decode()
            auth = "Proxy-Authorization: Basic %s\r\n" % tok
        target = "%s:%d" % (dst_host, int(dst_port))
        req = ("CONNECT %s HTTP/1.1\r\nHost: %s\r\n"
               "Proxy-Connection: Keep-Alive\r\n%s\r\n" % (target, target, auth))
        s.sendall(req.encode("latin-1", "replace"))
        line = _read_line(s)
        parts = line.split()
        if len(parts) < 2 or not parts[1].startswith("2"):
            raise OSError("代理 CONNECT 被拒：%s" % (line.strip()[:100] or "无响应"))
        # 吞掉剩余响应头（直到空行），个别代理会回多个头
        for _ in range(50):
            if _read_line(s) == "":
                break
        return s
    except BaseException:
        try:
            s.close()
        except Exception:
            pass
        raise


def open_tunnel(proxy, dst_host, dst_port, timeout=10.0):
    """打开到 dst_host:dst_port 的连接：proxy=None 直连，否则经代理隧道。"""
    if not proxy:
        s = socket.create_connection((dst_host, int(dst_port)), timeout=timeout)
        s.settimeout(timeout)
        return s
    if str(proxy.get("scheme", "")).startswith("socks"):
        return _socks5_connect(proxy, dst_host, dst_port, timeout)
    return _http_connect_tunnel(proxy, dst_host, dst_port, timeout)


# ============================================================
# 四、统一 HTTP 请求（代理 / 直连同一套代码）
# ============================================================
def request_via(proxy, url, method="GET", timeout=10.0, max_bytes=MAX_BYTES,
                headers=None, read_all=False):
    """经指定代理（proxy=None = 直连）发一次 HTTP/1.1 请求并读回响应。

    返回 dict：{ok, status, reason, latency_ms, total_ms, err, host, port,
                url, body(bytes), headers(dict)}
      · ok：2xx/3xx 为 True（与源管家「只有 2xx/3xx 才算可达」口径一致）
      · latency_ms：到「响应状态行」的耗时（首个响应字节）
      · body：最多 max_bytes；read_all=True 时不限（硬上限 16MB）
    """
    res = {"ok": False, "status": None, "reason": "", "latency_ms": None,
           "total_ms": None, "err": "", "host": "", "port": None,
           "url": url, "body": b"", "headers": {}, "truncated": False}
    u = str(url or "").strip()
    try:
        p = urllib.parse.urlsplit(u)
    except Exception:
        res["err"] = "URL 无法解析"
        return res
    scheme = (p.scheme or "").lower()
    if scheme not in ("http", "https") or not p.hostname:
        res["err"] = "仅支持 http/https URL"
        return res
    host = p.hostname
    port = p.port or (443 if scheme == "https" else 80)
    res["host"], res["port"] = host, port
    path = p.path or "/"
    if p.query:
        path += "?" + p.query

    hdr = {"Host": host if port in (80, 443) else "%s:%d" % (host, port),
           "User-Agent": _UA, "Accept": "*/*", "Connection": "close"}
    for k, v in (headers or {}).items():
        hdr[str(k)] = str(v)
    head = "%s %s HTTP/1.1\r\n" % (method, path)
    head += "".join("%s: %s\r\n" % (k, v) for k, v in hdr.items()) + "\r\n"

    limit = HARD_MAX_BYTES if read_all else max(1, int(max_bytes or MAX_BYTES))
    t0 = time.time()
    sock = None
    try:
        sock = open_tunnel(proxy, host, port, timeout)
        if scheme == "https":
            sock = _ssl_ctx().wrap_socket(sock, server_hostname=host)
        sock.sendall(head.encode("latin-1", "replace"))
        line = _read_line(sock)
        res["latency_ms"] = int((time.time() - t0) * 1000)
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[1].isdigit():
            raise OSError("响应不是合法 HTTP 状态行：%s" % (line.strip()[:80] or "空响应"))
        status = int(parts[1])
        res["status"] = status
        res["reason"] = (parts[2] if len(parts) > 2 else "").strip()
        # 响应头
        for _ in range(200):
            hl = _read_line(sock)
            if hl == "":
                break
            if ":" in hl:
                k, v = hl.split(":", 1)
                res["headers"][k.strip().lower()] = v.strip()
        # 响应体（读到 EOF / 上限）
        body = b""
        sock.settimeout(max(1.0, min(6.0, float(timeout))))
        while len(body) < limit:
            try:
                chunk = sock.recv(min(65536, limit - len(body)))
            except socket.timeout:
                break
            except OSError:
                break
            if not chunk:
                break
            body += chunk
        res["body"] = body
        # read_all 模式下读到硬上限即视为「被截断」——调用方（如 jar MD5）必须据此放弃
        # 基于内容的判断，否则会拿半截数据算出错误的 MD5。
        res["truncated"] = bool(read_all and len(body) >= limit)
        res["ok"] = 200 <= status < 400
        if not res["ok"]:
            res["err"] = "http:%d" % status
    except socket.timeout:
        res["err"] = "连接超时（%ss）" % timeout
    except OSError as ex:
        msg = str(ex)
        low = msg.lower()
        if "timed out" in low:
            res["err"] = "连接超时（%ss）" % timeout
        elif "refused" in low or "拒绝" in msg:
            res["err"] = "连接被拒绝（%s）" % msg
        elif "certificate" in low or "ssl" in low:
            res["err"] = "TLS 握手失败：%s" % msg[:80]
        elif "name or service" in low or "getaddrinfo" in low:
            res["err"] = "域名解析失败（代理地址可能写错）：%s" % msg[:60]
        else:
            res["err"] = msg[:120]
    except Exception as ex:
        res["err"] = "%s: %s" % (type(ex).__name__, str(ex)[:100])
    finally:
        try:
            if sock is not None:
                sock.close()
        except Exception:
            pass
    res["total_ms"] = int((time.time() - t0) * 1000)
    return res


def http_get_via(proxy, url, timeout=10.0, max_bytes=MAX_BYTES, headers=None):
    """检测用简封装：GET 一次，只关心 ok/status/耗时/错误。"""
    return request_via(proxy, url, "GET", timeout, max_bytes, headers)


def text_of(res, limit=None):
    """把 request_via 的 body 解成文本（utf-8 失败回落 gbk），并解开 \\uXXXX 转义。"""
    body = (res or {}).get("body") or b""
    if not body:
        return ""
    import re as _re
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("gbk", errors="ignore")
    if "\\u" in text:
        try:
            text = _re.sub(r"\\u([0-9a-fA-F]{4})",
                           lambda m: chr(int(m.group(1), 16)), text)
        except Exception:
            pass
    if limit:
        text = text[:int(limit)]
    return text


# ============================================================
# 五、验证服务器是否正常（口径：能否连到 Google 首页）
# ============================================================
def check_proxy(spec=None, test_url=None, timeout=CHECK_TIMEOUT, with_direct=True):
    """验证代理服务器是否正常 —— **以能否连到 Google 首页为准**。

    spec：代理串（dict 亦可）。None → 取当前生效代理。
    test_url：自定义测试地址（单测用；默认 Google 首页，失败自动试 generate_204）。
    with_direct：是否附带一次「直连」对照（用于判断代理是否真的在起作用）。

    返回 dict：
      {spec, valid, ok, label, note, url, status, latency_ms,
       via(dict), direct(dict|None), applied(bool|None)}
    """
    p = resolve(spec) if not isinstance(spec, dict) else (spec or None)
    res = {"spec": (display_proxy(p) if p else str(spec or "")), "valid": bool(p),
           "ok": False, "label": "不可用", "note": "", "url": test_url or CHECK_URL,
           "status": None, "latency_ms": None, "via": None, "direct": None,
           "applied": None}
    if not p:
        res["note"] = ("未配置代理（留空即直连）。" if not str(spec or "").strip()
                       else "代理地址无法识别：" + parse_error_hint(str(spec)))
        res["label"] = "未配置" if not str(spec or "").strip() else "格式错误"
        return res

    # 经代理访问 Google 首页（主地址失败再试 generate_204，提高容错）
    via = None
    for u in ([res["url"]] if test_url else [CHECK_URL, CHECK_FALLBACK_URL]):
        via = http_get_via(p, u, timeout=timeout, max_bytes=2048)
        if via.get("ok"):
            res["url"] = u
            break
    res["via"] = via
    res["status"] = via.get("status")
    res["latency_ms"] = via.get("latency_ms")
    res["ok"] = bool(via.get("ok"))

    direct = None
    if with_direct:
        direct = http_get_via(None, res["url"], timeout=timeout, max_bytes=2048)
        res["direct"] = direct
        res["applied"] = bool(res["ok"] and not direct.get("ok"))

    ms = via.get("latency_ms")
    ms_txt = ("%d ms" % ms) if isinstance(ms, int) else "耗时未知"
    if res["ok"]:
        res["label"] = "正常"
        if res["applied"] is True:
            res["note"] = ("代理服务器正常：经代理打开 Google 首页 HTTP %s（%s）；"
                           "直连不通 → 代理确实在起作用"
                           % (via.get("status"), ms_txt))
        elif res["applied"] is False:
            res["note"] = ("代理服务器正常：经代理打开 Google 首页 HTTP %s（%s）；"
                           "（直连也能打开 Google，代理是否必须由您判断）"
                           % (via.get("status"), ms_txt))
        else:
            res["note"] = ("代理服务器正常：经代理打开 Google 首页 HTTP %s（%s）"
                           % (via.get("status"), ms_txt))
    else:
        res["label"] = "不可用"
        err = via.get("err") or "未知错误"
        res["note"] = ("代理服务器不可用：%s。请检查地址/端口是否正确、"
                       "代理软件是否已启动。" % err)
        if direct is not None and direct.get("ok"):
            res["note"] += "（当前直连可访问 Google，可先留空走直连）"
    return res


# ============================================================
# 六、自检
# ============================================================
if __name__ == "__main__":       # 手动试跑：python pyinj_proxy.py <代理串>
    import sys
    import json as _json
    if len(sys.argv) > 1:
        r = check_proxy(sys.argv[1])
        r2 = dict(r)
        if r2.get("via"):
            r2["via"] = {k: v for k, v in r2["via"].items() if k != "body"}
        if r2.get("direct"):
            r2["direct"] = {k: v for k, v in r2["direct"].items() if k != "body"}
        print(_json.dumps(r2, ensure_ascii=False, indent=2))
    else:
        print("用法：python pyinj_proxy.py <代理串>（如 http://127.0.0.1:7890）")
