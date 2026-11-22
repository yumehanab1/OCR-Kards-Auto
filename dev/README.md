# 开发工具

`dev/` 不参与运行时。这里的脚本分为离线回归、图像判据分析、现场取证和文档生成四类。

## PC 读取模拟器：路线 B 单局原型

`emu_battle_pilot.py` 是 Windows 侧的开发原型，未发布，不接入默认 PC 面板或引擎。模拟器不需要助手 APK；PC 原型仍须通过 `--mobile-root` **只读**加载已核对的本地手游规则和模板。只处理已确认的训练战场，不从主页开局，不点换牌、选目标或结算，不出指令、盲拖未知牌、移动或攻击。

可选识图工具：

- `emu_training_profile.py` 的 `TrainingVision` 使用同局、绑定一致且人工核过的两张首回合空支援线图，仅为原相邻落点补证；抓牌另要求局部完整卡名精确对应卡库单位。独立的 `RightmostUnitTitles` 只逐帧读取唯一、完整露出的右端单位名，不复用旧读数，不接入基础 CLI 默认路径；读牌本身不是派发许可。
- `emu_board_witness.py` 只识别已审 1280×720 简中「选择目标」提示，用于行动选择及等待后验；命中停在 `target_selection_pending`，已派发的效果仍未决，不点目标、不结束回合。
- `emu_rejection_witness.py` 独立识别已审 1280×720 简中「指挥点数不足，无法使用此卡牌」；原型只在部署后验阶段用它标记 `deploy_rejected_insufficient_kredits`，不确认部署、不猜实际抓中的牌、不重发。两个提示未命中都不是放行依据。
- `emu_route_b_fast_vision.py` 是可选的同帧识图适配器：共享重复的像素计算，但每张图仍重读完整卡名、卡面费和可用费用。`emu_route_b_readonly.py` 校验并加载第三局归档的识图配置，只接收已保存的 1280×720 PNG，向标准输出写 JSONL；不连接设备，也没有派发或续局入口。

在 PC 仓库根目录用便携 Python 执行以下**离线**命令，不启动 ADB 或触控。事先令 `$mobile` 指向本地手游源码树（规则、模板和保存的测试样本），`$png` 指向已有原始 PNG，`$newDir` 指向手游树之外、尚不存在的本地输出目录：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONNOUSERSITE = '1'
$py = '.\python\python.exe'
$old = 'logs/pc_emu_b_20261119_0128'
$reopened = 'logs/pc_emu_b_20261119_reboot_0224'
$battleE = Join-Path $old 'battle-E-resolved-deploy'
$live01 = Join-Path $reopened 'live-01'
$live04 = Join-Path $reopened 'live-04'

& $py -B dev/emu_battle_pilot.py --mobile-root $mobile --frame $png --out $newDir
& $py -B dev/emu_battle_pilot_test.py --mobile-root $mobile --battle-e $battleE --card3-run $live01
& $py -B dev/emu_training_profile_test.py --mobile-root $mobile --capture $reopened --previous-capture $old
& $py -B dev/emu_rightmost_title_test.py --capture $live04
& $py -B dev/emu_board_witness_test.py --battle-dir $battleE
& $py -B dev/emu_rejection_witness_test.py --replay
```

`--frame` 是单张文件检查，只向新目录写 `events.jsonl` 和该帧的副本；未传 `--frame` 的设备采帧不是离线。测试命令带齐对应的本机证据参数才覆盖真实帧；`emu_rejection_witness_test.py --replay` 从上述固定日志目录取样。删掉证据参数只能运行不依赖这些样本的用例；部分样本未随仓库提供。

仅在有本机第三局归档的 PC 仓库中复现慢帧（沿用上面的 `$py` 和环境变量）：

```powershell
$s = (Resolve-Path 'logs/pc_emu_b_lobby_20261119_073422').Path
$frames = @(66,68,69,70,71 | ForEach-Object { Join-Path $s ('battle-01/discard-{0:D4}.png' -f $_) })
$frameArgs = @(foreach ($f in $frames) { '--frame'; $f })
# 冷：每张图各起两个新进程，轮换新旧顺序；暖：先检查开场双帧，再测五帧三遍。
$order = @('original','fast')
foreach ($f in $frames) {
    foreach ($v in $order) { & $py -B dev/emu_route_b_readonly.py --session-root $s --variant $v --profile --frame $f }
    [array]::Reverse($order)
}
foreach ($v in 'fast','original') {
    & $py -B dev/emu_route_b_readonly.py --session-root $s --variant $v --profile --entry-check --rounds 3 @frameArgs
}
& $py -B dev/emu_route_b_fast_vision_test.py --session-root $s -v
```

`observe_ms` 不含磁盘读图、PNG 解码、ADB 传输、前台复核或派发。归档固定绑定本机第三局及其空场参照，不是新对局的参照来源。普通 41 项测试现在将数字诊断图导出到临时目录，保留真实样本读取和计算；无需预装数字库。

现场须另行确认授权、训练模式与唯一目标实例。设备采帧须显式指定 `--adb`、回环 `--serial` 与 `--package`；只有同时传 `--live --confirmed-training` 才允许发送。`--end-only` 关闭部署，`--max-actions` / `--seconds` 限制预算，`--stop-file` 支持协作停止。结束回合需要两帧明确「敌方」且我方按钮消失；部署需要手牌变化、原有单位留存且目标侧确实多出一个有兵种的单位。`adb_returned_zero` 不是成功；`effect_unconfirmed` 要停下复核原帧，不重发。原图和完整账本只保存在本地。参见[单实例训练报告](../docs/reports/pc/2026-11-19-emulator-single-training.md)。

## 离线回归

- `emu_transport_test.py`：30 项模拟器发现与传输层回归，覆盖 MuMu / 雷电（LDPlayer）/ 蓝叠（BlueStacks）/ 通用 ADB 发现与别名去重、自定义提供方与传输工厂扩展口、MuMu IPC 像素翻转/缩放/缓冲区复用/异常释放、ADB 自动重连与前台包名解析；不操作真实模拟器。
- `emu_ocr_server_test.py`：17 项共享本地 OCR 服务回归，覆盖 `127.0.0.1` 绑定、随机 token 鉴权、绕过系统代理、`/health` 与 `/ocr`、异常自动回退本地 RapidOCR 及 `EmuManager` 自动拉起/停机生命周期；不操作真实模拟器。
- `emu_worker_test.py`：89 项模拟器视觉与单实例工作进程回归，覆盖 `mobile-core` / `src/emu_runtime` 只读加载、1.61.27589 菜单/登录奖励/先手与后手换牌/断网重启 OCR、两级空槽与橙色单位部署兜底、看门狗自愈、随机节奏抖动、每日局数/时长上限、状态文件并发写重试与协作停止；不操作真实模拟器。
- `emu_manager_test.py`：19 项多开调度器回归，覆盖 `config/emu_options.json` 原子读写、按实例独立配置覆盖、每日用量统计、错峰批量启动、共享 OCR 启停、并行协作停机、日志增量缓存与实例启停控制委托；不操作真实模拟器。
- `gui_emu_test.py`：面板模拟器多开与 PC 高级抽屉集成回归，覆盖 `make_js_api` 反射隔离、5 个 `emu_*` 桥接接口、更新锁互斥、配置隔离、PC 折叠实验项与一键跳转多开、多开按实例覆盖与 Node 前端交互逻辑；不打开窗口或操作游戏。
- `input_edges_test.py`：20项假输入边界检查，覆盖零费部署输入失败不后验/不换槽、安全停止信号和释放、结束确认前保留失败锁、换算来源失效、按下后失焦/遮挡/几何变化，以及物理拖拽末段失败；不操作游戏。
- `message_input_test.py`：面板默认/保存/参数、窗口绑定、消息悬停/停车/点击/拖拽、无物理回退、遮挡/前台/尺寸/旧坐标拒绝、异常松开；15项假Win32检查，不操作游戏。
- `attack_input_test.py`：攻击/上前线输入失败不做后验、不计成功/游戏拒绝、不封总部、回合内不重发及上层账本；16项假输入检查，不操作游戏。
- `card_coverage_test.py`：1646个cardId无遗漏、当前规则一致、天气/重名分开、候选不放行、无实机冒认及生成确定性；不写文件、不操作游戏。

- `orange_speed_test.py`：主牌裁框、嵌套首张截止、禁止过期追加OCR/重悬停、未知身份拒识与部署diff保留；另含天气抓点复核每次重读效果、费用/版本变化拒绝、共享截止恢复及传统入口；使用假帧，不调用OCR、不操作游戏。
- `orange_identity_ab.py --baseline-ref <提交> [--manifest <样本清单>]`：旧/新分类器真实帧回放，记录卡名/费用/天气版本、OCR次数/面积与耗时；禁用输入和指纹写入。默认另有全帧宽diff压力样本，明确标为合成边界；实际扫描diff需由清单提供neutral或diff_box，不把静态计时视为实机回合速度。

- `beta_version_test.py`：beta/正式版比较、正式Atom过滤、精确beta更新源的附件/HEAD回退、自定义源隔离、配套beta包预备与安装；只操作临时目录。

- `classic_strategy_test.py`：传统模式从面板/CLI传至引擎、绕过橙色与凑费、旧布局/记忆及全量回退、1费继续扫描、大手牌3次成功后收手、零费保护及禁用同点重悬停；不操作游戏。

- `card_db_update_test.py`：1646条卡库/1588个卡名、12张平衡补丁、按cardId同步规则、补丁幂等与拒绝未知上游变化、旧改名指纹隔离、突发交战2费/5费与旧3费拒绝；不操作游戏。
- `update_card_db.py --snapshot <官网快照> [--write]`：根据已审阅快照哈希与card_db/patches/2026-10-15.json构建卡库，默认仅核对；不联网、不修改指令权限。改库后运行order_plan.py --write及order_list_doc.py刷新规则资料和清单。
- `gui_bridge_test.py`：使用真实pywebview桥接初始化与调用，验证仅公开七个操作方法、不遍历原生窗口/进程属性；不创建窗口或操作游戏。
- `gui_long_log_test.py`：128MiB日志、超长单行/UTF-8、单次限量读取、缓存与增量传输、轮询并发约束、保留原文归档、查看器追加/截短/轮换跟随；只操作临时文件。

- `orange_first_test.py`：零费/估计预算不盲扫、首张即停、不因满阵线/已出天气漏过后续合法候选、放大面板费用复核、协作截止及真实零预算失败帧；不操作游戏。

  另含三张真实左侧悬停帧的1费边界回放与费用不一致拒绝；本机样本位于shots/orange_hover_roi_20261016，跨系统缺样时只跳过这一项。

- `update_install_test.py`：只替换变更/新增文件、分段下载/完整回退、断网与损坏校验、配置保护、文件占用回滚、崩溃恢复、Windows互斥锁及独立助手退出等待/重启；只操作临时目录，不操作游戏。

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
| `update_feed_assets_test.py` | API限流/超时后读取公开附件、配套清单校验、GUI文件比对与错误提示 |

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

- `card_coverage.py`：默认只打印全卡能力统计；`--write`生成`docs/generated/card_coverage.json`及`.md`，`--check`只读核对。按cardId逐条记录现有规则、执行路径、信息缺口、策略/实机证据未登记状态，不修改出牌权限。

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
- `pc_speed_watch.py --label baseline --max-turns 8`：运行生产训练策略并观测完整我方回合、扫描/OCR/截图/等待/监测写盘耗时；默认当前橙色策略，最多五局或八个已观测回合，15秒/回合边界刷盘，复用现有图像最多六张。会操作游戏；`--label fix` 分目录比较，`--resume <目录> --max-turns 16` 续测，按钮消失单独记录而不直接断言超时。
  已手动选定休闲模式时可用`--mode casual --rounds 1 --max-turns 0`记录完整线上计时对局；不选择排位。
