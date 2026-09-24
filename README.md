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

## 面板开关

| 开关 | 默认 | 作用 |
|---|---:|---|
| 自动打完一局 | 开 | 部署、出牌、结算 |
| 攻击 | 开 | 按规则表攻击和上前线 |
| 惰性扫描 | 开 | 找到可出的牌就停止扫描 |
| 结束回合 | 关 | 主动点击结束回合 |
| 排位模式 | 关 | 启用前会提示检测和封号风险 |
| 只看不动 | 关 | 调试用，不移动鼠标 |
| 跑几局 | 3 | `0` 表示持续运行 |

排位模式只在有 `ranked_mode_btn` 模板时点击排位；模板缺失会安全停住，不会回退到休闲模式。

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
| `dev/` | 测试、探针、标定工具 |
| `shots/`、`logs/` | 本机材料，不提交、不发布 |

更多说明：[`docs/README.md`](docs/README.md)、[`docs/architecture.md`](docs/architecture.md)、[`dev/README.md`](dev/README.md)。

## 许可

源码采用 GPL-3.0。`ui_templates/` 中的游戏截图素材属于 1939 Games，边界见 [`NOTICE.md`](NOTICE.md)。