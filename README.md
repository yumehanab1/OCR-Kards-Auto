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

## 检测更新

面板的“检测更新”会先读取 GitHub Release，再下载一个很小的
`.manifest.json` 清单，逐个计算本地文件的 SHA-256，并列出变更或缺失的路径。
它不会下载或解压完整 zip，也不会自动替换文件；当前 Release 没有清单时会明确提示无法列出差异。

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
| `mobile/` | 手机版 Release 占位说明；手机版源码和 APK 保持独立维护 |
| `dev/` | 测试、探针、标定工具 |
| `shots/`、`logs/` | 本机材料，不提交、不发布 |

更多说明：[`docs/README.md`](docs/README.md)、[`docs/architecture.md`](docs/architecture.md)、[`dev/README.md`](dev/README.md)。
目前不会自动打出的指令卡见[禁用清单](docs/generated/打不出去的指令卡.md)。

## 许可

源码采用 GPL-3.0。`ui_templates/` 中的游戏截图素材属于 1939 Games，边界见 [`NOTICE.md`](NOTICE.md)。

## 手机端 / Android

手游助手与 Windows PC 端分开维护。请从 [v0.2.0 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.0) 的 **Mobile / Android** 区域下载：

- `KARDS-AUTO-Mobile-v0.2.0.zip`：APK、安装说明和公开验证报告。
- `KARDS-AUTO-Mobile-v0.2.0.manifest.json`：包内文件的 SHA-256 与大小清单。

当前包包含 code57 / versionName 0.8.31。runtime-test 模拟器配合 KARDS 1.60.27292/code2703 完成了休闲模式连续 5 局实测：5/5 胜利，330 次战斗输入均 accepted/completed，每局胜负和回页均确认。实体手机、脱离主机和完整断线重连仍未验收，详见仓库及包内报告。

手机端只依赖 APK 和 Android 无障碍权限，运行时不依赖 Windows、ADB、Python 或 PC 端程序。PC 端验证结果不能替代手游验证。
