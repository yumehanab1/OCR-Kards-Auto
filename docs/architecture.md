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
                   ├─ order_choice.py      两牌/三牌选牌阶段与连续选牌
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

空白画面判据先于页面动作。暗色领取奖励页可能平均亮度低于 10，因此仅在
`dismiss` 已开启时，按客户区比例检查中央奖励图案和底部领取字区的亮像素；
两处均满足条件才允许继续原有结算补点。窗口可见性检查仍须通过，未知画面本身
不会开启补点。`main_loop.POST_MATCH_DARK_REWARD` 可关闭该识别例外。

选牌画面优先于普通对局处理：每个可操作画面检查三牌布局，识别到后进入 `selection_pending`，不要求知道上一张打出的牌。两牌抉择按 `orders.py` 中已标左/右的规则选择；三牌按等概率随机选择。单位部署、攻击或移动触发的三牌同样交给这个阶段；攻击和移动发现弹窗后暂停原有战场判定。一次点击后继续观察下一组选牌，稳定回到正常对局后才恢复之前阶段；无法确定规则或结果时进入 `selection_blocked` 并留帧。独立总开关为 `order_choice.ENABLE_SELECTION_STAGE`。

当前坐标及布局只校准了 1280×720 客户区。`dev/choice_test.py` 使用本机截图验证；离线通过不代表游戏内通过。
双牌选边还会核对两张选项的标题是否都与已标规则卡名一致。真实帧显示便携 OCR
的置信度可能低于开发虚拟环境，因此阈值按便携环境验证。动画期空标题会限时
复读；持续读不到或不一致时进入 `selection_blocked`。
三牌选边会等待布局稳定，再核对三张选项标题均存在于卡库，要求连续两次读到
同一组标题后才进行等概率随机选择。动画时标题未读全会限时复读，卡库中没有的
标题复读确认后停手。标题确认总时限为六秒，读到一次正确标题不会重置计时；
这适用于开发、预报及单位触发的三选一。下一组选项仍留在
同一选牌阶段，不会因第一次点击而恢复普通对局。

识别不到状态时必须保持 `fail-closed`：记录 `state -> None` 并等待，不凭猜测点击。

## 新文件放哪里

- 新的运行时模块：`src/` 根目录，并在本文的运行链路中登记。
- 新的离线回归：暂放 `dev/`，文件名以 `_test.py` 结尾，并在 `dev/README.md` 登记。
- 新的探针/A-B 工具：暂放 `dev/`，用 `_probe.py`、`_ab.py`、`_diag.py` 或 `_timing.py` 区分用途。
- 新的设计、排障和实机报告：`docs/`，按 `design/`、`generated/`、`reports/`、`archive/` 的语义归类。
- 临时截图、日志、拼图：`shots/` 或 `logs/`，不要放根目录。
- 根目录只保留用户入口、安装/构建脚本、许可证和顶层说明。
