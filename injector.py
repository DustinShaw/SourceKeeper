# -*- coding: utf-8 -*-
"""
源管家 —— 绿色 exe 工具（Qt / PySide6 版，带 CLI 模式）
=============================================================
TVBox / 影视仓 / FongMi TV 等支持 py 接口 APP 的「全源」配置管理器。
用途：把新的 spider 源（.py / .js / .jar / csp_）与直连 CMS 源（type:1）
统一登记、编辑、查重、测活进 py.json 的 sites 数组，
免去手工拼 key / name / api、手改 JSONC 的麻烦。本软件由 AI 辅助生成。

特点：
  - 单文件 exe，免安装、免 Python 环境（PyInstaller --onefile 打包）
  - 不执行任何 .py 代码，仅当文本解析，安全
  - 手术式插入 sites 数组，完整保留原 py.json 的 // 注释与排版
  - 注入前自动时间戳备份 py.json
  - 支持多选 / 扫描 py/ 目录批量注入、查重、校验 class Spider
  - 双模式：
      * 双击运行（无参数）-> 图形界面
      * 命令行（带 --inject/--scan 等参数）-> 无界面批处理，可在脚本中使用

仅在 Windows 下以 exe 形式交付；源码也可 `python injector.py` 直接跑。
"""

import os
import re
import sys
import json
import shutil
import socket
import ssl
import urllib.request
import urllib.error
from datetime import datetime

# 版本号：常规写作「发布日期+时间」YYMMDDHHMM（build.py 会核对日期部分=今天）；
# 临时节假日版可直接写标记串（如“2026 国庆特别版”），build.py 检测到非 10 位数字
# 会自动跳过日期核对并给出提示。恢复常规发版时改回 YYMMDDHHMM 即可。
APP_VERSION = "2610042023"   # YYMMDDHHMM（build 核对前 6 位=今天；exe 名「源管家 v<版本>.exe」）
APP_NAME = "源管家"             # 应用名（窗口标题基础名；版本号移入「关于」）
APP_TITLE = APP_NAME            # 主窗口标题基础名（实际标题 = 仓库路径 — 源管家）
APP_TITLE_SUFFIX = "%s v%s" % (APP_NAME, APP_VERSION)   # 窗体标题统一后缀（所有标题栏都标注版本）


def tagged_title(text=""):
    """把任意标题补成「<text> — 源管家 v<版本>」；text 为空时只返回后缀本身。

    幂等：标题里已含后缀则原样返回（全局兜底过滤器会二次调用它）。
    所有 setWindowTitle 都应经此函数，保证每个窗体的标题栏都明确标注当前版本。
    """
    head = str(text or "").strip()
    if not head:
        return APP_TITLE_SUFFIX
    if APP_TITLE_SUFFIX in head:
        return head
    return "%s — %s" % (head, APP_TITLE_SUFFIX)


def _tag_window_title(win):
    """给单个窗体补上版本标识（幂等，供全局兜底过滤器逐窗口调用）。"""
    try:
        if not hasattr(win, "windowTitle") or not win.isWindow():
            return
        cur = win.windowTitle()
        if cur and tagged_title(cur) != cur:
            win.setWindowTitle(tagged_title(cur))
    except Exception:
        pass

IS_DARK = False  # 由 run_gui 按系统主题赋值；供内联样式（表格/空状态/状态标签）选择配色

# 全局主题：按钮主次危险三级 + 输入框 + 分组框（浅色、统一圆角与悬停态）
APP_QSS = """
QPushButton { background:#ffffff; border:1px solid #cfd8e3; border-radius:6px;
  padding:5px 14px; color:#2c3e50; }
QPushButton:hover { border-color:#4a6fa5; color:#34538a; background:#f7fafd; }
QPushButton:pressed { background:#eef4fb; }
QPushButton:disabled { color:#9aa7b5; border-color:#e3e8ef; background:#f7f9fb; }
QPushButton[accent="primary"] { background:#3a82c7; border:1px solid #3a82c7;
  color:#ffffff; font-weight:bold; }
QPushButton[accent="primary"]:hover { background:#4f9ad8; border-color:#4f9ad8; }
QPushButton[accent="primary"]:pressed { background:#2e6ba8; }
QPushButton[accent="primary"]:disabled { background:#a9bdd6; border-color:#a9bdd6; color:#f0f4f9; }
QPushButton[accent="danger"] { color:#c0392b; border-color:#e0b4ae; }
QPushButton[accent="danger"]:hover { background:#fdf0ee; border-color:#d98880; }
QPushButton[accent="danger"]:pressed { background:#f9dcd8; }
QPushButton[accent="danger"]:disabled { color:#c9b6b2; border-color:#e9dcda; background:#faf7f6; }
QLineEdit { border:1px solid #cfd8e3; border-radius:6px; padding:4px 8px; background:#ffffff; }
QLineEdit:focus { border-color:#4a6fa5; }
QGroupBox { font-weight:bold; color:#2c3e50; border:1px solid #e3e8ef;
  border-radius:6px; margin-top:10px; padding-top:6px; }
QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 4px; color:#34538a; }
QListWidget, QPlainTextEdit { border:1px solid #e3e8ef; border-radius:6px; }
"""

# 深色主题样式（跟随系统；浅色沿用上方 APP_QSS）。与 APP_QSS 结构一一对应。
APP_QSS_DARK = """
QPushButton { background:#2b2f36; border:1px solid #3c424b; border-radius:6px;
  padding:5px 14px; color:#e6e9ed; }
QPushButton:hover { border-color:#5b8fd6; color:#cfe0f5; background:#333a44; }
QPushButton:pressed { background:#262b32; }
QPushButton:disabled { color:#6b7280; border-color:#2f343c; background:#23272e; }
QPushButton[accent="primary"] { background:#3a82c7; border:1px solid #3a82c7;
  color:#ffffff; font-weight:bold; }
QPushButton[accent="primary"]:hover { background:#5aa5e0; border-color:#5aa5e0; }
QPushButton[accent="primary"]:pressed { background:#2e6ba8; }
QPushButton[accent="primary"]:disabled { background:#36506b; border-color:#36506b; color:#c8d4e0; }
QPushButton[accent="danger"] { color:#ff8a7a; border-color:#5a3a36; }
QPushButton[accent="danger"]:hover { background:#3a2724; border-color:#7a4a44; }
QPushButton[accent="danger"]:pressed { background:#33211e; }
QPushButton[accent="danger"]:disabled { color:#7a5a55; border-color:#33302f; background:#262322; }
QLineEdit { border:1px solid #3c424b; border-radius:6px; padding:4px 8px; background:#1f2329; color:#e6e9ed; }
QLineEdit:focus { border-color:#5b8fd6; }
QGroupBox { font-weight:bold; color:#cdd3da; border:1px solid #3c424b;
  border-radius:6px; margin-top:10px; padding-top:6px; }
QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 4px; color:#7fb0e0; }
QListWidget, QPlainTextEdit { border:1px solid #3c424b; border-radius:6px; background:#1f2329; color:#e6e9ed; }
"""


# ----------------------------------------------------------------------------
# 核心逻辑层（pyinj_core）：纯逻辑已拆分至独立模块，此处 re-export 保持兼容
# ----------------------------------------------------------------------------
from pyinj_core import *  # noqa: F401,F403
import pyinj_core as _core
globals().update({n: getattr(_core, n) for n in dir(_core)
                  if n.startswith("_") and not n.startswith("__")})

# ----------------------------------------------------------------------------
# 新增工具模块（全部零 Qt 纯逻辑，"以新增模块方式"扩展，不改动 pyinj_core）：
#   pyinj_sections : lives/parses 数组管理 + sites/分区拖拽排序
#   pyinj_kw       : 外置词库加载（敏感词库 / 需特殊上网域名库）+ 分类识别
#   pyinj_speed    : 延迟采样 + 前 N 字节真实下载判活的测速
#   pyinj_netdiag  : DNS / 超时-拒绝区分 / 代理域名库命中的网络诊断
#   pyinj_jar      : jar 型 spider 源的远程 jar 健康体检
#   pyinj_playlist : TXT ↔ M3U 直播源列表互转
#   pyinj_report   : 汇总测速/诊断/分类/JAR 的诊断报告导出（MD/CSV）
# ----------------------------------------------------------------------------
import pyinj_sections  # noqa: F401
import pyinj_kw        # noqa: F401
import pyinj_speed     # noqa: F401
import pyinj_netdiag   # noqa: F401
import pyinj_jar       # noqa: F401
import pyinj_playlist  # noqa: F401
import pyinj_report    # noqa: F401



# ----------------------------------------------------------------------------
# UTF-8 安全输出（CLI）
#   应用名、版本号、日志里大量使用中文与 ✓/⚠/┃ 等符号，而 Windows 控制台默认
#   GBK：① 部分符号 GBK 不可编码 → UnicodeEncodeError 崩溃；② GBK 字节写进
#   UTF-8 代码页的控制台 → 乱码。这里统一：切 65001 代码页 + 把 stdout/stderr
#   换成始终输出 UTF-8 字节的包装器（连 argparse 自己打印的信息也一并覆盖）。
#   包装器保留 .buffer 指向原始二进制流，pyinj_core 的 `sys.stdout.buffer.write`
#   写法仍然可用。
# ----------------------------------------------------------------------------
class _Utf8Writer(object):
    """始终以 UTF-8 输出。
    · 底层有二进制 buffer（真实控制台/管道）→ encode 成 UTF-8 字节写入；
    · 底层是纯文本流（如测试用 StringIO 捕获）→ 原样写 str，保证文本捕获可用。
    这样 argparse 自己打印的信息也一并被覆盖，不会被 GBK 偷偷写出去。"""

    def __init__(self, stream):
        raw = getattr(stream, "buffer", None)
        if raw is not None:
            self._raw, self._bytes_mode = raw, True
            self.buffer = raw           # 兼容 pyinj_core 的 sys.stdout.buffer.write
        else:
            self._raw, self._bytes_mode = stream, False
            self.buffer = None

    def write(self, s):
        try:
            if self._bytes_mode and isinstance(s, str):
                self._raw.write(s.encode("utf-8"))
            else:
                self._raw.write(s)
            self._raw.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self._raw.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def fileno(self):
        try:
            return self._raw.fileno()
        except Exception:
            return 0

    @property
    def encoding(self):
        return "utf-8"


def _ensure_utf8_stdio():
    """幂等（按「是否已包装该流」判定，不依赖全局一次性开关）：
    控制台切 UTF-8 代码页 + stdout/stderr 换 UTF-8 写入器。
    之所以按流判定而不是只做一次：测试会用 redirect_stdout(StringIO) 捕获输出，
    流每次都可能不同，一次性开关会把某个临时流永久锁住。"""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for name in ("stdout", "stderr"):
        st = getattr(sys, name, None)
        if st is None or isinstance(st, _Utf8Writer):
            continue
        try:
            setattr(sys, name, _Utf8Writer(st))
        except Exception:
            pass


_STDIO_UTF8_READY = False   # 保留：兼容外部可能的引用；实际幂等由 isinstance 判定


# ----------------------------------------------------------------------------
# CLI 模式（无界面，不依赖 Qt）
# ----------------------------------------------------------------------------
def run_cli(argv):
    import argparse

    _ensure_utf8_stdio()

    # 安全输出（在 _Utf8Writer 之上再包一层异常处理，避免任何情况下崩进程）
    def _emit(*args, **kw):
        sep = kw.get("sep", " ")
        end = kw.get("end", "\n")
        s = sep.join(str(a) for a in args) + end
        try:
            buf = sys.stdout.buffer
            buf.write(s.encode("utf-8"))
            buf.flush()
        except Exception:
            try:
                sys.stdout.write(s)
            except Exception:
                pass

    print = _emit  # 函数内遮蔽内置 print

    p = argparse.ArgumentParser(
        prog="源管家",
        description="TVBox / 影视仓 全源管理器（无界面模式）：管理配置 sites 数组里的 "
                    "Spider 脚本源与直连 CMS 源。",
    )
    p.add_argument("--repo", default=get_app_dir(), help="仓库根目录（含 spider 配置 json），默认 exe 所在目录")
    p.add_argument("--inject", nargs="+", metavar="FILE", help="要注入的 .py 文件（可多个）")
    p.add_argument("--add-cms", nargs="+", metavar="URL", dest="add_cms",
                   help="添加直连 CMS 源（type:1）：粘贴一个或多个 API 地址（http/https）")
    p.add_argument("--scan", action="store_true", help="扫描 repo/py 目录下未注册的 .py")
    p.add_argument("--no-copy", action="store_true", help="仓库外的 .py 不复制到 py/ 目录")
    p.add_argument("--type", type=int, default=3, help="站点 type，默认 3")
    p.add_argument("--no-filter", action="store_true", help="filterable=0")
    p.add_argument("--no-quick", action="store_true", help="quickSearch=0")
    p.add_argument("--no-search", action="store_true", help="searchable=0")
    p.add_argument("--list", action="store_true", help="查看所有已注册站点")
    p.add_argument("--check", action="store_true", help="查重（重复 key / api）")
    p.add_argument("--dedup", action="store_true", help="去重：按 key/api 保留首个、删除重复项")
    p.add_argument("--adult-scan", action="store_true", help="自动检测各站点 .py 内容，为涉及成人内容的站点标注 adult=1")
    p.add_argument("--duanju-scan", action="store_true", help="检测短剧类站点（读 .py 内容+站点名）；配合 --write 批量注释禁用")
    p.add_argument("--live-scan", action="store_true", help="检测直播类站点（读 .py 内容+站点名）；配合 --write 批量注释禁用")
    p.add_argument("--check-url", action="store_true", help="检测各站点 .py 中的源地址 URL 是否可达（多种方法，任一可达即有效）")
    p.add_argument("--probe", action="store_true",
                   help="源测活：按 type 路由（直连 CMS 走 HTTP 取分类栏；spider 加载 .py 取 homeContent 分类栏 → 首页影片），判定死源/活源")
    p.add_argument("--disable", dest="disable_keys", nargs="+", metavar="KEY", help="禁用指定 key 的站点（注释掉对应配置，立即写入；需 --write）")
    p.add_argument("--enable", dest="enable_keys", nargs="+", metavar="KEY", help="启用指定 key 的站点（取消注释，立即写入；需 --write）")
    p.add_argument("--del", dest="del_keys", nargs="+", metavar="KEY", help="删除指定 key 的站点（可多个）")
    p.add_argument("--keep-py", dest="keep_py", action="store_true",
                   help="与 --del 连用：只删配置项、保留对应 .py 文件（默认连 .py 一起删，备份到 py_trash/）")
    p.add_argument("--set", dest="set_specs", nargs="+", metavar="KEY.FIELD=VALUE",
                   help="修改站点字段，如 py_x.name=新名 / py_x.type=4，可多个")
    p.add_argument("--write", action="store_true", help="真正写入配置文件；不加则只预览")
    p.add_argument("--config", metavar="NAME", default=None,
                   help="指定配置文件名（默认 py.json；未指定且 py.json 不存在时自动识别含 sites 数组的 *.json）")
    args = p.parse_args(argv)

    repo = os.path.abspath(args.repo)
    cfg_name = guess_config_file(repo, args.config)
    if cfg_name is None:
        print("错误：未找到可用配置文件（%s）。可用 --config 指定文件名。" % repo)
        return 2
    base_dir = cfg_base_dir(repo, cfg_name)  # api / py 目录相对它解析
    try:
        raw, sites, eks, eas = load_repo(repo, cfg_name)
    except FileNotFoundError as e:
        print("错误：%s" % e)
        return 2
    except Exception as e:
        print("错误：配置文件 %s 解析失败：%s" % (cfg_name, e))
        return 2

    print("仓库：%s" % repo)
    print("配置文件：%s" % cfg_name)
    print("现有站点：%d 个" % len(sites))

    # ---- ① 查看配置 ----
    if args.list:
        print("\n已注册站点（共 %d 个）：" % len(sites))
        for obj, dis in parse_sites_with_disabled(raw):
            tag = " [禁用]" if dis else ""
            print("  %-18s %-22s %-28s type=%s%s" % (
                obj.get("key", ""), obj.get("name", ""), obj.get("api", ""),
                obj.get("type", ""), tag))
        return 0

    # ---- ② 查重 ----
    if args.check:
        reps = check_duplicates(sites)
        if reps:
            print("\n发现重复项 %d 个：" % len(reps))
            for r in reps:
                print("  ⚠ " + r)
        else:
            print("\n未发现重复 key / api。")
        return 0

    # ---- ②b 去重 ----
    if args.dedup:
        new_text, removed = deduplicate_sites(raw)
        if not removed:
            print("\n未发现重复项，无需去重。")
            return 0
        print("\n将删除 %d 个重复条目（保留首个）：" % len(removed))
        for key, name, reason in removed:
            print("  删除  key=%s  (name=%s)  [%s]" % (key, name, reason))
        if not args.write:
            print("\n[预览模式] 未修改文件。加 --write 才真正写入 py.json。")
            return 0
        bak = backup_and_write(repo, new_text, cfg_name)
        print("\n已备份：%s" % os.path.basename(bak))
        print("已删除 %d 个重复条目。" % len(removed))
        return 0

    # ---- ②c 成人内容自动检测标注 ----
    if args.adult_scan:
        new_text = raw
        marked = []
        # .py 找不到时自动遍历 exe/配置/仓库目录找回（应对 py 文件夹被改名/移动）
        _roots = default_search_roots(repo, cfg_name)
        _name_map = discover_py_files(_roots) if _roots else {}
        for e in sites:
            key = e.get("key")
            if not key:
                continue
            py, _by_search = resolve_spider_path_resilient(base_dir, e.get("api", ""), repo, _name_map)
            if not os.path.isfile(py):
                is_ad, kw = detect_adult("", e.get("name", ""),
                                         extra_text=entry_extra_text(e))  # 退化为站点名+ext
            else:
                is_ad, kw = detect_adult(py, e.get("name", ""),
                                         extra_text=entry_extra_text(e))
                if _by_search:
                    print("  (自动遍历找到 .py：%s)" % py)
            if not is_ad:
                continue
            # 已有 adult=1 的跳过（保持），否则标注
            try:
                fv = int(e.get("adult", 0) or 0)
            except Exception:
                fv = 0
            if fv == 1:
                continue
            try:
                new_text, _ = update_site(new_text, key, "adult", 1)
                marked.append((key, e.get("name", ""), kw))
            except ValueError as ex:
                print("✗ " + str(ex))
        if not marked:
            print("\n未检测到成人内容站点（或均已标注）。")
            return 0
        print("\n检测到 %d 个成人内容站点（将标注 adult=1）：" % len(marked))
        for key, name, kw in marked:
            print("  %s (%s)  [命中: %s]" % (key, name, kw))
        if not args.write:
            print("\n[预览模式] 未修改文件。加 --write 才真正写入 py.json。")
            return 0
        bak = backup_and_write(repo, new_text, cfg_name)
        print("\n已备份：%s" % os.path.basename(bak))
        print("已标注 %d 个成人站点。" % len(marked))
        return 0

    # ---- ②c1 直播类站点检测（--write 时批量注释禁用）----
    if args.live_scan:
        # .py 找不到时自动遍历 exe/配置/仓库目录找回（应对 py 文件夹被改名/移动）
        _roots = default_search_roots(repo, cfg_name)
        _name_map = discover_py_files(_roots) if _roots else {}
        found = []
        for e in sites:
            key = e.get("key")
            if not key:
                continue
            py, _by_search = resolve_spider_path_resilient(base_dir, e.get("api", ""), repo, _name_map)
            if not os.path.isfile(py):
                is_lv, kw = detect_live("", e.get("name", ""))  # 退化为仅按站点名
            else:
                is_lv, kw = detect_live(py, e.get("name", ""))
            if is_lv:
                found.append((key, e.get("name", ""), kw))
        if not found:
            print("\n未检测到直播类站点。")
            return 0
        print("\n检测到 %d 个直播类站点：" % len(found))
        for key, name, kw in found:
            print("  %s (%s)  [命中: %s]" % (key, name, kw))
        if not args.write:
            print("\n[预览模式] 未修改文件。加 --write 将批量注释禁用以上站点。")
            return 0
        new_text = raw
        done, failed = [], []
        for key, _name, _kw in found:
            new_text, f = disable_site(new_text, key)
            (done if f else failed).append(key)
        if not done:
            print("\n未找到任何可禁用的直播站点（可能均已禁用）。")
            return 0
        bak = backup_and_write(repo, new_text, cfg_name)
        print("\n已备份：%s" % os.path.basename(bak))
        print("已禁用 %d 个直播类站点（注释掉配置，可逆）。" % len(done))
        if failed:
            print("⚠ 未找到：%s" % "、".join(failed))
        return 0

    # ---- ②c2 短剧类站点检测（--write 时批量注释禁用）----
    if args.duanju_scan:
        # .py 找不到时自动遍历 exe/配置/仓库目录找回（应对 py 文件夹被改名/移动）
        _roots = default_search_roots(repo, cfg_name)
        _name_map = discover_py_files(_roots) if _roots else {}
        found = []
        for e in sites:
            key = e.get("key")
            if not key:
                continue
            py, _by_search = resolve_spider_path_resilient(base_dir, e.get("api", ""), repo, _name_map)
            if not os.path.isfile(py):
                is_dj, kw = detect_duanju("", e.get("name", ""))  # 退化为仅按站点名
            else:
                is_dj, kw = detect_duanju(py, e.get("name", ""))
            if is_dj:
                found.append((key, e.get("name", ""), kw))
        if not found:
            print("\n未检测到短剧类站点。")
            return 0
        print("\n检测到 %d 个短剧类站点：" % len(found))
        for key, name, kw in found:
            print("  %s (%s)  [命中: %s]" % (key, name, kw))
        if not args.write:
            print("\n[预览模式] 未修改文件。加 --write 将批量注释禁用以上站点。")
            return 0
        new_text = raw
        done, failed = [], []
        for key, _name, _kw in found:
            new_text, f = disable_site(new_text, key)
            (done if f else failed).append(key)
        if not done:
            print("\n未找到任何可禁用的短剧站点（可能均已禁用）。")
            return 0
        bak = backup_and_write(repo, new_text, cfg_name)
        print("\n已备份：%s" % os.path.basename(bak))
        print("已禁用 %d 个短剧类站点（注释掉配置，可逆）。" % len(done))
        if failed:
            print("⚠ 未找到：%s" % "、".join(failed))
        return 0

    # ---- ②d URL 源地址可达性检测（按 type 路由：直连/远程走 HTTP，spider 抽 .py 内 URL）----
    if args.check_url:
        print("\nURL 源地址可达性检测（共 %d 个站点）：" % len(sites))
        any_unreach = False
        for e in sites:
            key = e.get("key")
            if not key:
                continue
            r = check_source_reachability(e, base_dir=base_dir)
            if r.get("reachable") is True:
                print("  ✓ %-18s 可达 (%s)  %s" % (key, r.get("method", ""),
                                                  (r.get("urls") or [""])[0]))
            elif r.get("reachable") is False:
                any_unreach = True
                print("  ✗ %-18s 不可达  %s" % (key, r.get("note", "")))
            else:
                print("  · %-18s %s" % (key, r.get("note", "")))
        print("\n检测完成。" + ("有不可达站点，可用 --disable KEY 注释禁用。" if any_unreach else ""))
        return 0

    # ---- ②d2 源测活（按 type 路由：直连 CMS 走 HTTP 取分类；spider 加载 .py）----
    if args.probe:
        print("\n源测活：按 type 路由（直连 CMS 取分类 / spider 加载 .py），共 %d 个站点" % len(sites))
        dead = []
        for e in sites:
            key = e.get("key")
            if not key:
                continue
            r, _is_py = probe_source(e, base_dir=base_dir, timeout=PROBE_TIMEOUT_DEFAULT,
                                   ext=e.get("ext"))
            lvl, verdict = source_verdict(r)
            if lvl == "ok":
                print("  ✓ %-18s 活源  分类 %d 个 | %s | 首页 %d 部"
                      % (key, len(r.get("classes") or []),
                         " · ".join((r.get("classes") or [])[:6]), r.get("videos", 0)))
            elif lvl == "bad":
                dead.append(key)
                print("  ✗ %-18s 死源  %s" % (key, "分类为空（影视仓里不会显示分类栏）"))
            elif lvl == "none":
                print("  ? %-18s %s" % (key, r.get("error") or "无资源"))
            else:
                dead.append(key)
                print("  ! %-18s 异常  %s" % (key, r.get("error", "")))
        print("\n测活完成。" + ("死源 %d 个，可用 --disable KEY 注释禁用：%s"
                                % (len(dead), " ".join(dead)) if dead else "未发现死源。"))
        return 0

    # ---- ②e 禁用 / 启用（注释掉 / 取消注释对应配置）----
    if args.disable_keys:
        new_text = raw
        done = []
        for k in args.disable_keys:
            new_text, found = disable_site(new_text, k)
            if found:
                done.append(k)
            else:
                print("✗ 未找到 key=%s（可能已禁用或不存在）" % k)
        if not done:
            return 0
        if not args.write:
            print("\n[预览模式] 将禁用 %d 个站点。加 --write 才真正写入。" % len(done))
            return 0
        bak = backup_and_write(repo, new_text, cfg_name)
        print("\n已备份：%s" % os.path.basename(bak))
        print("已禁用 %d 个站点：%s" % (len(done), ", ".join(done)))
        return 0

    if args.enable_keys:
        new_text = raw
        done = []
        for k in args.enable_keys:
            new_text, found = enable_site(new_text, k)
            if found:
                done.append(k)
            else:
                print("✗ 未找到被禁用的 key=%s" % k)
        if not done:
            return 0
        if not args.write:
            print("\n[预览模式] 将启用 %d 个站点。加 --write 才真正写入。" % len(done))
            return 0
        bak = backup_and_write(repo, new_text, cfg_name)
        print("\n已备份：%s" % os.path.basename(bak))
        print("已启用 %d 个站点：%s" % (len(done), ", ".join(done)))
        return 0

    # ---- ③ 删除 / 修改 ----
    if args.del_keys or args.set_specs:
        new_text = raw
        changed = []
        del_objs = []  # 被删站点的完整 dict（含 api），用于后续删除对应 .py
        if args.del_keys:
            for k in args.del_keys:
                try:
                    new_text, obj = delete_site(new_text, k)
                    changed.append(("del", k, obj))
                    del_objs.append(obj)
                except ValueError as e:
                    print("✗ " + str(e))
        if args.set_specs:
            for spec in args.set_specs:
                try:
                    key_field, value = spec.rsplit("=", 1)
                    key, field = key_field.rsplit(".", 1)
                    if field in _INT_FIELDS:
                        value = int(value)
                    new_text, obj = update_site(new_text, key, field, value)
                    changed.append(("set", key, (field, value)))
                except ValueError as e:
                    print("✗ 解析失败 %s：%s" % (spec, e))
        try:
            parse_jsonc(new_text)
        except Exception as e:
            print("✗ 操作后配置不合法，已放弃：%s" % e)
            return 2
        if not changed:
            print("没有执行任何变更。")
            return 0
        # 计算删除配置项对应的 .py（仍有其它站点引用同一 .py 则跳过；
        # 加 --keep-py 则只删配置项、保留 .py，方便将来再次添加）
        removed_keys_set = {str(o.get("key", "")) for o in del_objs}
        remaining = [s for s in sites if str(s.get("key", "")) not in removed_keys_set]
        key_api = {str(o.get("key", "")): o.get("api", "") for o in del_objs}
        if getattr(args, "keep_py", False):
            py_plan, py_skip = [], []
        else:
            py_plan, py_skip = collect_orphan_py(base_dir, removed_keys_set, key_api, remaining, repo,
                                                default_search_roots(repo, cfg_name))

        print("\n将执行 %d 项变更：" % len(changed))
        for act, k, info in changed:
            if act == "del":
                p = resolve_spider_path(base_dir, key_api.get(k, ""), repo)
                tag = ("（对应 .py：%s）" % p) if p else ""
                print("  删除  key=%s  (name=%s)%s" % (k, info.get("name", ""), tag))
            else:
                print("  修改  key=%s  %s=%s" % (k, info[0], info[1]))
        if py_plan:
            print("  其中 %d 个对应 .py 将一并删除（删除前备份到 py_trash/）：" % len(py_plan))
            for p in py_plan:
                print("    - %s" % p)
        for p, r in py_skip:
            print("  ⚠ .py 跳过删除：%s（%s）" % (p, r))
        if not args.write:
            print("\n[预览模式] 未修改文件。加 --write 才真正写入 py.json。")
            return 0
        bak = backup_and_write(repo, new_text, cfg_name)
        print("\n已备份：%s" % os.path.basename(bak))
        print("已完成 %d 项配置变更。" % len(changed))
        n = 0
        for p in py_plan:
            if trash_spider(base_dir, p):
                n += 1
                print("  已删除 .py（备份 py_trash）：%s" % p)
        if n:
            print("已删除 %d 个对应 .py。" % n)
        return 0

    entries, logs = [], []
    if args.scan:
        e1, l1 = collect_from_scan(base_dir, eks, eas)
        entries += e1
        logs += l1
        # 反向校验：已注册配置项对应的 .py 是否还在磁盘上
        missing, relocated = check_missing_py_resilient(base_dir, sites, repo, cfg_name)
        for key, api, p in relocated:
            logs.append(("warn", "提示：%s 的 .py 原路径失效，已在别处找回：%s" % (key, p)))
        for key, api in missing:
            logs.append(("err", "缺失 .py：%s（%s）对应文件不存在" % (key, api)))
        if not missing and not relocated:
            logs.append(("ok", "已注册 %d 个站点的 .py 文件均存在。" % len(sites)))
    if args.inject:
        e2, l2 = collect_from_files(args.inject, base_dir, not args.no_copy, eks, eas)
        entries += e2
        logs += l2
    if getattr(args, "add_cms", None):
        for url in args.add_cms:
            url = (url or "").strip()
            if not url:
                continue
            try:
                e = make_entry_from_api(url, type_hint=1)
            except Exception as ex:
                logs.append(("err", "无法生成直连源（%s）：%s" % (url, ex)))
                continue
            if e["key"] in eks or e["api"].rstrip("/") in {a.rstrip("/") for a in eas}:
                logs.append(("warn", "已存在，跳过：%s（%s）" % (e["name"], e["api"])))
                continue
            entries.append(e)
            logs.append(("info", "已加入直连源：%s（%s）" % (e["name"], e["api"])))

    for lv, m in logs:
        print(LEVEL_TAG.get(lv, "· ") + m)

    if not entries:
        print("没有可注入的新条目。")
        return 0

    print("\n待注入 %d 个站点：" % len(entries))
    for e in entries:
        print("  %-20s %-16s %s" % (e["name"][:20], e["key"][:16], e["api"]))

    if not args.write:
        print("\n[预览模式] 未修改文件。加 --write 才真正写入 py.json。")
        return 0

    switches = {
        "filterable": not args.no_filter,
        "quickSearch": not args.no_quick,
        "searchable": not args.no_search,
        "type": args.type,
    }
    bak = commit_write(repo, raw, entries, switches, cfg_name)
    print("\n已备份：%s" % os.path.basename(bak))
    print("已注入 %d 个站点。" % len(entries))
    return 0


# ----------------------------------------------------------------------------
# GUI 模式（懒加载 PySide6，仅图形界面路径才导入 Qt）
# ----------------------------------------------------------------------------
def run_gui():
    # --console 打包时双击会先弹一个控制台，GUI 模式下把它藏掉，保持界面干净
    try:
        if sys.platform == "win32":
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass

    # ---- Qt 绑定兼容层：默认 PySide6/Qt6；装不到时回退 PySide2/Qt5（Windows 7 版走这条）----
    # 两边都有的类直接共用导入；差异只有 QShortcut 的位置、app.exec() 的写法，
    # 以及 PySide2 没有 Q_ARG/Q_RETURN_ARG —— 跨线程传参一律走「无参槽 + 属性」
    # （见 _ask_user_dir / prompt_py_dir），三条差异均在下方兜住。
    try:
        from PySide6.QtWidgets import (
            QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
            QPushButton, QListWidget, QPlainTextEdit, QGroupBox, QCheckBox,
            QSpinBox, QFileDialog, QMessageBox, QDialog, QFormLayout,
            QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView,
            QTabWidget,
            QAbstractItemView, QProgressBar, QMenu, QFrame, QRadioButton,
            QInputDialog, QComboBox, QGridLayout, QSizePolicy,
        )
        from PySide6.QtGui import (QColor, QFont, QKeySequence, QShortcut,
                                   QDesktopServices)  # Qt6：QShortcut 已移入 QtGui
        # Q_ARG/Q_RETURN_ARG 不使用：Qt5/PySide2 没有这两个别名；跨线程传参走
        # 「无参槽 + 属性」（见 _ask_user_dir / prompt_py_dir）
        from PySide6.QtCore import (QThread, Signal, QMetaObject, Qt,
                                    Slot, QItemSelectionModel,
                                    QTimer, QSettings, QEvent, QUrl)
        QT_BINDING = "PySide6"
    except ImportError:
        from PySide2.QtWidgets import (
            QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
            QPushButton, QListWidget, QPlainTextEdit, QGroupBox, QCheckBox,
            QSpinBox, QFileDialog, QMessageBox, QDialog, QFormLayout,
            QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView,
            QTabWidget,
            QAbstractItemView, QProgressBar, QMenu, QFrame, QRadioButton,
            QInputDialog, QComboBox, QGridLayout, QSizePolicy,
            QShortcut,          # Qt5：QShortcut 属于 QtWidgets
        )
        from PySide2.QtGui import (QColor, QFont, QKeySequence,
                                   QDesktopServices)
        from PySide2.QtCore import (QThread, Signal, QMetaObject, Qt,
                                    Slot, QItemSelectionModel,
                                    QTimer, QSettings, QEvent, QUrl)
        QT_BINDING = "PySide2"

    def _app_exec(app):
        """启动事件循环：Qt6/Qt5 都通过 app.exec() 退出；
        PySide2 只有 `exec_()`（Qt5 的 exec 是关键字所以改名）。

        ⚠️ 顺序不能反：PySide6 里 `exec_` 只是 `exec` 的弃用别名，
        若优先取 exec_，就会绕过测试对 `QApplication.exec` 的替换，
        跑成永不退出的真实事件循环（2026-09-26 因此挂住 test_gui_v13 两小时）。
        所以一律「先 exec，取不到再退回 exec_」。"""
        fn = getattr(app, "exec", None) or getattr(app, "exec_", None)
        if fn is None:
            raise AttributeError("当前绑定既没有 exec 也没有 exec_")
        return fn()

    # 提升为模块级，便于打包脚本 / 测试断言当前用的是哪套 Qt 绑定
    globals()["_app_exec"] = _app_exec
    globals()["QT_BINDING"] = QT_BINDING

    def _system_is_dark():
        # 跟随系统深浅色：优先 Qt6.5+ colorScheme，Windows 回落注册表 AppsUseLightTheme
        try:
            sh = QApplication.instance().styleHints()
            cs = sh.colorScheme()
            if cs == Qt.ColorScheme.Dark:
                return True
            if cs == Qt.ColorScheme.Light:
                return False
        except Exception:
            pass
        try:
            if sys.platform == "win32":
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0:
                    return True
        except Exception:
            pass
        return False

    def _apply_dark_palette(app):
        from PySide6.QtGui import QPalette, QColor
        p = QPalette()
        p.setColor(QPalette.Window, QColor("#1e2228"))
        p.setColor(QPalette.WindowText, QColor("#e6e9ed"))
        p.setColor(QPalette.Base, QColor("#1f2329"))
        p.setColor(QPalette.AlternateBase, QColor("#262b32"))
        p.setColor(QPalette.Text, QColor("#e6e9ed"))
        p.setColor(QPalette.Button, QColor("#2b2f36"))
        p.setColor(QPalette.ButtonText, QColor("#e6e9ed"))
        p.setColor(QPalette.Highlight, QColor("#34538a"))
        p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        app.setPalette(p)

    # ---- 成人/短剧内容检测后台线程：避免配置项多时读取 .py 阻塞界面造成假死 ----
    class _AdultScanWorker(QThread):
        progress = Signal(int, int, str)       # 已完成数, 总数, 当前站点名（检测阶段）
        item_done = Signal(str, bool, object, bool, object, bool, object)  # key, 是否成人, 成人命中词, 是否短剧, 短剧命中词, 是否直播, 直播命中词
        finished_map = Signal(dict)            # 最终 detect_map: key -> (is_adult, adult_kw, is_dj, dj_kw)
        search_progress = Signal(int, int, str)  # 遍历搜索 .py 阶段进度（done, 0, dirname）

        def __init__(self, dialog, base_dir, entries, alt_dir=None, repo_dir=None,
                     cfg_name=None, allow_prompt=True, deep=False):
            super().__init__(dialog)
            self.dialog = dialog
            self.base_dir = base_dir
            self.entries = entries
            self.alt_dir = alt_dir
            self.repo_dir = repo_dir
            self.cfg_name = cfg_name
            self.allow_prompt = allow_prompt
            self.deep = bool(deep)   # 深度检测：对 http(s) 直连站拉取 api 内容补充判定
            self._resolved = {}  # key -> py_path
            self._name_map = {}  # 遍历搜索得到的 {小写文件名: 路径}

        def run(self):
            # 安全兜底：任何异常都不能让界面卡死在「检测中…」，
            # 出错时退化为仅按站点名判定并正常收尾。
            try:
                self._run_impl()
            except Exception:
                total = len(self.entries)
                m = {}
                for i, e in enumerate(self.entries):
                    _k = str(e.get("key", ""))
                    _x = entry_extra_text(e)
                    is_ad, kw = detect_adult("", e.get("name", ""), extra_text=_x)
                    is_dj, dkw = detect_duanju("", e.get("name", ""), extra_text=_x)
                    is_lv, lkw = detect_live("", e.get("name", ""), extra_text=_x)
                    m[_k] = (is_ad, kw, is_dj, dkw, is_lv, lkw)
                    self.item_done.emit(_k, is_ad, kw, is_dj, dkw, is_lv, lkw)
                    self.progress.emit(i + 1, total, e.get("name", ""))
                self.finished_map.emit(m)

        def _aborted(self):
            """成人检测：是否应中止（用户点了「停止」或对话框已关闭）。"""
            d = self.dialog
            return bool(d) and (getattr(d, "_adult_stop", False)
                                or getattr(d, "_closed", False))

        def _wait_if_paused(self):
            """成人检测：暂停时挂起本线程，直到「继续」或「停止」。"""
            d = self.dialog
            while (d and getattr(d, "_adult_paused", False)
                   and not getattr(d, "_adult_stop", False)
                   and not getattr(d, "_closed", False)):
                try:
                    self.msleep(100)
                except Exception:
                    break

        def _run_impl(self):
            # ---- 阶段 A：解析「本地 Spider 源」的资源文件真实路径 ----
            # 只有「本地 Spider」才有本地文件；type:1 直连 / 0 XML / 4 目录 / 远程源
            # 均无本地文件，直接跳过（不再对它们做无意义的遍历与「未找到」）。
            # expects_local_file 为权威口径（兼容影视仓字符串 type 变体）。
            spider_entries = [e for e in self.entries if expects_local_file(e)]
            roots = default_search_roots(self.repo_dir, self.cfg_name) if self.repo_dir else []
            name_map = {}
            if spider_entries:
                self.search_progress.emit(0, 0, "开始遍历查找 Spider 源 .py 文件…")
                last_emit = 0

                def _cb(done, total, d):
                    nonlocal last_emit
                    if done == 1 or done - last_emit >= 25:
                        last_emit = done
                        self.search_progress.emit(done, 0, d)

                name_map = discover_py_files(
                    roots, _cb,
                    (lambda: self.dialog._closed) if self.dialog else None) \
                    if roots else {}
                self._name_map = name_map  # 供 URL 检测线程复用，避免重复遍历
                self.search_progress.emit(-1, 0, "遍历完成，开始检测…")
            # 解析每个 Spider 条目
            for e in spider_entries:
                if self._aborted():
                    break
                self._wait_if_paused()
                if self._aborted():
                    break
                k = str(e.get("key", ""))
                p, _ = resolve_spider_path_resilient(
                    self.base_dir, e.get("api", ""), self.alt_dir, name_map)
                self._resolved[k] = p if os.path.isfile(p) else ""
            # 仍有 Spider 源未找到 .py：请求主线程弹框让用户选择 .py 目录（仅一次）
            if self.allow_prompt and spider_entries:
                missing = [str(e.get("key", "")) for e in spider_entries
                           if not os.path.isfile(self._resolved.get(str(e.get("key", "")), ""))]
                if missing:
                    chosen = self._ask_user_dir(missing)
                    if chosen:
                        nm2 = discover_py_files(
                            [chosen], None,
                            (lambda: self.dialog._closed) if self.dialog else None)
                        for e in spider_entries:
                            k = str(e.get("key", ""))
                            if os.path.isfile(self._resolved.get(k, "")):
                                continue
                            bn = os.path.basename(
                                api_to_path(self.base_dir, e.get("api", ""))).lower()
                            p3 = nm2.get(bn)
                            if p3 and os.path.isfile(p3):
                                self._resolved[k] = p3
            # ---- 阶段 B：读 .py 内容做成人/短剧/直播检测（Spider 源，同一遍三判定）----
            total = len(self.entries)
            m = {}
            for i, e in enumerate(self.entries):
                if self._aborted():
                    break
                self._wait_if_paused()
                if self._aborted():
                    break
                _k = str(e.get("key", ""))
                _py = self._resolved.get(_k, "")
                # 按 type 分流：仅「本地 Spider 源且解析到文件」才读内容判定；
                # type:1 直连 / 0 XML / 4 目录 / 远程源一律只按站点名判定
                # （这些源本来就没有本地文件内容可读）。expects_local_file 为权威口径。
                if expects_local_file(e) and os.path.isfile(_py):
                    is_ad, kw = detect_adult(_py, e.get("name", ""),
                                             extra_text=entry_extra_text(e))
                    is_dj, dkw = detect_duanju(_py, e.get("name", ""),
                                               extra_text=entry_extra_text(e))
                    is_lv, lkw = detect_live(_py, e.get("name", ""),
                                             extra_text=entry_extra_text(e))
                else:
                    # 非本地 Spider 或找不到文件：先按「站点名 + ext 字段」判定。
                    # 深度检测开启且三项未全部命中时，再拉取 api 页面内容补充判定
                    # （每站最多一次网络请求，已命中的项不重复判定以省时间）。
                    _extra = entry_extra_text(e)
                    is_ad, kw = detect_adult("", e.get("name", ""), extra_text=_extra)
                    is_dj, dkw = detect_duanju("", e.get("name", ""), extra_text=_extra)
                    is_lv, lkw = detect_live("", e.get("name", ""), extra_text=_extra)
                    if (self.deep and not self._aborted()
                            and not (is_ad and is_dj and is_lv)):
                        _u = entry_deep_url(e)
                        if _u:
                            _fetched = deep_fetch_text(_u)
                            if _fetched:
                                _dx = (_extra + "\n" + _fetched) if _extra else _fetched
                                if not is_ad:
                                    is_ad, kw = detect_adult(
                                        "", e.get("name", ""), extra_text=_dx)
                                if not is_dj:
                                    is_dj, dkw = detect_duanju(
                                        "", e.get("name", ""), extra_text=_dx)
                                if not is_lv:
                                    is_lv, lkw = detect_live(
                                        "", e.get("name", ""), extra_text=_dx)
                m[_k] = (is_ad, kw, is_dj, dkw, is_lv, lkw)
                self.item_done.emit(_k, is_ad, kw, is_dj, dkw, is_lv, lkw)
                self.progress.emit(i + 1, total, e.get("name", ""))
            self.finished_map.emit(m)

        def _ask_user_dir(self, missing):
            """经主线程弹框让用户选择 .py 目录（BlockingQueuedConnection 阻塞本线程，
            直到主线程弹框返回）。失败/已关闭则返回 ''。"""
            try:
                import json
                dlg = self.dialog
                if dlg is None or getattr(dlg, "_closed", False):
                    return ""
                # 参数放属性、结果取属性，无参 invoke——Qt5/Qt6 皆可用
                dlg._pending_missing = json.dumps(missing)
                dlg._pending_result = ""
                QMetaObject.invokeMethod(
                    dlg, "prompt_py_dir", Qt.BlockingQueuedConnection)
                return getattr(dlg, "_pending_result", "") or ""
            except Exception:
                return ""

    # ---- URL 源地址可达性检测后台线程：成人检测完成后顺序启动，避免界面卡顿 ----
    class _UrlCheckWorker(QThread):
        progress = Signal(int, int, str)        # 已完成数, 总数, 当前站点名
        item_done = Signal(str, int, str, str)  # key, 状态码(1可达/0不可达/2无URL), 方法, 备注
        finished_map = Signal(dict)             # 最终 url_map: key -> (code, method, note)

        def __init__(self, dialog, base_dir, entries, resolved=None, name_map=None,
                     alt_dir=None, repo_dir=None, cfg_name=None, allow_prompt=False):
            super().__init__(dialog)
            self.dialog = dialog
            self.base_dir = base_dir
            self.entries = entries
            self.resolved = resolved or {}      # 由成人检测线程预解析的 key->py_path
            self.name_map = name_map or {}       # 遍历搜索得到的 {小写文件名: 路径}
            self.alt_dir = alt_dir
            self.repo_dir = repo_dir
            self.cfg_name = cfg_name
            self.allow_prompt = allow_prompt

        def run(self):
            # 安全兜底：异常不得让界面卡在「检测中…」
            try:
                self._run_impl()
            except Exception:
                total = len(self.entries)
                m = {}
                for i, e in enumerate(self.entries):
                    k = str(e.get("key", ""))
                    m[k] = (2, "", "检测异常")
                    self.item_done.emit(k, 2, "", "检测异常")
                    self.progress.emit(i + 1, total, e.get("name", ""))
                self.finished_map.emit(m)

        def _resolve_py(self, e):
            k = str(e.get("key", ""))
            if k in self.resolved and os.path.isfile(self.resolved[k]):
                return self.resolved[k]
            # 复用语人检测线程的遍历结果；若为空且提供了仓库信息则临时补一次
            if not self.name_map and self.repo_dir:
                roots = default_search_roots(self.repo_dir, self.cfg_name)
                self.name_map = discover_py_files(roots) if roots else {}
            p, _ = resolve_spider_path_resilient(
                self.base_dir, e.get("api", ""), self.alt_dir, self.name_map)
            return p if os.path.isfile(p) else ""

        def _aborted(self):
            """URL 检测：是否应中止（用户点了「停止」或对话框已关闭）。"""
            d = self.dialog
            return bool(d) and (getattr(d, "_url_stop", False)
                                or getattr(d, "_closed", False))

        def _wait_if_paused(self):
            """URL 检测：暂停时挂起本线程，直到「继续」或「停止」。"""
            d = self.dialog
            while (d and getattr(d, "_url_paused", False)
                   and not getattr(d, "_url_stop", False)
                   and not getattr(d, "_closed", False)):
                try:
                    self.msleep(100)
                except Exception:
                    break

        def _run_impl(self):
            # 按 type 路由检测：不再预遍历 .py 目录（check_source_reachability 自行解析）。
            total = len(self.entries)
            m = {}
            for i, e in enumerate(self.entries):
                if self._aborted():
                    break
                self._wait_if_paused()
                if self._aborted():
                    break
                k = str(e.get("key", ""))
                # 按 type 路由检测（真正管理各种 type）：
                #   type:1 直连 CMS → HTTP 探 api 可达性
                #   type:3 Spider  → 从 .py 抽取源地址 URL 检测
                #   type:0/4 或 http → HTTP 探 api
                # check_source_reachability 内部已按此分流，不再一律要求 .py。
                r = check_source_reachability(e, base_dir=self.base_dir)
                if r.get("reachable") is True:
                    code, method, note = 1, r.get("method", ""), ""
                elif r.get("reachable") is False:
                    code, method, note = 0, "", r.get("note", "")
                else:
                    # None：无 URL 可检测 / 直连源无本地 .py 等 → 中性提示
                    code, method, note = 2, "", (r.get("note") or "无 URL 可检测")
                m[k] = (code, method, note)
                self.item_done.emit(k, code, method, note)
                self.progress.emit(i + 1, total, e.get("name", ""))
            self.finished_map.emit(m)

    class _ProxyCheckWorker(QThread):
        """「需特殊上网」后台线程：对每个站点用 pyinj_netdiag.diagnose_source
        判断是否命中「DNS 失败 / 命中代理域名库 / 连接被拒」等需要代理的情形。
        结果通过 finished_map 发回：key -> bool。只读检测，不改配置。"""

        progress = Signal(int, int, str)   # 已完成, 总数, 当前站点名
        finished_map = Signal(dict)        # key -> bool

        def __init__(self, dialog, entries, base_dir=None, proxy_domains=None):
            super().__init__(dialog)
            self.dialog = dialog
            self.entries = entries
            self.base_dir = base_dir
            self.proxy_domains = proxy_domains

        def _aborted(self):
            d = self.dialog
            return bool(d) and getattr(d, "_closed", False)

        def _wait_if_paused(self):
            d = self.dialog
            while (d and getattr(d, "_proxy_paused", False)
                   and not getattr(d, "_proxy_stop", False)
                   and not getattr(d, "_closed", False)):
                try:
                    self.msleep(100)
                except Exception:
                    break

        def run(self):
            m = {}
            total = len(self.entries)
            try:
                for i, e in enumerate(self.entries):
                    if self._aborted() or getattr(self.dialog, "_proxy_stop", False):
                        break
                    self._wait_if_paused()
                    key = str(e.get("key", ""))
                    try:
                        r = pyinj_netdiag.diagnose_source(
                            e, self.base_dir, max_urls=2,
                            proxy_domains=self.proxy_domains)
                        need = bool(r.get("needs_proxy")) or r.get("level") == "proxy"
                    except Exception:
                        need = False
                    m[key] = need
                    try:
                        self.progress.emit(i + 1, total, str(e.get("name") or key))
                    except Exception:
                        pass
            except Exception:
                pass
            self.finished_map.emit(m)

    class _MissingPyWorker(QThread):
        """「.py 存在性检测」后台线程：对话框打开即自动运行（只读、快速），
        校验每个已注册配置项对应的 .py 是否还在磁盘上；直接路径失效时
        再遍历仓库找回一次（py 文件夹被改名/移动的场景）。
        结果通过 finished_check 信号发回：(missing, relocated)。"""

        finished_check = Signal(list, list)  # missing=[(key,api)], relocated=[(key,api,path)]

        def __init__(self, dialog, base_dir, entries, repo_dir=None, cfg_name=None):
            super().__init__(dialog)
            self.dialog = dialog
            self.base_dir = base_dir
            self.entries = entries
            self.repo_dir = repo_dir
            self.cfg_name = cfg_name

        def _aborted(self):
            d = self.dialog
            return bool(d) and getattr(d, "_closed", False)

        def run(self):
            missing, relocated = [], []
            try:
                # 阶段 1：直接路径解析（快，逐条可中止）
                # 只校验「应有本地文件」的源（本地 Spider）；type:1 直连 / 0 XML /
                # 4 目录 / 远程源一律跳过，不再误报「缺失 .py」。
                for e in self.entries:
                    if self._aborted():
                        return
                    key = str(e.get("key", ""))
                    api = str(e.get("api", ""))
                    if not expects_local_file(e):
                        continue
                    p = resolve_spider_path(self.base_dir, api, self.repo_dir)
                    if not os.path.isfile(p):
                        missing.append((key, api))
                # 阶段 2：对缺失项遍历找回（可中止）
                if missing and not self._aborted():
                    roots = default_search_roots(self.repo_dir, self.cfg_name)
                    name_map = discover_py_files(
                        roots, None,
                        (lambda: self._aborted())) if roots else {}
                    still = []
                    for key, api in missing:
                        if self._aborted():
                            return
                        bn = os.path.basename(api_to_path(self.base_dir, api)).lower()
                        p2 = name_map.get(bn)
                        if p2 and os.path.isfile(p2):
                            relocated.append((key, api, p2))
                        else:
                            still.append((key, api))
                    missing = still
            except Exception:
                pass
            if not self._aborted():
                self.finished_check.emit(missing, relocated)

    class App(QWidget):
        def __init__(self):
            super().__init__()
            # 记住上次的仓库目录（QSettings 按用户持久化）；无效则回退 exe 目录
            try:
                _st = QSettings("PyInjector", "PyInjector")
                _last = str(_st.value("repo_dir", "") or "")
            except Exception:
                _st, _last = None, ""
            if _last and os.path.isdir(_last):
                self.repo_dir = _last
            else:
                self.repo_dir = get_app_dir()
            self.cfg_file = CONFIG_NAME  # 实际使用的配置文件名（可自动识别/用户指定）
            self.base_dir = self.repo_dir  # 基准目录（配置文件所在目录，api/py 目录相对它解析）
            self.pending = []
            self.raw = ""
            self.data = {}
            self.sites = []
            self.existing_keys = set()
            self.existing_apis = set()

            self.setWindowTitle(self._repo_title())
            self.resize(900, 640)
            try:
                _geo = _st.value("main/geometry") if _st is not None else None
                if _geo is not None:
                    self.restoreGeometry(_geo)
            except Exception:
                pass
            # 拖拽注入：把 .py 直接拖进主窗口即完成注入
            try:
                self.setAcceptDrops(True)
            except Exception:
                pass
            self._build_ui()
            self.load_repo()

        def closeEvent(self, ev):
            # 退出时记住窗口几何，下次原样打开
            try:
                QSettings("PyInjector", "PyInjector").setValue(
                    "main/geometry", self.saveGeometry())
            except Exception:
                pass
            super().closeEvent(ev)

        # ---- UI 构造 ----
        def _build_ui(self):
            root = QVBoxLayout(self)

            h = QHBoxLayout()
            h.addWidget(QLabel("仓库目录:"))
            self.ent_repo = QLineEdit(self.repo_dir)
            self.ent_repo.setReadOnly(True)
            h.addWidget(self.ent_repo, 1)
            h.addWidget(QPushButton("选择…", clicked=self.choose_repo))
            root.addLayout(h)

            # 配置文件：可编辑下拉框——点 ▼ 直接列出仓库目录里的候选 JSON（打分排序），
            # 点选即加载；也支持手动输入，留空=自动识别（不限定 py.json，便于通用）
            hc = QHBoxLayout()
            hc.addWidget(QLabel("配置文件:"))
            self.ent_cfg = QComboBox()
            self.ent_cfg.setEditable(True)
            self.ent_cfg.setInsertPolicy(QComboBox.NoInsert)
            self.ent_cfg.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            self.ent_cfg.activated.connect(lambda _i: self.load_repo())
            _le = self.ent_cfg.lineEdit()
            if _le is not None:
                _le.setPlaceholderText("留空=自动识别（点右侧▼下拉选择，也可手动填文件名）")
                _le.returnPressed.connect(self.load_repo)
            hc.addWidget(self.ent_cfg, 1)
            hc.addWidget(QPushButton("自动识别", clicked=self.autodetect_cfg))
            root.addLayout(hc)
            self._refresh_cfg_candidates()

            # ---- 顶部工具栏：动词优先 + 图标（替代原四步编号 GroupBox，去误导性编号）----
            # 按「维度」分两行，避免 13 个按钮挤成一行把窗口撑宽：
            #   行 1「待注入」：对下方待注入列表的增删与落盘；
            #   行 2「仓库」  ：对已加载 py.json 仓库的维护（管理/合并/查重/去重/刷新/关于）。
            def _mkbtn(text, slot, minw=None, accent=None):
                b = QPushButton(text, clicked=slot)
                if minw:
                    b.setMinimumWidth(minw)
                if accent:
                    b.setProperty("accent", accent)
                return b

            def _grp(text):
                l = QLabel(text)
                l.setStyleSheet("color:#8a97a5; padding:2px 6px 2px 0;" if IS_DARK
                                else "color:#5a6b7b; padding:2px 6px 2px 0;")
                return l

            bar = QVBoxLayout()
            bar.setSpacing(6)

            # 两个分组标签等宽，保证上下两行按钮左对齐
            lbl_list, lbl_repo = _grp("待注入"), _grp("仓库")
            _gw = max(lbl_list.sizeHint().width(), lbl_repo.sizeHint().width(), 58)
            lbl_list.setFixedWidth(_gw)
            lbl_repo.setFixedWidth(_gw)

            # 行 1：待注入列表（增 / 删 / 清空）+ 落盘
            row1 = QHBoxLayout()
            row1.setSpacing(6)
            row1.addWidget(lbl_list)
            row1.addWidget(_mkbtn("📄 注入文件", self.inject_files))
            row1.addWidget(_mkbtn("➕ 添加直连", self.add_cms_source))
            row1.addWidget(_mkbtn("🔍 扫描目录", self.scan_py))
            row1.addWidget(_mkbtn("移除选中", self.remove_selected))
            row1.addWidget(_mkbtn("🗑 清空列表", self.clear_pending, accent="danger"))
            row1.addStretch(1)
            row1.addWidget(_mkbtn("💾 写入配置", self.write_config, accent="primary"))
            bar.addLayout(row1)

            # 行 2：已加载仓库的维护
            row2 = QHBoxLayout()
            row2.setSpacing(6)
            row2.addWidget(lbl_repo)
            row2.addWidget(_mkbtn("⚙ 管理站点", self.view_config))
            row2.addWidget(_mkbtn("🔀 合并导入", self.merge_import, accent="primary"))
            row2.addWidget(_mkbtn("✓ 查重", self.check_dups))
            row2.addWidget(_mkbtn("♻ 去重", self.dedup))
            row2.addWidget(_mkbtn("🔄 刷新", self.load_repo))
            row2.addStretch(1)
            row2.addWidget(_mkbtn("ℹ 关于", self._show_about))
            bar.addLayout(row2)

            root.addLayout(bar)

            # 状态标签：承接「已加载/站点数」等信息（不再塞进标题栏）
            self.lbl_status = QLabel("")
            self.lbl_status.setStyleSheet(
                "color:#8a97a5; padding:2px 2px;" if IS_DARK else "color:#5a6b7b; padding:2px 2px;")
            root.addWidget(self.lbl_status)

            # AI 生成声明（主窗口常驻，明确软件由 AI 辅助生成）
            self.lbl_ai = QLabel("🤖 本工具由 AI 辅助生成 · 仅供个人学习测试")
            self.lbl_ai.setStyleSheet(
                "color:#b0bcc9; font-size:11px; padding:1px 2px;" if IS_DARK
                else "color:#8a97a5; font-size:11px; padding:1px 2px;")
            root.addWidget(self.lbl_ai)

            gb = QGroupBox("全局开关（套用到待注入条目）")
            gh = QHBoxLayout(gb)
            self.var_filt = QCheckBox("可筛选 filterable")
            self.var_qs = QCheckBox("速搜 quickSearch")
            self.var_sr = QCheckBox("可搜索 searchable")
            self.var_copy = QCheckBox("仓库外文件复制到 py/")
            self.var_filt.setChecked(True)
            self.var_qs.setChecked(True)
            self.var_sr.setChecked(True)
            self.var_copy.setChecked(True)
            gh.addWidget(self.var_filt)
            gh.addWidget(self.var_qs)
            gh.addWidget(self.var_sr)
            gh.addWidget(self.var_copy)
            gh.addWidget(QLabel("type:"))
            self.var_type = QSpinBox()
            self.var_type.setRange(0, 9)
            self.var_type.setValue(3)
            # type 是「每条站点独立」的接口类型。三条注入路径**都会自带 type**：
            #   · 注入文件 / 扫描目录 → make_entry() 按 .py 推断 = 3(Spider)
            #   · 添加直连源          → make_entry_from_api(type_hint=1) = 1
            # 所以本项正常情况下永不生效，默认**置灰锁定**（避免误以为能全局改 type）；
            # 仅当待注入列表里真的出现「缺 type」的条目时才解锁（见 _sync_type_switch）。
            self.var_type.setToolTip(
                "已锁定：注入的 .py 固定为 3(Spider)，「➕ 添加直连」自动为 1，\n"
                "每条站点的 type 由它自身决定，无需在此手改。")
            self._sync_type_switch()
            gh.addWidget(self.var_type)
            gh.addStretch(1)
            root.addWidget(gb)

            gl = QGroupBox("待注入列表（双击可改 key / name）")
            gv = QVBoxLayout(gl)
            self.lb = QListWidget()
            self.lb.itemDoubleClicked.connect(self.edit_selected)
            gv.addWidget(self.lb)
            # 待注入列表空状态：为空时中央显示操作引导（叠层 QLabel，不挡鼠标交互）
            self.lb_empty = QLabel(
                "还没有待注入的条目\n\n"
                "点「📄 注入文件」选择 .py，或直接把 .py 拖进本窗口；\n"
                "也可以「🔍 扫描目录」批量登记 py/ 下未注册的爬虫；\n"
                "直连 CMS 源点「➕ 添加直连」粘贴 API 地址即可。\n"
                "加入后双击条目可改 key / name，再点「💾 写入配置」落盘。")
            self.lb_empty.setAlignment(Qt.AlignCenter)
            self.lb_empty.setStyleSheet(
                "color:%s; font-size:13px; background:transparent;"
                % ("#8a97a5" if IS_DARK else "#9aa7b5"))
            self.lb_empty.setAttribute(Qt.WA_TransparentForMouseEvents)
            try:
                self.lb_empty.setParent(self.lb.viewport())
                self.lb.viewport().installEventFilter(self)  # viewport 尺寸变化时同步 overlay
            except Exception:
                pass
            self.lb_empty.hide()
            root.addWidget(gl, 1)
            self._update_pending_empty()  # 构造时即按空列表显示引导

            lg = QGroupBox("日志")
            lv = QVBoxLayout(lg)
            self.log = QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setStyleSheet("background:#0f1419; color:#c8e6c9; font-family:Consolas;")
            lv.addWidget(self.log)
            root.addWidget(lg, 1)

        # ---- 日志 ----
        def log_msg(self, msg, level="info"):
            tag = LEVEL_TAG.get(level, "· ")
            self.log.appendPlainText(tag + msg)
            QApplication.processEvents()

        # ---- 仓库加载 ----
        def _refresh_cfg_candidates(self):
            """把仓库目录里的候选配置文件填进「配置文件」下拉框（保留当前文本）。
            目录取 ent_repo 输入框的实时文本（与 _resolve_cfg 同源）。"""
            try:
                cur = self.ent_cfg.currentText()
                names = list_config_candidates(self.ent_repo.text().strip())
                self.ent_cfg.clear()
                self.ent_cfg.addItems(names)
                self.ent_cfg.setCurrentText(cur)
            except Exception:
                pass

        def _resolve_cfg(self):
            """根据用户输入/自动识别确定配置文件。返回 (cfg, 错误信息或 None)。"""
            self.repo_dir = self.ent_repo.text().strip()
            hint = self.ent_cfg.currentText().strip() if hasattr(self, "ent_cfg") else ""
            cfg = guess_config_file(self.repo_dir, hint or None)
            if cfg is None:
                if hint:
                    return None, "未找到指定的配置文件：%s" % hint
                return None, "在 %s 未找到可用的配置文件（可手动填写配置文件名）" % self.repo_dir
            self.cfg_file = cfg
            self.base_dir = cfg_base_dir(self.repo_dir, cfg)
            # 回显识别结果（不覆盖用户手输的有效值——两者一致时无感）
            if self.ent_cfg.currentText().strip() != cfg:
                self.ent_cfg.setCurrentText(cfg)
            return cfg, None

        def _repo_title(self):
            """标题 = 仓库路径 — 源管家 v<版本>（仓库未选时仅「源管家 v<版本>」）。"""
            return tagged_title(self.repo_dir or "")

        def _set_status(self, text):
            """仓库状态（已加载/站点数）显示在状态标签，标题保持「仓库路径 — 源管家」。"""
            try:
                self.lbl_status.setText(text or "")
            except Exception:
                pass
            self.setWindowTitle(self._repo_title())

        def _show_about(self):
            """关于对话框：展示版本号 + AI 生成声明。"""
            try:
                QMessageBox.about(
                    self, tagged_title("关于"),
                    "源管家 — TVBox / 影视仓 全源管理器\n\n版本：%s\n\n"
                    "🤖 本软件由 AI 辅助生成（仅供个人学习测试之用）\n\n"
                    "绿色单文件 · 免安装 · 双模式（GUI / CLI）\n"
                    "仅做静态解析与只读 HTTP 探测，绝不执行任何爬虫代码。" % APP_VERSION)
            except Exception:
                pass

        def autodetect_cfg(self):
            cfg, err = self._resolve_cfg()
            if err:
                self._set_status("未找到配置文件")
                self.log_msg(err, "err")
                return
            self._refresh_cfg_candidates()
            self.load_repo()

        def load_repo(self):
            cfg, err = self._resolve_cfg()
            if err:
                self._set_status("未找到配置文件")
                self.log_msg(err, "err")
                self.sites = []
                self.existing_keys = set()
                self.existing_apis = set()
                self.refresh_list()
                return
            try:
                self.raw, self.sites, self.existing_keys, self.existing_apis = load_repo(
                    self.repo_dir, self.cfg_file)
            except FileNotFoundError as e:
                self._set_status("未找到配置文件")
                self.log_msg(str(e), "err")
                self.sites = []
                self.existing_keys = set()
                self.existing_apis = set()
                self.refresh_list()
                return
            except Exception as e:
                self._set_status("配置解析失败")
                self.log_msg("配置文件 %s 解析失败: %s" % (self.cfg_file, e), "err")
                return
            self._set_status("已加载 %s · 站点 %d 个" % (self.cfg_file, len(self.sites)))
            self.log_msg("已加载仓库：%s（配置文件 %s，现有站点 %d 个）"
                         % (self.repo_dir, self.cfg_file, len(self.sites)), "ok")

        def choose_repo(self):
            d = QFileDialog.getExistingDirectory(self, "选择仓库根目录（含 spider 配置 json 与 py/ 目录）", self.repo_dir)
            if d:
                self.ent_repo.setText(d)
                try:
                    QSettings("PyInjector", "PyInjector").setValue("repo_dir", d)
                except Exception:
                    pass
                self._refresh_cfg_candidates()
                self.load_repo()

        # ---- 列表刷新 ----
        def refresh_list(self):
            self.lb.clear()
            for e in self.pending:
                self.lb.addItem("%-22s | %-18s | %s" % (e["name"][:22], e["key"][:18], e["api"]))
            self._update_pending_empty()
            self._sync_type_switch()

        def _sync_type_switch(self):
            """全局 type 开关：默认锁定，只有待注入列表里真缺 type 时才解锁。

            三条注入路径都会自带 type（.py→3，直连→1），故 normal 情况下该开关
            从不参与写入；置灰可避免用户误以为「这里能全局改 type」。
            将来若某条路径产生「缺 type」的条目，它会自动解锁并作为兜底值生效
            （commit_write 只对缺 type 的条目套用它，绝不抹平已有 type）。"""
            sw = getattr(self, "var_type", None)
            if sw is None:
                return
            try:
                missing = [p for p in self.pending
                           if p.get("type") is None or p.get("type") == ""]
                if missing:
                    sw.setEnabled(True)
                    sw.setToolTip(
                        "接口类型：0=XML  1=JSON直连(CMS)  3=Spider  4=目录型\n"
                        "当前有 %d 条待注入条目未带 type，写入时将套用此值。"
                        % len(missing))
                else:
                    sw.setEnabled(False)
                    sw.setToolTip(
                        "已锁定：注入的 .py 固定为 3(Spider)，「➕ 添加直连」自动为 1，\n"
                        "每条站点的 type 由它自身决定，无需在此手改。")
            except Exception:
                pass

        def _update_pending_empty(self):
            """待注入列表为空时显示操作引导；有内容即隐藏。"""
            try:
                lbl = getattr(self, "lb_empty", None)
                if lbl is None:
                    return
                if self.lb.count() > 0:
                    lbl.hide()
                else:
                    lbl.setGeometry(self.lb.viewport().rect())
                    lbl.show()
                    lbl.raise_()
            except Exception:
                pass

        def resizeEvent(self, ev):
            try:
                super().resizeEvent(ev)
            except Exception:
                pass
            # 空状态 overlay 跟随窗口尺寸
            try:
                lbl = getattr(self, "lb_empty", None)
                if lbl is not None and self.lb.count() == 0:
                    lbl.setGeometry(self.lb.viewport().rect())
            except Exception:
                pass

        def showEvent(self, ev):
            try:
                super().showEvent(ev)
            except Exception:
                pass
            # 首次显示时布局已生效，补一次几何同步（此前 isVisible 守卫会跳过）
            try:
                self._update_pending_empty()
            except Exception:
                pass

        def eventFilter(self, obj, ev):
            # 全局兜底：任何窗体（含 QMessageBox / QInputDialog）设置标题时，
            # 自动补上版本标识 —— 保证「所有窗体标题栏」都明确标注当前版本。
            try:
                if ev.type() == QEvent.WindowTitleChange:
                    _tag_window_title(obj)
            except Exception:
                pass
            # viewport 尺寸变化（含首次布局）→ 同步 overlay 几何
            try:
                lbl = getattr(self, "lb_empty", None)
                if lbl is not None and obj is self.lb.viewport() and ev.type() == ev.Type.Resize:
                    if self.lb.count() == 0:
                        lbl.setGeometry(self.lb.viewport().rect())
            except Exception:
                pass
            try:
                return super().eventFilter(obj, ev)
            except Exception:
                return False

        # ---- 拖拽注入：把 .py 文件直接拖进主窗口 ----
        def dragEnterEvent(self, ev):
            try:
                if ev.mimeData().hasUrls():
                    for u in ev.mimeData().urls():
                        if u.toLocalFile().lower().endswith(".py"):
                            ev.acceptProposedAction()
                            return
            except Exception:
                pass
            try:
                ev.ignore()
            except Exception:
                pass

        def dropEvent(self, ev):
            files = []
            try:
                if ev.mimeData().hasUrls():
                    files = [u.toLocalFile() for u in ev.mimeData().urls()
                             if u.toLocalFile().lower().endswith(".py")]
            except Exception:
                pass
            if not files:
                return
            self._inject_files(files)
            try:
                ev.acceptProposedAction()
            except Exception:
                pass

        # ---- ① 注入文件 ----
        def inject_files(self):
            files, _ = QFileDialog.getOpenFileNames(
                self, "选择 spider .py 文件（可多选）", "", "Python (*.py);;All (*.*)"
            )
            if not files:
                return
            self._inject_files(files)

        def _inject_files(self, files):
            ents, logs = collect_from_files(files, self.base_dir, self.var_copy.isChecked(),
                                            self.existing_keys, self.existing_apis)
            for lv, m in logs:
                self.log_msg(m, lv)
            self.pending += ents
            self.refresh_list()
            if ents:
                self.log_msg("共加入 %d 个待注入条目。" % len(ents), "info")

        # ---- ② 扫描 py/ 目录 ----
        def scan_py(self):
            ents, logs = collect_from_scan(self.base_dir, self.existing_keys, self.existing_apis)
            for lv, m in logs:
                self.log_msg(m, lv)
            self.pending += ents
            self.refresh_list()
            if ents:
                self.log_msg("扫描完成，新增 %d 个未注册条目。" % len(ents), "info")
            else:
                self.log_msg("扫描完成：py/ 内 .py 均已注册。", "info")
            # 反向校验：已注册配置项对应的 .py 是否还在磁盘上
            # （此前只查「目录里有、配置里没有」，漏了「配置里有、文件已丢失」）
            missing, relocated = check_missing_py_resilient(
                self.base_dir, self.sites, self.repo_dir, self.cfg_file)
            for key, api, p in relocated:
                self.log_msg("提示：%s 的 .py 原路径失效，已在别处找回：%s"
                             % (key, p), "warn")
            for key, api in missing:
                self.log_msg("缺失 .py：%s（%s）对应文件不存在，请处理"
                             % (key, api), "err")
            if not missing and not relocated:
                self.log_msg("已注册 %d 个站点的 .py 文件均存在。" % len(self.sites), "ok")

        # ---- ③ 添加直连源（type:1，手动粘贴 API 地址）----
        def add_cms_source(self):
            """手动粘贴直连 CMS 的 API 地址，生成一条 type:1 站点条目加入待注入列表。"""
            dlg = QDialog(self)
            dlg.setWindowTitle(tagged_title("添加直连源（type:1）"))
            fl = QFormLayout(dlg)
            api_edit = QLineEdit()
            api_edit.setPlaceholderText("例如：https://example.com/api.php/provide/vod?ac=list")
            name_edit = QLineEdit()
            name_edit.setPlaceholderText("可选；留空则按地址自动推断名称")
            fl.addRow("API 地址 *:", api_edit)
            fl.addRow("名称:", name_edit)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            fl.addRow(bb)
            if dlg.exec() != QDialog.Accepted:
                return
            api = api_edit.text().strip()
            if not api:
                QMessageBox.warning(self, "提示", "API 地址不能为空。")
                return
            try:
                e = make_entry_from_api(api, name=name_edit.text().strip() or None, type_hint=1)
            except Exception as ex:
                QMessageBox.warning(self, "无法生成", "生成条目失败：%s" % ex)
                return
            if any(str(x.get("api", "")) == e["api"] for x in self.pending):
                QMessageBox.information(self, "提示", "该 API 已在待注入列表中。")
                return
            self.pending.append(e)
            self.refresh_list()
            self.log_msg("已加入直连源：%s（%s）" % (e.get("name"), e.get("api")), "info")

        # ---- 双击编辑 ----
        def edit_selected(self, item):
            idx = self.lb.row(item)
            if idx < 0 or idx >= len(self.pending):
                return
            e = self.pending[idx]
            dlg = QDialog(self)
            dlg.setWindowTitle(tagged_title("编辑条目"))
            fl = QFormLayout(dlg)
            vk = QLineEdit(e["key"])
            vn = QLineEdit(e["name"])
            fl.addRow("key:", vk)
            fl.addRow("name:", vn)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            fl.addRow(bb)
            if dlg.exec() == QDialog.Accepted:
                e["key"] = vk.text().strip()
                e["name"] = vn.text().strip()
                self.refresh_list()

        # ---- 移除 / 清空 ----
        def remove_selected(self):
            row = self.lb.currentRow()
            if row < 0:
                return
            e = self.pending.pop(row)
            self.log_msg("已移除：%s" % e["api"], "info")
            self.refresh_list()

        def clear_pending(self):
            if not self.pending:
                return
            if QMessageBox.question(self, "确认", "清空待注入列表（不影响已写入的配置）？") == QMessageBox.Yes:
                self.pending.clear()
                self.refresh_list()
                self.log_msg("已清空待注入列表。", "info")

        # ---- ④ 查看/修改配置 ----
        def view_config(self):
            if not self.raw:
                QMessageBox.critical(self, "错误", "尚未成功加载配置（%s）。" % self.cfg_file)
                return
            dlg = ConfigDialog(self, self.repo_dir, self.raw, self.sites, self.cfg_file, self.base_dir)
            if dlg.exec() == QDialog.Accepted and dlg.changed:
                self.load_repo()
                self.log_msg("配置已更新。", "ok")

        # ---- ⑤ 配置查重 ----
        def check_dups(self):
            if not self.sites:
                QMessageBox.information(self, "提示", "尚未加载任何站点。")
                return
            reps = check_duplicates(self.sites)
            if reps:
                QMessageBox.warning(self, "查重结果",
                                    "发现重复项 %d 个：\n\n" % len(reps) + "\n".join("• " + r for r in reps))
            else:
                QMessageBox.information(self, "查重结果",
                                    "未发现重复项。\n\n判重口径：key 必须唯一；功能重复 =（api + jar + ext）三者全同。\n仅 api 相同、ext/jar 不同属多线路复用，不算重复。")

        def dedup(self):
            """去重（主窗口入口）：按（key 唯一性 / api+jar+ext 组合）保留首个、删除重复项，确认后写盘。"""
            if not self.raw:
                QMessageBox.information(self, "提示", "尚未成功加载配置。")
                return
            new_text, removed = deduplicate_sites(self.raw)
            if not removed:
                QMessageBox.information(self, "去重", "未发现重复项，无需去重。")
                return
            msg = "将删除 %d 个重复条目（保留首个）：\n\n" % len(removed)
            msg += "\n".join("• %s（%s）" % (key, name) for key, name, reason in removed)
            if QMessageBox.question(self, "确认去重", msg + "\n\n确定立即写入吗？") != QMessageBox.Yes:
                return
            bak = backup_and_write(self.repo_dir, new_text, self.cfg_file)
            self.raw = new_text
            self.load_repo()
            QMessageBox.information(
                self, "完成", "已去重，删除 %d 个重复条目。\n备份：%s"
                % (len(removed), os.path.basename(bak)))

        # ---- ③ 写入 ----
        def write_config(self):
            if not self.pending:
                QMessageBox.information(self, "提示", "待注入列表为空。")
                return
            if not self.raw:
                QMessageBox.critical(self, "错误", "尚未成功加载配置（%s）。" % self.cfg_file)
                return

            seen = set(self.existing_keys)
            to_write = []
            skipped = 0
            for e in self.pending:
                if e["key"] in seen:
                    self.log_msg("跳过（key 已存在）：%s" % e["key"], "warn")
                    skipped += 1
                    continue
                seen.add(e["key"])
                to_write.append(e)

            if not to_write:
                QMessageBox.information(self, "提示", "没有可写入的新条目（全部重复）。")
                return

            switches = {
                "filterable": self.var_filt.isChecked(),
                "quickSearch": self.var_qs.isChecked(),
                "searchable": self.var_sr.isChecked(),
                "type": self.var_type.value(),
            }

            try:
                bak = commit_write(self.repo_dir, self.raw, to_write, switches, self.cfg_file)
                self.log_msg("已备份：%s" % os.path.basename(bak), "ok")
            except Exception as ex:
                self.log_msg("写入失败：%s" % ex, "err")
                QMessageBox.critical(self, "错误", "写入失败：%s" % ex)
                return

            self.log_msg("成功注入 %d 个站点（跳过 %d 个重复）。" % (len(to_write), skipped), "ok")
            QMessageBox.information(self, "完成", "已注入 %d 个站点。\n备份：%s" % (len(to_write), os.path.basename(bak)))
            self.load_repo()
            self.pending = [p for p in self.pending if p in to_write]
            self.refresh_list()

        # ---- 合并导入：把另一份配置（本地文件 / 粘贴文本 / 远程 URL）的站点并入当前仓库 ----
        def merge_import(self):
            """打开「合并导入」对话框，把外部配置按正确判重口径并入当前仓库。

            判重口径（与全局一致）= 功能身份 (type, api, jar, ext) 四元组，绝不用 api 单独判重，
            避免 jar 型多站点（同名类名 + 不同 ext）被误并。写入保留条目全部字段，
            并自动搬运本地 spider 的 .py/.js/.drpy 与本地 jar；
            配套文件**同名但内容不同**时默认改名为 _2 后缀并同步改写配置里的 api/jar，
            绝不静默跳过（详见 _FileConflictDialog）。"""
            if not self.raw:
                QMessageBox.information(self, "提示", "尚未成功加载配置（%s）。" % self.cfg_file)
                return
            dlg = _MergeDialog(self, self.repo_dir, self.cfg_file, self.raw, self.base_dir)
            if dlg.exec() != QDialog.Accepted:
                return
            new_text = getattr(dlg, "result_text", None)
            if not new_text:
                return
            try:
                bak = backup_and_write(self.repo_dir, new_text, self.cfg_file)
            except Exception as ex:
                QMessageBox.critical(self, "错误", "写入失败：%s" % ex)
                return
            self.raw = new_text
            self.load_repo()
            fs = getattr(dlg, "file_stats", None) or {}
            msg = "已合并写入配置。\n备份：%s" % os.path.basename(bak)
            if fs.get("copied"):
                msg += "\n\n已自动搬运 %d 个本地配套文件（.py/.js/.drpy/jar）。" % len(fs["copied"])
            if fs.get("renamed"):
                msg += ("\n%d 个同名但内容不同的配套文件已**改名搬运**"
                        "（配置里的 api/jar 已同步改为新名）：\n  %s"
                        % (len(fs["renamed"]), "、".join(fs["renamed"][:8])))
            if fs.get("skipped"):
                msg += "\n%d 个配套文件内容一致，已跳过（无需搬运）。" % len(fs["skipped"])
            if fs.get("conflict_skipped"):
                msg += ("\n⚠️ 你选择了「跳过」的 %d 个冲突文件未搬运，配置仍指向原路径，"
                        "需你手动处理：\n  %s"
                        % (len(fs["conflict_skipped"]), "、".join(fs["conflict_skipped"][:8])))
            if fs.get("backed_up"):
                msg += "\n%d 个被覆盖的目标文件已备份到 backups/companions/。" % len(fs["backed_up"])
            if fs.get("missing_src"):
                msg += "\n⚠️ %d 个配套文件在来源仓库找不到，未搬运，需你手动处理。" % len(fs["missing_src"])
            if fs.get("via_mirror"):
                msg += ("\n🚀 %d 个文件直连失败、已经镜像加速获取（内容可能滞后于源站，"
                        "如异常请核对）：\n  %s"
                        % (len(fs["via_mirror"]), "、".join(fs["via_mirror"][:6])))
            if fs.get("ref_skipped_encoding"):
                msg += ("\n⚠️ %d 个配套文件不是 UTF-8 编码：为保证**不写坏原文件**，"
                        "未改写它们内部的引用，请人工核对：\n  %s"
                        % (len(fs["ref_skipped_encoding"]),
                           "、".join(fs["ref_skipped_encoding"][:8])))
            QMessageBox.information(self, "完成", msg)

    class ConfigDialog(QDialog):
        """查看/编辑/删除已注册站点的对话框，保存时手术式写回并备份。"""

        def __init__(self, parent, repo_dir, raw, sites, cfg_file=CONFIG_NAME, base_dir=None):
            super().__init__(parent)
            self.repo_dir = repo_dir
            self.cfg_file = cfg_file
            # 基准目录：api / py 目录相对它解析（配置在子目录时 ≠ 仓库根目录）
            self.base_dir = base_dir or cfg_base_dir(repo_dir, cfg_file)
            self.raw = raw
            # 同时纳入 active 站点与被 /* [disabled] */ 注释禁用的站点（_disabled 标记），
            # 使「禁用」列可管理、可一键启用还原。
            self.entries = []
            for obj, dis in parse_sites_with_disabled(self.raw):
                e2 = dict(obj)
                e2["_disabled"] = dis
                self.entries.append(e2)
            # 后台检测状态：默认不自动开始；成人与 URL 两路完全分离，
            # 各自带 开始/暂停(继续)/停止 按钮，独立手动启停（避免打开界面即焦虑）
            self.detect_map = {}       # key -> (is_adult, kw)
            self.duanju_map = {}       # key -> (is_duanju, kw)，与成人检测同遍扫描得出
            self.live_map = {}         # key -> (is_live, kw)，与成人检测同遍扫描得出
            self._scanning = False     # 成人/短剧/直播内容检测进行中标记
            self._adult_started = False  # 是否已开始过（未开始时列显示「未检测」）
            self._adult_stop = False   # 成人检测：停止请求
            self._adult_paused = False # 成人检测：暂停标记
            self._adult_resolved = {}  # 成人线程解析结果（key->py_path），供 URL 检测复用
            self._adult_name_map = {}  # 成人线程遍历结果（文件名->路径）
            self.url_map = {}          # key -> (code, method, note)
            self.proxy_map = {}        # key -> bool：该站点是否需要特殊上网（代理）；由「网络体检」填充
            self._proxy_scanning = False
            self._proxy_stop = False
            self._proxy_paused = False
            self._proxy_worker = None
            self._url_scanning = False
            self._url_started = False  # URL 可达性检测是否已开始过
            self._url_stop = False     # URL 检测：停止请求
            self._url_paused = False   # URL 检测：暂停标记
            self._worker = None
            self._url_worker = None
            # .py 存在性检测：打开界面即自动后台运行（只读、快速），结果填入「文件」列
            self.file_map = {}         # key -> "missing" / "relocated" / "normal"
            self.file_reloc = {}       # key -> 找回后的实际路径（ relocated 时）
            self._file_checking = False
            self._file_worker = None
            self._closed = False       # 对话框是否已关闭（防止线程回调操作已销毁控件）
            self._sort_col = -1        # 当前排序列（-1=不排序，保持插入顺序）
            self._sort_asc = True      # 升序/降序
            # 恢复用户上次的排序偏好与窗口几何（QSettings 持久化；测试 mock 环境静默跳过）
            try:
                _st = QSettings("PyInjector", "PyInjector")
                _sc = _st.value("cfg/sort_col", -1, type=int)
                if isinstance(_sc, int) and -1 <= _sc <= 9:
                    self._sort_col = _sc
                self._sort_asc = bool(_st.value("cfg/sort_asc", True, type=bool))
                _geo = _st.value("cfg/geometry")
                if _geo is not None:
                    self.restoreGeometry(_geo)
            except Exception:
                pass
            # key 不在表格中显示（key 不可编辑且占位），双击行内任意列（api 列除外）即可编辑
            self._base_headers = ["name", "api", "类型", "筛选/快搜/搜", "成人", "短剧", "直播", "可达", "禁用", "资源"]
            self.removed_keys = set()
            # 删除时用户勾选了「同时删除 .py」的 key；未勾选的只删配置项、保留 .py
            self.removed_del_py = set()
            self.modified = {}  # key -> {field: value}
            self.changed = False
            self.setWindowTitle(tagged_title("查看 / 修改 / 删除配置"))
            self.resize(760, 500)
            self._build()
            self._refresh_table()
            # 注意：成人 / URL 检测不自动开始——两路各自带「开始/暂停/停止」按钮，
            # 由用户手动触发（见 _start_adult / _start_url）。
            # 打开界面即保持平静：按钮可用、进度条空置、成人/可达列显示「未检测」。
            # 仅「.py 存在性检测」自动后台运行（只读、快速），异常在「文件」列标示。
            self._start_file_check()

        # ---- .py 存在性检测（打开界面即自动后台运行，只读）----
        def _start_file_check(self):
            if self._closed:
                return
            if self._file_checking:
                return
            self._file_checking = True
            self.file_map = {}
            self.file_reloc = {}
            self._file_worker = _MissingPyWorker(
                self, self.base_dir, self.entries,
                repo_dir=self.repo_dir, cfg_name=self.cfg_file)
            self._file_worker.finished_check.connect(self._on_file_check_done)
            self._file_worker.finished.connect(self._file_worker.deleteLater)
            self._file_worker.start()

        def _on_file_check_done(self, missing, relocated):
            self._file_checking = False
            if self._closed:
                return
            miss_keys = {k for k, _a in missing}
            rel_keys = {k for k, _a, _p in relocated}
            self.file_reloc = {k: p for k, _a, p in relocated}
            for e in self.entries:
                k = str(e.get("key", ""))
                api = str(e.get("api", ""))
                if k in miss_keys:
                    self.file_map[k] = "missing"
                elif k in rel_keys:
                    self.file_map[k] = "relocated"
                elif not api or "://" in api:
                    self.file_map[k] = "remote"
                else:
                    self.file_map[k] = "normal"
            # 有异常时在检测分组标题上给出汇总提示（不弹窗、不打扰）
            # 注：缺失校验只针对「本地 Spider 源」——直连/XML/目录/远程源无本地文件，
            # 不参与统计，故文案用「Spider 资源」而非笼统的「.py」。
            if hasattr(self, "detect_grp") and self.detect_grp is not None:
                try:
                    if missing or relocated:
                        parts = []
                        if missing:
                            parts.append("Spider 资源缺失 %d 个" % len(missing))
                        if relocated:
                            parts.append("已找回 %d 个" % len(relocated))
                        self.detect_grp.setTitle(
                            "后台检测（成人·短剧·直播 / URL 可达性）— 独立启停 · ⚠ " + "，".join(parts))
                    else:
                        self.detect_grp.setTitle(
                            "后台检测（成人·短剧·直播 / URL 可达性）— 独立启停 · Spider 资源齐全")
                except Exception:
                    pass
            self._refresh_table()

        def _to_bool(self, v):
            try:
                return bool(int(v))
            except Exception:
                return bool(v)

        def _adult_of(self, e):
            """返回 (是否成人, 是否自动检测)。手动标注优先，否则用自动检测结果。"""
            key = str(e.get("key", ""))
            fv = e.get("adult", None)
            if fv is not None and self._to_bool(fv):
                return True, False
            auto, _kw = self.detect_map.get(key, (False, None))
            if auto:
                return True, True
            return False, False

        # ---- 成人内容后台检测回调（保持界面流畅，缓解等待焦虑）----
        def _on_scan_progress(self, done, total, name):
            if self._closed:
                return
            self.prog_bar.setRange(0, total or 1)
            self.prog_bar.setValue(done)
            if self._adult_paused:
                return  # 暂停中：保留「已暂停」文案，不被在途进度信号冲掉
            self.prog_label.setText("成人/短剧/直播检测：第 %d / %d 个 · %s"
                                    % (done, total, name))

        def _on_search_progress(self, done, total, dirname):
            """遍历搜索 .py 阶段：进度条按忙碌指示（未知总量）。"""
            if self._closed:
                return
            if self._adult_paused:
                return  # 暂停中：保留「已暂停」文案
            if done < 0:
                # 遍历完成，检测阶段会重置进度条，这里仅更新文案
                self.prog_label.setText("成人/短剧/直播检测：遍历完成，开始检测…")
                return
            self.prog_bar.setRange(0, 0)  # 忙碌指示（未知总量）
            self.prog_label.setText("成人/短剧/直播检测：正在遍历查找 .py 文件…(已扫描 %d 个目录)" % done)

        def _on_scan_item(self, key, is_adult, kw, is_dj, dkw, is_live, lkw):
            if self._closed:
                return
            self.detect_map[key] = (is_adult, kw)
            self.duanju_map[key] = (is_dj, dkw)
            self.live_map[key] = (is_live, lkw)
            self._update_adult_cell(key, is_adult)   # 该行成人列实时刷新
            self._update_duanju_cell(key, is_dj)     # 该行短剧列实时刷新
            self._update_live_cell(key, is_live)     # 该行直播列实时刷新

        def _on_scan_done(self, m):
            self.detect_map = {k: (v[0], v[1]) for k, v in m.items()}
            self.duanju_map = {k: (v[2], v[3]) for k, v in m.items()}
            self.live_map = {k: (v[4], v[5]) for k, v in m.items()}
            self._scanning = False
            # 立即缓存成人线程的解析结果，供 URL 检测复用（worker 之后会 deleteLater）
            try:
                self._adult_resolved = getattr(self._worker, "_resolved", {}) if self._worker else {}
                self._adult_name_map = getattr(self._worker, "_name_map", {}) if self._worker else {}
            except Exception:
                self._adult_resolved, self._adult_name_map = {}, {}
            if self._closed:
                return
            # 检测收尾：进度条拉满并保留汇总（含短剧/直播统计）；URL 检测不再自动接力（两路分离）
            n_adult = sum(1 for v in m.values() if v[0])
            n_dj = sum(1 for v in m.values() if v[2])
            n_lv = sum(1 for v in m.values() if v[4])
            self.prog_bar.setRange(0, 1)
            self.prog_bar.setValue(1)
            if self._adult_stop:
                self.prog_label.setText("成人/短剧/直播检测：已停止 · 共 %d 个 · 成人 %d 个 · 短剧 %d 个 · 直播 %d 个"
                                        % (len(m), n_adult, n_dj, n_lv))
            else:
                self.prog_label.setText("成人/短剧/直播检测：完成 · 共 %d 个 · 成人 %d 个 · 短剧 %d 个 · 直播 %d 个"
                                        % (len(m), n_adult, n_dj, n_lv))
            self._update_detect_ui()
            self._refresh_table()

        def _on_url_progress(self, done, total, name):
            if self._closed:
                return
            self.url_bar.setRange(0, total or 1)
            self.url_bar.setValue(done)
            if self._url_paused:
                return  # 暂停中：保留「已暂停」文案，不被在途进度信号冲掉
            self.url_label.setText("URL 可达性检测：第 %d / %d 个 · %s"
                                   % (done, total, name))

        def _on_url_item(self, key, code, method, note):
            if self._closed:
                return
            self.url_map[key] = (code, method, note)
            self._update_url_cell(key, code, method, note)

        def _on_url_done(self, m):
            self.url_map = m
            self._url_scanning = False
            if self._closed:
                return
            # URL 检测收尾：进度条拉满并保留汇总
            n_ok = sum(1 for c, _m, _n in m.values() if c == 1)
            n_bad = sum(1 for c, _m, _n in m.values() if c == 0)
            self.url_bar.setRange(0, 1)
            self.url_bar.setValue(1)
            if self._url_stop:
                self.url_label.setText("URL 可达性检测：已停止 · 可达 %d · 不可达 %d · 其它 %d"
                                       % (n_ok, n_bad, len(m) - n_ok - n_bad))
            else:
                self.url_label.setText("URL 可达性检测：完成 · 可达 %d · 不可达 %d · 其它 %d"
                                       % (n_ok, n_bad, len(m) - n_ok - n_bad))
            self._update_detect_ui()
            self._refresh_table()

        # ---- 两路检测：独立 开始 / 暂停(继续) / 停止 ----
        def _start_adult(self):
            """开始成人/短剧内容检测（同一遍扫描，不影响 URL 检测）。"""
            if self._closed or self._scanning:
                return
            self._adult_stop = False
            self._adult_paused = False
            self._adult_started = True
            self._scanning = True
            self.detect_map = {}
            self.duanju_map = {}
            self.live_map = {}
            self.prog_label.setText("成人/短剧/直播检测：准备…")
            self.prog_bar.setRange(0, len(self.entries) or 1)
            self.prog_bar.setValue(0)
            self._update_detect_ui()
            self._refresh_table()
            self._worker = _AdultScanWorker(
                self, self.base_dir, self.entries,
                alt_dir=self.repo_dir, repo_dir=self.repo_dir,
                cfg_name=self.cfg_file, allow_prompt=True,
                deep=bool(self.cb_deep.isChecked()))
            self._worker.progress.connect(self._on_scan_progress)
            self._worker.item_done.connect(self._on_scan_item)
            self._worker.finished_map.connect(self._on_scan_done)
            self._worker.search_progress.connect(self._on_search_progress)
            self._worker.finished.connect(self._worker.deleteLater)
            self._worker.start()

        def _pause_adult(self):
            """暂停 / 继续 成人检测（同一按钮切换）。"""
            if self._closed or not self._scanning:
                return
            self._adult_paused = not self._adult_paused
            self.prog_label.setText(
                "成人/短剧/直播检测：已暂停（点「继续」恢复）" if self._adult_paused
                else "成人/短剧/直播检测：继续检测…")
            self._update_detect_ui()

        def _stop_adult(self):
            """停止成人检测：worker 循环检测到标志后尽快退出（不强制 kill）。"""
            if self._closed or not self._scanning:
                return
            self._adult_stop = True
            self._adult_paused = False  # 退出暂停，让 worker 循环能走到停止检查
            try:
                if self._worker is not None:
                    self._worker.requestInterruption()
            except Exception:
                pass
            self.prog_label.setText("成人/短剧/直播检测：正在停止…")
            self._update_detect_ui()

        def _start_url(self):
            """开始 URL 可达性检测（不影响成人检测）。"""
            if self._closed or self._url_scanning:
                return
            self._url_stop = False
            self._url_paused = False
            self._url_started = True
            self._url_scanning = True
            self.url_map = {}
            self.url_label.setText("URL 可达性检测：准备…")
            self.url_bar.setRange(0, len(self.entries) or 1)
            self.url_bar.setValue(0)
            self._update_detect_ui()
            self._refresh_table()
            resolved = self._adult_resolved or {}
            name_map = self._adult_name_map or {}
            self._url_worker = _UrlCheckWorker(
                self, self.base_dir, self.entries, resolved, name_map,
                alt_dir=self.repo_dir, repo_dir=self.repo_dir,
                cfg_name=self.cfg_file, allow_prompt=False)
            self._url_worker.progress.connect(self._on_url_progress)
            self._url_worker.item_done.connect(self._on_url_item)
            self._url_worker.finished_map.connect(self._on_url_done)
            self._url_worker.finished.connect(self._url_worker.deleteLater)
            self._url_worker.start()

        def _pause_url(self):
            """暂停 / 继续 URL 检测（同一按钮切换）。"""
            if self._closed or not self._url_scanning:
                return
            self._url_paused = not self._url_paused
            self.url_label.setText(
                "URL 可达性检测：已暂停（点「继续」恢复）" if self._url_paused
                else "URL 可达性检测：继续检测…")
            self._update_detect_ui()

        def _stop_url(self):
            """停止 URL 检测：worker 循环检测到标志后尽快退出（不强制 kill）。"""
            if self._closed or not self._url_scanning:
                return
            self._url_stop = True
            self._url_paused = False  # 退出暂停，让 worker 循环能走到停止检查
            try:
                if self._url_worker is not None:
                    self._url_worker.requestInterruption()
            except Exception:
                pass
            self.url_label.setText("URL 可达性检测：正在停止…")
            self._update_detect_ui()

        # ---- 需特殊上网（代理）体检：复用 pyinj_netdiag.diagnose_source ----
        def scan_proxy_sites(self):
            """后台体检全部站点：判定哪些「需要特殊上网（代理）」，结果填入 proxy_map，
            供过滤下拉的「⚠️ 仅需特殊上网」使用。只读，不改配置。"""
            if self._closed or self._proxy_scanning:
                return
            if not self.entries:
                QMessageBox.information(self, "提示", "当前没有站点可体检。")
                return
            self._proxy_stop = False
            self._proxy_paused = False
            self._proxy_scanning = True
            self.proxy_map = {}
            self._toast("网络体检进行中…（可继续操作，完成后自动刷新）")
            self._proxy_worker = _ProxyCheckWorker(self, self.entries, self.base_dir)
            self._proxy_worker.finished_map.connect(self._on_proxy_done)
            self._proxy_worker.finished.connect(self._proxy_worker.deleteLater)
            self._proxy_worker.start()

        def _on_proxy_done(self, m):
            self._proxy_scanning = False
            self.proxy_map = dict(m or {})
            n = sum(1 for v in self.proxy_map.values() if v)
            self._refresh_table()
            self._toast("网络体检完成：%d 个站点可能需要特殊上网" % n)

        # ---- 共用检测控制（勾选类型 + 一套 开始/暂停/停止）----
        def _start_detect(self):
            """按勾选类型启动检测；已在跑的类型不受影响，只启动未跑的。"""
            if self._closed:
                return
            if self.cb_adult.isChecked() and not self._scanning:
                self._start_adult()
            if self.cb_url.isChecked() and not self._url_scanning:
                self._start_url()
            self._update_detect_ui()

        def _pause_detect(self):
            """暂停/继续：若当前有已暂停的则全部恢复，否则暂停所有在跑的。"""
            if self._closed:
                return
            any_paused = (self._scanning and self._adult_paused) or (self._url_scanning and self._url_paused)
            if any_paused:
                if self._scanning and self._adult_paused:
                    self._pause_adult()
                if self._url_scanning and self._url_paused:
                    self._pause_url()
            else:
                if self._scanning and not self._adult_paused:
                    self._pause_adult()
                if self._url_scanning and not self._url_paused:
                    self._pause_url()
            self._update_detect_ui()

        def _stop_detect(self):
            """停止所有在跑的检测。"""
            if self._closed:
                return
            if self._scanning:
                self._stop_adult()
            if self._url_scanning:
                self._stop_url()
            self._update_detect_ui()

        def _update_detect_ui(self):
            """按两路检测状态刷新共用控制按钮与类型勾选；任一路在跑/暂停时进入忙碌态。"""
            if self._closed:
                return
            a_run, u_run = self._scanning, self._url_scanning
            any_run = a_run or u_run
            any_paused = (a_run and self._adult_paused) or (u_run and self._url_paused)
            try:
                self.b_detect_start.setDisabled(any_run)
                self.b_detect_pause.setEnabled(any_run)
                self.b_detect_pause.setText("继续" if any_paused else "暂停")
                self.b_detect_stop.setEnabled(any_run)
                self.cb_adult.setEnabled(not any_run)
                self.cb_url.setEnabled(not any_run)
                self.cb_deep.setEnabled(not any_run)
            except Exception:
                pass
            self._set_busy(any_run)

        def _row_of_key(self, key):
            """按 key 在当前显示列表中定位表格行号（表格列已无 key 列，不能再读表格 item）。"""
            for i, e in enumerate(getattr(self, "_shown", [])):
                if str(e.get("key", "")) == str(key):
                    return i
            return -1

        def _update_url_cell(self, key, code, method, note):
            """按 key 找到表格行，实时写入可达列结果（不整体重绘，避免闪烁）。"""
            r = self._row_of_key(key)
            if r < 0:
                return
            if code == 1:
                txt = ("可达(%s)" % method) if method else "可达"
                ci = QTableWidgetItem(txt)
                ci.setForeground(QColor(20, 120, 40))
            elif code == 0:
                ci = QTableWidgetItem("不可达")
                ci.setForeground(QColor(200, 30, 30))
            else:
                ci = QTableWidgetItem(note or "无URL")
                ci.setForeground(QColor(110, 110, 110))
            self.table.setItem(r, 7, ci)   # 可达列（key 列移除后为第 7 列）

        # 参数不走 Q_ARG/Q_RETURN_ARG：Qt5/PySide2 没有这两个别名（Q_ARG 直通会段错误）。
        # 统一改成「无参槽 + 属性传递」：调用方先把 payload 写到 self._pending_missing，
        # 再无参 invokeMethod（BlockingQueuedConnection 保证槽已在本线程跑完），结果取 _pending_result。
        @Slot()
        def prompt_py_dir(self):
            """主线程弹框：让用户手动选择 .py 目录（自动遍历仍未找到时触发）。
            入参取自 self._pending_missing，结果写入 self._pending_result。"""
            import json
            try:
                missing_names = json.loads(self._pending_missing or "[]") or []
            except Exception:
                missing_names = []
            if self._closed:
                self._pending_result = ""
                return
            names = "、".join(missing_names[:8]) + ("…" if len(missing_names) > 8 else "")
            QMessageBox.information(
                self, "未找到 Spider 源文件",
                "自动遍历搜索后，仍有 %d 个 Spider 源的文件未找到（例如：%s）。\n"
                "请手动选择 spider 文件（.py/.js/.jar）所在目录。"
                % (len(missing_names), names))
            d = QFileDialog.getExistingDirectory(self, "选择 spider 文件所在目录", self.base_dir)
            self._pending_result = d or ""

        def _update_adult_cell(self, key, is_adult):
            """按 key 找到表格行，实时写入成人列结果（不整体重绘，避免闪烁）。"""
            r = self._row_of_key(key)
            if r < 0:
                return
            txt = "是(检)" if is_adult else "否"
            ci = QTableWidgetItem(txt)
            if is_adult:
                ci.setForeground(QColor(200, 30, 30))
            self.table.setItem(r, 4, ci)

        def _update_duanju_cell(self, key, is_dj):
            """按 key 找到表格行，实时写入短剧列结果（不整体重绘，避免闪烁）。"""
            r = self._row_of_key(key)
            if r < 0:
                return
            ci = QTableWidgetItem("是(检)" if is_dj else "否")
            if is_dj:
                ci.setForeground(QColor(200, 130, 20))  # 短剧源标橙
            self.table.setItem(r, 5, ci)

        def _update_live_cell(self, key, is_live):
            """按 key 找到表格行，实时写入直播列结果（不整体重绘，避免闪烁）。"""
            r = self._row_of_key(key)
            if r < 0:
                return
            ci = QTableWidgetItem("是(检)" if is_live else "否")
            if is_live:
                ci.setForeground(QColor(150, 60, 180))  # 直播源标紫
            self.table.setItem(r, 6, ci)

        def resizeEvent(self, ev):
            """窗口尺寸变化时，让 name 列吸收/让出多余空间（用户手动拖过则不再干预）。

            布局刷新滞后于 resize 事件：此处用 singleShot(0) 延后一帧，等 viewport
            宽算完再分配，避免拿到旧宽度。"""
            try:
                super().resizeEvent(ev)
            except Exception:
                pass
            if not getattr(self, "_name_user_resized", False):
                try:
                    QTimer.singleShot(0, self._fit_name_column)
                except Exception:
                    self._fit_name_column()

        def showEvent(self, ev):
            """首次展示后（布局已算完）分配一次 name 列弹性宽度。"""
            try:
                super().showEvent(ev)
            except Exception:
                pass
            if not getattr(self, "_name_user_resized", False):
                try:
                    QTimer.singleShot(0, self._fit_name_column)
                except Exception:
                    pass

        def _fit_name_column(self):
            """把「表格视口宽 - 其余列宽之和」分给 name 列，实现自适应（不锁死拖动）。

            用户手动拖过 name 列（_name_user_resized）则直接返回，尊重用户选择——
            该标志在这里自查，防止 singleShot 延迟回调绕过调用点的判断。"""
            if getattr(self, "_name_user_resized", False):
                return
            try:
                viewport = self.table.viewport().width()
                others = 0
                for c in range(1, self.table.columnCount()):
                    if not self.table.isColumnHidden(c):
                        others += self.table.columnWidth(c)
                w = min(max(viewport - others - 2, 120), 600)
                if abs(self.table.columnWidth(0) - w) > 2:
                    self.table.setColumnWidth(0, w)
            except Exception:
                pass

        # 各列「按内容自适应」时的宽度上下限（表头/内容都很短时不必占那么宽）
        _COL_MIN = {1: 90, 2: 62, 3: 96, 4: 52, 5: 52, 6: 52, 7: 62, 8: 52, 9: 62}
        _COL_MAX = {1: 240, 2: 90, 3: 130, 4: 70, 5: 70, 6: 70, 7: 80, 8: 70, 9: 80}

        def _auto_fit_other_columns(self):
            """第 1–9 列严格按内容自适应：逐列按「表头 + 全部单元格」的需求宽取值，
            再用各列专属的 [min,max] 夹紧，避免短列被全局下限顶宽（用户反馈：
            实际宽度远超内容需求）。name 列（0）不在此处处理，由 _fit_name_column 弹性分配。"""
            if getattr(self, "_cols_user_resized", False):
                return
            try:
                fm = self.table.fontMetrics()
                for c in range(1, self.table.columnCount()):
                    if self.table.isColumnHidden(c):
                        continue
                    # 表头需求宽
                    hi = self.table.horizontalHeaderItem(c)
                    need = fm.horizontalAdvance(hi.text() if hi else "") + 22
                    # 内容需求宽（取最宽的单元格，最多看前 300 行防卡顿）
                    rows = min(self.table.rowCount(), 300)
                    for r in range(rows):
                        it = self.table.item(r, c)
                        if it is not None:
                            need = max(need, fm.horizontalAdvance(it.text()) + 20)
                    lo = self._COL_MIN.get(c, 52)
                    hi_w = self._COL_MAX.get(c, 120)
                    self.table.setColumnWidth(c, int(min(max(need, lo), hi_w)))
            except Exception:
                pass

        def _on_user_col_resized(self, idx, new_width):
            """**仅用户在表头上真实拖动分隔条**后触发（程序调宽不触发，见 _UserAwareHHeader）。

            拖第 0 列（name）→ 停止 name 自适应；拖其它列 → 记录用户自定义列宽，
            此后不再自动收缩（尊重用户选择）。"""
            try:
                if idx == 0:
                    self._name_user_resized = True
                else:
                    self._cols_user_resized = True
                    if not getattr(self, "_name_user_resized", False):
                        self._fit_name_column()
            except Exception:
                pass

        def closeEvent(self, ev):
            # 未保存保护：有待写入的删除/修改时，给出 保存 / 放弃 / 取消 三选
            if getattr(self, "removed_keys", None) or getattr(self, "modified", None):
                box = QMessageBox(
                    QMessageBox.Question, "有未保存的更改",
                    "删除/修改尚未写入配置文件。\n\n退出前要保存吗？",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, self)
                box.setButtonText(QMessageBox.Save, "保存并写入")
                box.setButtonText(QMessageBox.Discard, "放弃更改")
                box.setButtonText(QMessageBox.Cancel, "取消")
                r = box.exec()
                if r == QMessageBox.Cancel:
                    ev.ignore()
                    return
                if r == QMessageBox.Save:
                    self.save()          # save 成功后自行 accept()；失败则留在界面
                    ev.ignore()
                    return
            self._teardown_persist()
            # 关闭时标记，避免后台线程回调已销毁的控件；并请求线程退出
            self._closed = True
            try:
                self._worker.quit()
            except Exception:
                pass
            try:
                if getattr(self, "_url_worker", None) is not None:
                    self._url_worker.quit()
            except Exception:
                pass
            super().closeEvent(ev)

        def _teardown_persist(self):
            """关闭前持久化：窗口几何与手动调整的列宽（带上下限 [46,220]，防旧布局错位值挤没 name 列）。

            仅当用户**手动拖过非 name 列**时才保存 cfg/colwidth/* 并置 cfg/cols_user_resized，
            否则这些键保持清空 → 下次仍走「按内容自适应」，不会被偏宽的旧值污染。"""
            try:
                st = QSettings("PyInjector", "PyInjector")
                st.setValue("cfg/geometry", self.saveGeometry())
                if getattr(self, "_cols_user_resized", False):
                    st.setValue("cfg/cols_user_resized", True)
                    for c in range(1, 10):
                        st.setValue("cfg/colwidth/%d" % c,
                                    min(max(self.table.columnWidth(c), 46), 220))
                else:
                    st.setValue("cfg/cols_user_resized", False)
                    for c in range(1, 10):
                        st.remove("cfg/colwidth/%d" % c)
                # name 列（第 0 列）单独存，宽度上限放宽到 600（内容自适应列）
                st.setValue("cfg/namewidth",
                            min(max(self.table.columnWidth(0), 120), 600))
            except Exception:
                pass

        def log_msg(self, msg, level="info"):
            # ConfigDialog 没有日志区：容错回退，避免 save() 异常路径报 AttributeError
            try:
                sys.stderr.write("[PyInjector] %s\n" % msg)
            except Exception:
                pass

        def _build(self):
            root = QVBoxLayout(self)

            # 检测状态面板：成人检测与 URL 可达性检测完全分离——各占一行、
            # 各有一条进度条，且各自带 开始/暂停(继续)/停止 三个按钮（放在状态条后、右对齐），
            # 默认不自动开始（避免打开界面即焦虑）
            detect_grp = QGroupBox("后台检测（勾选类型 · 共用控制）")
            self.detect_grp = detect_grp  # 供 .py 存在性检测完成后更新汇总标题
            detect_gv = QVBoxLayout(detect_grp)
            detect_gv.setContentsMargins(10, 8, 10, 8)
            detect_gv.setSpacing(4)

            # 检测类型勾选（共用控制前先选要跑哪些）
            ct = QHBoxLayout()
            ct.setContentsMargins(0, 0, 0, 0)
            self.cb_adult = QCheckBox("成人 / 短剧 / 直播")
            self.cb_adult.setChecked(True)
            self.cb_url = QCheckBox("URL 可达性")
            self.cb_url.setChecked(True)
            self.cb_deep = QCheckBox("深度检测（拉取直连站API内容，较慢）")
            self.cb_deep.setChecked(False)
            self.cb_deep.setToolTip(
                "对 type 0/1 直连站拉取 api 页面内容做关键词匹配（每站一次网络请求）。\n"
                "关闭时直连站仅按「站点名 + ext 字段」判定，速度快但可能漏检。")
            ct.addWidget(self.cb_adult)
            ct.addWidget(self.cb_url)
            ct.addWidget(self.cb_deep)
            ct.addStretch(1)
            detect_gv.addLayout(ct)

            self.prog_box = QWidget()
            pv = QVBoxLayout(self.prog_box)
            pv.setContentsMargins(0, 0, 0, 0)
            pv.setSpacing(2)

            def _mkdbtn(text, slot, enabled=True, fixed=True):
                b = QPushButton(text)
                if fixed:
                    b.setFixedWidth(64)
                b.setEnabled(enabled)
                b.clicked.connect(slot)
                return b

            row1 = QHBoxLayout()
            row1.setContentsMargins(0, 0, 0, 0)
            self.prog_label = QLabel("成人/短剧/直播检测：未开始 · 勾选后点「开始」")
            self.prog_bar = QProgressBar()
            self.prog_bar.setObjectName("adultBar")
            self.prog_bar.setRange(0, len(self.entries) or 1)
            self.prog_bar.setValue(0)
            self.prog_bar.setTextVisible(True)
            row1.addWidget(self.prog_label, 1)
            row1.addWidget(self.prog_bar, 2)
            pv.addLayout(row1)

            row2 = QHBoxLayout()
            row2.setContentsMargins(0, 0, 0, 0)
            self.url_label = QLabel("URL 可达性检测：未开始 · 勾选后点「开始」")
            self.url_bar = QProgressBar()
            self.url_bar.setObjectName("urlBar")
            self.url_bar.setRange(0, len(self.entries) or 1)
            self.url_bar.setValue(0)
            self.url_bar.setTextVisible(True)
            row2.addWidget(self.url_label, 1)
            row2.addWidget(self.url_bar, 2)
            pv.addLayout(row2)
            # 渐变色进度条：成人检测=暖色（橙→红），URL 检测=冷色（青→蓝）；背景随主题
            _pb_bg = "#2b2f36" if IS_DARK else "#eef1f5"
            _pb_bd = "#3c424b" if IS_DARK else "#cfd8e3"
            _pb_fg = "#e6e9ed" if IS_DARK else "#333"
            self.prog_box.setStyleSheet(
                "QProgressBar { background:%s; border:1px solid %s;"
                " border-radius:4px; min-height:16px; text-align:center; color:%s; }"
                " QProgressBar::chunk { border-radius:3px; }"
                " QProgressBar#adultBar::chunk { background: qlineargradient("
                "x1:0,y1:0,x2:1,y2:0, stop:0 #ff9d4d, stop:1 #ff5470); }"
                " QProgressBar#urlBar::chunk { background: qlineargradient("
                "x1:0,y1:0,x2:1,y2:0, stop:0 #36d1dc, stop:1 #5b86e5); }"
                % (_pb_bg, _pb_bd, _pb_fg))
            detect_gv.addWidget(self.prog_box)

            # 共用控制行：勾选哪些就跑哪些，暂停/停止同时作用于在跑的类型
            ctrl = QHBoxLayout()
            ctrl.setContentsMargins(0, 0, 0, 0)
            self.b_detect_start = _mkdbtn("开始", self._start_detect, fixed=False)
            self.b_detect_pause = _mkdbtn("暂停", self._pause_detect, enabled=False, fixed=False)
            self.b_detect_stop = _mkdbtn("停止", self._stop_detect, enabled=False, fixed=False)
            ctrl.addWidget(self.b_detect_start)
            ctrl.addWidget(self.b_detect_pause)
            ctrl.addWidget(self.b_detect_stop)
            ctrl.addStretch(1)
            detect_gv.addLayout(ctrl)
            root.addWidget(detect_grp)

            # 搜索行：现代风——无标签、框内搜索占位符 + 内置清空 ×，回车跳下一个匹配
            self._busy_buttons = []   # 检测期间禁用的按钮（关闭按钮除外）
            sh = QHBoxLayout()
            # 过滤下拉：兼容原有「按 type」过滤，并新增「仅成人 / 仅需特殊上网」两个维度
            # （保留旧选项，不删除；新增项排在后面，用 _filter_spec 描述过滤方式）
            self.type_filter = QComboBox()
            self.type_filter.addItems([
                "全部类型", "直连 CMS (1)", "Spider (3)", "XML (0)", "目录型 (4)",
                "🔞 仅成人", "⚠️ 仅需特殊上网", "⛔ 仅失效源",
            ])
            self.type_filter.setToolTip(
                "过滤表格：按接口类型 0=XML / 1=JSON直连(CMS) / 3=Spider(含 .py/.js/.jar/csp_) / 4=目录型；"
                "或只看 🔞 成人站点、⚠️ 需特殊上网（代理）站点（后者需先在工具箱跑过网络诊断）、"
                "⛔ 仅失效源（URL 不可达或本地脚本缺失，需先跑对应检测）")
            self.type_filter.setMinimumWidth(140)
            self.type_filter.currentIndexChanged.connect(self._on_type_filter)
            # 过滤规则表：下标 -> ("type", t) / ("adult",) / ("proxy",) / ("dead",)，None=全部
            self._filter_spec = [None,
                                 ("type", 1), ("type", 3), ("type", 0), ("type", 4),
                                 ("adult",), ("proxy",), ("dead",)]
            self._type_filter = None
            sh.addWidget(self.type_filter)
            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText("🔍 输入 key / name / api 筛选（回车 = 下一个匹配）…")
            self.search_edit.setClearButtonEnabled(True)
            self.search_edit.textChanged.connect(self._on_search)
            try:
                self.search_edit.returnPressed.connect(self._find_next)
            except Exception:
                pass
            sh.addWidget(self.search_edit, 1)
            self.lbl_count = QLabel("")
            sh.addWidget(self.lbl_count)
            root.addLayout(sh)

            self.table = QTableWidget(0, 10)
            self.table.setHorizontalHeaderLabels(list(self._base_headers))
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            # 右键上下文菜单（现代桌面应用核心交互）
            try:
                self.table.setContextMenuPolicy(Qt.CustomContextMenu)
                self.table.customContextMenuRequested.connect(self._show_ctx_menu)
            except Exception:
                pass
            # api 列悬停手型光标（链接可点击的视觉暗示）
            try:
                self.table.setMouseTracking(True)
                self.table.viewport().installEventFilter(self)
            except Exception:
                pass

            # 行号列（垂直表头）跟随数据行斑马纹：系统默认的行号列是独立灰条，
            # 且 header item 的 setBackground 在本 Qt 版本下不渲染（已实测），
            # 故自定义 QHeaderView 逐段绘制：奇偶行底色与数据区完全一致。
            class _ZebraVHeader(QHeaderView):
                def __init__(self, table):
                    try:
                        super().__init__(Qt.Vertical, table)
                    except Exception:      # mock 环境下 Qt.Vertical 可能不存在
                        super().__init__()
                    self._alt = QColor("#eef4fb")
                    self._base = QColor("#ffffff")
                    self._line = QColor(208, 216, 227)
                    self._txt = QColor(80, 90, 105)
                    try:
                        self.setDefaultAlignment(Qt.AlignCenter)
                    except Exception:
                        pass

                def paintSection(self, painter, rect, idx):
                    try:
                        painter.save()
                        painter.fillRect(rect, self._alt if idx % 2 == 1 else self._base)
                        painter.setPen(self._line)
                        painter.drawLine(rect.right(), rect.top(),
                                         rect.right(), rect.bottom())
                        painter.setPen(self._txt)
                        painter.drawText(rect, Qt.AlignCenter, str(idx + 1))
                        painter.restore()
                    except Exception:
                        pass

            self.table.setVerticalHeader(_ZebraVHeader(self.table))

            # 水平表头：自定义类**精确识别「用户真的拖动分隔条」**——
            # QHeaderView.sectionResized 会被程序自身 setColumnWidth 与布局刷新触发
            # （实测 show/resize 也会发），仅靠该信号无法区分用户操作，
            # 故在 mousePress 命中分隔条（cursor == SplitHCursor）时记下段号，
            # mouseRelease 时回调 on_user_resized（程序调宽则永不触发）。
            class _UserAwareHHeader(QHeaderView):
                def __init__(self, table):
                    try:
                        super().__init__(Qt.Horizontal, table)
                    except Exception:
                        super().__init__()
                    self._drag_sec = None
                    self.on_user_resized = None

                def mousePressEvent(self, ev):
                    try:
                        if self.cursor().shape() == Qt.SplitHCursor:
                            self._drag_sec = self.logicalIndexAt(ev.pos())
                    except Exception:
                        self._drag_sec = None
                    try:
                        super().mousePressEvent(ev)
                    except Exception:
                        pass

                def mouseReleaseEvent(self, ev):
                    sec = self._drag_sec
                    self._drag_sec = None
                    try:
                        super().mouseReleaseEvent(ev)
                    except Exception:
                        pass
                    try:
                        if sec is not None and sec >= 0 and callable(self.on_user_resized):
                            self.on_user_resized(sec, self.sectionSize(sec))
                    except Exception:
                        pass

            self._hheader = _UserAwareHHeader(self.table)
            self.table.setHorizontalHeader(self._hheader)
            self._hheader.on_user_resized = self._on_user_col_resized

            # 交错行底色（斑马纹）+ 浅色现代表头 + 行内边距（更透气的行高）
            self.table.setAlternatingRowColors(True)
            if IS_DARK:
                self.table.setStyleSheet(
                    "QTableWidget { alternate-background-color: #262b32; background: #1f2329; }"
                    "QTableWidget::item { padding: 5px 8px; }"
                    "QTableWidget::item:selected { background: #34538a; color: #ffffff; }"
                    "QTableWidget::item:!selected:hover { background: transparent; }"
                    "QHeaderView::section:horizontal { background: #2b2f36; color: #cdd3da;"
                    "font-weight: bold; padding: 6px 8px; border: none;"
                    "border-right: 1px solid #3c424b; border-bottom: 2px solid #5b8fd6; }"
                    "QTableCornerButton::section { background: #2b2f36; border: none; }")
            else:
                self.table.setStyleSheet(
                    "QTableWidget { alternate-background-color: #eef4fb; background: #ffffff; }"
                    "QTableWidget::item { padding: 5px 8px; }"
                    "QTableWidget::item:selected { background: #cfe4f7; color: #1f2933; }"
                    "QTableWidget::item:!selected:hover { background: transparent; }"
                    "QHeaderView::section:horizontal { background: #f5f7fa; color: #2c3e50;"
                    "font-weight: bold; padding: 6px 8px; border: none;"
                    "border-right: 1px solid #e3e8ef; border-bottom: 2px solid #34538a; }"
                    "QTableCornerButton::section { background: #f5f7fa; border: none; }")
            # 各列自适应：全部列均为交互式（可拖动调宽）。name 列作为「弹性列」
            # 吸收窗口多余空间（Stretch 模式会锁死拖动，故用 Interactive + 动态分配）；
            # 其余列**严格按内容自适应**（不过宽、也不被 76px 下限顶宽）。
            hdr = self.table.horizontalHeader()
            hdr.setSectionResizeMode(QHeaderView.Interactive)
            # 保底宽度只给到较小值：name 列本就 clamp ≥120，无需全局 76 把短列顶宽
            hdr.setMinimumSectionSize(46)
            try:
                _st = QSettings("PyInjector", "PyInjector")
                # name 列按内容自适应，限制在合理区间（其后由 resizeEvent 吸收多余空间）
                _nm = self.table.columnWidth(0)
                self.table.setColumnWidth(0, min(max(_nm + 16, 120), 320))
                # 只有当用户**确实手动拖过列宽**（cfg/cols_user_resized）时才回放存储值；
                # 否则保持「按内容自适应」——避免旧版本遗留的偏宽值一直生效（用户实发反馈）
                _user_cols = _st.value("cfg/cols_user_resized", False, type=bool)
                if _user_cols:
                    for _c in range(1, 10):
                        _w = _st.value("cfg/colwidth/%d" % _c, 0, type=int)
                        if _w and _w > 20:
                            self.table.setColumnWidth(_c, min(max(_w, 46), 220))
                    self._cols_user_resized = True
                # name 列也恢复用户上次手动调宽（key 单独存，避免与旧值冲突）
                _nw = _st.value("cfg/namewidth", 0, type=int)
                if _nw and _nw > 40:
                    self.table.setColumnWidth(0, min(max(_nw, 120), 600))
                    self._name_user_resized = True
            except Exception:
                pass
            # 用户真实拖动分隔条 → 经 _UserAwareHHeader.on_user_resized 回调
            # （不用 sectionResized：它会被程序自身调宽触发，无法区分）
            # 首次展示后把剩余空间分给 name 列（等布局算完视口宽再调，避免拿到 0）
            self._fit_name_column()
            # 点击字段名排序（自定义排序，兼容 type 数值列与成人列的特殊显示）
            self.table.horizontalHeader().setSectionsClickable(True)
            self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
            # 恢复上次会话的排序指示器
            if self._sort_col >= 0:
                try:
                    self.table.horizontalHeader().setSortIndicator(
                        self._sort_col,
                        Qt.AscendingOrder if self._sort_asc else Qt.DescendingOrder)
                    self.table.horizontalHeader().setSortIndicatorShown(True)
                except Exception:
                    pass
            # 点击 api 列（第 1 列）→ 用系统默认程序打开对应 .py；双击其他列 → 编辑该站点
            self.table.cellClicked.connect(self._on_api_cell_clicked)
            self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
            # 选中变化时联动「禁用选中/启用选中」按钮的可用性
            self.table.itemSelectionChanged.connect(self._update_action_buttons)
            root.addWidget(self.table)
            # 表格空状态：搜索无结果（或列表为空）时在表格中央显示提示，
            # 用叠层 QLabel 实现（不挡鼠标交互），_refresh_table 末尾按 _shown 显隐
            self.empty_label = QLabel("没有匹配的站点")
            self.empty_label.setAlignment(Qt.AlignCenter)
            self.empty_label.setStyleSheet(
                "color:#9aa7b5; font-size:14px; font-weight:bold; background:transparent;")
            self.empty_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            try:
                self.empty_label.setParent(self.table.viewport())
            except Exception:
                pass
            self.empty_label.hide()
            # 底部操作条：按钮多达 14 个，若挤在一行会把对话框最小宽度撑到上千像素
            # （导致表格上方出现大片空白、窗口被强行撑宽）。改为**两行分组网格**：
            #   第 1 行：批量操作（删除/禁用/启用/禁用短剧/禁用直播）
            #   第 2 行：检测工具（源测活/网络体检/工具箱）+ 导出（导出干净/智能分流）
            #   右下角固定：保存并写入（主操作）+ 关闭
            # QGridLayout 不强制一行放完，按钮条的「最小宽度」回落到单行最宽分组，
            # 对话框宽度重新由表格内容决定，空白区域消失。
            self._btn_disable = None
            self._btn_enable = None

            def _mk_btn(txt, fn, accent=None, busy=False):
                b = QPushButton(txt, clicked=fn)
                if accent:
                    b.setProperty("accent", accent)
                b.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                if busy:
                    self._busy_buttons.append(b)
                return b

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(6)

            # ---- 第 1 行：批量操作 ----
            batch = [("🗑 删除选中", self.del_row, "danger"),
                     ("禁用选中", self.disable_selected, None),
                     ("启用选中", self.enable_selected, None),
                     ("禁用短剧", self.disable_duanju, None),
                     ("禁用直播", self.disable_live, None),
                     ("🧹 剔除失效源", self.purge_dead_sources, None)]
            for i, (txt, fn, accent) in enumerate(batch):
                b = _mk_btn(txt, fn, accent, busy=True)
                grid.addWidget(b, 0, i)
                if txt == "禁用选中":
                    self._btn_disable = b
                elif txt == "启用选中":
                    self._btn_enable = b

            # ---- 第 2 行：检测工具 + 导出 ----
            tools = [("🩺 源测活", self.probe_config, None),
                     ("🌐 网络体检", self.scan_proxy_sites, None),
                     ("🧰 工具箱", self.open_toolbox, None),
                     ("📤 导出干净配置", self.export_config, None),
                     ("🔀 智能分流导出", self.split_export, None)]
            for i, (txt, fn, accent) in enumerate(tools):
                grid.addWidget(_mk_btn(txt, fn, accent), 1, i)

            # grid 左侧弹性 + 右下角主操作/关闭
            grid.setColumnStretch(len(batch), 1)
            b_save = _mk_btn("💾 保存并写入", self.save, "primary", busy=True)
            grid.addWidget(b_save, 0, len(batch), 1, 2,
                           Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(_mk_btn("关闭", self.close), 1, len(tools),
                           Qt.AlignRight | Qt.AlignVCenter)
            root.addLayout(grid)

            # 底部状态行：瞬时提示（toast，替代部分弹窗）；计数在搜索行右侧
            srow = QHBoxLayout()
            self.lbl_toast = QLabel("")
            self.lbl_toast.setStyleSheet("color:#1e7e34; font-weight:bold;")
            srow.addWidget(self.lbl_toast, 1)
            root.addLayout(srow)

            # 快捷键（现代应用标配；mock 测试环境无 QShortcut，静默跳过）
            try:
                QShortcut(QKeySequence("Ctrl+F"), self,
                          activated=lambda: self.search_edit.setFocus())
                QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save)
                QShortcut(QKeySequence(QKeySequence.Delete), self.table,
                          activated=self.del_row)
                QShortcut(QKeySequence("F5"), self, activated=self._f5_refresh)
                QShortcut(QKeySequence("Esc"), self, activated=self._esc_pressed)
            except Exception:
                pass
            # 打开界面即平静态：两路检测均未运行，所有按钮可用；再按选中态（无选中）联动禁用/启用按钮
            self._update_detect_ui()
            self._update_action_buttons()

        # ---- 快捷键 / toast / 上下文菜单 / 手型光标 ----
        def _f5_refresh(self):
            """F5：重新检测 .py 存在性并刷新表格。"""
            if self._closed:
                return
            self._start_file_check()
            self._refresh_table()
            self._toast("已刷新")

        def _esc_pressed(self):
            """Esc：搜索框有内容先清空，否则关闭对话框。"""
            if getattr(self, "search_edit", None) is not None and self.search_edit.text():
                self._clear_search()
            else:
                self.close()

        def _toast(self, msg, ms=4000):
            """非模态瞬时提示（4s 自动消失），替代低风险操作的结果弹窗。"""
            if getattr(self, "_closed", False):
                return
            self._toast_msg = msg
            self.lbl_toast.setText("✓ " + msg)
            try:
                QTimer.singleShot(ms, self._toast_clear)
            except Exception:
                pass

        def _toast_clear(self):
            if getattr(self, "_closed", False):
                return
            if getattr(self, "lbl_toast", None) is not None and \
                    self.lbl_toast.text() == "✓ " + getattr(self, "_toast_msg", ""):
                self.lbl_toast.setText("")

        def eventFilter(self, obj, ev):
            """api 列（第 1 列）悬停显示手型光标——链接可点击的视觉暗示。"""
            try:
                if obj is self.table.viewport() and ev.type() == QEvent.MouseMove \
                        and not getattr(self, "_closed", False):
                    idx = self.table.indexAt(ev.position().toPoint())
                    r, c = idx.row(), idx.column()
                    local = (0 <= r < len(self._shown)
                             and c == 1
                             and "://" not in str(self._shown[r].get("api", "")))
                    self.table.viewport().setCursor(
                        Qt.PointingHandCursor if local else Qt.ArrowCursor)
            except Exception:
                pass
            return super().eventFilter(obj, ev)

        def _show_ctx_menu(self, pos):
            """表格右键菜单：编辑 / 打开（按 type 分流）/ 复制 api / 禁用 / 启用 / 删除。"""
            if self._closed:
                return
            row = self.table.rowAt(pos.y())
            if 0 <= row < len(self._shown):
                # 点击行不在当前多选内时，切换为单选该行；在多选内则保留整组选中
                try:
                    if not self.table.selectionModel().isRowSelected(row):
                        self.table.selectRow(row)
                except Exception:
                    self.table.selectRow(row)
            sel_rows = self._selected_rows()
            if not sel_rows:
                return
            menu = QMenu(self)
            e = self._shown[sel_rows[0]]
            api = str(e.get("api", ""))
            menu.addAction("✏️ 编辑", self.edit_row)

            # 「打开」动作按 type 动态变文案/图标：不同 type 打开的东西完全不同。
            tgt = open_target_of(e, self.base_dir, self.repo_dir,
                                 resolved_py=self.file_reloc.get(str(e.get("key", ""))))
            _kind_icon = {"file": "📄", "jar": "📦", "url": "🔗", "dir": "📂"}
            _kind_text = {"file": "打开脚本文件", "jar": "打开所依赖的 jar",
                          "url": tgt.get("label") or "打开 API 链接",
                          "dir": tgt.get("label") or "打开目录"}
            if tgt["kind"] in _kind_icon:
                menu.addAction("%s %s" % (_kind_icon[tgt["kind"]],
                                          _kind_text.get(tgt["kind"], tgt.get("label") or "打开")),
                               lambda: self._open_entry_target(
                                   e, resolved_py=self.file_reloc.get(str(e.get("key", "")))))
            elif tgt["kind"] == "none":
                act_none = menu.addAction("⚠️ 无本地文件/链接")
                act_none.setEnabled(False)

            act_copy = menu.addAction("📋 复制 api（%s…）" % api[:40])
            act_copy.triggered.connect(
                lambda: (QApplication.clipboard().setText(api), self._toast("api 已复制")))
            menu.addSeparator()
            menu.addAction("🚫 禁用选中", self.disable_selected)
            menu.addAction("✅ 启用选中", self.enable_selected)
            menu.addSeparator()
            menu.addAction("🗑 删除选中", self.del_row)
            menu.addSeparator()
            menu.addAction("🔍 查重", self.check_dups)
            menu.addAction("♻ 去重", self.dedup)
            menu.addSeparator()
            menu.addAction("🧹 剔除失效源（不可达/缺文件）", self.purge_dead_sources)
            menu.exec(self.table.viewport().mapToGlobal(pos))

        def _set_busy(self, busy):
            """检测期间禁用除「关闭」外的所有交互控件，防止检测中改动配置。"""
            if getattr(self, "_closed", False):
                return
            self._busy = busy
            for b in getattr(self, "_busy_buttons", []):
                try:
                    b.setEnabled(not busy)
                except Exception:
                    pass
            se = getattr(self, "search_edit", None)
            if se is not None:
                try:
                    se.setEnabled(not busy)
                except Exception:
                    pass
            if not busy:
                # 恢复后禁用/启用按钮不能无脑全开，要按当前选中项的禁用状态重算
                self._update_action_buttons()

        def _update_action_buttons(self):
            """按当前选中项联动按钮：无选中→双灰；选中含启用项→「禁用选中」亮，
            含禁用项→「启用选中」亮；混合多选时两者同时亮（各自只作用于对应状态的项）。"""
            if getattr(self, "_closed", False) or getattr(self, "_busy", False):
                return   # 忙碌（检测）期间保持全灰，由 _set_busy(False) 收尾时统一恢复
            bd = getattr(self, "_btn_disable", None)
            be = getattr(self, "_btn_enable", None)
            if bd is None or be is None:
                return
            shown = getattr(self, "_shown", [])
            sel = [shown[r] for r in self._selected_rows()]
            has_enabled = any(not e.get("_disabled", False) for e in sel)
            has_disabled = any(bool(e.get("_disabled", False)) for e in sel)
            try:
                bd.setEnabled(has_enabled)
                be.setEnabled(has_disabled)
            except Exception:
                pass

        def _refresh_table(self):
            # 记住刷新前的全部选中行（按 key），重建表格后恢复整组选中，
            # 避免刷新丢选中/按钮联动失真（多选批量操作依赖这一点）
            shown0 = getattr(self, "_shown", [])
            try:
                sel_rows = sorted({idx.row() for idx in
                                   self.table.selectionModel().selectedRows()})
            except Exception:
                sel_rows = []
            if not sel_rows:
                cur_row = self.table.currentRow()
                if 0 <= cur_row < len(shown0):
                    sel_rows = [cur_row]
            sel_keys = {str(shown0[r].get("key", "")) for r in sel_rows
                        if 0 <= r < len(shown0)}
            kw = ""
            if hasattr(self, "search_edit") and self.search_edit is not None:
                kw = self.search_edit.text().strip().lower()
            if kw:
                self._shown = [e for e in self.entries
                               if kw in str(e.get("key", "")).lower()
                               or kw in str(e.get("name", "")).lower()
                               or kw in str(e.get("api", "")).lower()]
            else:
                self._shown = list(self.entries)
            # 按过滤维度收窄（下拉框）：type(0/1/3/4) / 仅成人 / 仅需特殊上网
            tf = getattr(self, "_type_filter", None)
            if tf is not None:
                kind = tf[0]
                if kind == "type":
                    want = tf[1]

                    def _cat(e):
                        t = _norm_type(e.get("type"))
                        if t is None:
                            t = infer_type(str(e.get("api", "")))
                        return t
                    self._shown = [e for e in self._shown if _cat(e) == want]
                elif kind == "adult":
                    self._shown = [e for e in self._shown if self._adult_of(e)[0]]
                elif kind == "proxy":
                    pm = getattr(self, "proxy_map", None) or {}
                    self._shown = [e for e in self._shown
                                   if pm.get(str(e.get("key", "")), False)]
                elif kind == "dead":
                    # 仅看已判定失效的（URL 不可达 / 本地脚本缺失）；未检测的不算
                    _dk = set(dead_source_keys(self.entries, self.url_map,
                                               getattr(self, "file_map", None))["keys"])
                    self._shown = [e for e in self._shown
                                   if str(e.get("key", "")) in _dk]
            # 应用点击表头排序（保持搜索过滤后的结果再排序）
            if self._sort_col >= 0:                self._shown.sort(
                    key=lambda e, c=self._sort_col: self._sort_key(e, c),
                    reverse=not self._sort_asc)
            self._update_header_arrows()
            self.table.setRowCount(0)
            for e in self._shown:
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(str(e.get("name", ""))))
                api = str(e.get("api", ""))
                api_item = QTableWidgetItem(api)
                # 链接化视觉：本地源=蓝色下划线（可点击打开）；远程源=灰色无下划线（无本地文件）
                if "://" in api:
                    api_item.setForeground(QColor(110, 110, 110))
                    api_item.setToolTip("远程源（无本地 .py 文件）")
                else:
                    api_item.setForeground(QColor(0, 102, 204))
                    f = QFont()
                    f.setUnderline(True)
                    api_item.setFont(f)
                    api_item.setToolTip("点击用系统默认程序打开对应 .py")
                self.table.setItem(r, 1, api_item)
                # 第 2 列：类型（友好显示 type 数字 + 中文名，便于一眼区分直连/Spider）
                _t = _norm_type(e.get("type"))
                if _t is None:
                    _t = infer_type(api)
                _tmap = {0: "0·XML", 1: "1·直连", 3: "3·Spider", 4: "4·目录"}
                _tlabel = _tmap.get(_t, str(e.get("type", "")) if e.get("type") not in (None, "") else "—")
                self.table.setItem(r, 2, QTableWidgetItem(_tlabel))
                fl = "%s/%s/%s" % (e.get("filterable", 1), e.get("quickSearch", 1), e.get("searchable", 1))
                self.table.setItem(r, 3, QTableWidgetItem(fl))
                # 检测进行中且本行尚未检测完：显示「检测中…」；未开始过：显示「未检测」
                if self._scanning and str(e.get("key", "")) not in self.detect_map:
                    adult_item = QTableWidgetItem("检测中…")
                    adult_item.setForeground(QColor(110, 110, 110))
                elif not self._adult_started:
                    adult_item = QTableWidgetItem("未检测")
                    adult_item.setForeground(QColor(110, 110, 110))
                else:
                    is_adult, auto = self._adult_of(e)
                    adult_txt = ("是(检)" if auto else "是") if is_adult else "否"
                    adult_item = QTableWidgetItem(adult_txt)
                    if is_adult:
                        adult_item.setForeground(QColor(200, 30, 30))  # 成人内容标红
                self.table.setItem(r, 4, adult_item)
                # 第 5 列：短剧（与成人同遍扫描；未完显示「检测中…」，未开始显示「未检测」）
                if self._scanning and str(e.get("key", "")) not in self.duanju_map:
                    dj_item = QTableWidgetItem("检测中…")
                    dj_item.setForeground(QColor(110, 110, 110))
                elif not self._adult_started:
                    dj_item = QTableWidgetItem("未检测")
                    dj_item.setForeground(QColor(110, 110, 110))
                else:
                    is_dj, _dkw = self.duanju_map.get(str(e.get("key", "")), (False, None))
                    dj_item = QTableWidgetItem("是(检)" if is_dj else "否")
                    if is_dj:
                        dj_item.setForeground(QColor(200, 130, 20))  # 短剧源标橙
                self.table.setItem(r, 5, dj_item)
                # 第 6 列：直播（与成人同遍扫描；未完显示「检测中…」，未开始显示「未检测」）
                if self._scanning and str(e.get("key", "")) not in self.live_map:
                    lv_item = QTableWidgetItem("检测中…")
                    lv_item.setForeground(QColor(110, 110, 110))
                elif not self._adult_started:
                    lv_item = QTableWidgetItem("未检测")
                    lv_item.setForeground(QColor(110, 110, 110))
                else:
                    is_lv, _lkw = self.live_map.get(str(e.get("key", "")), (False, None))
                    lv_item = QTableWidgetItem("是(检)" if is_lv else "否")
                    if is_lv:
                        lv_item.setForeground(QColor(150, 60, 180))  # 直播源标紫
                self.table.setItem(r, 6, lv_item)
                # 第 7 列：URL 可达性（后台线程检测，未完显示「检测中…」；未开始显示「未检测」）
                key = str(e.get("key", ""))
                if self._url_scanning and key not in self.url_map:
                    url_item = QTableWidgetItem("检测中…")
                    url_item.setForeground(QColor(110, 110, 110))
                elif not self._url_started:
                    url_item = QTableWidgetItem("未检测")
                    url_item.setForeground(QColor(110, 110, 110))
                else:
                    code, method, note = self.url_map.get(key, (2, "", "未检测"))
                    if code == 1:
                        txt = ("可达(%s)" % method) if method else "可达"
                        url_item = QTableWidgetItem(txt)
                        url_item.setForeground(QColor(20, 120, 40))
                    elif code == 0:
                        url_item = QTableWidgetItem("不可达")
                        url_item.setForeground(QColor(200, 30, 30))
                    else:
                        url_item = QTableWidgetItem(note or "无URL")
                        url_item.setForeground(QColor(110, 110, 110))
                self.table.setItem(r, 7, url_item)
                # 第 8 列：是否禁用
                dis_item = QTableWidgetItem("是" if e.get("_disabled") else "否")
                if e.get("_disabled"):
                    dis_item.setForeground(QColor(200, 30, 30))
                self.table.setItem(r, 8, dis_item)
                # 第 9 列：资源状态（类型感知：直连/远程/jar 源均无本地 .py 文件）
                key8 = str(e.get("key", ""))
                _tr = source_type_of(e)
                if _tr == 1:
                    # 直连 CMS：以 http 接口形式存在，无本地 .py 文件
                    file_item = QTableWidgetItem("直连")
                    file_item.setForeground(QColor(0, 102, 204))
                elif "://" in api or e.get("jar"):
                    # 远程源（远程 spider）或 jar 型 spider（api 是 jar 内类名，如 csp_Config）
                    file_item = QTableWidgetItem("远程")
                    file_item.setForeground(QColor(110, 110, 110))
                else:
                    st = self.file_map.get(key8)
                    if st is None and self._file_checking:
                        file_item = QTableWidgetItem("检测中…")
                        file_item.setForeground(QColor(110, 110, 110))
                    elif st == "missing":
                        file_item = QTableWidgetItem("缺失")
                        file_item.setForeground(QColor(200, 30, 30))
                    elif st == "relocated":
                        file_item = QTableWidgetItem("已找回")
                        file_item.setForeground(QColor(200, 130, 20))
                    elif st == "remote":
                        file_item = QTableWidgetItem("远程")
                        file_item.setForeground(QColor(110, 110, 110))
                    else:
                        file_item = QTableWidgetItem("正常")
                        file_item.setForeground(QColor(20, 120, 40))
                self.table.setItem(r, 9, file_item)
            # 恢复刷新前的选中（同一组 key 的新位置；整组多选一并恢复）。
            # 注意：不能用 setCurrentCell 设当前行——它会清掉多选；改用 Current 标志。
            if sel_keys:
                first_restored = None
                for i, e in enumerate(self._shown):
                    if str(e.get("key", "")) in sel_keys:
                        flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
                        if first_restored is None:
                            flags |= QItemSelectionModel.Current
                        try:
                            self.table.selectionModel().select(
                                self.table.model().index(i, 0), flags)
                            if first_restored is None:
                                first_restored = i
                        except Exception:
                            self.table.selectRow(i)
                            break
            if hasattr(self, "lbl_count") and self.lbl_count is not None:
                n_dis = sum(1 for e in self.entries if e.get("_disabled"))
                txt = "共 %d 条，显示 %d 条 · 已禁用 %d" % (len(self.entries), len(self._shown), n_dis)
                if getattr(self, "removed_keys", None) or getattr(self, "modified", None):
                    txt += " · <span style='color:#c0392b;font-weight:bold'>●</span> 未保存更改（Ctrl+S）"
                self.lbl_count.setText(txt)
            # 表格重建后按当前选中项重算「禁用选中/启用选中」按钮可用性
            self._update_action_buttons()
            # 表格内容已就绪 → 现在才知道各列真实内容宽度，此时做一次「按内容自适应」
            # （构造期表格还是空的，早算会偏窄；用户拖过列宽则跳过，尊重用户设置）
            self._auto_fit_other_columns()
            if not getattr(self, "_name_user_resized", False):
                self._fit_name_column()
            # 空状态：无匹配项时在表格中央显示提示
            self._update_empty_state()

        def _update_empty_state(self):
            """表格为空（搜索无结果 / 列表为空）时显示居中的「没有匹配的站点」提示。"""
            try:
                lbl = getattr(self, "empty_label", None)
                if lbl is None:
                    return
                if getattr(self, "_shown", None):
                    lbl.hide()
                else:
                    lbl.setGeometry(self.table.viewport().rect())
                    lbl.show()
                    lbl.raise_()
            except Exception:
                pass

        # ---- 点击 api 列：按 type 打开对应的东西（本地脚本 / 远程 jar / API 链接 / 目录）----
        def _on_api_cell_clicked(self, row, col):
            """点击第 1 列（api）时，用系统默认方式打开该站点的「正确目标」。
            ⚠️ 不再一律当 .py 打开（jar 型 spider 没有本地 .py）。"""
            if self._closed or col != 1:
                return
            if row < 0 or row >= len(self._shown):
                return
            entry = self._shown[row]
            key = str(entry.get("key", ""))
            self._open_entry_target(entry, resolved_py=self.file_reloc.get(key))

        def _open_entry_target(self, entry, resolved_py=None):
            """按 type 分流打开：本地脚本→文件、jar 型→远程 jar、直连→API 链接、目录型→目录。"""
            tgt = open_target_of(entry, self.base_dir, self.repo_dir, resolved_py)
            kind = tgt["kind"]
            if kind == "file":
                try:
                    os.startfile(tgt["path"])
                except Exception as ex:
                    QMessageBox.warning(self, "无法打开", "调用系统默认程序失败：%s" % ex)
            elif kind == "dir":
                p = tgt["path"]
                if p and os.path.isdir(p):
                    try:
                        os.startfile(p)
                    except Exception as ex:
                        QMessageBox.warning(self, "无法打开", "打开目录失败：%s" % ex)
                elif p and os.path.isfile(p):
                    try:
                        os.startfile(os.path.dirname(os.path.abspath(p)))
                    except Exception as ex:
                        QMessageBox.warning(self, "无法打开", "打开目录失败：%s" % ex)
                else:
                    QMessageBox.information(self, "提示",
                                            "未找到可打开的目录：\n%s" % (p or entry.get("api", "")))
            elif kind in ("jar", "url"):
                try:
                    ok = QDesktopServices.openUrl(QUrl(tgt["url"]))
                except Exception:
                    ok = False
                if not ok:
                    QApplication.clipboard().setText(tgt["url"])
                    self._toast("链接已复制到剪贴板（系统打开失败）")
            else:
                QMessageBox.warning(self, "无法打开", tgt["note"] or "没有可打开的目标。")

        # ---- 双击行编辑 ----
        def _on_row_double_clicked(self, row, col):
            """双击除 api 列（第 1 列，单击=按 type 打开对应目标）外的任意列：弹出该站点编辑窗口。"""
            if self._closed or col == 1:
                return
            if row < 0 or row >= len(self._shown):
                return
            self.edit_row()

        # ---- 点击表头排序 ----
        def _on_header_clicked(self, col):
            if self._closed:
                return
            if col == self._sort_col:
                self._sort_asc = not self._sort_asc      # 再次点击同列：切换升降序
            else:
                self._sort_col = col
                self._sort_asc = True
            # 原生排序指示器（替代文本箭头）
            try:
                hdr = self.table.horizontalHeader()
                hdr.setSortIndicator(
                    col, Qt.AscendingOrder if self._sort_asc else Qt.DescendingOrder)
                hdr.setSortIndicatorShown(True)
            except Exception:
                pass
            self._refresh_table()

        def _sort_key(self, e, col):
            """返回用于排序的键；type 按数值、成人按等级、其余按文本。（key 列已移除）"""
            if col == 0:
                return str(e.get("name", "")).lower()
            if col == 1:
                return str(e.get("api", "")).lower()
            if col == 2:
                try:
                    return int(e.get("type", 0) or 0)
                except Exception:
                    return 0
            if col == 3:
                return (self._to_bool(e.get("filterable", 1)),
                        self._to_bool(e.get("quickSearch", 1)),
                        self._to_bool(e.get("searchable", 1)))
            if col == 4:
                k = str(e.get("key", ""))
                if self._scanning and k not in self.detect_map:
                    return 2                              # 检测中（排最后）
                if not self._adult_started:
                    return 2                              # 未检测（排最后）
                is_adult, _auto = self._adult_of(e)
                return 1 if is_adult else 0              # 成人=1 在前，否=0 在后
            if col == 5:
                k = str(e.get("key", ""))
                if self._scanning and k not in self.duanju_map:
                    return 2                              # 检测中（排最后）
                if not self._adult_started:
                    return 2                              # 未检测（排最后）
                is_dj = self.duanju_map.get(k, (False, None))[0]
                return 0 if is_dj else 1                 # 短剧源(0)排最前
            if col == 6:
                k = str(e.get("key", ""))
                if self._scanning and k not in self.live_map:
                    return 2                              # 检测中（排最后）
                if not self._adult_started:
                    return 2                              # 未检测（排最后）
                is_lv = self.live_map.get(k, (False, None))[0]
                return 0 if is_lv else 1                 # 直播源(0)排最前
            if col == 7:
                k = str(e.get("key", ""))
                if self._url_scanning and k not in self.url_map:
                    return 3                              # 检测中（排最后）
                if not self._url_started:
                    return 3                              # 未检测（排最后）
                code = self.url_map.get(k, (2, "", ""))[0]
                return 0 if code == 0 else (1 if code == 1 else 2)  # 不可达(0)最前，可达(1)其次，无URL(2)最后
            if col == 8:
                return 0 if e.get("_disabled") else 1    # 已禁用(0)排前
            if col == 9:
                k8 = str(e.get("key", ""))
                st = self.file_map.get(k8)
                if st is None:
                    return 3                              # 检测中/未检测（排最后）
                return {"missing": 0, "relocated": 1, "normal": 2, "remote": 2}.get(st, 2)
            return 0

        def _update_header_arrows(self):
            # 排序指示器已改用 QHeaderView 原生箭头（见 _on_header_clicked），此处仅保证表头文本干净
            try:
                if self.table.horizontalHeaderItem(0) is not None:
                    self.table.setHorizontalHeaderLabels(list(self._base_headers))
            except Exception:
                pass

        def _on_type_filter(self, idx):
            """按选中的过滤维度收窄表格：type（0/1/3/4）/ 仅成人 / 仅需特殊上网。"""
            specs = getattr(self, "_filter_spec", None)
            self._type_filter = specs[idx] if (specs and 0 <= idx < len(specs)) else None
            self._refresh_table()

        def _on_search(self, _text):
            self._refresh_table()
            if self._shown:
                self.table.selectRow(0)
                self.table.scrollToItem(self.table.item(0, 0))

        def _clear_search(self):
            self.search_edit.blockSignals(True)
            self.search_edit.setText("")
            self.search_edit.blockSignals(False)
            self._refresh_table()

        def _find_next(self):
            if not self._shown:
                return
            row = self.table.currentRow()
            nxt = (row + 1) % len(self._shown)
            self.table.selectRow(nxt)
            item = self.table.item(nxt, 0)
            if item is not None:
                self.table.scrollToItem(item)

        def _sel_entry(self):
            row = self.table.currentRow()
            if row < 0 or row >= len(self._shown):
                QMessageBox.information(self, "提示", "请先选中一行。")
                return None
            return self._shown[row]

        def edit_row(self):
            e = self._sel_entry()
            if e is None:
                return
            if e.get("_disabled"):
                QMessageBox.warning(self, "提示",
                                    "该站点已禁用（已被注释掉），请先「启用选中」再编辑。")
                return
            key = str(e.get("key", ""))
            dlg = QDialog(self)
            dlg.setWindowTitle(tagged_title("编辑站点：" + key))
            fl = QFormLayout(dlg)
            vn = QLineEdit(str(e.get("name", "")))
            va = QLineEdit(str(e.get("api", "")))
            vt = QSpinBox()
            vt.setRange(0, 9)
            vt.setValue(int(e.get("type", 3) or 3))
            vf = QCheckBox()
            vf.setChecked(self._to_bool(e.get("filterable", 1)))
            vq = QCheckBox()
            vq.setChecked(self._to_bool(e.get("quickSearch", 1)))
            vs = QCheckBox()
            vs.setChecked(self._to_bool(e.get("searchable", 1)))
            vadult = QCheckBox("涉及成人内容（R18）")
            _is_ad, _auto = self._adult_of(e)
            vadult.setChecked(_is_ad)
            if _auto:
                _kw = self.detect_map.get(str(e.get("key", "")), (False, None))[1]
                vadult.setText("涉及成人内容（R18）——自动检测命中: %s" % _kw)
            fl.addRow("站点标识 key（不可改）:", QLabel(key))
            fl.addRow("名称 name:", vn)
            fl.addRow("接口地址 api:", va)
            vjar = QLineEdit(str(e.get("jar", "") or ""))
            fl.addRow("jar 包名（仅 jar 型 spider 源）:", vjar)
            fl.addRow("类型 type（0-9）:", vt)
            fl.addRow("可筛选 filterable:", vf)
            fl.addRow("可快搜 quickSearch:", vq)
            fl.addRow("可搜索 searchable:", vs)
            fl.addRow("成人内容 R18:", vadult)
            _ext_cur = e.get("ext")
            _ext_txt = (json.dumps(_ext_cur, ensure_ascii=False, indent=2)
                        if isinstance(_ext_cur, (dict, list))
                        else (str(_ext_cur) if _ext_cur else ""))
            ve = QPlainTextEdit(_ext_txt)
            ve.setPlaceholderText('（无扩展参数，可留空；例如 {"site": "https://..."}）')
            # 高度随内容动态伸缩：空/单行→紧凑两行；有内容→按行数展开，上限 10 行后滚动
            _EXT_MIN_VIS_LINES = 2
            _EXT_MAX_VIS_LINES = 10

            def _ext_fit_height(*_a):
                try:
                    txt = ve.toPlainText()
                    lines = (txt.count("\n") + 1) if txt else 1
                    vis = (_EXT_MIN_VIS_LINES if lines <= 1
                           else min(lines, _EXT_MAX_VIS_LINES))
                    try:
                        lh = int(ve.fontMetrics().lineSpacing())
                    except Exception:
                        lh = 20
                    ve.setFixedHeight(vis * lh + 14)
                except Exception:
                    pass

            _ext_fit_height()
            try:
                ve.textChanged.connect(_ext_fit_height)
            except Exception:
                pass
            fl.addRow("扩展参数 ext（JSON）:", ve)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.rejected.connect(dlg.reject)

            def _on_ok():
                txt = ve.toPlainText().strip()
                if txt:
                    try:
                        ext_val = json.loads(txt)
                    except Exception as ex:
                        QMessageBox.warning(
                            dlg, "ext 不是合法 JSON",
                            "ext 字段必须是合法 JSON（对象或数组）：\n%s" % ex)
                        return
                else:
                    ext_val = None
                vals = {
                    "name": vn.text().strip(),
                    "api": va.text().strip(),
                    "type": vt.value(),
                    "filterable": 1 if vf.isChecked() else 0,
                    "quickSearch": 1 if vq.isChecked() else 0,
                    "searchable": 1 if vs.isChecked() else 0,
                    "adult": 1 if vadult.isChecked() else 0,
                    "jar": vjar.text().strip(),
                    "ext": ext_val,
                }
                self.modified[key] = vals
                for k, v in vals.items():
                    e[k] = v
                self._refresh_table()
                dlg.accept()

            bb.accepted.connect(_on_ok)
            fl.addRow(bb)
            dlg.exec()

        def _selected_rows(self):
            """返回当前选中的所有行号（升序去重）。

            无 selectionModel（mock 测试环境）或未多选时退回 currentRow。
            """
            rows = []
            try:
                rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
            except Exception:
                rows = []
            if not rows:
                r = self.table.currentRow()
                if 0 <= r < len(self._shown):
                    rows = [r]
            return [r for r in rows if 0 <= r < len(self._shown)]

        def del_row(self):
            rows = self._selected_rows()
            if not rows:
                QMessageBox.information(self, "提示", "请先选中一行。")
                return
            targets = [self._shown[r] for r in rows]
            # 已禁用的条目先取消注释，使其回到 active 以便删除
            for e in targets:
                if e.get("_disabled"):
                    k = str(e.get("key", ""))
                    new_text, found = enable_site(self.raw, k)
                    if found:
                        self.raw = new_text
                        self.changed = True
                        e["_disabled"] = False
            keys = [str(e.get("key", "")) for e in targets]
            if len(keys) == 1:
                msg = "确定删除站点 %s 吗？" % keys[0]
            else:
                preview = "\n".join("• " + k for k in keys[:12])
                if len(keys) > 12:
                    preview += "\n… 等共 %d 个" % len(keys)
                msg = "确定删除以下 %d 个站点吗？\n\n%s" % (len(keys), preview)
            box = QMessageBox(
                QMessageBox.Question, "确认删除",
                msg + "\n\n（点击「保存并写入」后生效）",
                QMessageBox.Yes | QMessageBox.No, self)
            py_paths = []
            for e in targets:
                # 直连/远程源（type:1 或 http 接口）无本地 .py，不提供「删除 .py」
                _t = _norm_type(e.get("type"))
                if _t is None:
                    _t = infer_type(str(e.get("api", "")))
                if _t == 1 or "://" in str(e.get("api", "")):
                    continue
                p = resolve_spider_path(self.base_dir, e.get("api", ""), self.repo_dir)
                if p:
                    py_paths.append(p)
            if len(py_paths) == 1:
                box.setInformativeText(
                    "对应 .py：\n%s\n\n不勾选则仅删除配置项、保留 .py 文件，方便将来再次添加。"
                    % py_paths[0])
            elif py_paths:
                box.setInformativeText(
                    "共对应 %d 个 .py 文件\n\n不勾选则仅删除配置项、保留 .py 文件，方便将来再次添加。"
                    % len(py_paths))
            else:
                box.setInformativeText("该源为直连/远程源，无本地 .py 文件，删除仅移除配置项。")
            # 可选：是否连 .py 一起删。仅当确有本地 .py 时才允许勾选（默认勾选），
            # 直连/远程源一律禁用该选项。
            cb = QCheckBox("同时删除对应 .py 文件（先备份到 py_trash/）")
            cb.setChecked(bool(py_paths))
            cb.setEnabled(bool(py_paths))
            box.setCheckBox(cb)
            if box.exec() != QMessageBox.Yes:
                return
            keys_set = set(keys)
            for k in keys:
                self.removed_keys.add(k)
                self.modified.pop(k, None)
                if cb.isChecked():
                    self.removed_del_py.add(k)
                else:
                    self.removed_del_py.discard(k)
            self.entries = [x for x in self.entries if str(x.get("key", "")) not in keys_set]
            self._refresh_table()
            self._toast("已删除 %d 个站点（Ctrl+S 保存后生效）" % len(keys))

        def disable_selected(self):
            rows = self._selected_rows()
            if not rows:
                QMessageBox.information(self, "提示", "请先选中一行。")
                return
            targets = [self._shown[r] for r in rows
                       if not self._shown[r].get("_disabled")]
            if not targets:
                QMessageBox.information(self, "提示", "选中的站点均已处于禁用状态。")
                return
            new_text = self.raw
            ok_keys = []
            for e in targets:
                k = str(e.get("key", ""))
                new_text2, found = disable_site(new_text, k)
                if found:
                    new_text = new_text2
                    ok_keys.append(k)
            if not ok_keys:
                QMessageBox.warning(self, "失败", "没有可禁用的站点（未在配置中找到）。")
                return
            bak = backup_and_write(self.repo_dir, new_text, self.cfg_file)
            self.raw = new_text
            self.changed = True
            for e in targets:
                if str(e.get("key", "")) in ok_keys:
                    e["_disabled"] = True
            self._refresh_table()
            self.log_msg("已禁用 %s（备份 %s）" % (", ".join(ok_keys), os.path.basename(bak)), "ok")
            self._toast("已禁用 %s" % (ok_keys[0] if len(ok_keys) == 1
                                      else "%d 个站点" % len(ok_keys)))

        def _ask_purge_mode(self, n_total, n_url, n_file):
            """确认「剔除失效源」的处理方式。返回 "disable" / "remove" / None(取消)。"""
            box = QMessageBox(self)
            try:
                box.setIcon(QMessageBox.Warning)
            except Exception:
                pass
            box.setWindowTitle(tagged_title("剔除失效源"))
            box.setText("检测到 %d 个已判定失效的站点。" % n_total)
            _parts = []
            if n_url:
                _parts.append("URL 不可达 %d" % n_url)
            if n_file:
                _parts.append("本地脚本缺失 %d" % n_file)
            box.setInformativeText(
                "依据：%s\n\n"
                "· 🚫 禁用：注释保留，随时可用「启用选中」恢复（推荐，立即写盘并备份）\n"
                "· 🗑 删除：从配置中摘除（点「保存并写入」后生效；不删 .py 文件）\n\n"
                "未检测过的站点一律不动。" % (" · ".join(_parts) or "检测结果"))
            b_dis = box.addButton("🚫 禁用（推荐）", QMessageBox.AcceptRole)
            b_del = box.addButton("🗑 删除", QMessageBox.DestructiveRole)
            box.addButton("取消", QMessageBox.RejectRole)
            try:
                box.setDefaultButton(b_dis)
            except Exception:
                pass
            box.exec()
            cb = None
            try:
                cb = box.clickedButton()
            except Exception:
                pass
            if cb is b_dis or cb is None:
                return "disable"
            if cb is b_del:
                return "remove"
            return None

        def _apply_purge(self, keys, mode):
            """按 key 列表执行剔除。disable=注释禁用并立即写盘（返回 (n, 备份路径)）；
            remove=标记删除（保存后生效，返回 (n, None)）。"""
            keys = [str(k) for k in (keys or []) if k]
            if mode == "remove":
                ks = set(keys)
                for k in keys:
                    self.removed_keys.add(k)
                    self.modified.pop(k, None)
                    # 保守：只摘配置项，不删本地 .py（要删请用「🗑 删除选中」单独确认）
                    self.removed_del_py.discard(k)
                self.entries = [x for x in self.entries
                                if str(x.get("key", "")) not in ks]
                self._refresh_table()
                return len(keys), None
            active = [e for e in self.entries
                      if str(e.get("key", "")) in set(keys) and not e.get("_disabled")]
            new_text, done = self.raw, []
            for e in active:
                k = str(e.get("key", ""))
                try:
                    nt, found = disable_site(new_text, k)
                except Exception:
                    found = False
                if found:
                    new_text = nt
                    done.append(k)
            if not done:
                return 0, None
            bak = backup_and_write(self.repo_dir, new_text, self.cfg_file)
            self.raw = new_text
            self.changed = True
            for e in active:
                if str(e.get("key", "")) in done:
                    e["_disabled"] = True
            self._refresh_table()
            return len(done), bak

        def purge_dead_sources(self):
            """🧹 剔除失效源：把**已检测判定失效**的站点一次性处理掉。

            判定只用明确失效信号（URL 不可达 / 本地脚本缺失），**未检测的条目一律不动**，
            避免误伤好源。默认「禁用」（注释保留、可恢复），也可选「删除」。
            """
            info = dead_source_keys(self.entries, self.url_map,
                                    getattr(self, "file_map", None))
            keys = info["keys"]
            if not keys:
                QMessageBox.information(
                    self, "未发现失效源",
                    "没有已判定失效的站点。\n\n"
                    "判定依据（需先跑检测，未检测的不算）：\n"
                    "· 「URL 可达性检测」→ 不可达\n"
                    "· 「本地 .py 检查」→ 缺失\n\n"
                    "也可用过滤下拉选「⛔ 仅失效源」查看当前结果。")
                return
            mode = self._ask_purge_mode(len(keys), len(info["unreachable"]),
                                        len(info["missing_file"]))
            if not mode:
                return
            n, bak = self._apply_purge(keys, mode)
            if not n:
                QMessageBox.warning(self, "未处理",
                                    "没有可处理的站点（可能已全部处于禁用/移除状态）。")
                return
            if mode == "remove":
                self._toast("已摘除 %d 个失效源（Ctrl+S 保存后生效）" % n)
                self.log_msg("剔除失效源：摘除 %d 个（未保存，需写入）" % n, "ok")
            else:
                self._toast("已禁用 %d 个失效源（可随时启用恢复）" % n)
                self.log_msg("剔除失效源：禁用 %d 个（备份 %s）"
                             % (n, os.path.basename(bak) if bak else "-"), "ok")

        def disable_duanju(self):
            """一键禁用所有检出为短剧类的站点（注释式，可逆，随时可「启用选中」恢复）。"""
            if not self._adult_started or not self.duanju_map:
                QMessageBox.information(
                    self, "提示",
                    "尚未进行内容检测。\n请先点上方「成人/短剧/直播检测」行的「开始」，检测完成后再禁用短剧源。")
                return
            dj_keys = []
            for e in self.entries:
                k = str(e.get("key", ""))
                if e.get("_disabled"):
                    continue
                if self.duanju_map.get(k, (False, None))[0]:
                    dj_keys.append(k)
            if not dj_keys:
                QMessageBox.information(self, "禁用短剧", "未检测到短剧类站点（或均已禁用）。")
                return
            preview = "\n".join("• " + k for k in dj_keys[:12])
            if len(dj_keys) > 12:
                preview += "\n… 等共 %d 个" % len(dj_keys)
            if QMessageBox.question(
                    self, "确认禁用短剧源",
                    "将禁用 %d 个短剧类站点（注释掉对应配置，可逆）：\n\n%s\n\n确定立即写入吗？"
                    % (len(dj_keys), preview)) != QMessageBox.Yes:
                return
            new_text = self.raw
            done, failed = [], []
            for k in dj_keys:
                new_text, found = disable_site(new_text, k)
                (done if found else failed).append(k)
            if not done:
                QMessageBox.warning(self, "失败", "未找到任何可禁用的短剧站点。")
                return
            bak = backup_and_write(self.repo_dir, new_text, self.cfg_file)
            self.raw = new_text
            self.changed = True
            for e in self.entries:
                if str(e.get("key", "")) in done:
                    e["_disabled"] = True
            self._refresh_table()
            msg = "已禁用 %d 个短剧类站点（注释掉配置，TVBox 等将忽略）。\n备份：%s" % (
                len(done), os.path.basename(bak))
            if failed:
                msg += "\n⚠ 未找到：%s" % "、".join(failed)
            QMessageBox.information(self, "完成", msg)

        def disable_live(self):
            """一键禁用所有检出为直播类的站点（注释式，可逆，随时可「启用选中」恢复）。"""
            if not self._adult_started or not self.live_map:
                QMessageBox.information(
                    self, "提示",
                    "尚未进行内容检测。\n请先点上方「成人/短剧/直播检测」行的「开始」，检测完成后再禁用直播源。")
                return
            lv_keys = []
            for e in self.entries:
                k = str(e.get("key", ""))
                if e.get("_disabled"):
                    continue
                if self.live_map.get(k, (False, None))[0]:
                    lv_keys.append(k)
            if not lv_keys:
                QMessageBox.information(self, "禁用直播", "未检测到直播类站点（或均已禁用）。")
                return
            preview = "\n".join("• " + k for k in lv_keys[:12])
            if len(lv_keys) > 12:
                preview += "\n… 等共 %d 个" % len(lv_keys)
            if QMessageBox.question(
                    self, "确认禁用直播源",
                    "将禁用 %d 个直播类站点（注释掉对应配置，可逆）：\n\n%s\n\n确定立即写入吗？"
                    % (len(lv_keys), preview)) != QMessageBox.Yes:
                return
            new_text = self.raw
            done, failed = [], []
            for k in lv_keys:
                new_text, found = disable_site(new_text, k)
                (done if found else failed).append(k)
            if not done:
                QMessageBox.warning(self, "失败", "未找到任何可禁用的直播站点。")
                return
            bak = backup_and_write(self.repo_dir, new_text, self.cfg_file)
            self.raw = new_text
            self.changed = True
            for e in self.entries:
                if str(e.get("key", "")) in done:
                    e["_disabled"] = True
            self._refresh_table()
            msg = "已禁用 %d 个直播类站点（注释掉配置，TVBox 等将忽略）。\n备份：%s" % (
                len(done), os.path.basename(bak))
            if failed:
                msg += "\n⚠ 未找到：%s" % "、".join(failed)
            QMessageBox.information(self, "完成", msg)

        def enable_selected(self):
            rows = self._selected_rows()
            if not rows:
                QMessageBox.information(self, "提示", "请先选中一行。")
                return
            targets = [self._shown[r] for r in rows
                       if self._shown[r].get("_disabled")]
            if not targets:
                QMessageBox.information(self, "提示", "选中的站点均处于启用状态，无需启用。")
                return
            new_text = self.raw
            ok_keys = []
            for e in targets:
                k = str(e.get("key", ""))
                new_text2, found = enable_site(new_text, k)
                if found:
                    new_text = new_text2
                    ok_keys.append(k)
            if not ok_keys:
                QMessageBox.warning(self, "失败", "没有可启用的站点（未找到被禁用的配置）。")
                return
            bak = backup_and_write(self.repo_dir, new_text, self.cfg_file)
            self.raw = new_text
            self.changed = True
            for e in targets:
                if str(e.get("key", "")) in ok_keys:
                    e["_disabled"] = False
            self._refresh_table()
            self.log_msg("已启用 %s（备份 %s）" % (", ".join(ok_keys), os.path.basename(bak)), "ok")
            self._toast("已启用 %s" % (ok_keys[0] if len(ok_keys) == 1
                                      else "%d 个站点" % len(ok_keys)))

        def check_dups(self):
            reps = check_duplicates(self.entries)
            if reps:
                QMessageBox.warning(self, "查重结果",
                                    "发现重复项 %d 个：\n\n" % len(reps) + "\n".join("• " + r for r in reps))
            else:
                QMessageBox.information(self, "查重结果",
                                    "未发现重复项。\n\n判重口径：key 必须唯一；功能重复 =（api + jar + ext）三者全同。\n仅 api 相同、ext/jar 不同属多线路复用，不算重复。")

        def dedup(self):
            new_text, removed = deduplicate_sites(self.raw)
            if not removed:
                QMessageBox.information(self, "去重", "未发现重复项，无需去重。")
                return
            msg = "将删除 %d 个重复条目（保留首个）：\n\n" % len(removed)
            msg += "\n".join("• %s（%s）" % (key, name) for key, name, reason in removed)
            if QMessageBox.question(self, "确认去重", msg + "\n\n确定立即写入吗？") != QMessageBox.Yes:
                return
            bak = backup_and_write(self.repo_dir, new_text, self.cfg_file)
            self.raw = new_text
            self.entries = parse_jsonc(new_text).get("sites", []) or []
            self.modified = {}
            self.removed_keys = set()
            self.removed_del_py = set()
            self.changed = True
            self._refresh_table()
            QMessageBox.information(self, "完成", "已去重，删除 %d 个重复条目。\n备份：%s" % (len(removed), os.path.basename(bak)))

        def save(self):
            new_text = self.raw
            errors = []
            for key, vals in self.modified.items():
                for field, value in vals.items():
                    try:
                        new_text, _ = update_site(new_text, key, field, value)
                    except ValueError as ex:
                        errors.append(str(ex))
            for key in self.removed_keys:
                try:
                    new_text, _ = delete_site(new_text, key)
                except ValueError as ex:
                    errors.append(str(ex))
            if errors:
                QMessageBox.critical(self, "错误", "保存失败：\n" + "\n".join(errors))
                return
            try:
                parse_jsonc(new_text)
            except Exception as ex:
                QMessageBox.critical(self, "错误", "修改后配置不合法，未保存：%s" % ex)
                return
            bak = backup_and_write(self.repo_dir, new_text, self.cfg_file)
            self.changed = True

            # 仅对勾选了「同时删除 .py」的站点删对应 .py（先备份到 py_trash，
            # 若仍有其它站点引用同一 .py 则跳过）；未勾选的只删配置项、保留 .py
            del_py_keys = self.removed_keys & getattr(self, "removed_del_py", set())
            py_deleted, py_skipped = [], []
            if del_py_keys:
                try:
                    raw_sites = (parse_jsonc(self.raw).get("sites", []) or [])
                    key_api = {str(s.get("key", "")): s.get("api", "") for s in raw_sites}
                    to_del, skipped = collect_orphan_py(
                        self.base_dir, del_py_keys, key_api, self.entries, self.repo_dir,
                        default_search_roots(self.repo_dir, self.cfg_file))
                    for p in to_del:
                        if trash_spider(self.base_dir, p):
                            py_deleted.append(p)
                    py_skipped.extend(skipped)
                except Exception as ex:
                    self.log_msg("删除 .py 时出错：%s" % ex, "err")

            msg = "已写入配置。\n备份：%s" % os.path.basename(bak)
            if py_deleted:
                msg += "\n\n已删除 %d 个对应 .py（已备份至 py_trash/）：\n" % len(py_deleted)
                msg += "\n".join("• " + p for p in py_deleted)
                for p in py_deleted:
                    self.log_msg("已删除 .py（备份 py_trash）：%s" % p, "ok")
            if py_skipped:
                msg += "\n\n跳过 %d 个 .py：\n" % len(py_skipped)
                msg += "\n".join("• %s（%s）" % (p, r) for p, r in py_skipped)
            QMessageBox.information(self, "完成", msg)
            self.accept()

        # ---- 导出干净配置（按勾选/过滤条件另存为新配置文件）----
        def export_config(self):
            """把当前配置里勾选保留的站点导出成一份新的配置文件。
            不覆盖现有配置：只写用户另存的路径，因此无需备份。"""
            if not self.raw:
                QMessageBox.information(self, "提示", "尚未成功加载配置。")
                return
            dlg = _ExportDialog(self, self.repo_dir, self.cfg_file, self.raw, self.entries,
                                detect={"adult": self.detect_map,
                                        "duanju": self.duanju_map,
                                        "live": self.live_map})
            if dlg.exec() != QDialog.Accepted:
                return
            out = dlg.out_path
            if not out:
                return
            keep = dlg.keep_keys()
            if not keep:
                QMessageBox.warning(self, "提示", "没有勾选任何站点，未导出。")
                return
            try:
                new_text, removed = export_config_text(self.raw, keep)
            except Exception as ex:
                QMessageBox.critical(self, "错误", "导出失败：%s" % ex)
                return
            try:
                with open(out, "w", encoding="utf-8") as f:
                    f.write(new_text)
            except Exception as ex:
                QMessageBox.critical(self, "错误", "写入失败：%s\n%s" % (out, ex))
                return
            self._toast("已导出 %d 条（剔除 %d 条）" % (len(keep), removed))
            self._refresh_cfg_candidates()  # 新配置文件加入下拉候选
            QMessageBox.information(
                self, "完成",
                "已导出到：%s\n\n保留 %d 个站点，剔除 %d 个。"
                "\n注意：api 路径（./py/xxx.py）相对基准目录解析，"
                "若导出到别的目录，目标目录需同样存在 py/ 目录。" % (out, len(keep), removed))

        # ---- 智能分流导出：按 adult 字段一键生成「纯净版 + 完整版」两套配置 ----
        def split_export(self):
            """按 adult 标记把当前配置分流成两套另存（纯净版剔除成人 / 完整版保留全部）。
            判定只用现有 adult 字段 +（可选）已跑过的成人检测结果，不改动当前配置。"""
            if not self.raw:
                QMessageBox.information(self, "提示", "尚未成功加载配置。")
                return
            adult_keys = {k for k, v in self.detect_map.items() if v and v[0]}
            dlg = _SplitExportDialog(self, self.repo_dir, self.cfg_file, self.raw,
                                     self.entries, adult_keys=adult_keys)
            if dlg.exec() != QDialog.Accepted:
                return
            r = getattr(dlg, "result", None)
            if not r:
                return
            self._toast("已导出：纯净版 %d 条 / 完整版 %d 条"
                        % (r["pure_kept"], r["total"]))
            self._refresh_cfg_candidates()  # 新配置文件加入下拉候选
            QMessageBox.information(
                self, "完成",
                "已导出两套配置：\n\n· 纯净版（剔除成人 %d 个）：%s\n· 完整版（保留全部 %d 个）：%s"
                % (r["pure_removed"], r["pure"], r["total"], r["full"]))

        # ---- 源测活（按 type 路由：type:1 直连 HTTP 取分类 / type:3 本地 .py 子进程）----
        def probe_config(self):
            """对可探测的源逐个模拟影视仓加载：分类栏出不来 = 死源。
            覆盖：type:1 直连 CMS（HTTP 取分类判活）、type:3 本地 .py（子进程隔离）、
            type:0/4 且 http 的源（HTTP 可达性兜底）。"""
            roots = default_search_roots(self.repo_dir, self.cfg_file)
            name_map = discover_py_files(roots) if roots else {}
            items = []
            for e in self.entries:
                api = str(e.get("api", ""))
                key = str(e.get("key", ""))
                if not api:
                    continue
                t = _norm_type(e.get("type"))
                if t is None:
                    t = infer_type(api)
                if t == 1 and api.startswith("http"):
                    items.append((key, str(e.get("name") or key), e, api, e.get("ext")))
                elif t == 3:
                    is_sp = api.startswith("csp_") or api.endswith((".py", ".js", ".jar", ".drpy"))
                    if not is_sp:
                        continue
                    if api.startswith("http"):
                        items.append((key, str(e.get("name") or key), e, api, e.get("ext")))
                    elif self.base_dir:
                        p, _ = resolve_spider_path_resilient(self.base_dir, api,
                                                             self.repo_dir, name_map)
                        if p and os.path.isfile(p):
                            items.append((key, str(e.get("name") or key), e, api, e.get("ext")))
                elif api.startswith("http"):
                    items.append((key, str(e.get("name") or key), e, api, e.get("ext")))
            if not items:
                QMessageBox.information(
                    self, "源测活",
                    "当前配置里没有可探测的源（需为 type:1 直连 / type:3 本地 .py / "
                    "type:0·4 且 http 的站点）。")
                return
            _ProbeDialog(self, items).exec()

        # ---- 工具箱：分类识别 / JAR 体检 / 测速 / 网络诊断 / 直播表转换 / 诊断报告 ----
        def open_toolbox(self):
            """打开「工具箱」对话框：把新增的零 Qt 纯逻辑模块（pyinj_jar /
            pyinj_playlist / pyinj_report / pyinj_kw / pyinj_speed / pyinj_netdiag）
            的能力接到界面上。对话框只读检测、不直接改配置，保证安全。"""
            _ToolboxDialog(self, self.entries, self.base_dir, self.repo_dir).exec()

    # ------------------------------------------------------------------
    # 站点预览表格：导出干净配置（首列 = 勾选框）
    # ------------------------------------------------------------------
    def _mk_check_table(headers):
        """新建一个只读的站点预览表格（首列留给勾选框）。"""
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        try:
            t.horizontalHeader().setMinimumSectionSize(60)
        except Exception:
            pass
        return t

    def _add_check_row(table, checked, cells, tips=None):
        """追加一行：首列勾选框，cells 为其余列文本（tips: {列序号: 悬浮说明}）。"""
        r = table.rowCount()
        table.insertRow(r)
        cb = QCheckBox()
        cb.setChecked(checked)
        table.setCellWidget(r, 0, cb)
        tips = tips or {}
        for i, txt in enumerate(cells):
            item = QTableWidgetItem(str(txt))
            item.setToolTip(tips.get(i, "") or str(txt))
            table.setItem(r, i + 1, item)
        return r

    def _cell(table, r, col):
        it = table.item(r, col)
        return it.text() if it is not None else ""

    def _row_checked(table, r):
        w = table.cellWidget(r, 0)
        return bool(w and w.isChecked())

    def _set_all_checked(table, checked):
        for r in range(table.rowCount()):
            w = table.cellWidget(r, 0)
            if w is not None:
                w.setChecked(checked)

    def _invert_checked(table):
        for r in range(table.rowCount()):
            w = table.cellWidget(r, 0)
            if w is not None:
                w.setChecked(not w.isChecked())

    # 列序号常量（首列是勾选框，故数据列从 1 起）
    E_NAME, E_KEY, E_API, E_TYPE, E_FLAG = 1, 2, 3, 4, 5

    class _ExportDialog(QDialog):
        """导出干净配置：勾选要保留的站点，剔除其余后另存为新配置文件。"""

        def __init__(self, parent, repo_dir, cfg_file, raw, entries, detect=None):
            super().__init__(parent)
            self.repo_dir = repo_dir
            self.cfg_file = cfg_file
            self.raw = raw
            self.entries = list(entries or [])
            self.detect = detect or {}
            self.out_path = ""
            self.setWindowTitle(tagged_title("📤 导出干净配置"))
            self.resize(900, 580)
            self._build()

        def _build(self):
            root = QVBoxLayout(self)

            fg = QGroupBox("快捷过滤（勾掉即排除该类站点，便于批量剔除）")
            fv = QHBoxLayout(fg)
            self.cb_no_adult = QCheckBox("排除成人")
            self.cb_no_duanju = QCheckBox("排除短剧")
            self.cb_no_live = QCheckBox("排除直播")
            self.cb_no_disabled = QCheckBox("排除已禁用")
            fv.addWidget(self.cb_no_adult)
            fv.addWidget(self.cb_no_duanju)
            fv.addWidget(self.cb_no_live)
            fv.addWidget(self.cb_no_disabled)
            fv.addStretch(1)
            root.addWidget(fg)

            sr = QHBoxLayout()
            sr.addWidget(QLabel("搜索："))
            self.search = QLineEdit()
            self.search.setPlaceholderText("按名称 / key / api 过滤下面的列表")
            self.search.textChanged.connect(lambda _t: self._refresh_table())
            sr.addWidget(self.search, 1)
            root.addLayout(sr)

            self.table = _mk_check_table(["", "名称", "key", "api", "类型", "检测标记"])
            root.addWidget(self.table, 1)

            row = QHBoxLayout()
            row.addWidget(QPushButton("全选", clicked=lambda: _set_all_checked(self.table, True)))
            row.addWidget(QPushButton("全不选", clicked=lambda: _set_all_checked(self.table, False)))
            row.addWidget(QPushButton("反选", clicked=lambda: _invert_checked(self.table)))
            row.addStretch(1)
            self.lbl_sum = QLabel("")
            row.addWidget(self.lbl_sum)
            root.addLayout(row)

            pr = QHBoxLayout()
            pr.addWidget(QLabel("输出文件："))
            self.ent_out = QLineEdit(self._default_out())
            pr.addWidget(self.ent_out, 1)
            pr.addWidget(QPushButton("浏览…", clicked=self._browse_out))
            root.addLayout(pr)
            tip = QLabel("提示：api 路径（./py/xxx.py）相对基准目录解析；只有导出到同目录"
                         "（或同样存在 py/ 的目录）时站内路径才有效。导出不会修改现有配置，"
                         "也不会覆盖未确认的同名文件。")
            tip.setWordWrap(True)
            root.addWidget(tip)

            btn = QHBoxLayout()
            btn.addStretch(1)
            b_cancel = QPushButton("取消", clicked=self.reject)
            b_ok = QPushButton("导出", clicked=self._do_export)
            b_ok.setProperty("accent", "primary")
            btn.addWidget(b_cancel)
            btn.addWidget(b_ok)
            root.addLayout(btn)
            self._refresh_table()

        def _default_out(self):
            base_dir = cfg_base_dir(self.repo_dir, self.cfg_file)
            stem = os.path.splitext(os.path.basename(self.cfg_file))[0]
            return os.path.join(base_dir, "%s.干净%s.json"
                                % (stem, datetime.now().strftime("-%Y%m%d-%H%M%S")))

        def _browse_out(self):
            path, _ = QFileDialog.getSaveFileName(
                self, "导出为（不会修改现有配置）",
                self.ent_out.text() or self._default_out(),
                "配置文件 (*.json);;所有文件 (*.*)")
            if path:
                self.ent_out.setText(path)

        # ---- 过滤与勾选 ----
        def _shown_entries(self):
            kw = self.search.text().strip().lower()
            out = []
            for e in self.entries:
                blob = "%s %s %s" % (e.get("key", ""), e.get("name", ""), e.get("api", ""))
                if kw and kw not in blob.lower():
                    continue
                out.append(e)
            return out

        def _is_excluded(self, e):
            key = str(e.get("key", ""))
            dm = self.detect
            try:
                if self.cb_no_adult.isChecked() and dm.get("adult", {}).get(key, (False,))[0]:
                    return True
                if self.cb_no_duanju.isChecked() and dm.get("duanju", {}).get(key, (False,))[0]:
                    return True
                if self.cb_no_live.isChecked() and dm.get("live", {}).get(key, (False,))[0]:
                    return True
            except Exception:
                pass
            if self.cb_no_disabled.isChecked() and e.get("_disabled", False):
                return True
            return False

        def _flags_text(self, e):
            key = str(e.get("key", ""))
            marks = []
            dm = self.detect
            try:
                if dm.get("adult", {}).get(key, (False,))[0]:
                    marks.append("成人")
                if dm.get("duanju", {}).get(key, (False,))[0]:
                    marks.append("短剧")
                if dm.get("live", {}).get(key, (False,))[0]:
                    marks.append("直播")
            except Exception:
                pass
            if e.get("_disabled", False):
                marks.append("已禁用")
            return "/".join(marks) or "-"

        def _refresh_table(self):
            self.table.setRowCount(0)
            for e in self._shown_entries():
                _add_check_row(self.table, not self._is_excluded(e),
                               [e.get("name", ""), e.get("key", ""), e.get("api", ""),
                                e.get("type", ""), self._flags_text(e)])
            self.lbl_sum.setText("显示 %d / 共 %d 个站点，勾选 %d 个将写入导出文件"
                                 % (self.table.rowCount(), len(self.entries),
                                    self._checked_count()))

        def _checked_count(self):
            n = 0
            for r in range(self.table.rowCount()):
                if _row_checked(self.table, r):
                    n += 1
            return n

        def keep_keys(self):
            """当前勾选（且在显示范围内）的站点 key 集合。"""
            keep = set()
            for r in range(self.table.rowCount()):
                if _row_checked(self.table, r):
                    k = _cell(self.table, r, E_KEY)
                    if k:
                        keep.add(k)
            return keep

        # ---- 落盘 ----
        def _do_export(self):
            path = self.ent_out.text().strip()
            if not path:
                QMessageBox.information(self, "提示", "请先选择输出文件。")
                return
            d = os.path.dirname(path)
            if d and not os.path.isdir(d):
                QMessageBox.warning(self, "路径无效", "目录不存在：%s" % d)
                return
            if os.path.isfile(path):
                if QMessageBox.question(self, "覆盖确认",
                                        "文件已存在，覆盖它？\n%s" % path) != QMessageBox.Yes:
                    return
            self.out_path = path
            self.accept()

    class _SplitExportDialog(QDialog):
        """🔀 智能分流导出：按 adult 字段一键生成「纯净版（剔除成人）」+「完整版」两套配置。

        判定依据（按用户拍板）：只按现有 adult 字段 / 已跑过的检测结果，不做实时内容检测。
        只读预览 + 导出，不修改当前配置。输出文件名默认成对（*.纯净版.json / *.完整版.json）。
        """

        def __init__(self, parent, repo_dir, cfg_file, raw, entries, adult_keys=None):
            super().__init__(parent)
            self.repo_dir = repo_dir
            self.cfg_file = cfg_file
            self.raw = raw
            self.entries = [dict(e) for e in (entries or [])]
            self.adult_keys = set(adult_keys or [])
            self.setWindowTitle(tagged_title("🔀 智能分流导出（纯净版 / 完整版）"))
            self.resize(880, 600)
            self._build()

        def _build(self):
            root = QVBoxLayout(self)
            tip = QLabel(
                "按 <b>adult 标记</b>把配置一键分成两套：<b>纯净版</b>（剔除成人站点）"
                "与 <b>完整版</b>（保留全部）。判定只用现有 adult 字段／已跑过的检测结果，"
                "<b>不改动当前配置</b>。")
            tip.setTextFormat(Qt.RichText)
            tip.setWordWrap(True)
            root.addWidget(tip)

            # 顶部：成人来源选择（仅影响“哪些算成人”，不改变导出结构）
            src = QHBoxLayout()
            src.addWidget(QLabel("成人判定："))
            self.cb_use_detect = QCheckBox("叠加自动检测结果（成人扫描）")
            self.cb_use_detect.setToolTip(
                "勾选后：除 adult 字段外，凡成人扫描标为“是”的站点也一并剔除出纯净版")
            self.cb_use_detect.setChecked(True)
            self.cb_use_detect.stateChanged.connect(lambda _s: self._refresh())
            src.addWidget(self.cb_use_detect)
            src.addStretch(1)
            root.addLayout(src)

            # 预览表：名称 / key / 判定（成人→仅完整版；否则两版都留）
            self.table = _mk_check_table(["", "名称", "key", "api", "判定"])
            root.addWidget(self.table, 1)

            row = QHBoxLayout()
            self.lbl_sum = QLabel("")
            row.addWidget(self.lbl_sum, 1)
            root.addLayout(row)

            # 输出目录 + 文件名
            pr = QHBoxLayout()
            pr.addWidget(QLabel("输出目录："))
            self.ent_dir = QLineEdit(self._default_dir())
            pr.addWidget(self.ent_dir, 1)
            pr.addWidget(QPushButton("浏览…", clicked=self._browse_dir))
            root.addLayout(pr)

            nr = QHBoxLayout()
            nr.addWidget(QLabel("文件名："))
            self.ent_pure = QLineEdit(self._default_name("纯净版"))
            self.ent_full = QLineEdit(self._default_name("完整版"))
            nr.addWidget(self.ent_pure, 1)
            nr.addWidget(QLabel(" / "))
            nr.addWidget(self.ent_full, 1)
            root.addLayout(nr)
            ntip = QLabel("提示：api 路径（./py/xxx.py）相对基准目录解析；建议导出到与原配置"
                          "同目录（或同样存在 py/ 的目录），站内路径才有效。")
            ntip.setWordWrap(True)
            root.addWidget(ntip)

            btn = QHBoxLayout()
            btn.addStretch(1)
            btn.addWidget(QPushButton("取消", clicked=self.reject))
            b_ok = QPushButton("导出两套", clicked=self._do_export)
            b_ok.setProperty("accent", "primary")
            btn.addWidget(b_ok)
            root.addLayout(btn)
            self._refresh()

        # ---- 判定 ----
        def _adult_set(self):
            """当前视为成人的 key 集合：adult 字段 +（可选）自动检测结果。"""
            s = set()
            for e in self.entries:
                key = str(e.get("key", ""))
                if _entry_is_adult(e, None) or (
                        self.cb_use_detect.isChecked() and key in self.adult_keys):
                    s.add(key)
            return s

        def _refresh(self):
            self.table.setRowCount(0)
            akeys = self._adult_set()
            for e in self.entries:
                key = str(e.get("key", ""))
                is_a = key in akeys
                verdict = "🔞 仅完整版" if is_a else "✅ 两版都含"
                _add_check_row(self.table, not is_a,
                               [e.get("name", ""), key, e.get("api", ""), verdict])
            total = len(self.entries)
            self.lbl_sum.setText("共 %d 个站点：纯净版保留 %d 个、剔除 %d 个（成人）；"
                                 "完整版保留全部 %d 个。"
                                 % (total, total - len(akeys), len(akeys), total))

        # ---- 路径 ----
        def _default_dir(self):
            return cfg_base_dir(self.repo_dir, self.cfg_file)

        def _default_name(self, tag):
            stem = os.path.splitext(os.path.basename(self.cfg_file))[0]
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            return "%s.%s-%s.json" % (stem, tag, ts)

        def _browse_dir(self):
            d = QFileDialog.getExistingDirectory(
                self, "选择输出目录（不改动现有配置）", self.ent_dir.text() or self._default_dir())
            if d:
                self.ent_dir.setText(d)

        # ---- 落盘 ----
        def _do_export(self):
            out_dir = self.ent_dir.text().strip()
            if not out_dir or not os.path.isdir(out_dir):
                QMessageBox.warning(self, "路径无效", "输出目录不存在：%s" % out_dir)
                return
            pn = self.ent_pure.text().strip()
            fn = self.ent_full.text().strip()
            if not pn or not fn:
                QMessageBox.information(self, "提示", "请填写两套输出文件名。")
                return
            if pn == fn:
                QMessageBox.warning(self, "提示", "两个文件名不能相同。")
                return
            pure_path = os.path.join(out_dir, pn)
            full_path = os.path.join(out_dir, fn)
            for p in (pure_path, full_path):
                if os.path.isfile(p):
                    if QMessageBox.question(self, "覆盖确认",
                                            "文件已存在，覆盖它？\n%s" % p) != QMessageBox.Yes:
                        return
            keys = [str(e.get("key", "")) for e in self.entries]
            try:
                res = split_by_adult(self.raw, self.entries,
                                     adult_keys=self._adult_set(), base_keys=keys)
            except Exception as ex:
                QMessageBox.critical(self, "错误", "分流导出失败：%s" % ex)
                return
            try:
                with open(pure_path, "w", encoding="utf-8") as f:
                    f.write(res["pure_text"])
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(res["full_text"])
            except Exception as ex:
                QMessageBox.critical(self, "错误", "写入失败：%s" % ex)
                return
            self.result = {"pure": pure_path, "full": full_path, **res}
            self.accept()

    class _MergeDialog(QDialog):
        """🔀 合并导入：把另一份配置（本地文件 / 粘贴文本 / 远程 URL）的站点并入当前仓库。

        判重口径（与全局一致，修复「之前合并结果错得离谱」的根因）：
          功能身份 = site_fingerprint(obj) = (api, jar, ext) 三元组。
            · 与现有站点指纹相同  → 判定「重复」，默认跳过（可改为覆盖）；
            · key 相同但指纹不同  → 判定「冲突」，默认新增并自动改名（避免撞 key）；
            · 完全不同            → 判定「新增」；
            · 同一批导入自身重复  → 判定「跳过」（锁定，不可改）。
        写入时保留条目**全部字段**（ext/jar/adult/changeable/categories…），
        并自动搬运本地 spider 的 .py/.js/.drpy 与本地 jar（仅当来源是本地文件、
        两仓库路径都明确时；目标已存在则跳过，源缺失则记 missing_src）。
        """

        _ACTION_VALUES = ("add", "overwrite", "skip")
        _TYPE_LABEL = {0: "XML", 1: "直连", 3: "Spider", 4: "目录"}
        _VERDICT_TEXT = {
            "new": "新增",
            "dup": "重复(功能相同)",
            "conflict": "冲突(同 key·将改名)",
            "skip": "跳过(批次内重复)",
        }

        def __init__(self, parent, repo_dir, cfg_file, raw, base_dir, src_repo_dir=None):
            super().__init__(parent)
            self.repo_dir = repo_dir
            self.cfg_file = cfg_file
            self.raw = raw
            self.base_dir = base_dir
            self.src_repo_dir = src_repo_dir   # 来源仓库根目录（本地文件时给出，用于搬运配套）
            self.src_remote_base = None        # 远程来源配置 URL 的目录（用于下载本地配套文件）
            self.src_text = None               # 来源原始文本（用于提取 lives/parses）
            self.src_lives = []                # 来源配置里的直播源
            self.src_parses = []               # 来源配置里的解析源
            self.plan = None
            self.rows = []
            self.result_text = ""
            self.stats = {}
            self.file_stats = {}
            self.setWindowTitle(tagged_title("🔀 合并导入"))
            self.resize(980, 640)
            self._build()

        def _build(self):
            root = QVBoxLayout(self)
            tip = QLabel(
                "把另一份影视仓配置的站点合并进当前仓库。<br>"
                "判重口径：功能身份 = <b>(type + api + jar + ext)</b> 四元组；"
                "jar 型多站点（同名类名 + 不同 ext）<b>不会被误并</b>。<br>"
                "写入后保留条目全部字段，并自动搬运配套 .py/.js/.drpy 与 jar"
                "（本地文件 / 远程 URL 均可；<b>同名但内容不同会改名并同步改写 api/jar</b>）。")
            tip.setTextFormat(Qt.RichText)
            tip.setWordWrap(True)
            root.addWidget(tip)

            # ---- 来源：三个 Tab ----
            self.tabs = QTabWidget()
            # Tab 1：本地文件
            w_file = QWidget()
            vf = QVBoxLayout(w_file)
            hf = QHBoxLayout()
            self.ent_file = QLineEdit()
            self.ent_file.setPlaceholderText("选择另一份配置文件（含 sites 数组的 .json / .jsonc）")
            hf.addWidget(self.ent_file, 1)
            hf.addWidget(QPushButton("浏览…", clicked=self._browse_file))
            vf.addLayout(hf)
            vf.addWidget(QLabel("选择本地文件时，若该文件所在仓库含 ./py/*.py 与本地 jar，"
                               "写入后会自动搬运到当前仓库：同名且内容相同则跳过；"
                               "同名但内容不同会弹窗确认后改名（默认）或覆盖（先备份）。"))
            vf.addStretch(1)
            self.tabs.addTab(w_file, "本地文件")

            # Tab 2：粘贴文本
            w_paste = QWidget()
            vp = QVBoxLayout(w_paste)
            self.txt_paste = QPlainTextEdit()
            self.txt_paste.setPlaceholderText("在此粘贴配置文本（含 sites 数组的 JSON / JSONC）")
            vp.addWidget(self.txt_paste, 1)
            w_paste.setLayout(vp)
            self.tabs.addTab(w_paste, "粘贴文本")

            # Tab 3：远程 URL
            w_url = QWidget()
            vu = QVBoxLayout(w_url)
            hu = QHBoxLayout()
            self.ent_url = QLineEdit()
            self.ent_url.setPlaceholderText("http(s):// 一份可公开访问的配置文件")
            hu.addWidget(self.ent_url, 1)
            vu.addLayout(hu)
            vu.addStretch(1)
            self.tabs.addTab(w_url, "远程 URL")
            root.addWidget(self.tabs)

            # ---- 解析按钮 ----
            hparse = QHBoxLayout()
            hparse.addWidget(QPushButton("解析本地文件", clicked=self._parse_file))
            hparse.addWidget(QPushButton("解析粘贴文本", clicked=self._parse_paste))
            hparse.addWidget(QPushButton("下载并解析 URL", clicked=self._parse_url))
            hparse.addStretch(1)
            root.addLayout(hparse)

            # ---- 预览表 ----
            self.table = _mk_check_table(["", "名称", "key", "api · 类型", "判定", "操作"])
            self.table.horizontalHeader().setStretchLastSection(False)
            root.addWidget(self.table, 1)

            # ---- 批量 + 汇总 ----
            hsum = QHBoxLayout()
            hsum.addWidget(QPushButton("全部加入", clicked=lambda: self._set_action_bulk("add")))
            hsum.addWidget(QPushButton("全部跳过", clicked=lambda: self._set_action_bulk("skip")))
            hsum.addStretch(1)
            self.lbl_sum = QLabel("尚未解析来源")
            hsum.addWidget(self.lbl_sum)
            root.addLayout(hsum)

            # ---- 底部 ----
            btn = QHBoxLayout()
            btn.addStretch(1)
            b_cancel = QPushButton("取消", clicked=self.reject)
            b_ok = QPushButton("合并写入", clicked=self._apply)
            b_ok.setProperty("accent", "primary")
            btn.addWidget(b_cancel)
            btn.addWidget(b_ok)
            root.addLayout(btn)

        # ---- 来源解析 ----
        def _browse_file(self):
            path, _ = QFileDialog.getOpenFileName(
                self, "选择配置文件", self.ent_file.text() or "",
                "配置 (*.json *.jsonc);;所有文件 (*.*)")
            if path:
                self.ent_file.setText(path)

        def _parse_file(self):
            path = self.ent_file.text().strip()
            if not path or not os.path.isfile(path):
                QMessageBox.warning(self, "提示", "请先选择有效的配置文件。")
                return
            self.src_repo_dir = os.path.dirname(os.path.abspath(path))
            self._mirror_note = ""
            try:
                text = read_text(path)
                items = load_sites_from_text(text)
            except Exception as ex:
                QMessageBox.critical(self, "解析失败", str(ex))
                return
            self.src_text = text
            self._build_plan(items)

        def _parse_paste(self):
            text = self.txt_paste.toPlainText()
            if not text.strip():
                QMessageBox.information(self, "提示", "请先粘贴配置文本。")
                return
            self.src_repo_dir = None
            self._mirror_note = ""
            try:
                items = load_sites_from_text(text)
            except Exception as ex:
                QMessageBox.critical(self, "解析失败", str(ex))
                return
            self.src_text = text
            self._build_plan(items)

        def _parse_url(self):
            url = self.ent_url.text().strip()
            if not url:
                QMessageBox.information(self, "提示", "请先填写远程 URL。")
                return
            self.src_repo_dir = None
            from urllib.parse import urljoin
            self.src_remote_base = urljoin(url, "./")
            info = {}
            try:
                text = fetch_text_from_url(url, info=info)
                items = load_sites_from_text(text)
            except Exception as ex:
                QMessageBox.critical(self, "解析失败", str(ex))
                return
            if info.get("mirror"):
                self._mirror_note = info["mirror"]
            self.src_text = text
            self._build_plan(items)

        def _build_plan(self, items):
            if not items:
                QMessageBox.information(self, "提示", "来源里没有可识别的站点条目。")
                return
            try:
                base_items = parse_sites_with_disabled(self.raw)
            except Exception:
                base_items = []
            self.plan = plan_merge(base_items, items)
            self.rows = self.plan["rows"]
            # 提取来源配置里的直播源 / 解析源（合并导入时不自动并入，需用户逐条勾选）
            if self.src_text:
                self.src_lives = load_array_items(self.src_text, "lives")
                self.src_parses = load_array_items(self.src_text, "parses")
                self.src_ads = load_array_items(self.src_text, "ads", accept_strings=True)
            self._fill_table()

        # ---- 预览表 ----
        def _fill_table(self):
            self.table.setRowCount(0)
            for row in self.rows:
                obj = row["obj"]
                verdict = row["verdict"]
                name = obj.get("name", "") or obj.get("key", "")
                key = obj.get("key", "")
                api = obj.get("api", "")
                try:
                    ti = int(obj.get("type", ""))
                except Exception:
                    ti = None
                type_label = self._TYPE_LABEL.get(ti, str(obj.get("type", "")))
                api_type = "%s · %s" % (api, type_label)

                cb = QCheckBox()
                include = verdict in ("new", "conflict")
                cb.setChecked(include)
                combo = QComboBox()
                combo.addItems(["新增", "覆盖", "跳过"])
                combo.setCurrentIndex({"add": 0, "overwrite": 1, "skip": 2}[row["action"]])
                combo.currentIndexChanged.connect(self._refresh_summary)
                locked = (verdict == "skip")
                if locked:
                    cb.setChecked(False)
                    cb.setEnabled(False)
                    combo.setEnabled(False)

                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setCellWidget(r, 0, cb)
                self.table.setItem(r, 1, QTableWidgetItem(str(name)))
                self.table.setItem(r, 2, QTableWidgetItem(str(key)))
                self.table.setItem(r, 3, QTableWidgetItem(api_type))
                self.table.setItem(r, 4, QTableWidgetItem(self._VERDICT_TEXT.get(verdict, verdict)))
                self.table.setCellWidget(r, 5, combo)
            self._refresh_summary()

        def _refresh_summary(self):
            if not self.plan:
                self.lbl_sum.setText("尚未解析来源")
                return
            s = self.plan["summary"]
            add = ov = sk = 0
            for i in range(self.table.rowCount()):
                cb = self.table.cellWidget(i, 0)
                combo = self.table.cellWidget(i, 5)
                if cb is not None and cb.isEnabled() and not cb.isChecked():
                    sk += 1
                    continue
                act = self._ACTION_VALUES[combo.currentIndex()] if combo is not None else "skip"
                if act == "add":
                    add += 1
                elif act == "overwrite":
                    ov += 1
                else:
                    sk += 1
            self.lbl_sum.setText(
                "来源共 %d 条：将新增 %d · 覆盖 %d · 跳过 %d　"
                "（解析判定：重复 %d / 冲突 %d / 批次内重复 %d）%s"
                % (len(self.rows), add, ov, sk, s["dup"], s["conflict"], s["skip"],
                   "　🚀 直连失败，配置经镜像获取" if getattr(self, "_mirror_note", "") else ""))

        def _set_action_bulk(self, mode):
            for i in range(self.table.rowCount()):
                cb = self.table.cellWidget(i, 0)
                combo = self.table.cellWidget(i, 5)
                if cb is None or not cb.isEnabled():
                    continue
                if mode == "add":
                    cb.setChecked(True)
                    combo.setCurrentIndex(0)
                else:
                    cb.setChecked(False)
                    combo.setCurrentIndex(2)
            self._refresh_summary()

        # ---- 落盘（写回由 App.merge_import 负责备份+刷新；此处只算新文本）----
        def _apply(self):
            if not self.plan:
                QMessageBox.information(self, "提示", "请先解析一份来源配置。")
                return
            rows = []
            for i, row in enumerate(self.rows):
                cb = self.table.cellWidget(i, 0)
                combo = self.table.cellWidget(i, 5)
                include = bool(cb and cb.isEnabled() and cb.isChecked())
                action = self._ACTION_VALUES[combo.currentIndex()] if combo is not None else "skip"
                if not include:
                    action = "skip"
                new_row = dict(row)
                new_row["action"] = action
                rows.append(new_row)
            src = self.src_repo_dir
            # ⚠️ 远程来源也要给 target_repo_dir，否则配套文件根本不会下载（历史上漏了这步）
            tgt = self.base_dir if (self.src_repo_dir or self.src_remote_base) else None
            # ---- 配套文件：先规划（含内容级冲突检测），有冲突则弹窗让用户逐文件处置 ----
            file_plan = None
            decisions = None
            objs = [r["obj"] for r in rows if r["action"] in ("add", "overwrite")]
            if tgt and objs:
                try:
                    if self.src_repo_dir:
                        file_plan = plan_companion_files_local(self.src_repo_dir, tgt, objs)
                    elif self.src_remote_base:
                        file_plan = plan_companion_files_remote(self.src_remote_base, tgt, objs)
                except Exception:
                    file_plan = None
            if file_plan and file_plan.get("conflicts"):
                fdlg = _FileConflictDialog(self, file_plan)
                if fdlg.exec() != QDialog.Accepted:
                    return
                decisions = fdlg.decisions
            try:
                new_text, stats, file_stats = apply_merge(
                    self.raw, rows, src_repo_dir=src, target_repo_dir=tgt,
                    src_remote_base=self.src_remote_base,
                    file_plan=file_plan, file_decisions=decisions)
            except ValueError as ex:
                QMessageBox.critical(self, "合并失败", str(ex))
                return
            # ---- lives / parses：弹出明细清单让用户逐条勾选 ----
            sections = []
            if self.src_lives:
                sections.append({"name": "lives", "label": "直播源 (lives)",
                                 "existing": load_array_items(new_text, "lives"),
                                 "incoming": self.src_lives,
                                 "fp": live_fingerprint, "fmt": fmt_section_entry})
            if self.src_parses:
                sections.append({"name": "parses", "label": "解析源 (parses)",
                                 "existing": load_array_items(new_text, "parses"),
                                 "incoming": self.src_parses,
                                 "fp": parse_fingerprint, "fmt": fmt_section_entry})
            if self.src_ads:
                sections.append({"name": "ads", "label": "广告拦截 (ads)",
                                 "existing": load_array_items(new_text, "ads", accept_strings=True),
                                 "incoming": self.src_ads,
                                 "fp": ads_fingerprint, "fmt": fmt_section_entry})
            if sections:
                dlg = _LivesDialog(self, new_text, sections)
                if dlg.exec() != QDialog.Accepted:
                    return
                new_text = dlg.result_text
                stats["lives_parses_added"] = dlg.added
            self.result_text = new_text
            self.stats = stats
            self.file_stats = file_stats
            self.accept()

    class _LivesDialog(QDialog):
        """直播源 / 解析源明细勾选弹窗：把来源配置里的 lives/parses 逐条列出，
        已存在的（按名称+URL/API 判定重复）默认不勾选，用户勾选后才并入当前仓库。
        sections: [{name, label, existing, incoming, fp, fmt}, ...]（lives / parses 各一项）。"""

        def __init__(self, parent, base_text, sections):
            super().__init__(parent)
            self.base_text = base_text
            self.sections = sections
            self.setWindowTitle(tagged_title("选择要导入的直播源 / 解析源"))
            self.resize(900, 560)
            self._build()

        def _build(self):
            root = QVBoxLayout(self)
            tip = QLabel("以下来源的条目不在「站点」合并范围内，需你逐条勾选是否导入。"
                         "已存在的（按内容判定重复）默认不勾选；"
                         "勾选的会在确认后并入当前仓库对应数组。")
            tip.setWordWrap(True)
            root.addWidget(tip)
            self.tabs = QTabWidget()
            for sec in self.sections:
                w = QWidget()
                v = QVBoxLayout(w)
                table = _mk_check_table(["", "名称", "URL / API", "判定"])
                plan = plan_section_merge(sec["existing"], sec["incoming"], sec["fp"])
                sec["plan"] = plan
                sec["table"] = table
                self._fill_tab(table, plan)
                v.addWidget(table, 1)
                h = QHBoxLayout()
                # ⚠️ QPushButton.clicked 会带一个 bool 参数发出；lambda 的第一个形参必须把它吃掉，
                # 否则 `lambda t=table:` 会被调用成 t=False → 按钮"点了没反应"（无控制台时异常被吞）。
                # 同时用第二形参 t=table 绑定本次迭代的表格，避免循环变量晚绑定。
                h.addWidget(QPushButton("全选", clicked=lambda _c=False, t=table: self._bulk(t, True)))
                h.addWidget(QPushButton("全不选", clicked=lambda _c=False, t=table: self._bulk(t, False)))
                h.addStretch(1)
                v.addLayout(h)
                self.tabs.addTab(w, sec["label"])
            root.addWidget(self.tabs, 1)
            btn = QHBoxLayout()
            btn.addStretch(1)
            btn.addWidget(QPushButton("取消", clicked=self.reject))
            b_ok = QPushButton("确认导入", clicked=self._apply)
            b_ok.setProperty("accent", "primary")
            btn.addWidget(b_ok)
            root.addLayout(btn)

        def _fill_tab(self, table, plan):
            table.setRowCount(0)
            for row in plan["rows"]:
                obj = row["obj"]
                if isinstance(obj, str):
                    name, url = obj, ""
                else:
                    name = str(obj.get("name") or "")
                    url = obj.get("url") or obj.get("api") or ""
                    if isinstance(url, list):
                        url = " | ".join(str(u) for u in url)
                cb = QCheckBox()
                locked = (row["verdict"] == "dup")
                cb.setChecked(not locked)
                if locked:
                    cb.setEnabled(False)
                r = table.rowCount()
                table.insertRow(r)
                table.setCellWidget(r, 0, cb)
                table.setItem(r, 1, QTableWidgetItem(str(name)))
                table.setItem(r, 2, QTableWidgetItem(str(url)))
                table.setItem(r, 3, QTableWidgetItem("重复(已存在)" if locked else "新增"))

        def _bulk(self, table, val):
            for i in range(table.rowCount()):
                cb = table.cellWidget(i, 0)
                if cb and cb.isEnabled():
                    cb.setChecked(val)

        def _apply(self):
            text = self.base_text
            total = 0
            for sec in self.sections:
                rows = []
                table = sec["table"]
                for i, prow in enumerate(sec["plan"]["rows"]):
                    cb = table.cellWidget(i, 0)
                    action = "add" if (cb and cb.isEnabled() and cb.isChecked()) else "skip"
                    nr = dict(prow)
                    nr["action"] = action
                    rows.append(nr)
                text, added = apply_merge_section(text, sec["name"], rows, sec["fmt"])
                total += added
            self.result_text = text
            self.added = total
            self.accept()

    class _FileConflictDialog(QDialog):
        """配套文件内容冲突处置弹窗。

        场景：目标仓库里已存在**同名**配套文件（./py/x.py、jars/x.jar…），但内容与来源不同。
        「名字相同 ≠ 内容相同」——此时不能静默跳过（会让导入的站点跑到本地旧文件），
        默认把来源文件**改名**为 _2 后缀，并同步改写配置里的 api/jar，两侧都不破坏；
        也可选择「覆盖」（先自动备份目标文件）或「跳过」（不搬，需人工处理）。"""

        _OPTS = ("rename", "overwrite", "skip")
        _TXT = {"rename": "重命名（推荐）", "overwrite": "覆盖（先备份）", "skip": "跳过"}

        def __init__(self, parent, plan):
            super().__init__(parent)
            self.plan = plan or {}
            self.decisions = {}
            self.setWindowTitle(tagged_title("⚠️ 配套文件同名冲突"))
            self.resize(900, 480)
            self._build()

        def _build(self):
            root = QVBoxLayout(self)
            n = len(self.plan.get("conflicts", []))
            same = len(self.plan.get("same", []))
            new = len(self.plan.get("new", []))
            tip = QLabel(
                "以下 <b>%d</b> 个配套文件在目标仓库里<b>同名但内容不同</b>。<br>"
                "默认<b>重命名</b>：来源文件改名为 <code>_2</code> 后缀，并把配置里对应的 "
                "api/jar 同时改写为新名 —— 本地旧文件与导入的新文件都不被破坏。<br>"
                "也可改为「覆盖」（自动先备份目标文件）或「跳过」（不搬，需你手动处理）。<br>"
                "<span style='color:#888'>&nbsp;·&nbsp;内容相同的 %d 个已自动跳过；"
                "新增的 %d 个将直接搬运，无需处置。</span>" % (n, same, new))
            tip.setTextFormat(Qt.RichText)
            tip.setWordWrap(True)
            root.addWidget(tip)

            self.table = _mk_check_table(["原文件（相对仓库）", "处置", "结果"])
            for it in self.plan.get("conflicts", []):
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(it.get("rel", "")))
                combo = QComboBox()
                combo.addItems([self._TXT[k] for k in self._OPTS])
                combo.setCurrentIndex(0)     # 默认 rename
                combo.currentIndexChanged.connect(lambda _i, row=r: self._refresh_row(row))
                self.table.setCellWidget(r, 1, combo)
                self.table.setItem(r, 2, QTableWidgetItem(it.get("new_rel", "")))
            root.addWidget(self.table, 1)

            btn = QHBoxLayout()
            btn.addStretch(1)
            btn.addWidget(QPushButton("取消", clicked=self.reject))
            b_ok = QPushButton("确认", clicked=self._apply)
            b_ok.setProperty("accent", "primary")
            btn.addWidget(b_ok)
            root.addLayout(btn)

        def _refresh_row(self, row):
            rel_item = self.table.item(row, 0)
            combo = self.table.cellWidget(row, 1)
            res_item = self.table.item(row, 2)
            if rel_item is None or res_item is None:
                return
            dec = self._OPTS[combo.currentIndex()] if combo is not None else "rename"
            if dec == "rename":
                res_item.setText(self.plan.get("map", {}).get(rel_item.text(), ""))
            elif dec == "overwrite":
                res_item.setText("原地覆盖（写入前自动备份）")
            else:
                res_item.setText("不搬运（配置仍指向原路径，需人工处理）")

        def _apply(self):
            for row in range(self.table.rowCount()):
                rel_item = self.table.item(row, 0)
                combo = self.table.cellWidget(row, 1)
                if rel_item is None:
                    continue
                dec = self._OPTS[combo.currentIndex()] if combo is not None else "rename"
                self.decisions[rel_item.text()] = dec
            self.accept()

    # ---- 源测活：模拟影视仓加载 py 源（homeContent 分类栏 → 首页影片），判定死源 ----
    def _probe_esc(s):
        """HTML 转义：分类名里可能带 & < >。"""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    class _ProbeWorker(QThread):
        """逐个跑源（按 type 路由 + 硬超时），不阻塞界面。"""

        item_done = Signal(str, str, dict, bool)   # key, 名称, 结果 dict, is_py
        progress = Signal(int, int, str)     # 已完成, 总数, 当前站点名
        finished_all = Signal()

        def __init__(self, dialog, items):
            super().__init__(dialog)
            self.dialog = dialog
            self.items = items               # [(key, name, entry, api, ext), ...]
            self._stop = False

        def stop(self):
            self._stop = True

        def run(self):
            total = len(self.items)
            for i, (key, name, entry, api, ext) in enumerate(self.items, 1):
                if self._stop:
                    break
                d = self.dialog
                if d is not None and getattr(d, "_closed", False):
                    break
                try:
                    self.progress.emit(i - 1, total, name)
                except Exception:
                    pass
                try:
                    base_dir = getattr(d, "base_dir", None)
                    r, is_py = probe_source(entry, base_dir=base_dir,
                                           timeout=PROBE_TIMEOUT_DEFAULT, ext=ext,
                                           ua=None, use_proxy=False)
                except Exception as ex:
                    r = {"ok": False, "alive": False, "classes": [], "videos": 0,
                         "titles": [], "via": "", "style": "",
                         "error": "%s: %s" % (type(ex).__name__, ex)}
                    is_py = False
                try:
                    self.item_done.emit(key, name, r, is_py)
                except Exception:
                    pass
            # 收尾：进度条拉满。循环里报的是「开始测第 i 个之前」的完成数，
            # 最后一个测完若不再报一次，进度条会永远停在 total-1（看着像没跑完）。
            try:
                self.progress.emit(total, total, "")
            except Exception:
                pass
            try:
                self.finished_all.emit()
            except Exception:
                pass

    class _ProbeDialog(QDialog):
        """源测活结果：表格 + 模拟影视仓顶部那一排分类标签（截图里的红框区）。"""

        P_NAME, P_VERDICT, P_CLASSES, P_TABS, P_VIDEOS, P_NOTE = 0, 1, 2, 3, 4, 5

        def __init__(self, parent, items):
            super().__init__(parent)
            self.items = items               # [(key, name, entry, api, ext), ...]
            self.results = {}                # key -> 结果 dict
            self.is_py_map = {}              # key -> 本次是否走了 .py 子进程
            self._row_level = {}             # 行号 -> ok/bad/err/none
            self._worker = None
            self._closed = False
            self.base_dir = getattr(parent, "base_dir", None)
            self.setWindowTitle(tagged_title("🩺 源测活（模拟影视仓加载）"))
            self.resize(920, 580)
            root = QVBoxLayout(self)

            tip = QLabel(
                "<b>测活原理</b>　按 type 路由：直连 CMS(type:1) 走 HTTP 取分类栏；"
                "Spider(type:3) 在子进程里加载 .py → 调 homeContent 取分类栏"
                "（即影视仓顶部那一排标签）→ 再取首页影片；<b>分类栏出不来 = 死源</b>。"
                "<br><b>操作提示</b>　💡 双击一行 = 按 type 打开对应目标（本地 .py / 所依赖的 jar / API 链接）；"
                "右键 = 编辑配置 / 打开目标（按 type）/ 禁用 / 删除。")
            tip.setTextFormat(Qt.RichText)
            tip.setWordWrap(True)
            root.addWidget(tip)

            self.table = QTableWidget(len(items), 6)
            self.table.setHorizontalHeaderLabels(
                ["名称", "判定", "分类数", "分类标签预览（影视仓红框区）", "首页影片", "说明"])
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.verticalHeader().setVisible(False)
            try:
                hh = self.table.horizontalHeader()
                hh.setSectionResizeMode(self.P_TABS, QHeaderView.Stretch)
                hh.setSectionResizeMode(self.P_NAME, QHeaderView.ResizeToContents)
            except Exception:
                pass
            self.table.itemSelectionChanged.connect(self._show_detail)
            self.table.itemSelectionChanged.connect(self._update_sel_btn)
            # 双击 = 打开该源的 .py（用系统默认编辑器）；右键 = 查看/修改/删除
            self.table.cellDoubleClicked.connect(self._on_double_click)
            try:
                self.table.setContextMenuPolicy(Qt.CustomContextMenu)
                self.table.customContextMenuRequested.connect(self._ctx_menu)
            except Exception:
                pass
            root.addWidget(self.table, 1)
            for r, (_k, name, _e2, _api, _e) in enumerate(items):
                for c in range(6):
                    self._set(r, c, name if c == self.P_NAME else
                              ("待测…" if c == self.P_VERDICT else ""))

            # 模拟影视仓的分类标签栏（选中行的完整预览）
            self.lbl_prev = QLabel("选中一行查看该源的完整分类栏")
            root.addWidget(self.lbl_prev)
            self.preview = QLabel("")
            self.preview.setWordWrap(True)
            self.preview.setStyleSheet(
                "padding:6px; border:1px solid %s; border-radius:6px;"
                % ("#3a4048" if IS_DARK else "#dde3ea"))
            self.preview.setMinimumHeight(56)
            root.addWidget(self.preview)

            hb = QHBoxLayout()
            self.btn_start = QPushButton("▶ 测活全部", clicked=lambda: self._start(None))
            self.btn_start_sel = QPushButton("▶ 测活选中", clicked=lambda: self._start("selected"))
            self.btn_stop = QPushButton("⏹ 停止", clicked=self._stop)
            self.btn_stop.setEnabled(False)
            self.btn_start_sel.setEnabled(False)
            self.cb_bad = QCheckBox("只看死源/异常")
            self.cb_bad.stateChanged.connect(self._apply_filter)
            hb.addWidget(self.btn_start)
            hb.addWidget(self.btn_start_sel)
            hb.addWidget(self.btn_stop)
            hb.addWidget(self.cb_bad)
            hb.addStretch(1)
            self.lbl_sum = QLabel("")
            hb.addWidget(self.lbl_sum)
            hb.addWidget(QPushButton("关闭", clicked=self.close))
            root.addLayout(hb)

            self.prog = QProgressBar()
            self.prog.setRange(0, max(1, len(items)))
            self.prog.setValue(0)
            root.addWidget(self.prog)

            if self.table.rowCount() > 0:
                self.table.selectRow(0)
            # 不再默认测活：进入时只展示待测状态，由用户点「测活全部」/「测活选中」触发。
            self.lbl_sum.setText("点击「测活全部」或「测活选中」开始（默认不自动测活）")
            self._update_sel_btn()

        # ---- 表格 ----
        def _set(self, r, col, text, color=None):
            it = self.table.item(r, col)
            if it is None:
                it = QTableWidgetItem(text)
                self.table.setItem(r, col, it)
            else:
                it.setText(text)
            if color:
                try:
                    it.setForeground(QColor(color))
                except Exception:
                    pass

        def _color(self, lvl):
            dark = bool(IS_DARK)
            if lvl == "ok":
                return "#2e7d32" if not dark else "#7ee081"
            if lvl == "bad":
                return "#c0392b" if not dark else "#ff8a80"
            if lvl == "err":
                return "#b26a00" if not dark else "#ffc46b"
            return "#6b7683" if not dark else "#9aa4b0"

        def _tab_html(self, names):
            """把分类名渲染成影视仓顶部标签栏的样子（截图红框那一排）。"""
            dark = bool(IS_DARK)
            bg = "#3a4048" if dark else "#eef2f7"
            fg = "#e6e9ed" if dark else "#2c3e50"
            cells = "".join(
                '<td style="background-color:%s; color:%s; padding:4px 10px;">%s</td>'
                % (bg, fg, _probe_esc(n)) for n in names[:30])
            more = "" if len(names) <= 30 else '<td style="padding:4px 6px;">…</td>'
            return ('<table cellspacing="4"><tr>'
                    '<td style="padding:4px 10px;"><b>主页</b></td>'
                    + cells + more + "</tr></table>")

        def _show_detail(self):
            r = self.table.currentRow()
            if r < 0 or r >= len(self.items):
                return
            name = self.items[r][1]
            res = self.results.get(self.items[r][0])
            if not res:
                self.lbl_prev.setText("“%s”：尚未测到（等待中）" % name)
                self.preview.setText("")
                return
            lvl, verdict = source_verdict(res)
            names = res.get("classes") or []
            self.lbl_prev.setText("“%s” 在影视仓里的分类栏（%s）" % (name, verdict))
            if not names:
                self.preview.setText(res.get("error") or
                                     "分类为空：影视仓里不会显示分类栏，判为死源。")
                return
            html = self._tab_html(names)
            titles = res.get("titles") or []
            if titles:
                html += ('<div style="margin-top:8px;">首页样例：'
                         + _probe_esc(" · ".join(titles)) + "</div>")
            self.preview.setText(html)

        # ---- 行操作：查看 / 修改 / 删除 对应的配置条目与 .py 源文件 ----
        @staticmethod
        def _open_path(path):
            """用系统默认程序打开文件或目录（.py → 默认编辑器；目录 → 资源管理器）。"""
            if not path:
                return False
            try:
                if not (os.path.isfile(path) or os.path.isdir(path)):
                    return False
                try:
                    if QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                        return True
                except Exception:
                    pass
                if os.name == "nt":
                    os.startfile(path)      # noqa: S606 用户主动打开自己仓库里的文件
                    return True
            except Exception:
                pass
            return False

        def _item_at(self, row):
            if row is None or row < 0 or row >= len(self.items):
                return None
            return self.items[row]

        def _on_double_click(self, row, _col):
            """双击 = 按 type 打开该源的正确目标（本地脚本 / 远程 jar / API 链接 / 目录）。"""
            it = self._item_at(row)
            if it is None:
                return
            key, name, entry, api, ext = it
            _parent = self.parent()
            _repo = getattr(_parent, "repo_dir", None) or self.base_dir
            tgt = open_target_of(entry, self.base_dir, _repo)
            kind = tgt["kind"]
            if kind == "file":
                if not self._open_path(tgt["path"]):
                    QMessageBox.information(self, "提示", "无法打开：\n%s" % tgt["path"])
            elif kind == "dir":
                p = tgt["path"]
                if not (p and self._open_path(p)):
                    QMessageBox.information(self, "提示", "无法打开目录：\n%s" % (p or api))
            elif kind in ("jar", "url"):
                QDesktopServices.openUrl(QUrl(tgt["url"]))
            else:
                QMessageBox.information(self, "提示",
                                        "“%s” %s" % (name, tgt["note"] or "无可打开的目标。"))

        def _is_disabled(self, key):
            """该站点在配置里是否已被注释禁用。"""
            p = self.parent()
            try:
                r = p._row_of_key(key)
                if r >= 0 and r < len(p._shown):
                    return bool(p._shown[r].get("_disabled"))
            except Exception:
                pass
            return False

        def _act_in_parent(self, key, fn_name):
            """把操作转交给「管理站点」对话框：它才知道怎么改配置 / 删站点。"""
            p = self.parent()
            if p is None:
                return
            try:
                r = p._row_of_key(key)
            except Exception:
                r = -1
            if r is None or r < 0:
                QMessageBox.information(self, "提示",
                                        "配置里找不到站点 %s（可能已被删除）。" % key)
                return
            try:
                p.table.selectRow(r)
                p.table.setCurrentCell(r, 0)
            except Exception:
                pass
            fn = getattr(p, fn_name, None)
            if fn is None:
                return
            try:
                fn()
            except Exception as ex:
                QMessageBox.warning(self, "操作失败", str(ex))
            self._show_detail()

        def _ctx_menu(self, pos):
            """右键菜单：查看/修改配置、打开 .py、打开目录、禁用/启用、删除。"""
            try:
                row = self.table.rowAt(pos.y())
            except Exception:
                row = self.table.currentRow()
            if row is None or row < 0:
                row = self.table.currentRow()
            it = self._item_at(row)
            if it is None:
                return
            key, name, entry, api, ext = it
            try:
                self.table.selectRow(row)
            except Exception:
                pass
            _parent = self.parent()
            _repo = getattr(_parent, "repo_dir", None) or self.base_dir
            tgt = open_target_of(entry, self.base_dir, _repo)
            menu = QMenu(self)
            menu.addAction("📝 编辑站点配置…", lambda: self._act_in_parent(key, "edit_row"))
            if tgt["kind"] == "file":
                act_py = menu.addAction("📄 打开脚本文件（双击亦可）")
                act_py.triggered.connect(lambda: self._open_path(tgt["path"]))
                act_dir = menu.addAction("📂 打开所在目录")
                act_dir.triggered.connect(
                    lambda: self._open_path(os.path.dirname(os.path.abspath(tgt["path"]))))
            elif tgt["kind"] == "jar":
                act_jar = menu.addAction("📦 打开所依赖的 jar（远程）")
                act_jar.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(tgt["url"])))
            elif tgt["kind"] == "url":
                act_url = menu.addAction("🔗 打开 API 链接")
                act_url.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(tgt["url"])))
            elif tgt["kind"] == "dir":
                act_dir2 = menu.addAction("📂 打开目录")
                act_dir2.triggered.connect(lambda: self._open_path(tgt["path"]))
            menu.addSeparator()
            if self._is_disabled(key):
                menu.addAction("✅ 启用该站点", lambda: self._act_in_parent(key, "enable_selected"))
            else:
                menu.addAction("🚫 禁用该站点", lambda: self._act_in_parent(key, "disable_selected"))
            menu.addSeparator()
            menu.addAction("🗑 删除该站点…", lambda: self._act_in_parent(key, "del_row"))
            menu.addSeparator()
            menu.addAction("💾 保存并写入配置", lambda: self._act_in_parent(key, "save"))
            try:
                menu.exec(self.table.viewport().mapToGlobal(pos))
            except Exception:
                try:
                    menu.exec_(self.table.viewport().mapToGlobal(pos))
                except Exception:
                    pass

        # ---- 流程 ----
        def _selected_keys(self):
            """当前选中的行对应的 key 列表（可能为空）。"""
            try:
                rows = self.table.selectionModel().selectedRows()
            except Exception:
                return []
            keys = []
            for idx in rows:
                r = idx.row()
                if 0 <= r < len(self.items):
                    keys.append(self.items[r][0])
            # 去重保序
            seen = set()
            out = []
            for k in keys:
                if k not in seen:
                    seen.add(k)
                    out.append(k)
            return out

        def _update_sel_btn(self):
            """「测活选中」按钮：有选中行才可用，标题带数量提示。"""
            n = len(self._selected_keys())
            self.btn_start_sel.setEnabled(n > 0)
            try:
                self.btn_start_sel.setText("▶ 测活选中(%d)" % n if n else "▶ 测活选中")
            except Exception:
                pass

        def _start(self, mode=None):
            # mode: None / "all" = 测活全部；"selected" = 只测活选中的行
            if mode == "selected":
                sel = self._selected_keys()
                if not sel:
                    self.lbl_sum.setText("未选中任何行，无法做部分测活")
                    return
                subset = [it for it in self.items if it[0] in set(sel)]
            else:
                subset = self.items
            if not subset:
                return
            # 残留的旧 worker（已结束但引用还在）不该挡住重新测活；
            # 只有**真在跑**的时候才忽略重复点击。
            w = self._worker
            if w is not None:
                if w.isRunning():
                    return
                self._worker = None
            # 只清空本次要测活的行的旧结果，保留其它行已测出的判定
            sel_keys = set(it[0] for it in subset)
            for r, (k, _n, _e2, _api, _e) in enumerate(self.items):
                if k in sel_keys:
                    self.results.pop(k, None)
                    self._row_level.pop(r, None)
                    self._set(r, self.P_VERDICT, "待测…")
                    self._set(r, self.P_CLASSES, "")
                    self._set(r, self.P_TABS, "")
                    self._set(r, self.P_VIDEOS, "")
                    self._set(r, self.P_NOTE, "")
            self.prog.setRange(0, max(1, len(subset)))
            self.prog.setValue(0)
            self.btn_start.setEnabled(False)
            self.btn_start_sel.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.lbl_sum.setText("正在测活 %d 个源…" % len(subset))
            self._worker = _ProbeWorker(self, subset)
            self._worker.item_done.connect(self._on_item)
            self._worker.progress.connect(self._on_progress)
            self._worker.finished_all.connect(self._on_done)
            self._worker.finished.connect(self._worker.deleteLater)
            self._worker.start()

        def _stop(self):
            if self._worker is not None:
                self._worker.stop()
            self.btn_stop.setEnabled(False)
            # 停止是「不再开始下一个」：当前这个源仍会跑完，
            # 因此「开始」要等 worker 真正退出（_on_done）后再亮，避免点了没反应。
            self.btn_start.setEnabled(False)
            self.lbl_sum.setText("正在停止…（当前源测完即止）")

        def _on_progress(self, done, total, name):
            try:
                self.prog.setMaximum(max(1, total))
                self.prog.setValue(done)
            except Exception:
                pass
            if name and not self.results.get(name):
                pass
            self.lbl_sum.setText("正在测：%s" % name)

        def _on_item(self, key, name, res, is_py):
            self.results[key] = res
            self.is_py_map[key] = bool(is_py)
            for r, (k, _n, _e2, _api, _e) in enumerate(self.items):
                if k != key:
                    continue
                lvl, verdict = source_verdict(res)
                self._row_level[r] = lvl
                self._set(r, self.P_VERDICT, verdict, self._color(lvl))
                names = res.get("classes") or []
                self._set(r, self.P_CLASSES, str(len(names)) if res.get("ok") else "")
                self._set(r, self.P_TABS,
                          (" · ".join(names[:8]) + ("…" if len(names) > 8 else ""))
                          if names else "")
                self._set(r, self.P_VIDEOS, str(res.get("videos", 0)) if res.get("ok") else "")
                note = "" if lvl == "ok" else (res.get("error") or "分类为空，无标签栏")
                self._set(r, self.P_NOTE, note, self._color(lvl))
                break
            self._apply_filter()
            self._summary()
            self._show_detail()

        def _on_done(self):
            self._worker = None
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            # 进度条兜底拉满：停止/异常退出时也要停在 100%，不留「没跑完」的错觉
            # （部分测活时 max 是子集大小，用当前 max 而不是全部行数）
            try:
                self.prog.setValue(self.prog.maximum())
            except Exception:
                pass
            self._update_sel_btn()
            self._summary()

        def _summary(self):
            ok = bad = err = 0
            for r in self.results.values():
                lvl, _v = source_verdict(r)
                if lvl == "ok":
                    ok += 1
                elif lvl == "bad":
                    bad += 1
                elif lvl == "err":
                    err += 1
            self.lbl_sum.setText("活源 %d · 死源 %d · 异常 %d（共 %d）"
                                 % (ok, bad, err, len(self.items)))

        def _apply_filter(self):
            only_bad = False
            try:
                only_bad = bool(self.cb_bad.isChecked())
            except Exception:
                pass
            for r in range(self.table.rowCount()):
                lvl = self._row_level.get(r)
                hide = only_bad and not (lvl in ("bad", "err"))
                try:
                    self.table.setRowHidden(r, hide)
                except Exception:
                    pass

        def closeEvent(self, event):
            self._closed = True
            if self._worker is not None:
                self._worker.stop()
            try:
                super().closeEvent(event)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 工具箱：把新增的零 Qt 纯逻辑模块接到界面上
    #   · 分类识别    —— pyinj_kw.detect_categories（成人/短剧/直播/音乐/音频/点播）
    #   · JAR 体检    —— pyinj_jar（jar 型 spider 的远程 jar 健康度）
    #   · 源测速      —— pyinj_speed（延迟采样 + 前 N 字节真实下载）
    #   · 网络诊断    —— pyinj_netdiag（DNS / 超时-拒绝 / 代理域名库）
    #   · 直播表转换  —— pyinj_playlist（TXT ↔ M3U）
    #   · 诊断报告    —— pyinj_report（汇总导出 Markdown / CSV）
    # 只读检测，不改配置；用「页选择 + 显隐」实现分页（不引入 QTabWidget，
    # 便于沿用既有 Mock-Qt 测试的控件白名单）。
    # ------------------------------------------------------------------
    class _ToolRunWorker(QThread):
        """工具箱通用后台任务：把一项「逐条处理」的检测放到子线程里跑，
        逐条回传进度，避免界面卡死（用户反馈：检测中像程序死了）。

        job(i, entry) -> 该条结果（可为 None 表示跳过）；
        entry_name(entry) -> 进度条上显示的站点名。
        结果通过 finished_rows 整体回传（list），进度用 progress 回传。"""

        progress = Signal(int, int, str)   # 已完成, 总数, 当前条目名
        finished_rows = Signal(list)       # 结果行列表
        failed = Signal(str)               # 异常信息

        def __init__(self, dialog, items, job, name_of=None):
            super().__init__(dialog)
            self.dialog = dialog
            self.items = list(items or [])
            self.job = job
            self.name_of = name_of or (lambda e: "")
            self._stop = False

        def stop(self):
            self._stop = True

        def run(self):
            rows = []
            total = len(self.items)
            try:
                for i, e in enumerate(self.items):
                    if self._stop or getattr(self.dialog, "_closed", False):
                        break
                    try:
                        self.progress.emit(i, total, str(self.name_of(e)))
                    except Exception:
                        pass
                    try:
                        r = self.job(i, e)
                        if r is not None:
                            rows.append(r)
                    except Exception:
                        pass
            except Exception as ex:
                try:
                    self.failed.emit(str(ex))
                except Exception:
                    pass
                return
            self.finished_rows.emit(rows)

    class _ReportWorker(QThread):
        """诊断报告后台任务：跑 build_report 并回传逐条进度（报告最耗时，最需要反馈）。"""

        progress = Signal(int, int, str)   # done, total, name
        finished_report = Signal(dict)     # 报告数据结构
        failed = Signal(str)

        def __init__(self, dialog, entries, base_dir, repo_name,
                     do_speed, do_diag, do_jar):
            super().__init__(dialog)
            self.dialog = dialog
            self.entries = list(entries or [])
            self.base_dir = base_dir
            self.repo_name = repo_name
            self.do_speed = do_speed
            self.do_diag = do_diag
            self.do_jar = do_jar

        def run(self):
            try:
                rep = pyinj_report.build_report(
                    self.entries, self.base_dir, repo_name=self.repo_name,
                    do_speed=self.do_speed, do_diag=self.do_diag, do_jar=self.do_jar,
                    progress_cb=lambda i, t, n: self.progress.emit(i, t, str(n)),
                    stop_check=lambda: (getattr(self.dialog, "_closed", False)))
            except Exception as ex:
                self.failed.emit(str(ex))
                return
            self.finished_report.emit(rep)

    class _ToolboxDialog(QDialog):
        def __init__(self, parent, entries, base_dir, repo_dir):
            super().__init__(parent)
            self.entries = [dict(e) for e in (entries or [])]
            self.base_dir = base_dir
            self.repo_dir = repo_dir
            self.title = "🧰 工具箱"
            self.setWindowTitle(tagged_title(self.title))
            self.resize(900, 600)
            self._busy = False
            self._worker = None
            self._closed = False
            self._run_worker = None       # 当前正在跑的工具任务（通用 worker）
            self._page_bars = {}          # 页名 -> (进度条, 状态标签)，各页独立视觉反馈
            self._tool_buttons = []       # 各页「开始」按钮（检测中统一禁用）

            root = QVBoxLayout(self)
            tip = QLabel(
                "把「分类识别 / JAR 体检 / 源测速 / 网络诊断 / 直播表转换 / 诊断报告」"
                "集中在这里。全部为<b>只读检测</b>，不改动你的配置。")
            tip.setTextFormat(Qt.RichText)
            tip.setWordWrap(True)
            root.addWidget(tip)

            top = QHBoxLayout()
            top.addWidget(QLabel("功能："))
            self.page = QComboBox()
            self.page.addItems([
                "分类识别", "JAR 体检", "源测速", "网络诊断",
                "直播表转换（TXT ↔ M3U）", "诊断报告导出",
            ])
            self.page.currentIndexChanged.connect(self._switch_page)
            top.addWidget(self.page, 1)
            root.addLayout(top)

            # 各功能页容器（QWidget + 显隐切换）
            self.pages = {}
            for name in ("cat", "jar", "speed", "net", "plist", "report"):
                w = QWidget()
                self.pages[name] = w
                root.addWidget(w, 1)
            self._build_cat(self.pages["cat"])
            self._build_jar(self.pages["jar"])
            self._build_speed(self.pages["speed"])
            self._build_net(self.pages["net"])
            self._build_plist(self.pages["plist"])
            self._build_report(self.pages["report"])

            self.lbl_status = QLabel("")
            self.lbl_status.setWordWrap(True)
            root.addWidget(self.lbl_status)

            hb = QHBoxLayout()
            hb.addStretch(1)
            hb.addWidget(QPushButton("关闭", clicked=self.close))
            root.addLayout(hb)
            self._switch_page(0)

        # ---- 通用：结果表 ----
        def _mk_table(self, headers, parent_layout):
            t = QTableWidget(0, len(headers))
            t.setHorizontalHeaderLabels(headers)
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.setSelectionBehavior(QAbstractItemView.SelectRows)
            parent_layout.addWidget(t, 1)
            return t

        def _status(self, msg):
            self.lbl_status.setText(msg)

        # ---- 每页独立的进度视觉反馈（进度条 + 状态文字），避免检测中像卡死 ----
        def _mk_progress(self, parent_layout, page_key):
            """在当前页加一条「进度条 + 状态文字」，并登记到 _page_bars。
            所有检测都通过 _set_progress / _run_tool 更新它，给出明确反馈。"""
            row = QHBoxLayout()
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFormat("就绪")
            bar.setMinimumWidth(220)
            lbl = QLabel("点上方按钮开始…")
            lbl.setWordWrap(True)
            row.addWidget(bar, 2)
            row.addWidget(lbl, 3)
            parent_layout.addLayout(row)
            self._page_bars[page_key] = (bar, lbl)
            return bar, lbl

        def _set_progress(self, page_key, done, total, name="", fmt=""):
            """更新某页进度条（done/total）与状态文字；total<=0 时置为不确定态。"""
            pair = self._page_bars.get(page_key)
            if not pair:
                return
            bar, lbl = pair
            try:
                if total and total > 0:
                    bar.setRange(0, total)
                    bar.setValue(done)
                    bar.setFormat(fmt or "%d / %d" % (done, total))
                else:
                    bar.setRange(0, 0)          # 不确定进度（来回滚动）
                    bar.setFormat(fmt or "处理中…")
                lbl.setText(("正在处理：%s（第 %d / %d）" % (name, done, total))
                            if name else (fmt or "处理中…"))
            except Exception:
                pass

        def _progress_start(self, page_key, total, fmt=""):
            self._set_progress(page_key, 0, total, "", fmt or "0 / %d" % total)

        def _progress_done(self, page_key, text, fmt="完成"):
            pair = self._page_bars.get(page_key)
            if not pair:
                return
            bar, lbl = pair
            try:
                bar.setRange(0, 100)
                bar.setValue(100)
                bar.setFormat(fmt)
            except Exception:
                pass
            self._status(text)

        def _progress_fail(self, page_key, text):
            pair = self._page_bars.get(page_key)
            if pair:
                bar, lbl = pair
                try:
                    bar.setRange(0, 100)
                    bar.setValue(0)
                    bar.setFormat("失败")
                except Exception:
                    pass
            self._status(text)

        def _run_tool(self, page_key, items, job, name_of, on_done, fmt="0 / %d",
                      raw_fmt=False):
            """通用：在后台线程跑一项逐条检测，带进度反馈；完成后回调 on_done(rows)。

            fmt 默认是带一个 %d 的格式串（用于「已完成 / 总数」）；
            raw_fmt=True 时 fmt 为纯文字（不参与格式化，如「转换中…」）。
            同一时刻只允许一个工具任务；运行中禁用所有「开始」按钮。"""
            if self._run_worker is not None:
                QMessageBox.information(self, "提示", "已有检测在进行中，请稍候…")
                return
            items = list(items or [])
            if not items:
                self._progress_fail(page_key, "没有可处理的条目。")
                QMessageBox.information(self, "提示", "当前没有可处理的条目。")
                return
            self._set_tool_buttons(False)
            label = fmt if raw_fmt else (fmt % len(items))
            self._progress_start(page_key, len(items), label)

            def _name(e):
                try:
                    return str(e.get("name") or e.get("key") or "")
                except Exception:
                    return ""

            w = _ToolRunWorker(self, items, job, name_of or _name)
            self._run_worker = w

            def _on_prog(done, total, nm):
                self._set_progress(page_key, done, total, nm)

            def _on_rows(rows):
                try:
                    on_done(rows)
                except Exception as ex:
                    self._progress_fail(page_key, "处理结果失败：%s" % ex)
                finally:
                    self._finish_tool()

            def _on_fail(msg):
                self._progress_fail(page_key, "检测异常：%s" % msg)
                self._finish_tool()

            w.progress.connect(_on_prog)
            w.finished_rows.connect(_on_rows)
            w.failed.connect(_on_fail)
            w.finished.connect(w.deleteLater)
            w.start()

        def _finish_tool(self):
            self._run_worker = None
            self._set_tool_buttons(True)

        def _set_tool_buttons(self, enabled):
            """检测进行中禁用各页「开始」按钮（防重复触发）。"""
            for b in getattr(self, "_tool_buttons", []):
                try:
                    b.setEnabled(enabled)
                except Exception:
                    pass

        def _switch_page(self, idx):
            names = ["cat", "jar", "speed", "net", "plist", "report"]
            for i, n in enumerate(names):
                self.pages[n].setVisible(i == idx)

        # ---- 分类识别页 ----
        def _build_cat(self, page):
            v = QVBoxLayout(page)
            h = QHBoxLayout()
            h.addWidget(QLabel("按站点名 + .py 内容，用「敏感词库.txt」判定分类标签。"))
            h.addStretch(1)
            b = QPushButton("▶ 开始识别", clicked=self._run_cat)
            self._tool_buttons.append(b)
            h.addWidget(b)
            v.addLayout(h)
            self._mk_progress(v, "cat")
            self.t_cat = self._mk_table(
                ["站点", "类型", "命中分类", "命中词"], v)

        def _run_cat(self):
            try:
                kws = pyinj_kw.load_keywords()
            except Exception as ex:
                QMessageBox.warning(self, "词库", "词库加载失败：%s" % ex)
                return

            def job(_i, e):
                name = str(e.get("name") or "")
                text = ""
                api = str(e.get("api") or "")
                if self.base_dir and api:
                    try:
                        p = resolve_spider_path(self.base_dir, api)
                        if p and os.path.isfile(p):
                            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                    except Exception:
                        text = ""
                cats = pyinj_kw.detect_categories(text, name, kws)
                if not cats:
                    return None
                labels = "·".join(pyinj_kw.CAT_LABELS.get(c, c)
                                 for c in pyinj_kw._CAT_ORDER if c in cats)
                words = "、".join("%s:%s" % (pyinj_kw.CAT_LABELS.get(c, c), w)
                                  for c, w in cats.items())
                return (name, str(source_type_of(e)), labels, words)

            def done(rows):
                self._fill_table(self.t_cat, rows)
                self._progress_done(
                    "cat", "分类识别完成：命中 %d / 共 %d 个站点。"
                    % (len(rows), len(self.entries)))

            self._run_tool("cat", self.entries, job, None, done, fmt="0 / %d")

        # ---- JAR 体检页 ----
        def _build_jar(self, page):
            v = QVBoxLayout(page)
            h = QHBoxLayout()
            h.addWidget(QLabel("体检 jar 型 spider 源（api 为类名 + jar 字段指向远程 jar）。"))
            h.addStretch(1)
            self.b_jar = QPushButton("▶ 开始体检", clicked=self._run_jar)
            self._tool_buttons.append(self.b_jar)
            h.addWidget(self.b_jar)
            v.addLayout(h)
            # MD5 校验（可选）：留空=只体检；填写期望 MD5=整包下载比对（jar 可能被替换/篡改）
            mh = QHBoxLayout()
            mh.addWidget(QLabel("期望 MD5（可选，填了才做整包校验）："))
            self.ent_jar_md5 = QLineEdit()
            self.ent_jar_md5.setPlaceholderText(
                "留空 = 只体检可达性/大小；填 32 位 MD5 = 额外下载整包比对")
            mh.addWidget(self.ent_jar_md5, 1)
            v.addLayout(mh)
            self._mk_progress(v, "jar")
            self.t_jar = self._mk_table(
                ["站点", "jar 判定", "状态码", "内容大小", "MD5", "备注", "jar URL"], v)

        def _run_jar(self):
            pairs = pyinj_jar.iter_jar_entries(self.entries)
            if not pairs:
                self._status("当前配置里没有 jar 型 spider 源。")
                QMessageBox.information(self, "JAR 体检", "当前配置里没有 jar 型源。")
                return
            expect = self.ent_jar_md5.text().strip() or None
            entries = [e for e, _u in pairs]

            def job(_i, e):
                r = pyinj_jar.check_jar_source(e, expect_md5=expect)
                mi = r.get("md5_info") or {}
                md5_cell = mi.get("label", "-") if expect else "-"
                if mi.get("level") == pyinj_jar.MD5_MISMATCH:
                    md5_cell = "不一致 ⚠"
                elif mi.get("level") == pyinj_jar.MD5_OK:
                    md5_cell = "一致 ✓"
                return (r.get("name") or r.get("key"), r.get("label", ""),
                        str(r.get("status") if r.get("status") is not None else "-"),
                        str(r.get("content_length") if r.get("content_length", -1) > 0
                            else r.get("bytes", 0)),
                        md5_cell,
                        r.get("note", ""), r.get("url", "")[:70])

            def done(rows):
                self._fill_table(self.t_jar, rows)
                ok = sum(1 for r in rows if r[1] == "健康")
                msg = "JAR 体检完成：共 %d 个，健康 %d 个。" % (len(rows), ok)
                if expect:
                    mism = sum(1 for r in rows if r[4].startswith("不一致"))
                    msg += " MD5 不一致 %d 个。" % mism
                self._progress_done("jar", msg)

            self._run_tool("jar", entries, job, None, done, fmt="0 / %d")

        # ---- 源测速页 ----
        def _build_speed(self, page):
            v = QVBoxLayout(page)
            h = QHBoxLayout()
            h.addWidget(QLabel("多次采样取延迟（截尾加权均值防误杀）+ 前 1KB 真实下载判活。"))
            h.addStretch(1)
            b = QPushButton("▶ 开始测速", clicked=self._run_speed)
            self._tool_buttons.append(b)
            h.addWidget(b)
            v.addLayout(h)
            self._mk_progress(v, "speed")
            self.t_speed = self._mk_table(
                ["站点", "可达", "质量", "延迟ms", "方式", "状态码", "备注"], v)

        def _run_speed(self):
            targets = []
            for e in self.entries:
                api = str(e.get("api") or "")
                t = source_type_of(e)
                if t not in (1, 3) and not api.startswith("http"):
                    continue
                targets.append(e)

            def job(_i, e):
                try:
                    r = pyinj_speed.speed_test_source(e, self.base_dir, max_urls=2)
                except Exception:
                    return None
                best = r.get("best") or {}
                reach = ("是" if r.get("reachable") is True
                         else ("否" if r.get("reachable") is False else "—"))
                return (str(e.get("name") or e.get("key")),
                        reach, best.get("quality", ""),
                        str(best.get("latency_ms") if best.get("latency_ms") is not None else ""),
                        best.get("method", ""),
                        str(best.get("status") if best.get("status") is not None else ""),
                        r.get("note", ""))

            def done(rows):
                self._fill_table(self.t_speed, rows)
                okn = sum(1 for r in rows if r[1] == "是")
                self._progress_done(
                    "speed", "测速完成：共 %d 个源，可达 %d 个。" % (len(rows), okn))

            self._run_tool("speed", targets, job, None, done, fmt="0 / %d")

        # ---- 网络诊断页 ----
        def _build_net(self, page):
            v = QVBoxLayout(page)
            h = QHBoxLayout()
            h.addWidget(QLabel("DNS 解析 / 连接超时 vs 拒绝 / 命中「需特殊上网域名库」。"))
            h.addStretch(1)
            b = QPushButton("▶ 开始诊断", clicked=self._run_net)
            self._tool_buttons.append(b)
            h.addWidget(b)
            v.addLayout(h)
            self._mk_progress(v, "net")
            self.t_net = self._mk_table(
                ["站点", "结论", "需代理", "域名", "IP", "耗时ms", "备注"], v)

        def _run_net(self):
            targets = []
            for e in self.entries:
                api = str(e.get("api") or "")
                if not api:
                    continue
                t = source_type_of(e)
                if t not in (0, 1, 3, 4) and not api.startswith("http"):
                    continue
                targets.append(e)

            def job(_i, e):
                try:
                    r = pyinj_netdiag.diagnose_source(e, self.base_dir, max_urls=2)
                except Exception:
                    return None
                first = (r.get("results") or [{}])[0]
                return (str(e.get("name") or e.get("key")),
                        r.get("label", ""),
                        "是" if r.get("needs_proxy") else "",
                        first.get("host", ""), first.get("ip", ""),
                        str(first.get("latency_ms") if first.get("latency_ms") is not None else ""),
                        r.get("note", ""))

            def done(rows):
                self._fill_table(self.t_net, rows)
                px = sum(1 for r in rows if r[2] == "是")
                self._progress_done(
                    "net", "网络诊断完成：共 %d 个源，疑似需特殊上网 %d 个。" % (len(rows), px))

            self._run_tool("net", targets, job, None, done, fmt="0 / %d")

        # ---- 直播表转换页 ----
        def _build_plist(self, page):
            v = QVBoxLayout(page)
            info = QLabel("在 TXT（TVBox 频道表）与 M3U 之间互转。点「选择文件」后自动识别 "
                          "源格式并输出到同目录（.m3u ↔ .txt）。")
            info.setWordWrap(True)
            v.addWidget(info)
            h = QHBoxLayout()
            b = QPushButton("📂 选择文件…并转换", clicked=self._run_plist)
            self._tool_buttons.append(b)
            h.addWidget(b)
            h.addStretch(1)
            v.addLayout(h)
            self._mk_progress(v, "plist")
            self.t_plist = self._mk_table(["文件", "源格式", "目标格式", "条目数", "输出"], v)

        def _run_plist(self):
            if self._run_worker is not None:
                QMessageBox.information(self, "提示", "已有检测在进行中，请稍候…")
                return
            path, _ = QFileDialog.getOpenFileName(
                self, "选择直播源列表", "",
                "播放列表 (*.txt *.m3u *.m3u8);;所有文件 (*.*)")
            if not path:
                return
            # 单文件转换：用「不确定进度」立即给出反馈，转换在后台完成
            self._set_tool_buttons(False)
            self._progress_start("plist", 0, "转换中…")

            def job(_i, p):
                try:
                    return pyinj_playlist.convert_file(p)
                except Exception as ex:
                    return {"__err__": str(ex)}

            def done(rows):
                if not rows:
                    self._progress_fail("plist", "转换未产生结果。")
                    return
                r = rows[0]
                if "__err__" in r:
                    self._progress_fail("plist", "转换失败：%s" % r["__err__"])
                    QMessageBox.critical(self, "错误", "转换失败：%s" % r["__err__"])
                    return
                self._fill_table(self.t_plist, [(
                    os.path.basename(r["src"]), r["src_fmt"], r["fmt"],
                    str(r["count"]), r["dst"])])
                self._progress_done(
                    "plist", "已转换：%s → %s（%d 条）" % (r["src_fmt"], r["fmt"], r["count"]))

            self._run_tool("plist", [path], job, None, done, fmt="转换中…", raw_fmt=True)

        # ---- 诊断报告导出页 ----
        def _build_report(self, page):
            v = QVBoxLayout(page)
            info = QLabel("对全部源跑一遍「分类 / 测速 / 网络诊断 / JAR 体检」，汇总成报告。"
                          "报告只读，导出为 Markdown（.md）或 CSV（.csv）。")
            info.setWordWrap(True)
            v.addWidget(info)
            h = QHBoxLayout()
            self.cb_report_speed = QCheckBox("含测速")
            self.cb_report_speed.setChecked(True)
            self.cb_report_diag = QCheckBox("含网络诊断")
            self.cb_report_diag.setChecked(True)
            self.cb_report_jar = QCheckBox("含 JAR 体检")
            self.cb_report_jar.setChecked(True)
            h.addWidget(self.cb_report_speed)
            h.addWidget(self.cb_report_diag)
            h.addWidget(self.cb_report_jar)
            h.addStretch(1)
            b = QPushButton("▶ 生成并导出…", clicked=self._run_report)
            self._tool_buttons.append(b)
            h.addWidget(b)
            v.addLayout(h)
            self._mk_progress(v, "report")
            self.t_report = self._mk_table(["站点", "分类", "可达", "网络诊断", "JAR"], v)

        def _run_report(self):
            if self._run_worker is not None:
                QMessageBox.information(self, "提示", "已有检测在进行中，请稍候…")
                return
            if not self.entries:
                self._progress_fail("report", "没有可处理的条目。")
                QMessageBox.information(self, "提示", "当前没有可处理的条目。")
                return
            do_speed = self.cb_report_speed.isChecked()
            do_diag = self.cb_report_diag.isChecked()
            do_jar = self.cb_report_jar.isChecked()
            self._set_tool_buttons(False)
            self._progress_start("report", len(self.entries), "0 / %d" % len(self.entries))
            w = _ReportWorker(self, self.entries, self.base_dir,
                              os.path.basename(os.path.abspath(self.repo_dir or ".")),
                              do_speed, do_diag, do_jar)
            self._run_worker = w

            def _on_prog(done, total, nm):
                self._set_progress("report", done, total, nm)

            def _on_rep(rep):
                try:
                    self._render_report(rep)
                except Exception as ex:
                    self._progress_fail("report", "生成报告失败：%s" % ex)
                finally:
                    self._finish_tool()

            def _on_fail(msg):
                self._progress_fail("report", "生成报告失败：%s" % msg)
                QMessageBox.critical(self, "错误", "生成报告失败：%s" % msg)
                self._finish_tool()

            w.progress.connect(_on_prog)
            w.finished_report.connect(_on_rep)
            w.failed.connect(_on_fail)
            w.finished.connect(w.deleteLater)
            w.start()

        def _render_report(self, rep):
            rows = []
            for r in rep["records"]:
                sp = r.get("speed") or {}
                dg = r.get("diag") or {}
                jr = r.get("jar") or {}
                reach = ("是" if sp.get("reachable") is True
                         else ("否" if sp.get("reachable") is False else ""))
                rows.append((r.get("name", ""), r.get("cat_labels", ""),
                             reach, dg.get("label", ""), (jr.get("label") if jr else "")))
            self._fill_table(self.t_report, rows)
            self._progress_done("report", "报告已生成：共 %d 个站点。" % rep["total"])
            path, _f = QFileDialog.getSaveFileName(
                self, "导出诊断报告", "源诊断报告.md",
                "Markdown (*.md);;CSV (*.csv)")
            if not path:
                self._status("报告已生成（未导出）：共 %d 个站点。" % rep["total"])
                return
            try:
                pyinj_report.export_report(path, rep)
            except Exception as ex:
                QMessageBox.critical(self, "错误", "导出失败：%s" % ex)
                return
            self._status("报告已导出：%s（共 %d 个站点）" % (path, rep["total"]))
            QMessageBox.information(self, "完成", "诊断报告已导出：\n%s" % path)

        # ---- 通用填表 ----
        def _fill_table(self, table, rows):
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    table.setItem(r, c, QTableWidgetItem(str(val)))
            try:
                table.resizeColumnsToContents()
            except Exception:
                pass

        def closeEvent(self, event):
            self._closed = True
            try:
                if self._worker is not None:
                    self._worker.stop()
            except Exception:
                pass
            try:
                if self._run_worker is not None:
                    self._run_worker.stop()
            except Exception:
                pass
            try:
                super().closeEvent(event)
            except Exception:
                pass

    app = QApplication(sys.argv)
    # 全局字体与主题（跟随系统深浅色；测试环境下此段被截取、不影响 mock）
    global IS_DARK
    try:
        IS_DARK = _system_is_dark()
    except Exception:
        IS_DARK = False
    try:
        app.setFont(QFont("Microsoft YaHei UI", 9))
        app.setStyleSheet(APP_QSS_DARK if IS_DARK else APP_QSS)
        if IS_DARK:
            _apply_dark_palette(app)
    except Exception:
        pass
    w = App()
    app.installEventFilter(w)   # 全局标题标注兜底（App.eventFilter → _tag_window_title）
    w.show()
    sys.exit(_app_exec(app))

    # ---- main ----


def main():
    # CLI 输出先切 UTF-8（应用名/日志含中文与符号，GBK 控制台会乱码甚至崩）
    try:
        _ensure_utf8_stdio()
    except Exception:
        pass
    # 源测活的子进程入口（frozen exe 里由 pyinj_core 启动自己，带该标志）
    if PROBE_WORKER_FLAG in sys.argv[1:]:
        probe_worker_main()
        return
    # 传入任何 CLI 参数（含 --inject/--scan/--help 等）走命令行模式，否则图形界面
    if "--version" in sys.argv[1:]:
        print("源管家 v%s" % APP_VERSION)
        return
    cli_flags = {"--inject", "--scan", "--repo", "--write", "--no-copy", "--type",
                 "--no-filter", "--no-quick", "--no-search", "--list", "--check",
                 "--dedup", "--adult-scan", "--duanju-scan", "--live-scan", "--check-url",
                 "--probe", "--disable", "--enable",
                 "--del", "--keep-py", "--set", "--config", "-h", "--help"}
    if any(a in cli_flags for a in sys.argv[1:]):
        sys.exit(run_cli(sys.argv[1:]))
    run_gui()


if __name__ == "__main__":
    main()
