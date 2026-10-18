# 手机端 / Android 0.2.3

手机版独立维护，PC 发布包不包含 APK。[源码与构建说明](source/README.md)。

正式版本为 **0.2.3 / versionCode 148**，本次增加旧安卓系统可选兼容截图及有限新鲜重采，减少黑帧和透明帧导致的识别停滞。正式包验证与 code147 开发包同包十局分别记录，详情见[发布报告](../docs/reports/mobile/APK_0.2.3_RELEASE.md)。

正式包构建、签名、覆盖安装、12组设备发布检查及78项截图专项和浮窗状态组已通过；无认证公开下载的大小与SHA-256已核对。

## 下载与使用

- [KARDS-AUTO-Mobile-v0.2.3.apk](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.3/KARDS-AUTO-Mobile-v0.2.3.apk)位于同页 [v0.2.3 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.3)，下载后安装，无需解压。
- 最低 Android 11/API30，支持 arm64-v8a 和 x86_64。覆盖更新需要与已有安装使用相同签名；本次正式包的签名与升级验证结果见[发布报告](../docs/reports/mobile/APK_0.2.3_RELEASE.md)。
- 已内置 Python、NumPy/OpenCV、OCR 运行库和模型；运行无需 Windows、ADB、Termux、Shizuku 或另装 Python。
- 安装并登录 KARDS，在系统无障碍设置启用“KARDS 对战助手”。使用简体中文；**画质不限，内容比例设为“原生”，UI 比例调为 1**。
- Android 14 及以上使用游戏窗口截图。Android 11—13 若系统截图黑屏，可在助手主界面启用“兼容截图”，亲自在系统屏幕共享弹窗确认后返回游戏。进程重启或授权撤销后需要重新授权；部分 MuMu 环境还需处理助手虚拟屏旋转，适用范围见发布报告。
- 选择休闲/排位及局数，`0` 表示无限。可从菜单开始或接管当前对局。右侧悬浮条点击展开，展开继续运行，手动点击停止；截图及输入期间面板会临时隐藏。
- 每步按攻击、移动、部署的顺序选择。新截图证据按 350MiB 预算管理，优先淘汰最旧非活动局；活动帧仍需暂存空间，旧版本历史不会自动迁移清理。

## 本次改进

- 增加 Android 11—13 可选兼容截图通道，在系统无障碍截图黑屏时使用。
- 黑帧、不完整透明帧在进入识别前拒绝，不再当作普通“画面未知”。
- 对不完整帧、黑帧及临时窗口错误共用最多三次新鲜重采；重采期间不触控，取消和原预算仍优先，持续失败仍停止。
- 浮窗说明重试及耗尽原因；保留前台、新鲜度、几何、触控回执和动作后验条件。

code147 开发包在 API32、1280×720 MuMu 同一会话连续完成十局，2胜8负，用时1小时8分46.633秒；21次已记录缺图均一次重采恢复，没有因此中断。code148 是新的正式构建，其验证范围在[发布报告](../docs/reports/mobile/APK_0.2.3_RELEASE.md)单独记录，不把开发包十局记作正式包同哈希实测。

当前识别结合文字、模板、颜色和几何信息，其他设备及布局仍需实测。部分出牌后再选战场目标的流程尚未完整支持；十局普通效果未知67次、结束未确认1次原样保留。连续完成不表示每个动作效果均已验证，也不证明胜率提升。模拟器底层透明来源及 OBS 黑屏尚未确定，不能推断所有截图和浮窗路径都已修复。

## 历史版本

- [0.2.2 APK 直链](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.2/KARDS-AUTO-Mobile-v0.2.2.apk)及[0.2.2 验证报告/SHA-256](../docs/reports/mobile/APK_0.2.2_RELEASE.md)。
- [0.2.1 APK 直链](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.1/KARDS-AUTO-Mobile-v0.2.1.apk)及[0.2.1 验证报告/SHA-256](../docs/reports/mobile/APK_0.2.1_RELEASE.md)。
- 0.2.0 ZIP 与清单保留在[历史 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.0)。
