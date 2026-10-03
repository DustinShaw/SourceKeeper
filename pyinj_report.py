# -*- coding: utf-8 -*-
"""源管家 · 诊断报告导出模块（pyinj_report）
==============================================
把「源测速 / 网络诊断 / 分类识别 / JAR 体检」的结果汇总成一份**可读、
可分享**的报告，支持 Markdown（便于粘贴/预览）与 CSV（便于表格处理）。

设计原则：
  · 零 Qt 依赖、纯逻辑；
  · 汇总层只负责**编排 + 格式化**，具体检测复用 pyinj_speed / pyinj_netdiag /
    pyinj_jar / pyinj_kw，不重复实现；
  · 报告内容与界面无关，可独立跑（__main__ 里对配置做一次全量体检）。

主要接口：
  · build_report(sites, base_dir, ...)   → 报告数据结构 dict
  · render_markdown(report)              → Markdown 文本
  · render_csv(report)                   → CSV 文本
  · export_report(path, report, fmt=None) → 写盘（按扩展名选格式）
"""

import csv
import io
import os
import time

from pyinj_core import source_type_of, resolve_spider_path, read_text, CONFIG_NAME
from pyinj_kw import detect_categories, load_keywords, CAT_LABELS, _CAT_ORDER
from pyinj_speed import speed_test_source
from pyinj_netdiag import diagnose_source, LEVEL_LABELS
from pyinj_jar import is_jar_entry, check_jar_source, JAR_LABELS


# 每类源最多取多少个 URL 参与测速/诊断（控制耗时）
MAX_URLS = 2


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_spider_text(entry, base_dir):
    """取条目对应 .py 的文本（用于分类识别）；取不到返回 ""。"""
    api = str(entry.get("api") or "")
    if not api or not base_dir:
        return ""
    try:
        p = resolve_spider_path(base_dir, api)
        if p and os.path.isfile(p):
            return read_text(p)
    except Exception:
        return ""
    return ""


def analyze_one(entry, base_dir=None, keywords=None,
                do_speed=True, do_diag=True, do_jar=True):
    """对单条源做一次完整分析，返回一条报告的原始记录 dict。"""
    name = str(entry.get("name") or "")
    api = str(entry.get("api") or "")
    t = source_type_of(entry)
    rec = {
        "name": name, "api": api, "type": t, "key": str(entry.get("key") or ""),
        "categories": {}, "cat_labels": "",
        "speed": None, "diag": None, "jar": None,
    }

    # 分类识别（用 .py 内容 + 站点名）
    try:
        text = _read_spider_text(entry, base_dir)
        cats = detect_categories(text, name, keywords)
        rec["categories"] = cats
        rec["cat_labels"] = "·".join(CAT_LABELS.get(c, c) for c in _CAT_ORDER if c in cats)
    except Exception:
        pass

    # JAR 体检
    if do_jar and is_jar_entry(entry):
        try:
            rec["jar"] = check_jar_source(entry)
        except Exception as e:
            rec["jar"] = {"level": "unreachable", "label": JAR_LABELS.get("unreachable", "不可达"),
                          "ok": False, "note": str(e)[:80], "url": ""}

    # 测速
    if do_speed:
        try:
            rec["speed"] = speed_test_source(entry, base_dir, max_urls=MAX_URLS)
        except Exception as e:
            rec["speed"] = {"reachable": None, "note": str(e)[:80], "best": None, "results": []}

    # 网络诊断
    if do_diag:
        try:
            rec["diag"] = diagnose_source(entry, base_dir, max_urls=MAX_URLS)
        except Exception as e:
            rec["diag"] = {"level": "unknown", "label": "异常", "note": str(e)[:80],
                           "needs_proxy": False, "results": []}

    return rec


def build_report(sites, base_dir=None, repo_name="", progress_cb=None,
                 stop_check=None, **kw):
    """对整份 sites 做体检，返回报告数据结构 dict：
    {title, generated_at, repo, total, records:[...], summary:{...}}。"""
    sites = [e for e in (sites or []) if isinstance(e, dict)]
    keywords = load_keywords()
    records = []
    total = len(sites)
    for i, e in enumerate(sites):
        if stop_check and stop_check():
            break
        rec = analyze_one(e, base_dir, keywords, **kw)
        records.append(rec)
        if progress_cb:
            try:
                progress_cb(i + 1, total, rec.get("name", ""))
            except Exception:
                pass
    summary = _summarize(records)
    return {"title": "源管家 · 源诊断报告", "generated_at": _now(),
            "repo": repo_name, "total": len(records),
            "records": records, "summary": summary}


def _summarize(records):
    s = {"reachable": 0, "unreachable": 0, "proxy": 0, "dns_fail": 0,
         "jar_total": 0, "jar_ok": 0, "jar_bad": 0, "cat_counts": {}}
    for r in records:
        sp = r.get("speed") or {}
        if sp.get("reachable") is True:
            s["reachable"] += 1
        elif sp.get("reachable") is False:
            s["unreachable"] += 1
        dg = r.get("diag") or {}
        if dg.get("needs_proxy") or dg.get("level") == "proxy":
            s["proxy"] += 1
        if dg.get("level") == "dns":
            s["dns_fail"] += 1
        jr = r.get("jar")
        if jr:
            s["jar_total"] += 1
            if jr.get("level") == "ok":
                s["jar_ok"] += 1
            elif jr.get("level") in ("http", "unreachable", "small"):
                s["jar_bad"] += 1
        for c in (r.get("categories") or {}):
            s["cat_counts"][c] = s["cat_counts"].get(c, 0) + 1
    return s


# ----------------------------------------------------------------------------
# 渲染
# ----------------------------------------------------------------------------
def _speed_cell(sp):
    if not sp:
        return "-"
    if sp.get("reachable") is True:
        best = sp.get("best") or {}
        ms = best.get("latency_ms")
        q = best.get("quality", "")
        return "%s %sms" % (q, ms if ms is not None else "?")
    if sp.get("reachable") is False:
        return "不可达"
    return "未测"


def _diag_cell(dg):
    if not dg:
        return "-"
    lbl = dg.get("label") or LEVEL_LABELS.get(dg.get("level", ""), "异常")
    if dg.get("needs_proxy"):
        return lbl + "（需代理）"
    return lbl


def _jar_cell(jr):
    if not jr:
        return "-"
    return jr.get("label") or JAR_LABELS.get(jr.get("level", ""), "?")


def render_markdown(report):
    """把报告渲染成 Markdown 文本。"""
    lines = []
    lines.append("# %s" % report.get("title", "源诊断报告"))
    lines.append("")
    lines.append("- 生成时间：%s" % report.get("generated_at", ""))
    if report.get("repo"):
        lines.append("- 配置仓库：%s" % report["repo"])
    lines.append("- 站点总数：%d" % report.get("total", 0))
    lines.append("")

    s = report.get("summary") or {}
    lines.append("## 概览")
    lines.append("")
    lines.append("| 指标 | 数量 |")
    lines.append("| --- | --- |")
    lines.append("| 可达 | %d |" % s.get("reachable", 0))
    lines.append("| 不可达 | %d |" % s.get("unreachable", 0))
    lines.append("| 疑似需特殊上网 | %d |" % s.get("proxy", 0))
    lines.append("| DNS 解析失败 | %d |" % s.get("dns_fail", 0))
    lines.append("| JAR 源（健康/异常） | %d（%d/%d） |" % (
        s.get("jar_total", 0), s.get("jar_ok", 0), s.get("jar_bad", 0)))
    cc = s.get("cat_counts") or {}
    if cc:
        cats = "、".join("%s %d" % (CAT_LABELS.get(c, c), cc[c])
                        for c in _CAT_ORDER if c in cc)
        lines.append("| 分类命中 | %s |" % cats)
    lines.append("")

    lines.append("## 明细")
    lines.append("")
    lines.append("| 站点 | 类型 | 分类 | 测速 | 网络诊断 | JAR | 说明 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in report.get("records", []):
        name = (r.get("name") or "").replace("|", "\\|")
        notes = []
        sp = r.get("speed") or {}
        if sp.get("note"):
            notes.append(sp["note"])
        dg = r.get("diag") or {}
        if dg.get("level") == "dns" and dg.get("note"):
            notes.append(dg["note"])
        jr = r.get("jar") or {}
        if jr and jr.get("level") not in ("ok", None) and jr.get("note"):
            notes.append("jar: " + jr["note"])
        note = "；".join(n for n in notes if n)
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            name, r.get("type", ""), r.get("cat_labels", "") or "-",
            _speed_cell(sp), _diag_cell(dg), _jar_cell(jr), note))
    lines.append("")
    return "\n".join(lines)


def render_csv(report):
    """把报告渲染成 CSV 文本（UTF-8 BOM 便于 Excel 直接打开中文）。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["站点", "key", "type", "分类", "可达", "延迟ms", "质量",
                "网络诊断", "需代理", "JAR", "说明"])
    for r in report.get("records", []):
        sp = r.get("speed") or {}
        best = sp.get("best") or {}
        dg = r.get("diag") or {}
        jr = r.get("jar") or {}
        w.writerow([
            r.get("name", ""), r.get("key", ""), r.get("type", ""),
            r.get("cat_labels", ""),
            "是" if sp.get("reachable") is True else ("否" if sp.get("reachable") is False else ""),
            best.get("latency_ms", ""), best.get("quality", ""),
            dg.get("label", ""),
            "是" if dg.get("needs_proxy") else "",
            (jr.get("label") if jr else ""),
            (sp.get("note") or dg.get("note") or ""),
        ])
    return "\ufeff" + buf.getvalue()


def export_report(path, report, fmt=None):
    """按路径扩展名（或显式 fmt）写报告。返回写入路径。"""
    if fmt is None:
        ext = os.path.splitext(path)[1].lower()
        fmt = "csv" if ext == ".csv" else "md"
    text = render_csv(report) if fmt == "csv" else render_markdown(report)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


if __name__ == "__main__":       # 手动试跑：python pyinj_report.py <repo_dir>
    import sys
    from pyinj_core import load_repo
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    data = load_repo(repo)
    sites = data.get("sites", []) if isinstance(data, dict) else []
    rep = build_report(sites, repo, repo_name=os.path.basename(os.path.abspath(repo)),
                       progress_cb=lambda i, t, n: print("[%d/%d] %s" % (i, t, n)))
    print(render_markdown(rep))
