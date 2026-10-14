# 开发工具

`dev/` 不参与运行时。这里的脚本分为离线回归、图像判据分析、现场取证和文档生成四类。

## 离线回归

- `weather_variants_test.py --assets <KARDS_Batch目录>`：27 个同名天气版本的规则、歧义拒绝、原图与 240px 缩图 OCR；不操作游戏。
- `pending_fixes_test.py`：零费候选、费用恢复、嵌套扫描截止、总部爆炸真实帧、丛林热友方目标与无目标路径。

- `special_hq_probe.py --assets <special-headquarter目录> --out <输出目录>`：保比例归一化用户 JPG，输出总部标框和 JSON，不访问游戏窗口。
- `special_hq_test.py --assets <special-headquarter目录>`：19 张保比例实机帧、19 次总部对调、46 个素材运行布局合成、21 套空牌桌；校验敌我总部、血量、目标点、单位数和支援槽位。合成数据不算实机结论。
- `special_hq_native_test.py`：对 `logs/pc_five_20261013_171141` 保存的原生 PC 周期帧做 A/B；输出差异图，固定检查正常单位不丢失、预览卡不计入战场、移动单位攻击数字不充当总部。

- `orange_hand_test.py`：费用组合、槽位约束、真实 PC 橙/灰帧及倾斜字形检查（不输入游戏）。
- `orange_hand_live.py`：当前 PC 对局中的有限时长验证；默认只悬停取证，`--play --seconds 180` 才运行出牌引擎，不创建下一局。每次运行证据存到独立时间目录。
- `pc_campaign_watch.py`：使用生产 Controller 观察指定局数，记录扫描耗时、成功/拒绝出牌、选牌事件、原始截图和源码哈希；出现停手即退出。`--resume` 保留已完成局并分段恢复，需用户授权实机运行。`--minimal-shots` 仅保留首次、结算及每局每类一次异常，关闭周期/扫描/普通拖牌/攻击存图；`--game-version` 记录已核实版本，未核实默认 unverified。最新状态索引为 `logs/pc_campaign_latest.json`。

在仓库根目录运行，退出码 `0` 表示通过：

```cmd
.venv\Scripts\python.exe dev\gui_test.py
.venv\Scripts\python.exe dev\gui_options_test.py
.venv\Scripts\python.exe dev\actions_test.py
.venv\Scripts\python.exe dev\update_check_test.py
.venv\Scripts\python.exe dev\orders_test.py
.venv\Scripts\python.exe dev\choice_test.py
.venv\Scripts\python.exe dev\dismiss_test.py
.venv\Scripts\python.exe dev\reward_test.py
.venv\Scripts\python.exe dev\turn_logic_test.py
```

`choice_test.py` 需要原始截图置于被忽略的 `shots/choice_samples/`，文件名为
`choice_two.png`、`choice_two_sea_battle.png`、`choice_two_sea_battle_blocked.png`、
`three_first.png`、`three_second.png`、`three_unit.png`、`normal.png`；也可用
`--samples-dir` 指向另一目录。测试还会扫描 `shots/` 中的真实非选牌帧。
三牌默认测试验证真实天气帧、空标题也能选边、连续菜单和防重复，不调用 OCR。
旧标题一致、空白、陌生标题和超时测试在可选诊断模式下保留。
本机实机停手帧 `shots/choice/0926_192524_blocked.png` 和两张“海战”样本用于验证
双牌无需 OCR 即可按规则选边、动画稳定等待、悬停边框和禁止重复点击。
缺少本机样本时测试会报错。选牌判据改动应同时用
`.venv` 和面板使用的 `python/python.exe` 运行，以覆盖两套 OCR 置信度。
正常对局帧默认读取样本目录的 `normal.png`，也可用 `--normal-frame` 指定。
固定样本不要只留在会自动清理的 `scan_frames/` 中。
`three_unit.png` 覆盖单位触发菜单的真实标题、中间选项与阶段恢复；
同时回归标题反复变化、正确与空白交替时的六秒超时。

便携 Python 不依赖跨系统 `.venv`，PowerShell 中可这样运行：

```powershell
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONPATH = (Join-Path $PWD 'src')
.\python\python.exe dev/choice_test.py
```

`reward_test.py` 需要被忽略的 `shots/post_match/reward_claim_20260926.png`
（1280×720 客户区）和 `shots/` 内至少 80 张暗色负帧；所有窗口和鼠标操作均用替身，
不会点击游戏。原始截图、完整日志和现场报告留在本机，不随包发布。

常用覆盖范围：

| 脚本 | 覆盖 |
|---|---|
| `turn_logic_test.py` | 回合状态机、部署、攻击 |
| `choice_test.py` | 真实帧两牌/三牌识别、独立入口、连续选牌和停手；不点击游戏 |
| `reward_test.py` | 暗色领奖页真实帧、黑帧及遮挡停手、4/10 补点恢复、局数停止与回退开关 |
| `card_match_test.py` | 卡名、费用、卡库 |
| `unit_state_test.py` | 费用徽章判据 |
| `hand_memory_test.py` | 手牌记忆 |
| `board_geom_test.py` | 战场几何 |
| `win_capture_test.py` | 截图管线 |
| `gui_test.py` | 面板参数、日志和冻结路径 |
| `gui_options_test.py` | 配置持久化、无效输入和写入失败 |
| `actions_test.py` | 鼠标动作失败处理 |
| `update_check_test.py` | 更新检查、Release 附件和文件清单哈希比对 |

依赖真实截图的用例在没有 `shots/` 时可能跳过或报缺样本，这是预期行为。

## 图像判据工具

修改识别规则前先做 A/B：

- `*_ab.py`：比较旧、新判据的多收和漏收；
- `*_diag.py`：解释某个候选为什么被过滤；
- `*_timing.py`：拆分耗时；
- `probe_*.py`、`*_probe.py`：现场取证或采样；
- `state_roi_ab.py`、`hand_edge_ab.py`、`card_mask_ab.py`：常用识别对照。
- `choice_title_probe.py`：只读比较旧双牌样本和实机停手帧的标题 OCR 裁切、
  置信度及文本；双牌运行流程已不使用该 OCR 判据。探针不连接游戏、不点击。
- `three_title_probe.py`：只读比较两组三选一截图在面板便携 Python 和开发环境
  的标题 OCR 置信度，并核对六个标题是否存在于卡库。

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
- `order_list_doc.py`：按当前 `orders.playable()` 生成可用及不能自动打出的两份指令卡清单；
- `orders_test.py`、`order_target_test.py`：验证规则表和目标判据。

生成文件不要手改；修改生成器后重新生成并跑对应测试。

## 新增脚本约定

脚本必须写清用途、是否需要游戏窗口、是否会点击，以及输出目录。新增回归、探针或生成器后，把它登记在本文件，并保持根目录只放运行入口和构建文件。

## 2026-10-14 天气五局专项补充

- `guard_adjacency_test.py`：总部相邻守护、非邻接/前线负例和轰炸机目标过滤；可回放本机守护现场帧。
- `weather_variants_test.py --assets <素材目录>`：27 版本、每组合最多一张天气、54 次原图/缩图 OCR；本机保存的旋风/骤雨失败裁图存在时额外回放。
- `pc_campaign_watch.py --rounds 5 --minimal-shots --weather-audit`：训练对局天气版本审计；首次天气小裁图总量上限六个，`--resume <目录>` 保留局数与源码分段。
