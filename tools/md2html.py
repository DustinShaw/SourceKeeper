# -*- coding: utf-8 -*-
"""md2html.py —— 把「使用方法.md」渲染成带侧边栏书签的单文件 HTML。

设计要点（与项目约定一致）：
  · 零第三方依赖、零 CDN：只用标准库重写一个**针对本文档语法子集**的
    Markdown 解析器（标题 / 表格 / 引用块 / 有序·无序列表 / 代码块 /
    加粗 / 内联代码 / 链接 / 分隔线 / 段落）。
  · 单文件输出：CSS 与 JS 内联，双击即用，无网环境也正常。
  · 左侧固定侧边栏书签（方案 A）：H2 为一级、H3 为二级；
    IntersectionObserver 做滚动高亮；窄屏折叠为抽屉（☰ 按钮）。
  · 锚点稳定且可读（scene-1 / faq / win7 ...），不用中文标题当 id。
  · 深浅色跟随系统 prefers-color-scheme，与工具本身行为一致。

用法：
    python tools/md2html.py                    # 使用方法.md -> 使用方法.html
    python tools/md2html.py --in X.md --out Y.html
    python tools/md2html.py --check            # 只做自检，不写文件（构建用）
"""
import argparse
import html as _html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


# ----------------------------------------------------------------------
# 1) 行内元素：转义 -> 代码 -> 加粗 -> 链接
# ----------------------------------------------------------------------
def _inline(text):
    """把一行 Markdown 的行内语法转成 HTML（先转义再替换，避免注入）。"""
    out = _html.escape(text, quote=False)
    # 行尾两个空格 = 换行（GitHub 风格），先处理成占位
    out = re.sub(r" {2,}$", "\x00BR\x00", out)
    # 内联代码：`code`（内容已转义）
    out = re.sub(r"`([^`]+)`", lambda m: "<code>%s</code>" % m.group(1), out)
    # 加粗：**text**
    out = re.sub(r"\*\*([^*]+)\*\*", lambda m: "<strong>%s</strong>" % m.group(1), out)
    # 斜体：*text*（避开已生成的 strong 标签）
    out = re.sub(r"(?<![\*\w])\*([^*\n]+)\*(?!\*)",
                 lambda m: "<em>%s</em>" % m.group(1), out)
    # 链接：[文字](url)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                 lambda m: '<a href="%s"%s>%s</a>'
                 % (m.group(2),
                    ' target="_blank" rel="noopener"' if m.group(2).startswith("http") else "",
                    m.group(1)), out)
    out = out.replace("\x00BR\x00", "<br>")
    return out


# ----------------------------------------------------------------------
# 2) 表格
# ----------------------------------------------------------------------
def _is_table_sep(line):
    s = line.strip()
    return bool(re.fullmatch(r"\|[\s:\-|]+\|", s)) and "-" in s


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _render_table(rows):
    if not rows:
        return ""
    head = _split_row(rows[0])
    body = [_split_row(r) for r in rows[2:]] if len(rows) > 2 else []
    parts = ['<div class="tw"><table><thead><tr>']
    for c in head:
        parts.append("<th>%s</th>" % _inline(c))
    parts.append("</tr></thead><tbody>")
    for r in body:
        parts.append("<tr>")
        for c in r:
            parts.append("<td>%s</td>" % _inline(c))
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


# ----------------------------------------------------------------------
# 3) 块级解析：返回 (html, toc)
# ----------------------------------------------------------------------
_HEAD_TXT = re.compile(r"^#{1,6}\s+(.*)$")
_SLUG = {
    "源管家 使用方法": "top",
    "0. 第一次使用": "first",
    "常见问题": "faq",
    "备份文件一览": "backup",
    "Win7 版怎么来 / 怎么打": "win7",
}


def _slug(text, used):
    """生成稳定 id：预置映射优先，其次「场景 N」抽号，再用标题文本做语义 slug。

    语义 slug 只保留 ASCII 字母数字（中文标题会被自然过滤掉），故再带一个
    自增序号兜底，保证 id 既唯一又可读（如 scene-3-tab-2 / faq）。
    """
    key = text.strip()
    base = _SLUG.get(key)
    if base is None:
        m = re.match(r"^场景\s*([0-9]+[a-z]?)", key)
        if m:
            base = "scene-" + m.group(1)
        else:
            m2 = re.match(r"^(\d+)\.", key)
            if m2:
                base = "sec-" + m2.group(1)
            else:
                # 从标题里抽 ASCII 词做 slug（中文标题抽不到则留空）
                words = re.findall(r"[A-Za-z0-9]+", key)
                base = "-".join(w.lower() for w in words[:3])
                if not base:
                    base = "sec"
    sid = base
    i = 2
    while sid in used:
        sid = "%s-%d" % (base, i)
        i += 1
    used.add(sid)
    return sid


def parse(md):
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, toc = [], []
    used = set()
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()

        # --- 代码围栏 ---
        if s.startswith("```"):
            lang = s[3:].strip()
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = ' class="lang-%s"' % lang if lang else ""
            out.append("<pre%s><code>%s</code></pre>"
                       % (cls, _html.escape("\n".join(buf), quote=False)))
            continue

        # --- 表格 ---
        if s.startswith("|") and i + 1 < n and _is_table_sep(lines[i + 1]):
            rows = [lines[i], lines[i + 1]]
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_render_table(rows))
            continue

        # --- 标题 ---
        m = _HEAD_TXT.match(s)
        if m:
            text = m.group(1).strip()
            lvl = len(s) - len(s.lstrip("#"))
            sid = _slug(text, used)
            if lvl == 1:
                out.append('<h1 id="%s">%s</h1>'
                           % (_SLUG.get(text.strip(), "top"), _inline(text)))
            elif lvl == 2:
                out.append('<h2 id="%s">%s</h2>' % (sid, _inline(text)))
                toc.append(("1", sid, text))
            elif lvl == 3:
                out.append('<h3 id="%s">%s</h3>' % (sid, _inline(text)))
                toc.append(("2", sid, text))
            else:
                out.append('<h4 id="%s">%s</h4>' % (sid, _inline(text)))
                toc.append(("2", sid, text))
            i += 1
            continue

        # --- 分隔线 ---
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", s):
            out.append("<hr>")
            i += 1
            continue

        # --- 引用块（连续 > 行合并为一个 blockquote）---
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            # 引用块内部的空行 -> 分段
            paras, cur = [], []
            for b in buf:
                if b == "":
                    if cur:
                        paras.append(" ".join(cur))
                        cur = []
                else:
                    cur.append(b)
            if cur:
                paras.append(" ".join(cur))
            out.append("<blockquote>" + "".join("<p>%s</p>" % _inline(p) for p in paras)
                       + "</blockquote>")
            continue

        # --- 无序 / 有序列表 ---
        if re.match(r"^[-*]\s+", s) or re.match(r"^\d+\.\s+", s):
            ordered = bool(re.match(r"^\d+\.\s+", s))
            tag = "ol" if ordered else "ul"
            items = []
            while i < n:
                t = lines[i].strip()
                if re.match(r"^[-*]\s+", t) or re.match(r"^\d+\.\s+", t):
                    items.append(re.sub(r"^([-*]|\d+\.)\s+", "", t))
                    i += 1
                elif t == "":
                    # 空行后若仍是同类列表项则继续（宽松处理）
                    j = i + 1
                    while j < n and lines[j].strip() == "":
                        j += 1
                    nxt = lines[j].strip() if j < n else ""
                    same = (re.match(r"^[-*]\s+", nxt) if not ordered
                            else re.match(r"^\d+\.\s+", nxt))
                    if same:
                        i = j
                        continue
                    break
                else:
                    break
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % _inline(x) for x in items), tag))
            continue

        # --- 空行 ---
        if s == "":
            i += 1
            continue

        # --- 段落（连续非空行合并）---
        buf = [s]
        i += 1
        while i < n:
            t = lines[i].strip()
            if (t == "" or t.startswith("#") or t.startswith(">")
                    or t.startswith("|") or t.startswith("```")
                    or re.match(r"^[-*]\s+", t) or re.match(r"^\d+\.\s+", t)
                    or re.fullmatch(r"-{3,}", t)):
                break
            buf.append(t)
            i += 1
        out.append("<p>%s</p>" % _inline(" ".join(buf)))
    return "\n".join(out), toc


# ----------------------------------------------------------------------
# 4) 页面模板
# ----------------------------------------------------------------------
CSS = """
:root{
  --bg:#ffffff; --fg:#1f2328; --muted:#57606a; --line:#d8dee4;
  --card:#f6f8fa; --side:#f6f8fa; --link:#0969da; --accent:#3a82c7;
  --code-bg:#eff1f3; --code-fg:#b3402a; --quote-bg:#f6f8fa; --quote-line:#d0d7de;
  --th-bg:#f0f3f6;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#1c2128; --fg:#e6edf3; --muted:#9aa4b0; --line:#3a4048;
    --card:#22272e; --side:#22272e; --link:#6cb6ff; --accent:#3a82c7;
    --code-bg:#2d333b; --code-fg:#ffab70; --quote-bg:#22272e; --quote-line:#3a4048;
    --th-bg:#2d333b;
  }
}
*{box-sizing:border-box;}
html{scroll-behavior:smooth;}
body{
  margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.75 "Segoe UI","Microsoft YaHei",system-ui,-apple-system,sans-serif;
}
a{color:var(--link); text-decoration:none;}
a:hover{text-decoration:underline;}
code{
  font-family:"Cascadia Mono",Consolas,"Courier New",monospace; font-size:.9em;
  background:var(--code-bg); color:var(--code-fg); padding:.15em .4em; border-radius:4px;
}
pre{
  background:var(--code-bg); padding:12px 14px; border-radius:8px; overflow:auto;
  border:1px solid var(--line);
}
pre code{background:none; color:var(--fg); padding:0; font-size:.88em;}

/* ---------- 布局 ---------- */
.wrap{display:flex; align-items:flex-start;}
aside{
  position:sticky; top:0; flex:0 0 268px; height:100vh; overflow-y:auto;
  background:var(--side); border-right:1px solid var(--line); padding:20px 12px 32px;
}
aside .brand{
  font-weight:700; font-size:15px; padding:0 10px 12px; margin-bottom:8px;
  border-bottom:1px solid var(--line); color:var(--fg);
}
aside .brand small{display:block; font-weight:400; font-size:12px; color:var(--muted); margin-top:4px;}
aside nav a{
  display:block; padding:5px 10px; margin:1px 0; border-radius:6px;
  color:var(--muted); font-size:13.5px; border-left:2px solid transparent;
}
aside nav a:hover{background:var(--card); color:var(--fg); text-decoration:none;}
aside nav a.lv2{padding-left:26px; font-size:12.8px;}
aside nav a.active{color:var(--accent); border-left-color:var(--accent); background:var(--card); font-weight:600;}
main{flex:1 1 auto; min-width:0; padding:34px 46px 90px; max-width:1000px;}
h1{font-size:26px; margin:0 0 18px;}
h2{
  font-size:20px; margin:34px 0 14px; padding-bottom:8px; border-bottom:1px solid var(--line);
  scroll-margin-top:16px;
}
h3{font-size:16.5px; margin:24px 0 10px; scroll-margin-top:16px;}
h4{font-size:15px; margin:18px 0 8px;}
p{margin:10px 0;}
ul,ol{margin:10px 0; padding-left:26px;}
li{margin:4px 0;}
hr{border:0; border-top:1px solid var(--line); margin:26px 0;}
blockquote{
  margin:14px 0; padding:10px 14px; background:var(--quote-bg);
  border-left:3px solid var(--quote-line); border-radius:0 6px 6px 0; color:var(--muted);
}
blockquote p{margin:6px 0;}
.tw{overflow-x:auto; margin:12px 0;}
table{border-collapse:collapse; width:100%; font-size:13.5px;}
th,td{border:1px solid var(--line); padding:7px 10px; text-align:left; vertical-align:top;}
th{background:var(--th-bg); font-weight:600; white-space:nowrap;}
tbody tr:nth-child(even){background:var(--card);}

/* 顶部说明条 + 回顶 */
.top-note{
  font-size:12.5px; color:var(--muted); background:var(--card);
  border:1px solid var(--line); border-radius:8px; padding:8px 12px; margin-bottom:18px;
}
#gotop{
  position:fixed; right:22px; bottom:22px; width:42px; height:42px; border-radius:50%;
  background:var(--accent); color:#fff; border:0; cursor:pointer; font-size:18px;
  box-shadow:0 2px 10px rgba(0,0,0,.25); display:none;
}
#gotop:hover{filter:brightness(1.08);}

/* 窄屏：侧边栏变抽屉 */
#menu-btn{
  display:none; position:fixed; left:14px; top:14px; z-index:40; width:42px; height:42px;
  border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--fg);
  font-size:18px; cursor:pointer;
}
#mask{display:none; position:fixed; inset:0; background:rgba(0,0,0,.4); z-index:30;}
@media (max-width:900px){
  #menu-btn{display:block;}
  aside{
    position:fixed; left:0; top:0; z-index:35; transform:translateX(-100%);
    transition:transform .22s ease; box-shadow:0 0 24px rgba(0,0,0,.3);
  }
  body.nav-open aside{transform:translateX(0);}
  body.nav-open #mask{display:block;}
  main{padding:64px 18px 80px;}
}
"""

JS = """
(function(){
  var links = Array.prototype.slice.call(document.querySelectorAll('aside nav a'));
  var targets = links.map(function(a){
    return document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1)));
  });
  function setActive(idx){
    links.forEach(function(a,i){ a.classList.toggle('active', i===idx); });
  }
  // 滚动高亮：取「当前已越过顶端、且最靠上」的标题
  var ticking = false;
  function onScroll(){
    if(ticking) return;
    ticking = true;
    requestAnimationFrame(function(){
      var y = window.scrollY + 90, best = 0;
      for(var i=0;i<targets.length;i++){
        var t = targets[i];
        if(t && t.offsetTop <= y) best = i;
      }
      // 滚到底部时高亮最后一项
      if(window.innerHeight + window.scrollY >= document.body.scrollHeight - 4){
        best = targets.length - 1;
      }
      setActive(best);
      document.getElementById('gotop').style.display = window.scrollY > 400 ? 'block' : 'none';
      ticking = false;
    });
  }
  window.addEventListener('scroll', onScroll, {passive:true});
  window.addEventListener('resize', onScroll);
  onScroll();

  // 初始按 hash 定位
  if(location.hash){
    var el = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if(el){ el.scrollIntoView(); }
  }

  // 点击侧边栏：窄屏跳转后收起抽屉
  links.forEach(function(a){
    a.addEventListener('click', function(){
      document.body.classList.remove('nav-open');
    });
  });

  var mb = document.getElementById('menu-btn');
  if(mb){ mb.addEventListener('click', function(){ document.body.classList.toggle('nav-open'); }); }
  var mask = document.getElementById('mask');
  if(mask){ mask.addEventListener('click', function(){ document.body.classList.remove('nav-open'); }); }
  var gt = document.getElementById('gotop');
  if(gt){ gt.addEventListener('click', function(){ window.scrollTo({top:0, behavior:'smooth'}); }); }
})();
"""

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<button id="menu-btn" aria-label="目录">☰</button>
<div id="mask"></div>
<div class="wrap">
<aside>
  <div class="brand">{brand}<small>{ver}</small></div>
  <nav>
{nav}
  </nav>
</aside>
<main>
  <div class="top-note">{note}</div>
{body}
</main>
</div>
<button id="gotop" aria-label="回到顶部">↑</button>
<script>{js}</script>
</body>
</html>
"""


def build_nav(toc):
    rows = []
    for lvl, sid, text in toc:
        cls = ' class="lv%s"' % lvl if lvl != "1" else ""
        rows.append('    <a href="#%s"%s>%s</a>' % (sid, cls, _html.escape(text, quote=False)))
    return "\n".join(rows)


def convert(md_text, title="源管家 使用方法", version=""):
    body, toc = parse(md_text)
    note = ("本页由 <code>使用方法.md</code> 自动生成%s —— 内容与文档源保持一致；"
            "侧边栏可直接跳转章节。") % (("（%s）" % version) if version else "")
    if version:
        note = ('本页由 <code>使用方法.md</code> 自动生成 · %s —— 侧边栏可直接跳转章节。'
                % version)
    nav = build_nav(toc)
    return PAGE.format(
        title=_html.escape(title, quote=False),
        css=CSS, js=JS, nav=nav, body=body, note=note,
        brand=_html.escape(title, quote=False),
        ver=_html.escape(version or "", quote=False),
    ), toc


def _read_version():
    try:
        src = open(os.path.join(ROOT, "injector.py"), encoding="utf-8").read()
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src)
        return ("v" + m.group(1)) if m else ""
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(description="使用方法.md -> 使用方法.html（带侧边栏书签）")
    ap.add_argument("--in", dest="src", default=os.path.join(ROOT, "使用方法.md"))
    ap.add_argument("--out", dest="dst", default=os.path.join(ROOT, "使用方法.html"))
    ap.add_argument("--title", default="源管家 使用方法")
    ap.add_argument("--check", action="store_true", help="只自检，不写文件")
    args = ap.parse_args()

    if not os.path.isfile(args.src):
        print("!! 找不到源文件：%s" % args.src)
        return 2
    md = open(args.src, encoding="utf-8").read()
    ver = _read_version()
    page, toc = convert(md, args.title, ver)

    # ---- 自检：锚点 id 唯一 + 侧边栏链接都能命中 ----
    ids = re.findall(r'<h[1-4] id="([^"]+)"', page)
    if len(ids) != len(set(ids)):
        print("!! 锚点 id 重复：%s" % [x for x in ids if ids.count(x) > 1])
        return 1
    hrefs = re.findall(r'<a href="#([^"]+)"', page)
    missing = [h for h in hrefs if h not in ids]
    if missing:
        print("!! 侧边栏链接找不到目标锚点：%s" % missing)
        return 1

    if args.check:
        print("✓ 校验通过：H2/H3 目录项 %d 个（一级 %d / 二级 %d），锚点 id %d 个，全部命中"
              % (len(toc), sum(1 for l, _s, _t in toc if l == "1"),
                 sum(1 for l, _s, _t in toc if l == "2"), len(ids)))
        return 0

    with open(args.dst, "w", encoding="utf-8") as f:
        f.write(page)
    print("✓ 已生成 %s（%d 字节）" % (os.path.basename(args.dst), len(page.encode("utf-8"))))
    print("  目录项 %d 个，锚点 %d 个，版本 %s" % (len(toc), len(ids), ver or "(未取到)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
