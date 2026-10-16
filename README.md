# KARDS AUTO

[![Release](https://img.shields.io/github/v/release/yumehanab1/OCR-Kards-Auto)](https://github.com/yumehanab1/OCR-Kards-Auto/releases) [![License](https://img.shields.io/github/license/yumehanab1/OCR-Kards-Auto)](LICENSE)

Windows 64 位 KARDS 画面自动化工具：只读屏幕、模拟鼠标，不读内存、不注入游戏。

> 自动化操作可能触发游戏检测。请使用小号，控制时长，不要无人值守长期运行。

## 直接使用

从 [Releases](https://github.com/yumehanab1/OCR-Kards-Auto/releases) 下载 `kards-auto_vX.Y.Z_x86_64.zip`，解压到空目录后：

1. KARDS 设置为简体中文、`1280×720`、窗口或无边框模式。
2. 打开 KARDS，停在主界面。
3. 双击 `KARDS AUTO.exe`，选择局数后点“开始”。

游戏窗口必须可见且在前台。日志在 `logs/main_loop.log`；遇到问题请附日志，不要附账号信息或完整截图。

面板只读取日志末尾，并限制超长行的显示长度；完整内容仍在日志文件中。
单个日志达到8MiB后，下次启动时会归档到 `logs/archive/`，历史日志保留。

## 检测更新

面板的“检测更新”会先读取 GitHub Release，再下载一个很小的
`.manifest.json` 清单，逐个计算本地文件的 SHA-256，并列出变更或缺失的路径。
查到新版或同版本修订后点击“应用更新”，会下载并校验变更/新增文件，自动关闭面板、替换文件并重启。
一致的文件保持原样，本机开关、窗口位置、学习的卡牌哈希、日志和手机版目录保留。
更新前先停止自动对局；替换失败会恢复旧文件，备份与结果保存在 `logs/updates/`。
若更新被意外中断，再开面板会提供“恢复旧文件”按钮。

下载服务器支持分段时，只读取 ZIP 目录和变更文件；不支持时会下载完整包，安装仍仅替换变更文件。
没有配套 PC 文件清单时，请使用发布页下载。已有旧面板需要先换用一次带“应用更新”的新版面板，后续即可直接更新。

## 面板开关

| 开关 | 默认 | 作用 |
|---|---:|---|
| 自动打完一局 | 开 | 部署、出牌、结算 |
| 攻击 | 开 | 按规则表攻击和上前线 |
| 坐标表直扫 | 开 | 使用已标定的手牌坐标加快扫描 |
| 结束回合 | 关 | 未开启自动打完一局时主动点击结束回合 |
| 排位模式 | 关 | 启用前会提示检测和封号风险 |
| 只看不动 | 关 | 调试用，不移动鼠标 |
| 跑几局 | 3 | `0` 表示持续运行 |

排位模式只在有 `ranked_mode_btn` 模板时点击排位；模板缺失会安全停住，不会回退到休闲模式。

开关和局数修改后自动写入 `config/gui_options.json`，重启面板自动恢复，不会自动运行。

## 从源码运行

需要 Windows 10/11、Python 3.10+：

```cmd
install.cmd
.venv\Scripts\python.exe src\main_loop.py --play --fast-scan --attack --max-rounds 1
```

改 `src/gui.py` 后运行 `build_gui.bat` 重打面板；改其他引擎模块无需重打。

## 项目结构

| 路径 | 内容 |
|---|---|
| `src/` | 面板和运行时引擎 |
| `config/` | 状态、规则、数字模板 |
| `ui_templates/` | UI 模板图 |
| `card_db/` | 运行时卡库 |
| `docs/design/` | 早期设计档案 |
| `docs/generated/` | 规则和清单生成物 |
| `docs/reports/` | PC 与手游/Android 报告入口 |
| [`mobile/`](mobile/README.md) | 手机版说明与[源码入口](mobile/source/README.md)，独立维护 |
| `dev/` | 测试、探针、标定工具 |
| `shots/`、`logs/` | 本机材料，不提交、不发布 |

更多说明：[`docs/README.md`](docs/README.md)、[`docs/architecture.md`](docs/architecture.md)、[`dev/README.md`](dev/README.md)。
目前不会自动打出的指令卡见[禁用清单](docs/generated/打不出去的指令卡.md)。

## 许可

源码采用 GPL-3.0。`ui_templates/` 中的游戏截图素材属于 1939 Games，边界见 [`NOTICE.md`](NOTICE.md)。

## 手机端 / Android

[手机版源码](mobile/source/README.md)已补入仓库，Android项目与PC源码独立维护。

[v0.2.2 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.2) 已预留手机版区域，0.2.2 APK待补充；当前手机版仍使用下方0.2.1下载。

请从 [v0.2.1 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.1) 的 **Mobile / Android** 区域直接下载：

- [KARDS-AUTO-Mobile-v0.2.1.apk](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.1/KARDS-AUTO-Mobile-v0.2.1.apk)：直接安装，无需解压。
- [安装说明](mobile/README.md)及[验证报告/SHA-256](docs/reports/mobile/APK_0.2.1_RELEASE.md)。旧0.2.0资产保留在历史Release。
- 游戏设置：画质不限，内容比例设为“原生”，UI 比例调为 1。

当前包为0.2.1 / versionCode109，包含悬浮启停/阶段显示、行动后部署、特殊外观识别与350MiB截图证据预算。经过正式构建、签名、覆盖安装及Android识别/截图回放验证；十局实机及截图单局证据来自明确列出的开发版本，不称0.2.1新十局通过。实体手机、脱离主机及完整断线重连仍未验收。

手机端只依赖 APK 和 Android 无障碍权限，运行时不依赖 Windows、ADB、Python 或 PC 端程序。PC 端验证结果不能替代手游验证。
