# 手机端 / Android 0.2.4

当前手机版 **0.2.4 / versionCode 191**。本次只更新 Android；Windows 继续使用 [PC 0.2.3](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.3)。

[下载 KARDS-AUTO-Mobile-v0.2.4.apk](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.4/KARDS-AUTO-Mobile-v0.2.4.apk) · [发布页](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.4) · [本次更新与验证](releases/0.2.4.md) · [源码与构建](source/README.md)

## 下载与使用

1. 最低 Android 11/API30，支持 arm64-v8a 和 x86_64。直接安装 APK，无需解压；原签名的旧版可直接覆盖更新，不要先卸载。安装了不同签名自编译包时，系统不会允许直接覆盖。运行无需 Windows、ADB、Termux、Shizuku 或另装 Python。
2. 安装并登录 KARDS。建议游戏用简体中文、内容比例设为“原生”、UI 比例 1；助手需启用系统无障碍权限。必要时在助手里选择已安装的游戏。
3. Android 14+ 使用游戏窗口截图。Android 11–13 若默认截图黑屏，可在助手主界面启用“兼容截图”，并亲自在系统弹窗确认屏幕共享；撤销或进程重新启动后需重新授权。
4. 选休闲/排位及局数（`0` 表示持续运行）。可从助手打开游戏，或选“仅启动辅助 · 手动打开游戏”再自行切过去。先确认人在场、游戏位于前台；有异常可从悬浮控制条停止。自动化可能触发游戏检测，不建议无人值守长时运行。
5. 内置更新检查的版本打开助手时会尝试查询发行版本；未看到提示可使用上面的固定下载链接。

## 已知限制

- 部分 4:3 布局的**可领取**奖励页可能无法自动越过；请手动处理后先返回真正的游戏主页。此页不是本版改善的“已领取/返回”提示页。
- 正式包的覆盖安装和组件检查、开发包的对局证据分别记录，不表示每个动作都确认或实体手机长期稳定。部分需要二次选目标的出牌仍不完整。

历史：[0.2.3 手机版](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.3/KARDS-AUTO-Mobile-v0.2.3.apk) · [0.2.3 验证](../docs/reports/mobile/APK_0.2.3_RELEASE.md) · [0.2.2 验证](../docs/reports/mobile/APK_0.2.2_RELEASE.md) · [0.2.1 验证](../docs/reports/mobile/APK_0.2.1_RELEASE.md)。
