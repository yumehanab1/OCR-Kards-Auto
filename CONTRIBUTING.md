# 贡献指南

这份文件写给**想改代码或提 PR 的人**。只想用工具的话看 [README.md](README.md) 就够了。

## 先看哪几份

| 文件 | 什么时候看 |
|---|---|
| [README.md](README.md) | 先看这个，了解程序怎么跑、有哪些约束 |
| `docs\` | 历史设计文档（M0–M3 里程碑、刷级方案），改识别逻辑之前值得翻 |
| [NOTICE.md](NOTICE.md) | 授权边界、第三方库、免责声明。**动 `ui_templates\` 之前必看** |
| [CHANGELOG.md](CHANGELOG.md) | 每个版本改了什么、为什么改 |
| `dev\README.md` | `dev\` 下 70 多个脚本分别是干什么的 |

## 搭环境

```cmd
install.cmd             :: 建 .venv 并装依赖
install.cmd minimal     :: 只装引擎必需的四个包
install.cmd mirror      :: 走清华镜像
```

要求 Python 3.10 以上。依赖清单见 `requirements.txt`；`rapidocr_onnxruntime`（OCR）和
`pywebview`（面板）是**可选**的，没装也照样能跑完整局。

装好之后可以直接跑引擎：

```cmd
.venv\Scripts\python.exe src\main_loop.py --play --fast-scan --attack --max-rounds 1
```

## 代码结构

`src\` 下的模块按职责分：

| 模块 | 职责 |
|---|---|
| `main_loop.py` | 主循环：状态机推进（主菜单 → 选牌组 → 排队 → 换牌 → 对局 → 结算）、遮挡与单实例保护 |
| `turn_engine.py` | 回合引擎：等我的回合 → 攻击 → 上前线 → 部署 → 结束回合 |
| `gui.py` | 面板（pywebview + WebView2）。**它会被打进 exe** |
| `capture.py` / `win.py` | 窗口查找、客户区尺寸、DPI、双通道截图 |
| `actions.py` / `deploy.py` | 鼠标动作与拖拽部署 |
| `hand_scanner_v2.py` | 手牌扫描：差分悬停 + 类型图标 + 卡名 OCR + 查库 |
| `hand_memory.py` | 手牌记忆（按从左到右的次序记身份，跨回合复用） |
| `hand_calibrate.py` | 手牌扇形的左右边缘检测 |
| `card_match.py` | 卡名匹配（精确 → 去噪 → 包含 → 前缀 → 近似）、费用徽章、卡面指纹库 |
| `board.py` | 战场读取：卡框、行结构、总部、支援线单位数 |
| `unit_state.py` | 费用徽章检测与「橙 = 这回合还能行动」判据 |
| `attack.py` | 攻击与上前线：规则表、守护、拦截、命中判据 |
| `kredits.py` / `kredits_templates.py` | 费用的数字定位与模板匹配 |
| `hq_hp.py` | 总部血量的盾牌定位 + 数字模板 |
| `frontline_line.py` | 「前线是谁的」（那条黑线的相对偏移） |
| `ui_state.py` | 界面状态分类（按模板自己的 region 搜索） |
| `update_check.py` | 检测更新（只依赖标准库，可离线测） |
| `game_report.py` / `watch_log.py` | 只读工具：一局的对账报表、实时看日志 |

## 跑测试

**没有 pytest，也没有 CI。** 现状是「每个 `*_test.py` 自己跑自己，退出码 0 就是过」，
在仓库根目录执行：

```cmd
.venv\Scripts\python.exe dev\turn_logic_test.py
```

### 回归基线（离线，不需要游戏）

这些是**改代码前后都该跑的**，全绿才算没坏：

| 用例 | 覆盖什么 |
|---|---|
| `dev\turn_logic_test.py` | 回合状态机 + 部署判据 + 攻击规则。最大的一套，约 200 秒 |
| `dev\card_match_test.py` | 卡名五级匹配 + 费用徽章 + 指纹库，**含全卡库自检**（1558 条卡名各自认自己） |
| `dev\unit_state_test.py` | 费用徽章的橙/灰判据、假徽章守卫 |
| `dev\hq_hp_test.py` | 总部血量盾牌读取（**留一验证**：拿某帧当测试样本时先把它贡献的原型拿掉） |
| `dev\kredits_two_digit_test.py` | 两位数费用（真值帧，钉住「11 不能读成 1」） |
| `dev\scan_fast_test.py` | 直扫兜底与各条早退原因 |
| `dev\hand_memory_test.py` | 手牌记忆：命中 / 失效 / 失效后重新铺格子 |
| `dev\board_geom_test.py` | 战场几何：行结构、卡数与卡间距是否合理 |
| `dev\win_capture_test.py` | 截图管线判据（`PrintWindow` 空壳图的识别与退路选择） |
| `dev\gui_test.py` | 面板：勾选转参数、状态解析、日志着色、冻结路径、窗口几何 |
| `dev\actions_test.py` | 鼠标动作软着陆（喂假 `winapi`，不需要窗口） |
| `dev\update_check_test.py` | 检测更新的每条错误分支（不碰网络，`--live` 才真查） |

> ⚠️ **`shots\` 不在仓库里**（排查用的存帧，`.gitignore` 排掉了）。所以依赖真值帧的用例
> 在新 clone 上会报「缺样本帧」或「要对着窗口交互」—— 那是**预期结果**，不是回归。
> 这类用例的判据依赖作者本机的存帧，这也是目前没法上 CI 的原因。

### 需要游戏窗口

```cmd
.venv\Scripts\python.exe dev\selfcheck.py
```

单实例锁与截图管线需要真的有一个 KARDS 窗口在跑。

### 只读 A/B 工具（改判据时用）

改任何**图像判据**之前，先用它们量，别凭直觉：

| 工具 | 干什么 |
|---|---|
| `dev\badge_false_ab.py` | 费用徽章并集的新旧对照，输出「掉了哪些 / 多了哪些」联系表 |
| `dev\badge_old_vs_new.py` | 换判据时把「多收的」和「丢掉的」分别拼图 |
| `dev\badge_ctx_ab.py` | 徽章「亮卡面」判据只看右边 vs 上右下任一方向 |
| `dev\badge_miss_diag.py` | 某个徽章**为什么没被检出**：逐条列出它卡在哪条过滤上 |
| `dev\kredits_numeral_ab.py` | 费用数字隔离的新旧对照（624 帧语料） |
| `dev\state_roi_ab.py` | 界面状态识别：整帧匹配 vs 按 region 匹配 |
| `dev\hand_timing.py` | 手牌识别耗时拆解与裁剪窗口 A/B |
| `dev\hand_edge_ab.py` / `hand_layout_pick_ab.py` | 手牌边缘与布局条目挑选 |
| `dev\card_mask_ab.py` / `card_ab_shots.py` | 战场卡面检测的新旧对照（含差异帧画图） |
| `dev\guard_ab.py` | 守护标记判据在全语料上的命中与边界带 |
| `dev\ocr_ab.py` / `intercept_ab.py` / `memory_ab.py` | OCR 兜底、拦截规则输入侧、手牌记忆开关的对照 |

### 取证与现场排查

`dev\live_probe.py`（看当前是什么界面）、`field_probe.py`（战场读数）、`attack_probe.py`（攻击预检）、
`hand_live_probe.py`（手牌逐探针证据）、`hover_dump.py`（把整帧 OCR 的每一行连位置打出来）、
`board_frame_check.py`（单帧核对器）、`guard_probe.py`（把一帧的卡摊开看）、
`game_report.py`（一局的对账报表）、`watch_log.py`（终端里实时看日志，中文不乱码）。

其余带 `_probe` / `_diag` / `_timing` 后缀的都是一次性排查脚本，按需用。

## 改代码的几条纪律

这几条都是踩过坑之后定下来的，PR 里也按这个标准看：

1. **改判据之前先量，并且做 A/B。** 换判据一定会改变「收进来的集合」，所以必须把
   **多收的**和**丢掉的**都切出来看图；只看总数会同时掩盖「多了一堆假的」和「丢了一堆真的」。
   验收标准应当写成「只有该变的变了」。
2. **合成用例全绿 ≠ 能用。** 合成帧里画面只有你画的那几个元素，判据怎么加都能过 ——
   它证明的是「规则符合我自己画的图」，不是「符合游戏」。任何图像判据最后一步都要在
   **真实帧上逐帧计数**，并和一个已有判据做 A/B。
3. **失败路径必须把证据打进日志。** traceback、OCR 原文、拒绝原因、占用者 PID。
   项目里三个难查的 bug 全是靠「日志里正好有那条证据」才定位的；在补上证据之前只能猜。
4. **关键状态用不会骗人的账本记，视觉判据只用来纠偏。** 费用、位置、数量这些会影响后续
   所有决策的状态，用账本 + 计数维护；用容易误判的视觉信号去更新它们，会把一次误判放大成
   一整回合的乱来。
5. **改动要留 A/B 开关。** 形如 `SOMETHING_ENABLED = True`，一行就能退回老行为，
   并且注释里写清当初为什么这么定。
6. **写仓库里的文本文件不要用 PowerShell 的 `Set-Content -Encoding UTF8`** —— 它会写 BOM，
   而带 BOM 的 `config\app_version.json` 会让版本号**静默变成 `0.0.0`**（于是永远提示有新版本）。
   要么用编辑器，要么 `[System.IO.File]::WriteAllText($p, $s, [System.Text.UTF8Encoding]::new($false))`。
7. **改了 `src\gui.py` 就必须重打 exe**（`build_gui.bat`），否则用户看到的还是旧面板。
   改引擎（其它 `src\*.py`）不用重打。面板自检写 `logs\gui_selftest.txt`，可以用它确认
   新代码真的在 exe 里。
8. **别把「自己 debug 时画了标注的图」当评测集** —— 洋红框之类的标注会污染像素判据。

## 卡库（`card_db\kards_data.json`）

这是**运行时必需**的文件：`card_match.load_db()` 用它把 OCR 读到的卡名换成费用和类型。
目录名 2026-09 之前叫 `card_db_test\`，容易让人以为是可以删的测试夹具 —— 而 v0.1.2 的事故
正是发布包漏了它：引擎**不报错**，只是「卡名 → 费用」整条路悄悄失效，整局不出牌。
代码里对新旧两个目录名都做了兼容（先找 `card_db\`，找不到再退回 `card_db_test\`）。

| 项 | 情况 |
|---|---|
| 内容 | 1613 条卡牌节点，其中 1558 条有中文卡名；含 `title.zh-Hans` / `kredits` / `type` / `cardId` |
| 体积 | 约 3.1 MB |
| 来源 | 官网的 GraphQL 接口 `herokuapi.kards.com/graphql`（非公开接口） |
| 更新频率 | 大约一个多月一次，增量不大 |
| 版本线索 | 文件本身**没有快照时间**；只有 `imageUrl` 里带着 `/images/card/v52/` 这样的版本段 |

**目前仓库里没有能重建它的脚本**，这是个已知缺口。`src\archive\fetch_kards_card.py` 是早期的
单次搜索查询（每页 20 条、只往控制台打印、不写文件），要 dump 出全部节点得翻 81 页，它做不到；
它依赖的 `requests` 在 `requirements.txt` 里也是注释掉的（属于可选依赖）。

**欢迎的贡献**：写一个能重建卡库、并把抓取时间与接口版本写进文件头的脚本，顺便更新这一节。
在那之前，更新卡库只能整份替换这个文件，并在提 PR 时说明是什么时候抓的。

## 提交与 PR

- **提交信息用中文**，一行说清「改了什么 / 为什么」。多行时正文里放判据（日志原文、帧名、A/B 数字）。
- 提交粒度按「一件独立的事」拆，不要求 squash；PR 里保留有意义的提交。
- **改了行为就同步更新**：`CHANGELOG.md`（如果这次要发版）、受影响的文档。
  `config\app_version.json` **只在发版时**改，PR 里不要动。
- PR 描述里请写清：改了什么、**凭什么说它是对的**（哪条用例、哪批帧、A/B 前后差多少）、
  有没有留退回开关。没有判据的改动会被问。
- 大改动（尤其是识别判据、规则表）建议先开 issue 讨论，避免写完发现方向不对。

## 代码风格

目前**没有 ruff / black / isort 配置**，也不强制格式化。现状约定：

- 4 空格缩进，UTF-8，行宽不限制；
- 注释和 docstring 用中文，重点写**判据**和**踩过的坑**（这个仓库里注释比代码值钱）；
- 模块顶部写清「这个模块负责什么、不负责什么」；
- 新增的可调参数放在模块顶部的常量区，带一行说明和单位。

## 授权边界

项目本身是 **GPL-3.0**。但 `ui_templates\` 里那 41 张 PNG 是从游戏画面上裁下来的，
版权属于 1939 Games，**不在 GPL-3.0 的授权范围内**，提 PR 时不要往里加新的游戏素材。
要加模板请用 `dev\template_capture.py` 让使用者自己从本机游戏里录。细节见
[NOTICE.md](NOTICE.md)。

## 安全问题怎么报

公开 issue 里**不要贴**这几样东西：

- `config\panel_token.txt` 的内容（它相当于面板的访问口令，手机端带着 `?t=<这串>` 就能打开面板）；
- 完整的本机绝对路径、账号昵称、对局日志里的对手信息（`logs\` 和 `shots\` 都可能有）。

这些内容发之前先删掉或打码。如果发现的是**面板本身的漏洞**（例如 token 校验被绕过、
本机文件可被读取），请走私下渠道：在 issue 里只写「有一个安全问题想私下报」，
不要贴复现细节，作者会给你一个联系方式。

## 发布流程

发布由维护者做，步骤固定：

1. 确认离线用例全绿（上面那张表）；
2. 改 `config\app_version.json` 的版本号，更新 `CHANGELOG.md`，提交并打 tag；
3. **改了 `src\gui.py` 就先重打 exe**（`build_gui.bat`），并把 `dist\KARDS AUTO.exe`
   复制到项目根 —— 发布包要从那里取；
4. 跑 `make_release.py` 打 zip。它自带自检：结构、该排掉的（`.venv` / `logs` / `shots` /
   `panel_token.txt`）、以及**关键文件在不在**（`card_db\kards_data.json`、
   `config\kredits_digits\n_00_mask.png` 等）。历史上两次事故都是「发布包少文件、引擎静默变笨」，
   所以这份清单是必须维护的；
5. ★ **把 zip 解压到一个空目录再验一次**：版本号、`卡库：1558 张卡名`、`费用数字模板：10/10`。
   这几个 bug 在开发目录里怎么测都测不出来；
6. 到 GitHub 上新建 Release，选 tag、把 zip 传成附件（这一步要人手点）。
