# -*- coding: utf-8 -*-
"""源管家 · Spider JAR 健康检查模块（pyinj_jar）
=================================================
TVBox/影视仓里有一类 **jar 型 spider 源**：
    { "key": "csp_Xxx", "name": "Xxx", "type": 3, "api": "csp_Xxx",
      "jar": "http://xxx/drpy.jar" }
其 `api` 是一个**类名**（csp_Xxx），真正干活的代码在远程 `jar` 里。所以：
  · 它**不该**有本地 .py 文件（pyinj_core.expects_local_file 已修正为 False）；
  · 它是否「健康」取决于那个 **jar URL 能不能下载到、大小是否合理**。

本模块就以「新增模块」方式补齐这部分体检能力：
  · jar_url_of(entry)          → 从条目里取出 jar URL（可能有 jar 字段，也兼容 api 直接写 http）
  · check_jar_url(url)         → 下载前 N 字节 + 取 Content-Length，判定健康/可疑/失效
  · check_jar_source(entry)    → 条目级 jar 体检
  · iter_jar_entries(sites)    → 从 sites 里筛出所有 jar 型条目

复用 pyinj_core 的 _HTTP_UA 与 source_type_of，不重写它们。
零 Qt 依赖、纯逻辑，可单测。
"""

import hashlib
import ssl
import urllib.request
import urllib.error

from pyinj_core import source_type_of, _HTTP_UA
import pyinj_proxy as _proxy_mod

# ---- 体检预算 ----
JAR_TIMEOUT = 8.0
JAR_MIN_BYTES = 1024          # 一个可用的 jar 通常远大于 1KB；小于此值多半是错误页
JAR_PROBE_BYTES = 4096        # 探测时只读前 N 字节（不整包下载）
JAR_MD5_MAX_BYTES = 64 * 1024 * 1024   # 计算整包 MD5 的上限（超过则只报「过大」，不整包下载）

# 健康等级
JAR_OK = "ok"                 # 健康（2xx 且拿到合理大小的内容）
JAR_SMALL = "small"           # 可疑（2xx 但内容过小，可能是错误页/占位）
JAR_HTTP_ERR = "http"         # HTTP 层错误（4xx/5xx）
JAR_UNREACHABLE = "unreachable"  # 网络不可达 / 超时
JAR_NO_URL = "no_url"         # 条目里没有 jar URL

JAR_LABELS = {
    JAR_OK: "健康",
    JAR_SMALL: "可疑",
    JAR_HTTP_ERR: "HTTP 错误",
    JAR_UNREACHABLE: "不可达",
    JAR_NO_URL: "无 jar",
}

# MD5 校验结果
MD5_OK = "ok"                 # 与期望值一致
MD5_MISMATCH = "mismatch"     # 与期望值不一致（jar 可能被替换/篡改）
MD5_SKIP = "skip"             # 未提供期望值 / jar 过大 / 下载失败
MD5_LABELS = {MD5_OK: "一致", MD5_MISMATCH: "不一致", MD5_SKIP: "未校验"}


def jar_url_of(entry):
    """取出条目对应的 jar URL。
    优先 `jar` 字段；若没有，但 `api` 本身就是 http(s) 且以 .jar 结尾，则用 api。
    取不到返回 ""。"""
    if not isinstance(entry, dict):
        return ""
    jar = str(entry.get("jar") or "").strip()
    if jar:
        return jar
    api = str(entry.get("api") or "").strip()
    if api.startswith("http") and api.lower().split("?")[0].endswith(".jar"):
        return api
    return ""


def is_jar_entry(entry):
    """是否属于 jar 型 spider 源（有 jar URL）。"""
    return bool(jar_url_of(entry))


def iter_jar_entries(sites):
    """从 sites 列表里筛出所有 jar 型条目，返回 [(entry, jar_url), ...]。"""
    out = []
    for e in sites or []:
        if not isinstance(e, dict):
            continue
        u = jar_url_of(e)
        if u:
            out.append((e, u))
    return out


def _open_head(url, timeout=JAR_TIMEOUT, read_bytes=JAR_PROBE_BYTES, proxy=None):
    """打开 URL 读前 N 字节 + 尽量取 Content-Length。
    返回 (status, nbytes, content_length, content_type, err)。
    配置了自定义代理时经代理请求。"""
    px = _proxy_mod.resolve(proxy)
    if px:
        r = _proxy_mod.request_via(
            px, url, "GET", timeout=timeout, max_bytes=read_bytes,
            headers={"Range": "bytes=0-%d" % (read_bytes - 1)})
        if r.get("status") is None:
            return None, 0, -1, "", (r.get("err") or "无响应")[:100]
        clen = -1
        try:
            clen = int(r["headers"].get("content-length") or -1)
        except Exception:
            clen = -1
        return (r["status"], len(r.get("body") or b""), clen,
                (r["headers"].get("content-type") or "").lower(), "")
    req = urllib.request.Request(
        url, method="GET",
        headers={"User-Agent": _HTTP_UA, "Accept": "*/*",
                 # jar 是二进制；向支持 Range 的服务器只要前几 KB 就够体检
                 "Range": "bytes=0-%d" % (read_bytes - 1)})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            status = getattr(resp, "status", None) or 200
            clen = resp.headers.get("Content-Length")
            ctype = (resp.headers.get("Content-Type") or "").lower()
            try:
                head = resp.read(read_bytes)
            except Exception:
                head = b""
            try:
                clen = int(clen) if clen is not None else -1
            except Exception:
                clen = -1
            return status, len(head or b""), clen, ctype, ""
    except urllib.error.HTTPError as e:
        return e.code, 0, -1, "", "http:%d" % e.code
    except Exception as ex:
        return None, 0, -1, "", str(ex)[:100]


def compute_md5(url, timeout=JAR_TIMEOUT, max_bytes=JAR_MD5_MAX_BYTES, proxy=None):
    """下载整包（流式，边读边算 MD5），返回 {'md5','bytes','status','note'}。

    · 超过 max_bytes 视为过大，不整包下载（note 说明），md5 为空；
    · 服务器报的 Content-Length 已知超限时直接跳过，避免白下；
    · 任何异常都转成 note，绝不抛出（供 GUI 安全调用）。
    · 配置了自定义代理时经代理下载；若响应超过代理模块的硬上限被**截断**，
      一律判为「过大」跳过 MD5（半截数据算出的 MD5 是错的，宁可不算）。
    """
    out = {"md5": "", "bytes": 0, "status": None, "note": ""}
    if not url:
        out["note"] = "无 URL"
        return out
    px = _proxy_mod.resolve(proxy)
    if px:
        r = _proxy_mod.request_via(px, url, "GET", timeout=timeout, read_all=True)
        out["status"] = r.get("status")
        body = r.get("body") or b""
        out["bytes"] = len(body)
        if r.get("status") is None:
            out["note"] = "下载失败：%s" % (r.get("err") or "无响应")
            return out
        if not r.get("ok"):
            out["note"] = "HTTP %s" % r.get("status")
            return out
        clen = -1
        try:
            clen = int(r["headers"].get("content-length") or -1)
        except Exception:
            clen = -1
        if r.get("truncated") or clen > max_bytes:
            out["note"] = ("jar 过大（%s 字节 > 上限 %d），已跳过 MD5"
                           % (clen if clen > 0 else ">硬上限", max_bytes))
            return out
        out["md5"] = hashlib.md5(body).hexdigest()
        return out
    req = urllib.request.Request(
        url, method="GET",
        headers={"User-Agent": _HTTP_UA, "Accept": "*/*"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    h = hashlib.md5()
    n = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            out["status"] = getattr(resp, "status", None) or 200
            clen = resp.headers.get("Content-Length")
            try:
                clen = int(clen) if clen is not None else -1
            except Exception:
                clen = -1
            if clen > max_bytes:
                out["note"] = "jar 过大（%d 字节 > 上限 %d），已跳过 MD5" % (clen, max_bytes)
                return out
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                n += len(chunk)
                if n > max_bytes:
                    out["note"] = "jar 过大（> %d 字节），已停止并跳过 MD5" % max_bytes
                    out["bytes"] = n
                    return out
                h.update(chunk)
    except Exception as ex:
        out["note"] = "下载失败：%s" % str(ex)[:100]
        return out
    out["bytes"] = n
    out["md5"] = h.hexdigest()
    return out


def verify_md5(url, expect_md5, timeout=JAR_TIMEOUT, max_bytes=JAR_MD5_MAX_BYTES,
               proxy=None):
    """下载 jar 计算 MD5 并与 expect_md5 比对。
    返回 {'level': ok/mismatch/skip, 'label', 'md5', 'expect', 'bytes', 'note'}"""
    expect = str(expect_md5 or "").strip().lower()
    res = {"level": MD5_SKIP, "label": MD5_LABELS[MD5_SKIP], "md5": "",
           "expect": expect, "bytes": 0, "note": ""}
    if not expect:
        res["note"] = "未提供期望 MD5"
        return res
    got = compute_md5(url, timeout=timeout, max_bytes=max_bytes, proxy=proxy)
    res["md5"] = got["md5"]
    res["bytes"] = got["bytes"]
    if not got["md5"]:
        res["note"] = got["note"] or "无法计算 MD5"
        return res
    if got["md5"].lower() == expect:
        res["level"] = MD5_OK
        res["label"] = MD5_LABELS[MD5_OK]
        res["note"] = "MD5 与期望值一致"
    else:
        res["level"] = MD5_MISMATCH
        res["label"] = MD5_LABELS[MD5_MISMATCH]
        res["note"] = "MD5 不一致（期望 %s…，实测 %s…）" % (expect[:8], got["md5"][:8])
    return res


def check_jar_url(url, timeout=JAR_TIMEOUT, min_bytes=JAR_MIN_BYTES,
                  read_bytes=JAR_PROBE_BYTES, expect_md5=None, proxy=None):
    """对单个 jar URL 做体检。
    返回 dict：{url, level, label, ok(bool), status, bytes, content_length,
               content_type, note, md5_info}
    判定口径：
      · 2xx 且（Content-Length ≥ min_bytes 或 实际读到 ≥ min_bytes）→ 健康；
      · 2xx 但内容明显过小 → 可疑（可能被重定向到错误页/登录页）；
      · 4xx/5xx → HTTP 错误；
      · 取不到响应 → 不可达。
    注意：服务器不支持 Range 时也接受实际读到的字节数判断，避免误杀。
    可选 expect_md5：提供则额外下载整包比对 MD5（结果在 md5_info）。"""
    res = {"url": url, "level": JAR_UNREACHABLE, "label": JAR_LABELS[JAR_UNREACHABLE],
           "ok": False, "status": None, "bytes": 0, "content_length": -1,
           "content_type": "", "note": "", "md5_info": None}
    if not url:
        res["level"] = JAR_NO_URL
        res["label"] = JAR_LABELS[JAR_NO_URL]
        res["note"] = "条目中没有 jar URL"
        return res
    status, nbytes, clen, ctype, err = _open_head(url, timeout, read_bytes, proxy=proxy)
    res["status"] = status
    res["bytes"] = nbytes
    res["content_length"] = clen
    res["content_type"] = ctype
    if status is None:
        res["level"] = JAR_UNREACHABLE
        res["label"] = JAR_LABELS[JAR_UNREACHABLE]
        res["note"] = err or "不可达"
        return res
    if not (200 <= status < 400):
        res["level"] = JAR_HTTP_ERR
        res["label"] = JAR_LABELS[JAR_HTTP_ERR]
        res["note"] = "HTTP %d" % status
        return res
    # 2xx：用 Content-Length（若可信）与实读字节双重判断
    size = clen if clen > 0 else nbytes
    # 有些服务器不支持 Range，会返回全量 → 实读即为总量上限，够大即健康
    if size >= min_bytes:
        res["level"] = JAR_OK
        res["label"] = JAR_LABELS[JAR_OK]
        res["ok"] = True
        res["note"] = "内容大小 %d 字节%s" % (
            size, ("（Content-Length）" if clen > 0 else "（已读）"))
    else:
        res["level"] = JAR_SMALL
        res["label"] = JAR_LABELS[JAR_SMALL]
        res["note"] = "内容仅 %d 字节，疑似错误页/占位（< %d）" % (size, min_bytes)
    # 可选：MD5 校验（仅在提供了期望值时才下载整包）
    if expect_md5:
        res["md5_info"] = verify_md5(url, expect_md5, timeout=timeout, proxy=proxy)
        if res["md5_info"]["level"] == MD5_MISMATCH:
            res["ok"] = False
            res["note"] += "；MD5 不一致"
    return res


def check_jar_source(entry, timeout=JAR_TIMEOUT, expect_md5=None, proxy=None):
    """条目级 jar 体检。返回 check_jar_url 的结果，并补上 name/key/type。
    非 jar 型条目返回 level=no_url。expect_md5 提供时额外做 MD5 校验。"""
    url = jar_url_of(entry or {})
    res = check_jar_url(url, timeout=timeout, expect_md5=expect_md5, proxy=proxy)
    res["name"] = str((entry or {}).get("name") or "")
    res["key"] = str((entry or {}).get("key") or "")
    res["type"] = source_type_of(entry or {})
    return res


def check_jar_sites(sites, timeout=JAR_TIMEOUT, progress_cb=None,
                    stop_check=None, proxy=None):
    """批量体检 sites 里的所有 jar 型条目。
    返回 {results:[...], total, ok, small, bad}（bad = http/unreachable）。
    progress_cb(done, total, name) 可选；stop_check() 返回 True 时提前中止。"""
    pairs = iter_jar_entries(sites)
    total = len(pairs)
    results = []
    for i, (e, _u) in enumerate(pairs):
        if stop_check and stop_check():
            break
        r = check_jar_source(e, timeout=timeout, proxy=proxy)
        results.append(r)
        if progress_cb:
            try:
                progress_cb(i + 1, total, r.get("name", ""))
            except Exception:
                pass
    ok = sum(1 for r in results if r["level"] == JAR_OK)
    small = sum(1 for r in results if r["level"] == JAR_SMALL)
    bad = sum(1 for r in results if r["level"] in (JAR_HTTP_ERR, JAR_UNREACHABLE))
    return {"results": results, "total": total, "ok": ok,
            "small": small, "bad": bad}


if __name__ == "__main__":       # 手动试跑：python pyinj_jar.py <jar_url>
    import sys
    if len(sys.argv) > 1:
        print(check_jar_url(sys.argv[1]))
