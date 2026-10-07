# -*- mode: python ; coding: utf-8 -*-
# Windows 7 版打包配置（与 PyInjector.spec 同源，只换 Qt 绑定与输出名）
#
# 用法（必须用 Python 3.9 环境跑，否则打出来还是 Win10+ 的 exe）：
#   <py39> -m PyInstaller PyInjector-win7.spec
#
# 为什么 Win7 版要单独一份 spec：
#   PySide2/Qt5 与 PySide6/Qt6 的模块名、DLL 完全不同，hiddenimports 也得跟着换；
#   其余第三方与标准库 hiddenimports 与 Win10 版完全一致（源测活 exec 动态加载的
#   import 静态分析同样看不见）。
a = Analysis(
    ['injector.py'],
    pathex=[],
    binaries=[],
    # 外置词库随 exe 分发到 data/（分类识别/网络诊断用，用户可编辑免重打包）：
    #   敏感词库.txt        —— 分类识别（成人/短剧/直播/音乐/音频/点播）
    #   需特殊上网域名库.txt —— 网络诊断（命中即提示「需特殊上网」）
    # 与标准版 PyInjector.spec 对齐（2026-09-29 白天新增 pyinj_kw/pyinj_netdiag 后补齐）。
    datas=[
        ('data/敏感词库.txt', 'data'),
        ('data/需特殊上网域名库.txt', 'data'),
    ],
    # ---- Qt5 绑定：PySide2（Qt6 版这里是 PySide6，Win7 用不了）----
    # PySide2 5.15.2.1 是 PyPI 上的最新版，Qt5.15；下面 hiddenimports 显式点名它的三个模块，
    # 因为 injector.py 的导入写在 run_gui() 内部，PyInstaller 静态分析同样看不见。
    # ---- 第三方 ----
    hiddenimports=[
        'requests',
        'urllib3', 'charset_normalizer', 'idna', 'certifi',
        'PySide2.QtCore', 'PySide2.QtGui', 'PySide2.QtWidgets',
        'shiboken2',
        'pyquery', 'cssselect',
        'bs4', 'soupsieve',
        'lxml', 'lxml.etree', 'lxml.html', 'lxml.cssselect',
        'ujson',
        'cachetools',
        # ---- 标准库（exec 动态加载的源码同样拿不到，uuid 就是这么漏的）----
        'uuid', 'base64', 'gzip', 'zlib', 'hashlib', 'random', 'ssl',
        'html', 'http', 'http.client', 'copy', 'traceback', 'string',
        'math', 'datetime', 'binascii', 'hmac', 'struct', 'socket',
        'urllib', 'urllib.parse', 'urllib.request', 'urllib.error',
        'concurrent', 'concurrent.futures', 'xml', 'xml.etree',
        'xml.etree.ElementTree', 'json', 'time', 'io', 'mimetypes',
        # ---- 新增工具模块静态 import 兜底（pyinj_* 自动分析；csv/collections 显式点名）----
        'csv', 'collections',
        # 自定义代理服务器（与标准版一致：SOCKS5 内置实现，不依赖 PySocks）
        'pyinj_proxy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    # 注意：PyInstaller 5.x 的 Analysis 不接受 optimize / packages 参数（PyInstaller 6 才有）
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='源管家Win7',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Win7 上控制台窗口隐藏更容易出问题，保留 console=True 便于出错时把报错贴回来；
    # 正式分发可将 console=False。
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
