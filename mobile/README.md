# 手机端 / Android 0.2.2

手机版独立维护，PC 发布包不包含 APK。[源码与构建说明](source/README.md)。

正式 **0.2.2 / versionCode 141** 已完成构建、签名、覆盖安装及 12 组设备检查，公开下载大小与 SHA-256 已核对。详情见[发布报告](../docs/reports/mobile/APK_0.2.2_RELEASE.md)。

## 下载与使用

- [KARDS-AUTO-Mobile-v0.2.2.apk](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.2/KARDS-AUTO-Mobile-v0.2.2.apk)位于同页 [v0.2.2 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.2)，下载后安装，无需解压。
- 最低 Android 11/API30，支持 arm64-v8a 和 x86_64。覆盖更新需要与已有安装使用相同签名；本次正式包的签名与升级验证结果见[发布报告](../docs/reports/mobile/APK_0.2.2_RELEASE.md)。
- 已内置 Python、NumPy/OpenCV、OCR 运行库和模型；运行无需 Windows、ADB、Termux、Shizuku 或另装 Python。
- 安装并登录 KARDS，在系统无障碍设置启用“KARDS 对战助手”。使用简体中文；**画质不限，内容比例设为“原生”，UI 比例调为 1**。
- 选择休闲/排位及局数，`0` 表示无限。可从菜单开始或接管当前对局。右侧悬浮条点击展开，展开继续运行，手动点击停止；截图及输入期间面板会临时隐藏。
- 每步按攻击、移动、部署的顺序选择。新截图证据按 350MiB 预算管理，优先淘汰最旧非活动局；活动帧仍需暂存空间，旧版本历史不会自动迁移清理。

## 本次改进

- 改善 16:9、宽屏及不同分辨率下的菜单、换牌和回合控件识别，根据当前文字与控件位置定位按钮。
- 修复部分登录奖励、促销弹窗和启动窗口切换导致的开局停滞。
- 识别“敌方正在选择起始手牌”并等待对手，避免确认换牌后重复点击或过早停止。
- 优化局部识别、画面复用和下一步规划，减少重复识别与无效等待；改善前线暂时识别不清时的回合超时问题。
- 优化游戏窗口截图、短暂遮挡处理和悬浮面板的窄屏布局。

开发验证中，code140 在 Android 15、1280×720 模拟器连续完成十局；code139 在 Android 15、2780×1264 实体手机连续完成五局。它们是不同测试包；正式 code141 的构建、安装和组件检查在[发布报告](../docs/reports/mobile/APK_0.2.2_RELEASE.md)单独记录，未把开发包对局记作正式包同哈希实测。

当前识别结合文字、模板、颜色和几何信息，其他设备及布局仍需实测。部分需要出牌后再选择目标的流程尚未完整支持；日志保留动作效果未知记录。额外模拟器截图检查仍有黑帧问题，浮窗相关检查尚未全过，详见发布报告。

## 历史版本

- [0.2.1 APK 直链](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.1/KARDS-AUTO-Mobile-v0.2.1.apk)及[0.2.1 验证报告/SHA-256](../docs/reports/mobile/APK_0.2.1_RELEASE.md)。
- 0.2.0 ZIP 与清单保留在[历史 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.0)。
