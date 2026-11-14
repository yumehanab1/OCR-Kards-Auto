# KARDS Android 0.2.3 / code153

手机版独立源码快照。Java 负责管理界面、无障碍服务、前台身份、取帧调度与触控回执；内置 Python/OpenCV 负责画面识别、动作选择与动作后验。OCR 模型、运行库、模板与内置引擎随 APK 提供，运行不需要 PC、ADB、Termux 或另装 Python。支持 `com.android1939.kards` 与 `com.android1939.kardsapk`。

## 安卓 10 适配

`minSdk=29`、`targetSdk=35`、`versionCode=153`，含 arm64-v8a 与 x86_64。

`AccessibilityService.takeScreenshot` 自 API30 才提供，API29 无法调用，因此截图通道按系统版本分流：API29 使用 `MediaProjection` 兼容截图（主界面启用并在系统弹窗授权屏幕共享），未授权时取帧返回 `android10_requires_compat_capture`；API30—33 使用系统显示截图，黑屏时可切兼容截图；API34 及以上使用游戏窗口截图。进程重启或授权撤销后需重新授权。

兼容截图在竖屏授权、横屏取帧时按当前显示几何调整虚拟屏尺寸，保留原授权，不再要求重新授权；离开游戏回到应用会暂停取帧，回到游戏继续。

高版本 API 与主路径隔离：`TakeScreenshotCallback`、`ScreenshotResult`、`HardwareBuffer` 集中在 `SystemScreenshot`，`getCurrentWindowMetrics` 集中在 `DisplayBounds$Api30`，调用方只按 `Build.VERSION.SDK_INT` 分支，API29 不加载这些类。`WindowInsets.Type`、`setDecorFitsSystemWindows` 在 API29 走旧 `getSystemWindowInset*()` 与默认 decor 处理；`DisplayBounds.get()` 在 API29 回退到 `Display.getRealMetrics()`，浮窗布局与游戏窗口判定共用同一边界。无障碍配置按资源目录拆分，默认 `res/xml/` 不含 API30+ 的 `canTakeScreenshot`，`res/xml-v30/` 才声明该能力。

## 运行准备

主界面「运行准备」列出无障碍权限、屏幕共享授权、后台运行、通知权限与游戏安装状态，每项右侧按钮直达对应的系统授权窗口。Android 10 上无障碍与屏幕共享为必需项；必需项未完成时开始按钮只跳授权，两个启动入口都不会创建会话。权限状态每秒刷新，授权返回后自动解除门控。准备页同时显示屏幕实际尺寸与宽高比，按横屏几何判断是否在支持区间；截图按原始分辨率读取后归一化到 1280×720 识别基准，支持 1.70—2.30 的横屏比例。「查看调试日志（详细）」打开全屏日志面板，记录权限状态、前台包名变化、每帧尺寸与通道、引擎事件与识别状态、会话失败原因、回放 JSON 与异常堆栈，可一键复制全部日志。

## 取帧与输入

截图不完整、黑帧及临时窗口错误共用最多三次新鲜重采，含首次最多四次采集。重采期间不触控，取消与原预算优先；持续异常停止，透明帧不计为有效帧。坏帧 PNG 的有界异步诊断只在 debug 包开启。

浮窗隐藏时保留窗口附着，用透明度与不可触控标记避免反复重建；战斗、菜单和结算共用原子派发边界，准备阶段超时的任务不能迟到提交输入。“仅启动辅助 · 手动打开游戏”不依赖安装探测，可先待命再手动打开游戏；自动打开仍解析游戏启动 Intent 并校验真实游戏前台。

## 识别提速

模板匹配把亮度 NCC 从 step4 coarse + step1 refine 改为 step8 → step4 → step2 → step1 金字塔搜索，低分回退全扫描，并预计算各尺度统计量、用 `long` 累加相关系数；282 帧合成样本 0.731ms 对 2.923ms，植入模板命中 276 对 265。`Objects` 用 float32 归一化矩阵点积替代逐个 `cv2.matchTemplate`；`Guards` 缓存按尺度生成的模板变体；`Detector` 复用形态学 kernel、HSV 与轮廓结果，去掉重复 `cvtColor`/`inRange`；`MulliganRecognizer` 由逐像素 `getPixel` 改为一次 `getPixels`。

## 诊断

「工具与诊断」里的只读观察回路切到 KARDS 后继续运行，可在游戏前台持续输出识别状态；「回放保存 PNG」接受任意受支持比例的 PNG 并输出识别 JSON 与保存路径。菜单页与对局页是靠资源栏、木质棋盘等锚点区分的：主界面判为 `NON_GAME`，对局内才授权动作，锚点不足时返回 `UNKNOWN` 并给出原因。

开始页的模式列表在灰度模板上「选中」与「未选中」几乎同分，选中项只靠橙色高亮区分，因此当前模式由各行橙色像素数判定，再决定是点模式还是点卡组；该判定对所有横屏比例生效，不限于 16:9。

## 已知边界

识别结合文字、模板、颜色和几何信息，其他设备与布局仍需实测。
