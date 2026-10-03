# -*- coding: utf-8 -*-
"""v14 GUI 冒烟测试（Mock PySide6，无需真实 Qt/显示器）。
目的：捕获 ConfigDialog 新方法体（_start_url_check / _update_url_cell /
disable_selected / enable_selected 及两处后台线程）中的 NameError / 属性错误。
后台线程以同步方式执行 run()，信号直接调用已连接槽。"""
import os
import sys
import json
import types
import inspect
import tempfile
import shutil
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

PASS, FAIL = 0, 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


# ---------------- 最小 PySide6 Mock ----------------
class _Sig:
    def __init__(self):
        self._slots = []
    def connect(self, fn):
        self._slots.append(fn)
    def disconnect(self, *a):
        self._slots = []
    def emit(self, *args):
        for fn in list(self._slots):
            fn(*args)


class Signal:
    def __init__(self, *types):
        self._types = types
        self._name = None
    def __set_name__(self, owner, name):
        self._name = name
    def __get__(self, instance, owner):
        if instance is None:
            return self
        d = instance.__dict__.setdefault("_sigs", {})
        if self._name not in d:
            d[self._name] = _Sig()
        return d[self._name]


def Slot(*a, **k):
    def deco(fn):
        return fn
    return deco


class QObject:
    def __init__(self, *a, **k):
        self._sigs = {}
    def deleteLater(self):
        pass
    def closeEvent(self, ev):
        pass


class QThread(QObject):
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent

    def start(self):
        try:
            self.run()
        finally:
            self.finished.emit()

    def quit(self):
        pass

    def run(self):
        pass


class QWidget(QObject):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self._enabled = True
    def close(self):
        self.closeEvent(None)
        return True
    def setEnabled(self, v):
        self._enabled = bool(v)
    def isEnabled(self):
        return self._enabled
    def setDisabled(self, v):
        self._enabled = not bool(v)
    def setMinimumWidth(self, *a):
        pass
    def setFixedWidth(self, *a):
        pass
    def setMinimumHeight(self, v):
        self._min_h = v
    def setMaximumHeight(self, v):
        self._max_h = v
    def setFixedHeight(self, v):
        self._min_h = self._max_h = self._fixed_h = v
    def height(self):
        return getattr(self, "_fixed_h",
                       getattr(self, "_min_h", getattr(self, "_max_h", 0)))
    def findChildren(self, *a):
        return []
    def setWindowTitle(self, *a):
        pass
    def resize(self, *a):
        pass
    def setLayout(self, *a):
        pass
    def setAcceptDrops(self, *a):
        pass
    def setAlignment(self, *a):
        pass
    def setAttribute(self, *a):
        pass
    def setGeometry(self, *a):
        pass
    def setToolTip(self, t=""):
        self._tip = t
    def toolTip(self):
        return getattr(self, "_tip", "")
    def setMaximumWidth(self, *a):
        pass
    def setSizePolicy(self, *a):
        pass
    def setPlaceholderText(self, *a):
        pass
    def raise_(self):
        pass
    def setParent(self, *a):
        pass
    def rect(self):
        return None
    def setStyleSheet(self, *a):
        pass
    def setObjectName(self, *a):
        pass
    def show(self):
        pass
    def hide(self):
        pass
    def isVisible(self):
        return False
    def accept(self):
        pass
    def reject(self):
        pass
    def exec(self):
        return 1


class QDialog(QWidget):
    def exec(self):
        return 1


class QColor:
    def __init__(self, *a):
        pass


class QFont:
    def __init__(self, *a):
        pass
    def setUnderline(self, v):
        pass


class QTableWidgetItem:
    def __init__(self, text=""):
        self._text = str(text)
        self._fg = None
        self._font = None
    def text(self):
        return self._text
    def setText(self, t):
        self._text = str(t)
    def setForeground(self, c):
        self._fg = c
    def setFont(self, f):
        self._font = f
    def setToolTip(self, t):
        pass


class _Header:
    Stretch = 1
    Interactive = 0
    sectionClicked = Signal()
    def setSectionResizeMode(self, *a):
        pass
    def setSectionsClickable(self, *a):
        pass
    def setSortIndicator(self, *a):
        pass
    def setSortIndicatorShown(self, *a):
        pass
    def setMinimumSectionSize(self, *a):
        pass
    def setStretchLastSection(self, *a):
        pass
    def setVisible(self, *a):
        pass


class QTableWidget(QWidget):
    cellClicked = Signal()
    cellDoubleClicked = Signal()
    itemSelectionChanged = Signal()
    customContextMenuRequested = Signal()

    def __init__(self, rows=0, cols=0):
        super().__init__()
        self._rows = rows
        self._cols = cols
        self._grid = {}
        self._widgets = {}
        self._header = _Header()
        self._current = -1
    def setRowCount(self, n):
        self._rows = n
        # 清理超出的行
        for (r, c) in list(self._grid):
            if r >= n:
                del self._grid[(r, c)]
        for (r, c) in list(self._widgets):
            if r >= n:
                del self._widgets[(r, c)]
    def setCellWidget(self, r, c, w):
        self._widgets[(r, c)] = w
    def cellWidget(self, r, c):
        return self._widgets.get((r, c))
    def rowCount(self):
        return self._rows
    def insertRow(self, r):
        self._rows += 1
    def setItem(self, r, c, item):
        self._grid[(r, c)] = item
    def item(self, r, c):
        return self._grid.get((r, c))
    def setHorizontalHeaderLabels(self, labels):
        self._labels = labels
    def horizontalHeader(self):
        return self._header
    def setSelectionBehavior(self, *a):
        pass
    def setEditTriggers(self, *a):
        pass
    def setAlternatingRowColors(self, *a):
        pass
    def setVerticalHeader(self, *a):
        pass
    def verticalHeader(self):
        return _Header()
    def setHorizontalHeader(self, hdr):
        self._header = hdr
        return hdr
    def selectRow(self, r):
        self._current = r
    def currentRow(self):
        return self._current
    def scrollToItem(self, *a):
        pass
    def setContextMenuPolicy(self, *a):
        pass
    def setMouseTracking(self, *a):
        pass
    def resizeColumnsToContents(self):
        pass
    def setColumnWidth(self, *a):
        pass
    def columnWidth(self, *a):
        return 80
    def viewport(self):
        return QWidget(self)


class QLineEdit(QWidget):
    textChanged = Signal()
    returnPressed = Signal()
    def __init__(self, text=""):
        super().__init__()
        self._text = text
    def text(self):
        return self._text
    def setText(self, t):
        self._text = t
    def setReadOnly(self, *a):
        pass
    def setPlaceholderText(self, *a):
        pass
    def setClearButtonEnabled(self, *a):
        pass


class QLabel(QWidget):
    def __init__(self, t=""):
        super().__init__()
        self._t = t
    def text(self):
        return self._t
    def setText(self, t):
        self._t = t
    def setTextFormat(self, *a):
        pass
    def setWordWrap(self, *a):
        pass
    def setStyleSheet(self, *a):
        pass


class QPushButton(QWidget):
    clicked = Signal()
    def __init__(self, t="", clicked=None):
        super().__init__()
        self._t = t
        if clicked is not None:
            self.clicked.connect(clicked)
    def text(self):
        return self._t
    def setText(self, t):
        self._t = t
    def click(self):
        self.clicked.emit()
    def setProperty(self, *a):
        pass


class QPlainTextEdit(QWidget):
    textChanged = Signal()
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text = text or ""
    def setReadOnly(self, *a):
        pass
    def setStyleSheet(self, *a):
        pass
    def appendPlainText(self, *a):
        pass
    def setPlainText(self, t):
        self._text = t
        self.textChanged.emit()
    def toPlainText(self):
        return self._text
    def fontMetrics(self):
        class _FM(object):
            def lineSpacing(self):
                return 20
            def height(self):
                return 16
        return _FM()


class QListWidget(QWidget):
    itemDoubleClicked = Signal()
    def clear(self):
        pass
    def addItem(self, *a):
        pass
    def count(self):
        return 0
    def viewport(self):
        return QWidget(self)
    def row(self, *a):
        return 0
    def currentRow(self):
        return -1


class QGroupBox(QWidget):
    def __init__(self, *a):
        super().__init__()


class QCheckBox(QWidget):
    def __init__(self, *a):
        super().__init__()
        self._checked = False
    def setChecked(self, b):
        self._checked = b
    def isChecked(self):
        return self._checked


class QSpinBox(QWidget):
    def __init__(self):
        super().__init__()
        self._v = 0
    def setRange(self, *a):
        pass
    def setValue(self, v):
        self._v = v
    def value(self):
        return self._v


class QProgressBar(QWidget):
    def setRange(self, *a):
        pass
    def setValue(self, *a):
        pass
    def setTextVisible(self, *a):
        pass
    def setObjectName(self, *a):
        pass
    def hide(self):
        pass
    def show(self):
        pass


class QFormLayout(QWidget):
    def addRow(self, *a):
        pass


class QDialogButtonBox(QWidget):
    Ok = 1
    Cancel = 2
    accepted = Signal()
    rejected = Signal()
    def __init__(self, *a):
        super().__init__()


class QVBoxLayout(QWidget):
    def addLayout(self, *a):
        pass
    def addWidget(self, *a):
        pass
    def addStretch(self, *a):
        pass
    def setContentsMargins(self, *a):
        pass
    def setSpacing(self, *a):
        pass
    def setHorizontalSpacing(self, *a):
        pass
    def setVerticalSpacing(self, *a):
        pass
    def setColumnStretch(self, *a):
        pass
    def setRowStretch(self, *a):
        pass


class QHBoxLayout(QVBoxLayout):
    pass


class QGridLayout(QVBoxLayout):
    pass


class QSizePolicy:
    Maximum = 1
    Fixed = 2
    Preferred = 3
    def __init__(self, *a, **k):
        pass


class QFileDialog:
    @staticmethod
    def getExistingDirectory(*a):
        return ""
    @staticmethod
    def getOpenFileNames(*a):
        return ([], "")


class QMessageBox:
    Yes = 1
    No = 0
    def __init__(self, *a, **k):
        pass
    @staticmethod
    def information(*a, **k):
        return QMessageBox.Yes
    @staticmethod
    def warning(*a, **k):
        return QMessageBox.Yes
    @staticmethod
    def question(*a, **k):
        return QMessageBox.Yes
    @staticmethod
    def critical(*a, **k):
        return QMessageBox.Yes


class QHeaderView:
    Stretch = 1
    ResizeToContents = 3
    Interactive = 0
    Horizontal = 1
    Vertical = 2
    sectionClicked = Signal()
    def __init__(self, *a):
        pass
    def setSectionResizeMode(self, *a):
        pass
    def setMinimumSectionSize(self, *a):
        pass
    def setSectionsClickable(self, *a):
        pass
    def setSortIndicator(self, *a):
        pass
    def setSortIndicatorShown(self, *a):
        pass
    def sectionSize(self, *a):
        return 60
    def logicalIndexAt(self, *a):
        return -1
    def cursor(self):
        return None
    def sectionSizeHint(self, *a):
        return 60


class QAbstractItemView:
    SelectRows = 1
    NoEditTriggers = 2


class Qt:
    BlockingQueuedConnection = 1
    CustomContextMenu = 3
    PointingHandCursor = 13
    ArrowCursor = 0
    AscendingOrder = 0
    DescendingOrder = 1
    AlignCenter = 0x0084
    AlignRight = 0x0002
    AlignLeft = 0x0001
    AlignVCenter = 0x0080
    AlignTop = 0x0020
    WA_TransparentForMouseEvents = 51
    NoBrush = 0
    Vertical = 2
    RichText = 1


class QEvent:
    MouseMove = 129
    WindowTitleChange = 33


class QTimer:
    @staticmethod
    def singleShot(ms, fn):
        pass  # 不实际触发，避免测试中 toast 被立即清空


class QSettings:
    def __init__(self, *a, **k):
        pass
    def value(self, *a, **k):
        return None
    def setValue(self, *a, **k):
        pass
    def contains(self, *a):
        return False


class QUrl:
    @staticmethod
    def fromLocalFile(path):
        return "file:///" + str(path).replace("\\", "/")


class QDesktopServices:
    @staticmethod
    def openUrl(url):
        # 测试里不真的打开外部程序，只记录调用
        OPENED.append(url)
        return True


OPENED = []


class QKeySequence:
    Delete = 0
    def __init__(self, *a):
        pass


class QShortcut:
    def __init__(self, *a, **k):
        pass


class _CtxAction:
    triggered = Signal()


class QMenu:
    def __init__(self, *a, **k):
        pass
    def addAction(self, *a, **k):
        return _CtxAction()
    def addSeparator(self):
        return None
    def exec(self, *a, **k):
        pass


class QFrame(QWidget):
    pass


class QTabWidget(QWidget):
    """合并导入对话框用的 Tab 容器 mock。"""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._tabs = []
    def addTab(self, w, label=""):
        self._tabs.append((w, label))


class QRadioButton(QWidget):
    """单选按钮 mock（injector 的 Qt import 列表里仍声明，供构造与勾选）。"""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._checked = False
    def isChecked(self):
        return self._checked
    def setChecked(self, v):
        self._checked = bool(v)


class QInputDialog(QWidget):
    """文本输入对话框 mock（injector 的 Qt import 列表里仍声明）。"""
    @staticmethod
    def getText(*a, **k):
        return "", False


class QComboBox(QWidget):
    """v260928：类型过滤下拉框用（全部 / 直连CMS(1) / Spider(3) / XML(0) / 目录(4)）。"""
    currentIndexChanged = Signal()

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._items = []      # [(label, userData)]
        self._idx = 0

    def addItem(self, label, userData=None):
        self._items.append((label, userData))

    def addItems(self, labels):
        for lb in labels:
            self._items.append((lb, None))

    def clear(self):
        self._items = []
        self._idx = 0

    def count(self):
        return len(self._items)

    def itemText(self, i):
        return self._items[i][0] if 0 <= i < len(self._items) else ""

    def itemData(self, i):
        return self._items[i][1] if 0 <= i < len(self._items) else None

    def currentIndex(self):
        return self._idx

    def currentText(self):
        return self.itemText(self._idx)

    def currentData(self):
        return self.itemData(self._idx)

    def setCurrentIndex(self, i):
        self._idx = i if 0 <= i < len(self._items) else 0
        try:
            self.currentIndexChanged.emit(self._idx)
        except Exception:
            pass

    def setMaxVisibleItems(self, n):
        pass


class QMetaObject:
    @staticmethod
    def invokeMethod(*a, **k):
        return ""


class Q_ARG:
    def __init__(self, *a):
        pass


class Q_RETURN_ARG:
    def __init__(self, *a):
        pass


class QApplication:
    def __init__(self, argv):
        pass
    def processEvents(self):
        pass
    def exec(self):
        return 0
    def setApplicationName(self, *a):
        pass


# ---- 组装 fake PySide6 包 ----
def _make_mod(name, attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


class QItemSelectionModel:
    """mock：仅提供标志常量；select/clearSelection 在 mock 表格上不存在，
    _refresh_table/_selected_rows 走 try/except 退回 currentRow 路径。"""
    Select = 0x0001
    Rows = 0x0020
    Current = 0x0010
    NoUpdate = 0x0000


qtcore = _make_mod("PySide6.QtCore", {
    "QThread": QThread, "Signal": Signal, "Slot": Slot,
    "QMetaObject": QMetaObject, "Qt": Qt, "Q_ARG": Q_ARG, "Q_RETURN_ARG": Q_RETURN_ARG,
    "QObject": QObject, "QItemSelectionModel": QItemSelectionModel,
    "QTimer": QTimer, "QSettings": QSettings, "QEvent": QEvent,
    "QUrl": QUrl,
})
qtgui = _make_mod("PySide6.QtGui", {"QColor": QColor, "QFont": QFont,
                                    "QKeySequence": QKeySequence,
                                    "QShortcut": QShortcut,
                                    "QDesktopServices": QDesktopServices})
qtwidgets = _make_mod("PySide6.QtWidgets", {
    "QApplication": QApplication, "QWidget": QWidget, "QVBoxLayout": QVBoxLayout,
    "QHBoxLayout": QHBoxLayout, "QLabel": QLabel, "QLineEdit": QLineEdit,
    "QPushButton": QPushButton, "QListWidget": QListWidget, "QPlainTextEdit": QPlainTextEdit,
    "QGroupBox": QGroupBox, "QCheckBox": QCheckBox, "QSpinBox": QSpinBox,
    "QFileDialog": QFileDialog, "QMessageBox": QMessageBox, "QDialog": QDialog,
    "QFormLayout": QFormLayout, "QDialogButtonBox": QDialogButtonBox,
    "QTableWidget": QTableWidget, "QTableWidgetItem": QTableWidgetItem,
    "QHeaderView": QHeaderView, "QAbstractItemView": QAbstractItemView,
    "QProgressBar": QProgressBar, "QColor": QColor,
    "QMenu": QMenu, "QFrame": QFrame, "QShortcut": QShortcut,
    "QRadioButton": QRadioButton, "QInputDialog": QInputDialog,
    "QComboBox": QComboBox, "QGridLayout": QGridLayout, "QSizePolicy": QSizePolicy,
    "QTabWidget": QTabWidget,
})
pkg = types.ModuleType("PySide6")
pkg.QtCore = qtcore
pkg.QtGui = qtgui
pkg.QtWidgets = qtwidgets
sys.modules["PySide6"] = pkg
sys.modules["PySide6.QtCore"] = qtcore
sys.modules["PySide6.QtGui"] = qtgui
sys.modules["PySide6.QtWidgets"] = qtwidgets

# ---------------- 注入 mock 并取出 ConfigDialog ----------------
import injector as I

# 构造一个小型测试仓库：2 个 active 站点 + 1 个已禁用站点；py/ 含 live-url 与 no-url 两个 .py
tmp = tempfile.mkdtemp(prefix="pyinj_gui_")
pydir = os.path.join(tmp, "py")
os.makedirs(pydir)

# 本地 http 服务器（供 live-url .py 检测）
import socket as _sk
import http.server as _hs
import threading as _th
_port = 0
_s = _sk.socket()
_s.bind(("127.0.0.1", 0))
_port = _s.getsockname()[1]
_s.close()
class _H(_hs.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a):
        pass
_srv = _hs.HTTPServer(("127.0.0.1", _port), _H)
_th.Thread(target=_srv.serve_forever, daemon=True).start()
import time
time.sleep(0.2)

with open(os.path.join(pydir, "live.py"), "w", encoding="utf-8") as f:
    f.write('url = "http://127.0.0.1:%d/feed"\n' % _port)
with open(os.path.join(pydir, "nope.py"), "w", encoding="utf-8") as f:
    f.write('x = 1\n')  # 无 URL

RAW = '''{
  "spider": "x",
  "sites": [
    {"key": "py_live", "name": "Live┃PY", "api": "./py/live.py", "type": 3},
    /* [disabled]
    {"key": "py_off", "name": "Off┃PY", "api": "./py/nope.py", "type": 3}
    */
    {"key": "py_nope", "name": "Nope┃PY", "api": "./py/nope.py", "type": 3}
  ]
}'''
cfg = os.path.join(tmp, "py.json")
with open(cfg, "w", encoding="utf-8") as f:
    f.write(RAW)

sites = I.parse_jsonc(RAW).get("sites", [])

# 取出 ConfigDialog 类（修改 run_gui 末尾避免启动真实 App）
src = inspect.getsource(I.run_gui)
idx = src.rfind("    app = QApplication")
src2 = src[:idx] + "    return ConfigDialog\n"
g = dict(I.__dict__)
exec(src2, g)
ConfigDialog = g["run_gui"]()

print("== GUI 构造 + 手动启动检测（mock 线程同步跑）==")
dlg = ConfigDialog(None, tmp, RAW, sites, "py.json", tmp)
# v2026.09.24.e：检测区合并为一张卡片，勾选类型 + 共用 开始/暂停/停止
# mock 的 QThread.start() 同步调用 run()，故各 worker 同步跑完
ok("构造后默认未开始（成人状态行）", "未开始" in dlg.prog_label.text(), dlg.prog_label.text())
ok("构造后默认未开始（可达状态行）", "未开始" in dlg.url_label.text(), dlg.url_label.text())
ok("构造后共用「开始」可用", dlg.b_detect_start.isEnabled())
ok("构造后共用「暂停」禁用", not dlg.b_detect_pause.isEnabled())
ok("构造后共用「停止」禁用", not dlg.b_detect_stop.isEnabled())
ok("存在类型勾选框", hasattr(dlg, "cb_adult") and hasattr(dlg, "cb_url"))
ok("类型勾选默认均勾选", dlg.cb_adult.isChecked() and dlg.cb_url.isChecked())
dlg._start_adult()
ok("成人检测完成", dlg._scanning is False)
ok("成人完成不自动接力 URL", dlg._url_scanning is False and not dlg._url_started)
dlg._start_url()
ok("表格 10 列", dlg.table._cols == 10, "cols=%s" % dlg.table._cols)
ok("已加载 3 条（含 1 禁用）", len(dlg.entries) == 3, str(len(dlg.entries)))
ok("禁用标记正确(live,off,nope -> F,T,F)",
   [e.get("_disabled") for e in dlg.entries] == [False, True, False],
   str([e.get("_disabled") for e in dlg.entries]))
ok("成人检测完成", dlg._scanning is False)
ok("URL 检测完成", dlg._url_scanning is False)
ok("URL 结果含 py_live", "py_live" in dlg.url_map)
ok("py_live 可达(code=1)", dlg.url_map.get("py_live", (0,))[0] == 1, str(dlg.url_map.get("py_live")))
ok("py_nope 无URL(code=2)", dlg.url_map.get("py_nope", (0,))[0] == 2, str(dlg.url_map.get("py_nope")))

print("== 检测卡片勾选驱动（v2026.09.24.e）==")
dlg2 = ConfigDialog(None, tmp, RAW, sites, "py.json", tmp)
ok("新建对话框类型勾选默认均勾选", dlg2.cb_adult.isChecked() and dlg2.cb_url.isChecked())
dlg2.cb_adult.setChecked(False)
dlg2._start_detect()
ok("仅勾 URL：成人未启动", dlg2._scanning is False)
ok("仅勾 URL：URL 已启动并完成", dlg2._url_scanning is False and "py_live" in dlg2.url_map)
dlg2.close()

print("== 禁用 / 启用 选中 ==")
# 选中第 0 行（py_live）并禁用
dlg.table.selectRow(0)
before_raw = dlg.raw
dlg.disable_selected()
ok("禁用后 raw 改变", dlg.raw != before_raw)
ok("py_live 进入禁用集合", "py_live" in I.parse_disabled_keys(dlg.raw))
ok("禁用后条目 _disabled=True", any(e.get("key") == "py_live" and e.get("_disabled") for e in dlg.entries))
# 再启用
dlg.table.selectRow(0)
dlg.enable_selected()
ok("启用后 py_live 不在禁用集合", "py_live" not in I.parse_disabled_keys(dlg.raw))
ok("启用后仍 JSON 合法", True)

print("== 🔀 合并导入对话框（_MergeDialog）==")
md_ns = dict(I.__dict__)
exec(src[:idx] + "    return _MergeDialog\n", md_ns)
MergeDialog = md_ns["run_gui"]()
base_raw = json.dumps({"spider": "s", "sites": [
    {"key": "a", "name": "A站", "api": "./py/a.py", "type": 3},
]}, ensure_ascii=False)
mdlg = MergeDialog(None, tmp, "py.json", base_raw, tmp)
# jar 型多站点：同一类名 csp_PanWebShare + 不同 ext，必须全部判为 new，绝不误并
jar_inc = json.dumps({"sites": [
    {"key": "j%d" % i, "api": "csp_PanWebShare", "jar": "x.jar",
     "ext": {"site": "http://%d" % i}, "type": 3} for i in range(8)
]}, ensure_ascii=False)
# 再加 key 撞现有 a 但指纹不同（冲突改名）+ 全新站点 b
full_inc = json.loads(jar_inc)
full_inc["sites"] += [
    {"key": "a", "name": "A其它", "api": "./py/other.py", "type": 3},   # key 撞现有 a 但指纹不同 -> conflict
    {"key": "b", "name": "B站", "api": "./py/b.py", "type": 3},        # 全新 -> new
]
mdlg.txt_paste.setPlainText(json.dumps(full_inc, ensure_ascii=False))
mdlg._parse_paste()
ok("合并计划已生成", mdlg.plan is not None)
s = mdlg.plan["summary"]
ok("jar 8 站点无误并（dup=0）", s["dup"] == 0, s)
ok("新增含 8 jar + 1 全新 b = 9", s["new"] == 9, s)
ok("key 撞车判为冲突 1 条", s["conflict"] == 1, s)
ok("表格行数 = 来源条数", mdlg.table.rowCount() == 10, mdlg.table.rowCount())
# 默认动作：全部 add（无 dup / 无批次内重复）
acts = [r["action"] for r in mdlg.rows]
ok("无默认跳过行", acts.count("skip") == 0, acts)
ok("默认全部 add（8 jar + 冲突 a + b = 10）", acts.count("add") == 10, acts)
# 全部设为加入并应用（无本地源仓库，不搬运配套）
mdlg._set_action_bulk("add")
mdlg._apply()
ok("应用产出新文本", bool(mdlg.result_text))
merged = I.parse_jsonc(mdlg.result_text)
mkeys = [x["key"] for x in merged["sites"]]
ok("合并后含原 a + 新增 b + 8 jar", set(mkeys) >= {"a", "b"}, mkeys)
ok("冲突行自动改名（a -> a_2）", "a_2" in mkeys, mkeys)
ok("8 个 jar 全部保留（未因同名类名被并掉）",
   sum(1 for x in merged["sites"] if x.get("api") == "csp_PanWebShare") == 8, mkeys)
ok("写入结果仍合法", isinstance(merged, dict))
mdlg.close()

_srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：%d 通过, %d 失败" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
