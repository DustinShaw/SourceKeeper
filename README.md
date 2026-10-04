<div align="center">
  <img src="cover.png" alt="SourceKeeper 封面" width="100%" />
</div>

# 源管家 · SourceKeeper

<div align="center">

**TVBox / 影视仓 全源管理器**

绿色单文件 exe · 免安装 · 免 Python 环境 · 双模式（GUI / CLI）

![License](https://img.shields.io/badge/license-MIT-blue)
![Platform](https://img.shields.io/badge/platform-Windows%207%20%7C%2010%2B-lightgrey)
![Python](https://img.shields.io/badge/python-3.10%2B-informational)
![Release](https://img.shields.io/github/v/release/DustinShaw/SourceKeeper?color=success)

[下载 exe](#-下载) · [快速开始](#-快速开始) · [功能一览](#-功能特性) · [从源码构建](#-从源码构建)

</div>

> 本软件由 AI 辅助生成，仅供个人学习测试之用。

## 简介

源管家是一款面向 TVBox / 影视仓 / FongMi 类播放器的配置管理桌面工具。它统一管理配置里的 `sites` 全部站点——既能登记 spider 爬虫脚本（`.py` / `.js` / `.jar`，`type:3`），也能登记直连 JSON 接口源（`type:1`，如苹果 CMS 的 `api.php/provide/vod`），免去手工拼 key/name/api、手改 JSON 的麻烦。

**隐私承诺**：除测活会正常联网请求外，仅在本地解析文本文件，不留存、不上传任何用户数据。

## ✨ 功能特性

| 功能 | 说明 |
| --- | --- |
| 全源支持 | 一套界面管全部 sites：Spider(3) / 直连 CMS(1) / XML(0) / 目录型(4) |
| 一键注入 | 多选 `.py` 或扫描 `py/` 目录批量登记进 sites 数组 |
| 添加直连源 | 粘贴 API 地址，自动推断 `type:1` 并生成 name 与唯一 key |
| 合并导入 | 把另一份配置（本地文件 / 粘贴文本 / 远程 URL）合并进当前仓库；按四元组判重、逐条预览、配套脚本一并搬运并改写引用；`ads` 按内容并集去重 |
| 剔除失效源 | 用已有检测结果，一键批量禁用或删除明确失效的站点 |
| 类型过滤 | 按 全部 / 直连 / Spider / XML / 目录 / 成人 / 需特殊上网 / 仅失效源 筛选 |
| 手术式编辑 | 完整保留原配置的 `//` 注释与排版，不重排文件 |
| 自动备份 | 每次写入前备份到 `backups/`（时间戳存档，自动轮转只留最近 10 份） |
| 🩺 源测活 | Spider 源子进程跑分类标签栏；直连源 HTTP 取分类列表判活 |
| 工具箱 | 分类识别 / JAR 体检 / 源测速 / 网络诊断 / 直播表转换 / 诊断报告 |
| 绿色单文件 | 双击即用图形界面，不弹控制台黑窗；命令行可走源码 `python injector.py` |

完整功能与场景操作见 [功能介绍.md](功能介绍.md) 与 [使用方法.md](使用方法.md)。

## 📦 下载

从 GitHub Releases 下载最新版本（推荐普通用户）：

**👉 [前往 Releases 页面下载](https://github.com/DustinShaw/SourceKeeper/releases)**

| 文件 | 适用系统 |
| --- | --- |
| `源管家 v2610042023.exe` | Windows 10+（Qt6） |
| `源管家 v2610042023-Win7.exe` | Windows 7（Qt5） |

## 🚀 快速开始

1. 下载对应系统的 exe，双击运行（无需安装、无需 Python）。
2. 点「选择…」选中你的**仓库目录**（里面应有配置文件和 `py/` 文件夹）；首次也可直接把 `.py` 文件拖进主窗口注入。
3. 程序自动识别配置文件（状态标签显示「已加载 xxx.json · 站点 N 个」即成功），所有窗口标题栏都会标注版本。

## ⌨️ 命令行（高级用法）

源码方式运行（需 Python 3.10+ 与 PySide6）：

```
python injector.py --help
```

## 🧱 项目结构

| 文件 | 作用 |
| --- | --- |
| `injector.py` | 主程序入口（GUI + CLI），顶部集中定义版本号与样式 |
| `pyinj_core.py` | 纯逻辑层（JSONC 解析 / 扫描 / 站点改写 / 备份 / 源探测），零 Qt 依赖、可单测 |
| `pyinj_sections.py` 等 | 各功能子模块（lives/parses、词库、测速、网络诊断、JAR 体检、直播表、诊断报告、ads 合并） |
| `data/` | 外置词库（敏感词分类库 / 需特殊上网域名库），分类识别与网络诊断功能依赖 |
| `PyInjector.spec` / `PyInjector-win7.spec` | PyInstaller 打包配置（手工维护，标准版 / Win7 版） |
| `build.py` / `build_win7.py` | 一键构建脚本（标准版 / Win7 版），含版本核对与全量测试 |
| `deploy*.py` | 部署与冒烟校验脚本 |
| `tests/` | 单元测试与 GUI 冒烟测试（PySide6 + PySide2 双链），约 50 个用例 |

说明：`py/`（影视源脚本）、`py.json`（个人配置）、`*.exe`、`dist/`、`build/``.workbuddy/` 等不纳入本仓库（见 `.gitignore`），以保持仓库为纯工具源码。

## 🛠️ 从源码构建

```
pip install -r requirements.txt
python build.py         # 标准版（需要 PySide6）
python build_win7.py    # Win7 版（需要 PySide2）
```

## 📄 许可证

本项目以 [MIT 许可证](LICENSE) 发布。

## ⚠️ 免责声明

- 本软件由 AI 辅助生成，仅供个人学习、测试与研究之用。
- 影视源 spider 脚本的版权归各自原作者所有，本仓库不包含任何用户个人配置与影视源数据。
- 使用本工具产生的任何配置与使用行为，由使用者自行负责。
