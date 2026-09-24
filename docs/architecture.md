# 当前架构

这份文档描述当前代码的真实运行链路。早期 M0–M3 文档记录设计过程，遇到冲突时以代码和本文件为准。

## 运行链路

```text
KARDS AUTO.exe
    └─ src/gui.py                 面板、参数收集、日志展示
         └─ src/main_loop.py      单实例保护、截图、状态机、结算流程
              ├─ src/ui_state.py  主菜单/选牌/排队/换牌/对局/结算识别
              └─ src/turn_engine.py
                   ├─ hand_scanner_v2.py  手牌识别
                   ├─ card_match.py       卡名、费用、类型
                   ├─ board.py             战场和总部
                   ├─ deploy.py            部署拖拽
                   └─ attack.py            上前线和攻击
```

面板 exe 只负责界面。发布包里的 `python\python.exe` 会重新读取发布包中的 `src\`、`config\`、`ui_templates\` 和 `card_db\`，所以修改引擎代码后不需要把代码编进 exe；修改 `src/gui.py` 后必须重打 exe。

## 运行时输入

| 目录/文件 | 作用 | 维护规则 |
|---|---|---|
| `src/` | 引擎和面板源码 | 运行时模块放根目录；废弃实验放 `src/archive/` |
| `config/templates.json` | 模板路径与 ROI | 加模板时同时提交 PNG 和区域 |
| `ui_templates/` | 按钮、图标模板 | 只放运行时需要的模板 |
| `config/kredits_digits/` | 费用数字模板 | 不要移到 `shots/`，发布脚本会检查它 |
| `config/order_plays.json` | 指令卡规则表 | 由 `dev/order_plan.py` 生成，避免手改 |
| `card_db/kards_data.json` | 卡名、费用、类型 | 运行时必需，不是测试夹具 |
| `logs/` | 本机运行日志 | 不提交、不打包 |
| `shots/` | 本机截图和取证材料 | 不提交、不打包 |

## 状态机边界

`main_loop.py` 只负责跨页面推进：

1. `main_menu`：点击主页面左上进入卡组选择；
2. `deck_select`：按普通/训练/排位模板选择模式，再点击开始；
3. `queueing`：等待匹配，超时取消并重来；
4. `mulligan`：确认换牌；
5. `in_game`：交给 `TurnEngine`；
6. `victory` / `defeat`：完成结算补点，回到主菜单。

识别不到状态时必须保持 `fail-closed`：记录 `state -> None` 并等待，不凭猜测点击。

## 新文件放哪里

- 新的运行时模块：`src/` 根目录，并在 `CONTRIBUTING.md` 的代码结构表登记。
- 新的离线回归：暂放 `dev/`，文件名以 `_test.py` 结尾，并在 `dev/README.md` 登记。
- 新的探针/A-B 工具：暂放 `dev/`，用 `_probe.py`、`_ab.py`、`_diag.py` 或 `_timing.py` 区分用途。
- 新的设计、排障和实机报告：`docs/`，按 `design/`、`generated/`、`reports/`、`archive/` 的语义归类。
- 临时截图、日志、拼图：`shots/` 或 `logs/`，不要放根目录。
- 根目录只保留用户入口、安装/构建脚本、许可证和顶层说明。
