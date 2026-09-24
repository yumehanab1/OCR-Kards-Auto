# 开发工具

`dev/` 不参与运行时。这里的脚本分为离线回归、图像判据分析、现场取证和文档生成四类。

## 离线回归

在仓库根目录运行，退出码 `0` 表示通过：

```cmd
.venv\Scripts\python.exe dev\gui_test.py
.venv\Scripts\python.exe dev\actions_test.py
.venv\Scripts\python.exe dev\update_check_test.py
.venv\Scripts\python.exe dev\orders_test.py
.venv\Scripts\python.exe dev\dismiss_test.py
.venv\Scripts\python.exe dev\turn_logic_test.py
```

常用覆盖范围：

| 脚本 | 覆盖 |
|---|---|
| `turn_logic_test.py` | 回合状态机、部署、攻击 |
| `card_match_test.py` | 卡名、费用、卡库 |
| `unit_state_test.py` | 费用徽章判据 |
| `hand_memory_test.py` | 手牌记忆 |
| `board_geom_test.py` | 战场几何 |
| `win_capture_test.py` | 截图管线 |
| `gui_test.py` | 面板参数、日志和冻结路径 |
| `actions_test.py` | 鼠标动作失败处理 |
| `update_check_test.py` | 更新检查错误分支 |

依赖真实截图的用例在没有 `shots/` 时可能跳过或报缺样本，这是预期行为。

## 图像判据工具

修改识别规则前先做 A/B：

- `*_ab.py`：比较旧、新判据的多收和漏收；
- `*_diag.py`：解释某个候选为什么被过滤；
- `*_timing.py`：拆分耗时；
- `probe_*.py`、`*_probe.py`：现场取证或采样；
- `state_roi_ab.py`、`hand_edge_ab.py`、`card_mask_ab.py`：常用识别对照。

这些工具通常会读取本机 `shots/`，部分会移动鼠标；运行前先看脚本顶部说明。

## 现场工具

| 目的 | 工具 |
|---|---|
| 看当前界面 | `live_probe.py` |
| 看战场 | `field_probe.py`、`board_frame_check.py` |
| 看手牌 | `hand_live_probe.py`、`hand_zone_capture.py` |
| 看攻击判据 | `attack_probe.py` |
| 看日志 | `src/watch_log.py` |
| 验证窗口和锁 | `selfcheck.py` |
| 采集 UI 模板 | `template_capture.py` |

## 规则与文档生成

- `order_plan.py`：维护指令卡规则并生成 `config/order_plays.json`；
- `order_list_doc.py`：生成 `docs/generated/指令卡清单.md`；
- `orders_test.py`、`order_target_test.py`：验证规则表和目标判据。

生成文件不要手改；修改生成器后重新生成并跑对应测试。

## 新增脚本约定

脚本必须写清用途、是否需要游戏窗口、是否会点击，以及输出目录。新增回归、探针或生成器后，把它登记在本文件，并保持根目录只放运行入口和构建文件。