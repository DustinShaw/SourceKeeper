# -*- mode: python ; coding: utf-8 -*-
# 全部使用相对路径（相对本 spec 所在目录），两台电脑均可直接打包：
#   <venv-python> -m PyInstaller PyInjector.spec
# 打包机无需再写死 site-packages 路径 —— 用哪个 python 跑，就自动用哪个环境分析依赖。

a = Analysis(
    ['injector.py'],
    pathex=[],
    binaries=[],
    # 外置词库（可编辑的本地文本文件）随 exe 一并分发到 data/ 目录：
    #   敏感词库.txt        —— 分类识别用（成人/短剧/直播/音乐/音频/点播）
    #   需特殊上网域名库.txt —— 网络诊断用（命中即提示「需特殊上网」）
    # 运行时 pyinj_kw.get_data_dir() 会优先在 exe 同目录的 data/ 下找它们；
    # 用户可直接编辑这两个文件定制词库，无需重新打包。
    datas=[
        ('data/敏感词库.txt', 'data'),
        ('data/需特殊上网域名库.txt', 'data'),
    ],
    # 源测活：被测 py 源是 exec 动态加载的，PyInstaller 的静态分析看不见它们的
    # import，必须在 hiddenimports 显式打包（影视仓 PyLoader 同样自带这些库）。
    # 普查自 py/*.py 实际用到的第三方库（2026-09-26.c）：
    #   requests / pyquery / bs4(+lxml) / ujson / cachetools
    hiddenimports=[
        # ---- 第三方 ----
        'requests',
        'urllib3', 'charset_normalizer', 'idna', 'certifi',
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
        # ---- 新增工具模块（pyinj_sections/speed/netdiag/kw/jar/playlist/report）----
        # 这些模块是静态 import 进 injector 的，PyInstaller 能自动分析；此处显式
        # 声明仅为稳妥（若日后改为惰性导入也不丢）。
        'csv', 'collections',
        # 自定义代理服务器（SOCKS5 走内置握手实现 —— 刻意**不**依赖 PySocks，
        # 两个构建环境都没有它；HTTP/HTTPS 走 CONNECT 隧道，全部用标准库）
        'pyinj_proxy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# ---------------------------------------------------------------------------
# 体积瘦身：本工具只用 QtCore / QtGui / QtWidgets 三个模块，下面三项与功能
# 完全无关，却是打包件里最大的三块（占解压后体积约 30%），一律滤掉：
#   · opengl32sw.dll 19.7MB —— SwiftShader 软件 OpenGL，只有 3D/QML 场景才需要
#   · PySide6/translations/ 6.4MB —— Qt 各语言包，程序不切多语言
#   · qdirect2d.dll   1.0MB —— Direct2D 平台插件，只用 qwindows 就够
# 移除后已在冻结 exe 上做过 GUI 冒烟（窗口/表格/对话框/源测活正常）。
# ---------------------------------------------------------------------------
_DROP_BIN = ('opengl32sw.dll', 'qdirect2d.dll')
_DROP_DAT = ('py-side6/translations',)
a.binaries = [t for t in a.binaries
              if not any(k in str(t[0]).lower() for k in _DROP_BIN)]
a.datas = [t for t in a.datas
           if not any(k in str(t[0]).lower() for k in _DROP_DAT)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='源管家',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 无控制台窗口（2026-09-29）：GUI 走窗口子系统，双击 exe 不再弹黑窗。
    # CLI 代码仍保留在 injector.py（未被删除），命令行模式只是不再通过 exe 暴露；
    # 源测活的子进程入口（--pyinj-probe-worker）不受影响——它也是本 exe 自我调用，
    # 无控制台时输出经管道回传，仍可正常解析。
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
