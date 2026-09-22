# `dev\` 里的脚本都是干什么的

跑游戏**用不到**这个目录（整个删掉不影响使用），它是开发和排查的工具箱。
按用途分四类，改代码时按需取用。带回游戏窗口跑的那些会**真的移动鼠标**，脚本自己的
docstring 和 `--help` 里都写了注意事项。

## 一、回归用例（离线，不需要游戏）

改代码前后都该跑，退出码 0 就是过。用法：在仓库根目录
`.venv\Scripts\python.exe dev\<名字>.py`。清单和覆盖范围见
[CONTRIBUTING.md](../CONTRIBUTING.md#跑测试)。

```
turn_logic_test.py       回合状态机 + 部署判据 + 攻击规则（最大的一套，约 200 秒）
card_match_test.py       卡名五级匹配 + 费用徽章 + 指纹库 + 全卡库自检
unit_state_test.py       费用徽章橙/灰判据、假徽章守卫
hq_hp_test.py            总部血量盾牌读取（留一验证）
kredits_two_digit_test.py 两位数费用（钉住「11 不能读成 1」）
kredits_extract_test.py  费用数字提取
scan_fast_test.py        直扫兜底与早退原因
hand_memory_test.py      手牌记忆
board_geom_test.py       战场几何（行结构 / 卡数 / 卡间距）
win_capture_test.py      截图管线判据（不需要窗口）
actions_test.py          鼠标动作软着陆（不需要窗口）
gui_test.py              面板逻辑
update_check_test.py     检测更新的每条错误分支
deploy_test.py / diff_test.py   早期的手动验证脚本，需要游戏窗口
```

> ⚠️ `shots\` 不在仓库里，所以依赖真值帧的用例在新 clone 上会报「缺样本帧」——
> 那是预期结果，不是回归。

## 二、只读 A/B（改判据之前先量）

```
badge_false_ab.py        费用徽章的假阳性守卫：并集新旧对照 + 掉/多联系表
badge_old_vs_new.py      换判据时把「多收的」「丢掉的」分别拼图
badge_ctx_ab.py          「亮卡面」判据：只看右边 vs 上右下任一方向
badge_band_probe.py      连通域检出 vs 行带补检
badge_tile_probe.py      把检出的徽章按橙/灰拼成小图（判对没有只能看图）
badge_s_calib.py         按饱和度分档拼图，用来标定橙/灰阈值
badge_feat_probe.py      给每个徽章候选量一组特征
badge_ab_test.py         两版徽章检测器对照（滑窗版就是被它判死的）
badge_miss_diag.py       某个徽章为什么没被检出：逐条列出卡在哪条过滤上
kredits_numeral_ab.py    数字隔离的新旧对照（624 帧）
ocr_ab.py                read_field 的 OCR 兜底新旧对照
state_roi_ab.py          界面状态识别：整帧 vs 按 region
hand_timing.py           手牌识别耗时拆解 + 裁剪窗口 A/B
hand_edge_ab.py          手牌左右边缘判据
hand_layout_pick_ab.py   布局条目挑选
hand_edge_diag.py        边缘为什么测错（把那条带上的区段全列出来）
card_mask_ab.py          战场卡面检测新旧对照
card_ab_shots.py         把上面的差异帧画出来（蓝=老 / 绿=新）
board_anchor_probe.py    场上卡定位的三套锚点（卡框 / 徽章 / 并集）对比
guard_ab.py              守护判据全语料命中 + 边界带拼图
intercept_ab.py          拦截规则的输入侧（敌方支援线有没有战斗机）
memory_ab.py             手牌记忆开/关两段日志对照
field_timing.py / field_timing2.py   read_field 各步耗时
mouse_vs_field_probe.py  鼠标位置对战场读数的影响
```

## 三、实机取证（只读，会移鼠标但不点击）

```
live_probe.py            当前是什么界面 + 存一帧
field_probe.py           战场读数（走新链路） + 标注图
attack_probe.py          攻击预检：逐张打印我方单位类型与目标；--move-front 会真拖一次
hand_live_probe.py       手牌每个探针的分类证据、图标分数、OCR 原文
hover_dump.py            悬停指定 x，存帧并把整帧 OCR 的每一行连位置打出来
board_sampler.py         采战场帧（原始帧 + 掩码 + 标注 + 索引 jsonl）
board_frame_check.py     单帧核对器：卡框 / 徽章 / 行结构 / 我方支援·前线张数
guard_probe.py           把一帧里每张盘面卡裁出来放大拼图（还有没有别的字形）
hq_hp_probe.py           总部血量盾牌取样、聚类、标定模板库
template_capture.py      交互式采集模板：抓当前窗口 → 拖框 → 按数字键存名
hand_zone_capture.py     手牌布局校准（手动框选版，推荐；比自动检测准）
hand_calibrate.py        手牌布局校准（自动版，慢，且张数靠推算）
turn_sampler.py          每个回合开始/结束各存一帧，用来标定费用数字颜色
calibrate_cost_color.py  把上面采到的帧按 x 配对，比较费用数字颜色
kredits_record.py        录制费用数字字形（实时标注疑似值）
kredits_glyphs_report.py 字形去重报表 + 拼图
scan_frame_check.py      把日志里的「量到 L…/R…」配到存帧上画竖线
scan_bench.py            离线跑手牌识别（用 shots 里的真实帧）
fix_bands.py             只读：给出四条战线的建议行带
drop_check.py            离线核对部署落点候选会不会砸在卡上
cost_state_probe.py      费用数字颜色标定辅助
deploy_probe.py          每 1.5 秒记一次战场变化，观察部署落在哪
edge_probe.py            手牌两个边缘的稳定度探针
```

## 四、日常查看

```
watch_log.py             终端里实时看日志（自己切代码页，中文不乱码）
game_report.py           一局的对账报表：时长 / 费用读数序列 / 部署 / 攻击 / 记忆，--issues 打原文
selfcheck.py             单实例锁与截图管线自检（需要游戏窗口）
m3_probe.py / turn_test.py / turn_planner.py / hover_probe.py / ocr_lines_debug.py
                         M3 时期的验证脚本，留作参考
vision_ask.py            调视觉模型看图（**需要联网和 API key**，只在调试时用，生产链路不用）
```

> 注意：`hand_calibrate.py` 和 `watch_log.py` 实际位于 `src\\`，对应入口是
> `src\\hand_calibrate.py` 与 `src\\watch_log.py`；上面的其它脚本才位于 `dev\\`。

## 一次性脚本的处理方式

带 `_probe` / `_diag` / `_timing` 后缀的大多是为某一次排查写的，能复用就留着，
真的没用了再删 —— 但**删之前确认没有文档或注释在引用它**。
