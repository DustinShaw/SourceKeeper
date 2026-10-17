# -*- coding: utf-8 -*-
"""上传到电视 / 盒子：ADB 传输层（纯标准库、零 Qt、零第三方依赖）。

设计要点（与「源管家」既有分层一致，可单测）：
  · **上传单位是「清单」**：不写死 py.json / py/ ——
      - 仓库目录：递归扫描整个 repo_dir，按排除规则过滤；
      - 自定义：用户任选的文件 / 文件夹（即便不用源管家改配置也能传别的配置）；
  · 排除规则用 glob（`DEFAULT_EXCLUDES`），默认排掉构建产物、备份、版本库与内部记录；
  · 远端路径 = 基础目录 + 相对路径（默认 /sdcard/，可自定义），统一用 `/`；
  · ADB 命令一律走参数列表（不拼 shell 字符串）；只在 `adb shell` 的**远端路径**上
    做单引号转义（中文 / 空格 / 单引号都能过）；
  · 每个文件「先 `rm -f` 再 push」——远端只读属性会挡住覆盖，与本地删只读 .py 同源；
  · 传完用 `md5sum` 核对，不一致自动重试一次；
  · 单文件失败不中断整批，最后汇总「成功 / 跳过 / 失败」。

对外主要接口：
    find_adb(explicit="")                  -> adb.exe 路径（找不到返回 ""）
    scan_repo(root, excludes=None)         -> 仓库清单
    scan_tree(root, excludes, prefix, src) -> 任意目录清单
    build_plan(items, base_remote)         -> [{"local","rel","remote","size"}]
    upload_plan(adb, plan, ...)            -> 结果行列表
    parse_devices / pick_device / parse_md5sum / norm_remote / shq / md5_file
"""
import fnmatch
import hashlib
import os
import posixpath
import re
import shutil
import subprocess

# ---- 默认排除：目录名、路径前缀或通配符 ----
DEFAULT_EXCLUDES = (
    # 目录（任何层级同名都排）
    ".git", ".svn", ".hg", ".workbuddy", ".idea", ".vscode",
    "__pycache__", "backups", "py_trash", "dist", "build", "node_modules",
    # 通配符
    "*.pyc", "*.pyo", "*.pyd", "*.log", "*.tmp", "*.bak", "*.bak.*",
    "*.exe", "*.msi", "*.zip", ".DS_Store", "Thumbs.db",
)

# 一次最多扫多少个文件（防用户误选 C:\ 之类）
MAX_SCAN_FILES = 20000

# adb 单条命令默认超时（秒）；push 大文件另有更长超时
CMD_TIMEOUT = 60
PUSH_TIMEOUT = 600


# ---------------------------------------------------------------- 基础工具

def _posix(s):
    return str(s or "").replace("\\", "/")


def _collapse(path):
    """折叠重复斜杠、去掉尾部斜杠（保留根 `/`）。"""
    p = re.sub(r"/{2,}", "/", _posix(path).strip())
    if not p:
        return "/"
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1:
        p = p.rstrip("/")
    return p or "/"


def norm_remote(base, rel=""):
    """把「基础目录 + 相对路径」拼成规范远端路径。

    · rel 以 `/` 开头 → 视为**绝对远端路径**（用户显式指定，直接覆盖基础目录）；
    · base 为空 → 默认 `/sdcard`；
    · 统一 `/` 分隔、折叠重复斜杠、去尾部斜杠。
    """
    r = _posix(rel).strip()
    if r.startswith("/"):
        return _collapse(r)
    b = _posix(base).strip() or "/sdcard"
    b = _collapse(b)
    r = r.strip("/")
    if not r:
        return b
    return _collapse(b.rstrip("/") + "/" + r)


def remote_dir(remote):
    d = posixpath.dirname(_collapse(remote))
    return d or "/"


def shq(s):
    """POSIX shell 单引号转义：'a b' → 'a b'，a'b → 'a'\\''b'。"""
    return "'" + str(s).replace("'", "'\\''") + "'"


def md5_file(path, chunk=1024 * 1024):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def format_size(n):
    try:
        n = float(n or 0)
    except Exception:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return ""


# ---------------------------------------------------------------- 扫描 / 清单

def should_exclude(rel, excludes=None):
    """按排除规则判断某个相对路径是否要跳过。

    规则串三种形态：
      · 纯名字（`backups`）→ 任一路径段匹配即排除；
      · 含 `/`（`py/old`）→ 按路径前缀匹配；
      · 含通配符（`*.exe`、`*.bak.*`）→ 对路径段与整条相对路径各做一次 fnmatch。
    """
    ex = DEFAULT_EXCLUDES if excludes is None else excludes
    r = _posix(rel).strip("/")
    if not r:
        return False
    parts = [p for p in r.split("/") if p]
    for raw in ex:
        p = _posix(raw).strip()
        if not p:
            continue
        p = p.strip("/")
        if not p:
            continue
        if "/" in p:
            if r == p or r.startswith(p + "/") or fnmatch.fnmatch(r, p):
                return True
            continue
        for seg in parts:
            if fnmatch.fnmatch(seg, p):
                return True
    return False


def scan_tree(root, excludes=None, prefix="", src="repo", max_files=MAX_SCAN_FILES):
    """递归扫描目录，返回清单：[{local, rel, size, src}, …]（按 rel 排序）。

    prefix 用于自定义文件夹：扫描 D:\\x 时 prefix="x"，远端据此保留文件夹名。
    符号链接不跟随（防环），扫描文件数有上限。
    """
    root = os.path.abspath(root or "")
    if not os.path.isdir(root):
        return []
    out = []
    prefix = _posix(prefix).strip("/")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir in (".", "") else _posix(rel_dir)
        # 目录名直接剪枝（不进入被排除目录，省时间）
        keep = []
        for d in dirnames:
            child = (rel_dir + "/" + d) if rel_dir else d
            if not should_exclude(child, excludes):
                keep.append(d)
        dirnames[:] = sorted(keep)
        for fn in sorted(filenames):
            rel = (rel_dir + "/" + fn) if rel_dir else fn
            if should_exclude(rel, excludes):
                continue
            if prefix:
                rel = prefix + "/" + rel
            local = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(local)
            except OSError:
                size = 0
            out.append({"local": local, "rel": _posix(rel), "size": size, "src": src})
            if len(out) >= max_files:
                return sorted(out, key=lambda x: x["rel"])
    return sorted(out, key=lambda x: x["rel"])


def scan_repo(root, excludes=None):
    """扫描「源管家仓库目录」——整个目录，不写死具体文件名。"""
    return scan_tree(root, excludes=excludes, prefix="", src="repo")


def custom_file(path):
    """把一个任选文件包成清单条目（rel = 文件名）。"""
    p = os.path.abspath(path or "")
    if not os.path.isfile(p):
        return None
    try:
        size = os.path.getsize(p)
    except OSError:
        size = 0
    return {"local": p, "rel": os.path.basename(p), "size": size, "src": "custom"}


def custom_dir(path, excludes=None):
    """把一个任选文件夹包成清单条目（远端保留文件夹名）。"""
    p = os.path.abspath(path or "")
    if not os.path.isdir(p):
        return []
    return scan_tree(p, excludes=excludes,
                     prefix=os.path.basename(p.rstrip("\\/")) or "dir", src="custom")


def build_plan(items, base_remote="/sdcard/"):
    """清单 → 传输计划：补上远端路径与大小，并去掉重复项（按 local 去重）。"""
    plan, seen = [], set()
    for it in (items or []):
        local = os.path.abspath(str(it.get("local") or ""))
        if local in seen or not local:
            continue
        seen.add(local)
        rel = _posix(it.get("rel") or os.path.basename(local)).strip("/")
        remote = str(it.get("remote") or "").strip() or norm_remote(base_remote, rel)
        try:
            size = os.path.getsize(local)
        except OSError:
            size = int(it.get("size") or 0)
        plan.append({"local": local, "rel": rel, "remote": _collapse(remote), "size": size})
    return plan


# ---------------------------------------------------------------- adb 定位 / 输出解析

def find_adb(explicit=""):
    """定位 adb.exe：显式指定 → 程序同目录 → platform-tools → PATH → Android SDK 默认位置。"""
    cand = []
    if explicit:
        cand.append(str(explicit).strip().strip('"'))
    here = None
    try:
        import sys
        here = os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys, "frozen", False) else __file__))
    except Exception:
        here = os.getcwd()
    if here:
        cand += [os.path.join(here, "adb.exe"),
                 os.path.join(here, "platform-tools", "adb.exe"),
                 os.path.join(here, "adb", "adb.exe")]
    w = shutil.which("adb")
    if w:
        cand.append(w)
    for env in ("LOCALAPPDATA", "USERPROFILE", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if not base:
            continue
        cand.append(os.path.join(base, "Android", "Sdk", "platform-tools", "adb.exe"))
        cand.append(os.path.join(base, "platform-tools", "adb.exe"))
    for p in cand:
        try:
            if p and os.path.isfile(p):
                return os.path.abspath(p)
        except Exception:
            continue
    return ""


def parse_devices(text):
    """解析 `adb devices -l` 输出 → [{serial, state, extra}, …]。"""
    out = []
    for line in str(text or "").replace("\r", "").splitlines():
        s = line.strip()
        if not s or s.lower().startswith("list of devices") or s.startswith("*"):
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        if state not in ("device", "offline", "unauthorized", "authorizing",
                         "bootloader", "recovery", "sideload"):
            continue
        out.append({"serial": serial, "state": state, "extra": " ".join(parts[2:])})
    return out


def pick_device(devices, prefer=""):
    """挑一个可用设备：优先串号等于 prefer，其次第一个 state=device。"""
    devs = list(devices or [])
    if prefer:
        for d in devs:
            if d.get("serial") == prefer and d.get("state") == "device":
                return d
    for d in devs:
        if d.get("state") == "device":
            return d
    return None


def describe_device(dev):
    """从 `adb devices -l` 的额外字段里取型号，用于界面显示。"""
    extra = str((dev or {}).get("extra") or "")
    m = re.search(r"model:(\S+)", extra)
    if m:
        return m.group(1).replace("_", " ")
    return str((dev or {}).get("serial") or "")


def parse_md5sum(text):
    """从 `md5sum <file>` 输出里取 32 位小写 md5（取不到返回 ""）。"""
    m = re.search(r"\b([0-9a-fA-F]{32})\b", str(text or ""))
    return m.group(1).lower() if m else ""


def explain_adb_error(text):
    """把 adb 的英文报错翻成能直接照做的中文提示。"""
    s = str(text or "")
    low = s.lower()
    if "unauthorized" in low:
        return "设备未授权：请在电视/盒子上点「允许 USB 调试」后重试"
    if "offline" in low:
        return "设备离线：可试 `adb disconnect` 后重连，或重启盒子上的调试开关"
    if "no devices" in low or "device not found" in low or "not found" in low:
        return "没有可用设备：确认地址/端口（默认 5555）与盒子已开「网络调试」"
    if "failed to connect" in low or "cannot connect" in low or "connection refused" in low:
        return "连接失败：地址或端口不对，或盒子的 ADB 调试没打开"
    if "permission denied" in low:
        return "没有写权限：换到 /sdcard/ 下的目录（如 /sdcard/Download/）"
    if "read-only file system" in low:
        return "远端是只读文件系统：不能写 /system 等分区，请改到 /sdcard/"
    if "no such file" in low or "does not exist" in low:
        return "远端目录不存在且创建失败：请检查路径拼写"
    if "more than one device" in low:
        return "连接了多台设备：请只保留一台，或在界面里选定设备后再传"
    return s.strip().replace("\r", " ")[:160] or "adb 执行失败"


# ---------------------------------------------------------------- ADB 封装

class Adb(object):
    """adb 命令封装。所有命令走参数列表，Windows 下不弹黑框。"""

    def __init__(self, adb_path, serial="", timeout=CMD_TIMEOUT):
        self.adb_path = str(adb_path or "")
        self.serial = str(serial or "")
        self.timeout = int(timeout or CMD_TIMEOUT)

    # -- 底层 --
    def _run(self, args, timeout=None):
        if not self.adb_path or not os.path.isfile(self.adb_path):
            return {"rc": -1, "out": "", "err": "找不到 adb.exe：%s" % (self.adb_path or "(空)")}
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += [str(a) for a in args]
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, timeout=timeout or self.timeout, **kw)
        except subprocess.TimeoutExpired:
            return {"rc": -1, "out": "", "err": "命令超时（%ds）：adb %s"
                    % (timeout or self.timeout, " ".join(str(a) for a in args))}
        except FileNotFoundError:
            return {"rc": -1, "out": "", "err": "找不到 adb.exe：%s" % self.adb_path}
        except OSError as ex:
            return {"rc": -1, "out": "", "err": "无法执行 adb：%s" % ex}
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        return {"rc": p.returncode, "out": out, "err": err, "ok": p.returncode == 0,
                "cmd": " ".join(cmd)}

    # -- 连接 / 设备 --
    def version(self):
        r = self._run(["version"], timeout=15)
        text = (r.get("out") or "") + (r.get("err") or "")
        r["ok"] = bool(r.get("ok")) and "Android Debug Bridge" in text
        if r["ok"]:
            m = re.search(r"version\s+([0-9][0-9.]*)", text)
            r["version"] = m.group(1) if m else ""
        return r

    def connect(self, addr):
        """`adb connect host:port`。注意 adb 即使失败也常返回 0，必须看输出。"""
        r = self._run(["connect", str(addr)], timeout=30)
        text = ((r.get("out") or "") + "\n" + (r.get("err") or "")).strip()
        low = text.lower()
        r["text"] = text
        if "connected to" in low or "already connected" in low:
            r["ok"] = True
            r["msg"] = "已连接 %s" % addr
        else:
            r["ok"] = False
            r["msg"] = explain_adb_error(text)
        return r

    def disconnect(self, addr=""):
        return self._run(["disconnect"] + ([str(addr)] if addr else []), timeout=20)

    def devices(self):
        r = self._run(["devices", "-l"], timeout=25)
        r["devices"] = parse_devices((r.get("out") or "") + "\n" + (r.get("err") or ""))
        return r

    # -- shell --
    def shell(self, cmd, timeout=None):
        return self._run(["shell", str(cmd)], timeout=timeout)

    def mkdir_p(self, remote):
        return self.shell("mkdir -p %s" % shq(_collapse(remote)))

    def rm(self, remote):
        return self.shell("rm -f %s" % shq(_collapse(remote)))

    def md5(self, remote):
        r = self.shell("md5sum %s" % shq(_collapse(remote)))
        return parse_md5sum(r.get("out") or "")

    def test_dir(self, remote):
        r = self.shell("test -d %s && echo __YES__" % shq(_collapse(remote)))
        return "__YES__" in (r.get("out") or "")

    def test_writable(self, remote):
        """建目录 → 写探针 → 删除。三者都成功才算可写（比只看「连上了」可靠）。"""
        d = _collapse(remote)
        r = self.mkdir_p(d)
        if not r.get("ok"):
            return {"ok": False, "msg": "无法创建目录：%s"
                    % explain_adb_error((r.get("err") or "") + (r.get("out") or ""))}
        probe = d.rstrip("/") + "/.pyinj_write_test"
        r = self.shell("echo ok > %s && echo __WROTE__ && rm -f %s" % (shq(probe), shq(probe)),
                       timeout=30)
        if "__WROTE__" not in (r.get("out") or ""):
            return {"ok": False, "msg": explain_adb_error((r.get("err") or "")
                                                          + (r.get("out") or ""))}
        return {"ok": True, "msg": "目录可写：%s" % d}

    # -- 传输 --
    def push(self, local, remote, timeout=PUSH_TIMEOUT):
        return self._run(["push", os.path.abspath(local), _collapse(remote)], timeout=timeout)


# ---------------------------------------------------------------- 上传执行

def _row(item, status, msg=""):
    return {"local": item.get("local", ""), "rel": item.get("rel", ""),
            "remote": item.get("remote", ""), "size": item.get("size", 0),
            "status": status, "msg": msg}


STATUS_TEXT = {"ok": "✓ 成功", "skip": "⏭ 跳过", "fail": "✗ 失败", "cancel": "⏹ 取消"}


def summarize(rows):
    c = {"ok": 0, "skip": 0, "fail": 0, "cancel": 0}
    for r in rows or []:
        k = r.get("status")
        if k in c:
            c[k] += 1
    c["total"] = len(rows or [])
    return c


def upload_plan(adb, plan, skip_same=True, progress=None, check_cancel=None, retries=1):
    """逐文件上传：建目录 → （可选）跳过 MD5 相同 → rm -f → push → md5 校验（失败重试）。

    progress(done, total, name)：每处理完一个文件回调一次；
    check_cancel() -> True 时停止，剩余条目记为「已取消」。
    返回结果行列表（status: ok / skip / fail / cancel）。
    """
    plan = list(plan or [])
    total = len(plan)
    rows = []
    made = set()
    for i, item in enumerate(plan):
        if check_cancel and check_cancel():
            rows.extend(_row(x, "cancel", "已取消") for x in plan[i:])
            break
        rel = item.get("rel") or os.path.basename(item.get("local") or "")
        local = item.get("local") or ""
        remote = item.get("remote") or ""
        if not os.path.isfile(local):
            rows.append(_row(item, "fail", "本地文件不存在或已被移动"))
        else:
            d = remote_dir(remote)
            if d not in made:
                mk = adb.mkdir_p(d)
                if not mk.get("ok"):
                    rows.append(_row(item, "fail", "创建远端目录失败：%s"
                                     % explain_adb_error((mk.get("err") or "")
                                                         + (mk.get("out") or ""))))
                    if progress:
                        progress(i + 1, total, rel)
                    continue
                made.add(d)
            local_md5 = md5_file(local)
            if skip_same and local_md5:
                if adb.md5(remote) == local_md5:
                    rows.append(_row(item, "skip", "远端 MD5 相同，已跳过"))
                    if progress:
                        progress(i + 1, total, rel)
                    continue
            # 先删：远端文件可能带只读属性，直接 push 会失败
            adb.rm(remote)
            ok, msg = False, ""
            for _attempt in range(max(0, int(retries)) + 1):
                r = adb.push(local, remote)
                if not r.get("ok"):
                    msg = explain_adb_error((r.get("err") or "") + (r.get("out") or ""))
                    continue
                got = adb.md5(remote)
                if got and local_md5 and got == local_md5:
                    ok, msg = True, ""
                    break
                msg = "MD5 校验不一致" if got else "读不到远端 MD5（校验失败）"
            rows.append(_row(item, "ok" if ok else "fail", msg))
        if progress:
            try:
                progress(i + 1, total, rel)
            except Exception:
                pass
    return rows
